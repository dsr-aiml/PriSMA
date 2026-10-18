"use client";
import { useId, useState, type ReactNode } from "react";
import { Select, DropdownMenu, Tooltip } from "radix-ui";
import { Icon, type IconName } from "@/components/icons";
export type SelectOption={value:string;label:string;description?:string;icon?:IconName;disabled?:boolean};
export function SelectField({label,value,options,onChange,disabled=false,compact=false}:{label:string;value:string;options:SelectOption[];onChange:(value:string)=>void;disabled?:boolean;compact?:boolean}){
  const selected=options.find(option=>option.value===value),id=useId();
  return <div className={compact?"select-field compact-select":"select-field"}>{!compact&&<label className="select-label" htmlFor={id}>{label}</label>}<Select.Root value={value} onValueChange={onChange} disabled={disabled}><Select.Trigger id={id} className="select-trigger" aria-label={label}>{selected?.icon&&<Icon name={selected.icon}/>}<span className="select-current">{selected?.label||label}</span><Select.Icon className="select-chevron"><Icon name="chevron"/></Select.Icon></Select.Trigger><Select.Portal><Select.Content className="prisma-select" position="popper" sideOffset={7} collisionPadding={16}><Select.ScrollUpButton className="select-scroll"><Icon name="chevron" className="up-icon"/></Select.ScrollUpButton><Select.Viewport>{options.map(option=><Select.Item className="select-option" key={option.value} value={option.value} disabled={option.disabled}>{option.icon&&<Icon name={option.icon}/>}<span className="select-option-copy"><Select.ItemText>{option.label}</Select.ItemText>{option.description&&<small>{option.description}</small>}</span><Select.ItemIndicator className="select-check"><Icon name="check"/></Select.ItemIndicator></Select.Item>)}</Select.Viewport><Select.ScrollDownButton className="select-scroll"><Icon name="chevron"/></Select.ScrollDownButton></Select.Content></Select.Portal></Select.Root></div>;
}
const formats:{format:string;label:string;extension:string;icon:IconName}[]=[
  {format:"markdown",label:"Assessment",extension:"MD",icon:"document"},
  {format:"json",label:"Report data",extension:"JSON",icon:"code"},
  {format:"sqlite",label:"Database",extension:"SQLITE",icon:"database"},
  {format:"evidence",label:"Source bundle",extension:"ZIP",icon:"folder"}
];
export function ExportMenu({id,referenceDepth,disabled=false}:{id:string;referenceDepth?:string;disabled?:boolean}){
  const [open,setOpen]=useState(false),[error,setError]=useState(""),[busy,setBusy]=useState("");
  async function download(format:string){
    if(busy)return;setBusy(format);setError("");
    try{
      const base=referenceDepth?"/api/reference/"+encodeURIComponent(referenceDepth):"/api/investigations/"+encodeURIComponent(id);
      const response=await fetch(base+"/export/"+format,{credentials:"same-origin",cache:"no-store"});
      if(!response.ok){let message="The export could not be prepared.";try{const data=await response.json();if(typeof data.detail==="string")message=data.detail;}catch{}throw new Error(message);}
      const blob=await response.blob(),url=URL.createObjectURL(blob),anchor=document.createElement("a");
      anchor.href=url;anchor.download=response.headers.get("content-disposition")?.match(/filename="([^"]+)"/)?.[1]||"prisma-report."+formats.find(f=>f.format===format)!.extension.toLowerCase();document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);setOpen(false);
    }catch(error){setError((error as Error).message);}finally{setBusy("");}
  }
  return <DropdownMenu.Root open={open} onOpenChange={setOpen}><DropdownMenu.Trigger asChild><button type="button" className="export-trigger" disabled={disabled||!!busy} aria-label="Export assessment"><Icon name="download"/><span>{busy?"Preparing…":"Export"}</span><Icon name="chevron"/></button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="prisma-menu export-menu" side="bottom" sideOffset={8} align="end" collisionPadding={16} aria-label="Export formats">{formats.map(item=><DropdownMenu.Item className="export-menu-item" key={item.format} disabled={!!busy} onSelect={event=>{event.preventDefault();void download(item.format);}}><Icon name={item.icon}/><span className="export-menu-copy"><strong>{item.label}</strong></span><span className="export-menu-extension">{item.extension}</span></DropdownMenu.Item>)}{error&&<p className="export-menu-error" role="alert">{error}</p>}</DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>;
}
export function Tip({label,children}:{label:string;children:ReactNode}){
  return <Tooltip.Provider delayDuration={450}><Tooltip.Root><Tooltip.Trigger asChild>{children}</Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="prisma-tooltip" sideOffset={8}>{label}<Tooltip.Arrow/></Tooltip.Content></Tooltip.Portal></Tooltip.Root></Tooltip.Provider>;
}
export function CopyButton({text,label="Copy"}:{text:string;label?:string}){
  const [state,setState]=useState("idle");
  async function copy(){try{await navigator.clipboard.writeText(text);setState("copied");setTimeout(()=>setState("idle"),1800);}catch{setState("failed");}}
  return <button type="button" className="quiet-button copy-control" onClick={()=>void copy()}><Icon name={state==="copied"?"check":"copy"}/><span aria-live="polite">{state==="copied"?"Copied":state==="failed"?"Copy unavailable":label}</span></button>;
}
