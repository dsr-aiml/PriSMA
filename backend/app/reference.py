"""Stateless reference sources use the same scanners and report contract as actual runs."""
import hashlib
import json
import time
from collections import Counter
from functools import lru_cache
from copy import deepcopy
from pathlib import Path

from .exports import evidence_dict
from .intelligence import PARSER_VERSION, chunk_spans, create_report, deterministic, normalize_source, verify_citations
from .models import Chunk, Evidence, now
from .research import research_summary
from .schemas import ImportedSource
from .source_analysis import inspect_document, prepare_source
from .static_scanners import scan_repository


@lru_cache(maxsize=2)
def reference_material(depth):
    started = time.monotonic()
    identity = "reference-" + depth
    fixture = json.loads((Path(__file__).parent.parent / "fixtures" / "atlas-sources.json").read_text())
    rows = [row for row in fixture["sources"] if depth != "quick" or row["scope"] == "quick"]
    evidence, chunks = [], []
    created = now()
    for index, row in enumerate(rows):
        source, _ = prepare_source(ImportedSource(**{key: value for key, value in row.items() if key != "scope"}))
        content = normalize_source(source)
        info = inspect_document(source, content)
        item = Evidence(id=f"{identity}:source-{index+1}", investigation_id=identity, source_url=source.origin,
            source_type=source.format, category=info["document_kind"], content=content, original_content=source.content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(), signals={"title": source.title, **{key:value for key,value in info.items() if key != "parser_data"}},
            collection_method="versioned_fixture", provenance="Atlas 3.0 — fictional reference source bundle", collected_at=created)
        evidence.append(item)
        for part, (start, end) in enumerate(chunk_spans(content)):
            chunks.append(Chunk(id=f"{identity}:s{index+1}p{part+1}", investigation_id=identity, evidence_id=item.id, start=start, end=end, content=content[start:end]))
    scanner = scan_repository(evidence)
    run = {"kind":"rules_only", "provider":"rules", "model":"structural parser", "parser_version":PARSER_VERSION,
        "prompt_version":"reference-source-bundle-3", "elapsed_ms":0, "requests":0, "cache_hits":0,
        "passages":len(chunks), "processed_passages":0, "parsed_documents":len(evidence),
        "retrieval":"lexical", "rejected_candidates":0, "rejection_reasons":{},
        "source_inventory":dict(Counter(e.category for e in evidence)), "structural_coverage":scanner["inventory"]["coverage"],
        "coverage":{"source_documents":len(evidence), "discovered_files":len(evidence), "retained_files":len(evidence), "selected_files":len(evidence), "excluded_files":0, "status":"complete"},
        "validation":"Exact source spans and structural reference validation; the source set is fictional."}
    lookup = {c.id:c for c in chunks}
    accepted = [(f,verify_citations(f.citations,lookup),"parser") for f in deterministic(evidence,chunks,scanner)]
    report = create_report(evidence, accepted, [], run, scanner)
    run["elapsed_ms"] = round((time.monotonic()-started)*1000)
    report["fixture"] = "Atlas 3.0"
    return report,evidence,chunks


def reference_snapshot(depth="standard"):
    report,evidence,_ = reference_material(depth)
    report = deepcopy(report)
    created = now()
    identity = "reference-" + depth
    return {"id":identity, "domain":"Atlas", "depth":depth, "mode":"demo", "status":"completed", "progress":100,
        "has_report":True, "engine":"rules", "model":None, "error":None, "created_at":created.isoformat(), "updated_at":created.isoformat(),
        "report":report, "analysis":research_summary(report,evidence,reference=True),
        "evidence":[{**evidence_dict(e), "content_loaded":True} for e in evidence], "events":[], "passages":[],
        "processing_options":{"provider":"rules", "semantic_retrieval":False},
        "actions":{"refresh_available":False, "repositories":[]}, "ephemeral":True}, evidence


def reference_answer(question, depth="standard"):
    from .query_engine import rank_passages, structured_answer
    report,evidence,chunks = reference_material(depth)
    answer = {**structured_answer(report,evidence,question), "answer_version":2, "provider":"rules", "retrieval":"lexical", "statements":[], "elapsed_ms":0}
    answer["insufficient_evidence"] = not answer["findings"]
    answer["passages"] = [{"chunk_id":c.id,"evidence_id":c.evidence_id,"content":c.content,"start":c.start,"end":c.end,"score":round(score,4)} for score,c in rank_passages(chunks,question,evidence=evidence)]
    return answer
