import json
import sqlite3
import pytest
from memory_demo.meal_engine import MealEngine
from memory_demo.meal_db import MealDB,DEFAULTS,QUERY
from memory_demo.meal_rules import parse_rules,NEUTRAL,qualifying_offer
from memory_demo.meal_preferences import normalized_extraction,migrate_legacy
from test_meal_lab import invoke

DINNER='我特别喜欢吃辣，晚饭预算500块，热量尽量控制在1000千卡。简单推荐三种就行。'
LUNCH='我不吃辣，午饭预算73块，热量470到610千卡。'


@pytest.fixture
def e(tmp_path,monkeypatch):
    db=MealDB(tmp_path/'meal');db.initialize()
    def model(self,system,prompt,**kw):
        if '"updates"' in system:return {'updates':[]}
        return {'tail_sql':QUERY.split('-- MODEL_SELECT:')[1].split('\n',1)[1],'name':'','overrides':[],'explanation':'测试查询'}
    monkeypatch.setattr('memory_demo.meal_engine.Model.call',model)
    return MealEngine(db)


def save(e,text,**kw):return invoke(e,'remember',text=text,save_mode=kw.pop('save_mode','replace'),**kw)
def test_loaded(e,memory_id,question='晚上吃什么好'):
    s=e.conversations.create('test',memory_id=memory_id)
    return invoke(e,'test_session',text=question,session=s['id'])
test_loaded.__test__=False


def test_dinner_likes_spicy_is_not_merely_spice_tolerance(e):
    lunch=save(e,LUNCH,memory_title='午饭偏好')
    pinned=e.conversations.create('test',memory_id=lunch['memory_id'])
    dinner=save(e,DINNER,memory_title='晚饭偏好')
    conditions=e.conversations.memory('test',dinner['memory_id'])['payload']['conditions']
    assert conditions['budget']==500 and conditions['kcal_max']==1000
    assert 'kcal_min' not in conditions and conditions['min_spice']==1 and conditions['max_spice']==2
    assert conditions['meal_period']=='dinner' and conditions['recommend_count']==3
    result=test_loaded(e,dinner['memory_id'])
    assert result['memory_test']['passed'] and result['has_matches'] and len(result['approved'])==3
    assert result['params']['kcal_min']==0 and 'kcal_min' not in result['specified_conditions']
    assert all(r['hot_lv']>=1 and r['price']<=500 and r['kcal_hi']<=1000 for r in result['approved'])
    assert all(qualifying_offer(r,result['params']) for r in result['approved'])
    assert '不辣' not in result['answer'] and '晚饭' in result['answer']
    assert e.current('test',pinned['id'])[0]['kcal_min']==470


@pytest.mark.parametrize('text,expected',[
 ('我喜欢吃辣',(1,2)),('我特别喜欢吃辣',(1,2)),('我能吃辣',(0,2)),
 ('我不吃辣',(0,0)),('我不喜欢吃辣',(0,0)),('我不想吃辣',(0,0)),('只吃微辣',(1,1)),('不要太辣',(0,1)),('只吃重辣',(2,2)),
])
def test_spice_semantics(text,expected):
    p=parse_rules(text)['updates'];assert (p['min_spice'],p['max_spice'])==expected


def test_upper_only_replaces_old_lower_even_in_explicit_update(e):
    save(e,LUNCH)
    newer=save(e,'热量不超过900千卡',save_mode='update')
    c=e.conversations.memory('test',newer['memory_id'])['payload']['conditions']
    assert c['budget']==73 and c['kcal_max']==900 and 'kcal_min' not in c
    assert e.current('test','new')[0]['kcal_min']==0


def test_lower_only_and_explicit_bound_contradiction(e):
    save(e,LUNCH)
    lower=save(e,'热量至少800千卡',save_mode='update')
    c=e.conversations.memory('test',lower['memory_id'])['payload']['conditions']
    assert c['kcal_min']==800 and 'kcal_max' not in c
    save(e,LUNCH)
    with pytest.raises(ValueError,match='下限高于上限'):save(e,'热量下限改成800千卡',save_mode='update')


def test_independent_partial_profile_does_not_borrow_omitted_conditions(e):
    save(e,LUNCH)
    only_budget=save(e,'晚饭预算100块')
    p=e.conversations.memory('test',only_budget['memory_id'])['payload']['conditions']
    assert set(p)=={'budget','meal_period'}
    current=e.current('test','new')[0]
    assert current['kcal_min']==0 and current['kcal_max']==10000 and current['max_spice']==2
    assert current['min_spice']==0


def test_no_matches_does_not_relax_spice_or_invent_recommendations(e):
    saved=save(e,'晚饭预算500块，热量不超过1000千卡，只吃微辣。')
    result=test_loaded(e,saved['memory_id'])
    assert result['memory_test']['passed'] and not result['has_matches'] and result['approved']==[]
    assert '没有找到' in result['answer'] and result['counts']['pass']==0
    assert result['params']['min_spice']==result['params']['max_spice']==1


def test_explicit_update_keeps_intended_fields_and_meal_scope_is_checked(e):
    first=save(e,DINNER)
    newer=save(e,'预算改成80块，其他不变',save_mode='update')
    c=e.conversations.memory('test',newer['memory_id'])['payload']['conditions']
    assert c['budget']==80 and c['meal_period']=='dinner' and c['min_spice']==1 and c['kcal_max']==1000
    with pytest.raises(ValueError,match='其他餐次'):test_loaded(e,first['memory_id'],'明天中午吃什么')


@pytest.mark.parametrize('text',['我对坚果过敏，晚饭预算100块','我只吃素食，预算80','不要海鲜，预算80','热量1000千卡左右','热量不超过4200千焦'])
def test_unsupported_or_ambiguous_criteria_cannot_be_saved_as_success(e,text):
    with pytest.raises(ValueError):save(e,text)
    assert e.conversations.memories('test')==[]


def test_recommendation_count_and_model_semantic_mistakes(e):
    values,quotes,clear=normalized_extraction(DINNER,[{'key':'max_spice','value':0,'quote':'喜欢吃辣'},
        {'key':'kcal_min','value':470,'quote':'控制在1000千卡'}])
    assert values['min_spice']==1 and values['max_spice']==2 and 'kcal_min' not in values and 'kcal_min' in clear
    saved=save(e,'晚饭预算500块，热量不超过1000千卡，喜欢吃辣，推荐两种。')
    assert len(test_loaded(e,saved['memory_id'])['approved'])==2


def test_three_kinds_prioritizes_main_meals_without_duplicate_portions(e):
    saved=save(e,DINNER)
    rows=test_loaded(e,saved['memory_id'])['approved']
    with e.db.connect() as c:
        meta={r['sku_cd']:dict(r) for r in c.execute('SELECT s.sku_cd,s.item_cd,s.mult,i.kind_cd FROM sku_spec s JOIN menu_item i ON i.item_cd=s.item_cd')}
    kinds=[tuple(sorted({meta[s]['item_cd'] for s in row['sku_ids'].split(',')})) for row in rows]
    assert len(set(kinds))==3
    assert all(any(meta[s]['kind_cd']=='main' for s in row['sku_ids'].split(',')) for row in rows)
    assert all(qualifying_offer(r,{**NEUTRAL,**e.conversations.memory('test',saved['memory_id'])['payload']['conditions']}) for r in rows)


def test_generated_limit_does_not_hide_required_distinct_meals(e,monkeypatch):
    saved=save(e,DINNER)
    monkeypatch.setattr('memory_demo.meal_engine.Model.call',lambda *a,**kw:{'tail_sql':"SELECT * FROM evaluated WHERE status='pass' ORDER BY price,offer_id LIMIT 2;",'name':'','overrides':[],'explanation':'截断示例'})
    result=test_loaded(e,saved['memory_id'])
    assert len(result['approved'])==3 and result['memory_test']['passed']
    assert len({row['offer_name'].split(' · ')[0] for row in result['approved']})==3


def test_verification_also_checks_unrequested_extra_restrictions(e):
    from memory_demo.meal_compare import verification
    expected={**NEUTRAL,'budget':500,'kcal_max':1000,'min_spice':1,'meal_period':'dinner'}
    actual={**expected,'kcal_min':470}
    assert not verification(expected,actual,{},loaded=True)['passed']


def test_model_cannot_invent_numbers_from_non_numerical_question():
    updates,_,_=normalized_extraction('晚上吃什么好',[{'key':'kcal_min','value':470,'quote':'晚上吃什么好'},
        {'key':'budget','value':73,'quote':'晚上吃什么好'},{'key':'min_spice','value':0,'quote':'晚上吃什么好'}])
    assert updates=={'meal_period':'dinner'}


@pytest.mark.parametrize('mutation,target',[
 ("UPDATE menu_item SET hot_lv=NULL WHERE item_cd='I000'",'COMBO:CB00'),
 ("UPDATE price_hist SET amt=-5 WHERE sku_cd='SK000-100' AND valid_to IS NULL",'SKU:SK000-100'),
 ("UPDATE recipe_line SET qty=-1 WHERE line_id='RL000-0'",'SKU:SK000-100'),
 ("UPDATE nutrient_ver SET f_100=-1 WHERE mat_cd='M003' AND valid_to IS NULL",'SKU:SK000-100'),
])
def test_bad_data_is_unknown_including_unknown_component_spice(e,mutation,target):
    with sqlite3.connect(e.db.path) as c:c.execute(mutation)
    row=next(r for r in e.db.canonical({**DEFAULTS,**NEUTRAL})['rows'] if r['offer_id']==target)
    assert row['status']=='unknown'


def test_legacy_dinner_is_repaired_from_originals_without_rewriting_history(e):
    lunch=save(e,LUNCH)
    base=e.conversations.memory('test',lunch['memory_id'])
    raw_lunch=e.store.get(base['payload']['source_record_id'])
    raw=e.store.add('test',1,'user_message','选餐条件原话',DINNER,session='new')
    notes=[]
    for key,value,source,quote in [('budget',500,raw,'预算500块'),('kcal_min',470,raw_lunch,'470到610千卡'),('kcal_max',1000,raw,'控制在1000千卡'),('max_spice',2,raw,'喜欢吃辣')]:
        notes.append(e.store.add('test',2,'note',key,str(value),refs=[source['id']],key='meal.'+key,condition=key,typed_value=value,
            evidence=[{'id':source['id'],'quote':quote}],topic='meal_preferences'))
    old=e.conversations.save('test','晚饭偏好',notes,[],session='new',training_ids=[raw_lunch['id'],raw['id']])
    with e.store.connect() as c:unchanged=c.execute('SELECT payload FROM meal_memories WHERE id=?',(old['id'],)).fetchone()[0]
    repaired=migrate_legacy(e);assert len(repaired)==1
    fixed=e.conversations.memory('test',old['id'])
    assert fixed['id']!=old['id'] and fixed['payload']['repaired_from']==old['id']
    assert fixed['payload']['conditions']['min_spice']==1 and 'kcal_min' not in fixed['payload']['conditions']
    assert fixed['payload']['training_ids']==[raw['id']]
    assert e.conversations.session('test','new')['memory_id']==fixed['id']
    with e.store.connect() as c:assert c.execute('SELECT payload FROM meal_memories WHERE id=?',(old['id'],)).fetchone()[0]==unchanged
    assert e.store.get(raw['id'])['content']==DINNER and list((e.db.root/'backups').glob('*.sqlite3'))
    assert migrate_legacy(e)==[]
