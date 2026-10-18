"use client";
import { useCallback, useEffect, useState } from "react";
import { WorkspaceShell, ReportPicker } from "@/components/workspace-shell";
import { ClaimDetails } from "@/components/claim-details";
import { Dialog, DialogTitle } from "@/components/dialog";
import { Icon } from "@/components/icons";
import { api, type Detail, type Investigation, type User } from "@/lib/api";
import { useAppearance } from "@/lib/use-appearance";
import { formatDate } from "@/lib/presentation";

type ChangeRow={label?:string;name?:string;feature?:string;method?:string;path?:string;context?:string;entity_name?:string;source_label?:string;target_label?:string;description?:string;kind?:string;type?:string;availability?:string;claim_id:string};
type Changes={added:ChangeRow[];removed:ChangeRow[];changed:{before:ChangeRow;after:ChangeRow}[]};
type Comparison={before:Investigation;after:Investigation;scope:string;same_source_documents:boolean;before_engine:string;after_engine:string;sections:Record<string,Changes>};
const rowTitle=(row:ChangeRow)=>row.source_label?`${row.source_label} → ${row.target_label} · ${row.label}`:row.entity_name?`${row.entity_name}.${row.name}`:[row.method,row.path??row.label??row.name??row.feature].filter(Boolean).join(" ");
const rowDetail=(row:ChangeRow)=>row.description??row.kind??row.type??row.availability??"";
const headings:Record<string,string>={components:"Components",connections:"Connections",routes:"API operations",technologies:"Technologies",entities:"Entities",features:"Capabilities",fields:"Data fields"};
export default function ComparisonPage() {
  const [user,setUser]=useState<User|null>(null),[before,setBefore]=useState<Detail|null>(null),[after,setAfter]=useState<Detail|null>(null),[picker,setPicker]=useState<"before"|"after"|null>(null);
  const [comparison,setComparison]=useState<Comparison|null>(null),[section,setSection]=useState("components"),[filter,setFilter]=useState("all"),[busy,setBusy]=useState(false),[error,setError]=useState(""),[inspection,setInspection]=useState<{side:"before"|"after";id:string}|null>(null);
  const {dark,hasIcon,toggleTheme}=useAppearance();
  useEffect(()=>{let active=true;api<User>("/auth/me").then(value=>{if(active)setUser(value);}).catch(()=>location.assign("/"));const identifier=new URLSearchParams(location.search).get("report");if(identifier)api<Detail>("/investigations/"+encodeURIComponent(identifier)+"?include_content=false").then(value=>{if(active&&value.report&&value.mode!=="demo")setAfter(value);}).catch(error=>{if(active)setError(error.message);});const cleared=()=>{setBefore(null);setAfter(null);setComparison(null);setInspection(null);};const storage=(event:StorageEvent)=>{if(event.key==="prisma:workspace-cleared")cleared();};window.addEventListener("prisma:data-cleared",cleared);window.addEventListener("storage",storage);return()=>{active=false;window.removeEventListener("prisma:data-cleared",cleared);window.removeEventListener("storage",storage);};},[]);
  useEffect(()=>{
    const removed=(id:string)=>{if(id!==before?.id&&id!==after?.id)return;if(id===before?.id)setBefore(null);if(id===after?.id)setAfter(null);setComparison(null);setInspection(null);setError("");};
    const event=(event:Event)=>removed((event as CustomEvent<string>).detail);
    const storage=(event:StorageEvent)=>{if(event.key==="prisma:report-deleted"&&event.newValue){try{removed(JSON.parse(event.newValue).id);}catch{/* Ignore malformed storage messages. */}}};
    window.addEventListener("prisma:report-deleted",event);window.addEventListener("storage",storage);
    return()=>{window.removeEventListener("prisma:report-deleted",event);window.removeEventListener("storage",storage);};
  },[before?.id,after?.id]);
  const closePicker=useCallback(()=>setPicker(null),[]),closeInspection=useCallback(()=>setInspection(null),[]);
  async function pick(item:Investigation) {
    if(!picker)return;const side=picker;setPicker(null);setError("");setComparison(null);setBusy(true);
    try{if(item.id===(side==="before"?after?.id:before?.id))throw new Error("Choose two different assessments.");const value=await api<Detail>("/investigations/"+item.id+"?include_content=false");if(!value.report||value.mode==="demo")throw new Error("Choose a real assessment with a retained report.");if(side==="before")setBefore(value);else setAfter(value);}
    catch(error){setError((error as Error).message);}finally{setBusy(false);}
  }
  async function compare() {
    if(!before||!after||busy)return;setBusy(true);setError("");
    try{const result=await api<Comparison>(`/investigations/${after.id}/compare/${before.id}`);setComparison(result);setFilter("all");const first=Object.keys(result.sections).find(key=>Object.values(result.sections[key]).some(rows=>rows.length));setSection(first??"components");}
    catch(error){setError((error as Error).message);}finally{setBusy(false);}
  }
  if(!user)return <main className="boot"><p>Opening comparison workspace…</p></main>;
  const changes=comparison?.sections[section],allChanges=comparison?Object.values(comparison.sections):[];
  const totals={added:allChanges.reduce((n,c)=>n+c.added.length,0),removed:allChanges.reduce((n,c)=>n+c.removed.length,0),changed:allChanges.reduce((n,c)=>n+c.changed.length,0)};
  const inspectDetail=inspection?.side==="before"?before:after,claim=inspectDetail?.report?.claims.find(c=>c.id===inspection?.id);
  return <WorkspaceShell user={user} comparison hasIcon={hasIcon} dark={dark} onTheme={toggleTheme} onHome={()=>location.assign("/")} onSelect={id=>location.assign("/assessments/"+id)} onLogout={()=>{void api("/auth/logout",{method:"POST"}).then(()=>location.assign("/"));}}>
    <div className="page-heading"><div><span className="eyebrow">Assessment comparison</span><h1 className="display-title">SEE WHAT CHANGED.</h1></div></div>
    <div className="comparison-selection">{(["before","after"] as const).map(side=>{
      const detail=side==="before"?before:after;
      return <section className={`comparison-report ${detail?"":"unselected"}`} key={side}>
        <div><span className="eyebrow">{side==="before"?"Baseline assessment":"Compared assessment"}</span>{detail&&<button className="quiet-button" disabled={busy} onClick={()=>setPicker(side)}>Change report<Icon name="arrow"/></button>}</div>
        {detail?<><h2>{detail.domain}</h2><p>{formatDate(detail.created_at)}</p><dl><div><dt>Sources</dt><dd>{detail.evidence.length}</dd></div><div><dt>Findings</dt><dd>{detail.report?.claims.length??0}</dd></div><div><dt>Engine</dt><dd>{detail.report?.run?.provider==="rules"?"Explicit parsing":detail.report?.run?.provider==="ollama"?"Local inference":"Hosted inference"}</dd></div></dl><a className="quiet-button" href={"/assessments/"+detail.id}>Open report<Icon name="arrow"/></a></>:<button className="comparison-choose" disabled={busy} onClick={()=>setPicker(side)}><Icon name="document"/><span><strong>{side==="before"?"Choose the baseline":"Choose a report to compare"}</strong><small>Browse saved assessments</small></span><Icon name="arrow"/></button>}
      </section>;
    })}</div>
    <div className="comparison-start"><span>{before&&after?"Both source records remain available for evidence review.":"Choose a baseline and a second assessment."}</span><button className="action-button primary-action" disabled={busy||!before||!after} onClick={()=>void compare()}>{busy?"Preparing comparison…":"Compare findings"}<Icon name="arrow"/></button></div>
    {error&&<div className="error" role="alert"><p>{error}</p></div>}
    {comparison&&<>
      <div className="comparison-summary"><p>{comparison.same_source_documents?"Both assessments use identical source documents.":"These assessments use different source documents."} {comparison.scope}</p><dl><div><dt>Added</dt><dd>{totals.added}</dd></div><div><dt>Removed</dt><dd>{totals.removed}</dd></div><div><dt>Changed</dt><dd>{totals.changed}</dd></div></dl></div>
      <div className="assessment-navigation quiet-scroll" role="tablist" aria-label="Comparison categories">{Object.entries(comparison.sections).map(([name,rows])=><button key={name} id={"comparison-tab-"+name} role="tab" aria-selected={section===name} aria-controls="comparison-panel" onClick={()=>setSection(name)}><span>{headings[name]??name}</span><small>{rows.added.length+rows.removed.length+rows.changed.length}</small></button>)}</div>
      <div className="comparison-filters" role="group" aria-label="Filter changes">{["all","added","removed","changed"].map(value=><button key={value} aria-pressed={filter===value} onClick={()=>setFilter(value)}>{value[0].toUpperCase()+value.slice(1)}</button>)}</div>
      <section className="comparison-panel" id="comparison-panel" role="tabpanel" aria-labelledby={"comparison-tab-"+section}>
        {changes&&(["added","removed"] as const).flatMap(type=>(filter==="all"||filter===type)?changes[type].map((row,index)=><article className="comparison-change" key={type+row.claim_id+index}><span className="comparison-change-type">{type==="added"?<Icon name="plus"/>:<Icon name="minus"/>}{type==="added"?"Added":"Removed"}</span><div><h3>{rowTitle(row)}</h3>{row.context&&<small>{row.context}</small>}{rowDetail(row)&&<p>{rowDetail(row)}</p>}</div><button className="quiet-button" onClick={()=>setInspection({side:type==="added"?"after":"before",id:row.claim_id})}>Evidence<Icon name="arrow"/></button></article>):[])}
        {changes&&(filter==="all"||filter==="changed")&&changes.changed.map((row,index)=><article className="comparison-change changed" key={row.after.claim_id+index}><span className="comparison-change-type"><Icon name="activity"/>Changed</span><div><h3>{rowTitle(row.after)}</h3><div className="comparison-before-after"><div><span>Baseline</span><p>{rowDetail(row.before)||"Retained declaration"}</p><button className="quiet-button" onClick={()=>setInspection({side:"before",id:row.before.claim_id})}>Baseline evidence<Icon name="arrow"/></button></div><div><span>Compared</span><p>{rowDetail(row.after)||"Retained declaration"}</p><button className="quiet-button" onClick={()=>setInspection({side:"after",id:row.after.claim_id})}>Compared evidence<Icon name="arrow"/></button></div></div></div></article>)}
        {changes&&!(filter==="all"?changes.added.length+changes.removed.length+changes.changed.length:changes[filter as keyof Changes].length)&&<div className="empty-state"><Icon name="check"/><h3>No {filter==="all"?"differences":filter+" findings"} in this category</h3><p>The retained findings match within this comparison.</p></div>}
      </section>
    </>}
    {picker&&<ReportPicker scope="real" readyOnly select={item=>void pick(item)} close={closePicker}/>}
    {claim&&inspection&&inspectDetail&&<Dialog close={closeInspection} className="inspector"><div className="inspector-header"><DialogTitle>{inspection.side==="before"?"Baseline":"Compared"} evidence</DialogTitle><button className="source-remove" aria-label="Close evidence" onClick={closeInspection}><Icon name="close"/></button></div><div className="inspector-content"><ClaimDetails claim={claim} evidence={inspectDetail.evidence}/></div></Dialog>}
  </WorkspaceShell>;
}
