import {useEffect, useRef, useState} from 'react';
import {BookOpen, Braces, FileText, Link2, X} from 'lucide-react';

export type Artifact = {
  id:string; layer:number; kind:string; title:string; content:string;
  payload:Record<string,unknown>;
};
export type Details = {
  versions:{id:string;path:string;content:string}[];
  artifacts:Artifact[]; events:unknown[]; timings:Record<string,number>;
  tokens:Record<string,number|null>;
};
type Change = {id?:string; quote:string; source:string};
export type Inspection = {
  title:string; text:string; status:string; conditions?:string; data?:Details;
  changes?:Change[]; usedRefs?:string[]; ref?:string; error?:string;
};
type Pane = 'overview'|'sources'|'technical';
type Offer = {offer_name:string;price:number;kcal_lo:number;kcal_hi:number;hot_lv:number};

function SourceRecord({record}: {record:Artifact}) {
  const offers = record.payload.approved as Offer[] | undefined;
  if (record.kind==='sql_result' && Array.isArray(offers)) {
    return <>
      <h4>经查询核验的推荐</h4>
      {offers.length ? <ul className="evidence-offers">{offers.map(offer=><li key={offer.offer_name}>
        <strong>{offer.offer_name}</strong>
        <span>{offer.price}元 · {offer.kcal_lo}～{offer.kcal_hi}千卡 · {['不辣','微辣','辣'][offer.hot_lv]}</span>
      </li>)}</ul> : <p>本轮没有符合条件的菜品。</p>}
    </>;
  }
  if (record.kind==='sql_result') {
    const result = record.payload.result as {rows?:Record<string,unknown>[]} | undefined;
    return <pre>{JSON.stringify(result?.rows ?? [], null, 2)}</pre>;
  }
  return <blockquote>{record.content}</blockquote>;
}

export default function ChatMemoryInspector({inspection, close}: {inspection:Inspection;close:()=>void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [pane,setPane] = useState<Pane>(inspection.ref?'sources':'overview');
  const [selected,setSelected] = useState<string|undefined>(inspection.ref);
  useEffect(()=>{
    const element = dialog.current;
    element?.showModal();
    return ()=>{element?.close();};
  },[]);
  const data = inspection.data;
  const changed = inspection.changes || [];
  const sourceIds = new Set([...changed.map(change=>change.source), ...(inspection.usedRefs||[])]);
  const records = data?.artifacts || [];
  const noteIds = new Set([...sourceIds,...changed.flatMap(change=>change.id?[change.id]:[])]);
  const notes = records.filter(record=>record.layer===2&&noteIds.has(record.id));
  const originals = records.filter(record=>record.kind==='user_message'&&(
    sourceIds.has(record.id)||notes.some(note=>Array.isArray(note.payload.refs)&&note.payload.refs.includes(record.id))
  ));
  const evidence = records.filter(record=>record.kind==='sql_result');
  const visibleSources = [...originals,...evidence];
  const selectedRecord = records.find(record=>record.id===selected);
  if (selectedRecord && !visibleSources.some(record=>record.id===selectedRecord.id)) visibleSources.unshift(selectedRecord);
  const files = data?.versions || [];
  const contexts = records.filter(record=>record.layer===4);
  const tabs = [
    {id:'overview' as const,label:'本轮概览',icon:BookOpen},
    {id:'sources' as const,label:'来源记录',icon:FileText},
    {id:'technical' as const,label:'技术详情',icon:Braces},
  ];

  function showSource(id: string) {
    setSelected(id);
    setPane('sources');
  }

  return <dialog ref={dialog} className="chat-inspector" aria-labelledby="chat-evidence-title"
    onCancel={event=>{event.preventDefault();close();}}
    onClick={event=>{if(event.target===event.currentTarget)close();}}>
    <div className="evidence-shell">
      <header className="chat-inspector-header">
        <div><p>{inspection.title}</p><h2 id="chat-evidence-title">记忆与来源</h2></div>
        <button type="button" aria-label="关闭" onClick={close} autoFocus><X size={20}/></button>
      </header>
      <nav className="evidence-nav" aria-label="记忆与来源栏目">
        {tabs.map(({id,label,icon:Icon})=><button type="button" key={id} aria-pressed={pane===id} onClick={()=>setPane(id)}><Icon size={16}/>{label}</button>)}
      </nav>
      <div className="evidence-body" key={pane}>
        {inspection.error&&<p role="alert" className="chat-error">{inspection.error}</p>}
        {!data&&!inspection.error&&<p role="status" className="chat-muted">正在读取来源…</p>}
        {data&&pane==='overview'&&<>
          <section className="evidence-summary">
            <div className="evidence-summary-label"><span/>{inspection.status}</div>
            <p className="evidence-question">{inspection.text}</p>
            {inspection.conditions&&<div className="evidence-conditions">{inspection.conditions.split(' · ').map(condition=><span key={condition}>{condition}</span>)}</div>}
          </section>
          {!!changed.length&&<section className="evidence-section">
            <h3>本轮记住的内容</h3>
            {[...new Set(changed.map(change=>change.quote))].map(quote=><blockquote key={quote}>{quote}</blockquote>)}
          </section>}
          <section className="evidence-section">
            <h3>原话依据</h3>
            {originals.length ? originals.slice(0,3).map(record=><button type="button" className="evidence-source-link" key={record.id} onClick={()=>showSource(record.id)}><FileText size={17}/><span>{record.content}</span><Link2 size={15}/></button>)
              : <p className="chat-muted">这轮没有关联长期记忆的原话。</p>}
            {originals.length>3&&<button type="button" className="evidence-all-sources" onClick={()=>setPane('sources')}>查看全部 {originals.length} 条原话</button>}
          </section>
        </>}
        {data&&pane==='sources'&&<>
          {inspection.ref&&!records.some(record=>record.id===inspection.ref)&&<p className="chat-muted">这条引用没有找到对应的来源。</p>}
          {visibleSources.length ? visibleSources.map(record=><details className="evidence-record" key={record.id} open={record.id===selected||undefined}>
            <summary><FileText size={16}/><span>{record.kind==='sql_result'&&Array.isArray(record.payload.approved)?'选餐结果':record.kind==='user_message'?'用户原话':record.title}</span>
              {record.kind==='user_message'&&<small className="evidence-preview">{record.content}</small>}</summary>
            <SourceRecord record={record}/>
          </details>) : <p className="chat-muted">这轮没有可展开的来源记录。</p>}
        </>}
        {data&&pane==='technical'&&<>
          <details className="evidence-record"><summary>记忆笔记与文件版本</summary>
            {notes.map(note=><div key={note.id}><h4>{note.title}</h4><pre>{JSON.stringify({id:note.id,content:note.content,...note.payload},null,2)}</pre></div>)}
            {files.map(version=><div key={version.id}><h4>{version.id}</h4><code>{version.path}</code><pre>{version.content}</pre></div>)}
            {!notes.length&&!files.length&&<p className="chat-muted">这轮没有关联的记忆版本。</p>}
          </details>
          <details className="evidence-record"><summary>本轮上下文 <small>{contexts.length} 项</small></summary>
            {contexts.map(record=><div key={record.id}><h4>{record.title}</h4><pre>{record.content}</pre></div>)}
            {!contexts.length&&<p className="chat-muted">没有可查看的上下文。</p>}
          </details>
          <details className="evidence-record"><summary>模型、工具与 SQL 运行轨迹</summary>
            <pre>{JSON.stringify({timings:data.timings,tokens:data.tokens,events:data.events},null,2)}</pre>
            {evidence.map(record=><div key={record.id}><h4>只读查询与绑定参数</h4><pre>{JSON.stringify({database:record.payload.database,sql:record.payload.sql,params:record.payload.params},null,2)}</pre></div>)}
          </details>
        </>}
      </div>
    </div>
  </dialog>;
}
