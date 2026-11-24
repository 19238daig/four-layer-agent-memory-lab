import json
import sqlite3
from contextlib import closing

import pytest

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from memory_demo.chat import run_chat
from memory_demo.file_checkpoint import FileCheckpoint
from memory_demo.file_store import FileStore
from memory_demo.meal_db import MealDB
from memory_demo.meal_engine import MealEngine
from memory_demo.meal_sessions import MealSessions
from memory_demo.store import Store, now, uid


@pytest.mark.parametrize(('label','scope'),[
    ('中饭','lunch'),('午饭','lunch'),('中午','lunch'),('午餐','lunch'),('午间','lunch'),
    ('早饭','breakfast'),('早餐','breakfast'),('早上','breakfast'),
    ('晚饭','dinner'),('晚餐','dinner'),('晚间','dinner'),
])
def test_meal_aliases_share_one_canonical_memory_scope(label,scope):
    from memory_demo.chat_memory import explicit_meal_changes, meal_scope
    from memory_demo.meal_rules import GENERIC_NAMES
    text = f'以后{label}我喜欢吃辣，预算100块，热量不超过1000千卡。'
    assert meal_scope(text,[])==scope
    changes = explicit_meal_changes(text,scope)
    assert (f'meal:{scope}:budget',100,'预算100块') in changes
    assert label in GENERIC_NAMES


def test_scope_repair_moves_latest_alias_from_generic_to_lunch(tmp_path):
    from memory_demo.chat_memory import ChatMemory, criteria, repair_chat_meal_scope
    store = FileStore(tmp_path/'memory')
    for mode in ('four_layer','deepagents'):
        memory = ChatMemory(store,'test',mode)
        old = store.start('test','chat','s1',{})
        prior = store.add('test',1,'user_message','用户消息','以后午饭不吃辣，预算120块，热量600到700千卡。',
                          chat_engine=mode,run_id=old,session='s1')
        from memory_demo.chat_memory import explicit_meal_changes
        version,_ = memory.commit(memory.current(True),explicit_meal_changes(prior['content'],'lunch'),prior,old)
        store.finish(old,{'branches':[dict(mode=mode,status='complete',memory_status='updated')]})
        new = store.start('test','chat','s2',{})
        source = store.add('test',1,'user_message','用户消息','以后中饭我喜欢吃辣，预算100块，热量不超过1000千卡。',
                           chat_engine=mode,run_id=new,session='s2')
        from memory_demo.chat_memory import meal_changes
        changes = meal_changes(source['content'],'any')
        version,_ = memory.commit(version,changes,source,new)
        store.finish(new,{'branches':[dict(mode=mode,status='complete',memory_status='updated')]})
    repair_chat_meal_scope(store)
    for mode in ('four_layer','deepagents'):
        version = ChatMemory(store,'test',mode).current(True)
        params, memory = criteria(version['entries'],'lunch','中午吃什么好')
        assert params['budget']==100 and params['kcal_min']==0 and params['kcal_max']==1000 and params['min_spice']==1
        assert memory['budget']['quote']=='预算100块'
        assert not any(name.startswith('meal:any:') for name in version['entries'])
        dinner,_ = criteria(version['entries'],'dinner','晚上吃什么好')
        assert dinner['budget']==120 and dinner['min_spice']==0


@pytest.mark.parametrize('qualification',[
    '清淡点', '口味清淡一点', '尽量清淡一些', '我想吃清淡一点',
])
def test_no_spice_with_casual_taste_description_preserves_explicit_rules(qualification):
    from memory_demo.chat_memory import criteria, explicit_meal_changes
    statement = f'以后中饭我不吃辣，{qualification}，热量不超过500千卡。'
    changes = {key:value for key,value,_ in explicit_meal_changes(statement,'lunch')}
    assert changes['meal:lunch:max_spice']==0
    assert changes['meal:lunch:kcal_max']==500
    params,_ = criteria({},'lunch',f'中午吃什么，不辣，{qualification}，热量不超过500千卡？')
    assert params['max_spice']==0 and params['kcal_max']==500


@pytest.mark.parametrize('qualification',[
    '清淡点，我对坚果过敏', '清淡点，低盐', '清淡点，少盐', '必须清淡', '清淡少油', '清淡点，不放盐',
])
def test_unverifiable_requirements_are_not_treated_as_casual_taste(qualification):
    from memory_demo.chat_memory import criteria, explicit_meal_changes
    statement = f'以后中饭我不吃辣，{qualification}，热量不超过500千卡。'
    with pytest.raises(ValueError,match='尚不能完整核验'):
        explicit_meal_changes(statement,'lunch')
    with pytest.raises(ValueError,match='尚不能完整核验'):
        criteria({},'lunch',f'中午吃什么，不辣，{qualification}，热量不超过500千卡？')


@pytest.mark.parametrize(('text','key','value','strict','cleared'),[
    ('热量超过500千卡','kcal_min',500,True,'kcal_max'),
    ('热量高于500','kcal_min',500,True,'kcal_max'),
    ('500千卡及以上','kcal_min',500,False,'kcal_max'),
    ('热量不要超过400千卡','kcal_max',400,False,'kcal_min'),
    ('热量低于400千卡','kcal_max',400,True,'kcal_min'),
    ('热量不能低于450千卡','kcal_min',450,False,'kcal_max'),
])
def test_heat_comparators_preserve_inclusive_and_exclusive_meaning(text,key,value,strict,cleared):
    from memory_demo.meal_rules import parse_rules
    result = parse_rules(text)
    assert not result['unsupported']
    assert result['updates'][key] == value
    assert bool(result['updates'].get(key+'_exclusive')) is strict
    assert cleared in result['clear_keys'] and cleared not in result['updates']


def test_chat_history_repair_uses_original_lower_range_and_keeps_sources(tmp_path):
    from memory_demo.chat_memory import ChatMemory, criteria, repair_chat_heat
    store = FileStore(tmp_path / 'memory')
    for mode in ('four_layer','deepagents'):
        memory = ChatMemory(store,'test',mode)
        start = store.start('test','chat','s1',{})
        first = store.add('test',1,'user_message','用户消息','以后晚饭预算200块，热量不超过400千卡。',
                          chat_engine=mode,run_id=start,session='s1')
        version,_ = memory.commit(memory.current(True),[
            ('meal:dinner:budget',200,'预算200块'),('meal:dinner:kcal_max',400,'不超过400千卡')
        ],first,start)
        store.finish(start,{'branches':[{'mode':mode,'status':'complete','memory_status':'updated'}]})
        change = store.start('test','chat','s2',{})
        second = store.add('test',1,'user_message','用户消息','以后晚饭预算1000块，热量超过500千卡。',
                           chat_engine=mode,run_id=change,session='s2')
        version,_ = memory.commit(version,[('meal:dinner:budget',1000,'预算1000块')],second,change)
        store.finish(change,{'branches':[{'mode':mode,'status':'complete','memory_status':'updated'}]})
    repair_chat_heat(store)
    marker = json.loads((store.path/'chat-heat-v2.json').read_text(encoding='utf-8'))
    assert len(marker['repairs']) == 2
    for mode in ('four_layer','deepagents'):
        entries = ChatMemory(store,'test',mode).current(True)['entries']
        assert 'meal:dinner:kcal_max' not in entries
        assert entries['meal:dinner:kcal_min']['quote']=='超过500千卡'
        params,_ = criteria(entries,'dinner','晚上吃什么？')
        assert params['budget']==1000 and params['kcal_min']==500 and params['kcal_min_exclusive']==1
        temporary,_ = criteria(entries,'dinner','今天热量不超过400千卡，晚上吃什么？')
        assert temporary['kcal_min']==0 and temporary['kcal_max']==400 and temporary['kcal_min_exclusive']==0


def test_catalogue_excludes_strict_calorie_endpoint(tmp_path):
    from memory_demo.meal_db import DEFAULTS, PREFIX
    database = MealDB(tmp_path/'catalog')
    database.initialize()
    params = {**DEFAULTS,'budget':10000,'min_spice':0,'max_spice':2}
    [candidate] = database.query(PREFIX+"SELECT offer_id,raw_lo FROM offers WHERE missing_count=0 AND price IS NOT NULL AND raw_lo>0 AND spice_missing=0 LIMIT 1",params)['rows']
    params.update(kcal_min=candidate['raw_lo'],kcal_max=10000,offer_id=candidate['offer_id'])
    assert database.canonical(params)['rows'][0]['status']=='pass'
    assert database.canonical({**params,'kcal_min_exclusive':1})['rows'][0]['status']!='pass'


def test_running_chat_exposes_current_phases_and_first_finished_branch(tmp_path):
    from memory_demo.chat_api import with_progress

    store = FileStore(tmp_path / 'memory')
    run_id = store.start('test', 'chat', 'test-session', {})
    store.event(run_id, 'chat_progress', dict(comparison_mode='four_layer', phase='answering'))
    store.event(run_id, 'chat_branch_result', dict(comparison_mode='four_layer', mode='four_layer',
                                                  answer='已核验', status='complete'))
    store.event(run_id, 'chat_progress', dict(comparison_mode='deepagents', phase='reading'))
    store.event(run_id, 'chat_progress', dict(comparison_mode='deepagents', phase='querying'))
    run = with_progress(store, store.run(run_id, 'test'))
    assert run['status'] == 'running'
    assert run['progress']['deepagents'] == 'querying'
    assert [branch['answer'] for branch in run['result']['branches']] == ['已核验']
    assert store.run(run_id, 'test')['result'] == {}


def test_migration_preserves_artifacts_versions_and_links_without_writing_archive(tmp_path):
    legacy = Store(tmp_path / 'archive.sqlite3')
    sessions = MealSessions(legacy)
    raw = legacy.add('test', 1, 'user_message', '选餐条件原话', '晚饭预算500块', session='first')
    note = legacy.add('test', 2, 'note', '预算', '500元', refs=[raw['id']], condition='budget', typed_value=500)
    topic = legacy.add('test', 3, 'representation', '偏好', f"- 预算 500 元 [{note['id']}]", refs=[note['id']])
    version = sessions.save('test', '晚饭', [note], [topic])
    session = sessions.create('test', '新会话', version['id'])
    legacy.set_head('test', 'representation', 'meal_preferences', topic['id'])
    # Settle the fixture's own WAL writes before checking that read-only import leaves it intact.
    with closing(legacy.connect()) as connection:
        assert connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0
    before = legacy.path.read_bytes()
    store = FileStore(tmp_path / 'files', legacy.path)
    assert store.get(topic['id'])['content'] == topic['content']
    assert legacy.path.read_bytes() == before

    restored = FileStore(store.path, legacy.path)
    assert restored.get(note['id'])['payload']['refs'] == [raw['id']]
    assert restored.heads('test', 'representation')[0]['id'] == topic['id']
    from memory_demo.file_sessions import FileMealSessions
    assert FileMealSessions(restored).view('test', session['id'])[1]['id'] == version['id']
    assert len(restored.objects('test')) == 3
    assert not list(store.path.rglob('*.sqlite*'))


def test_hashed_workspace_renames_with_both_memories_and_sessions_intact(tmp_path):
    from memory_demo.chat_memory import ChatMemory
    from memory_demo.file_sessions import FileMealSessions
    from memory_demo.file_store import key, read_json, write_json, write_text

    store = FileStore(tmp_path / 'memory')
    user = 'meal-demo'
    sessions = FileMealSessions(store)
    session = sessions.create(user, '午饭')
    run = store.start(user, 'chat', session['id'], {})
    current_path = store.workspace(user)
    assert current_path.name == user
    ids = {}
    for mode in ('four_layer', 'deepagents'):
        memory = ChatMemory(store, user, mode)
        source = store.add(user, 1, 'user_message', '用户消息', '以后午饭不吃辣。',
                           chat_engine=mode, run_id=run, session=session['id'])
        version, _ = memory.commit(memory.current(True), [('meal:lunch:max_spice', 0, '不吃辣')], source, run)
        ids[mode] = (version['id'], source['id'])
    store.finish(run)
    checkpoint = 'deep_agents/checkpoints/example/state.json'
    write_json(current_path / checkpoint, {'saved': True})
    archive = 'deep_agents/legacy/profile/AGENTS.md'
    write_text(current_path / archive, '# 原有记忆归档\n')
    hashed = current_path.with_name(key(user))
    current_path.rename(hashed)
    write_json(store.path / 'deep-import.json', {'imported': [f'workspaces/{hashed.name}/{archive}']})

    # An existing same-name directory must not be overwritten.
    collision = current_path.with_name('Meal-Demo')
    write_json(collision / 'workspace.json', {'user': 'Meal-Demo'})
    for _ in range(2):
        restored = FileStore(store.path)
        renamed = restored.workspace(user)
        assert renamed.name == 'meal-demo-2' and not hashed.exists()
        assert restored.workspace('Meal-Demo') == collision
        assert FileMealSessions(restored).session(user, session['id']) == session
        assert restored.run(run, user)['status'] == 'complete'
        for mode, (version_id, source_id) in ids.items():
            version = ChatMemory(restored, user, mode).current(True)
            assert version['id'] == version_id
            assert version['entries']['meal:lunch:max_spice']['source'] == source_id
            assert restored.get(source_id, user)['content'] == '以后午饭不吃辣。'
        assert (renamed / 'deep_agents/AGENTS.md').is_file()
        assert (renamed / 'four_layer/knowledge/chat-index.md').is_file()
        assert read_json(renamed / checkpoint) == {'saved': True}
        [location] = read_json(store.path / 'deep-import.json')['imported']
        assert (store.path / location).read_text(encoding='utf-8') == '# 原有记忆归档\n'


def test_file_checkpoint_resumes_graph_and_isolates_fresh_thread(tmp_path):
    class State(TypedDict):
        count: int

    def compile_graph():
        graph = StateGraph(State)
        graph.add_node('increment', lambda state: {'count': state.get('count', 0) + 1})
        graph.add_edge(START, 'increment')
        graph.add_edge('increment', END)
        return graph.compile(checkpointer=FileCheckpoint(tmp_path / 'state.json'))

    config = {'configurable': {'thread_id': 'one'}}
    assert compile_graph().invoke({'count': 0}, config)['count'] == 1
    assert compile_graph().invoke({}, config)['count'] == 2
    assert compile_graph().invoke({'count': 0}, {'configurable': {'thread_id': 'two'}})['count'] == 1


def test_catalog_chat_uses_only_read_only_queries_in_both_engines(tmp_path, monkeypatch):
    from memory_demo.chat import catalog_request

    store = FileStore(tmp_path / 'memory')
    database = MealDB(tmp_path / 'catalog')
    database.initialize()
    original = database.path.read_bytes()
    engine = MealEngine(database, store=store)

    def unexpected_model(*args, **kwargs):
        pytest.fail('目录查询应直接使用数据库')

    monkeypatch.setattr('memory_demo.chat.Model.call', unexpected_model)
    monkeypatch.setattr('memory_demo.chat.deep_chat', unexpected_model)
    session = dict(id=uid('session'), engine='parallel', memory_enabled=False, user_id='test',
                   title='测试', created_at=now())
    engine.conversations.write_session(session)
    for text, expected, params, rows in [
        ('餐厅s03是哪家', '旧店（停用）', {'shop_cd': 'S03'}, [{'shop_cd': 'S03', 'nm': '旧店（停用）', 'active_f': 0}]),
        ('查询门店S99', '没有找到', {'shop_cd': 'S99'}, []),
        ('你连上数据库了吗', '已实际读取', {}, [{'shop_count': 3}]),
    ]:
        data = dict(user='test', session=session['id'], text=text)
        run = store.start('test', 'chat', session['id'], data)
        branches = run_chat(engine, run, data)['branches']
        assert {branch['mode'] for branch in branches} == {'four_layer', 'deepagents'}
        for branch in branches:
            assert branch['status'] == 'complete' and branch['memory_status'] == 'disabled'
            assert expected in branch['answer'] and branch['total_tokens'] == 0
            evidence = store.get(branch['evidence_id'], 'test')
            assert evidence['id'] in branch['answer']
            assert evidence['payload']['result']['rows'] == rows
            assert evidence['payload']['database'] == str(database.path)
            assert evidence['payload']['params'] == params
    assert catalog_request('餐厅S03中午吃什么好') is None
    assert database.path.read_bytes() == original


def test_parallel_chat_exposes_every_catalog_table(tmp_path):
    from memory_demo.meal_db import TABLES

    store = FileStore(tmp_path / 'memory')
    database = MealDB(tmp_path / 'catalog')
    database.initialize()
    engine = MealEngine(database, store=store)
    original = database.path.read_bytes()
    session = dict(id=uid('session'), engine='parallel', memory_enabled=False, user_id='test',
                   title='测试', created_at=now())
    engine.conversations.write_session(session)

    def query(text):
        data = dict(user='test', session=session['id'], text=text)
        run = store.start('test', 'chat', session['id'], data)
        branches = run_chat(engine, run, data)['branches']
        assert {branch['mode'] for branch in branches} == {'four_layer', 'deepagents'}
        results = []
        for branch in branches:
            assert branch['status'] == 'complete' and branch['total_tokens'] == 0, branch['answer']
            evidence = store.get(branch['evidence_id'], 'test')
            results.append(evidence['payload']['result']['rows'])
        assert results[0] == results[1]
        return results[0]

    listed = query('数据库有哪些表？')
    assert {row['table_name'] for row in listed} == set(TABLES)
    for row in listed:
        table = row['table_name']
        sample = query(f'查看 {table} 前 2 条')
        assert len(sample) == 2 and row['row_count'] >= len(sample)
        fields = query(f'{table} 有哪些字段？')
        assert {field['col_nm'] for field in fields} == set(sample[0])
    prices = query('看历史价格表前 3 条')
    assert query('看历史价格表从第 3 条开始，只看前 1 条') == [prices[2]]
    assert query('price_hist从第二条开始，前两条') == prices[1:3]
    assert query('门店表有多少条记录') == [{'row_count': 3}]
    assert database.path.read_bytes() == original


def test_catalog_business_queries_keep_filters_in_both_branches(tmp_path, monkeypatch):
    from memory_demo.chat_memory import ChatMemory

    store = FileStore(tmp_path / 'memory')
    database = MealDB(tmp_path / 'catalog')
    database.initialize()
    original = database.path.read_bytes()
    engine = MealEngine(database, store=store)
    monkeypatch.setattr('memory_demo.chat.Model.call', lambda *a, **kw: pytest.fail('应执行已明确的业务查询'))
    monkeypatch.setattr('memory_demo.chat.deep_chat', lambda *a, **kw: pytest.fail('应执行已明确的业务查询'))
    session = dict(id=uid('session'), engine='parallel', memory_enabled=True, user_id='test',
                   title='测试', created_at=now())
    engine.conversations.write_session(session)
    # A real preference exists in both workspaces and must not filter a factual answer.
    for mode in ('four_layer', 'deepagents'):
        seed = store.start('test', 'chat', session['id'], {})
        source = store.add('test', 1, 'user_message', '用户消息', '我喜欢吃辣。',
                           chat_engine=mode, run_id=seed, session=session['id'])
        memory = ChatMemory(store, 'test', mode)
        memory.commit(memory.current(True), [('meal:any:min_spice', 1, source['content'])], source, seed)
        store.finish(seed)

    def ask(text):
        data = dict(user='test', session=session['id'], text=text)
        run = store.start('test', 'chat', session['id'], data)
        branches = run_chat(engine, run, data)['branches']
        rows = []
        for branch in branches:
            assert branch['status'] == 'complete' and branch['total_tokens'] == 0, branch['answer']
            assert 'params' not in branch  # These questions do not use meal recommendation filters.
            evidence = store.get(branch.get('evidence_id'), 'test')
            rows.append(evidence['payload']['result']['rows'] if evidence else [])
        assert rows[0] == rows[1]
        return rows[0], branches[0]['answer']

    s01, _ = ask('menu_item（菜单）当中S01店有哪些菜品')
    assert len(s01) == 25 and {row['shop_cd'] for row in s01} == {'S01'}
    s02, _ = ask('S02店当中所有的菜品列举出来')
    assert len(s02) == 25 and {row['shop_cd'] for row in s02} == {'S02'}
    s02_available = [row for row in s02 if row['active_f']]
    assert len(s02_available) == 24
    for question in (
            'S02店出售的菜品有哪些', 'S02有哪些在售菜品', 'S02正在售卖的菜品有哪些',
            'S02卖什么菜', 'S02都卖啥？', 'S02店有哪些菜品在售', 'S02店出售哪些菜品',
            '巷口食堂目前出售的菜品有哪些'):
        actual, reply = ask(question)
        assert actual == s02_available, question
        assert '在售' in reply, question
    assert ask('S02店不在售的菜品有哪些')[0] == [row for row in s02 if not row['active_f']]
    assert ask('青禾小馆这家门店有哪些菜品？')[0] == s01
    assert ask('S01有哪些菜品，从第 3 条开始，前 2 条')[0] == s01[2:4]
    assert ask('menu_item shop_cd=S01 AND hot_lv=0')[0] == [row for row in s01 if row['hot_lv']==0][:5]
    assert ask('S01店有多少道菜品？')[0] == [{'row_count': 25}]
    rows, answer = ask('清汤牛肉面在哪家店售卖')
    assert [(r['item_cd'], r['shop_cd']) for r in rows] == [('I020', 'S01')]
    assert '青禾小馆' in answer
    multiple, _ = ask('清汤牛肉面和西兰花牛肉饭哪些门店有卖？')
    assert {row['dish'] for row in multiple} == {'清汤牛肉面', '西兰花牛肉饭'}
    for question in (
            '清汤牛肉面哪些店有卖', '清汤牛肉面哪些门店在卖？', '清汤牛肉面哪儿买得到？',
            '有卖清汤牛肉面的店有哪些？', '清汤牛肉面是哪家店？', 'I020有卖吗？',
            'S01门店有卖清汤牛肉面吗？', '清汤牛肉面到哪家能吃到？', '哪些店出售清汤牛肉面'):
        matches, reply = ask(question)
        assert [(r['item_cd'], r['shop_cd'], r['available']) for r in matches] == [('I020', 'S01', 1)], question
        assert '在售' in reply
    wrong_store, reply = ask('清汤牛肉面哪些店有卖，S02有吗')
    assert wrong_store == [] and '没有找到' in reply
    wrong_store, reply = ask('S02卖清汤牛肉面吗？')
    assert wrong_store == [] and '没有找到' in reply
    inactive, _ = ask('I049有卖吗？')
    assert inactive and inactive[0]['available'] == 0
    assert len(ask('青禾小馆这家门店有哪些在售菜品？')[0]) == 25
    assert ask('菜单当中的清炖排骨面属于哪家餐厅')[0][0]['shop_cd'] == 'S01'
    assert ask('西红柿鸡蛋盖饭在哪家店售卖')[0][0]['item_cd'] == 'I006'
    assert {r['item_cd'] for r in ask('清汤牛肉面多少钱')[0]} == {'I020'}
    assert {r['item_cd'] for r in ask('清汤牛肉面用哪些食材')[0]} == {'I020'}
    recipe_rows, _ = ask('查看 recipe_line 里 I020 的数据')
    assert recipe_rows and all(row['recipe_id'].startswith('RV020') for row in recipe_rows)
    assert [r['item_cd'] for r in ask('查看 menu_item 里清汤牛肉面的数据')[0]] == ['I020']
    prices = ask('查看 price_hist 中清汤牛肉面的记录')[0]
    assert prices and all(row['sku_cd'].startswith('SK020-') for row in prices)
    assert ask('月球牛肉面在哪家店售卖')[0] == []
    assert '没有匹配到指定' in ask('查看 menu_item 里月球牛肉面的数据')[1]
    assert '无法确认' in ask('查看 cook_rule 里 S01 的数据')[1]
    assert '请用明确' in ask('查看 menu_item 里名称含有鸡的记录')[1]
    assert database.path.read_bytes() == original

    assert ask('S02的清汤牛肉面多少钱？')[0] == []
    assert ask('S02的清汤牛肉面用哪些食材？')[0] == []
    with closing(sqlite3.connect(database.path)) as connection, connection:
        connection.executemany("""
            INSERT INTO price_hist(price_id, sku_cd, amt, valid_from, valid_to)
            VALUES (?, ?, ?, '2026-02-01', NULL)
        """, [('QA-missing', 'SK020-80', None), ('QA-negative', 'SK020-100', -1)])
        connection.execute("UPDATE sku_spec SET active_f=0 WHERE sku_cd='SK020-125'")
        connection.execute("UPDATE shop_mst SET active_f=0 WHERE shop_cd='S02'")
        connection.execute("""
            INSERT INTO recipe_ver(recipe_id, item_cd, ver_no, servings, oil_g, rule_cd, valid_from)
            VALUES ('QA-recipe', 'I020', 3, 1, 0, 'steam', '2026-02-01')
        """)
        connection.execute("""
            INSERT INTO recipe_line(line_id, recipe_id, mat_cd, qty, uom, wt_basis)
            VALUES ('QA-line', 'QA-recipe', 'M001', 30, 'g', 'raw')
        """)
    damaged = database.path.read_bytes()
    assert ask('I020有卖吗？')[0][0]['available'] == 0
    assert ask('清汤牛肉面多少钱？')[0] == []
    historic, reply = ask('清汤牛肉面的历史价格？')
    assert any(row['amt'] is None for row in historic) and '价格缺失' in reply and '价格异常' in reply
    assert [row['item_cd'] for row in ask('S01门店有哪些不在售菜品？')[0]] == ['I020']
    assert ask('S01有多少在售菜品？')[0] == [{'row_count': 24}]
    assert ask('S02有多少在售菜品？')[0] == [{'row_count': 0}]
    latest_recipe, _ = ask('清汤牛肉面用哪些食材？')
    assert [row['recipe_id'] for row in latest_recipe] == ['QA-recipe']
    assert database.path.read_bytes() == damaged


def test_store_menu_resolves_alias_before_query_and_keeps_availability(tmp_path, monkeypatch):
    store = FileStore(tmp_path / 'memory')
    database = MealDB(tmp_path / 'catalog')
    database.initialize()
    engine = MealEngine(database, store=store)
    monkeypatch.setattr('memory_demo.chat.Model.call', lambda *a, **kw: pytest.fail('门店菜单应直接查库'))
    monkeypatch.setattr('memory_demo.chat.deep_chat', lambda *a, **kw: pytest.fail('门店菜单应直接查库'))

    def ask(text, *, enabled=True):
        session = dict(id=uid('session'), engine='parallel', memory_enabled=enabled, user_id='test',
                       title='测试', created_at=now())
        engine.conversations.write_session(session)
        data = dict(user='test', session=session['id'], text=text)
        run = store.start('test', 'chat', session['id'], data)
        branches = run_chat(engine, run, data)['branches']
        assert {branch['mode'] for branch in branches} == {'four_layer', 'deepagents'}
        for branch in branches:
            assert branch['status'] == 'complete' and branch['total_tokens'] == 0, branch['answer']
        return branches

    assert all(branch['memory_status'] == 'updated' for branch in ask('以后把S02叫做KFC'))
    expected_all = database.query('SELECT * FROM menu_item WHERE shop_cd=:shop ORDER BY 1', {'shop': 'S02'})['rows']
    expected_sale = [row for row in expected_all if row['item_cd'] != 'I049']
    assert len(expected_all) == 25 and len(expected_sale) == 24
    for prompt, expected in (
            ('查看KFC门店的菜单', expected_all),
            ('KFC出售的菜品有哪些', expected_sale),
            ('kfc都卖啥？', expected_sale),
            ('ＫＦＣ出售哪些菜品？', expected_sale),
            ('KFC菜单前3条', expected_all[:3]),
            ('KFC有什么菜', expected_all),
            ('巷口食堂菜单前3条', expected_all[:3]),
            ('S02店出售的菜品有哪些', expected_sale)):
        for branch in ask(prompt):
            evidence = store.get(branch['evidence_id'], 'test')
            assert evidence['payload']['result']['rows'] == expected, prompt
            if 'kfc' in prompt.casefold() or 'ＫＦＣ' in prompt:
                assert 'S02' in branch['answer'] and branch['used_refs'], prompt

    for prompt, enabled in (('KFC出售的菜品有哪些', False), ('SuperKFC出售的菜品有哪些', True)):
        for branch in ask(prompt, enabled=enabled):
            assert '请提供要查询的门店' in branch['answer'] and 'evidence_id' not in branch
    for branch in ask('KFC卖清汤牛肉面吗？'):
        evidence = store.get(branch['evidence_id'], 'test')
        assert evidence['payload']['params']['shop_cd'] == 'S02'
        assert evidence['payload']['result']['rows'] == []


@pytest.mark.parametrize('arguments', [
    'action=rows, table=price_hist, limit=-2',
    'action=rows, table=price_hist, offset=1.5',
    'action=rows, table=price_hist, limit=1000',
    'action=rows, table=price_hist, offset=0, offset=20',
    'action=count, table=price_hist, offset=3',
    'action=rows, table=price_hist, shop_cd=S01',
])
def test_invalid_explicit_catalog_tool_parameters_are_not_silently_dropped(arguments):
    from memory_demo.chat_catalog import catalog_request, explicit_tool_request

    text = f'请调用 read_catalog_table（{arguments}）'
    assert explicit_tool_request(text) is None
    assert catalog_request(text).action == 'clarify'


def test_model_cannot_turn_general_chat_into_preference_filtered_sql(tmp_path, monkeypatch):
    store = FileStore(tmp_path / 'memory')
    database = MealDB(tmp_path / 'catalog')
    database.initialize()
    engine = MealEngine(database, store=store)
    session = dict(id=uid('session'), engine='four_layer', memory_enabled=True, user_id='test',
                   title='测试', created_at=now())
    engine.conversations.write_session(session)

    def model(self, system, prompt, **kwargs):
        if kwargs.get('json_mode'):
            return {'meal_query': True, 'dish': '清汤牛肉面', 'updates': []}
        return '可以展开讲清汤牛肉面的做法。'

    monkeypatch.setattr('memory_demo.chat.Model.call', model)
    data = dict(user='test', session=session['id'], text='介绍一下清汤牛肉面的做法')
    run = store.start('test', 'chat', session['id'], data)
    [branch] = run_chat(engine, run, data)['branches']
    assert branch['status'] == 'complete' and 'params' not in branch and 'evidence_id' not in branch


def test_colloquial_catalog_plans_are_grounded_and_follow_own_session(tmp_path, monkeypatch):
    from memory_demo.catalog_language import PLAN_PROMPT

    store = FileStore(tmp_path / 'memory')
    database = MealDB(tmp_path / 'catalog')
    database.initialize()
    engine = MealEngine(database, store=store)
    session = dict(id=uid('session'), engine='parallel', memory_enabled=True, user_id='test',
                   title='测试', created_at=now())
    engine.conversations.write_session(session)
    calls = []

    def model(self, system, prompt, **kwargs):
        assert system == PLAN_PROMPT
        message = json.loads(prompt)['message']
        calls.append(message)
        plans = {
            '巷口那边现在能整点啥，前两条': dict(intent='menu', store='巷口', availability='available',
                                            availability_quote='现在能整点啥'),
            '接着看看后面三条': dict(intent='next_page', use_previous=True),
            '这家现在还能点啥': dict(intent='menu', use_previous=True, availability='available',
                                 availability_quote='现在还能点'),
            '清汤牛肉面要去哪个馆子点': dict(intent='dish_store', dish='清汤牛肉面'),
            '那道得掏几块银子': dict(intent='dish_price', use_previous=True),
            '这玩意儿在不在店里放着': dict(intent='menu', store='模型编造的门店'),
            '鸡饭里都放了些啥，能瞧瞧吗': dict(intent='dish_ingredients', dish='鸡饭'),
        }
        return plans[message]

    monkeypatch.setattr('memory_demo.chat.Model.call', model)
    monkeypatch.setattr('memory_demo.chat.deep_chat', lambda *a, **kw: pytest.fail('查库应使用同一份校验计划'))

    def ask(text, sid=session['id']):
        data = dict(user='test', session=sid, text=text)
        run = store.start('test', 'chat', sid, data)
        branches = run_chat(engine, run, data)['branches']
        assert {branch['mode'] for branch in branches} == {'four_layer', 'deepagents'}
        results = []
        for branch in branches:
            assert branch['status'] == 'complete' and 'params' not in branch, branch['answer']
            evidence = store.get(branch.get('evidence_id'), 'test')
            results.append(evidence['payload']['result']['rows'] if evidence else None)
        assert results[0] == results[1]
        return results[0], branches[0]['answer']

    catalog = database.query('SELECT * FROM menu_item WHERE shop_cd=:shop AND active_f=1 ORDER BY 1',
                             {'shop': 'S02'})['rows']
    assert ask('巷口那边现在能整点啥，前两条')[0] == catalog[:2]
    assert ask('接着看看后面三条')[0] == catalog[2:5]
    assert ask('这家现在还能点啥')[0] == catalog
    stores, _ = ask('清汤牛肉面要去哪个馆子点')
    assert [(row['item_cd'], row['shop_cd']) for row in stores] == [('I020', 'S01')]
    prices, _ = ask('那道得掏几块银子')
    assert prices and {row['item_cd'] for row in prices} == {'I020'}
    assert '原话' in ask('这玩意儿在不在店里放着')[1]
    assert '匹配多个菜品' in ask('鸡饭里都放了些啥，能瞧瞧吗')[1]
    fresh = dict(session, id=uid('session'))
    engine.conversations.write_session(fresh)
    assert '菜品名称或编号' in ask('那道得掏几块银子', fresh['id'])[1]
    assert '继续查看哪张表' in ask('接着看看后面三条', fresh['id'])[1]
    assert len(calls) == 9  # Identical branch inputs reuse one interpretation per turn.


@pytest.mark.parametrize(('text', 'code', 'name'), [
    ('以后把S03都叫做兰州拉面', 'S03', '兰州拉面'),
    ('今后把 s03 门店一律叫作兰州拉面。', 'S03', '兰州拉面'),
    ('以后 S03 这个店都叫兰州拉面', 'S03', '兰州拉面'),
    ('麻烦将 I025 的称呼统一改为「招牌饭」', 'I025', '招牌饭'),
    ('之后S03都改回原称呼', 'S03', None),
    ('把 S03 恢复为数据库登记名', 'S03', None),
])
def test_catalog_name_instruction_accepts_natural_variants(text, code, name):
    from memory_demo.catalog_names import NameEdit, parse_name_edit

    assert parse_name_edit(text) == NameEdit(code, name)


def test_catalog_alias_updates_survive_sessions_and_preserve_database_records(tmp_path, monkeypatch):
    from memory_demo.chat_memory import ChatMemory
    from memory_demo.store import uid

    store = FileStore(tmp_path / 'memory')
    database = MealDB(tmp_path / 'catalog')
    database.initialize()
    original = database.path.read_bytes()
    engine = MealEngine(database, store=store)
    monkeypatch.setattr('memory_demo.chat.Model.call', lambda *args, **kw: pytest.fail('应直接处理明确的称呼操作'))
    monkeypatch.setattr('memory_demo.chat.deep_chat', lambda *args, **kw: pytest.fail('应直接处理明确的称呼操作'))
    # Reproduce the two different keys saved by the old version.
    for mode, key in [('four_layer', 'preference:s03_store_alias'), ('deepagents', 'fact:s03_store_name')]:
        run = store.start('test', 'chat', 'old', {})
        original_text = '以后叫S03店为公共食堂'
        source = store.add('test', 1, 'user_message', '用户消息', original_text,
                           chat_engine=mode, run_id=run, session='old')
        memory = ChatMemory(store, 'test', mode)
        memory.commit(memory.current(True), [(key, '公共食堂', '公共食堂')], source, run)

    def turn(text, *, enabled=True):
        session = dict(id=uid('session'), engine='parallel', memory_enabled=enabled,
                       user_id='test', title='测试', created_at=now())
        engine.conversations.write_session(session)
        data = dict(user='test', session=session['id'], text=text)
        run = store.start('test', 'chat', session['id'], data)
        branches = run_chat(engine, run, data)['branches']
        assert all(branch['status'] == 'complete' for branch in branches), branches
        return branches

    for question in ('S03店是什么', 'S03叫什么', 'S03叫啥'):
        for branch in turn(question):
            assert '公共食堂' in branch['answer'] and '旧店（停用）' in branch['answer']
            assert branch['used_refs'] and branch['memory_read'] and branch['memory_status'] == 'unchanged'
            assert '公共食堂' not in store.get(branch['evidence_id'], 'test')['content']
    for branch in turn('以后把S03都叫做兰州拉面'):
        assert branch['memory_status'] == 'updated'
        assert '兰州拉面' in branch['answer']
    assert all('兰州拉面' in branch['answer'] and '公共食堂' not in branch['answer']
               for branch in turn('兰州拉面是哪家？'))
    assert all('兰州拉面' not in branch['answer'] for branch in turn('S03是什么', enabled=False))
    assert all(branch['memory_status'] == 'disabled' for branch in turn('以后S03叫临时食堂', enabled=False))
    assert all(branch['memory_status'] == 'unchanged' and '这轮没有修改' in branch['answer']
               for branch in turn('假设以后把S03都叫做假设食堂'))
    assert all('兰州拉面' in branch['answer'] for branch in turn('S03是什么店'))
    assert all(branch['memory_status'] == 'updated' for branch in turn('取消S03店的叫法称呼'))
    assert all('兰州拉面' not in branch['answer'] and '公共食堂' not in branch['answer']
               for branch in turn('S03是什么'))
    assert all(branch['memory_status'] == 'updated' for branch in turn('以后把 I025 菜品叫作招牌辣饭'))
    for branch in turn('I025是哪个菜？'):
        assert '招牌辣饭' in branch['answer'] and '麻辣鸡肉饭' in branch['answer']
        assert branch['used_refs']
    assert database.path.read_bytes() == original


def test_old_catalog_edits_are_repaired_without_overwriting_newer_names(tmp_path):
    from memory_demo.catalog_names import names_for_catalog, repair_catalog_names
    from memory_demo.chat_memory import ChatMemory

    store = FileStore(tmp_path / 'memory')
    mode = 'deepagents'
    memory = ChatMemory(store, 'test', mode)

    def historical(text, change=None):
        run = store.start('test', 'chat', 'test-session', {})
        source = store.add('test', 1, 'user_message', '用户消息', text, session='test-session', run_id=run,
                           chat_engine=mode)
        if change:
            memory.commit(memory.current(True), [(*change, text)], source, run)
        store.finish(run, {'branches': [{'mode': mode, 'status': 'complete',
                                         'memory_status': 'updated' if change else 'unchanged'}]})

    historical('以后叫S03店为沙县小吃', ('preference:catalog_name.S03', '沙县小吃'))
    historical('之后S03都改回原称呼', ('fact:old_shop_name', '原称呼'))
    historical('以后把S03都叫做兰州拉面')
    historical('以后叫S02店为社区小馆', ('preference:catalog_name.S02', '社区小馆'))
    historical('取消S02店的叫法称呼')
    historical('取消S01的别名')
    historical('以后叫S01为街坊食堂', ('preference:catalog_name.S01', '街坊食堂'))
    repair_catalog_names(store)
    current = memory.current(True)
    names = names_for_catalog(store, 'test', current['entries'])
    assert names['S03']['value'] == '兰州拉面' and 'fact:old_shop_name' not in current['entries']
    assert 'S02' not in names and names['S01']['value'] == '街坊食堂'
    revision = memory.current(True)['id']
    repair_catalog_names(store)
    assert memory.current(True)['id'] == revision


def test_meal_and_fact_removals_and_replacements_are_verified_across_sessions(tmp_path, monkeypatch):
    from memory_demo.chat_memory import ChatMemory, criteria
    from memory_demo.meal_rules import NEUTRAL

    store = FileStore(tmp_path/'memory')
    database = MealDB(tmp_path/'catalog')
    database.initialize()
    engine = MealEngine(database, store=store)
    mock_reply = lambda *a, **kw: (dict(answer='已经删除。'), [], [], [])
    monkeypatch.setattr('memory_demo.chat.four_layer', mock_reply)
    monkeypatch.setattr('memory_demo.chat.deep_chat', mock_reply)

    def turn(text, enabled=True):
        session = dict(id=uid('session'), engine='parallel', memory_enabled=enabled, user_id='test',
                       title='测试', created_at=now())
        engine.conversations.write_session(session)
        data = dict(user='test', session=session['id'], text=text)
        run = store.start('test', 'chat', session['id'], data)
        return run_chat(engine, run, data)['branches']

    for mode in ('four_layer', 'deepagents'):
        memory = ChatMemory(store,'test',mode)
        run = store.start('test', 'chat', 'old', {})
        source = store.add('test', 1, 'user_message', '用户消息', '预算80块，我家猫叫年糕。',
                           run_id=run, session='old', chat_engine=mode)
        memory.commit(memory.current(True), [('meal:any:budget', 80, '预算80块'),
                                               ('meal:any:kcal_max', 450, '热量不超过450千卡'),
                                               ('fact:pet_name', '年糕', '我家猫叫年糕')], source, run)
    assert all(b['memory_status']=='updated' for b in turn('取消午饭的热量上限'))
    assert all(b['memory_status']=='updated' for b in turn('忘掉年糕这个名字'))
    unknown = turn('忘掉我留的密码')
    assert all(b['memory_status']=='unchanged' and '没有找到能确认' in b['answer'] for b in unknown)
    assert all(b['memory_status']=='disabled' for b in turn('取消晚饭热量上限', enabled=False))
    for mode in ('four_layer', 'deepagents'):
        entries = ChatMemory(store,'test',mode).current(True)['entries']
        lunch,_ = criteria(entries,'lunch','中午吃什么？')
        dinner,_ = criteria(entries,'dinner','晚上吃什么？')
        assert lunch['budget']==80 and lunch['kcal_max']==NEUTRAL['kcal_max']
        assert dinner['kcal_max']==450 and 'fact:pet_name' not in entries
    assert all(b['memory_status']=='updated' for b in turn('以后午饭热量不超过520千卡。'))
    for mode in ('four_layer', 'deepagents'):
        entries = ChatMemory(store,'test',mode).current(True)['entries']
        assert 'meal_reset:lunch:kcal_max' not in entries
        assert criteria(entries,'lunch','中午吃什么？')[0]['kcal_max']==520


def test_chat_saves_clear_preferences_then_uses_scope_and_ignores_temporary(tmp_path, monkeypatch):
    store = FileStore(tmp_path / 'memory')
    database = MealDB(tmp_path / 'catalog')
    database.initialize()
    engine = MealEngine(database, store=store)

    def model(self, system, prompt, **kwargs):
        if not kwargs.get('json_mode'):
            return '好的。'
        message = json.loads(prompt)['message']
        if '清淡点' in message:
            raise ValueError('模型输出不完整')
        return dict(meal_query='吃什么' in message, updates=[
            dict(category='meal', quote=message)
        ] if '预算' in message or '今天想吃辣' in message else [])

    monkeypatch.setattr('memory_demo.chat.Model.call', model)

    def turn(text, *, memory=True):
        session = dict(id=uid('session'), engine='four_layer', memory_enabled=memory,
                       user_id='test', title='测试', created_at=now())
        engine.conversations.write_session(session)
        data = dict(user='test', session=session['id'], text=text)
        run = store.start('test', 'chat', session['id'], data)
        return run_chat(engine, run, data)['branches'][0]

    assert turn('以后午饭喜欢吃辣，预算73块，热量470到610千卡。')['memory_status'] == 'updated'
    assert turn('以后晚饭喜欢吃辣，预算500块，热量不超过1000千卡。')['memory_status'] == 'updated'
    assert turn('今天想吃辣。')['memory_status'] == 'unchanged'
    update = turn('以后中饭我不吃辣，清淡点，热量不超过500千卡。')
    assert update['memory_status'] == 'updated'
    assert 'params' not in update
    assert '热量≤500千卡、不辣' in update['answer'] and '无法据此核验油盐' in update['answer']
    lunch = turn('中午吃什么？')
    dinner = turn('晚上吃什么？')
    control = turn('晚上吃什么？', memory=False)
    assert lunch['params']['budget'] == 73 and lunch['params']['max_spice'] == lunch['params']['min_spice'] == 0
    assert lunch['params']['kcal_min'] == 0 and lunch['params']['kcal_max'] == 500
    assert lunch['approved'] and all(row['hot_lv']==0 and row['kcal_hi']<=500 for row in lunch['approved'])
    assert dinner['params']['budget'] == 500 and dinner['params']['kcal_min'] == 0 and dinner['params']['min_spice'] == 1
    assert control['params']['budget'] == 120 and not control['used_refs'] and control['memory_status'] == 'disabled'
