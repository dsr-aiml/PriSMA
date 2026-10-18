"use client";
import { Icon } from "@/components/icons";

export function ScopeCounter({label,description,value,min,max,onChange}:{label:string;description:string;value:number;min:number;max:number;onChange:(value:number)=>void}) {
  return <div className="scope-counter"><div><strong>{label}</strong><p>{description}</p></div><div className="counter-actions" role="group" aria-label={label}><button type="button" className="counter-button" aria-label={"Decrease "+label.toLowerCase()} disabled={value<=min} onClick={()=>onChange(Math.max(min,value-1))}><Icon name="minus"/></button><input type="number" inputMode="numeric" min={min} max={max} value={value} aria-label={label+" limit"} onChange={event=>{const next=Number(event.target.value);if(Number.isFinite(next))onChange(Math.min(max,Math.max(min,Math.floor(next))));}}/><button type="button" className="counter-button" aria-label={"Increase "+label.toLowerCase()} disabled={value>=max} onClick={()=>onChange(Math.min(max,value+1))}><Icon name="plus"/></button></div></div>;
}

export function SettingSwitch({label,description,checked,onChange,disabled=false}:{label:string;description:string;checked:boolean;onChange:(checked:boolean)=>void;disabled?:boolean}) {
  return <label className={"setting-switch "+(disabled?"is-disabled":"")}><span><strong>{label}</strong><small>{description}</small></span><input type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={event=>onChange(event.target.checked)}/><span className="switch-rail" aria-hidden="true"><span/></span></label>;
}
