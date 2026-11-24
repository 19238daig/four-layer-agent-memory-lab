"""Real Deep Agents comparison, isolated per run; no scripted answers."""
import os
import time
import httpx
from pathlib import Path
from .config import DATA_DIR, MODEL, BASE_URL, MODEL_EXTRA_BODY
from .llm import Model, safe_error
from .engine import ANSWER


def compare(engine,run,d):
    store=engine.store
    user=d.get('user','demo')
    question=d.get('text','周末午饭吃点什么比较合适？')
    # Replay exactly the explicit record inputs. Prior generated answers/questions are excluded.
    records=store.recordings(user)
    if not records:
        raise ValueError('没有可对比的录入消息。请先 record 至少一条日常偏好。')
    rows=[]
    config=dict(model=MODEL,question=question,training_message_ids=[x['id'] for x in records],
        note='同模型、相同录入消息顺序、新会话、独立记忆空间；框架提示词和工具不同。字符数不是token数。')
    engine.step(run,'对比配置',config,dict(training_messages=[x['content'] for x in records]))
    for mode in ['stateless','four_layer','deepagents']:
        start=time.perf_counter()
        before=len(store.events(run_id=run))
        try:
            if mode=='stateless':
                answer=Model(store,run).call(ANSWER,question,purpose='无记忆基线 · 新会话回答',max_tokens=6000)
                row=dict(mode=mode,answer=answer,memory_chars=0,training_calls=0)
            elif mode=='four_layer':
                scope=f'{user}::compare::{run}'
                sessions=[]
                for i,x in enumerate(records):
                    session=f'compare-learn-{i}'
                    engine.do_record(run,dict(user=scope,session=session,text=x['content']))
                    sessions.append(session)
                for session in sessions:
                    engine.do_distill(run,dict(user=scope,session=session))
                engine.do_dream(run,dict(user=scope))
                result=engine.do_ask(run,dict(user=scope,session='compare-new-session',text=question))
                row=dict(mode=mode,answer=result['answer'],memory_chars=result['memory_chars'],
                    scope=scope,cited_ids=result['cited_ids'],answer_id=result['answer_id'])
            else:
                row=deepagents_run(engine,run,records,question)
            row['status']='complete'
        except Exception as exc:
            row=dict(mode=mode,status='failed',error=safe_error(exc),answer='',memory_chars=None)
        events=store.events(run_id=run)[before:]
        responses=[e['data'] for e in events if e['type']=='model_response']
        usage=[]
        for response in responses:
            u=response.get('usage') or {}
            total=u.get('total_tokens')
            if total is not None: usage.append(total)
        row.update(elapsed_ms=round((time.perf_counter()-start)*1000),model_calls=len(responses),
                   total_tokens=sum(usage) if usage else None,token_measurement='provider' if usage else 'unavailable',
                   tool_calls=sum(e['type']=='deepagents_tool' and e['data'].get('phase')=='start' for e in events))
        rows.append(row)
        store.event(run,'comparison_result',row)
    return dict(comparison=rows,config=config,message='比较已完成；各分支失败会独立显示，不会伪造结果。')


def deepagents_run(engine,run,records,question):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_openai import ChatOpenAI
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import HumanMessage
    from .file_checkpoint import FileCheckpoint

    store=engine.store
    root=(DATA_DIR/'deepagents'/run).resolve()
    root.mkdir(parents=True,exist_ok=True)
    memory=root/'AGENTS.md'
    memory.write_text('# 用户记忆\n\n暂无已记录的偏好。\n',encoding='utf-8')
    phase={'name':'training'}

    class Audit(BaseCallbackHandler):
        def on_chat_model_start(self,serialized,messages,**kwargs):
            blocks=[[dict(role=m.type,content=m.content) for m in group] for group in messages]
            store.event(run,'model_request',dict(purpose='Deep Agents · '+phase['name'],model=MODEL,messages=blocks))

        def on_llm_end(self,response,**kwargs):
            message=response.generations[0][0].message
            store.event(run,'model_response',dict(purpose='Deep Agents · '+phase['name'],model=MODEL,
                content=message.content,usage=getattr(message,'usage_metadata',None),
                tool_calls=getattr(message,'tool_calls',[])))

        def on_tool_start(self,serialized,input_str,**kwargs):
            store.event(run,'deepagents_tool',dict(phase='start',stage=phase['name'],
                        tool=(serialized or {}).get('name','tool'),input=input_str))

        def on_tool_end(self,output,**kwargs):
            store.event(run,'deepagents_tool',dict(phase='end',stage=phase['name'],output=str(output)))

    model=ChatOpenAI(model=MODEL,base_url=BASE_URL,api_key=os.getenv('OPENAI_API_KEY'),
        timeout=90,max_retries=1,temperature=0.1,max_tokens=6000,stream_usage=False,
        http_client=httpx.Client(trust_env=False),extra_body=MODEL_EXTRA_BODY)
    backend=FilesystemBackend(root_dir=str(root),virtual_mode=True)
    before=memory.read_text(encoding='utf-8')
    with FileCheckpoint(root/'checkpoints.json') as saver:
        agent=create_deep_agent(model=model,backend=backend,checkpointer=saver,memory=['/AGENTS.md'],
            system_prompt=ANSWER+'\n你在一个本地记忆演示中。学习阶段收到用户的日常偏好后，请先使用 edit_file 更新 /AGENTS.md，保存简洁事实，纠正时替换旧值。记录来源 T-ID（消息附带）。回答阶段根据已有记忆回答，不需要再更新文件。只保存材料中明确表达的信息。',
            subagents=[])
        audit=Audit()
        for i,x in enumerate(records):
            agent.invoke({'messages':[HumanMessage(content=f"{x['content']}\n（此消息来源：{x['id']}）")]},
                         config={'configurable':{'thread_id':f'learn-{i}'},'callbacks':[audit],'recursion_limit':32})
            after=memory.read_text(encoding='utf-8')
            engine.step(run,'Deep Agents · 记忆文件变化',dict(source=x['id'],before=before),
                        dict(path='/AGENTS.md',after=after,changed=before!=after),[x['id']])
            before=after
        phase['name']='new_session'
        actual_memory=memory.read_text(encoding='utf-8')
        engine.step(run,'Deep Agents · 新会话加载记忆',dict(path='/AGENTS.md'),dict(content=actual_memory,char_count=len(actual_memory)))
        result=agent.invoke({'messages':[HumanMessage(content=question)]},
            config={'configurable':{'thread_id':'answer-new-session'},'callbacks':[audit],'recursion_limit':32})
    last=result['messages'][-1]
    return dict(mode='deepagents',answer=last.content,memory_chars=len(actual_memory),
                memory_file=actual_memory,backend='FilesystemBackend(virtual_mode=True)',
                changed_from_empty=actual_memory!='# 用户记忆\n\n暂无已记录的偏好。\n',
                note='真实 deepagents 执行。来源追踪由本 Demo 的 callback 添加。记忆文件与 checkpoint 在本地持久化。')
