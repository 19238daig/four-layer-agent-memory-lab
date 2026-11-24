import {useEffect,useRef,useState} from 'react';
import {Play,Check,ChevronRight,ArrowLeft,ArrowRight,Plus,MessageSquare,NotebookPen,Network,PanelTop,Link2,GitCompareArrows,LoaderCircle,Eye,SlidersHorizontal,Layers3,AlertCircle,RotateCcw,ChevronDown} from 'lucide-react';
import type {Artifact,Run,State,Trace} from './types';
import './studio.css';

type Action='record'|'distill'|'dream'|'context'|'ask'|'compare';
type Operation={action:Action;session?:string;text?:string};
type Detail=Run&{events:Trace[]};
type Saved={step:number;runs:Record<number,string[]>;drafts:Record<number,string>;questions:Record<number,string>;expected:Record<number,number>};
type Props={user:string;state:State;busy:boolean;connected:boolean;onRun:(action:string,data:Record<string,any>)=>Promise<string|null>;onRef:(id:string)=>void;onOpenRun:(id:string)=>void;onNew:()=>void};
const names:Record<string,string>={record:'保存原始消息',distill:'提取记忆笔记',dream:'整理主题与启动记忆',context:'预览注入内容',ask:'在新会话提问',compare:'运行三组对比'};
export const demoSteps=[
 {title:'录入日常偏好',layer:'L1 原始记录',icon:MessageSquare,description:'先保存原话，观察它们怎样进入原始记录。此时还不会生成笔记。',input:'我平时不吃辣，午饭最好控制在80块以内。\n给我建议的时候，简单列两三条就好。',label:'日常消息（一行一条，可直接修改）',button:'保存日常消息',expect:'原始记录增加；另外三层暂时不变。'},
 {title:'提取记忆笔记',layer:'L2 记忆笔记',icon:NotebookPen,description:'从刚才的原话中提取可长期使用的偏好，并为每条笔记保留原文依据。',button:'提取记忆笔记',expect:'得到饮食、预算、回复风格等笔记；点击来源可回到原话。'},
 {title:'整理主题与索引',layer:'L3 + L4',icon:Network,description:'跨会话整理有效笔记，形成主题 Wiki，并为下一次会话准备少量启动记忆。',button:'整理主题与索引',expect:'主题页引用笔记；启动记忆保留通用偏好与目录。'},
 {title:'预览注入上下文',layer:'L4 注入上下文',icon:PanelTop,description:'先查看新会话会拿到什么。这里只生成预览，不发起模型调用。',button:'预览注入上下文',expect:'查看精简启动记忆，区分目录索引与事实正文。'},
 {title:'换个会话问午饭',layer:'跨会话使用',icon:MessageSquare,description:'用一个全新会话提问，不直接携带旧聊天全文。系统会按需查找相关记忆。',input:'周末午饭吃点什么比较合适？',label:'新会话的问题',button:'提问并观察记忆',expect:'回答体现不吃辣和预算，能打开实际上下文与引用来源。'},
 {title:'改一下午饭预算',layer:'记忆版本更新',icon:RotateCcw,description:'把预算从80元改成120元，再整理和提问。页面会逐步展示录入、提取、整理与回答。',input:'以后午饭预算改成120块吧，还是不吃辣。',label:'对之前偏好的修改',question:'明天中午帮我想两种吃法。',button:'更新预算并验证',expect:'新回答使用120元预算，旧记忆版本仍能查看。'},
 {title:'从原话找回猫名',layer:'L1 原文回查',icon:Eye,description:'只保存一句新消息，故意不生成笔记，看看能否直接从原始记录找回。',input:'对了，我家猫叫年糕。',label:'只保留在原始记录里的消息',question:'我家猫叫什么来着？',button:'保存原话并提问',expect:'回答找到“年糕”，并引用 T 开头的原始消息。'},
 {title:'问一个无关问题',layer:'按需筛选',icon:Layers3,description:'观察常识问题是否会读取饮食主题。少量通用启动记忆仍会存在。',input:'为什么天空看起来是蓝色的？',label:'与个人偏好无关的问题',button:'提问并检查筛选',expect:'不检索饮食和猫名材料，避免无关信息进入回答。'},
 {title:'和 Deep Agents 比较',layer:'真实框架对比',icon:GitCompareArrows,description:'将相同录入消息交给三组独立运行。包含真实 Deep Agents 的记忆文件读写，通常需要几分钟。',input:'周末午饭吃点什么比较合适？',label:'三组共同回答的问题',button:'开始真实方案对比',expect:'并排查看无记忆、四层记忆、Deep Agents 的回答与实际调用统计。'},
];

function load(user:string):Saved{try{const v=JSON.parse(localStorage.getItem('memory-lab-studio:'+user)||'null');if(v&&Number.isInteger(v.step)&&v.step>=0&&v.step<demoSteps.length)return {step:v.step,runs:v.runs||{},drafts:v.drafts||{},questions:v.questions||{},expected:v.expected||{}};}catch{}return {step:0,runs:{},drafts:{},questions:{},expected:{}};}
function Pretty({text,onRef}:{text:string;onRef:(id:string)=>void}){return <div className="rich-text">{text.split(/(\[(?:T|N|R|C|A)-[a-f0-9]+\]|\*\*[^*]+\*\*)/g).map((s,i)=>/^\[(?:T|N|R|C|A)-/.test(s)?<button key={i} className="inline-ref" onClick={()=>onRef(s.slice(1,-1))}><Link2 size={11}/>{s.slice(1,-1)}</button>:s.startsWith('**')?<strong key={i}>{s.slice(2,-2)}</strong>:<span key={i}>{s}</span>)}</div>;}
function Ref({id,onRef}:{id:string;onRef:Props['onRef']}){return <button className="inline-ref" onClick={()=>onRef(id)}><Link2 size={11}/>{id}</button>;}

export default function DemoStudio({user,state,busy,connected,onRun,onRef,onOpenRun,onNew}:Props){
 const[saved,setSaved]=useState<Saved>(()=>load(user));
 const[mode,setMode]=useState<'guided'|'free'>('guided');
 const[executing,setExecuting]=useState(false);
 const[progress,setProgress]=useState('');
 const[error,setError]=useState('');
 const[details,setDetails]=useState<Detail[]>([]);
 const[view,setView]=useState('result');
 const[freeAction,setFreeAction]=useState<Action>('record');
 const[freeSession,setFreeSession]=useState('day1');
 const[freeText,setFreeText]=useState('我平时不吃辣，午饭最好控制在80块以内。');
 const[freeRuns,setFreeRuns]=useState<string[]>([]);
 const lock=useRef(false);
 const step=demoSteps[saved.step];
 const draft=saved.drafts[saved.step]??step.input??'';
 const question=saved.questions[saved.step]??step.question??'';
 const ids=mode==='guided'?(saved.runs[saved.step]||[]):freeRuns;
 const idsKey=ids.join(',');
 const knownRuns=ids.map(id=>state.runs.find(r=>r.id===id)).filter((r):r is Run=>!!r);
 const pending=executing||busy;
 const completed=ids.length>0&&details.length===ids.length&&details.every(r=>r.status==='complete')&&(mode==='free'||ids.length===(saved.expected[saved.step]??ids.length));
 const snapshots=details.flatMap(r=>r.result.artifacts||[]).map(id=>state.objects.find(o=>o.id===id)).filter((o):o is Artifact=>!!o);
 const hasRaw=state.objects.some(o=>o.kind==='user_message');
 const hasNotes=state.objects.some(o=>o.kind==='note'&&o.active);
 const hasSeed=state.objects.some(o=>o.kind==='injection_seed'&&o.active);
 const need=saved.step===1&&!hasRaw?'请先完成第1步，保存日常消息。':saved.step===2&&!hasNotes?'请先完成第2步，提取记忆笔记。':[3,4,5].includes(saved.step)&&!hasSeed?'请先整理主题与启动记忆。':saved.step===8&&!hasRaw?'请先录入日常消息，作为三组共同学习的材料。':'';

 useEffect(()=>{localStorage.setItem('memory-lab-studio:'+user,JSON.stringify(saved));},[saved,user]);
 useEffect(()=>{let cancelled=false;if(!ids.length){setDetails([]);return;}Promise.all(ids.map(async id=>{const r=await fetch('/api/runs/'+id+'?user='+encodeURIComponent(user));if(!r.ok)throw Error('读取执行结果失败');return await r.json() as Detail;})).then(v=>{if(!cancelled)setDetails(v);}).catch(e=>{if(!cancelled)setError(String(e));});return()=>{cancelled=true;};},[idsKey,state.runs,user]);

 function edit(value:string){setSaved(s=>({...s,drafts:{...s.drafts,[s.step]:value}}));}
 function selectStep(index:number){if(executing)return;setSaved(s=>({...s,step:index}));setView('result');setError('');}
 async function waitFor(id:string){const started=Date.now();while(Date.now()-started<20*60*1000){const response=await fetch('/api/runs/'+id+'?user='+encodeURIComponent(user));if(!response.ok)throw Error('连接中断，可从最近运行查看后台进度。');const run=await response.json() as Detail;setDetails(previous=>[...previous.filter(r=>r.id!==id),run]);if(run.status==='failed')throw Error(run.error||'本步执行失败，请查看运行详情。');if(run.status==='complete')return;await new Promise(resolve=>setTimeout(resolve,900));}throw Error('等待超时，后台可能仍在处理，请查看最近运行。');}
 function operations():Operation[]{const unique=Date.now().toString(36);switch(saved.step){
  case 0:return draft.split('\n').map(text=>text.trim()).filter(Boolean).map(text=>({action:'record',session:'day1',text}));
  case 1:return [{action:'distill',session:'day1'}];
  case 2:return [{action:'dream'}];
  case 3:return [{action:'context',session:'preview-'+unique}];
  case 4:return [{action:'ask',session:'day2-'+unique,text:draft}];
  case 5:return [{action:'record',session:'day3',text:draft},{action:'distill',session:'day3'},{action:'dream'},{action:'ask',session:'day4-'+unique,text:question}];
  case 6:return [{action:'record',session:'day5',text:draft},{action:'ask',session:'day6-'+unique,text:question}];
  case 7:return [{action:'ask',session:'day7-'+unique,text:draft}];
  default:return [{action:'compare',session:'compare-'+unique,text:draft}];
 }}
 async function execute(){if(lock.current||pending||!connected)return;setError('');setView('result');const ops=mode==='guided'?operations():[{action:freeAction,session:freeSession,text:freeText}];if(!ops.length)return;lock.current=true;setExecuting(true);setDetails([]);const stepIndex=saved.step;if(mode==='guided')setSaved(s=>({...s,runs:{...s.runs,[stepIndex]:[]},expected:{...s.expected,[stepIndex]:ops.length}}));else setFreeRuns([]);try{for(let i=0;i<ops.length;i++){const op=ops[i];setProgress(`${i+1} / ${ops.length} · ${names[op.action]}`);const {action,...data}=op;const id=await onRun(action,data);if(!id)throw Error('操作未能提交，请检查页面上方的错误提示。');if(mode==='guided')setSaved(s=>({...s,runs:{...s.runs,[stepIndex]:[...(s.runs[stepIndex]||[]),id]}}));else setFreeRuns(s=>[...s,id]);await waitFor(id);}setProgress('本步执行完成');}catch(e){setError(e instanceof Error?e.message:String(e));setProgress('本步未完成');}finally{lock.current=false;setExecuting(false);}}
 const inputMissing=mode==='guided'?(!!step.input&&!draft.trim())||(!!step.question&&!question.trim()):(['record','ask','compare'].includes(freeAction)&&!freeText.trim())||!freeSession.trim();
 const totalFinished=Object.entries(saved.runs).filter(([index,group])=>group.length>0&&group.length===(saved.expected[Number(index)]??group.length)&&group.every(id=>state.runs.some(r=>r.id===id&&r.status==='complete'))).length;

 return <section className="demo-studio" aria-label="前端交互演示">
  <div className="studio-toolbar"><div className="studio-mode" aria-label="演示方式"><button className={mode==='guided'?'selected':''} aria-pressed={mode==='guided'} disabled={executing} onClick={()=>{setMode('guided');setError('');}}><Play size={14}/>分步演示</button><button className={mode==='free'?'selected':''} aria-pressed={mode==='free'} disabled={executing} onClick={()=>{setMode('free');setError('');}}><SlidersHorizontal size={14}/>自由操作</button></div><button className="button secondary compact" disabled={pending} onClick={onNew}><Plus size={14}/>新建空白演示</button></div>
  <div className="studio-memory-strip" aria-label="四层实时数量">{[{n:1,name:'原始记录',count:state.objects.filter(o=>o.layer===1).length},{n:2,name:'有效笔记',count:state.objects.filter(o=>o.layer===2&&o.active).length},{n:3,name:'主题页面',count:state.objects.filter(o=>o.layer===3&&o.active).length},{n:4,name:'上下文快照',count:state.objects.filter(o=>o.layer===4&&o.kind!=='model_context').length}].map(l=><div key={l.n} className={'studio-layer studio-layer-'+l.n}><span>L{l.n}</span><strong>{l.name}</strong><b>{l.count}</b></div>)}</div>
  <div className={'studio-layout '+(mode==='free'?'free-layout':'')}>
   {mode==='guided'&&<nav className="studio-steps panel" aria-label="演示步骤"><div className="studio-steps-heading"><strong>日常午饭场景</strong><span>已完成 {totalFinished} / {demoSteps.length}</span></div>{demoSteps.map((s,i)=>{const done=(saved.runs[i]||[]).length>0&&(saved.runs[i]||[]).length===(saved.expected[i]??(saved.runs[i]||[]).length)&&(saved.runs[i]||[]).every(id=>state.runs.some(r=>r.id===id&&r.status==='complete'));return <button key={s.title} data-step={i} aria-current={saved.step===i?'step':undefined} className={'studio-step '+(saved.step===i?'selected':'')+(done?' done':'')} disabled={executing} onClick={()=>selectStep(i)}><span className="studio-step-number">{done?<Check size={13}/>:String(i+1).padStart(2,'0')}</span><span><strong>{s.title}</strong><small>{s.layer}</small></span><ChevronRight size={13}/></button>;})}</nav>}
   <div className="studio-content">
    <section className="panel studio-input"><div className="studio-input-heading"><span className="studio-operation-icon">{mode==='guided'?<step.icon size={21}/>:<SlidersHorizontal size={21}/>}</span><div><span className="studio-overline">{mode==='guided'?`第 ${saved.step+1} 步 / ${demoSteps.length} · ${step.layer}`:'选择操作，直接执行'}</span><h2>{mode==='guided'?step.title:'自由操作工作台'}</h2></div></div><p className="studio-description">{mode==='guided'?step.description:'自由输入消息、切换会话，直接查看四层记忆的真实变化。'}</p>
     {mode==='guided'?<>{step.input&&<label className="message-field">{step.label}<textarea aria-label="演示输入" value={draft} onChange={e=>edit(e.target.value)} disabled={executing} rows={saved.step===0?3:2}/></label>}{step.question&&<label className="message-field">更新后，在新会话里这样问<textarea aria-label="验证问题" value={question} onChange={e=>setSaved(s=>({...s,questions:{...s.questions,[s.step]:e.target.value}}))} disabled={executing} rows={2}/></label>}<div className="studio-expect"><Eye size={15}/><div><strong>这一步看什么</strong><p>{step.expect}</p></div></div></>:<><div className="form-row"><label>操作<select aria-label="自由操作类型" value={freeAction} disabled={executing} onChange={e=>setFreeAction(e.target.value as Action)}>{Object.entries(names).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><label>会话名称<input aria-label="自由操作会话" value={freeSession} onChange={e=>setFreeSession(e.target.value)} disabled={executing}/></label></div>{['record','ask','compare'].includes(freeAction)&&<label className="message-field">日常消息或问题<textarea aria-label="自由输入" value={freeText} onChange={e=>setFreeText(e.target.value)} disabled={executing} rows={3}/></label>}<p className="studio-free-hint">同名会话继续聊天；想演示跨会话记忆时，换一个会话名称。</p></>}
     {mode==='guided'&&need&&<div className="studio-prerequisite"><AlertCircle size={14}/>{need}</div>}
     {!connected&&<div className="studio-prerequisite"><AlertCircle size={14}/>页面尚未连接服务，恢复连接后即可执行。</div>}
     {error&&<div role="alert" className="studio-error"><AlertCircle size={15}/><span>{error}</span></div>}
     <div className="studio-input-footer"><span className="studio-execution-status" role="status" aria-live="polite">{executing?<><LoaderCircle size={14} className="spin"/>{progress}</>:completed?<><Check size={14}/>本步执行完成</>:busy?'有操作正在后台执行':mode==='guided'&&[0,3].includes(saved.step)?'本步不调用模型':'使用真实模型服务'}</span><button className="button primary" data-testid="execute-step" disabled={pending||!connected||inputMissing||(mode==='guided'&&!!need)} onClick={execute}>{executing?<LoaderCircle size={14} className="spin"/>:<Play size={14}/>} {executing?'正在执行…':mode==='guided'?step.button:'执行操作'}</button></div>
    </section>
    <section className="panel studio-results" aria-busy={executing}><div className="panel-heading"><div><h2>本步执行结果</h2><span>{ids.length?`${ids.length} 次实际操作，输入、输出与来源均已保存`:'执行后，结果会直接显示在这里'}</span></div>{ids.length>0&&<span className={'badge '+(completed?'teal':executing?'amber':'neutral')}>{completed?'已完成':executing?'执行中':knownRuns.some(r=>r.status==='failed')?'执行失败':'已保存'}</span>}</div><div className="studio-result-tabs">{[{id:'result',label:'输出结果'},{id:'events',label:'输入与输出'},{id:'sources',label:'引用来源'}].map(v=><button key={v.id} className={view===v.id?'selected':''} aria-pressed={view===v.id} onClick={()=>setView(v.id)}>{v.label}</button>)}</div><div className="studio-result-body">
     {!ids.length?<div className="studio-result-empty"><PanelTop size={28}/><strong>准备好后，点击上方执行按钮</strong><p>每一步都会运行真实处理，并保留可以检查的结果。</p></div>:view==='result'?<>
      {details.map(run=><div className="studio-run-output" key={run.id}><div className="studio-run-label"><strong>{names[run.action]||run.action}</strong><button className="text-button" onClick={()=>onOpenRun(run.id)}>完整详情 <ChevronRight size={12}/></button></div>{run.status==='failed'?<div className="studio-error">{run.error}</div>:run.result.answer?<><Pretty text={run.result.answer} onRef={onRef}/><div className="studio-answer-evidence"><span>已读取 {run.result.read_ids?.length||0} 项</span><span>明确引用 {run.result.cited_ids?.length||0} 项</span>{state.objects.find(o=>o.id===run.result.answer_id)?.payload.context_id&&<button className="text-button" onClick={()=>onRef(state.objects.find(o=>o.id===run.result.answer_id)!.payload.context_id)}>查看实际上下文</button>}</div></>:run.result.content?<Pretty text={run.result.content} onRef={onRef}/>:run.result.comparison?<div className="studio-comparison">{run.result.comparison.map((r:any)=><article key={r.mode}><h3>{r.mode==='stateless'?'无跨会话记忆':r.mode==='four_layer'?'四层记忆':'Deep Agents'}</h3>{r.status==='failed'?<p className="studio-error">{r.error}</p>:<Pretty text={typeof r.answer==='string'?r.answer:JSON.stringify(r.answer)} onRef={onRef}/>}<div className="studio-compare-metrics"><span>{r.model_calls} 次调用</span><span>{r.total_tokens?.toLocaleString()??'未提供'} token</span></div></article>)}</div>:<>{(run.result.artifacts||[]).map((id:string)=>{const obj=state.objects.find(o=>o.id===id);return obj?<button className={'studio-artifact layer-'+obj.layer} key={id} onClick={()=>onRef(id)}><span><span className="badge">L{obj.layer}</span><strong>{obj.title}</strong><ChevronRight size={13}/></span><p>{obj.content}</p><code>{obj.id}</code></button>:null;})}{run.result.message&&<p className="studio-output-note">{run.result.message}</p>}</>}{run.status==='running'&&<div className="studio-running"><LoaderCircle size={16} className="spin"/><span>{[...run.events].reverse().find(e=>e.type==='model_request')?.data.purpose||'正在处理，请稍候…'}</span></div>}</div>)}
     </>:view==='events'?<>{details.map(run=><div className="studio-event-group" key={run.id}><div className="studio-run-label"><strong>{names[run.action]||run.action}</strong><span className="muted">{run.status==='complete'?'已完成':run.status==='failed'?'失败':'执行中'}</span></div><div className="studio-submitted-input"><span>提交的输入</span><p>{run.input.text||names[run.action]}</p>{run.input.session&&<small>会话：{run.input.session}</small>}</div>{run.events.filter(e=>e.type==='step').map(e=><details className="studio-event-detail" key={e.seq}><summary>{e.data.title}<ChevronDown size={13}/></summary><div className="io-grid"><div><span className="data-label">输入</span><pre>{JSON.stringify(e.data.input,null,2)}</pre></div><div><span className="data-label">输出</span><pre>{JSON.stringify(e.data.output,null,2)}</pre></div></div>{e.data.refs?.length>0&&<div className="refs-line">来源 {e.data.refs.map((id:string)=><Ref key={id} id={id} onRef={onRef}/>)}</div>}</details>)}</div>)}</>:<><p className="studio-source-intro">选择输出或来源，可以继续回查原文。这里列出结构上的引用关系，回答是否引用以其明确标注为准。</p>{snapshots.map(o=><div className="studio-source-row" key={o.id}><button className="studio-source-title" onClick={()=>onRef(o.id)}><span className="badge">L{o.layer}</span><strong>{o.title}</strong><code>{o.id}</code><ChevronRight size={13}/></button>{o.payload.refs?.length>0?<div className="refs-line">来源 {o.payload.refs.map((ref:string)=><Ref key={ref} id={ref} onRef={onRef}/>)}</div>:<p className="muted">这是原始输入，没有上游来源。</p>}{o.payload.evidence?.map((e:any)=><blockquote key={e.id}>“{e.quote}” <Ref id={e.id} onRef={onRef}/></blockquote>)}</div>)}{!snapshots.length&&<p className="muted">本步的文件来源与模型请求可在完整运行详情中查看。</p>}</>}
    </div></section>
    {mode==='guided'&&<div className="studio-navigation"><button className="button secondary" disabled={saved.step===0||executing} onClick={()=>selectStep(saved.step-1)}><ArrowLeft size={14}/>上一步</button><span>{completed?'本步已完成，可以继续。':'可以选择任意步骤，按提示完成前置操作。'}</span><button className="button secondary" disabled={saved.step===demoSteps.length-1||executing} onClick={()=>selectStep(saved.step+1)}>下一步<ArrowRight size={14}/></button></div>}
   </div>
  </div>
 </section>;
}
