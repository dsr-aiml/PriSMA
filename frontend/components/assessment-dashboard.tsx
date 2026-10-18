"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import dynamic from "next/dynamic";
import { AssessmentActions, type AssessmentAction } from "@/components/assessment-actions";
import { ApiInventory, Blueprint, EvidenceView, Findings, Technologies } from "@/components/report-views";
import { CollectionDetails, EvidenceQuestions, FeatureMapping, RunDetails } from "@/components/model-insights";
import { RepositoryInventory } from "@/components/repository-insights";
import { ResearchOverview, ResearchInsights } from "@/components/research-insights";
import { ResearchInspector, type Inspection } from "@/components/research-inspector";
import { DeliveryStatus } from "@/components/delivery-status";
import { ProcessingHistory } from "@/components/processing-history";
import { ActivityIndicator, ContentMirage } from "@/components/activity-indicator";
import { ExportMenu, Tip } from "@/components/ui";
import { ReportDeleteDialog } from "@/components/report-delete";
import { Icon, type IconName } from "@/components/icons";
import { type Detail } from "@/lib/api";
import { formatDate, statusLabel } from "@/lib/presentation";
const Graph=dynamic(()=>import("@/components/graph"),{ssr:false,loading:()=> <ContentMirage label="Opening the architecture workspace"/>});
const terminal=(status:string)=>["completed","failed","cancelled"].includes(status);
type Section="overview"|"insights"|"architecture"|"repository"|"api"|"data"|"technologies"|"features"|"sources"|"questions"|"activity";
const sectionNames:Record<Section,string>={overview:"Overview",insights:"Insights",architecture:"Architecture",repository:"Repository",api:"API",data:"Data model",technologies:"Technologies",features:"Capabilities",sources:"Sources",questions:"Research query",activity:"Activity"};
const sections:Section[]=Object.keys(sectionNames) as Section[];
const sectionIcons:Record<Section,IconName>={overview:"layers",insights:"insight",architecture:"graph",repository:"branch",api:"server",data:"database",technologies:"code",features:"grid",sources:"document",questions:"search",activity:"activity"};
function initialSection(id:string):Section{if(typeof window==="undefined")return "overview";const value=new URLSearchParams(location.search).get("view");if(value&&sections.includes(value as Section))return value as Section;try{const saved=sessionStorage.getItem("prisma:report-view:"+id);if(saved&&sections.includes(saved as Section))return saved as Section;}catch{}return "overview";}
function engineLabel(detail:Detail){return ({rules:"Explicit parsing",ollama:"Local inference",gemini:"Hosted inference"} as Record<string,string>)[detail.report?.run?.provider??detail.processing_options?.provider??""]??"Reference assessment";}

export function AssessmentDashboard({detail,dark,busy,onControl}:{detail:Detail;dark:boolean;inspect?:(id:string)=>void;busy:boolean;onControl:(action:AssessmentAction,parameters?:Record<string,unknown>)=>void}){
  const [section,setSection]=useState<Section>(()=>{return initialSection(detail.id);}),[inspection,setInspection]=useState<Inspection|null>(null),[width,setWidth]=useState(460),[deleting,setDeleting]=useState(false);
  const [repositoryPaths,setRepositoryPaths]=useState<string[]|undefined>(),[targetEntity,setTargetEntity]=useState(""),[targetOperation,setTargetOperation]=useState(""),[architectureVisited,setArchitectureVisited]=useState(()=>initialSection(detail.id)==="architecture");
  const panel=useRef<HTMLDivElement>(null),scrollPositions=useRef<Record<string,number>>({}),cleanupDrag=useRef<()=>void>(()=>{});
  const report=detail.report,finished=terminal(detail.status),reference=detail.mode==="demo";
  const inspect=useCallback((id:string)=>setInspection({kind:"claim",id}),[]);
  const inspectSource=useCallback((id:string)=>setInspection({kind:"source",id}),[]);
  const inspectInsight=useCallback((id:string)=>setInspection({kind:"insight",id}),[]);
  const closeInspector=useCallback(()=>setInspection(null),[]),closeDeletion=useCallback(()=>setDeleting(false),[]);
  const navigate=useCallback((target:string)=>{if(!sections.includes(target as Section))return;scrollPositions.current[section]=window.scrollY;setSection(target as Section);if(target==="architecture")setArchitectureVisited(true);},[section,reference]);
  useEffect(()=>{try{if(!reference)sessionStorage.setItem("prisma:report-view:"+detail.id,section);}catch{}const url=new URL(location.href);url.searchParams.set("view",section);history.replaceState(history.state,"",url);},[section,detail.id]);
  useEffect(()=>{const event=(event:Event)=>{const value=(event as CustomEvent<{section:string;record?:{kind:string;id:string}}>).detail;navigate(value.section);if(value.record?.kind==="source")inspectSource(value.record.id);if(value.record?.kind==="claim")inspect(value.record.id);if(value.record?.kind==="entity"){setTargetEntity(value.record.id);setInspection(null);}if(value.record?.kind==="operation"){setTargetOperation(value.record.id);setInspection(null);}if(value.record?.kind==="module"){setRepositoryPaths([value.record.id]);setInspection(null);}};window.addEventListener("prisma:research-navigate",event);return()=>window.removeEventListener("prisma:research-navigate",event);},[navigate,inspect,inspectSource]);
  useEffect(()=>()=>cleanupDrag.current(),[]);
  function resize(event:React.PointerEvent<HTMLButtonElement>){cleanupDrag.current();const start=event.clientX,current=width;const move=(event:PointerEvent)=>setWidth(Math.max(340,Math.min(700,current+start-event.clientX)));const stop=()=>{document.removeEventListener("pointermove",move);document.removeEventListener("pointerup",stop);document.removeEventListener("pointercancel",stop);};document.addEventListener("pointermove",move);document.addEventListener("pointerup",stop);document.addEventListener("pointercancel",stop);cleanupDrag.current=stop;}
  function exploreModules(paths:string[]){setRepositoryPaths(paths);navigate("repository");setInspection(null);}
  const counts:Partial<Record<Section,number>>={insights:detail.analysis?.insights.length,architecture:report?.nodes.length,repository:report?.repository?.modules.length,api:report?.api_endpoints.length,data:report?.entities.length,technologies:report?.technologies.length,features:report?.features?.length,sources:detail.evidence.length};
  return <div className="research-workspace">
    <header className="research-report-heading"><div><a className="quiet-button research-back" href={reference?"/reference":"/"}><Icon name="arrow"/>{reference?"Reference":"Assessments"}</a><span className="eyebrow">{reference?"Atlas reference":"Architecture research"}</span><h1>{detail.domain}</h1><div className="research-meta">{!reference&&<time dateTime={detail.created_at}>{formatDate(detail.created_at)}</time>}<span>{engineLabel(detail)}</span>{reference?<span>{detail.depth==="quick"?"Essentials scope":"Complete scope"}</span>:<span>{finished&&report?.run?.coverage?.status==="partial"?"Partial assessment":statusLabel(detail.status)}</span>}</div></div><div className="research-report-actions">{finished&&report&&<ExportMenu id={detail.id} referenceDepth={reference?detail.depth:undefined}/>} {!reference&&finished&&report&&<Tip label="Compare source snapshots or analysis engines"><a className="icon-button" href={"/compare?report="+encodeURIComponent(detail.id)} aria-label="Compare this assessment"><Icon name="layers"/></a></Tip>}{!reference&&<AssessmentActions detail={detail} busy={busy} onControl={onControl}/>} {!reference&&finished&&<Tip label="Delete this report"><button className="icon-button report-trash" aria-label="Delete this report" onClick={()=>setDeleting(true)}><Icon name="trash"/></button></Tip>}</div></header>
    {reference&&<p className="assessment-scope-note">Fictional Atlas reference; separate from real source assessments.</p>}
    {!finished&&<div className="research-run-state"><ActivityIndicator label={statusLabel(detail.status)} detail={detail.events.at(-1)?.message??"Waiting for the background worker"}/><span>{detail.evidence.length} retained {detail.evidence.length===1?"source":"sources"}</span></div>}
    {detail.error&&<div className="research-run-error" role="alert"><Icon name="shield"/><div><strong>{report?"Saved findings remain available":"Assessment needs attention"}</strong><p>{detail.error}</p></div></div>}
    {report?<>
      <nav className="research-navigation quiet-scroll" role="tablist" aria-label="Report sections">{sections.map(value=><button key={value} id={"research-tab-"+value} role="tab" aria-selected={section===value} aria-controls="research-panel" onClick={()=>navigate(value)}><Icon name={sectionIcons[value]}/><span>{sectionNames[value]}</span>{counts[value]!==undefined&&<small>{counts[value]}</small>}{section===value&&<m.span className="research-active-line" layoutId="research-active-section" transition={{duration:.22,ease:[.22,1,.36,1]}}/>}</button>)}</nav>
      <div ref={panel} className={`research-grid ${inspection?"has-inspection":""}`} style={{"--inspector-width":`${width}px`} as React.CSSProperties}>
        <section className="research-main" id="research-panel" role="tabpanel" aria-labelledby={"research-tab-"+section}>
          <AnimatePresence initial={false} mode="wait">{section!=="architecture"&&<m.div key={section} className="research-section" initial={{opacity:0,y:5}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-3}} transition={{duration:.2,ease:[.22,1,.36,1]}} onAnimationComplete={()=>{const top=scrollPositions.current[section];if(top!==undefined)window.scrollTo({top,behavior:"instant"});}}>
            {section==="overview"&&<ResearchOverview detail={detail} select={inspectInsight} navigate={navigate}/>}
            {section==="insights"&&<ResearchInsights detail={detail} select={inspectInsight} inspectClaim={inspect} inspectSource={inspectSource}/>}
            {section==="repository"&&<RepositoryInventory key={repositoryPaths?.join("|")??"all"} detail={detail} inspect={inspect} paths={repositoryPaths}/>}
            {section==="api"&&<ApiInventory report={report} inspect={inspect} initialSelected={targetOperation}/>}
            {section==="data"&&<Blueprint report={report} inspect={inspect} initialSelected={targetEntity}/>}
            {section==="technologies"&&<Technologies report={report} inspect={inspect}/>}
            {section==="features"&&<FeatureMapping report={report} inspect={inspect}/>}
            {section==="sources"&&<EvidenceView detail={detail} select={inspectSource}/>}
            {section==="questions"&&<EvidenceQuestions detail={detail} inspect={inspect} inspectSource={inspectSource}/>}
            {section==="activity"&&<div className="research-activity"><div className="research-section-heading"><div><h2>Activity</h2></div></div><RunDetails report={report}/>{!finished&&<DeliveryStatus id={detail.id}/>} {detail.processing_options?.collection&&<CollectionDetails record={detail.processing_options.collection}/>}{!reference&&<ProcessingHistory events={detail.events} expanded/>}</div>}
          </m.div>}</AnimatePresence>
          {architectureVisited&&<div className="research-architecture" hidden={section!=="architecture"}><Graph report={report} evidence={detail.evidence} onSelect={inspect} dark={dark} onExploreModules={exploreModules}/><Findings report={report} inspect={inspect}/></div>}
        </section>
        {inspection&&<><button className="inspector-resize" role="separator" aria-label="Resize evidence inspector" aria-orientation="vertical" aria-valuenow={width} aria-valuemin={340} aria-valuemax={700} onPointerDown={resize} onKeyDown={event=>{if(event.key==="ArrowLeft"||event.key==="ArrowRight"){event.preventDefault();setWidth(w=>Math.max(340,Math.min(700,w+(event.key==="ArrowLeft"?24:-24))));}}}/><ResearchInspector detail={detail} inspection={inspection} close={closeInspector} inspectSource={inspectSource}/></>}
      </div>
      <details className="research-methodology"><summary>Method<Icon name="chevron"/></summary><p>PriSMA combines source declarations, structural parsing and the selected interpretation engine. Findings link to retained records and exact excerpts. Coverage describes the available source set; evidence-strength ratings are rubric scores. Static relationships and documented schemas do not establish private deployment or measured runtime behavior.</p>{report.diagnostic&&<p>{report.diagnostic}</p>}</details>
    </>:<div className={`research-grid research-pending ${inspection?"has-inspection":""}`} style={{"--inspector-width":`${width}px`} as React.CSSProperties}><div>{finished?<div className="research-empty"><Icon name="document"/><h3>No findings</h3><p>Inspect the saved sources and processing record before continuing.</p></div>:<ContentMirage label="Preparing…"/>}{detail.evidence.length>0&&<EvidenceView detail={detail} select={inspectSource}/>}<ProcessingHistory events={detail.events} expanded/>{!finished&&<DeliveryStatus id={detail.id}/>} {detail.processing_options?.collection&&<CollectionDetails record={detail.processing_options.collection}/>}</div>{inspection&&<ResearchInspector detail={detail} inspection={inspection} close={closeInspector} inspectSource={inspectSource}/>}</div>}
    {deleting&&<ReportDeleteDialog report={detail} close={closeDeletion} deleted={()=>location.assign(reference?"/reference":"/")}/>}
  </div>;
}
