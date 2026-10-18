"""Bounded report context for conversational research, without a rewrite model call."""
import json
import re
from types import SimpleNamespace

from .query_engine import _rank_text


def format_request(question):
    value = question.casefold().strip()
    if re.search(r"\b(?:pointer events?|pointer interactions?|mouse|touch|javascript|code|api|database|authentication|architecture|repository)\b", value):
        return False
    if not re.search(r"\b(?:\d+\s*words?|pointers|bullet points?|bullets|shorter|briefer|summari[sz]e|simplify|rephrase|condense|elaborate|expand|more(?: details?)?)\b", value):
        return False
    # A requested length does not make an explicit new subject a rewrite.
    value = re.sub(r"\b\d+\s*words?\b", " ", value)
    filler = {"a", "an", "the", "me", "please", "can", "could", "you", "would", "will", "tell", "give", "write", "make", "say", "explain", "show", "answer", "response", "reply", "it", "this", "that", "these", "those", "them", "above", "same", "again", "now", "in", "as", "of", "to", "with", "using", "and", "or", "for", "about", "around", "under", "within", "maximum", "max", "at", "most", "up", "no", "more", "than", "words", "word", "pointers", "bullet", "points", "bullets", "shorter", "short", "briefer", "brief", "briefly", "concise", "summarize", "summarise", "simplify", "rephrase", "condense", "elaborate", "expand", "detail", "details", "detailed", "depth", "deeper", "much", "some", "instead", "into", "on", "its", "your", "last", "previous", "step", "by"}
    return not (set(re.findall(r"[a-z]+", value)) - filler)


def conversation_query(question, history):
    # Carry referents for short follow-ups; an explicit new topic keeps its own retrieval.
    pronouns = {"it", "that", "those", "them", "they", "its", "second", "first", "last"}
    tokens = set(question.lower().strip('?.!').split())
    if history and format_request(question):
        return next((turn["question"][:500] for turn in reversed(history) if not format_request(turn["question"])), history[-1]["question"][:500])
    if history and (tokens & pronouns or tokens & {'this', 'these'}):
        topic = next((turn["question"][:500] for turn in reversed(history) if not format_request(turn["question"])), history[-1]["question"][:500])
        return question + "\nPrevious topic: " + topic
    return question


def synopsis(report):
    fields = {
        "components": ("nodes", ("id", "label", "kind", "context", "module_paths")),
        "relationships": ("edges", ("source", "target", "label", "relationship_kind", "context")),
        "technologies": ("technologies", ("name", "category", "declarations")),
        "api": ("api_endpoints", ("method", "path", "summary")),
        "data_models": ("entities", ("name", "context")),
        "capabilities": ("features", ("feature", "tier", "availability")),
    }
    result={"product": {k: (report.get("product") or {}).get(k) for k in ("description", "coverage", "open_questions")}, "summary":report.get("summary", "")[:500], "coverage":report.get("run",{}).get("structural_coverage",{}), "counts":{key:len(report.get(key,[])) for key in ('nodes','edges','technologies','api_endpoints','entities','fields','features')}}
    product = report.get("product") or {}
    result["product"]["workflows"] = [{k: w.get(k) for k in ("title", "status", "execution")} for w in product.get("workflows", [])[:6]]
    result["product"]["features"] = [{k: f.get(k) for k in ("text", "status", "tier")} for f in product.get("features", [])[:6]]
    if any((m.get("path", "").startswith(("https://", "http://", "web/"))) for m in (report.get("repository") or {}).get("modules", [])):
        result["implementation_scope"] = "Retained shipped browser code; original repository structure and private backend internals are not established."
    for label,(key,keys) in fields.items():
        rows=[]
        for row in report.get(key,[])[:16]:
            selected={k:row[k] for k in keys if k in row}
            if 'module_paths' in selected:selected['module_paths']=selected['module_paths'][:3]
            if 'declarations' in selected:selected['declarations']=[{k:d[k] for k in ('group','version') if k in d} for d in selected['declarations'][:3]]
            rows.append(selected)
        result[label]=rows
    # No whole repository inventory, duplicated sources, credentials or giant prompt.
    while len(json.dumps(result,ensure_ascii=False).encode()) > 6500:
        largest=max(fields,key=lambda key:len(json.dumps(result[key])))
        if not result[largest]:break
        result[largest].pop()
    return result


def report_units(report, evidence, question, previous=(), maximum=24):
    """Citation-backed orientation including follow-up referents and diverse report claims."""
    sources={s.id:s for s in evidence}
    claims=report.get('claims',[])
    ranked=sorted(claims,key=lambda c:-_rank_text(c.get('description','')+' '+c.get('context',''),question))
    chosen=[]; seen=set(); counts={}
    product = report.get("product") or {}
    product_records = product.get("purpose", [])[:2] + product.get("workflows", [])[:8] + product.get("features", [])[:8]
    citations=[{**c, "product_unit": True} for row in product_records for c in row.get("citations", [])[:1]]
    citations += [c for turn in previous[-2:] for c in turn.get('citations',[])][:6]
    citations += [citation for claim in ranked for citation in claim.get('citations',[])[:1]]
    for citation in citations:
        source=sources.get(citation.get('evidence_id'));start,end=citation.get('start'),citation.get('end')
        if source is None or not isinstance(start,int) or not isinstance(end,int) or not 0 <= start < end <= len(source.content):continue
        text=source.content[start:end]
        if text != citation.get('quote') or text in seen or counts.get(source.id,0)>=4:continue
        if len(text)>600:text=text[:600];end=start+600
        chosen.append(SimpleNamespace(id=('product:' if citation.get("product_unit") else 'report:')+str(len(chosen)), evidence_id=source.id,content=text,start=start,end=end))
        seen.add(text);counts[source.id]=counts.get(source.id,0)+1
        if len(chosen)>=maximum:break
    # Broad conversational questions still receive README/configuration orientation
    # even when there are no successful parser findings or lexical keyword matches.
    for source in sorted(evidence,key=lambda s:(s.signals or {}).get('analysis_priority',9)):
        if len(chosen)>=maximum:break
        if (source.signals or {}).get('document_kind') not in {'architecture','documentation','manifest'} or source.id in counts:continue
        text=source.content[:600]
        if len(text)>=12 and text not in seen:
            chosen.append(SimpleNamespace(id='orientation:'+source.id, evidence_id=source.id,content=text,start=0,end=len(text)));seen.add(text)
    return chosen
