"use client";
import { useEffect, useMemo, useState } from "react";
import { api, type Evidence, type Citation } from "@/lib/api";
import { CopyButton } from "@/components/ui";
import { ContentMirage } from "@/components/activity-indicator";
import { Icon } from "@/components/icons";
import { sourceRange, sourceWindow, type SourceRange } from "@/lib/source-position";
type Token={content:string;color?:string};
const WINDOW=20000;
export function SourceReader({source,citations=[],focusRange}:{source:Evidence;citations?:Pick<Citation,"start"|"end"|"quote">[];focusRange?:SourceRange}){
  const [content,setContent]=useState<string|null>(source.content_loaded===false?null:source.content),[error,setError]=useState(""),[page,setPage]=useState(0),[segment,setSegment]=useState(0),[tokens,setTokens]=useState<Token[][]|null>(null),[retry,setRetry]=useState(0),[dark,setDark]=useState(false);
  useEffect(()=>{const update=()=>setDark(document.documentElement.dataset.theme==="dark");const observer=new MutationObserver(update);observer.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});update();return()=>observer.disconnect();},[]);
  useEffect(()=>{let active=true;const controller=new AbortController();setError("");if(source.content_loaded!==false){setContent(source.content);return()=>controller.abort();}setContent(null);api<Evidence>(`/investigations/${source.investigation_id}/sources/${encodeURIComponent(source.id)}`,{signal:controller.signal}).then(result=>{if(active)setContent(result.content);}).catch(error=>{if(active)setError(error.message);});return()=>{active=false;controller.abort();};},[source.id,source.investigation_id,source.content_loaded,source.content,retry]);
  const lines=useMemo(()=>content?.split("\n")??[],[content]);
  const starts=useMemo(()=>{const output=[0];let offset=0;for(const line of lines){offset+=line.length+1;output.push(offset);}return output;},[lines]);
  const characters=useMemo(()=>source.characters??Array.from(content??"").length,[content,source.characters]);
  const verified=useMemo(()=>{
    const text=content??"",valid=citations.filter(c=>Number.isInteger(c.start)&&Number.isInteger(c.end)&&c.start>=0&&c.end>c.start);
    const wanted=[...new Set(valid.flatMap(c=>[c.start,c.end]))].sort((a,b)=>a-b),offsets=new Map<number,number>();
    let point=0,utf16=0,index=0;
    while(utf16<=text.length&&index<wanted.length){if(point===wanted[index]){offsets.set(point,utf16);index++;continue;}if(utf16===text.length)break;utf16+=(text.codePointAt(utf16)??0)>65535?2:1;point++;}
    return valid.flatMap(c=>{const start=offsets.get(c.start),end=offsets.get(c.end);return start!==undefined&&end!==undefined&&text.slice(start,end)===c.quote?[{start,end}]:[];}).sort((a,b)=>a.start-b.start);
  },[content,citations]);
  const focus=useMemo(()=>focusRange&&content!==null?sourceRange(content,focusRange):null,[content,focusRange]);
  const highlights=focus?[focus]:verified,first=focus?.start??verified[0]?.start;
  useEffect(()=>{const next=first===undefined?{page:0,segment:0}:sourceWindow(starts,first,WINDOW);setPage(next.page);setSegment(next.segment);},[source.id,first,starts]);
  const raw=useMemo(()=>lines.slice(page*80,page*80+80).join("\n"),[lines,page]);
  const start=Math.min(raw.length,segment*WINDOW),end=Math.min(raw.length,(segment+1)*WINDOW);
  const safeStart=start>0&&raw.charCodeAt(start)>=0xdc00&&raw.charCodeAt(start)<=0xdfff?start-1:start;
  const safeEnd=end<raw.length&&raw.charCodeAt(end)>=0xdc00&&raw.charCodeAt(end)<=0xdfff?end+1:end;
  const code=raw.slice(safeStart,safeEnd),windowLines=code.split("\n"),firstLine=page*80+raw.slice(0,safeStart).split("\n").length;
  const lineOffsets=useMemo(()=>{const positions=[];let cursor=(starts[page*80]??0)+safeStart;for(const line of windowLines){positions.push(cursor);cursor+=line.length+1;}return positions;},[code,starts,page,safeStart]);
  const language=useMemo(()=>{const ext=source.source_url.split(/[?#]/)[0].split(".").at(-1)?.toLowerCase()??"";const names:Record<string,string>={ts:"typescript",tsx:"typescript",js:"javascript",jsx:"javascript",mjs:"javascript",py:"python",json:"json",yaml:"yaml",yml:"yaml",toml:"toml",sql:"sql",html:"html",htm:"html",md:"markdown"};return Object.hasOwn(names,ext)?names[ext]:"text";},[source.source_url]);
  useEffect(()=>{let active=true;setTokens(null);if(language==="text")return;void import("@/lib/source-highlight").then(module=>module.highlightSource(code,language,dark)).then(result=>{if(active)setTokens(result);}).catch(()=>{});return()=>{active=false;};},[code,language,dark]);
  function download(){if(content===null)return;const url=URL.createObjectURL(new Blob([content],{type:"text/plain;charset=utf-8"}));const anchor=document.createElement("a");anchor.href=url;anchor.download=(source.source_url.split(/[?#]/)[0].split("/").at(-1)||"source")+".txt";anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function lineContent(line:string,index:number){let position=lineOffsets[index];return (tokens?.[index]??[{content:line}]).flatMap((token,tokenIndex)=>{const absolute=position;position+=token.content.length;const relevant=highlights.filter(range=>range.start<position&&range.end>absolute);const cuts=[...new Set([0,token.content.length,...relevant.flatMap(range=>[Math.max(0,range.start-absolute),Math.min(token.content.length,range.end-absolute)])])].sort((a,b)=>a-b);return cuts.slice(0,-1).map((start,cut)=>{const highlighted=relevant.some(range=>absolute+start>=range.start&&absolute+cuts[cut+1]<=range.end);return <span key={tokenIndex+":"+cut} className={highlighted?"citation-token":""} style={{color:token.color}}>{token.content.slice(start,cuts[cut+1])}</span>;});});}
  if(error)return <div className="source-load-error" role="alert"><p>{error}</p><button className="quiet-button" onClick={()=>setRetry(value=>value+1)}>Retry source read<Icon name="refresh"/></button></div>;
  if(content===null)return <ContentMirage label="Opening source record"/>;
  return <div className="source-reader">{focusRange&&<p className="source-position-note">{focus?`Declaration at characters ${(focusRange.start+1).toLocaleString()}–${focusRange.end.toLocaleString()}.`:"The retained declaration location is outside this source snapshot."}</p>}<div className="source-reader-toolbar"><span>{lines.length.toLocaleString()} lines · {characters.toLocaleString()} characters</span><div><CopyButton text={content} label="Copy text"/><button className="icon-button" aria-label="Download normalized source text" onClick={download}><Icon name="download"/></button></div></div><div className="source-code" aria-label="Normalized source text">{windowLines.map((line,index)=><div key={firstLine+index+":"+segment}><span className="source-line-number" aria-hidden="true">{firstLine+index}</span><code>{lineContent(line,index)}{line===""?"\u200b":""}</code></div>)}</div>{raw.length>WINDOW&&<div className="source-segments"><span>Reading segment {segment+1} of {Math.ceil(raw.length/WINDOW)}</span><div><button className="quiet-button" disabled={segment===0} onClick={()=>setSegment(v=>v-1)}>Previous segment</button><button className="quiet-button" disabled={(segment+1)*WINDOW>=raw.length} onClick={()=>setSegment(v=>v+1)}>Next segment</button></div></div>}{lines.length>80&&<div className="picker-pagination"><span>Lines {page*80+1}–{Math.min(lines.length,page*80+80)}</span><div><button className="icon-button" aria-label="Previous source lines" disabled={page===0} onClick={()=>{setPage(p=>p-1);setSegment(0);}}><Icon name="chevron" className="previous-icon"/></button><button className="icon-button" aria-label="Next source lines" disabled={(page+1)*80>=lines.length} onClick={()=>{setPage(p=>p+1);setSegment(0);}}><Icon name="chevron"/></button></div></div>}</div>;
}
