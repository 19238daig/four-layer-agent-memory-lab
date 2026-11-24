import json
import pytest
from memory_demo.meal_engine import MealEngine
from memory_demo.meal_db import MealDB
from memory_demo.meal_compare import verification,usage_totals,TaggedStore,compile_agent_sql
from test_meal_lab import invoke,mock_call


@pytest.fixture
def engine(tmp_path,monkeypatch):
    db=MealDB(tmp_path/'meal');db.initialize()
    monkeypatch.setattr('memory_demo.meal_engine.Model.call',mock_call)
    return MealEngine(db)


def remember(e,text='不吃辣，预算120，热量600到700千卡',session='first'):
    return invoke(e,'remember',text=text,session=session)


def test_new_session_loads_selected_saved_version_without_old_chat(engine):
    e=engine;saved=remember(e)
    first=invoke(e,'generate',text='明天午饭吃什么',session='first')
    invoke(e,'execute_sql',plan_id=first['plan_id'],session='first')
    new=e.conversations.create('test','新的会话',saved['memory_id'])
    plan=invoke(e,'generate',text='周末午饭呢？',session=new['id'])
    assert plan['params']['kcal_min']==600 and plan['memory_id']==saved['memory_id']
    context=e.store.get(plan['context_id'])
    assert context['payload']['history_ids']==[]
    prompt=json.loads(context['content'])
    assert prompt['current_session_history']==[] and prompt['memory_loaded']
    assert all(e.store.get(e.store.get(n['id'])['payload']['refs'][0])['session']=='first' for n in prompt['condition_sources'])
    assert prompt['condition_sources']
    assert len(e.conversations.sessions('test'))==2


def test_sessions_pin_versions_and_can_fork_older_memory(engine):
    e=engine;original=remember(e)
    other=e.conversations.create('test','沿用旧版',original['memory_id'])
    updated=remember(e,'不吃辣，预算120，热量500到600千卡')
    assert original['memory_id']!=updated['memory_id']
    assert e.current('test','first')[0]['kcal_min']==500
    assert e.current('test',other['id'])[0]['kcal_min']==600
    old=e.conversations.memory('test',original['memory_id'])
    assert old['payload']['conditions']['kcal_min']==600
    # Updating the second conversation must not overwrite the first conversation's snapshot.
    remember(e,session=other['id'])
    assert e.current('test','first')[0]['kcal_min']==500


def test_no_memory_control_uses_labeled_defaults_and_preserves_records(engine):
    e=engine;saved=remember(e,'我特别喜欢吃辣，晚饭预算500块，热量不超过1000千卡，推荐三种。')
    count=len(e.store.objects('test'))
    empty=e.conversations.create('test','无记忆对照','')
    plan=invoke(e,'generate',session=empty['id'],text='晚上吃什么好？')
    assert not plan['memory_loaded'] and plan['memory_id'] is None
    assert plan['params']['budget']==120 and plan['params']['kcal_min']==600 and plan['params']['kcal_max']==700
    assert plan['params']['min_spice']==0 and plan['params']['max_spice']==0
    ctx=json.loads(e.store.get(plan['context_id'])['content'])
    assert ctx['condition_sources']==[] and ctx['current_session_history']==[]
    assert not ctx['memory_loaded']
    assert len(e.store.objects('test'))>count
    assert len(e.conversations.memories('test'))==1
    assert e.conversations.memory('test',saved['memory_id'])['payload']['conditions']['budget']==500


def test_saved_memory_is_user_scoped_and_sql_is_session_scoped(engine):
    e=engine;saved=remember(e)
    with pytest.raises(ValueError,match='当前记忆空间'):e.conversations.create('another',memory_id=saved['memory_id'])
    other=e.conversations.create('test',memory_id=saved['memory_id'])
    plan=invoke(e,'generate',text='午饭呢',session='first')
    with pytest.raises(ValueError,match='另一个会话'):
        invoke(e,'execute_sql',plan_id=plan['plan_id'],session=other['id'])


def test_bootstrap_imports_legacy_memory_without_deleting_artifacts(engine):
    e=engine;remember(e)
    with e.store.connect() as c:c.execute('DELETE FROM meal_sessions');c.execute('DELETE FROM meal_memories')
    before=[o['id'] for o in e.store.objects('test')]
    initial=e.conversations.bootstrap('test')
    assert initial['memory_id']
    assert before==[o['id'] for o in e.store.objects('test')]
    assert e.conversations.bootstrap('test')['id']==initial['id']


def test_metrics_distinguish_unknown_from_zero_and_do_not_invent_tokens(engine):
    assert usage_totals([])['total_tokens'] is None
    stats=usage_totals([{'usage':{'total_tokens':140}},{'usage':{'total_tokens':60}},{'usage':None}])
    assert stats['total_tokens']==200 and stats['reported_calls']==2 and stats['unreported_calls']==1
    assert stats['token_measurement']=='partial'
    assert usage_totals([{'usage':{'total_tokens':0}}])['total_tokens']==0
    run=engine.store.start('test','meal_compare','first',{})
    TaggedStore(engine.store,'four_layer').event(run,'model_response',{'usage':{'total_tokens':123}})
    event=engine.store.events(run_id=run)[-1]
    assert event['data']['comparison_mode']=='four_layer'


def test_formula_correct_does_not_imply_memory_conditions_correct():
    check=verification({'budget':73,'kcal_min':470},{'budget':120,'kcal_min':600},{},loaded=True)
    assert not check['passed']
    baseline=verification({'budget':120},{'budget':120},{},loaded=False)
    assert baseline['passed'] and not baseline['memory_loaded']


def test_simple_test_runs_full_pipeline_and_keeps_session_proof(engine):
    e=engine
    saved=invoke(e,'remember',text='不吃辣，预算120，热量600到700千卡',session='first',memory_title='我的午饭偏好')
    assert e.conversations.memory('test',saved['memory_id'])['title']=='我的午饭偏好'
    new=e.conversations.create('test','新会话',saved['memory_id'])
    result=invoke(e,'test_session',session=new['id'],text='明天午饭吃什么？')
    assert result['audited'] and result['approved']
    proof=result['memory_test']
    assert proof['memory_id']==saved['memory_id'] and proof['passed']
    assert proof['current_session_history_count']==0 and not proof['previous_session_history_injected']
    assert e.store.get(result['answer_id'])['session']==new['id']


def test_deep_agent_tail_uses_same_verified_formula(engine):
    from memory_demo.meal_db import DEFAULTS
    sql=compile_agent_sql("SELECT * FROM evaluated WHERE status='pass' ORDER BY price,offer_id LIMIT :limit;")
    actual=engine.db.query(sql,DEFAULTS)['rows']
    expected=[r for r in engine.db.canonical(DEFAULTS)['rows'] if r['status']=='pass']
    assert actual==expected
    assert compile_agent_sql('SELECT * FROM menu_item')=='SELECT * FROM menu_item'
