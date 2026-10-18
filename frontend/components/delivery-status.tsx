"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Icon } from "@/components/icons";
type State={available:boolean;state:string;recoverable:boolean;reason:string;deliveries?:string[]};
export function DeliveryStatus({id}:{id:string}){
  const [state,setState]=useState<State|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  async function check(){setBusy(true);setError("");try{setState(await api<State>(`/investigations/${id}/delivery`));}catch(error){setError((error as Error).message);}finally{setBusy(false);}}
  async function recover(){setBusy(true);setError("");try{await api(`/investigations/${id}/recover`,{method:"POST"});location.reload();}catch(error){setError((error as Error).message);setBusy(false);}}
  return <div className="delivery-status"><button className="quiet-button" disabled={busy} onClick={()=>void check()}><Icon name="queue"/>{busy?"Checking delivery…":"Check worker delivery"}<Icon name="arrow"/></button>{state&&<p role="status">{state.reason}{state.deliveries?.length?" "+state.deliveries.join(", ")+".":""}</p>}{state?.recoverable&&<button className="quiet-button" disabled={busy} onClick={()=>void recover()}>Reconcile interrupted assessment<Icon name="refresh"/></button>}{error&&<p role="alert">{error}</p>}</div>;
}
