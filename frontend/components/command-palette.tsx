"use client";
import { useEffect, useMemo, useState } from "react";
import { Command } from "cmdk";
import { Dialog, DialogTitle } from "@/components/dialog";
import { Icon, type IconName } from "@/components/icons";
import { api, type Detail, type HistoryPage, type Investigation } from "@/lib/api";
import { reportSections, searchScore } from "@/lib/workspace-search";
type RecordKind="source"|"claim"|"module"|"entity"|"operation";
export function researchNavigate(section:string,record?:{kind:RecordKind;id:string}){window.dispatchEvent(new CustomEvent("prisma:research-navigate",{detail:{section,record}}));}
type Result={key:string;label:string;description:string;icon:IconName;score:number;run:()=>void};
export function CommandPalette({close,select,report}:{close:()=>void;select:(item:Investigation)=>void;report?:Detail|null}){
  const [query,setQuery]=useState(""),[page,setPage]=useState<HistoryPage|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(true),[scope,setScope]=useState("all");
  useEffect(()=>{
    const controller=new AbortController();let active=true;setLoading(true);setError("");setPage(null);
    const timer=setTimeout(()=>{api<HistoryPage>("/investigations/history?scope=real&limit=20&q="+encodeURIComponent(query.trim()),{signal:controller.signal}).then(value=>{if(active)setPage(value);}).catch(error=>{if(active&&!controller.signal.aborted)setError(error.message);}).finally(()=>{if(active)setLoading(false);});},180);
    return()=>{active=false;clearTimeout(timer);controller.abort();};
  },[query]);
  const groups=useMemo(()=>{
    const output:{name:string;items:Result[]}[]=[];
    function group(name:string,items:Result[]){const visible=items.filter(item=>item.score>0).sort((a,b)=>b.score-a.score||a.label.localeCompare(b.label)).slice(0,14);if(visible.length)output.push({name,items:visible});}
    const navigate=(section:string,record?:{kind:RecordKind;id:string})=>{close();requestAnimationFrame(()=>researchNavigate(section,record));};
    if(scope==="all")group("Workspace",[{label:"Overview",url:"/",icon:"layers"},{label:"Comparison",url:"/compare",icon:"layers"},{label:"Accounts",url:"/account",icon:"user"},{label:"Reference",url:"/reference",icon:"document"}].map(item=>({key:"page-"+item.url,label:item.label,description:"Workspace page",icon:item.icon as IconName,score:searchScore(item.label,query),run:()=>{close();location.assign(item.url);}})));
    if(scope!=="reports"&&report?.report){
      group("This assessment",reportSections.map(s=>({key:"section-"+s.id,label:s.label,description:"Open report section",icon:s.icon,score:searchScore(s.label+" "+s.keywords,query),run:()=>navigate(s.id)})));
      if(query.trim()){
        group("Source records",report.evidence.map(source=>({key:"source-"+source.id,label:source.signals?.title||source.source_url,description:source.source_url,icon:"document",score:searchScore((source.signals?.title||"")+" "+source.source_url+" "+source.source_type,query),run:()=>navigate("sources",{kind:"source",id:source.id})})));
        group("Components",report.report.nodes.map(node=>({key:"component-"+node.id,label:node.label,description:[node.kind,node.context].filter(Boolean).join(" · "),icon:"graph",score:searchScore(node.label+" "+node.kind+" "+(node.context||""),query),run:()=>navigate("architecture",{kind:"claim",id:node.claim_id})})));
        group("Modules", (report.report.repository?.modules??[]).map(module=>({key:"module-"+module.evidence_id+"-"+module.path,label:module.path,description:module.format+" · "+(module.role||"Source module"),icon:"code",score:searchScore(module.path,query),run:()=>navigate("repository",{kind:"module",id:module.path})})));
        group("API operations",report.report.api_endpoints.map(route=>({key:"route-"+route.id,label:route.method+" "+route.path,description:route.context||route.summary||"Retained operation",icon:"server",score:searchScore(route.method+" "+route.path+" "+(route.summary||"")+" "+(route.operation_id||""),query),run:()=>navigate("api",{kind:"operation",id:route.id})})));
        group("Data definitions",report.report.entities.map(entity=>({key:"entity-"+entity.id,label:entity.name,description:entity.context||"Retained data definition",icon:"database",score:searchScore(entity.name+" "+(entity.context||""),query),run:()=>navigate("data",{kind:"entity",id:entity.id})})));
        group("Findings",report.report.claims.map(claim=>({key:"claim-"+claim.id,label:claim.description,description:claim.context||claim.type.replaceAll("_"," "),icon:"insight",score:searchScore(claim.description+" "+(claim.context||""),query),run:()=>navigate("insights",{kind:"claim",id:claim.id})})));
      }
    }
    if(scope!=="assessment")group("Saved reports",(page?.items??[]).map(item=>({key:"report-"+item.id,label:item.domain,description:new Date(item.created_at).toLocaleDateString()+" · "+({rules:"Explicit parsing",ollama:"Local inference",gemini:"Hosted inference"} as Record<string,string>)[item.engine||"rules"],icon:"document",score:1,run:()=>{close();select(item);}})));
    return output;
  },[query,scope,page,report,close,select]);
  const total=groups.reduce((sum,g)=>sum+g.items.length,0);
  return <Dialog close={close} className="command-dialog"><DialogTitle className="sr-only">Search workspace</DialogTitle><Command shouldFilter={false} loop label="Workspace search"><div className="command-input"><Icon name="search"/><Command.Input autoFocus value={query} onValueChange={setQuery} placeholder={report?"Search this workspace":"Search reports and pages"} aria-label="Search workspace records"/>{query&&<button className="icon-button" aria-label="Clear workspace search" onClick={()=>setQuery("")}><Icon name="close"/></button>}<button className="command-escape" onClick={close}>Esc</button></div><div className="command-scopes" aria-label="Search scope">{[["all","Everything"],["reports","Reports"],...(report?.report?[["assessment","This assessment"]]:[])].map(([id,label])=><button key={id} aria-pressed={scope===id} onClick={()=>setScope(id)}>{label}</button>)}<span aria-live="polite">{loading&&scope!=="assessment"?"Searching reports…":total+" matches"}</span></div><Command.List className="quiet-scroll">{!total&&!loading&&<Command.Empty>No matches</Command.Empty>}{groups.map(group=><Command.Group heading={group.name} key={group.name}>{group.items.map(item=><Command.Item key={item.key} value={item.key} onSelect={item.run}><span className="command-record-icon"><Icon name={item.icon}/></span><span className="command-record-copy"><strong>{item.label}</strong><small>{item.description}</small></span><Icon name="arrow"/></Command.Item>)}</Command.Group>)}{loading&&!total&&<p className="command-loading" role="status">Loading…</p>}{error&&<div className="command-error" role="alert">{error}<button className="quiet-button" onClick={()=>setQuery(query+" ")}>Retry<Icon name="refresh"/></button></div>}</Command.List><div className="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span><span><kbd>Enter</kbd> Open</span></div></Command></Dialog>;
}
