"use client";
import { useEffect, useRef, useState } from "react";
function useMotionActivity(){
  const ref=useRef<HTMLDivElement>(null),[paused,setPaused]=useState(false);
  useEffect(()=>{let visible=true;const update=()=>setPaused(document.hidden||!visible);const observer=new IntersectionObserver(([entry])=>{visible=entry.isIntersecting;update();});if(ref.current)observer.observe(ref.current);document.addEventListener("visibilitychange",update);return()=>{observer.disconnect();document.removeEventListener("visibilitychange",update);};},[]);
  return {ref,paused};
}
export function ActivityIndicator({label,detail,mirage=false}:{label:string;detail?:string;mirage?:boolean}){
  const {ref,paused}=useMotionActivity();
  return <div ref={ref} className={`activity-indicator ${paused?"motion-paused":""} ${mirage?"activity-mirage":""}`} role="status"><div className="signal-wave" aria-hidden="true">{Array.from({length:18},(_,index)=><span key={index} style={{height:12+Math.round((Math.sin(index*1.3)+1)*10),animationDelay:`${index*-.13}s`}}/>)}</div><div><strong>{label}</strong>{detail&&<p>{detail}</p>}</div></div>;
}
export function ContentMirage({label="Opening saved records"}:{label?:string}){const {ref,paused}=useMotionActivity();return <div ref={ref} className={`content-mirage ${paused?"motion-paused":""}`} role="status"><span>{label}</span><div aria-hidden="true">{Array.from({length:5},(_,index)=><i key={index} style={{width:`${90-index*11}%`}}/>)}</div></div>;}
