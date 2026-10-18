"use client";
import { useEffect, useId, useRef, useState } from "react";
import { Dialog, DialogTitle } from "@/components/dialog";
import { ClaimDetails } from "@/components/claim-details";
import { SourceReader } from "@/components/source-reader";
import { Icon } from "@/components/icons";
import { DefinitionTree } from "@/components/definition-tree";
import type { Detail, ResearchInsight } from "@/lib/api";
export type Inspection={kind:"claim"|"source"|"insight";id:string};
export function ResearchInspector({detail,inspection,close,inspectSource}:{detail:Detail;inspection:Inspection;close:()=>void;inspectSource:(id:string)=>void}){
  const heading=useRef<HTMLHeadingElement>(null),title=useId();
  const [sheet,setSheet]=useState(false);
  useEffect(()=>{const media=matchMedia("(max-width:1100px)");const update=()=>setSheet(media.matches);update();media.addEventListener("change",update);return()=>media.removeEventListener("change",update);},[]);
  const origin=useRef<HTMLElement|null>(null);
  useEffect(()=>{const active=document.activeElement as HTMLElement;if(active&&active!==document.body&&!active.closest(".research-inspector"))origin.current=active;heading.current?.focus();},[inspection.kind,inspection.id,sheet]);
  useEffect(()=>()=>{if(origin.current?.isConnected)origin.current.focus();},[]);
  const claim=detail.report?.claims.find(c=>c.id===inspection.id),source=detail.evidence.find(e=>e.id===inspection.id),insight=detail.analysis?.insights.find(i=>i.id===inspection.id);
  const content=<aside className="research-inspector" aria-label="Evidence inspector" onKeyDown={event=>{if(event.key==="Escape"){event.stopPropagation();close();}}}><header><div><span className="eyebrow">{inspection.kind==="source"?"Source record":inspection.kind==="insight"?"Research insight":"Finding evidence"}</span>{sheet?<DialogTitle ref={heading} tabIndex={-1}>{inspection.kind==="source"?"Source":"Evidence"}</DialogTitle>:<h2 id={title} ref={heading} tabIndex={-1}>{inspection.kind==="source"?"Source":"Evidence"}</h2>}</div><button className="icon-button" onClick={close} aria-label="Close evidence inspector"><Icon name="close"/></button></header><div className="research-inspector-body quiet-scroll">
    {inspection.kind==="claim"&&claim?<><ClaimDetails claim={claim} evidence={detail.evidence}/><div className="inspector-source-links">{claim.supporting_evidence_ids.map(id=><button key={id} className="quiet-button" onClick={()=>inspectSource(id)}>Open source record<Icon name="arrow"/></button>)}</div></>:inspection.kind==="source"&&source?<><h3>{source.signals?.title||source.source_url}</h3><code className="source-location">{source.source_url}</code><SourceReader key={source.id} source={source} citations={detail.report?.claims.flatMap(c=>c.citations?.filter(ref=>ref.evidence_id===source.id)??[])??[]}/><details className="inspector-provenance"><summary>Source provenance</summary><dl><dt>Captured</dt><dd>{new Date(source.collected_at).toLocaleString()}</dd><dt>Method</dt><dd>{source.collection_method.replaceAll("_"," ")}</dd><dt>Provenance</dt><dd>{source.provenance}</dd><dt>SHA-256</dt><dd><code>{source.content_hash}</code></dd></dl></details></>:inspection.kind==="insight"&&insight?<InsightDetails insight={insight} detail={detail} inspectSource={inspectSource}/>:<p className="empty-copy">This record is no longer available in the selected report.</p>}
  </div></aside>;
  return sheet?<Dialog close={close} className="research-inspector-sheet">{content}</Dialog>:content;
}
function InsightDetails({insight,detail,inspectSource}:{insight:ResearchInsight;detail:Detail;inspectSource:(id:string)=>void}){
  return <div className="insight-detail"><span className="classification-text">{insight.kind.replaceAll("_"," ")}</span><h3>{insight.title}</h3><p>{insight.observation}</p>{insight.context&&<p className="insight-context">{insight.context}</p>}{insight.distinct_snapshots>0&&<div className="insight-support-count"><strong>{insight.distinct_snapshots}</strong><span>distinct linked source snapshots</span></div>}{insight.citations.map((citation,index)=><blockquote key={index}><p>{citation.quote}</p><button className="quiet-button" onClick={()=>inspectSource(citation.evidence_id)}>Source<Icon name="arrow"/></button></blockquote>)}{insight.claim_ids.slice(0,8).map(id=>{const claim=detail.report?.claims.find(c=>c.id===id);return claim?<details key={id} className="insight-finding"><summary>{claim.description}</summary><ClaimDetails claim={claim} evidence={detail.evidence}/></details>:null;})}<h4>Supporting records</h4>{insight.evidence_ids.map(id=>{const source=detail.evidence.find(e=>e.id===id);return source?<button key={id} className="inspector-source-link" onClick={()=>inspectSource(id)}><Icon name="document"/><span>{source.signals?.title||source.source_url}<small>{source.source_url}</small></span><Icon name="arrow"/></button>:null;})}{Object.keys(insight.data).length>0&&<DefinitionTree value={insight.data} name="Derived record"/>}</div>;
}
