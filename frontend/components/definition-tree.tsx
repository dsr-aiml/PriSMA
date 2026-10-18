"use client";
import { useState } from "react";
export function DefinitionTree({value,name="Definition",depth=0}:{value:unknown;name?:string;depth?:number}){
  const [open,setOpen]=useState(depth===0),[limit,setLimit]=useState(40);
  if(value===null||typeof value!=="object")return <div className="definition-value"><code>{name}</code><span>{value===undefined?"Unspecified":String(value)}</span></div>;
  const entries=Object.entries(value);
  return <details className="definition-tree" open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary><code>{name}</code><span>{entries.length} {Array.isArray(value)?"items":"fields"}</span></summary>{open&&(depth<12?<div>{entries.slice(0,limit).map(([key,child])=><DefinitionTree key={key} value={child} name={key} depth={depth+1}/>)}{entries.length>limit&&<button className="quiet-button" onClick={()=>setLimit(v=>v+40)}>Show more fields</button>}</div>:<p className="muted-copy">Further nesting is available in the exported contract.</p>)}</details>;
}
