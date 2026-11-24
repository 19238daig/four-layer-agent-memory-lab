"""Memory invariants, independent of any external model service."""
import json
from memory_demo.engine import Engine
from memory_demo.store import Store
from memory_demo.llm import parse_json


def make_engine(tmp_path):
    return Engine(Store(tmp_path/'test.sqlite3'))


def record(e,text,session='day1'):
    run=e.store.start('test','record',session,{'text':text})
    result=e.do_record(run,{'user':'test','session':session,'text':text})
    e.store.finish(run,result)
    return result['artifacts'][0]


def distill(e,monkeypatch,message_id,value,quote,session='day1'):
    result={'notes':[{'key':'diet.lunch_budget','topic':'diet','title':'午饭预算','value':value,
                      'importance':4,'evidence':[{'id':message_id,'quote':quote}]}]}
    monkeypatch.setattr('memory_demo.engine.Model.call',lambda *a,**kw:result)
    run=e.store.start('test','distill',session,{})
    return e.do_distill(run,{'user':'test','session':session})


def test_update_keeps_old_version_and_evidence(tmp_path,monkeypatch):
    e=make_engine(tmp_path)
    one=record(e,'午饭80块以内')
    first=distill(e,monkeypatch,one,'午饭预算80元','午饭80块以内')['artifacts'][0]
    original=e.store.get(first)
    two=record(e,'改成120块吧','day2')
    second=distill(e,monkeypatch,two,'午饭预算120元','改成120块吧','day2')['artifacts'][0]
    assert e.store.get(first)==original
    assert e.store.heads('test','note')[0]['id']==second
    assert e.store.get(second)['payload']['supersedes']==first
    assert e.store.get(second)['payload']['refs']==[two]
    assert e.store.get(second)['payload']['version']==2


def test_invalid_evidence_writes_no_notes(tmp_path,monkeypatch):
    import pytest
    e=make_engine(tmp_path)
    one=record(e,'午饭80块以内')
    with pytest.raises(ValueError,match='原文校验'):
        distill(e,monkeypatch,one,'预算200元','原文不存在的摘录')
    assert not e.store.heads('test','note')
    assert e.store.unprocessed('test','day1')


def test_duplicate_distill_is_idempotent(tmp_path,monkeypatch):
    e=make_engine(tmp_path)
    one=record(e,'午饭80块以内')
    distill(e,monkeypatch,one,'午饭预算80元','午饭80块以内')
    monkeypatch.setattr('memory_demo.engine.Model.call',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Must not call model')))
    e.do_distill('irrelevant',{'user':'test','session':'day1'})
    assert len(e.store.objects('test',layer=2))==1


def test_cross_session_context_does_not_include_old_chat(tmp_path,monkeypatch):
    e=make_engine(tmp_path)
    record(e,'私密的旧会话全文：我家猫叫年糕')
    captured=[]
    def fake(self,system,prompt,**kwargs):
        captured.append((system,prompt))
        if kwargs.get('json_mode'): return {'topics':[],'search_terms':[],'reason':'常识问题'}
        return '天空因光的散射而呈蓝色。'
    monkeypatch.setattr('memory_demo.engine.Model.call',fake)
    run=e.store.start('test','ask','new',{})
    result=e.do_ask(run,{'user':'test','session':'new','text':'天空为什么蓝？'})
    answer_prompt=json.loads(captured[-1][1])
    assert answer_prompt['current_session_history']==[]
    assert answer_prompt['retrieved_memory']==[]
    assert '私密的旧会话全文' not in captured[-1][1]
    assert not result['cited_ids']


def test_unknown_answer_citations_not_counted(tmp_path,monkeypatch):
    e=make_engine(tmp_path)
    def fake(self,system,prompt,**kw):
        return {'topics':[],'search_terms':[]} if kw.get('json_mode') else '我猜是这样 [N-deadbeef00]'
    monkeypatch.setattr('memory_demo.engine.Model.call',fake)
    run=e.store.start('test','ask','new',{})
    result=e.do_ask(run,{'user':'test','session':'new','text':'你好'})
    assert result['cited_ids']==[]
    assert e.store.get(result['answer_id'])['payload']['invalid_citations']==['N-deadbeef00']


def test_transcript_search_and_scope_isolation(tmp_path):
    e=make_engine(tmp_path)
    one=record(e,'我家猫叫年糕')
    e.do_record('x',{'user':'other','session':'a','text':'我家猫叫汤圆'})
    assert [x['id'] for x in e.search('test',['猫','名字'])]==[one]
    assert e.store.get(one,'other') is None


def test_json_code_fence():
    assert parse_json('```json\n{"notes": []}\n```')=={'notes':[]}


def test_persistence_and_interrupted_run_recovery(tmp_path):
    e=make_engine(tmp_path)
    original=record(e,'我家猫叫年糕')
    interrupted=e.store.start('test','ask','new',{})
    restored=Store(tmp_path/'test.sqlite3')
    restored.recover_interrupted()
    assert restored.get(original)['content']=='我家猫叫年糕'
    assert restored.run(interrupted,'test')['status']=='failed'
    assert restored.run(interrupted,'other') is None


def test_nested_wiki_citation_is_available_evidence(tmp_path,monkeypatch):
    e=make_engine(tmp_path)
    raw=record(e,'不吃辣')
    note=e.store.add('test',2,'note','口味','不吃辣',refs=[raw],key='diet.spice',topic='diet')
    e.store.set_head('test','note','diet.spice',note['id'])
    page=e.store.add('test',3,'representation','饮食',f"不吃辣 [{note['id']}]",refs=[note['id']],topic='diet')
    e.store.set_head('test','representation','diet',page['id'])
    def fake(self,system,prompt,**kw):
        if kw.get('json_mode'):return {'topics':['diet'],'search_terms':[]}
        assert note['id'] in json.loads(prompt)['allowed_citation_ids']
        return f"可以吃清淡的菜 [{note['id']}]"
    monkeypatch.setattr('memory_demo.engine.Model.call',fake)
    run=e.store.start('test','ask','new',{})
    result=e.do_ask(run,dict(user='test',session='new',text='午饭吃什么'))
    assert result['cited_ids']==[note['id']]
