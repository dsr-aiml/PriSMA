"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Landing } from "@/components/landing";
import { ContentMirage } from "@/components/activity-indicator";
import { Brand, ThemeToggle } from "@/components/brand";
import { Icon } from "@/components/icons";
import { PasswordField } from "@/components/password-field";
import { WorkspaceShell } from "@/components/workspace-shell";
import { WebInvestigation } from "@/components/web-investigation";
import { SourceImport } from "@/components/source-import";
import { AssessmentDashboard } from "@/components/assessment-dashboard";
import { useAppearance } from "@/lib/use-appearance";
import { api, APIError, historyChanged, Detail, Investigation, User } from "@/lib/api";
import { formatDate, statusLabel } from "@/lib/presentation";

const terminal = (status: string) => ["completed", "failed", "cancelled"].includes(status);

export default function Workspace({reference=false,assessmentId=""}:{reference?:boolean;assessmentId?:string}) {
  const [user, setUser] = useState<User | null>(null), [authReady, setAuthReady] = useState(false), [register, setRegister] = useState(true);
  const [username, setUsername] = useState(""), [workflow, setWorkflow] = useState(reference?"reference":"sources");
  const [email, setEmail] = useState(""), [password, setPassword] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [depth, setDepth] = useState("standard"), [history, setHistory] = useState<Investigation[]>([]);
  const [selected, setSelected] = useState(assessmentId), [detail, setDetail] = useState<Detail | null>(null);
  const [generation,setGeneration]=useState(0);
  const [syncError, setSyncError] = useState("");
  const {dark, hasIcon, toggleTheme} = useAppearance();

  useEffect(() => {
    setSelected(reference?"":assessmentId||location.hash.slice(1));
    if(!reference&&!assessmentId&&location.hash.slice(1)){location.replace("/assessments/"+encodeURIComponent(location.hash.slice(1)));return;}
    api<User>("/auth/me").then(setUser).catch(() => {}).finally(() => setAuthReady(true));
    const change = () => {if(reference)location.hash="";};
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, [assessmentId,reference]);
  const refresh = useCallback(async () => {
    const items = await api<Investigation[]>("/investigations?scope="+(reference?"reference":"real")); setHistory(items); return items;
  }, [reference]);
  useEffect(() => {
    if (!user || reference) return;
    let active = true;
    const update = () => refresh().catch(error => { if (active) setSyncError(error.message); });
    update(); const timer = setInterval(update, 4000);
    return () => { active = false; clearInterval(timer); };
  }, [user, refresh, reference]);
  useEffect(() => {
    if (reference) return;
    if (!user || !selected) { setDetail(null); return; }
    let active = true, timer: ReturnType<typeof setTimeout>;
    setDetail(null);  setSyncError("");
    async function update() {
      try {
        const result = await api<Detail>("/investigations/" + encodeURIComponent(selected)+"?include_content=false");
        if (!active) return;
        if ((result.mode === "demo") !== reference) { location.replace(result.mode === "demo" ? "/reference#"+result.id : "/assessments/"+result.id); return; }
        setDetail(result); setSyncError("");
        if (!terminal(result.status)) timer = setTimeout(update, 1500);
      } catch (error) {
        if (active) { if(error instanceof APIError&&error.status===401){location.assign("/");return;}setSyncError((error as Error).message);if(!(error instanceof APIError&&[403,404].includes(error.status)))timer=setTimeout(update,3000); }
      }
    }
    update(); return () => { active = false; clearTimeout(timer); };
  }, [user, selected, reference, generation]);

  useEffect(()=>{const cleared=()=>{if(assessmentId){location.assign("/");return;}setHistory([]);setDetail(null);setSelected("");location.hash="";if(user)void refresh();};const storage=(event:StorageEvent)=>{if(event.key==="prisma:workspace-cleared")cleared();};window.addEventListener("prisma:data-cleared",cleared);window.addEventListener("storage",storage);return()=>{window.removeEventListener("prisma:data-cleared",cleared);window.removeEventListener("storage",storage);};},[user,refresh,assessmentId]);
  useEffect(()=>{
    const removed=(id:string)=>{if(id===selected){if(assessmentId){location.assign("/");return;}setSelected("");setDetail(null);location.hash="";}if(user)void refresh();};
    const event=(event:Event)=>removed((event as CustomEvent<string>).detail);
    const storage=(event:StorageEvent)=>{if(event.key==="prisma:report-deleted"&&event.newValue){try{removed(JSON.parse(event.newValue).id);}catch{/* Ignore malformed storage messages. */}}};
    window.addEventListener("prisma:report-deleted",event);window.addEventListener("storage",storage);
    return()=>{window.removeEventListener("prisma:report-deleted",event);window.removeEventListener("storage",storage);};
  },[user,refresh,assessmentId,selected]);
  async function authenticate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { setUser(await api<User>("/auth/" + (register ? "register" : "login"), { method: "POST", body: JSON.stringify(register ? { email, password, username } : { email, password }) })); setPassword(""); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }
  function select(id: string) { if(!reference){location.assign("/assessments/"+encodeURIComponent(id));return;}setSelected(id);location.hash=id; }
  function home() { if(assessmentId){location.assign("/");return;}setSelected("");setDetail(null); location.hash = ""; setError("");  }
  async function start(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { const result = await api<Detail>("/reference?depth="+depth); setDetail(result);setSelected(result.id); }
    catch (error) { setError((error as Error).message); } finally { setBusy(false); }
  }

  async function logout() {
    try { await api("/auth/logout", { method: "POST" }); setUser(null); setHistory([]); home(); }
    catch (error) { setError((error as Error).message); }
  }
  async function control(action:"cancel"|"resume"|"reassess"|"refresh",parameters?:Record<string,unknown>) {
    setBusy(true);setError("");
    try {const result=await api<Investigation>(`/investigations/${selected}/${action}`,{method:"POST",...(parameters?{body:JSON.stringify(parameters)}:{})});historyChanged();if(action==="reassess"||action==="refresh"){select(result.id);return;}setGeneration(value=>value+1);await refresh();}
    catch(error){if((action==="reassess"||action==="refresh")&&error instanceof APIError&&typeof error.details.investigation_id==="string"){select(error.details.investigation_id);return;}setError((error as Error).message);}finally{setBusy(false);}
  }

  if (!authReady) return <main className="boot" id="workspace-root"><Brand hasIcon={hasIcon} /><p>Opening…</p></main>;
  if (!user) return <Landing hasIcon={hasIcon} dark={dark} toggleTheme={toggleTheme} register={register} setRegister={value=>{setRegister(value);setError("");}} busy={busy} error={error} authenticate={authenticate} username={username} setUsername={setUsername} email={email} setEmail={setEmail} password={password} setPassword={setPassword}/>;

  return <><WorkspaceShell report={detail} reference={reference} user={user} history={history} selected={selected} hasIcon={hasIcon} dark={dark} onTheme={toggleTheme} onHome={home} onSelect={select} onLogout={logout}>
      {!selected&&<div className="page-heading"><div><span className="eyebrow">{selected ? "Report" : reference?"Reference":"Architecture"}</span><h1 className="display-title">{selected ? detail?.domain ?? "OPENING REPORT" : reference?"ATLAS REFERENCE.":"UNDERSTAND THE SYSTEM."}</h1></div>{selected && <button className="action-button secondary-action" onClick={home}>New report<Icon name="plus" /></button>}</div>}
      {reference && !selected && <div className="sample-context"><p>Fictional Atlas reference. No reports saved.</p></div>}
      {error && <ErrorNotice message={error} />}{syncError && <ErrorNotice message={syncError}><button className="quiet-button" onClick={() => location.reload()}>Reload workspace<Icon name="arrow" /></button></ErrorNotice>}
      {!selected ? <>
        {!reference&&<div className="investigation-modes" aria-label="Investigation workflow"><button aria-pressed={workflow==="sources"} onClick={()=>setWorkflow("sources")}><Icon name="document" />Files and repositories</button><button aria-pressed={workflow==="web"} onClick={()=>setWorkflow("web")}><Icon name="search" />Live URL</button></div>}
        {!reference ? workflow==="sources"?<SourceImport onCreated={select}/>:<WebInvestigation onCreated={select}/> : <section className="intake-workbench reference-intake"><div className="intake-heading"><div><span className="eyebrow">Reference</span><h2>Reference</h2><p>Architecture, source code and an API contract.</p></div><Icon name="graph"/></div><form onSubmit={start}><div className="reference-scope-options">{[["standard","Complete","Repository dependencies, API operations, resource schemas and commercial terms."],["quick","Core","Architecture declarations, the API contract and frontend dependencies."]].map(([value,title,description])=><button type="button" key={value} aria-pressed={depth===value} onClick={()=>setDepth(value)}><Icon name={value==="standard"?"layers":"graph"}/><span><strong>{title}</strong><small>{description}</small></span><Icon name={depth===value?"check":"arrow"}/></button>)}</div><div className="intake-assessment-footer"><span></span><button className="action-button primary-action" disabled={busy}><span>{busy?"Opening…":"Open report"}</span><Icon name="arrow"/></button></div></form></section>}
        {!reference&&<><section className="overview-continuity"><div className="continuity-title"><span>YOUR RESEARCH WORKSPACE</span><h2>FROM SOURCES<br/>TO UNDERSTANDING.</h2></div><div className="continuity-principles">{[{icon:"layers" as const,title:"Product",text:"Understand the public pages, features and workflows."},{icon:"branch" as const,title:"Systems",text:"Trace code, interfaces and supported service boundaries."},{icon:"document" as const,title:"Evidence",text:"Follow each finding to the sources that establish it."}].map(item=><article key={item.title}><Icon name={item.icon}/><div><h3>{item.title}</h3><p>{item.text}</p></div></article>)}</div></section>
        <section className="recent-section"><div className="section-heading"><div><h2>Reports</h2></div><span>{history.length} saved</span></div>{history.length ? <div className="recent-list">{history.slice(0,8).map(item => <button onClick={() => select(item.id)} key={item.id}><Icon name="document" /><span><strong>{item.domain}</strong><small>{formatDate(item.created_at)}<span className="list-separator">·</span>{item.mode !== "demo" ? "Source assessment" : item.depth === "quick" ? "Essentials" : "Complete"}</small></span><span className="report-state">{statusLabel(item.status)}</span><Icon name="arrow" /></button>)}</div> : <div className="empty-state"><Icon name="graph" /><h3>No reports</h3></div>}</section></>}
      </> : <>
        {!detail&&!syncError&&<ContentMirage label="Opening saved assessment"/>}
        {detail&&<AssessmentDashboard key={detail.id} detail={detail} dark={dark} busy={busy} onControl={(action,parameters)=>void control(action,parameters)}/>}
      </>}
    </WorkspaceShell></>;
}

function ErrorNotice({ message, children }: { message: string; children?: React.ReactNode }) {
  return <div role="alert" className="error"><p>{message}</p>{children}</div>;
}

