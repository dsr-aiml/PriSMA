import { SourceContent } from "@/components/source-content";
import { Claim, Evidence } from "@/lib/api";
import { DefinitionTree } from "@/components/definition-tree";
import { classificationLabel } from "@/lib/presentation";

export function ClaimDetails({ claim, evidence }: { claim: Claim; evidence: Evidence[] }) {
  const supporting = evidence.filter(item => claim.supporting_evidence_ids.includes(item.id));
  const contradicting = evidence.filter(item => claim.contradicting_evidence_ids.includes(item.id));
  return <div className="claim-detail">
    <span className="classification-text">{classificationLabel(claim.classification)}</span>
    <h3>{claim.description}</h3>
    <div className="evidence-strength"><strong>{claim.confidence}</strong><div><span>Evidence strength</span><small>Rubric score out of 100, not a probability</small></div></div>
    <section><h4>Assessment</h4><p>{claim.confidence_explanation}</p></section>
    {!!claim.attributes && Object.keys(claim.attributes).length > 0 && <section className="finding-properties"><h4>Documented properties</h4><dl>{Object.entries(claim.attributes).filter(([,value])=>value!==""&&value!==null).map(([key,value])=><div key={key}><dt>{key.replaceAll("_"," ")}</dt><dd>{typeof value==="object"?<DefinitionTree value={value} name="Definition"/>:String(value)}</dd></div>)}</dl></section>}
    {!!claim.citations?.length && <section className="citation-excerpts"><h4>Cited passages</h4>{claim.citations.map((citation,index)=><blockquote key={index}><p>{citation.quote}</p><small>{citation.role} · {evidence.find(item=>item.id===citation.evidence_id)?.source_url??citation.evidence_id} · characters {citation.start}–{citation.end}</small></blockquote>)}</section>}
    <section><h4>Supporting sources <span>{supporting.length}</span></h4>{supporting.map(item => <SourceRecord key={item.id} item={item} />)}</section>
    {contradicting.length > 0 && <section className="conflicting-sources"><h4>Conflicting sources <span>{contradicting.length}</span></h4>{contradicting.map(item => <SourceRecord key={item.id} item={item} />)}</section>}

  </div>;
}

function SourceRecord({ item }: { item: Evidence }) {
  return <article className="source-record"><span className="source-category">{item.category.replaceAll("_", " ")}</span><code>{item.source_url}</code><p>{item.content.slice(0,400)}</p><SourceContent source={item}/><small>{item.provenance}</small></article>;
}
