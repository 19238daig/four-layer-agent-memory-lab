"""Numerical, isolation and evidence invariants; no paid API calls."""
import hashlib
import math
import sqlite3
import pytest
from memory_demo.meal_db import MealDB,DEFAULTS,QUERY,PREFIX
from memory_demo.meal_engine import MealEngine


@pytest.fixture
def db(tmp_path):
    d=MealDB(tmp_path/'meal');d.initialize();return d


def test_seed_and_idempotent_initialization(db):
    before=hashlib.sha256(db.path.read_bytes()).hexdigest()
    info=db.initialize()
    counts={t['name']:t['count'] for t in info['tables']}
    assert len(counts)==14 and counts['menu_item']==50 and counts['material_dict']==80 and counts['combo_hdr']==20
    assert hashlib.sha256(db.path.read_bytes()).hexdigest()==before
    assert sqlite3.connect(db.path).execute('PRAGMA foreign_key_check').fetchall()==[]


def test_does_not_open_foreign_database(tmp_path):
    d=MealDB(tmp_path);c=sqlite3.connect(d.path);c.execute('CREATE TABLE private(value)');c.commit();c.close()
    before=d.path.read_bytes()
    with pytest.raises(ValueError,match='非本演示'):d.initialize()
    assert d.path.read_bytes()==before


@pytest.mark.parametrize('sql',[
 'DELETE FROM menu_item','UPDATE menu_item SET nm="x"','DROP TABLE menu_item',
 "ATTACH DATABASE 'other.sqlite3' AS x",'PRAGMA user_version=9',
 "SELECT load_extension('bad')",'SELECT * FROM sqlite_master',
 'SELECT 1; DELETE FROM menu_item',
 "WITH x AS (SELECT 1) DELETE FROM menu_item",
 "SELECT readfile('other.sqlite3')",
])
def test_read_only_sandbox_rejects_mutations_and_external_access(db,sql):
    before=hashlib.sha256(db.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):db.query(sql)
    assert hashlib.sha256(db.path.read_bytes()).hexdigest()==before


def test_numerics_units_versions_and_no_double_oil(db):
    rows=db.canonical(DEFAULTS)['rows'];assert {r['status'] for r in rows}=={'pass','fail','unknown','uncertain'}
    r=next(x for x in rows if x['offer_id']=='SKU:SK000-100')
    # Independently calculate recipe0: 200g mixed rice, 100g raw chicken (85g cooked/.85), 90g broccoli.
    expected=2*(4*3.2+9*1+4*26)+(4*23+9*2)+.9*(4*3+9*.4+4*5)
    assert r['base_kcal']==round(expected,2)
    assert r['kcal_lo']==round(expected+9*6*.6,1)
    assert r['kcal_hi']==round(expected+9*6*.8,1)
    assert r['recipe_ids']=='RV000-2' and r['price_ids'].endswith('-2')
    parts=db.detail(r['offer_id'],DEFAULTS)['rows']
    assert next(p for p in parts if p['mat_cd']=='M003')['edible_g_per_offer']==100
    assert all(p['nut_id'].endswith('-2') for p in parts)
    old=db.canonical({**DEFAULTS,'as_of':'2025-01-01'})['rows']
    assert next(x for x in old if x['offer_id']==r['offer_id'])['recipe_ids']=='RV000-1'


def test_missing_is_unknown_and_disabled_item_excluded(db):
    rows=db.canonical(DEFAULTS)['rows']
    assert all(r['status']=='unknown' and r['kcal_lo'] is None for r in rows if 'SK047' in r['offer_id'] or 'SK048' in r['offer_id'])
    assert not any('SK049' in r['offer_id'] for r in rows)
    assert len(db.resolve('鸡饭'))>1
    assert db.resolve('西红柿鸡蛋盖饭')[0]['item_cd']=='I006'


def test_combo_reconciles_all_parts(db):
    r=next(x for x in db.canonical(DEFAULTS)['rows'] if x['offer_id']=='COMBO:CB00')
    parts=db.detail(r['offer_id'],DEFAULTS)['rows']
    assert math.isclose(sum(p['ingredient_kcal'] for p in parts),r['base_kcal'],abs_tol=.01)
    assert len(set(p['sku_cd'] for p in parts))==2


def test_query_limit_and_snapshot(db):
    result=db.query('WITH RECURSIVE n(v) AS (SELECT 1 UNION ALL SELECT v+1 FROM n WHERE v<600) SELECT v FROM n')
    assert len(result['rows'])==500 and result['truncated']
    frozen=db.snapshot(db.root/'frozen')
    assert frozen.canonical(DEFAULTS)==db.canonical(DEFAULTS) or frozen.canonical(DEFAULTS)['rows']==db.canonical(DEFAULTS)['rows']
    with sqlite3.connect(db.path) as c:c.execute("UPDATE menu_item SET nm='edited' WHERE item_cd='I000'")
    assert frozen.resolve('清蒸鸡肉饭')[0]['nm']=='清蒸鸡肉饭'
    assert db.resolve('清蒸鸡肉饭')[0]['nm']=='edited' # the retained alias still resolves


def mock_call(self,system,prompt,**kw):
    import json
    data=json.loads(prompt)
    if 'updates' in system:
        text=data['text'];low=500 if '500' in text else 600;hi=600 if '500' in text else 700
        return {'updates':[{'key':'budget','value':120,'quote':'120'}, {'key':'kcal_min','value':low,'quote':str(low)},
                           {'key':'kcal_max','value':hi,'quote':str(hi)},{'key':'max_spice','value':0,'quote':'不吃辣'}]}
    if 'tail_sql' in system:return {'tail_sql':QUERY.split('-- MODEL_SELECT:')[1].split('\n',1)[1], 'name':'鸡饭' if '鸡饭' in data['question'] else '', 'overrides':[], 'explanation':'真实模型测试用替身'}
    return '\n'.join(f"{x['row']['offer_name']} [{x['evidence_id']}]" for x in data['approved'])


def invoke(e,action,**data):
    d={'user':'test','session':'new',**data};r=e.store.start('test',action,'new',d)
    out=getattr(e,'do_'+action)(r,d);e.store.finish(r,out);return out


def test_memory_versions_context_and_recommendation_provenance(db,monkeypatch):
    monkeypatch.setattr('memory_demo.meal_engine.Model.call',mock_call)
    e=MealEngine(db)
    invoke(e,'remember',text='不吃辣，预算120，热量600到700千卡')
    old=[n for n in e.store.heads('test','note') if n['payload'].get('condition')=='kcal_min'][0]
    p=invoke(e,'generate',text='明天午饭吃什么？')
    assert p['params']['kcal_min']==600 and e.store.get(p['context_id'])['layer']==4
    r=invoke(e,'execute_sql',plan_id=p['plan_id'])
    assert r['audited'] and len(r['approved'])==3
    assert len(e.store.get(r['answer_id'])['payload']['refs'])==3
    for ref in r['evidence_ids']:
        artifact=e.store.get(ref);assert artifact['payload']['refs']==[r['result_id']]
        assert artifact['payload']['detail']
    invoke(e,'remember',text='不吃辣，预算120，热量500到600千卡')
    current=[n for n in e.store.heads('test','note') if n['payload'].get('condition')=='kcal_min'][0]
    assert current['payload']['supersedes']==old['id'] and e.store.get(old['id'])['content']==old['content']
    assert invoke(e,'generate',text='再推荐一次')['params']['kcal_min']==500
    assert e.store.get(r['result_id'])['payload']['params']['kcal_min']==600


def test_ambiguity_and_exploration_cannot_produce_recommendations(db,monkeypatch):
    monkeypatch.setattr('memory_demo.meal_engine.Model.call',mock_call)
    e=MealEngine(db);invoke(e,'remember',text='不吃辣，预算120，热量600到700千卡')
    p=invoke(e,'generate',text='鸡饭有哪些？');assert p['ambiguous']
    with pytest.raises(ValueError,match='选择具体'):invoke(e,'execute_sql',plan_id=p['plan_id'])
    r=invoke(e,'execute_sql',plan_id=p['plan_id'],selected_item='I000',sql='SELECT 1 AS made_up_kcal')
    assert not r['audited'] and not r['approved']


def test_bad_model_quote_cannot_override_literal_rule_and_workspace_is_isolated(db,monkeypatch):
    monkeypatch.setattr('memory_demo.meal_engine.Model.call',lambda *a,**k:{'updates':[{'key':'budget','value':5,'quote':'not present'}]})
    e=MealEngine(db)
    invoke(e,'remember',text='预算120')
    budget=next(n for n in e.store.heads('test','note') if n['payload'].get('condition')=='budget')
    assert budget['payload']['typed_value']==120
    assert budget['payload']['evidence'][0]['quote']=='预算120'
    assert e.state('another')['objects']==[]
