import json
import re
import sqlite3
from .meal_rules import CRITERIA_VERSION,KEYS,NEUTRAL,parse_rules,validate_values,display_value
from .store import now


def infer_mode(text):
    return 'update' if re.search(r'改成|改为|改到|还是|仍然|仍旧|保持|不变|只改|继续沿用',text) else 'replace'


def normalized_extraction(text,model_updates=None):
    rules=parse_rules(text)
    if rules['unsupported']:raise ValueError('；'.join(rules['unsupported']))
    values={};quotes={}
    for item in model_updates or []:
        k=item.get('key');v=item.get('value');q=item.get('quote','')
        if k not in KEYS or not q or q not in text:continue
        if k.endswith('_exclusive'):continue
        if k in ['min_spice','max_spice','meal_period','recommend_count'] and k not in rules['updates']:continue
        # Numerical quotes must actually support the extracted number.
        if k in ['budget','kcal_min','kcal_max','recommend_count']:
            numbers=[float(x) for x in re.findall(r'\d+(?:\.\d+)?',q)]
            if not numbers:
                digits={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
                for cn in re.findall(r'[零〇一二两三四五六七八九十百千万]+',q):
                    total=0;section=0;n=0
                    for char in cn:
                        if char in digits:n=digits[char]
                        elif char=='万':total+=(section+n)*10000;section=0;n=0
                        else:section+=(n or 1)*{'十':10,'百':100,'千':1000}[char];n=0
                    numbers.append(total+section+n)
            if v not in numbers:continue
        values[k]=v;quotes[k]=q
    values.update(rules['updates']);quotes.update(rules['quotes'])
    for k in rules['clear_keys']:values.pop(k,None);quotes.pop(k,None)
    validate_values(values)
    return values,quotes,rules['clear_keys']


def persist_profile(engine,run,user,session,values,origins,title,*,mode,source_id=None,base_notes=None,repaired_from=None,activate=True):
    store=engine.store
    old={n['payload']['key']:n for n in base_notes or []}
    rules=[n for n in (base_notes or store.heads(user,'note')) if not n['payload'].get('condition')]
    notes=list(rules);created=[]
    for key,value in values.items():
        origin=origins[key];prev=old.get('meal.'+key)
        if mode=='update' and prev and prev['payload'].get('typed_value')==value and prev['payload'].get('criteria_version')==CRITERIA_VERSION:
            notes.append(prev);continue
        n=store.add(user,2,'note',KEYS[key],f'{KEYS[key]}：{display_value(key,value)}',refs=[origin['id']],
            evidence=[{'id':origin['id'],'quote':origin['quote']}],key='meal.'+key,condition=key,typed_value=value,
            topic='meal_preferences',version=prev['payload'].get('version',1)+1 if prev else 1,
            supersedes=prev['id'] if mode=='update' and prev else None,criteria_version=CRITERIA_VERSION,run_id=run)
        notes.append(n);created.append(n['id'])
    reps=[]
    for topic,name in [('meal_rules','数据库与热量规则'),('meal_preferences','当前餐次与饮食条件')]:
        ns=[n for n in notes if n['payload'].get('topic')==topic]
        if not ns:continue
        r=store.add(user,3,'representation',name,'\n'.join(f"- {n['content']} [{n['id']}]" for n in ns)+
            ('\n- 未设置的条件不从其它记忆借用。' if topic=='meal_preferences' else ''),refs=[n['id'] for n in ns],
            topic=topic,criteria_version=CRITERIA_VERSION,compiler='有来源的确定性主题编译',run_id=run)
        reps.append(r);created.append(r['id'])
    if activate:
        heads=[('note',n['payload']['key'],n['id']) for n in notes]
        heads.extend(('representation',r['payload']['topic'],r['id']) for r in reps)
        store.replace_heads(user,heads,clear=('note','representation'))
    saved=engine.conversations.save(user,title,notes,reps,session=session,criteria_version=CRITERIA_VERSION,
        save_mode=mode,source_record_id=source_id,repaired_from=repaired_from)
    engine.step(run,'保存经过语义校准的偏好',{'save_mode':mode,'source':source_id},
        {'memory_id':saved['id'],'conditions':values,'unspecified':[k for k in KEYS if k not in values],
         'policy':'未设条件不继承，喜欢辣要求有辣，餐次隔离'},created,3)
    return saved,created


def migrate_legacy(engine):
    """Non-destructive repair from original records; never rewrite historical answers or notes."""
    store=engine.store
    with store.connect() as c:
        rows=c.execute('SELECT * FROM meal_memories ORDER BY rowid').fetchall()
        repaired={r[0] for r in c.execute('SELECT old_id FROM meal_memory_repairs')}
    legacy=[dict(r) for r in rows if json.loads(r['payload']).get('criteria_version',0)<CRITERIA_VERSION and r['id'] not in repaired]
    if not legacy:return []
    backups=engine.db.root/'backups';backups.mkdir(parents=True,exist_ok=True)
    backup=backups/('memory-before-criteria-v2-'+now().replace(':','-')+'.sqlite3')
    with store.connect() as src,sqlite3.connect(backup) as dest:src.backup(dest)
    results=[]
    for raw in legacy:
        p=json.loads(raw['payload']);user=raw['user_id']
        allowed={o['id']:o for o in store.objects(user)}
        ids=set(p.get('training_ids',[]))
        if p.get('source_record_id'):ids.add(p['source_record_id'])
        candidates=[o for o in allowed.values() if o['kind']=='user_message' and o['title']=='选餐条件原话'
                    and o['created_at']<=raw['created_at'] and o['session']==p.get('source_session')]
        if candidates:ids.add(candidates[-1]['id'])
        records=[o for o in allowed.values() if o['id'] in ids and o['kind']=='user_message']
        run=store.start(user,'repair_memory',p.get('source_session'),{'old_memory_id':raw['id'],'backup':str(backup)})
        try:
            values={};origins={};latest=None
            for t in records:
                fallback=[]
                for nid in p.get('note_ids',[]):
                    n=allowed.get(nid)
                    if n and n['payload'].get('condition') in KEYS:
                        for ev in n['payload'].get('evidence',[]):
                            if ev.get('id')==t['id']:fallback.append({'key':n['payload']['condition'],'value':n['payload']['typed_value'],'quote':ev['quote']})
                updates,quotes,clear=normalized_extraction(t['content'],fallback)
                if not updates:continue
                mode=t['payload'].get('save_mode') or infer_mode(t['content'])
                if updates.get('meal_period') and values.get('meal_period','any') not in ['any',updates['meal_period']]:mode='replace'
                if mode=='replace':values={};origins={}
                for key in clear:values.pop(key,None);origins.pop(key,None)
                values.update(updates);origins.update({k:{'id':t['id'],'quote':quotes[k]} for k in updates});latest=t
            if not values or not latest:raise ValueError('旧记忆缺少可核验的原始偏好，请重新保存明确条件。')
            validate_values(values)
            base=[allowed[i] for i in p.get('note_ids',[]) if i in allowed]
            saved,created=persist_profile(engine,run,user,None,values,origins,raw['title'],mode='replace',
                source_id=latest['id'],base_notes=base,repaired_from=raw['id'],activate=False)
            with store.connect() as c:
                c.execute('INSERT INTO meal_memory_repairs VALUES(?,?,?,?,?)',(raw['id'],saved['id'],user,'由原话重新核验，已修正旧条件继承与辣度语义',now()))
                c.execute('UPDATE meal_sessions SET memory_id=? WHERE user_id=? AND memory_id=?',(saved['id'],user,raw['id']))
            store.finish(run,{'old_memory_id':raw['id'],'memory_id':saved['id'],'conditions':values,'artifacts':created})
            results.append(saved['id'])
        except Exception as exc:
            with store.connect() as c:c.execute('INSERT INTO meal_memory_repairs VALUES(?,?,?,?,?)',(raw['id'],None,user,str(exc)[:500],now()))
            store.finish(run,error=str(exc))
    return results
