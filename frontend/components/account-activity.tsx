"use client";
import { useState, type CSSProperties } from "react";
import { Icon } from "@/components/icons";
import type { AccountActivity } from "@/lib/api";
import { formatDate, statusLabel } from "@/lib/presentation";

export function AccountActivityView({activity,sources,questions}:{activity:AccountActivity;sources:number;questions:number}){
  const [selected,setSelected]=useState("");
  const days=activity.days,total=days.reduce((sum,day)=>sum+day.assessments,0),peak=Math.max(1,...days.map(day=>day.assessments));
  const focus=days.find(day=>day.date===selected)??days.at(-1);
  const outcomes=Object.entries(activity.outcomes).sort(([a],[b])=>a.localeCompare(b));
  const all=outcomes.reduce((sum,[,count])=>sum+count,0);
  const dateLabel=(date:string)=>new Date(date+"T12:00:00Z").toLocaleDateString(undefined,{month:"short",day:"numeric",timeZone:"UTC"});
  return <section className="account-trail" aria-labelledby="account-trail-title">
    <div className="trail-introduction"><div><span className="eyebrow">Your workspace in motion</span><h2 id="account-trail-title">An assessment trail.</h2><p>Each mark is a day of work. Your saved evidence and questions stay connected to the reports below.</p></div><dl><div><dt>Sources retained</dt><dd>{sources.toLocaleString()}</dd></div><div><dt>Questions saved</dt><dd>{questions.toLocaleString()}</dd></div></dl></div>
    <div className="trail-body"><div className="trail-chart"><div className="trail-chart-heading"><div><strong>{total}</strong><span>assessments created in 28 days</span></div><output aria-live="polite">{focus?`${dateLabel(focus.date)} · ${focus.assessments} created`:"No activity"}</output></div>
      <div className="trail-bars" role="group" aria-label="Daily assessments, UTC. Focus or select a day for its count.">{days.map((day,index)=><button key={day.date} className={`${day.assessments?"has-activity":""} ${focus?.date===day.date?"is-current":""}`} style={{"--bar-height":`${Math.max(3,day.assessments/peak*100)}%`,"--bar-delay":`${index*14}ms`} as CSSProperties} aria-label={`${dateLabel(day.date)}: ${day.assessments} assessments`} aria-pressed={focus?.date===day.date} onFocus={()=>setSelected(day.date)} onPointerEnter={()=>setSelected(day.date)} onClick={()=>setSelected(day.date)}><span/></button>)}</div>
      <div className="trail-axis"><span>{days[0]&&dateLabel(days[0].date)}</span><span>Daily activity · UTC</span><span>{days.at(-1)&&dateLabel(days.at(-1)!.date)}</span></div>
      <div className="trail-outcomes"><div className="trail-outcome-line" aria-hidden="true">{outcomes.map(([status,count])=><span key={status} data-status={status} style={{flex:count}}/>)}</div><div>{outcomes.map(([status,count])=><span key={status}><i data-status={status}/>{statusLabel(status)} <strong>{count}</strong></span>)}{!all&&<span>Your first assessment will appear here.</span>}</div><small>All saved assessments · {all}</small></div>
    </div><div className="trail-recent"><h3>Latest work</h3>{activity.recent.map(item=><a href={"/assessments/"+item.id} key={item.id}><span><strong>{item.name}</strong><small>{formatDate(item.created_at)} · {statusLabel(item.status)}</small></span><Icon name="arrow"/></a>)}{!activity.recent.length&&<p>Start with a repository, folder, ZIP or public URL. Your history grows here.</p>}</div></div>
  </section>;
}
