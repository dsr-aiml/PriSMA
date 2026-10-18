"use client";
import { FormEvent, InputHTMLAttributes, useEffect, useMemo, useRef, useState } from "react";
import { AnalysisOptions, defaultProcessing } from "@/components/analysis-options";
import { Icon } from "@/components/icons";
import { ActivityIndicator } from "@/components/activity-indicator";
import { api, APIError, historyChanged, type Investigation } from "@/lib/api";

type SourceRow = {id:string;title:string;path:string;format:string;characters:number;preview:string;metadata:{document_kind:string;kind_label:string;analysis_priority:number;analysis_reason:string;parse_warnings:string[]}};
type Bundle = {bundle_id:string;subject:string;sources:SourceRow[];retained:number;discovered?:number;excluded:number;characters:number;skip_counts:Record<string,number>;skipped:{path:string;reason:string}[]};
const byteLimit=50_000_000;
const bytes=(value:number)=>value>=1_000_000?`${(value/1_000_000).toFixed(1)} MB`:`${Math.ceil(value/1000)} KB`;

export function SourceImport({onCreated}:{onCreated:(id:string)=>void}) {
  const [bundle,setBundle]=useState<Bundle|null>(null),[selected,setSelected]=useState<string[]>([]),[focus,setFocus]=useState(""),[subject,setSubject]=useState("");
  const [options,setOptions]=useState(defaultProcessing),[busy,setBusy]=useState(false),[error,setError]=useState(""),[query,setQuery]=useState(""),[kind,setKind]=useState("all"),[page,setPage]=useState(0);
  const [repository,setRepository]=useState(""),[repositoryOpen,setRepositoryOpen]=useState(false),[savedAssessment,setSavedAssessment]=useState(""),[removing,setRemoving]=useState(""),[dragging,setDragging]=useState(false),[notice,setNotice]=useState(""),[activity,setActivity]=useState("");
  const fileInput=useRef<HTMLInputElement>(null),folderInput=useRef<HTMLInputElement>(null);
  useEffect(()=>{const reset=()=>{setBundle(null);setSelected([]);setFocus("");setSubject("");setRepository("");setSavedAssessment("");setError("");};const storage=(event:StorageEvent)=>{if(event.key==="prisma:workspace-cleared")reset();};window.addEventListener("prisma:data-cleared",reset);window.addEventListener("storage",storage);return()=>{window.removeEventListener("prisma:data-cleared",reset);window.removeEventListener("storage",storage);};},[]);
  const rows=useMemo(()=>bundle?.sources.filter(row=>(kind==="all"||row.metadata.document_kind===kind)&&`${row.path} ${row.title}`.toLowerCase().includes(query.toLowerCase()))??[],[bundle,kind,query]);
  const focused=bundle?.sources.find(row=>row.id===focus);
  const kinds=useMemo(()=>Array.from(new Set(bundle?.sources.map(row=>row.metadata.document_kind)??[])),[bundle]);
  useEffect(()=>setPage(current=>Math.min(current,Math.max(0,Math.ceil(rows.length/40)-1))),[rows.length]);
  function adopt(reviewed:Bundle,previous:Bundle|null) {
    const oldIds=new Set(previous?.sources.map(row=>row.id)??[]),valid=new Set(reviewed.sources.map(row=>row.id));
    setBundle(reviewed);setSubject(current=>current||reviewed.subject);
    setSelected(current=>[...current.filter(id=>valid.has(id)),...reviewed.sources.filter(row=>!oldIds.has(row.id)&&row.metadata.analysis_priority<9).map(row=>row.id)]);
    setFocus(current=>valid.has(current)?current:reviewed.sources[0]?.id??"");setSavedAssessment("");
  }
  function toggle(id:string){setSelected(value=>value.includes(id)?value.filter(key=>key!==id):[...value,id]);}
  function handleFailure(error:unknown) {
    setError((error as Error).message);
    if(error instanceof APIError&&[404,410].includes(error.status)){setBundle(null);setSelected([]);setFocus("");setError("This source review has expired. Add the files again to start a fresh review.");}
  }
  async function stage(name:string,body:BodyInit,contentType:string,previous:Bundle|null) {
    return api<Bundle>("/sources/preview?filename="+encodeURIComponent(name)+(previous?"&bundle_id="+encodeURIComponent(previous.bundle_id):""),{method:"POST",headers:{"content-type":contentType},body});
  }
  async function review(files:File[]|FileList|null) {
    if(!files?.length||busy)return;setActivity("Reading sources…");setBusy(true);setError("");setNotice("");
    let current=bundle;
    try {
      const list=Array.from(files);if(list.length>20000)throw new Error("Review up to 20,000 entries per bundle.");
      // Archives and large report exports use their bounded native reader. Each result is appended.
      const native=list.filter(file=>!file.webkitRelativePath&&(/\.(zip|har)$/i.test(file.name)||(/\.json$/i.test(file.name)&&file.size>2000000)));
      for(const file of native){if(file.size>byteLimit)throw new Error(`${file.name} exceeds the 50 MB upload limit.`);const reviewed=await stage(file.name,file,"application/octet-stream",current);adopt(reviewed,current);current=reviewed;}
      const other=list.filter(file=>!native.includes(file));
      if(other.length===1&&!other[0].webkitRelativePath){const file=other[0];if(file.size>byteLimit)throw new Error("Upload a file of 50 MB or smaller.");const reviewed=await stage(file.name,file,"application/octet-stream",current);adopt(reviewed,current);current=reviewed;}
      else if(other.length) {
        const records:{path:string;size:number;content?:string;data?:string}[]=[];let size=0;
        for(const file of other) {
          const path=file.webkitRelativePath||file.name;
          if(file.size>(/\.har$/i.test(file.name)?15000000:2000000)||/(?:^|\/)(?:node_modules|\.git|dist|build|\.next|\.venv|venv|vendor)\//.test(path)||/\.(?:png|jpe?g|svg|woff2?|ttf|mp[34]|exe)$/i.test(path)){records.push({path,size:file.size,content:""});continue;}
          // Send the original bytes; File.text() silently replaces non-UTF-8 data.
          const data=new Uint8Array(await file.arrayBuffer());let binary="";for(let index=0;index<data.length;index+=16384)binary+=String.fromCharCode(...data.subarray(index,index+16384));const encoded=btoa(binary);size+=encoded.length;records.push({path,size:file.size,data:encoded});
          if(size>45_000_000)throw new Error("Divide this folder into smaller uploads.");
        }
        const body=JSON.stringify({files:records});if(new TextEncoder().encode(body).length>byteLimit)throw new Error("Divide this folder into smaller uploads.");
        const reviewed=await stage(other[0].webkitRelativePath?.split("/")[0]||"Source collection",body,"application/vnd.prisma.files+json",current);adopt(reviewed,current);current=reviewed;
      }
      setQuery("");setKind("all");setPage(0);setNotice("Sources updated.");
    } catch(error){handleFailure(error);} finally{setBusy(false);if(fileInput.current)fileInput.current.value="";if(folderInput.current)folderInput.current.value="";}
  }
  async function reviewRepository() {
    if(busy)return;setActivity("Reading repository…");setBusy(true);setError("");setNotice("");
    try{const reviewed=await api<Bundle>("/sources/repository",{method:"POST",body:JSON.stringify({url:repository,...(bundle?{bundle_id:bundle.bundle_id}:{})})});adopt(reviewed,bundle);setRepositoryOpen(false);setRepository("");setKind("all");setQuery("");setPage(0);setNotice("Repository added.");}
    catch(error){handleFailure(error);}finally{setBusy(false);}
  }
  async function remove(row:SourceRow) {
    if(!bundle||busy)return;setBusy(true);setRemoving(row.id);setError("");setNotice("");
    try{const reviewed=await api<Bundle>(`/sources/bundles/${encodeURIComponent(bundle.bundle_id)}/items/${encodeURIComponent(row.id)}`,{method:"DELETE"});adopt(reviewed,bundle);setNotice(`${row.title} removed from this review.`);}
    catch(error){handleFailure(error);}finally{setBusy(false);setRemoving("");}
  }
  async function submit(event:FormEvent) {
    event.preventDefault();if(!bundle||!selected.length||busy)return;setActivity("Queuing…");setBusy(true);setError("");setSavedAssessment("");
    try{const result=await api<Investigation>("/investigations/bundle",{method:"POST",body:JSON.stringify({domain:subject,...options,bundle_id:bundle.bundle_id,selected})});historyChanged();onCreated(result.id);}
    catch(error){handleFailure(error);if(error instanceof APIError&&typeof error.details.investigation_id==="string"){setSavedAssessment(error.details.investigation_id);historyChanged();}}finally{setBusy(false);}
  }
  return <section className={"intake-workbench "+(dragging?"intake-dragging":"")} tabIndex={0} aria-label="Source intake"
    onPaste={event=>{if(event.clipboardData.files.length){event.preventDefault();void review(event.clipboardData.files);}}}
    onDragOver={event=>{if(event.dataTransfer.types.includes("Files")){event.preventDefault();setDragging(true);}}}
    onDragLeave={event=>{if(!event.currentTarget.contains(event.relatedTarget as Node))setDragging(false);}}
    onDrop={event=>{event.preventDefault();setDragging(false);void review(event.dataTransfer.files);}}>
    <div className="intake-heading"><div><h2>Sources</h2></div><Icon name="layers"/></div>
    <input ref={fileInput} type="file" multiple hidden onChange={event=>void review(event.target.files)}/>
    <input ref={folderInput} type="file" multiple hidden {...({webkitdirectory:"",directory:""} as InputHTMLAttributes<HTMLInputElement>)} onChange={event=>void review(event.target.files)}/>
    <div className="intake-entrypoints">
      <button type="button" disabled={busy} onClick={()=>fileInput.current?.click()}><Icon name="document"/><strong>Files & ZIP</strong><span>Upload files</span><Icon name="arrow"/></button>
      <button type="button" disabled={busy} onClick={()=>folderInput.current?.click()}><Icon name="code"/><strong>Project folder</strong><span>Upload folder</span><Icon name="arrow"/></button>
      <button type="button" disabled={busy} aria-expanded={repositoryOpen} onClick={()=>setRepositoryOpen(value=>!value)}><Icon name="link"/><strong>GitHub repository</strong><span>Public repository</span><Icon name="arrow"/></button>
    </div>
    {repositoryOpen&&<form className="repository-intake source-entry-panel" onSubmit={event=>{event.preventDefault();void reviewRepository();}}><div className="source-address-panel"><label htmlFor="repository-address">Repository URL</label><div className="source-address"><Icon name="code"/><input id="repository-address" required value={repository} onChange={event=>setRepository(event.target.value)} placeholder="https://github.com/owner/repository" autoCapitalize="none" spellCheck={false}/><button type="button" className="source-remove" aria-label="Close repository intake" onClick={()=>setRepositoryOpen(false)}><Icon name="close"/></button></div></div><div className="source-entry-footer"><p>Default branch or /tree/branch.</p><button className="action-button secondary-action" disabled={busy||!repository}><span>{busy?"Reading repository…":"Import"}</span><Icon name="arrow"/></button></div></form>}
    {busy&&!removing&&<ActivityIndicator label={activity||"Reading source records"}/>}
    {notice&&<p className="intake-notice" role="status">{notice}</p>}
    {bundle&&<>
      <div className="intake-summary"><div><strong>{bundle.retained}</strong><span>Sources</span></div><div><strong>{selected.length}</strong><span>Selected</span></div><div><strong>{bundle.excluded}</strong><span>Excluded</span></div><div><strong>{bytes(bundle.characters)}</strong><span>Content</span></div></div>
      <div className="intake-library"><div className="intake-library-index"><div className="intake-library-toolbar"><label className="component-search"><Icon name="search"/><input aria-label="Search imported files" placeholder="Search files" value={query} onChange={event=>{setQuery(event.target.value);setPage(0);}}/></label><button className="quiet-button" type="button" disabled={busy} onClick={()=>setSelected(bundle.sources.filter(row=>row.metadata.analysis_priority<9).map(row=>row.id))}>Recommended</button><button className="quiet-button" type="button" disabled={busy} onClick={()=>setSelected(selected.length===bundle.sources.length?[]:bundle.sources.map(row=>row.id))}>{selected.length===bundle.sources.length?"Clear selection":"Select all"}</button></div>
        <div className="intake-kind-tabs quiet-scroll" aria-label="File categories"><button aria-pressed={kind==="all"} onClick={()=>{setKind("all");setPage(0);}}>All</button>{kinds.map(value=><button key={value} aria-pressed={kind===value} onClick={()=>{setKind(value);setPage(0);}}>{bundle.sources.find(row=>row.metadata.document_kind===value)?.metadata.kind_label}</button>)}</div>
        <div className="intake-file-list quiet-scroll">{rows.slice(page*40,page*40+40).map(row=><div key={row.id} className={"intake-file-row "+(row.id===focus?"focused ":"")+(removing===row.id?"source-removing":"")}><input type="checkbox" disabled={busy} checked={selected.includes(row.id)} aria-label={"Include "+row.path} onChange={()=>toggle(row.id)}/><button className="source-row-content" onClick={()=>setFocus(row.id)}><Icon name={row.metadata.document_kind==="source_code"?"code":"document"}/><span><strong>{row.title}</strong><small>{row.path.replace(/^local:/,"")}</small></span><span className="intake-kind-label">{row.metadata.kind_label}</span></button><button type="button" className="source-remove source-review-remove" disabled={busy} onClick={()=>void remove(row)} aria-label={"Remove "+row.title+" from this review"} title="Remove from this review"><Icon name="close"/></button></div>)}{!rows.length&&<p className="intake-empty">{bundle.sources.length?"No sources match this filter.":"Add files or a repository to continue."}</p>}</div>
        {rows.length>40&&<div className="intake-pagination"><button className="quiet-button" disabled={page===0} onClick={()=>setPage(value=>value-1)}>Previous</button><span>{page*40+1}–{Math.min(page*40+40,rows.length)} of {rows.length}</span><button className="quiet-button" disabled={(page+1)*40>=rows.length} onClick={()=>setPage(value=>value+1)}>Next</button></div>}
      </div><aside className="intake-preview">{focused?<><span className="eyebrow">Preview</span><h3>{focused.title}</h3><code>{focused.path}</code><dl><div><dt>Format</dt><dd>{focused.format}</dd></div><div><dt>Analysis</dt><dd>{focused.metadata.analysis_reason}</dd></div><div><dt>Content</dt><dd>{focused.characters.toLocaleString()} characters</dd></div></dl><pre>{focused.preview}</pre>{focused.metadata.parse_warnings.map((message,index)=><p key={index}>{message}</p>)}</>:<p>Select a source.</p>}</aside></div>
      {bundle.excluded>0&&<details className="intake-exclusions"><summary>Excluded · {bundle.excluded} files</summary><div>{Object.entries(bundle.skip_counts).map(([reason,count])=><p key={reason}><strong>{count}</strong> {reason}</p>)}</div><ul>{bundle.skipped.slice(0,80).map((row,index)=><li key={index}><code>{row.path}</code><span>{row.reason}</span></li>)}</ul></details>}
      <form className="intake-assessment" onSubmit={submit}><div className="intake-assessment-heading"><div><h3>Analysis</h3></div><label>Project<input required maxLength={253} value={subject} onChange={event=>setSubject(event.target.value)} placeholder="Project name or example.com"/></label></div><AnalysisOptions value={options} onChange={setOptions}/><div className="intake-assessment-footer"><span>{selected.length} selected sources</span><button className="action-button primary-action" disabled={busy||!selected.length}><span>{busy?"Preparing…":"Analyze"}</span><Icon name="arrow"/></button></div></form>
    </>}
    {!bundle&&<p className="intake-formats">ZIP · PDF · DOCX · Markdown · HTML · JSON · YAML · TOML · Source code · SQL<br/><span>50 MB per upload · up to 2,000 sources in a combined review</span></p>}
    {error&&<div className="error" role="alert"><p>{error}</p>{savedAssessment&&<button type="button" className="quiet-button" onClick={()=>onCreated(savedAssessment)}>Open report<Icon name="arrow"/></button>}</div>}
  </section>;
}
