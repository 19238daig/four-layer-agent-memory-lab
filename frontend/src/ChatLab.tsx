import {useEffect, useRef, useState, type FormEvent} from 'react';
import {ArrowUp, BookOpen, ChevronDown, Clock3, FlaskConical, Layers3, LoaderCircle, MessageSquare, MessageSquarePlus, Plus, Soup, Trash2, Utensils, Workflow} from 'lucide-react';
import ChatMemoryInspector, {type Details, type Inspection} from './ChatMemoryInspector';
import './chat-lab.css';

const labels = {four_layer: '四层记忆', deepagents: 'Deep Agents', parallel: '并排对话'};
type Mode = keyof typeof labels;
type Session = {id:string;title:string;engine:Mode;memory_enabled:boolean};
type Change = {id?:string;key:string;value:string|number|null;quote:string;source:string};
type QueryParams = {budget:number;kcal_min:number;kcal_max:number;kcal_min_exclusive?:number;kcal_max_exclusive?:number;min_spice:number;max_spice:number};
type Branch = {mode:Mode;status:string;answer:string;elapsed_ms:number;total_tokens:number|null;input_tokens:number|null;output_tokens:number|null;unreported_calls:number;memory_status:string;memory_error?:string;changes?:Change[];used_refs?:string[];params?:QueryParams;memory_recalibrated?:boolean;meal_memory_matched?:boolean};
type Phase = 'reading'|'extracting'|'querying'|'answering'|'saving';
type Turn = {id:string;input:{text:string};status:string;error?:string;created_at?:string;progress?:Partial<Record<Mode,Phase>>;result:{branches?:Branch[]}};
const phaseLabels:Record<Phase,string> = {
  reading:'正在读取本轮记忆', extracting:'正在分析消息与偏好', querying:'正在查询并核验菜品',
  answering:'正在生成回答', saving:'正在更新记忆',
};
const examples = [
  {title:'记住我的晚饭偏好',text:'以后晚饭我喜欢吃辣，预算500块，热量不超过1000千卡。',icon:Utensils},
  {title:'按我的口味选餐',text:'晚上吃什么好？',icon:Soup},
  {title:'记住一件小事',text:'我家猫叫年糕。',icon:BookOpen},
];

async function request<T>(path:string, body?:unknown, method=body===undefined?'GET':'POST'):Promise<T> {
  const response = await fetch(path, body === undefined ? {method} : {
    method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入后重试。');
  return data;
}

function describeQuery(params:QueryParams) {
  const budget = params.budget===10000 ? '预算不限' : '预算≤'+params.budget+'元';
  let heat = '热量不限';
  const low = params.kcal_min>0 || Boolean(params.kcal_min_exclusive);
  const high = params.kcal_max<10000 || Boolean(params.kcal_max_exclusive);
  const lowerBound = (params.kcal_min_exclusive?'>':'≥')+params.kcal_min;
  const upperBound = (params.kcal_max_exclusive?'<':'≤')+params.kcal_max;
  if (low && high) heat = (params.kcal_min_exclusive||params.kcal_max_exclusive)
    ? lowerBound+' 且 '+upperBound+'千卡' : params.kcal_min+'～'+params.kcal_max+'千卡';
  else if (low) heat = lowerBound+'千卡';
  else if (high) heat = upperBound+'千卡';
  const spice = params.max_spice===0 ? '不辣' : params.min_spice===2 ? '重辣' : params.min_spice===1&&params.max_spice===1 ? '微辣' : params.min_spice>0 ? '有辣' : params.max_spice===1 ? '不超过微辣' : '辣度不限';
  return [budget,heat,spice].join(' · ');
}

function Answer({text, open}: {text:string;open:(id:string)=>void}) {
  const references = [...new Set(text.match(/\[[TNRCA]-[a-f0-9]{10}\]/g)||[])];
  return <div className="chat-answer-text">{text.split(/(\*\*[^*]+\*\*|\[[TNRCA]-[a-f0-9]{10}\])/g).map((part,index) => {
    if (part.startsWith('**')) return <strong key={index}>{part.slice(2,-2)}</strong>;
    if (references.includes(part)) {
      const number = references.indexOf(part)+1;
      return <button type="button" className="chat-ref" key={index} aria-label={'查看来源 '+number} onClick={()=>open(part.slice(1,-1))}>{number}</button>;
    }
    return <span key={index}>{part}</span>;
  })}</div>;
}

function EngineTitle({mode}: {mode:Mode}) {
  return <h2><span className={'chat-engine-icon '+(mode==='deepagents'?'deep':'')}>
    {mode==='deepagents'?<Workflow size={15}/>:<Layers3 size={15}/>}
  </span>{labels[mode]}</h2>;
}

function BranchProgress({mode,turn}: {mode:Mode;turn:Turn}) {
  const phase = turn.progress?.[mode];
  const [now,setNow] = useState(Date.now());
  useEffect(()=>{
    const timer = window.setInterval(()=>setNow(Date.now()),1000);
    return ()=>window.clearInterval(timer);
  },[]);
  const elapsed = turn.created_at?Math.max(0,Math.floor((now-Date.parse(turn.created_at))/1000)):0;
  const stage = turn.status==='sending'?'正在发送消息':phase?phaseLabels[phase]:'等待开始';
  return <article className="chat-answer chat-answer-pending">
    <EngineTitle mode={mode}/>
    <p className="chat-stage"><LoaderCircle size={16} aria-hidden="true"/>
      <span role="status">{stage}…</span>
      {elapsed>0&&<small>本轮已等待 {elapsed} 秒</small>}
    </p>
  </article>;
}

export default function ChatLab({workspace}:{workspace:string}) {
  const [user] = useState(()=>localStorage.getItem('meal-space:'+workspace)||'meal-'+workspace);
  const query = '?user='+encodeURIComponent(user);
  const [sessions,setSessions] = useState<Session[]>([]);
  const [session,setSession] = useState<Session|null>(null);
  const [turns,setTurns] = useState<Turn[]>([]);
  const [mode,setMode] = useState<Mode>('four_layer');
  const [remember,setRemember] = useState(true);
  const [text,setText] = useState('');
  const [busy,setBusy] = useState(false);
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState('');
  const [model,setModel] = useState('');
  const [fileRoot,setFileRoot] = useState('');
  const [detail,setDetail] = useState<Inspection|null>(null);
  const [deleting,setDeleting] = useState<Session|null>(null);
  const [deleteError,setDeleteError] = useState('');
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const newMenu = useRef<HTMLDetailsElement>(null);
  const stream = useRef<HTMLDivElement>(null);
  const inspectionSequence = useRef(0);
  const composer = useRef<HTMLTextAreaElement>(null);
  const sending = useRef(false);
  const pending = useRef<{request_id:string;session:string;text:string}|null>(null);
  const sessionKey = 'memory-v2-session:'+user;
  const legacyLink = '/?view=meal-legacy&user='+encodeURIComponent(workspace);
  const studioLink = '/?view=studio&user='+encodeURIComponent(workspace);

  async function list() {
    const data = await request<{sessions:Session[];model:string;root:string}>('/api/chat/sessions'+query);
    setSessions(data.sessions);
    setModel(data.model);
    setFileRoot(data.root);
    return data.sessions;
  }

  async function select(value:Session) {
    const data = await request<{session:Session;turns:Turn[]}>('/api/chat/sessions/'+value.id+query);
    setSession(data.session);
    setMode(value.engine);
    setRemember(value.memory_enabled);
    setTurns(data.turns);
    localStorage.setItem(sessionKey,value.id);
  }

  useEffect(()=>{
    list().then(values=>{
      const last = values.find(value=>value.id===localStorage.getItem(sessionKey));
      if (last) return select(last);
    }).catch(err=>setError(err.message)).finally(()=>setLoading(false));
  },[user]);

  useEffect(()=>{
    if (!session || !turns.some(turn=>turn.status==='running')) return;
    let canceled = false;
    let timer: number;
    const id = session.id;
    async function poll() {
      try {
        const next = await request<{session:Session;turns:Turn[]}>('/api/chat/sessions/'+id+query);
        if (!canceled) {
          setSession(next.session);
          setTurns(next.turns);
          if (!next.turns.some(turn=>turn.status==='running')) {
            await list();
            return;
          }
        }
      } catch (err) {
        if (!canceled) setError((err as Error).message);
      }
      if (!canceled) timer=window.setTimeout(poll,700);
    }
    void poll();
    return ()=>{canceled=true;window.clearTimeout(timer);};
  },[session?.id,turns.some(turn=>turn.status==='running')]);

  useEffect(()=>{
    const area = stream.current;
    if (area) area.scrollTop = area.scrollHeight;
  },[turns.length,session?.id]);
  useEffect(()=>{
    function closeOutside(event:PointerEvent) {
      const menu = newMenu.current;
      if (menu?.open && event.target instanceof Node && !menu.contains(event.target)) menu.open=false;
    }
    function closeOnEscape(event:KeyboardEvent) {
      const menu = newMenu.current;
      if (event.key==='Escape'&&menu?.open) {
        menu.open=false;
        menu.querySelector('summary')?.focus();
      }
    }
    window.addEventListener('pointerdown', closeOutside);
    window.addEventListener('keydown', closeOnEscape);
    return ()=>{window.removeEventListener('pointerdown',closeOutside);window.removeEventListener('keydown',closeOnEscape);};
  },[]);
  useEffect(()=>{
    if (deleting && !deleteDialog.current?.open) deleteDialog.current?.showModal();
    if (!deleting && deleteDialog.current?.open) deleteDialog.current.close();
  },[deleting]);

  const running = turns.some(turn=>turn.status==='running'||turn.status==='sending');
  const locked = busy || loading || running;

  function newChat(nextMode = mode, nextRemember = remember) {
    if (newMenu.current) newMenu.current.open=false;
    setMode(nextMode);
    setRemember(nextRemember);
    setSession(null);
    setTurns([]);
    setText('');
    setError('');
    pending.current=null;
    localStorage.removeItem(sessionKey);
    composer.current?.focus();
  }

  async function removeSession() {
    if (!deleting || busy) return;
    setBusy(true);
    setDeleteError('');
    try {
      await request('/api/chat/sessions/'+deleting.id+query,undefined,'DELETE');
      setSessions(previous=>previous.filter(item=>item.id!==deleting.id));
      if (session?.id===deleting.id) newChat(mode,true);
      setDeleting(null);
    } catch (err) {
      setDeleteError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function send(event:FormEvent) {
    event.preventDefault();
    const message = text.trim();
    if (!message || locked || sending.current) return;
    sending.current=true;
    setBusy(true);
    setError('');
    const draftId = 'sending-'+crypto.randomUUID();
    const created_at = new Date().toISOString();
    setTurns(previous=>[...previous,{id:draftId,input:{text:message},created_at,result:{},status:'sending'}]);
    setText('');
    try {
      const active = session || await request<Session>('/api/chat/sessions',{user,engine:mode,memory_enabled:remember});
      setSession(active);
      localStorage.setItem(sessionKey,active.id);
      if (!pending.current || pending.current.session!==active.id || pending.current.text!==message) {
        pending.current={request_id:crypto.randomUUID(),session:active.id,text:message};
      }
      const data = await request<{run_id:string}>('/api/chat/turns',{user,...pending.current});
      setTurns(previous=>previous.some(turn=>turn.id===data.run_id)
        ? previous.filter(turn=>turn.id!==draftId)
        : previous.map(turn=>turn.id===draftId?{...turn,id:data.run_id,status:'running'}:turn));
      pending.current=null;
    } catch (err) {
      setTurns(previous=>previous.filter(turn=>turn.id!==draftId));
      setText(current=>current||message);
      setError((err as Error).message);
    } finally {
      setBusy(false);
      sending.current=false;
      composer.current?.focus();
    }
  }

  async function inspect(turn:Turn,branch:Branch,ref?:string) {
    const token = ++inspectionSequence.current;
    const status = branch.memory_status==='disabled'?'无记忆对照':
      branch.memory_status==='updated'?'已更新记忆':
      branch.memory_status==='failed'?'记忆更新失败':
      branch.used_refs?.length?'本轮读取了长期记忆':'本轮无长期记忆变化';
    const selection = {title:labels[branch.mode], ref, status, text:turn.input.text,
      changes:branch.changes, usedRefs:branch.used_refs, conditions:branch.params?describeQuery(branch.params):undefined};
    setDetail(selection);
    try {
      const result = await request<{branches:Partial<Record<Mode,Details>>}>('/api/chat/runs/'+turn.id+query);
      if (token!==inspectionSequence.current) return;
      const data = result.branches[branch.mode];
      setDetail({...selection,data,error:data?undefined:'这轮没有可查看的详细记录。'});
    } catch (err) {
      if(token===inspectionSequence.current)setDetail({...selection,error:(err as Error).message});
    }
  }

  return <div className="chat-lab">
    <aside className="chat-sidebar">
      <div className="chat-brand"><span className="chat-brand-mark"><Layers3 size={19}/></span><strong>Memory Lab</strong></div>
      <div className="chat-new-group">
        <button className="chat-new" type="button" onClick={()=>newChat(mode,true)} disabled={locked}><Plus size={18}/>新会话</button>
        <details className="chat-new-menu" ref={newMenu}>
          <summary aria-label="更多新会话选项" title="更多新会话选项"><ChevronDown size={16}/></summary>
          <div className="chat-new-options"><button type="button" onClick={()=>newChat(mode,false)} disabled={locked}><FlaskConical size={17}/>新建无记忆对照</button></div>
        </details>
      </div>
      <nav aria-label="最近会话" className="chat-sessions">
        {sessions.map(value=><div className="chat-session-row" key={value.id}>
          <button className="chat-session-open" type="button" disabled={busy||loading} aria-current={session?.id===value.id?'page':undefined}
          onClick={async()=>{setBusy(true);setError('');try{await select(value);setText('');pending.current=null;}catch(err){setError((err as Error).message);}finally{setBusy(false);}}}>
            <MessageSquare size={15}/><span>{value.title}</span><small>{labels[value.engine]}{value.memory_enabled?'':' · 无记忆对照'}</small>
          </button>
          <button className="chat-session-delete" type="button" title="删除对话" aria-label={'删除对话：'+value.title}
            disabled={busy||loading||(session?.id===value.id&&running)} onClick={()=>{setDeleteError('');setDeleting(value);}}>
            <Trash2 size={16}/>
          </button>
        </div>)}
      </nav>
      {fileRoot && <details className="chat-tools">
        <summary>记忆文件位置</summary>
        <dl className="chat-memory-paths">
          <dt>本会话的工作空间</dt>
          <dd>{fileRoot}</dd>
          <dt>四层记忆 · 主题目录</dt>
          <dd>four_layer/knowledge/chat-index.md</dd>
          <dt>Deep Agents · 长期记忆</dt>
          <dd>deep_agents/AGENTS.md</dd>
        </dl>
      </details>}
      <details className="chat-tools"><summary>实验工具</summary><a href={legacyLink}>SQL、数据库与旧选餐演示</a><a href={studioLink}>原四层交互演示</a></details>
    </aside>
    <main className="chat-main">
      <header className="chat-header">
        <div className="chat-heading"><h1>热量选餐实验室</h1>{!remember&&<span className="chat-control-status"><FlaskConical size={13}/>无记忆对照</span>}</div>
        <div className="chat-settings">
          <label><Workflow size={16}/><span className="chat-visually-hidden">对话引擎</span><select value={mode} title={model} disabled={locked} onChange={e=>newChat(e.target.value as Mode)}>
            {Object.entries(labels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
        </div>
      </header>
      <div className="chat-stream" ref={stream} aria-label="聊天记录">
        {error&&<p className="chat-error" role="alert">{error}</p>}
        {loading&&<p role="status" className="chat-muted">正在读取会话…</p>}
        {!loading&&!turns.length&&<section className="chat-empty">
          <div className="chat-welcome">
            <span className="chat-welcome-mark">{remember?<Utensils size={24}/>:<FlaskConical size={24}/>}</span>
            <h2>{remember?'今天想吃什么？':'无记忆对照'}</h2>
            <p>{remember?'聊聊口味、预算或想吃的菜。以后想换个会话接着问，偏好也会记着。':'这个会话只使用当前对话，长期记忆的读取和写入已关闭。'}</p>
          </div>
          <div className="chat-prompts">{examples.map(({title,text:example,icon:Icon})=><button key={title} type="button" onClick={()=>{setText(example);composer.current?.focus();}}><Icon size={17}/><strong>{title}</strong><span>{example}</span></button>)}</div>
        </section>}
        {turns.map(turn=>{
          const pendingTurn = turn.status==='sending'||turn.status==='running';
          const branches = turn.result.branches||[];
          const modes:Mode[] = mode==='parallel'?['four_layer','deepagents']:[mode];
          return <section className="chat-turn" key={turn.id}>
          <p className="chat-user-message">{turn.input.text}</p>
          {turn.error&&<p className="chat-error" role="alert">{turn.error}</p>}
          <div className={(pendingTurn?modes.length:branches.length)>1?'chat-parallel':'chat-single'}>
            {(pendingTurn?modes:branches.map(branch=>branch.mode)).map(branchMode=>{
              const branch = branches.find(value=>value.mode===branchMode);
              if (!branch) return <BranchProgress mode={branchMode} turn={turn} key={branchMode}/>;
              return <article className="chat-answer" key={branch.mode}>
              <EngineTitle mode={branch.mode}/>
              {branch.memory_recalibrated&&<p className="chat-query-line chat-recalibrated">偏好已校准。以下是历史结果，重新提问可使用修正后的偏好。</p>}
              {branch.params&&<p className="chat-query-line">{branch.memory_recalibrated?'历史筛选':'本轮筛选'} {describeQuery(branch.params)}</p>}
              {branch.status==='failed'?<p className="chat-error" role="alert">{branch.answer}</p>:<Answer text={branch.answer} open={id=>inspect(turn,branch,id)}/>}
              <p className={'chat-memory-line '+(branch.memory_status==='failed'?'chat-error':'')}>
                {branch.memory_status==='updated'? '已更新记忆 · '+(branch.changes?.length||0)+' 项':
                 branch.memory_status==='disabled'?'本轮不读写长期记忆':
                 branch.memory_status==='failed'?'记忆更新失败'+(branch.memory_error?' · '+branch.memory_error:''):
                 branch.meal_memory_matched===false?'本轮未匹配到选餐记忆':
                 branch.used_refs?.length?'已读取历史记忆 · 本轮无新增':'本轮无长期记忆变化'}
              </p>
              <div className="chat-answer-footer"><span><Clock3 size={13}/>{(branch.elapsed_ms/1000).toFixed(1)} 秒 · {branch.total_tokens===null?'token 未提供':branch.total_tokens.toLocaleString()+' token'}{branch.unreported_calls>0&&branch.total_tokens!==null?'（部分）':''}</span><button type="button" onClick={()=>inspect(turn,branch)}>查看记忆与来源 <ChevronDown size={13}/></button></div>
            </article>;})}
          </div>
        </section>;})}
      </div>
      <form className="chat-composer" onSubmit={send}>
        <label htmlFor="chat-message" className="chat-visually-hidden">输入消息</label>
        <MessageSquarePlus className="chat-composer-icon" size={20}/>
        <textarea id="chat-message" ref={composer} placeholder={remember?'说说想吃什么，或告诉我你的偏好…':'输入对照问题…'} value={text} rows={2} maxLength={10000} onChange={e=>setText(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();e.currentTarget.form?.requestSubmit();}}}/>
        <button type="submit" aria-label="发送" disabled={locked||!text.trim()}>{running?<LoaderCircle size={21} className="chat-send-progress"/>:<ArrowUp size={21}/>}</button>
      </form>
    </main>
    {detail&&<ChatMemoryInspector inspection={detail} close={()=>{inspectionSequence.current++;setDetail(null);}}/>}
    <dialog ref={deleteDialog} className="chat-delete-dialog" aria-labelledby="chat-delete-title"
      onCancel={event=>{event.preventDefault();if(!busy)setDeleting(null);}}>
      <h2 id="chat-delete-title">删除这段对话？</h2>
      <p className="chat-delete-name">{deleting?.title}</p>
      <p>对话会从列表移除。两套引擎已经记住的偏好和关联原话仍可用于后续对话。</p>
      {deleteError&&<p className="chat-error" role="alert">{deleteError}</p>}
      <div className="chat-delete-actions">
        <button type="button" disabled={busy} autoFocus onClick={()=>setDeleting(null)}>取消</button>
        <button type="button" disabled={busy} onClick={removeSession}>删除对话</button>
      </div>
    </dialog>
  </div>;
}
