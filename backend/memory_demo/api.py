import asyncio
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import MODEL, ROOT
from .engine import Engine

engine=Engine()
@asynccontextmanager
async def lifespan(app):
    engine.store.recover_interrupted()
    yield

app=FastAPI(title='Memory Lab',version='0.1.0',lifespan=lifespan)
from .meal_api import router as meal_router
app.include_router(meal_router)
from .chat_api import router as chat_router
app.include_router(chat_router)


class Operation(BaseModel):
    action: Literal['record','distill','dream','context','ask','compare','replay']
    user: str=Field(default='demo',min_length=1,max_length=80,pattern=r'^[\w\-]+$')
    session: str=Field(default='day1',min_length=1,max_length=80,pattern=r'^[\w\-]+$')
    text: str=Field(default='',max_length=10000)
    source_run: str=''
    scenario: str='lunch'


@app.get('/api/health')
def health():
    return dict(ok=True,app='memory-lab',model=MODEL)


@app.post('/api/operations',status_code=202)
def operation(body:Operation):
    if body.action in ['record','ask','compare'] and not body.text.strip():
        raise HTTPException(422,'请输入消息或问题。')
    if body.action=='replay' and not body.source_run:
        raise HTTPException(422,'请选择要回放的运行。')
    return dict(run_id=engine.submit(body.action,body.model_dump(exclude={'action'})))


@app.get('/api/state')
def state(user:str='demo'):
    return engine.state(user)


@app.get('/api/artifacts/{artifact_id}')
def artifact(artifact_id:str,user:str='demo'):
    obj=engine.store.get(artifact_id)
    if obj and obj['user_id']!=user:
        prefix=f'{user}::compare::'
        scope=obj['user_id']
        comparison=engine.store.run(scope[len(prefix):],user) if scope.startswith(prefix) else None
        if not comparison or comparison['action']!='compare':
            obj=None
    if not obj: raise HTTPException(404,'找不到该记忆记录。')
    return obj


@app.get('/api/runs/{run_id}')
def run(run_id:str,user:str='demo'):
    obj=engine.store.run(run_id,user)
    if not obj: raise HTTPException(404,'找不到该运行。')
    return dict(**obj,events=engine.store.events(run_id=run_id,user=user))


@app.get('/api/events')
async def stream(request:Request,user:str='demo',after:int=0):
    try: cursor=max(after,int(request.headers.get('last-event-id','0')))
    except ValueError: cursor=after
    async def generate():
        nonlocal cursor
        while not await request.is_disconnected():
            events=engine.store.events(after=cursor,user=user,limit=200)
            for e in events:
                cursor=e['seq']
                yield f'id: {cursor}\ndata: {json.dumps(e,ensure_ascii=False)}\n\n'
            if not events: yield ': heartbeat\n\n'
            await asyncio.sleep(0.6)
    return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})


# Built React assets are served by FastAPI, keeping the CLI and browser on one origin.
dist=ROOT/'frontend'/'dist'
if (dist/'assets').exists():
    app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')


@app.get('/')
def index():
    path=dist/'index.html'
    if path.exists(): return FileResponse(path)
    raise HTTPException(503,'前端尚未构建。请执行 scripts/setup.ps1，或在 frontend 中运行 npm run dev。')
