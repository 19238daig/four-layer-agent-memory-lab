import {useEffect,useRef,useState,type ReactNode} from 'react';
import DemoStudio from './DemoStudio';
import MealLab from './MealLab';
import ChatLab from './ChatLab';
import type {Artifact,Run,Trace,State} from './types';
import {Layers3,Command,ArrowUpRight,ArrowRight,Check,Copy,FileText,NotebookPen,Network,PanelTop,Activity,Search,GitCompareArrows,Terminal,ChevronRight,ChevronDown,Link2,Clock3,RefreshCw,Play,MessageSquare,Database,BookOpen,X,Radio,AlertCircle,ExternalLink} from 'lucide-react';

const empty:State={objects:[],runs:[],sessions:[],edges:[]};
const names:Record<string,string>={record:'录入对话',distill:'提取笔记',dream:'整理记忆',context:'预览注入',ask:'新会话提问',compare:'方案对比',replay:'回放轨迹'};
const layers=[
 {n:1,name:'原始记录',en:'Transcripts',icon:FileText,color:'amber',input:'用户消息、回答与工具事件',output:'可搜索的完整经历',hint:'保留原话，作为来源依据',cmd:'record'},
 {n:2,name:'记忆笔记',en:'Memory notes',icon:NotebookPen,color:'teal',input:'原始记录、用户纠正',output:'有来源的事实与偏好',hint:'提取要点，保留版本变化',cmd:'distill'},
 {n:3,name:'记忆表示',en:'Memory representations',icon:Network,color:'blue',input:'多次会话的有效笔记',output:'主题 Wiki 与交叉链接',hint:'组织关联，需要时再读取',cmd:'dream'},
 {n:4,name:'注入上下文',en:'Injected context',icon:PanelTop,color:'rose',input:'精选偏好、主题索引',output:'下一次请求的记忆快照',hint:'少量常驻，详情按需检索',cmd:'context'},
];
const tabs=[{id:'studio',label:'交互演示',icon:Play},{id:'meal',label:'热量选餐实验室',icon:Database},{id:'overview',label:'四层总览',icon:Layers3},{id:'runs',label:'运行详情',icon:Activity},{id:'trace',label:'引用追踪',icon:Link2},{id:'compare',label:'方案对比',icon:GitCompareArrows}];
function time(s:string){return new Date(s).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function json(v:any){return JSON.stringify(v,null,2);}
function CopyButton({text,label='复制'}:{text:string;label?:string}){const[ok,setOk]=useState(false);return <button aria-label={ok?'已复制':label||'复制内容'} className="copy-button" onClick={async()=>{try{await navigator.clipboard.writeText(text);setOk(true);setTimeout(()=>setOk(false),1800);}catch{setOk(false);}}}>{ok?<Check size={14}/>:<Copy size={14}/>} {ok?'已复制':label}</button>;}
function Badge({children,tone='neutral'}:{children:ReactNode;tone?:string}){return <span className={'badge '+tone}>{children}</span>;}
function RichText({text,onRef}:{text:string;onRef:(id:string)=>void}){return <div className="rich-text">{text.split(/(\[(?:T|N|R|C|A)-[a-f0-9]+\]|\*\*[^*]+\*\*)/g).map((s,i)=>/^\[(?:T|N|R|C|A)-/.test(s)?<button key={i} className="inline-ref" onClick={()=>onRef(s.slice(1,-1))}><Link2 size={11}/>{s.slice(1,-1)}</button>:s.startsWith('**')?<strong key={i}>{s.slice(2,-2)}</strong>:<span key={i}>{s}</span>)}</div>;}

export default function App(){
 useEffect(()=>{
  const viewport = window.visualViewport;
  let frame = 0;
  function update(){
   cancelAnimationFrame(frame);
   frame = requestAnimationFrame(()=>{
    document.documentElement.style.setProperty('--app-viewport-width', Math.min(window.innerWidth, viewport?.width||window.innerWidth)+'px');
    document.documentElement.style.setProperty('--app-viewport-height', (viewport?.height||window.innerHeight)+'px');
   });
  }
  update();
  window.addEventListener('resize',update);
  viewport?.addEventListener('resize',update);
  return ()=>{cancelAnimationFrame(frame);window.removeEventListener('resize',update);viewport?.removeEventListener('resize',update);};
 },[]);
 const params=new URLSearchParams(location.search);
 const view=params.get('view');
 if((!view&&!params.has('run'))||view==='meal')return <ChatLab workspace={params.get('user')||'demo'}/>;
 return <StudioApp/>;
}

function StudioApp(){
 const initial=new URLSearchParams(location.search);
 const[user,setUser]=useState(initial.get('user')||'demo');
 const[tab,setTab]=useState(initial.get('view')==='meal-legacy'?'meal':initial.get('view')&&tabs.some(t=>t.id===initial.get('view'))?initial.get('view')!:initial.has('run')?'runs':'studio');
 const[state,setState]=useState<State>(empty);
 const[health,setHealth]=useState<{model:string}|null>(null);
 const[connected,setConnected]=useState(false);
 const[error,setError]=useState('');
 const[selected,setSelected]=useState<string|null>(null);
 const[external,setExternal]=useState<Artifact[]>([]);
 const[runId,setRunId]=useState<string|null>(initial.get('run'));
 const[events,setEvents]=useState<Trace[]>([]);
 const[layerFilter,setLayerFilter]=useState(0);
 const[showHistory,setShowHistory]=useState(false);
 const[query,setQuery]=useState('');
 const[sending,setSending]=useState(false);
 const[inspectorTab,setInspectorTab]=useState('output');
 const[notice,setNotice]=useState('');
 const debounce=useRef<ReturnType<typeof setTimeout>|null>(null);
 const latestSeq=useRef(0);
 const currentRun=state.runs.find(r=>r.id===runId)||state.runs[0];
 const object=state.objects.find(o=>o.id===selected)||external.find(o=>o.id===selected);
 const latestAnswer=[...state.objects].reverse().find(o=>o.kind==='answer');
 const busy=state.runs.some(r=>r.status==='running');

 async function refresh(){try{const r=await fetch('/api/state?user='+encodeURIComponent(user));if(!r.ok)throw Error('读取数据失败');setState(await r.json());}catch(e){setError(String(e));}}
 useEffect(()=>{setState(empty);setExternal([]);setSelected(null);latestSeq.current=0;refresh();fetch('/api/health').then(r=>r.json()).then(setHealth).catch(()=>setError('服务未连接，请双击工作区的“打开记忆演示”入口。'));},[user]);
 useEffect(()=>{const source=new EventSource('/api/events?user='+encodeURIComponent(user)+'&after='+latestSeq.current);source.onopen=()=>setConnected(true);source.onerror=()=>setConnected(false);source.onmessage=e=>{const v=JSON.parse(e.data) as Trace;latestSeq.current=v.seq;if(debounce.current)clearTimeout(debounce.current);debounce.current=setTimeout(()=>refresh(),120);};return()=>{source.close();if(debounce.current)clearTimeout(debounce.current);};},[user]);
 useEffect(()=>{if(!currentRun){setEvents([]);return;}let canceled=false;fetch('/api/runs/'+currentRun.id+'?user='+encodeURIComponent(user)).then(r=>r.json()).then(r=>{if(!canceled)setEvents(r.events||[]);}).catch(()=>{});return()=>{canceled=true;};},[currentRun?.id,currentRun?.status,state.objects.length,state.runs]);
 useEffect(()=>{const params=new URLSearchParams({user,view:tab==='meal'?'meal-legacy':tab});if(runId)params.set('run',runId);history.replaceState(null,'','?'+params.toString());},[runId,user,tab]);
 useEffect(()=>{if(!selected)return;const previous=document.activeElement;const panel=document.querySelector<HTMLElement>('.inspector');panel?.querySelector<HTMLButtonElement>('button')?.focus();function handle(e:KeyboardEvent){if(e.key==='Escape'){setSelected(null);return;}if(e.key!=='Tab'||!panel)return;const controls=Array.from(panel.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],select,input,textarea'));const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}window.addEventListener('keydown',handle);return()=>{window.removeEventListener('keydown',handle);if(previous instanceof HTMLElement&&previous.isConnected)previous.focus();};},[selected]);
 async function submit(a:string,extra:Record<string,any>={},stay=false):Promise<string|null>{setSending(true);setError('');try{const r=await fetch('/api/operations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:a,user,session:'day1',text:'',...extra})});const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'请检查输入内容。');setRunId(data.run_id);if(!stay)setTab(a==='compare'?'compare':'runs');await refresh();return data.run_id;}catch(e){setError(String(e));return null;}finally{setSending(false);}}
 async function openRef(id:string){const found=state.objects.find(o=>o.id===id)||external.find(o=>o.id===id);if(found){setSelected(id);setInspectorTab('output');}else{try{const r=await fetch('/api/artifacts/'+id+'?user='+encodeURIComponent(user));if(!r.ok)throw Error();const obj=await r.json();setExternal(old=>[...old.filter(o=>o.id!==id),obj]);setSelected(id);setInspectorTab('output');}catch{setNotice('找不到当前空间可访问的来源。');setTimeout(()=>setNotice(''),4500);}}}
 function chooseRun(r:Run){setRunId(r.id);setTab(r.action==='compare'?'compare':'runs');}
 const displayObjects=state.objects.filter(o=>(!layerFilter?o.layer>0:o.layer===layerFilter)&&
  (showHistory||o.layer===1||o.active||['injected_snapshot','context_preview','model_context'].includes(o.kind))&&
  (!query||(o.title+o.content+o.id).toLowerCase().includes(query.toLowerCase()))).reverse();

 const statCounts=layers.map(l=>state.objects.filter(o=>o.layer===l.n&&(l.n===1||o.active||(l.n===4&&['injected_snapshot','context_preview'].includes(o.kind)))).length);
 const latestStep=[...events].reverse().find(e=>e.type==='step');

 return <div className={'app-shell'+(tab==='meal'?' meal-mode':'')}><a className="skip-link" href="#main-content">跳到主要内容</a>
  <aside className="sidebar">
   <a className="brand" href="/" aria-label="Memory Lab 首页"><span className="brand-mark"><Layers3 size={21}/></span><span>Memory Lab<small>四层记忆实验台</small></span></a>
   <div className="sidebar-section"><span className="section-label">工作空间</span><label className="workspace-select"><Database size={15}/><select value={user} aria-label="选择用户空间" disabled={busy||sending} onChange={e=>{setRunId(null);setUser(e.target.value);}}>{!['demo','walkthrough'].includes(user)&&<option value={user}>{user}</option>}<option value="demo">我的演示空间</option><option value="walkthrough">已验证示例</option></select></label><div className="local-note"><span className="status-dot"/>本地文件存储</div></div>
   <nav aria-label="主导航">{tabs.map(t=><button key={t.id} className={'nav-item '+(tab===t.id?'active':'')} onClick={()=>setTab(t.id)}><t.icon size={17}/>{t.label}</button>)}</nav>
   <div className="history-heading"><span className="section-label">最近运行</span><span>{state.runs.length}</span></div>
   <div className="history-list">{state.runs.slice(0,15).map(r=><button key={r.id} className={'history-item '+(currentRun?.id===r.id?'selected':'')} onClick={()=>chooseRun(r)}><span className={'run-dot '+r.status}/><span>{names[r.action]||r.action}<small>{r.session||'跨会话'}<span>{time(r.created_at)}</span></small></span></button>)}{!state.runs.length&&<p className="sidebar-empty">执行第一步操作后，<br/>运行记录会出现在这里。</p>}</div>
   <a className="article-link" href="https://www.anthropic.com/research/components-of-agent-memory" target="_blank" rel="noreferrer"><BookOpen size={16}/><span>架构参考原文<small>Anthropic Research</small></span><ArrowUpRight size={15}/></a>
   <div className="sidebar-footer">观察记忆如何形成，也看见它的来源。</div>
  </aside>
  <div className="main-shell">
   <header className="topbar"><div className="breadcrumb">实验台<ChevronRight size={14}/><strong>{tabs.find(t=>t.id===tab)?.label}</strong></div><div className="connection"><span className={'status-dot '+(!connected?'offline':'')}/>{connected?'实时同步':'等待连接'}<span className="top-divider"/><span className="model-name">{health?.model||'连接模型中'}</span></div></header>
   {error&&<div role="alert" className="alert"><AlertCircle size={16}/><span>{error}</span><button aria-label="关闭错误" onClick={()=>setError('')}><X size={16}/></button></div>}
   {notice&&<div role="status" className="notice">{notice}</div>}
   <main id="main-content">
    <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line"/>Agent memory, made visible</div><h1>{tab==='meal'?'测试跨会话记忆':tab==='overview'?'看见记忆的每一层':tab==='runs'?'从输入到输出，逐步查看':tab==='trace'?'每一条记忆，都有来处':tab==='compare'?'同一句话，不同的记忆路径':'从一句日常对话开始'}</h1><p>{tab==='meal'?'先保存偏好，再用新会话提问，最后对比四层记忆与 Deep Agents。':tab==='overview'?'录入日常对话，观察它如何成为笔记、主题知识和下一次会话的上下文。':tab==='runs'?'查看真实执行事件、模型请求，以及本轮实际使用的材料。':tab==='trace'?'区分已读取、已进入上下文与回答已引用，沿来源回到原话。':tab==='compare'?'使用同一模型和同一组录入消息，观察四层记忆与 Deep Agents 的实际行为。':'直接在页面录入、执行和查看结果，逐步演示四层记忆的变化。'}</p></div><button className="button secondary compact" onClick={()=>{setTab(tab==='studio'?'overview':'studio');}}>{tab==='studio'?<Layers3 size={15}/>:<Play size={15}/>} {tab==='studio'?'返回总览':'交互演示'}</button></div>
    {tab==='meal'&&<MealLab key={user} workspace={user}/>}
    {tab==='overview'&&<>
     <div className="architecture panel"><div className="panel-heading"><div><h2>四层记忆架构</h2><span>从完整经历，到精简的启动记忆</span></div><Badge tone="teal"><span className="status-dot"/>真实运行数据</Badge></div>
      <div className="layers">{layers.map((l,i)=>{const Icon=l.icon;const items=state.objects.filter(o=>o.layer===l.n&&(l.n===1||o.active||['injected_snapshot','context_preview'].includes(o.kind)));const last=items.at(-1);return <div className={'layer-column '+l.color+(latestStep?.data.layer===l.n&&busy?' processing':'')} key={l.n}>
       <button className="layer-title" onClick={()=>{setLayerFilter(l.n);document.getElementById('memory-records')?.scrollIntoView({behavior:'smooth',block:'start'});}}><span className="layer-icon"><Icon size={21}/></span><span className="layer-id">L{l.n}</span><strong>{l.name}</strong><small>{l.en}</small><span className="layer-count">{statCounts[i]}<span> 条记录</span></span></button>
       <div className="layer-io"><span>输入</span><p>{l.input}</p><span>输出</span><p>{l.output}</p></div>
       {last?<button className="layer-latest" onClick={()=>openRef(last.id)}><span><span className="mini-dot"/>最近输出 <ChevronRight size={12}/></span><strong>{last.title}</strong><p>{last.content.slice(0,65)}</p><code>{last.id}</code></button>:<div className="layer-empty"><span className="dashed-line"/><p>{l.hint}</p><code>{l.cmd}</code></div>}
       {i<3&&<span className="layer-arrow" aria-hidden="true"><ArrowRight size={15}/></span>}
      </div>;})}</div>
      <div className="architecture-footer"><span><RefreshCw size={13}/>Dream 可回查原文、整理主题并更新启动记忆</span><span>下层材料可按需读取，箭头表示常见整理路径</span></div>
     </div>
     <div className="overview-bottom"><section className="panel start-panel"><div className="panel-heading"><h2>{latestAnswer?'最近一次回答':'准备好第一句日常对话'}</h2>{latestAnswer?<Badge tone="teal">新会话</Badge>:<MessageSquare size={17}/>}</div>{latestAnswer?<><RichText text={latestAnswer.content} onRef={openRef}/><div className="answer-footer"><button className="text-button" onClick={()=>{setSelected(latestAnswer.id);setTab('trace');}}>查看引用链 <ArrowRight size={13}/></button><span>{latestAnswer.session}</span></div></>:<><div className="sample-quote">“我平时不吃辣，午饭最好控制在80块以内。”</div><p className="muted">从这句普通的话开始，看它如何在新会话中影响回答。</p><button className="button primary" onClick={()=>setTab('studio')}><Play size={15}/>开始分步演示<ArrowRight size={15}/></button></>}</section><section className="panel concept-panel"><div className="panel-heading"><h2>读取，不等于引用</h2><Link2 size={17}/></div><div className="evidence-line"><span>已读取</span><ChevronRight size={14}/><span>已进入上下文</span><ChevronRight size={14}/><span>回答已引用</span></div><p>保留每一步的可观察证据。点击来源 ID，可以继续查看主题页、笔记和原始消息。</p><button className="text-button" onClick={()=>setTab('trace')}>打开引用追踪 <ArrowRight size={13}/></button></section></div>
     <section className="panel records-panel" id="memory-records"><div className="panel-heading"><h2>记忆记录 <span className="heading-count">{displayObjects.length}</span></h2><div className="record-tools"><label className="search-field"><Search size={14}/><input aria-label="搜索记忆内容" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索内容或 ID"/></label><label className="history-toggle"><input type="checkbox" checked={showHistory} onChange={e=>setShowHistory(e.target.checked)}/>历史版本</label></div></div><div className="filter-row">{[{n:0,name:'全部'},...layers].map(l=><button className={layerFilter===l.n?'selected':''} key={l.n} onClick={()=>setLayerFilter(l.n)}>{l.n?'L'+l.n+' · ':''}{l.name}</button>)}</div><div className="record-table"><div className="table-head"><span>内容</span><span>层级 / 状态</span><span>来源</span><span>时间</span></div>{displayObjects.slice(0,60).map(o=><button className="record-row" key={o.id} onClick={()=>openRef(o.id)}><span><strong>{o.title}</strong><small>{o.content.slice(0,70)}</small></span><span><Badge tone={layers[o.layer-1]?.color}>L{o.layer}</Badge><small>{o.active?'当前有效':o.payload.supersedes?'历史版本':o.kind==='context_preview'?'仅预览':'已保存'}</small></span><span>{o.payload.refs?.length||0} 处引用</span><span>{time(o.created_at)}<ChevronRight size={13}/></span></button>)}{!displayObjects.length&&<div className="empty-row"><Database size={23}/><strong>{query?'没有匹配的记录':'记忆空间还是空的'}</strong><p>{query?'换个关键词试试。':'先录入一段对话，四层记录会随着页面操作逐步形成。'}</p></div>}</div></section>
    </>}
    <div hidden={tab!=='studio'}><DemoStudio key={user} user={user} state={state} busy={busy||sending} connected={connected} onRun={(a,data)=>submit(a,data,true)} onRef={openRef} onOpenRun={id=>{setRunId(id);setTab('runs');}} onNew={()=>{setRunId(null);setSelected(null);setUser('demo-'+Date.now().toString(36));setTab('studio');}}/></div>
    {tab==='runs'&&<section className="panel run-panel"><div className="panel-heading"><div><h2>{currentRun?names[currentRun.action]:'等待第一次操作'}</h2><span>{currentRun?.id||'执行记录会保存在本地'}</span></div>{currentRun&&<div className="run-actions"><Badge tone={currentRun.status==='failed'?'rose':currentRun.status==='running'?'amber':'teal'}>{currentRun.status==='complete'?'执行完成':currentRun.status==='failed'?'执行失败':'执行中'}</Badge><button className="button secondary compact" disabled={busy||currentRun.status!=='complete'||currentRun.action==='replay'} onClick={()=>submit('replay',{source_run:currentRun.id})}><Play size={13}/>回放</button></div>}</div>{currentRun?.action==='replay'&&<div className="replay-banner">正在回放已保存轨迹，未调用模型。来源：{currentRun.input.source_run}</div>}{currentRun?.error&&<div className="inline-error">{currentRun.error}</div>}<div className="timeline">{events.filter(e=>!['started','complete'].includes(e.type)).map(e=><details className={'timeline-event '+e.type} key={e.seq} open={e.type==='step'}><summary><span className="timeline-point"/><span className="event-title">{e.type==='step'?e.data.title:e.type==='model_request'?e.data.purpose+' · 请求':e.type==='model_response'?e.data.purpose+' · 响应':e.type==='deepagents_tool'?'Deep Agents 工具 · '+e.data.phase:e.type==='comparison_result'?'对比结果 · '+e.data.mode:e.type}</span><time>{time(e.created_at)}</time><ChevronDown size={14}/></summary><div className="event-body">{e.type==='step'?<><div className="io-grid"><div><span className="data-label">输入</span><pre>{json(e.data.input)}</pre></div><div><span className="data-label">输出</span><pre>{json(e.data.output)}</pre></div></div>{e.data.refs?.length>0&&<div className="refs-line"><span>来源</span>{e.data.refs.map((id:string)=><button key={id} className="inline-ref" onClick={()=>openRef(id)}><Link2 size={11}/>{id}</button>)}</div>}{e.data.diff?.length>0&&<details className="diff"><summary>查看版本差异</summary><pre>{e.data.diff.join('\n')}</pre></details>}</>:<pre>{json(e.data)}</pre>}</div></details>)}{!events.length&&<div className="empty-row"><Activity size={25}/><strong>这里将显示真实运行轨迹</strong><p>打开交互演示，选择一个步骤并点击执行。</p></div>}</div></section>}
    {tab==='trace'&&<TraceView state={state} object={object||latestAnswer} onRef={openRef}/>}
    {tab==='compare'&&<CompareView runs={state.runs} currentRun={currentRun} events={events} busy={busy} onRun={()=>{submit('compare',{text:'周末午饭吃点什么比较合适？'});}} onSelect={(r)=>{setRunId(r.id);setTab('runs');}} onRef={openRef}/>}
    <footer className="page-footer"><span>Memory Lab <span className="footer-separator">/</span> 本地四层记忆演示</span><span>原始记录可追溯 · 记忆版本可检查</span></footer>
   </main>
  </div>
  {object&&<><div className="inspector-backdrop" onClick={()=>setSelected(null)}/><aside className="inspector" role="dialog" aria-modal="true" aria-label="记忆记录详情"><div className="inspector-heading"><span><Badge tone={layers[object.layer-1]?.color}>{object.layer?'L'+object.layer:'回答'}</Badge> 记录详情</span><button aria-label="关闭详情" className="icon-button" onClick={()=>setSelected(null)}><X size={19}/></button></div><div className="inspector-title"><h2>{object.title}</h2><div><code>{object.id}</code><CopyButton text={object.id} label=""/></div><p>{object.session||'跨会话'} <span>·</span> {new Date(object.created_at).toLocaleString('zh-CN')}</p>{object.payload.version&&<Badge>{'版本 '+object.payload.version+(object.active?' · 当前有效':' · 历史版本')}</Badge>}</div><div className="inspector-tabs">{[{id:'output',name:'输出'},{id:'input',name:'输入与来源'},{id:'meta',name:'完整数据'}].map(t=><button key={t.id} className={inspectorTab===t.id?'selected':''} onClick={()=>setInspectorTab(t.id)}>{t.name}</button>)}</div><div className="inspector-content">{inspectorTab==='output'?<><RichText text={object.content} onRef={openRef}/>{object.kind==='model_context'&&<p className="info-note">完整分区见“完整数据”中的 sections。这里保存实际回答请求，不等同于全部内容都是启动记忆。</p>}</>:inspectorTab==='input'?<><p className="muted">该输出引用了以下记录。点击继续回溯。</p>{object.payload.refs?.map((id:string)=>{const ref=state.objects.find(o=>o.id===id)||external.find(o=>o.id===id);return <button key={id} className="source-card" onClick={()=>openRef(id)}><span><Link2 size={13}/>{id}<ChevronRight size={13}/></span><strong>{ref?.title||'外部来源'}</strong><p>{ref?.content.slice(0,160)}</p></button>;})}{!object.payload.refs?.length&&<div className="info-note">这是原始输入，没有更早的来源。</div>}{object.payload.evidence?.map((e:any)=><blockquote key={e.id}>{e.quote}<small>逐字摘录自 {e.id}</small></blockquote>)}{object.payload.supersedes&&<div className="refs-line">替代旧版本<button className="inline-ref" onClick={()=>openRef(object.payload.supersedes)}>{object.payload.supersedes}</button></div>}{object.payload.context_id&&<button className="button secondary" onClick={()=>openRef(object.payload.context_id)}>查看本轮实际上下文 <ArrowUpRight size={14}/></button>}</>:<pre>{json(object)}</pre>}</div></aside></>}
 </div>;
}

function TraceView({state,object,onRef}:{state:State;object?:Artifact;onRef:(id:string)=>void}){
 const[chosen,setChosen]=useState<string|null>(null);
 const answers=state.objects.filter(o=>o.kind==='answer').reverse();
 const selected=answers.find(a=>a.id===chosen)||(object?.kind==='answer'?object:answers[0]);
 const byId=new Map(state.objects.map(o=>[o.id,o]));
 function branch(id:string,depth=0,seen=new Set<string>()):ReactNode{const o=byId.get(id);if(!o||seen.has(id)||depth>5)return null;const next=new Set(seen);next.add(id);return <div className="trace-branch" key={id}><button className={'trace-node '+(layers[o.layer-1]?.color||'teal')} onClick={()=>onRef(id)}><span><Badge tone={layers[o.layer-1]?.color}>{o.layer?'L'+o.layer:'回答'}</Badge><code>{id}</code><ArrowUpRight size={14}/></span><strong>{o.title}</strong><p>{o.content.slice(0,110)}</p></button>{o.payload.refs?.length>0&&<div className="trace-children">{o.payload.refs.map((ref:string)=>branch(ref,depth+1,next))}</div>}</div>;}
 return <><div className="panel trace-explainer"><div><Radio size={18}/><strong>已读取</strong><p>检索或工具返回了内容</p></div><ChevronRight size={15}/><div><PanelTop size={18}/><strong>已进入上下文</strong><p>真实模型请求包含该材料</p></div><ChevronRight size={15}/><div><Link2 size={18}/><strong>回答已引用</strong><p>回答明确标注了来源 ID</p></div></div>{selected?<><section className="panel trace-answer"><div className="panel-heading"><h2>选择一条回答</h2><select aria-label="选择要追踪的回答" value={selected.id} onChange={e=>setChosen(e.target.value)}>{answers.map(a=><option key={a.id} value={a.id}>{a.session} · {a.id}</option>)}</select></div><RichText text={selected.content} onRef={onRef}/><div className="trace-stats"><Badge>已读取 {selected.payload.read_ids?.length||0} 项</Badge><Badge tone="teal">明确引用 {selected.payload.cited_ids?.length||0} 项</Badge><button className="text-button" onClick={()=>onRef(selected.payload.context_id)}>查看实际上下文 <ArrowUpRight size={13}/></button></div></section><section className="panel trace-tree"><div className="panel-heading"><h2>从回答回到原话</h2><span>点击节点展开完整输入与输出</span></div>{branch(selected.id)}{!selected.payload.refs?.length&&<p className="info-note">这条回答没有明确引用记忆。可以检查上下文，但不能据此认定模型使用了某条材料。</p>}</section></>:<div className="panel empty-row tall"><Link2 size={32}/><strong>先在新会话里问一个问题</strong><p>回答生成后，这里会显示它真正标注的来源链。</p></div>}</>;
}

function CompareView({runs,currentRun,events,busy,onRun,onSelect,onRef}:{runs:Run[];currentRun?:Run;events:Trace[];busy:boolean;onRun:()=>void;onSelect:(r:Run)=>void;onRef:(id:string)=>void}){
 const compareRun=currentRun?.action==='compare'?currentRun:runs.find(r=>r.action==='compare');
 const rows=compareRun?.result.comparison||(currentRun?.id===compareRun?.id?events.filter(e=>e.type==='comparison_result').map(e=>e.data):[]);
 const modes=[{id:'stateless',name:'无跨会话记忆',desc:'新会话只收到当前问题'},{id:'four_layer',name:'四层记忆',desc:'完整原文、笔记、Wiki 与精简注入'},{id:'deepagents',name:'Deep Agents',desc:'真实框架、持久化 AGENTS.md'}];
 return <><div className="compare-toolbar"><div><h2>同一问题，三组独立运行</h2><p>“周末午饭吃点什么比较合适？”</p></div><button className="button primary" disabled={busy} onClick={onRun}><Play size={14}/>{busy?'运行中…':'开始真实对比'}</button></div><div className="comparison-grid">{modes.map(m=>{const r=rows.find((x:any)=>x.mode===m.id);return <section className={'panel comparison-card '+m.id} key={m.id}><div className="comparison-card-head"><span>{m.id==='stateless'?<MessageSquare size={20}/>:m.id==='four_layer'?<Layers3 size={20}/>:<Database size={20}/>}</span><h2>{m.name}</h2><p>{m.desc}</p></div><div className="comparison-answer">{r?.status==='failed'?<div className="inline-error">{r.error}</div>:r?<RichText text={typeof r.answer==='string'?r.answer:json(r.answer)} onRef={onRef}/>:<div className="comparison-wait"><span className="dashed-line"/><p>{compareRun?.status==='running'?'正在真实执行，完成后显示结果。':'运行后显示真实回答。'}</p></div>}</div><dl className="comparison-metrics"><div><dt>记忆材料字符数</dt><dd>{r?.memory_chars?.toLocaleString()??'—'}</dd></div><div><dt>全部模型调用</dt><dd>{r?.model_calls??'—'}</dd></div><div><dt>全部 token</dt><dd>{r?.total_tokens?.toLocaleString()??'未提供'}</dd></div><div><dt>学习与回答总耗时</dt><dd>{r?(r.elapsed_ms/1000).toFixed(1)+'s':'—'}</dd></div><div><dt>工具调用次数</dt><dd>{r?.tool_calls??'—'}</dd></div></dl>{r?.memory_file&&<details className="deep-memory"><summary>查看实际 AGENTS.md <ChevronDown size={13}/></summary><pre>{r.memory_file}</pre></details>}</section>;})}</div><div className="info-note comparison-note"><AlertCircle size={16}/><p>三组使用相同模型、录入消息顺序和当前问题。学习预算、框架系统提示与工具不同；这里展示一次运行，不是性能排行榜。字符数不等于 token；调用、token 与耗时包含学习阶段。Deep Agents 的追踪由本 Demo 添加。</p></div>{compareRun&&<div className="panel compare-history"><div className="panel-heading"><h2>本次比较</h2><Badge tone={compareRun.status==='complete'?'teal':'amber'}>{compareRun.status==='complete'?'运行完成':compareRun.status==='failed'?'失败':'执行中'}</Badge></div><code>{compareRun.id}</code><p className="muted">所有框架调用与记忆文件变化，均保存在运行详情中。</p><button className="text-button" onClick={()=>onSelect({...compareRun,action:'compare'})}>查看完整运行详情 <ChevronRight size={13}/></button></div>}<div className="compare-reference"><a href="https://docs.langchain.com/oss/python/deepagents/memory" target="_blank" rel="noreferrer">Deep Agents 官方记忆文档 <ExternalLink size={13}/></a><span>Deep Agents 也支持后台整理；本次选择显式文件记忆配置进行比较。</span></div></>;
}
