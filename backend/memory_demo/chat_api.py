from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import MODEL
from .file_store import read_json
from .meal_api import db, get_engine
from .store import now, uid

router = APIRouter(prefix='/api/chat')


def with_progress(store, run):
    if run['status'] != 'running':
        return run
    phases = {}
    branches = []
    for event in store.events(run_id=run['id'], limit=10000):
        data = event['data']
        mode = data.get('comparison_mode')
        if not mode:
            continue
        if event['type'] == 'chat_progress':
            phases[mode] = data['phase']
        elif event['type'] == 'chat_branch_result':
            branches.append(data)
    return {**run, 'progress': phases, 'result': {'branches': branches}}


class NewSession(BaseModel):
    user: str = Field(default='meal-demo', min_length=1, max_length=80, pattern=r'^[\w-]+$')
    engine: Literal['four_layer', 'deepagents', 'parallel'] = 'four_layer'
    memory_enabled: bool = True


class Turn(BaseModel):
    user: str = Field(default='meal-demo', min_length=1, max_length=80, pattern=r'^[\w-]+$')
    session: str = Field(pattern=r'^session-[a-f0-9]{10}$')
    request_id: str = Field(pattern=r'^[a-f0-9-]{32,36}$')
    text: str = Field(min_length=1, max_length=10000)


@router.get('/sessions')
def sessions(user: str = 'meal-demo'):
    if not db.ready:
        db.initialize()
    engine = get_engine()
    conversations = engine.conversations.sessions(user)
    return dict(sessions=[s for s in conversations if 'engine' in s],
                root=str(engine.store.workspace(user)), model=MODEL)


@router.post('/sessions', status_code=201)
def create(body: NewSession):
    engine = get_engine()
    with engine.store.lock:
        session = dict(**body.model_dump(), id=uid('session'), user_id=body.user,
                       title='新会话', memory_id=None, created_at=now())
        engine.conversations.write_session(session)
    return session


@router.get('/sessions/{session_id}')
def conversation(session_id: str, user: str = 'meal-demo'):
    engine = get_engine()
    session = engine.conversations.session(user, session_id)
    if not session or 'engine' not in session:
        raise HTTPException(404, '找不到这个聊天会话。')
    with engine.store.lock:
        turns = sorted((r for r in engine.store.run_index.values()
                        if r['user_id'] == user and r['session'] == session_id and r['action'] == 'chat'),
                       key=lambda r: r['created_at'])
        turns = [with_progress(engine.store, run) for run in turns]
    repairs = []
    for name in ('chat-heat-v2.json','chat-scope-v1.json'):
        repairs.extend(read_json(engine.store.path / name, {}).get('repairs',[]))
    repaired_versions = {repair.get('previous_revision'):repair for repair in repairs if repair['user']==user}
    for index, turn in enumerate(turns):
        branches = turn['result'].get('branches', [])
        updated = []
        for branch in branches:
            repair = repaired_versions.get(branch.get('memory_read'))
            params = branch.get('params')
            superseded = (repair and params and turn['created_at']>=repair['effective_from']
                          and (not repair.get('scope') or params.get('meal_period')==repair['scope']))
            updated.append({**branch,'memory_recalibrated':True} if superseded else branch)
        if updated:
            turns[index] = {**turn,'result':{**turn['result'],'branches':updated}}
    return dict(session=session, turns=turns)


@router.delete('/sessions/{session_id}')
def delete_session(session_id: str, user: str = 'meal-demo'):
    engine = get_engine()
    with engine.store.lock:
        session = engine.conversations.session(user, session_id)
        if not session or 'engine' not in session:
            raise HTTPException(404, '找不到这个聊天会话。')
        if any(r['user_id']==user and r['session']==session_id and r['status']=='running'
               for r in engine.store.run_index.values()):
            raise HTTPException(409, '请等这轮对话结束后再删除。')
        engine.conversations.write_session({**session, 'deleted_at':now()})
    return {'deleted':session_id}


@router.post('/turns', status_code=202)
def submit(body: Turn):
    engine = get_engine()
    data = body.model_dump()
    data['text'] = data['text'].strip()
    if not data['text']:
        raise HTTPException(422, '请输入消息。')
    with engine.store.lock:
        session = engine.conversations.session(body.user, body.session)
        if not session or 'engine' not in session:
            raise HTTPException(404, '找不到这个聊天会话。')
        for run in engine.store.run_index.values():
            if run['user_id'] == body.user and run['action'] == 'chat' and run['input'].get('request_id') == body.request_id:
                if run['input'] != data:
                    raise HTTPException(409, '这条请求已用于另一条消息。')
                return {'run_id': run['id']}
        if any(r['user_id'] == body.user and r['status'] == 'running' for r in engine.store.run_index.values()):
            raise HTTPException(409, '当前空间还有一轮对话正在处理，请等它完成。')
        if session['title'] == '新会话':
            engine.conversations.write_session({**session, 'title': data['text'][:28]})
        return {'run_id': engine.submit('chat', data)}


@router.get('/runs/{run_id}')
def details(run_id: str, user: str = 'meal-demo'):
    engine = get_engine()
    run = engine.store.run(run_id, user)
    if not run or run['action'] != 'chat':
        raise HTTPException(404, '找不到本轮运行。')
    run = with_progress(engine.store, run)
    from .chat_memory import ChatMemory
    output = {}
    for branch in run['result'].get('branches', []):
        mode = branch['mode']
        memory = ChatMemory(engine.store, user, mode)
        versions = []
        for revision in dict.fromkeys([branch.get('memory_read'), branch.get('memory_revision')]):
            if revision:
                version = read_json(memory.root / 'chat_versions' / f'{revision}.json')
                if version:
                    body = memory.root / version['markdown']
                    versions.append(dict(id=revision, path=str(body), content=body.read_text(encoding='utf-8')))
        ids = [*branch.get('context_ids', []), *branch.get('used_refs', []), branch.get('answer_id'),
               branch.get('evidence_id')]
        for change in branch.get('changes', []):
            ids.extend([change['id'], change['source']])
        events = [e for e in engine.store.events(run_id=run_id, user=user, limit=10000)
                  if e['data'].get('comparison_mode') == mode]
        artifacts = {}
        def visit(artifact_id):
            if not artifact_id or artifact_id in artifacts or len(artifacts) >= 100:
                return
            obj = engine.store.get(artifact_id, user)
            if obj:
                artifacts[artifact_id] = obj
                for ref in obj['payload'].get('refs', []):
                    visit(ref)
        for artifact_id in ids:
            visit(artifact_id)
        output[mode] = dict(versions=versions, artifacts=list(artifacts.values()), events=events,
                            timings=branch.get('timings', {}),
                            tokens={k: branch.get(k) for k in ('input_tokens', 'output_tokens', 'total_tokens')})
    return dict(branches=output)
