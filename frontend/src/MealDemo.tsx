import {useEffect,useRef,useState} from 'react';
import {Check,Play,Plus,ChevronRight,Layers3,MessageSquare,NotebookPen,GitCompareArrows} from 'lucide-react';
import MealComparePanel from './MealComparePanel';
import {criteriaVersion,savedCriteria,resultCriteria} from './mealCriteria';

export default function MealDemo({state,spaces,user,busy:parentBusy,text,onText,question,onQuestion,onRun,onCreate,onSpace,onSession,onAdvanced,onRef,comparison,events,renderText}:any){
 const[step,setStep]=useState('save');const[source,setSource]=useState('__current__');
 const[name,setName]=useState('我的饮食偏好');const[inherit,setInherit]=useState(false);const initialized=useRef(false);
 const current=state.current_session;const memory=state.selected_memory;const memories=state.memory_snapshots||[];
 const selectedSource=source==='__current__'?(current?.memory_id||''):source;
 const[applying,setApplying]=useState(false);const applyingRef=useRef(false);
 const busy=parentBusy||applying;
 const selectionPending=selectedSource!==(current?.memory_id||'');
 const comparisonMemory=memories.find((m:any)=>m.id===selectedSource)||(memory?.id===selectedSource?memory:null);
 const visibleComparison=!selectionPending&&(!comparison?.result?.config?.memory_id||comparison.result.config.memory_id===selectedSource)?comparison:null;
 const selectedTitle=memories.find((m:any)=>m.id===selectedSource)?.title||'所选记忆';
 async function applyAndTest(create:boolean,test:boolean){
  if(busy||applyingRef.current)return;
  applyingRef.current=true;setApplying(true);
  try{
   const session=create?await onCreate(selectedSource):current;
   if(!session)return;
   if(create)setSource('__current__');
   if(test)await onRun('test_session',{text:question,session:session.id});
  }finally{applyingRef.current=false;setApplying(false);}
 }
 async function compareSelected(options:any){
  if(busy||applyingRef.current||!comparisonMemory)return;
  applyingRef.current=true;setApplying(true);
  try{
   const session=selectionPending?await onCreate(comparisonMemory.id):current;
   if(!session)return;
   if(selectionPending)setSource('__current__');
   await onRun('meal_compare',{text:question,...options,session:session.id});
  }finally{applyingRef.current=false;setApplying(false);}
 }
 const runs=state.runs.filter((r:any)=>r.session===current?.id);
 const latest=runs.find((r:any)=>r.action==='test_session');
 const result=latest?.status==='complete'?latest.result:null;
 useEffect(()=>{if(!current||initialized.current)return;initialized.current=true;const saved=localStorage.getItem('meal-demo-step:'+user);setStep(saved&&['save','test','compare'].includes(saved)?saved:memory?'test':'save');},[current?.id]);
 useEffect(()=>{if(initialized.current)localStorage.setItem('meal-demo-step:'+user,step);},[step,user]);
 const savedSummary=memory?savedCriteria(memory.payload.conditions):'';
 const historical=result&&(result.criteria_version!==criteriaVersion||(result.memory_test?.memory_id||null)!==(memory?.id||null));
 const subtitle=memory?`${current?.title||'当前会话'} · 已加载「${memory.title}」`:`${current?.title||'当前会话'} · 未加载个人记忆`;
 return <div className="meal-simple">
  <div className="meal-demo-status"><span><MessageSquare size={14}/>{subtitle}</span><button className="meal-small-button" disabled={busy} onClick={()=>onAdvanced('memory')}><Layers3 size={13}/>查看四层记忆</button></div>
  <nav className="meal-demo-steps" aria-label="简明演示步骤">{[{id:'save',n:'1',title:'保存一份记忆',icon:NotebookPen},{id:'test',n:'2',title:'新会话测试',icon:MessageSquare},{id:'compare',n:'3',title:'Deep Agents 对比',icon:GitCompareArrows}].map(s=><button key={s.id} aria-current={step===s.id?'step':undefined} className={step===s.id?'selected':''} onClick={()=>setStep(s.id)}><span>{s.n}</span><s.icon size={16}/><strong>{s.title}</strong><ChevronRight size={14}/></button>)}</nav>
  {step==='save'&&<section className="panel meal-demo-card"><div className="meal-demo-title"><span>第1步</span><h2>先告诉它这顿饭的偏好</h2><p>只在这里说一次。新会话提问时，不再重复预算和热量要求。</p></div><label>给这份记忆起个名字<input aria-label="简明记忆名称" value={name} onChange={e=>setName(e.target.value)} disabled={busy}/></label><label>日常偏好<textarea aria-label="简明偏好输入" value={text} onChange={e=>onText(e.target.value)} rows={3} disabled={busy}/></label><details className="meal-save-options"><summary>保存方式：{inherit?'修改当前记忆':'独立保存，不带入旧条件'}</summary><label><input type="checkbox" checked={inherit} onChange={e=>setInherit(e.target.checked)} disabled={busy||!memory}/>在当前记忆上修改，保留未提及条件</label><p>默认独立保存。只设置热量上限时，不会借用旧记忆的下限；午饭与晚饭分别保存。</p></details><div className="meal-demo-actions"><button className="meal-example-link" disabled={busy} onClick={()=>onText('我不吃辣，午饭预算73块，热量尽量控制在470到610千卡。')}>填入演示示例</button><button className="button primary" disabled={busy||!current||!text.trim()} onClick={()=>onRun('remember',{text,memory_title:name.trim()||'我的饮食偏好',save_mode:inherit?'update':'replace'})}><NotebookPen size={14}/>保存这份记忆</button></div>{memory&&<div className="meal-demo-saved"><Check size={17}/><div><strong>已保存：{memory.title}</strong><p>{savedSummary}</p></div><button className="button secondary" disabled={busy} onClick={()=>setStep('test')}>下一步：新会话测试<ChevronRight size={14}/></button></div>}</section>}
  {step==='test'&&<>
   <section className="panel meal-demo-card">
    <div className="meal-demo-title"><span>第2步</span><h2>新开会话，看看它还记不记得</h2><p>选择要测试的记忆或“不加载记忆”，再问一句日常问题。更换选择后，测试会自动新开对应会话。</p></div>
    <div className="meal-demo-new-session"><label>选择要带入的记忆<select aria-label="简明新会话记忆" value={selectedSource} onChange={e=>setSource(e.target.value)} disabled={busy}><option value="">不加载记忆（用于对照）</option>{memories.map((m:any)=><option key={m.id} value={m.id}>{m.title}</option>)}</select></label><button className="button secondary" disabled={busy||!current} onClick={()=>applyAndTest(true,false)}><Plus size={14}/>{selectedSource?'新开会话并加载':'新开无记忆会话'}</button></div>
    {selectionPending?<div className="meal-stale meal-selection-pending" role="status">已选择{selectedSource?`「${selectedTitle}」`:'“不加载记忆”'}，尚未应用。当前会话{memory?`仍加载「${memory.title}」`:'未加载个人记忆'}。点击下方测试会自动新开对应会话；旧测试结果已收起。</div>:<div className="meal-demo-current">{memory?`本会话已加载「${memory.title}」`:'本会话未加载个人记忆；不带入已保存的饮食条件。'}<span>原会话聊天全文不带入{memory?.payload.repaired_from?' · 已从原话校准旧版本':''}</span></div>}
    <label>在新会话里问<textarea aria-label="简明测试问题" value={question} onChange={e=>onQuestion(e.target.value)} rows={2} disabled={busy}/></label>
    <div className="meal-demo-actions"><small>例如：“今天这顿饭吃什么比较合适？”</small><button className="button primary" disabled={busy||!current||!question.trim()} onClick={()=>applyAndTest(selectionPending,true)}><Play size={14}/>{selectionPending?(selectedSource?'加载所选记忆并测试':'新开无记忆会话并测试'):memory?'测试它是否记得':'测试无记忆对照'}</button></div>
   </section>
   {!selectionPending&&latest?.status==='failed'&&<div className="meal-error" role="alert">{latest.error}</div>}
   {!selectionPending&&historical&&<div className="meal-stale">这条历史结果使用了旧规则或旧记忆，请重新测试。旧结果已保留，不再标记为当前记忆验证通过。</div>}{!selectionPending&&result&&!historical&&<section className="panel meal-demo-card meal-demo-result"><div className="meal-demo-result-heading"><h2>本次测试结果</h2><span className={'meal-status '+(result.memory_test?.memory_loaded?(result.memory_test.passed?(result.has_matches?'pass':'unknown'):'fail'):'unknown')}>{result.memory_test?.memory_loaded?(result.memory_test.passed?(result.has_matches?'条件读取与推荐均已核验':'条件已读取，但没有符合项'):'记忆条件需核对'):'未加载记忆的对照'}</span></div><div className="meal-demo-condition-pills">{resultCriteria(result).map((item:any)=><span key={item.label}>{item.label}<strong>{item.value}</strong></span>)}</div><p className="meal-demo-proof">{result.memory_test?.memory_loaded?'仅使用本会话选定的记忆':'未加载个人记忆；下方标明演示默认条件'}；上一会话聊天全文：未带入。本会话已有 {result.memory_test?.current_session_history_count??0} 条历史消息。</p><div className="meal-answer">{renderText(result.answer)}</div><div className="meal-demo-actions"><button className="meal-small-button" onClick={()=>onRef(result.memory_test.context_id)}><Layers3 size={13}/>查看本次实际注入</button>{memory?<button className="button primary" onClick={()=>setStep('compare')}>下一步：对比 Deep Agents<ChevronRight size={14}/></button>:<small>重新选择并加载保存的记忆后，可对比 Deep Agents。</small>}</div></section>}
  </>}
  {step==='compare'&&<>
   <div className="panel meal-demo-card meal-demo-question">
    <label>选择用于两组对比的记忆<select aria-label="简明对比记忆" value={selectedSource} onChange={e=>setSource(e.target.value)} disabled={busy}><option value="">请选择一份已保存的记忆</option>{memories.map((m:any)=><option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
    {comparisonMemory?<p className="meal-demo-proof">{savedCriteria(comparisonMemory.payload.conditions)}{selectionPending?'。点击开始会自动新开会话并加载这份记忆，原无记忆对照会话保留。':''}</p>:<div className="meal-stale" role="status">{memories.length?'当前会话未加载个人记忆。请在上方选择“晚饭偏好”等已保存记忆，即可开始对比。':'当前空间还没有保存的记忆，请先保存一份偏好。'}{!memories.length&&<button className="meal-small-button" disabled={busy} onClick={()=>setStep('save')}>去保存一份记忆</button>}</div>}
    <label>两组共同回答这个问题<textarea aria-label="简明对比问题" value={question} onChange={e=>onQuestion(e.target.value)} rows={2} disabled={busy}/></label>
   </div>
   <MealComparePanel compact comparison={visibleComparison} events={visibleComparison?events:[]} busy={busy} memory={comparisonMemory} question={question} onRun={compareSelected} onRef={onRef} onHistory={(id:string)=>onAdvanced('history',id)} renderText={renderText}/>
  </>}
  <details className="meal-demo-more"><summary>切换以前的会话或其他记忆空间</summary><div><label>以前的会话<select aria-label="简明切换会话" disabled={busy||!current} value={current?.id||''} onChange={e=>{setSource('__current__');onSession(e.target.value);}}>{!current&&<option value="">读取中…</option>}{(state.session_list||[]).map((s:any)=><option key={s.id} value={s.id}>{s.title} · {s.id.slice(-6)}</option>)}</select></label><label>记忆空间<select aria-label="简明切换空间" disabled={busy} value={user} onChange={e=>onSpace(e.target.value)}>{!spaces.some((s:any)=>s.user_id===user)&&<option value={user}>{user}</option>}{spaces.map((s:any)=><option key={s.user_id} value={s.user_id}>{s.user_id}</option>)}</select></label></div></details>
 </div>;
}
