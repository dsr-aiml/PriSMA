"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { SettingSwitch } from "@/components/source-controls";
import { Icon } from "@/components/icons";
import { SelectField } from "@/components/ui";

export type ProcessingSettings = {provider:"rules"|"ollama"|"gemini";model_profile:"light"|"balanced"|"advanced";semantic_retrieval:boolean};
export const defaultProcessing:ProcessingSettings = {provider:"rules",model_profile:"light",semantic_retrieval:false};
type Profile={id:ProcessingSettings["model_profile"];label:string;description:string;model:string;enabled:boolean;max_bytes:number};
type Catalog={embedding_model:string;profiles:Profile[];memory_budget_bytes:number;gpu_layers:number;models:{name:string;size:number}[];reason:string;note:string;running:{name:string;size_vram:number}[]};

export function AnalysisOptions({value,onChange,compact=false,semanticAvailable=true}:{value:ProcessingSettings;onChange:(value:ProcessingSettings)=>void;compact?:boolean;semanticAvailable?:boolean}){
  const [catalog,setCatalog]=useState<Catalog|null>(null),[readiness,setReadiness]=useState(""),[checking,setChecking]=useState(false);
  useEffect(()=>{let active=true;setReadiness("");if(value.provider==="ollama")api<Catalog>("/models/installed").then(v=>{if(active)setCatalog(v);}).catch(e=>{if(active)setReadiness(e.message);});return()=>{active=false;};},[value.provider]);
  function change(patch:Partial<ProcessingSettings>){setReadiness("");onChange({...value,...patch});}
  async function check(){setChecking(true);setReadiness("");try{const result=await api<{ready:boolean;reason:string}>(`/models/readiness?provider=${value.provider}&profile=${value.model_profile}&semantic=${value.semantic_retrieval}`);setReadiness(result.reason);}catch(e){setReadiness((e as Error).message);}finally{setChecking(false);}}
  const engines=[{value:"rules",label:"Explicit parsing",description:"Source declarations",icon:"code" as const},{value:"ollama",label:"Local inference",description:"On-device interpretation",icon:"server" as const},{value:"gemini",label:"Hosted inference",description:"Google interpretation",icon:"cloud" as const}];
  const choose=(provider:string)=>change({provider:provider as ProcessingSettings["provider"],semantic_retrieval:provider==="rules"?false:value.semantic_retrieval});
  return <div className={"processing-settings"+(compact?" compact-processing":"")}>
    {compact?<SelectField label="Query engine" value={value.provider} onChange={choose} options={engines}/>:<fieldset className="engine-fieldset"><legend>Engine</legend><div className="engine-options" role="group" aria-label="Engine">{engines.map(engine=><button type="button" key={engine.value} aria-pressed={value.provider===engine.value} onClick={()=>choose(engine.value)}><Icon name={engine.icon}/><span><strong>{engine.label}</strong><small>{engine.description}</small></span><Icon name="check"/></button>)}</div></fieldset>}

    {value.provider==="ollama"&&<section className="local-profiles"><SelectField label="Local model profile" value={value.model_profile} onChange={profile=>change({model_profile:profile as ProcessingSettings["model_profile"]})} options={(catalog?.profiles??[{id:"light",label:"Lightweight",description:"Loading server configuration",model:"",enabled:true,max_bytes:2000000000}]).map(profile=>({value:profile.id,label:profile.label,description:profile.model||"Configuration loading",disabled:!profile.enabled,icon:"layers"}))}/>{catalog&&<div className="selected-model-record"><span>Analysis model</span><code>{catalog.profiles.find(profile=>profile.id===value.model_profile)?.model||"Not configured"}</code></div>}{catalog&&<details className="profile-capacity"><summary>Inference server capacity<Icon name="chevron" /></summary><p>Analysis model: <code>{catalog.profiles.find(profile=>profile.id===value.model_profile)?.model||"Not configured"}</code>.</p><p>Passage embeddings: <code>{catalog.embedding_model}</code> · {value.semantic_retrieval?"enabled":"disabled"}.</p><p>{(catalog.memory_budget_bytes/1e9).toFixed(1)} GB configured memory budget. {catalog.gpu_layers===0?"CPU processing.":"GPU offload configured; check observed usage during a run."}</p>{catalog.reason&&<p>{catalog.reason}</p>}<ul>{catalog.models.map(model=><li key={model.name}><span>{model.name}</span><span>{(model.size/1e9).toFixed(2)} GB weights</span></li>)}</ul>{catalog.running.map(model=><p key={model.name}>{model.name}: {(model.size_vram/1e9).toFixed(2)} GB observed VRAM.</p>)}<p>{catalog.note}</p></details>}</section>}
    {value.provider!=="rules"&&<div className="model-options"><SettingSwitch label="Semantic source retrieval" description="Passage index" checked={value.semantic_retrieval} disabled={!semanticAvailable} onChange={checked=>change({semantic_retrieval:checked})}/><button type="button" className="quiet-button" disabled={checking} onClick={()=>void check()}>{checking?"Checking…":"Check service"}<Icon name="arrow" /></button>{readiness&&<p role="status">{readiness}</p>}</div>}
  </div>;
}
