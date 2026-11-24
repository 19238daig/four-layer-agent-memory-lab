from typing import Literal
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from .meal_db import MealDB,QUERY,SQL_ROOT
from .meal_engine import MealEngine
from .llm import safe_error
from .file_store import FileStore, ROOT
import threading

router=APIRouter(prefix='/api/meal',tags=['独立热量选餐实验室'])
db=MealDB()
_engine=None
_lock=threading.Lock()


def get_engine():
    global _engine
    if not db.ready:raise HTTPException(409,'请先初始化专用模拟数据库。')
    with _lock:
        if _engine is None:
            engine=MealEngine(db, store=FileStore(ROOT / 'meal', db.root / 'memory.sqlite3'))
            from .chat_memory import repair_chat_heat, repair_chat_meal_scope
            from .catalog_names import repair_catalog_names
            repair_chat_heat(engine.store)
            repair_chat_meal_scope(engine.store)
            repair_catalog_names(engine.store)
            _engine=engine
    return _engine


class MealOperation(BaseModel):
    action:Literal['remember','generate','execute_sql','meal_compare','test_session']
    user:str=Field(default='meal-demo',min_length=1,max_length=80,pattern=r'^[\w\-]+$')
    session:str=Field(default='new-session',min_length=1,max_length=80,pattern=r'^[\w\-]+$')
    text:str=Field(default='',max_length=10000)
    plan_id:str=Field(default='',max_length=80)
    sql:str=Field(default='',max_length=60000)
    selected_item:str=Field(default='',max_length=80)
    fresh_learn:bool=False
    include_baseline:bool=True
    memory_title:str=Field(default='',max_length=100)
    save_mode:Literal['replace','update']='replace'


class SessionRequest(BaseModel):
    user:str=Field(default='meal-demo',min_length=1,max_length=80,pattern=r'^[\w\-]+$')
    title:str=Field(default='',max_length=100)
    memory_id:str=Field(default='',max_length=80)
    session:str=Field(default='',max_length=80)


@router.get('/spaces')
def spaces():
    return get_engine().conversations.spaces() if db.ready else []


def mutation_engine(user):
    e=get_engine()
    if any(r['status']=='running' for r in e.store.runs(user)):raise HTTPException(409,'当前空间有操作正在执行，完成后再切换或保存。')
    return e


@router.post('/sessions')
def create_session(body:SessionRequest):
    try:
        e=mutation_engine(body.user)
        with e.lock:return e.conversations.create(body.user,body.title,body.memory_id)
    except ValueError as exc:raise HTTPException(422,safe_error(exc))


@router.post('/memories')
def save_memory(body:SessionRequest):
    try:
        e=mutation_engine(body.user)
        with e.lock:
            s,memory,notes,reps=e.conversations.view(body.user,body.session)
            if not any(n['payload'].get('condition') for n in notes):raise ValueError('当前会话没有可保存的饮食记忆，请先保存偏好。')
            if memory and (memory.get('validation_warning') or memory['payload'].get('criteria_version',0)<2):raise ValueError('旧版本尚未完成校准，请在第一步从原话重新保存，不能直接复制为已核验版本。')
            return e.conversations.save(body.user,body.title or '手动保存的饮食记忆',notes,reps,session=s['id'],
                criteria_version=memory['payload'].get('criteria_version',0) if memory else 0,
                save_mode=memory['payload'].get('save_mode','replace') if memory else 'replace',
                source_record_id=memory['payload'].get('source_record_id') if memory else None)
    except ValueError as exc:raise HTTPException(422,safe_error(exc))


@router.get('/database')
def database():
    try:return {**db.info(), 'memory_path': str(ROOT / 'meal')}
    except Exception as exc:raise HTTPException(409,safe_error(exc))


@router.post('/initialize')
def initialize():
    try:
        result=db.initialize();get_engine()
        return result
    except Exception as exc:raise HTTPException(409,safe_error(exc))


@router.get('/table/{table}')
def browse(table:str,offset:int=0):
    try:return db.browse(table,max(0,offset))
    except Exception as exc:raise HTTPException(400,safe_error(exc))


@router.get('/state')
def state(user:str='meal-demo',session:str=''):
    if not db.ready:return dict(objects=[],runs=[],sessions=[],edges=[],conditions={})
    e=get_engine()
    try:
        selected=e.conversations.session(user,session) if session else e.conversations.bootstrap(user)
        if not selected:raise ValueError('会话不存在或属于另一个记忆空间。')
        s,memory,notes,reps=e.conversations.view(user,selected['id'])
        data=e.state(user);active={o['id'] for o in notes+reps}
        for obj in data['objects']:obj['active']=obj['id'] in active
        return {**data,'conditions':e.current(user,s['id'])[0],'current_session':s,'selected_memory':memory,
                'session_list':e.conversations.sessions(user),'memory_snapshots':e.conversations.memories(user)}
    except ValueError as exc:raise HTTPException(404,safe_error(exc))


@router.post('/operations',status_code=202)
def operation(body:MealOperation):
    if body.action in ['remember','generate','meal_compare','test_session'] and not body.text.strip():raise HTTPException(422,'请输入日常消息或问题。')
    if body.action=='execute_sql' and not body.plan_id:raise HTTPException(422,'请先生成SQL计划。')
    return dict(run_id=get_engine().submit(body.action,body.model_dump(exclude={'action'})))


@router.get('/runs/{run_id}')
def run(run_id:str,user:str='meal-demo'):
    e=get_engine();r=e.store.run(run_id,user)
    if not r:raise HTTPException(404,'当前场景没有这次运行。')
    return {**r,'events':e.store.events(run_id=run_id,user=user)}


@router.get('/artifacts/{artifact_id}')
def artifact(artifact_id:str,user:str='meal-demo',comparison_run:str=''):
    obj=get_engine().store.get(artifact_id,user)
    if not obj:raise HTTPException(404,'当前场景没有这条来源。')
    return obj


@router.get('/download/{kind}')
def download(kind:str):
    files={'schema':SQL_ROOT/'schema.sql','query':SQL_ROOT/'query.sql','catalog':db.root/'catalog-reproducible.sql'}
    path=files.get(kind)
    if path is None or not path.is_file():raise HTTPException(404,'文件不存在，请先初始化。')
    return FileResponse(path,filename=path.name,media_type='text/plain; charset=utf-8')
