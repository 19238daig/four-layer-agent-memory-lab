"""Persistent memory, fresh-conversation comparison with independently checked conditions."""
import hashlib
import json
import os
import re
import time
import httpx
from .config import MODEL,BASE_URL,MODEL_EXTRA_BODY
from .llm import safe_error
from .meal_db import QUERY,DEFAULTS,PREFIX,FORMULA
from .meal_engine import KEYS
from .store import now
from .meal_rules import CRITERIA_VERSION,NEUTRAL,GENERIC_NAMES,assert_meal_matches,qualifying_offer,verified_answer,parse_rules


class TaggedStore:
    def __init__(self,store,mode):self.store,self.mode=store,mode
    def __getattr__(self,key):return getattr(self.store,key)
    def event(self,run,event_type,data):return self.store.event(run,event_type,{**data,'comparison_mode':self.mode})


def usage_totals(responses):
    usages=[r.get('usage') or {} for r in responses]
    values=[u.get('total_tokens') for u in usages if isinstance(u.get('total_tokens'),(int,float))]
    return dict(total_tokens=sum(values) if values else None,reported_calls=len(values),
        unreported_calls=len(responses)-len(values),token_measurement='provider' if len(values)==len(responses) and values else 'partial' if values else 'unavailable')


def compile_agent_sql(sql):
    sql=sql.strip()
    if re.match(r'^SELECT\s+\*\s+FROM\s+evaluated\b',sql,re.I):
        return PREFIX+'-- Deep Agents 生成最终SELECT；工具复用已核验CTE。\n'+sql
    return sql


def verification(expected,actual,note_refs,*,loaded):
    checks=[dict(key=k,label=KEYS[k],expected=v,actual=actual.get(k),matched=actual.get(k)==v,
                 source_note_id=note_refs.get(k)) for k,v in expected.items() if k in KEYS]
    return dict(checks=checks,passed=bool(checks) and all(c['matched'] for c in checks),
                memory_loaded=loaded,conclusion='值一致仅表示参数匹配；无记忆对照即使相同也不算跨会话记忆证据。' if not loaded else '检查实际SQL参数是否匹配选定记忆与本轮明确覆盖。')


def compare_meals(engine,run,d):
    user=d['user'];question=d['text'];store=engine.store
    s,memory,notes,reps=engine.conversations.view(user,d['session'])
    if not memory:raise ValueError('请先选择一份保存的记忆，或保存当前偏好后比较。')
    if memory.get('validation_warning') or memory['payload'].get('criteria_version',0)<CRITERIA_VERSION:raise ValueError('这份记忆尚未完整核验，请重新保存明确条件。')
    assert_meal_matches(memory['payload']['conditions'],question)
    if parse_rules(question)['unsupported']:raise ValueError('；'.join(parse_rules(question)['unsupported']))
    records=[store.get(i,user) for i in memory['payload']['training_ids']]
    records=[r for r in records if r]
    if not records:raise ValueError('所选记忆没有原始学习消息。')
    root=engine.db.root/'comparisons'/run
    snapshot=engine.db.snapshot(root)
    expected={**NEUTRAL,**memory['payload']['conditions']}
    refs={n['payload']['condition']:n['id'] for n in notes if n['payload'].get('condition')}
    modes=['four_layer','deepagents']+(['stateless'] if d.get('include_baseline',True) else [])
    config=dict(question=question,source_session=s['id'],memory_id=memory['id'],memory_title=memory['title'],
        expected_conditions=expected,training_ids=[r['id'] for r in records],fresh_learn=d.get('fresh_learn',False),
        model=MODEL,criteria_version=CRITERIA_VERSION,note='各分支均新会话，无上一会话聊天全文；四层直接加载保存版本，Deep Agents首次学习文件、之后复用。无记忆组使用明确标注的演示默认值。')
    engine.step(run,'跨会话记忆对比配置',config,{'database_snapshot':str(snapshot.path),'modes':modes})
    rows=[]
    for mode in modes:
        started=time.perf_counter();before=len(store.events(run_id=run))
        store.event(run,'comparison_branch_started',dict(mode=mode,started_at=now()))
        try:
            if mode in ['stateless','four_layer']:
                from .meal_engine import MealEngine
                child=MealEngine(snapshot,store=TaggedStore(store,mode),recover=False)
                conversation=child.conversations.create(user,'__compare__'+mode,memory['id'] if mode=='four_layer' else '')
                data=dict(user=user,session=conversation['id'],text=question)
                plan=child.do_generate(run,data)
                if plan['ambiguous']:raise ValueError('菜名存在歧义，请先在工作台明确菜名后比较。')
                result=child.do_execute_sql(run,{**data,'plan_id':plan['plan_id']})
                # Explicit current-question constraints take precedence over saved preferences.
                if mode=='four_layer':
                    expected.update(plan.get('overrides',{}))
                    for key in plan.get('overrides',{}):refs.pop(key,None)
                row=dict(mode=mode,status='complete',answer=result['answer'],counts=result['counts'],audited=result['audited'],
                    sql=plan['sql'],params=plan['params'],approved=result['approved'],result_id=result['result_id'],
                    context_id=plan['context_id'],conversation_id=conversation['id'],memory_id=memory['id'] if mode=='four_layer' else None,
                    memory_loaded=mode=='four_layer',persistent_memory_reused=mode=='four_layer',learning_model_calls=0,criteria_version=CRITERIA_VERSION,
                    memory_file='\n\n'.join(x['content'] for x in reps) if mode=='four_layer' else '未加载个人记忆；使用演示默认参数。')
            else:row=deep_run(engine,run,records,question,snapshot,memory,user,fresh=d.get('fresh_learn',False))
            row['verification']=verification(expected,row['params'],refs,loaded=mode!='stateless')
            if mode!='stateless' and not row['verification']['passed']:
                row['model_answer']=row.get('answer','');row['answer']='本组未正确使用所选记忆，已拦截推荐。请展开条件明细查看差异；没有把错误结果标为记忆成功。';row['approved']=[]
            # All conditions in the known version, including missing ones, are evaluated here.
            canonical=snapshot.canonical(row['params'])
            row['all_candidate_counts']={status:sum(r['status']==status for r in canonical['rows']) for status in ['pass','fail','uncertain','unknown']}
        except Exception as exc:row=dict(mode=mode,status='failed',error=safe_error(exc))
        events=store.events(run_id=run)[before:]
        responses=[e['data'] for e in events if e['type']=='model_response']
        learning=[r for r in responses if r.get('stage')=='learning']
        answering=[r for r in responses if r.get('stage')!='learning']
        row.update(elapsed_ms=round((time.perf_counter()-started)*1000),model_calls=len(responses),
            learning_model_calls=sum(r.get('stage')=='learning' for r in responses),
            answer_model_calls=sum(r.get('stage')!='learning' for r in responses),
            tool_calls=sum(e['type']=='deepagents_tool' and e['data'].get('phase')=='start' for e in events),
            learning_tokens=usage_totals(learning)['total_tokens'] if learning else 0,
            answer_tokens=usage_totals(answering)['total_tokens'],**usage_totals(responses))
        rows.append(row);store.event(run,'comparison_result',row)
    return dict(comparison=rows,config=config,database_snapshot=str(snapshot.path),question=question,
                message='比较已结束：分别核对SQL计算、实际条件和跨会话记忆来源。')


def deep_run(engine,run,records,question,db,memory,user,*,fresh=False):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_openai import ChatOpenAI
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.tools import tool
    from langchain_core.messages import HumanMessage
    from .file_checkpoint import FileCheckpoint

    fingerprint=hashlib.sha256(json.dumps(dict(criteria_version=CRITERIA_VERSION,user=user,model=MODEL,notes=memory['payload']['note_ids'],
        records=[(r['id'],r['content']) for r in records]),sort_keys=True).encode()).hexdigest()
    profile=(db.root/'fresh-profile') if fresh else (engine.db.root/'deep_memory'/fingerprint[:24])
    profile.mkdir(parents=True,exist_ok=True)
    manifest=profile/'manifest.json';profile_memory=profile/'AGENTS.md'
    cached=False
    if manifest.is_file() and profile_memory.is_file():
        try:
            saved=json.loads(manifest.read_text(encoding='utf-8'))
            cached=saved['fingerprint']==fingerprint and saved['sha256']==hashlib.sha256(profile_memory.read_bytes()).hexdigest()
        except (ValueError,KeyError):pass
    store=engine.store;executions=[];phase={'name':'learning'};rejected=[];source_reads=[];query_retries=[]
    reference={**NEUTRAL,**memory['payload']['conditions']}
    question_rules=parse_rules(question);reference.update(question_rules['updates'])
    for key in question_rules['clear_keys']:reference[key]=NEUTRAL[key]

    @tool
    def read_saved_memory_sources() -> str:
        """按需回查这份记忆保存时的用户原话及来源ID，不读取其它会话聊天。用于核对文件摘要遗漏的条件。"""
        source_reads.append(True)
        engine.step(run,'Deep Agents · 按需回查保存的偏好原话',{'memory_id':memory['id']},
            {'source_ids':[r['id'] for r in records]},[r['id'] for r in records],1)
        return json.dumps([{'id':r['id'],'text':r['content'],'save_mode':r['payload'].get('save_mode','replace')} for r in records],ensure_ascii=False)

    @tool
    def inspect_meal_database() -> str:
        """读取本次独立模拟库结构、公式模板和参数说明，不访问其他数据库。"""
        return json.dumps(dict(schema=db.schema(),formula=FORMULA,verified_cte_applied_by_tool=True,
            verified_query_template="SELECT * FROM evaluated ORDER BY CASE status WHEN 'pass' THEN 0 WHEN 'uncertain' THEN 1 ELSE 2 END, price, offer_id LIMIT :limit;",
            result_columns=['offer_id','offer_name','price','hot_lv','kcal_lo','kcal_hi','status','reason'],neutral_unspecified=NEUTRAL,
            instructions='依据AGENTS.md和当前问题传参。喜欢辣要求min_spice=1,max_spice=2；能吃辣只允许，min=0,max=2；不辣min=max=0；只吃微辣min=max=1。未设热量下限用0，上限未设用10000，未设预算用10000。餐次meal_period必须为breakfast/lunch/dinner/any。SQL只需 SELECT * FROM evaluated，可添加WHERE和ORDER BY。工具拼接相同公式CTE，不要重写公式。'),ensure_ascii=False)

    @tool
    def run_meal_sql(sql:str,budget:float,kcal_min:float,kcal_max:float,min_spice:int,max_spice:int,meal_period:str,recommend_count:int=3,name:str='') -> str:
        """生成最终 SELECT * FROM evaluated 并只读执行；工具拼接核验CTE。参数从已保存记忆获取，返回真实结果与来源。"""
        params={**DEFAULTS,'budget':budget,'kcal_min':kcal_min,'kcal_max':kcal_max,'min_spice':min_spice,'max_spice':max_spice,'meal_period':meal_period,'recommend_count':recommend_count,'name':name}
        for key in ('kcal_min_exclusive','kcal_max_exclusive'):
            params[key] = reference.get(key,0)
        if not(0<=budget<=10000 and 0<=kcal_min<=kcal_max<=10000 and min_spice in [0,1,2] and max_spice in [0,1,2] and min_spice<=max_spice and meal_period in ['any','breakfast','lunch','dinner'] and 1<=recommend_count<=10):return '参数无效，请检查辣度范围、餐次和热量上下限。'
        differences=[k for k,v in reference.items() if k in KEYS and params.get(k)!=v]
        if differences:
            rejected.append(differences)
            store.event(run,'deepagents_condition_rejected',{'keys':differences,'actual':params,'comparison_mode':'deepagents'})
            return json.dumps({'error':'条件未通过校验，尚未执行查询','mismatched_keys':differences,
                'next_action':'请重新读取AGENTS.md，必要时调用read_saved_memory_sources回查原话，再自行修正参数。recommend_count是用户要的推荐数量，不是SQL候选条数；未设下限不得自行增加。'},ensure_ascii=False)
        if name in GENERIC_NAMES:params['name']=''
        elif name and name not in question:return '菜名必须来自当前问题，不能根据菜单自行增加名称筛选。'
        try:
            agent_sql=sql;sql=compile_agent_sql(sql)
            result=db.query(sql,params);canonical=db.canonical(params);by={r['offer_id']:r for r in canonical['rows']}
            audited=all(r.get('offer_id') in by and r==by[r['offer_id']] for r in result['rows']) and result['columns']==canonical['columns']
            if audited and not any(r['status']=='pass' for r in result['rows']) and any(r['status']=='pass' for r in canonical['rows']):
                return "查询额外过滤掉了符合条件的候选，请使用 SELECT * FROM evaluated WHERE status='pass' ORDER BY price,offer_id LIMIT :limit; 不要擅自添加条件。"
            counts={s:sum(r.get('status')==s for r in result['rows']) for s in ['pass','fail','uncertain','unknown']} if audited else {}
            eligible=[r for r in result['rows'] if r.get('status')=='pass'] if audited else []
            if any(not qualifying_offer(r,params) for r in eligible):raise ValueError('候选与实际条件不符，已拦截。')
            approved=db.recommend(eligible,params)
            canonical_choices=db.recommend([r for r in canonical['rows'] if r['status']=='pass'],params)
            if audited and {r['offer_id'] for r in approved}!={r['offer_id'] for r in canonical_choices}:
                query_retries.append(True)
                store.event(run,'deepagents_query_rejected',{'reason':'查询过早截断或额外过滤，遗漏优先主餐或不同菜品','comparison_mode':'deepagents'})
                return "SQL提前截断或额外筛选导致遗漏主餐/不同菜品。请执行 SELECT * FROM evaluated ORDER BY CASE status WHEN 'pass' THEN 0 ELSE 1 END,price,offer_id LIMIT :limit; 工具从完整候选中优先主餐、标准份并去重，recommend_count只控制展示数，不要把它作为SQL的LIMIT。"
            snap=store.add(user,1,'deep_sql_result','Deep Agents SQL结果',json.dumps(result,ensure_ascii=False),
                run_id=run,sql=sql,agent_sql=agent_sql,params=params,audited=audited,db_path=str(db.path),result=result)
            record=dict(sql=sql,params=params,counts=counts,approved=approved,audited=audited,result_id=snap['id'])
            executions.append(record)
            return json.dumps({**record,'sql':'详见运行轨迹','rejected_sample':[r for r in result['rows'] if r.get('status')!='pass'][:4],
                'next_action':'根据已核验结果回答，不必再查库。' if audited else '这是探索结果，不能用于推荐。请调用 SELECT * FROM evaluated WHERE status=\'pass\' ORDER BY price,offer_id LIMIT :limit; 工具会拼接完整公式CTE，不要自己重写。'},ensure_ascii=False)
        except Exception as exc:return safe_error(exc)

    class Audit(BaseCallbackHandler):
        def on_chat_model_start(self,serialized,messages,**kwargs):
            store.event(run,'model_request',dict(purpose='Deep Agents · '+phase['name'],stage=phase['name'],model=MODEL,
                messages=[[dict(role=m.type,content=m.content) for m in g] for g in messages],comparison_mode='deepagents'))
        def on_llm_end(self,response,**kwargs):
            m=response.generations[0][0].message
            store.event(run,'model_response',dict(purpose='Deep Agents · '+phase['name'],stage=phase['name'],content=m.content,
                usage=getattr(m,'usage_metadata',None),tool_calls=getattr(m,'tool_calls',[]),comparison_mode='deepagents'))
        def on_tool_start(self,serialized,input_str,**kwargs):store.event(run,'deepagents_tool',dict(phase='start',stage=phase['name'],tool=(serialized or {}).get('name'),input=input_str))
        def on_tool_end(self,output,**kwargs):store.event(run,'deepagents_tool',dict(phase='end',stage=phase['name'],output=str(output)))

    model=ChatOpenAI(model=MODEL,base_url=BASE_URL,api_key=os.getenv('OPENAI_API_KEY'),temperature=0.1,max_tokens=10000,
        timeout=90,max_retries=1,stream_usage=False,http_client=httpx.Client(trust_env=False),extra_body=MODEL_EXTRA_BODY)
    system='本地选餐演示。学习阶段保存明确条件与来源到/AGENTS.md。独立保存时先清除旧个人条件；修改时仅保留未清除的字段。喜欢辣必须有辣(min=1,max=2)，能吃辣是允许(min=0,max=2)，不吃辣min=max=0，只吃微辣min=max=1。上限不等于范围，没设下限就是0；未设上限或预算使用10000。餐次分别记录，不混用午饭和晚饭条件。学习阶段不查询。回答时只加载记忆和当前问题，以新线程inspect_meal_database后run_meal_sql查询，不改记忆。不得访问其他数据库。'
    def agent_for(root,saver):
        return create_deep_agent(model=model,backend=FilesystemBackend(root_dir=str(root),virtual_mode=True),
            checkpointer=saver,memory=['/AGENTS.md'],tools=[inspect_meal_database,run_meal_sql,read_saved_memory_sources],subagents=[],system_prompt=system)
    try:
        if not cached:
            profile_memory.write_text('# 饮食记忆\n尚未学习。\n',encoding='utf-8')
            with FileCheckpoint(profile/'learning.json') as saver:
                agent=agent_for(profile,saver)
                for i,r in enumerate(records):
                    from .meal_preferences import infer_mode
                    mode=r['payload'].get('save_mode') or infer_mode(r['content'])
                    clear=list(parse_rules(r['content'])['clear_keys'])
                    agent.invoke({'messages':[HumanMessage(content=f'保存方式：{mode}（replace为独立保存，先清除旧个人偏好；update为修改）。明确清除字段：{clear}。学习但暂不推荐：'+r['content']+' 来源：'+r['id'])]},
                        config={'configurable':{'thread_id':f'{run}-learn-{i}'},'callbacks':[Audit()],'recursion_limit':28})
                    engine.step(run,'Deep Agents · 学习写入记忆文件',{'source':r['id']},{'content':profile_memory.read_text(encoding='utf-8')},[r['id']])
            manifest.write_text(json.dumps(dict(fingerprint=fingerprint,sha256=hashlib.sha256(profile_memory.read_bytes()).hexdigest(),source_memory_id=memory['id'])),encoding='utf-8')
        learned=profile_memory.read_text(encoding='utf-8')
        # Copy only the persisted memory file; a fresh checkpoint contains no previous conversation.
        answer_root=db.root/'deep-answer';answer_root.mkdir(exist_ok=True)
        (answer_root/'AGENTS.md').write_text(learned,encoding='utf-8')
        phase['name']='new_session'
        context=store.add(user,4,'deep_memory_context','Deep Agents新会话加载的持久记忆',learned,
            refs=memory['payload']['training_ids'],run_id=run,memory_id=memory['id'],persistent_memory_reused=cached,
            memory_path=str(profile_memory),previous_session_history_injected=False)
        engine.step(run,'Deep Agents · 新会话复用磁盘记忆',{'memory_id':memory['id'],'cached':cached},
            {'path':str(profile_memory),'content':learned,'context_id':context['id'],'previous_session_messages':0},[context['id']],4)
        conversation_id=f'deep-answer-{run}'
        with FileCheckpoint(answer_root/'fresh-checkpoints.json') as saver:
            result=agent_for(answer_root,saver).invoke({'messages':[HumanMessage(content=question)]},
                config={'configurable':{'thread_id':conversation_id},'callbacks':[Audit()],'recursion_limit':32})
        verified=[e for e in executions if e['audited']]
        if not verified:raise ValueError('Deep Agents未成功执行可核验SQL，实际记忆和工具轨迹已保留。')
        chosen=verified[-1]
        answer=verified_answer(chosen['approved'],chosen['params'],[chosen['result_id']]*len(chosen['approved']))
        return dict(mode='deepagents',status='complete',answer=answer,model_answer=result['messages'][-1].content,memory_file=learned,
            memory_path=str(profile_memory),memory_id=memory['id'],memory_loaded=True,persistent_memory_reused=cached,
            context_id=context['id'],conversation_id=conversation_id,criteria_version=CRITERIA_VERSION,
            corrected_attempts=len(rejected),source_retrievals=len(source_reads),query_retries=len(query_retries),**chosen)
    finally:model.http_client.close()
