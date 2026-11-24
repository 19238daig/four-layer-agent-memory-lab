"""Opt-in real-service acceptance run, isolated from the user's demo space."""
import json
import time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'artifacts'/'live-validation.json'
REPORT.parent.mkdir(exist_ok=True)
client=httpx.Client(base_url='http://127.0.0.1:8010',timeout=20,trust_env=False)
results=[]


def run(action,session='day1',text='',**extra):
    response=client.post('/api/operations',json=dict(action=action,user='walkthrough',session=session,text=text,**extra))
    response.raise_for_status()
    run_id=response.json()['run_id']
    print(action,run_id,flush=True)
    started=time.monotonic()
    while True:
        response=client.get('/api/runs/'+run_id,params={'user':'walkthrough'});response.raise_for_status()
        obj=response.json()
        if obj['status']!='running':break
        if time.monotonic()-started>1200:raise TimeoutError(run_id)
        time.sleep(1)
    results.append(obj)
    REPORT.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    if obj['status']!='complete':raise RuntimeError(obj['error'])
    print('  complete',round(time.monotonic()-started,1),'s',flush=True)
    return obj


run('record',text='我平时不吃辣，午饭最好控制在80块以内。')
run('record',text='给我建议的时候，简单列两三条就好。')
run('distill')
run('dream')
run('context','day2')
first=run('ask','day2','周末午饭吃点什么比较合适？')
assert first['result']['cited_ids'],'First answer did not cite supplied memory'
run('record','day3','以后午饭预算改成120块吧，还是不吃辣。')
run('distill','day3')
run('dream')
updated=run('ask','day4','明天中午帮我想两种吃法。')
run('record','day5','对了，我家猫叫年糕。')
raw=run('ask','day6','我家猫叫什么来着？')
assert '年糕' in raw['result']['answer'],'Transcript fallback failed'
assert any(x.startswith('T-') for x in raw['result']['cited_ids']),'No transcript citation'
irrelevant=run('ask','day7','为什么天空看起来是蓝色的？')
assert not irrelevant['result']['read_ids'],'Unrelated question retrieved personal memory'
replay=run('replay',source_run=raw['id'])
assert all(e['data'].get('replay') for e in replay['events'] if e['type']=='model_response')
comparison=run('compare',text='周末午饭吃点什么比较合适？')
assert len(comparison['result']['comparison'])==3
assert all(x['status']=='complete' for x in comparison['result']['comparison']),comparison['result']['comparison']
print('LIVE ACCEPTANCE PASSED',flush=True)
