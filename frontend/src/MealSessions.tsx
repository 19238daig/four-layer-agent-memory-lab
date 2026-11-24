import {useState} from 'react';
import {Plus,Save,MessageSquare,NotebookPen} from 'lucide-react';

export default function MealSessions({state,spaces,user,busy,onSpace,onSession,onCreate,onSave}:any){
 const[source,setSource]=useState('__current__');const[title,setTitle]=useState('');
 const current=state.current_session;const memory=state.selected_memory;
 const chosen=source==='__current__'?(current?.memory_id||''):source;
 const memories=state.memory_snapshots||[];
 return <section className="panel meal-session-panel" aria-label="会话与保存的记忆">
  <div className="meal-session-heading"><div><MessageSquare size={17}/><h2>会话与长期记忆</h2></div><span>新会话保留历史记录，按选择加载记忆版本</span></div>
  <div className="meal-session-controls">
   <label>记忆空间<select aria-label="选择选餐记忆空间" disabled={busy} value={user} onChange={e=>{setSource('__current__');onSpace(e.target.value);}}>{!spaces.some((s:any)=>s.user_id===user)&&<option value={user}>{user}</option>}{spaces.map((s:any)=><option key={s.user_id} value={s.user_id}>{s.user_id} · {s.records}条笔记</option>)}</select></label>
   <label>当前会话<select aria-label="选择选餐会话" disabled={busy||!current} value={current?.id||''} onChange={e=>{setSource('__current__');onSession(e.target.value);}}>{!current&&<option value="">正在读取会话…</option>}{(state.session_list||[]).map((s:any)=><option key={s.id} value={s.id}>{s.title} · {s.id.slice(-6)}</option>)}</select></label>
   <label>新会话加载哪份记忆<select aria-label="新会话记忆选择" disabled={busy} value={chosen} onChange={e=>setSource(e.target.value)}><option value="">不加载历史记忆（对照）</option>{memories.map((m:any)=><option key={m.id} value={m.id}>{m.title} · {m.id.slice(-6)}</option>)}</select></label>
   <button className="button primary" disabled={busy||!current} onClick={async()=>{await onCreate(chosen);setSource('__current__');}}><Plus size={14}/>新建会话</button>
  </div>
  <div className="meal-loaded-memory"><NotebookPen size={15}/><div><strong>{memory?'本会话已加载：'+memory.title:'本会话未加载个人记忆'}</strong><span>{memory?`${memory.id} · ${Object.keys(memory.payload.conditions).length}项饮食条件 · 原始聊天不会跨会话直接复制`:'使用明确标注的演示默认条件；历史四层记录仍保留，可以选择保存版本再新开会话。'}</span></div></div>
  <div className="meal-save-memory"><label>给当前记忆保存一个名字<input aria-label="保存记忆名称" value={title} onChange={e=>setTitle(e.target.value)} placeholder="例如：工作日清淡午餐" disabled={busy}/></label><button className="button secondary" disabled={busy||!memory} onClick={async()=>{await onSave(title.trim());setTitle('');setSource('__current__');}}><Save size={14}/>保存当前记忆版本</button><small>修改偏好后会自动保存新版本；其他会话仍使用它们选定的版本。</small></div>
 </section>;
}
