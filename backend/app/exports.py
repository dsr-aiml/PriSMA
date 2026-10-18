import csv
import hashlib
import html
import io
import json
import re
import sqlite3
import tempfile
import zipfile

from .models import Evidence, Investigation
from .source_storage import original_text, public_signals
from .research import research_summary
from .source_semantics import visible_report

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE investigations(id TEXT PRIMARY KEY, domain TEXT NOT NULL, mode TEXT NOT NULL,
 fixture TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, summary TEXT NOT NULL);
CREATE TABLE sources(id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), url TEXT NOT NULL, type TEXT NOT NULL);
CREATE TABLE evidence(id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), source_id TEXT NOT NULL REFERENCES sources(id),
 category TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL, collected_at TEXT NOT NULL,
 collection_method TEXT NOT NULL, provenance TEXT NOT NULL, signals_json TEXT NOT NULL);
CREATE TABLE claims(id TEXT PRIMARY KEY, investigation_id TEXT NOT NULL REFERENCES investigations(id), type TEXT NOT NULL,
 description TEXT NOT NULL, classification TEXT NOT NULL, confidence INTEGER NOT NULL CHECK(confidence BETWEEN 0 AND 100),
 confidence_explanation TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE claim_evidence_links(claim_id TEXT NOT NULL REFERENCES claims(id), evidence_id TEXT NOT NULL REFERENCES evidence(id),
 role TEXT NOT NULL CHECK(role IN ('supporting','contradicting')), PRIMARY KEY(claim_id,evidence_id,role));
CREATE TABLE technologies(id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, claim_id TEXT NOT NULL REFERENCES claims(id));
CREATE TABLE api_endpoints(id TEXT PRIMARY KEY, method TEXT NOT NULL, path TEXT NOT NULL, classification TEXT NOT NULL, claim_id TEXT NOT NULL REFERENCES claims(id));
CREATE TABLE inferred_entities(id TEXT PRIMARY KEY, name TEXT NOT NULL, confidence INTEGER NOT NULL, claim_id TEXT NOT NULL REFERENCES claims(id));
CREATE TABLE inferred_fields(id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES inferred_entities(id), name TEXT NOT NULL, type TEXT NOT NULL,
 claim_id TEXT NOT NULL REFERENCES claims(id));
CREATE TABLE inferred_relationships(id TEXT PRIMARY KEY, source_entity_id TEXT NOT NULL REFERENCES inferred_entities(id),
 target_entity_id TEXT NOT NULL REFERENCES inferred_entities(id), field TEXT NOT NULL, cardinality TEXT NOT NULL, claim_id TEXT NOT NULL REFERENCES claims(id));
CREATE TABLE architecture_nodes(id TEXT PRIMARY KEY, label TEXT NOT NULL, kind TEXT NOT NULL, confidence INTEGER NOT NULL,
 classification TEXT NOT NULL, claim_id TEXT NOT NULL REFERENCES claims(id));
CREATE TABLE architecture_edges(id TEXT PRIMARY KEY, source_node_id TEXT NOT NULL REFERENCES architecture_nodes(id),
 target_node_id TEXT NOT NULL REFERENCES architecture_nodes(id), label TEXT NOT NULL, confidence INTEGER NOT NULL,
 classification TEXT NOT NULL, claim_id TEXT NOT NULL REFERENCES claims(id));
CREATE INDEX evidence_investigation_idx ON evidence(investigation_id);
CREATE INDEX claims_investigation_idx ON claims(investigation_id);
CREATE INDEX claim_evidence_evidence_idx ON claim_evidence_links(evidence_id);
CREATE INDEX fields_entity_idx ON inferred_fields(entity_id);
CREATE INDEX edges_source_idx ON architecture_edges(source_node_id);
CREATE INDEX edges_target_idx ON architecture_edges(target_node_id);
"""


def evidence_dict(e: Evidence):
    return {
        "id": e.id,
        "investigation_id": e.investigation_id,
        "source_url": e.source_url,
        "source_type": e.source_type,
        "category": e.category,
        "content": e.content,
        "original_content": original_text(e),
        "content_hash": e.content_hash,
        "signals": public_signals(e),
        "provenance": e.provenance,
        "collection_method": e.collection_method,
        "collected_at": e.collected_at.isoformat(),
    }


def disclaimer(inv):
    if inv.mode == "demo":
        return "Fictional Atlas fixtures, not findings about the requested domain. The SQLite schema represents this report, not a competitor database."
    if inv.mode == "live":
        return "Assessment of public documents, linked client code and selected browser observations. Collection coverage is recorded below. Client interfaces and logical data definitions do not establish private service internals or physical storage."
    return "User-supplied snapshots; attribution was not independently fetched. Interpretations require source review. Logical entities and the SQLite report schema do not establish private physical storage."


def passage_dict(chunk):
    return {
        "id": chunk.id,
        "evidence_id": chunk.evidence_id,
        "start": chunk.start,
        "end": chunk.end,
        "content": chunk.content,
        "embedding_model": chunk.embedding_model,
    }


def question_dict(question):
    return {
        "id": question.id,
        "chat_id": question.chat_id,
        "question": question.question,
        "status": question.status,
        "answer": question.answer,
        "processing_options": question.processing_options,
        "error": question.error,
        "created_at": question.created_at.isoformat(),
    }


def report_document(inv: Investigation, evidence: list[Evidence], chunks=(), questions=(), *, compact=False):
    document = dict(
        schema_version=4 if compact else 3,
        contract="prisma.report",
        title="Architecture assessment — " + inv.domain,
        investigation_id=inv.id,
        requested_domain=inv.domain,
        mode=inv.mode,
        created_at=inv.created_at.isoformat(),
        generated_at=inv.updated_at.isoformat(),
        disclaimer=disclaimer(inv),
        processing_options=inv.processing_options,
        report=visible_report(inv.report, evidence),
        analysis=research_summary(visible_report(inv.report,evidence), evidence, inv.processing_options, reference=inv.mode == "demo"),
        evidence=[evidence_dict(e) for e in evidence],
        passages=[passage_dict(c) for c in chunks],
        questions=[question_dict(q) for q in questions],
    )
    if compact:
        document["content_storage"] = "normalized_snapshots"
        document["source_texts"] = {e.content_hash: e.content for e in evidence}
        document["evidence"] = [{k: v for k, v in evidence_dict(e).items() if k not in {"content", "original_content"}} | {"content_ref": e.content_hash, "characters": len(e.content)} for e in evidence]
        document["passages"] = [{k: v for k, v in passage_dict(c).items() if k != "content"} for c in chunks]
        # Provider alternates are audit metadata, not additional inline source copies.
        for e in document["evidence"]:
            e["signals"] = dict(e.get("signals") or {})
            if e["signals"].get("alternate_representations"):
                e["signals"]["alternate_representations"] = [{k: v for k, v in row.items() if k != "raw_content"} for row in e["signals"]["alternate_representations"]]
    return document


def evidence_bundle(inv, evidence, chunks=(), questions=()):
    document = report_document(inv, evidence, chunks, questions, compact=True)
    document.pop("source_texts", None)
    document["content_storage"] = "bundle_files"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        written = set()
        for row, source in zip(document["evidence"], evidence, strict=True):
            for field, content in (("content_ref", source.content), ("original_ref", original_text(source))):
                name = "evidence/" + hashlib.sha256(content.encode()).hexdigest() + ".txt"
                row[field] = name
                if name not in written:
                    archive.writestr(name, content)
                    written.add(name)
        archive.writestr("prisma-evidence.json", json.dumps(document, ensure_ascii=False, separators=(",", ":")))
    return output.getvalue()


def md(value):
    value = html.escape(str(value), quote=False).replace("\n", " ").replace("\r", " ")
    return re.sub(r"([\\`*_{}\[\]<>|#])", r"\\\1", value)


def evidence_matrix_csv(inv, evidence):
    """All findings × all distinct snapshots, matching the dashboard's grouping."""
    report = visible_report(inv.report, evidence)
    groups = {}
    for source in evidence:
        group = groups.setdefault(source.content_hash or source.id, {"source": source, "ids": set()})
        group["ids"].add(source.id)
    snapshots = list(groups.values())
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")

    def cell(value):
        text = "" if value is None else str(value)
        # Spreadsheet formula injection, including formulas following whitespace.
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text

    writer.writerow(["Finding ID", "Type", "Context", "Finding", "Classification", "Evidence strength"] + [cell(f"S{i + 1} | {(g['source'].signals or {}).get('title') or g['source'].source_url} | {g['source'].source_url}") for i, g in enumerate(snapshots)])
    for claim in report.get("claims", []):
        supporting, contradicting = set(claim.get("supporting_evidence_ids", [])), set(claim.get("contradicting_evidence_ids", []))
        states = []
        for group in snapshots:
            yes, no = bool(group["ids"] & supporting), bool(group["ids"] & contradicting)
            states.append("Both" if yes and no else "Supporting" if yes else "Contradicting" if no else "")
        writer.writerow([cell(claim.get(key, "")) for key in ("id", "type", "context", "description", "classification", "confidence")] + states)
    return "\ufeff" + output.getvalue()


def markdown_report(inv, evidence, chunks=(), questions=()):
    """Reader-oriented report using retained findings; no export-time inference."""
    report = visible_report(inv.report, evidence)
    analysis = research_summary(report, evidence, inv.processing_options, reference=inv.mode == "demo") or {}
    sources = {source.id: source for source in evidence}
    source_refs = {source.id: f"S{i + 1}" for i, source in enumerate(evidence)}
    claims = {claim["id"]: claim for claim in report.get("claims", [])}
    claim_refs = {key: f"F{i + 1}" for i, key in enumerate(claims)}
    def refs(ids):
        return ", ".join(source_refs[key] for key in dict.fromkeys(ids) if key in source_refs)
    def finding(key):
        return claim_refs.get(key, "")
    def table(headers, rows):
        return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |", *["| " + " | ".join(md(value) for value in row) + " |" for row in rows], ""]
    def register(note, rows, maximum=80):
        rows = list(rows)
        if len(rows) > maximum:
            lines.extend([f"{note}: {len(rows):,} records; {maximum:,} shown here. Full inventories accompany the JSON and SQLite exports.", ""])
        return rows[:maximum]
    run = report.get("run", {})
    collection = (inv.processing_options or {}).get("collection", {})
    nodes = {node["id"]: node for node in report.get("nodes", [])}
    lines = [f"# Architecture assessment: {md(inv.domain)}", "", f"Prepared {inv.updated_at.strftime('%d %B %Y')} · PriSMA · {inv.id}", "", "## Executive summary", "", md(report.get("summary") or "The assessment records the interfaces and structure established by the selected sources."), "", "**Scope.** " + disclaimer(inv), ""]
    product = analysis.get("product", {})
    if product.get("workflows"):
        lines += ["## Product workflows", ""]
        lines += table(["Workflow", "Page", "Basis", "Execution", "Description or fields", "Sources"], [(row["title"], row.get("page_url", ""), row["status"], row.get("execution", ""), row.get("description") or ", ".join(f.get("label") or f.get("name", "") for f in row.get("fields", [])), refs(row["evidence_ids"])) for row in product["workflows"][:40]])
    if product.get("pages"):
        lines += ["## Page inventory", ""]
        lines += table(["Page", "URL", "Basis", "Access observations", "Sources"], [(row["title"], row["url"], row["status"], "; ".join(dict.fromkeys(str(o.get("access_reason") or o.get("access") or o.get("status")).replace("_", " ") for o in row.get("access_observations", []))), refs(row["evidence_ids"])) for row in product["pages"][:80]])
    if product.get("features"):
        lines += ["## Published product features", ""]
        lines += table(["Feature", "Published description", "Basis", "Sources"], [(row["text"], row.get("description", ""), row["status"], refs(row["evidence_ids"])) for row in product["features"][:60]])
    if product.get("data_flows"):
        lines += ["## Client and service flows", ""]
        lines += table(["Page or initiator", "Request", "Basis", "Response", "Sources"], [(row.get("page_url") or (row.get("initiator") or {}).get("url", ""), row["method"] + " " + row["target"], row["basis"], str(row.get("status", "unobserved")), refs(row["evidence_ids"])) for row in product["data_flows"][:60]])
    highlights = [row for row in analysis.get("insights", []) if row["kind"] not in {"coverage", "stack"}][:8]
    if highlights:
        lines += ["## Research highlights", ""]
        for row in highlights:
            reference = refs(row.get("evidence_ids", []))
            lines += ["- **" + md(row["title"]) + ".** " + md(row["observation"]) + (f" [{reference}]" if reference else "")]
        lines += [""]
    if report.get("edges"):
        lines += ["## System relationships", ""]
        rows = []
        for edge in register("Connections", report["edges"], 60):
            claim = claims.get(edge.get("claim_id"), {})
            basis = edge.get("relationship_kind") or claim.get("attributes", {}).get("contract_basis") or claim.get("classification", "")
            rows.append((nodes.get(edge.get("source"), {}).get("label", ""), edge.get("label", ""), nodes.get(edge.get("target"), {}).get("label", ""), str(basis).replace("_", " "), finding(edge.get("claim_id"))))
        lines += table(["From", "Relationship", "To", "Basis", "Finding"], rows)
    if nodes:
        lines += ["## Components", ""]
        lines += table(["Component", "Role", "Context", "Finding"], [(n["label"], n.get("description") or n.get("kind", "").replace("_", " "), n.get("context", ""), finding(n.get("claim_id"))) for n in register("Components", nodes.values())])
    if report.get("technologies"):
        lines += ["## Technology profile", ""]
        rows = []
        for tech in register("Technologies", report["technologies"], 100):
            declarations = tech.get("declarations") or [{"group": tech.get("category", ""), "claim_id": tech.get("claim_id")}]
            groups = list(dict.fromkeys(str(d.get("group", "")).replace("_", " ") for d in declarations))
            versions = list(dict.fromkeys(str(d["version"]) for d in declarations if d.get("version")))
            rows.append((tech["name"], ", ".join(groups), ", ".join(versions), ", ".join(dict.fromkeys(finding(d.get("claim_id")) for d in declarations))))
        lines += table(["Technology", "Evidence role", "Declared version", "Findings"], rows)
    if report.get("api_endpoints"):
        lines += ["## Interfaces", ""]
        rows = []
        for route in register("API operations", report["api_endpoints"], 100):
            claim = claims.get(route.get("claim_id"), {})
            basis = route.get("contract_basis") or claim.get("attributes", {}).get("contract_basis") or claim.get("classification", "")
            rows.append((route["method"], route["path"], route.get("summary", ""), str(basis).replace("_", " "), finding(route.get("claim_id"))))
        lines += table(["Method", "Route", "Purpose", "Basis", "Finding"], rows)
    if report.get("security_schemes"):
        lines += ["### Authentication", ""]
        lines += table(["Scheme", "Type", "Location", "Finding"], [(r["security_scheme"], r.get("type", ""), r.get("location") or r.get("scheme", ""), finding(r.get("claim_id"))) for r in report["security_schemes"]])
    if report.get("entities"):
        lines += ["## Data definitions", ""]
        fields = {}
        for field in report.get("fields", []):
            fields.setdefault(field["entity_id"], []).append(field)
        rows = []
        for entity in register("Data definitions", report["entities"]):
            properties = fields.get(entity["id"], [])
            description = ", ".join(row["name"] + (": " + row["type"] if row.get("type") not in {None, "", "unknown"} else "") for row in properties[:15])
            if len(properties) > 15:
                description += f"; {len(properties) - 15} additional fields"
            rows.append((entity["name"], description, entity.get("context", ""), finding(entity.get("claim_id"))))
        lines += table(["Definition", "Fields", "Context", "Finding"], rows)
    if report.get("features"):
        lines += ["## Capabilities", ""]
        rows = []
        for row in register("Capabilities", report["features"], 60):
            terms = "; ".join(str(row.get(key, "")) for key in ("tier", "availability", "limitation") if str(row.get(key, "")).casefold() not in {"", "unknown", "unspecified", "not specified"})
            rows.append((row["feature"], terms, finding(row.get("claim_id"))))
        lines += table(["Capability", "Published terms", "Finding"], rows)
    if analysis.get("repository_groups"):
        lines += ["## Implementation structure", ""]
        lines += table(["Source group", "Role", "Modules", "Resolved imports"], [(r["path"], r["role"], r["modules"], r["resolved_imports"]) for r in analysis["repository_groups"][:40]])
    points = list(dict.fromkeys(report.get("unknowns", []) + analysis.get("open_questions", [])))
    if points:
        lines += ["## Open points", "", *["- " + md(point) for point in points[:12]], ""]
    lines += ["## Assessment record", ""]
    records = [("Engine", run.get("provider", "Not recorded")), ("Model", run.get("model") or "Not used"), ("Parser", run.get("parser_version", "Not recorded")), ("Distinct source snapshots", len({e.content_hash or e.id for e in evidence})), ("Extraction coverage", run.get("coverage", {}).get("status", "Not recorded"))]
    records += [("Model-reviewed passages", str(run.get("processed_passages", 0)) + " of " + str(run.get("passages", 0))), ("Failed model requests", run.get("failed_requests", 0))]
    if collection:
        records += [("Collection status", collection.get("status", "Not recorded")), ("Document Fetch requests", collection.get("url_attempts", 0)), ("Discovery Search requests", collection.get("search_attempts", 0))]
        browser = collection.get("browser", {})
        if browser:
            records += [("Browser coverage", browser.get("status", "")), ("Rendered pages", browser.get("pages", 0)), ("Browser reads", browser.get("requests", 0)), ("Retained client scripts", browser.get("scripts_retained", 0)), ("Retained original modules", browser.get("analysis_retained", {}).get("source_map_modules", 0))]
    lines += table(["Measure", "Recorded value"], records)
    if run.get("provider") == "rules":
        lines += ["No model review was performed.", ""]
    outcomes = [o for o in collection.get("outcomes", []) if o.get("status") not in {"collected", "duplicate"}]
    if outcomes:
        lines += ["### Acquisition gaps", ""]
        lines += table(["Location", "Outcome", "Reason"], [(o.get("url", ""), o.get("status", ""), o.get("reason", "")) for o in outcomes[:20]])
    lines += ["Evidence-strength scores are heuristic ratings, not probabilities. Supporting and contradicting records remain distinct. Exact source spans, raw inventories and acquisition outcomes accompany the JSON, SQLite and evidence-bundle exports.", "", "## Finding register", ""]
    lines += table(["Finding", "Type", "Context", "Description", "Classification", "Strength", "Supporting", "Contradicting"], [(claim_refs[key], r["type"], r.get("context", ""), r["description"], r["classification"], r["confidence"], refs(r.get("supporting_evidence_ids", [])), refs(r.get("contradicting_evidence_ids", []))) for key, r in claims.items()])
    lines += ["## Source register", ""]
    lines += table(["Reference", "Source", "Location", "Acquisition", "Captured"], [(source_refs[e.id], (e.signals or {}).get("title") or e.source_url, e.source_url, e.collection_method, e.collected_at.isoformat()) for e in evidence])
    recorded = []
    for question in questions:
        if question.status != "completed" or not question.answer:
            continue
        paragraphs = []
        for statement in question.answer.get("statements", []):
            citations = statement.get("citations", [])
            if not citations or any(c.get("evidence_id") not in sources or not isinstance(c.get("start"), int) or not isinstance(c.get("end"), int) or not 0 <= c["start"] < c["end"] <= len(sources[c["evidence_id"]].content) or sources[c["evidence_id"]].content[c["start"]:c["end"]] != c.get("quote") for c in citations):
                continue
            paragraphs.append(md(statement["text"]) + " [" + refs(c["evidence_id"] for c in citations) + "]")
        if paragraphs:
            recorded += ["### " + md(question.question), "", *[paragraph + "\n" for paragraph in paragraphs]]
    if recorded:
        lines += ["## Research discussion", "", *recorded]
    return "\n".join(lines).rstrip() + "\n"


def sqlite_report(inv: Investigation, evidence: list[Evidence], chunks=(), questions=()) -> bytes:
    r = visible_report(inv.report, evidence)
    # File-backed SQLite gives portable bytes; temporary directory is removed after response materialization.
    with tempfile.TemporaryDirectory(prefix="prisma-export-") as directory:
        path = directory + "/report.sqlite"
        with sqlite3.connect(path) as db:
            db.executescript(
                SCHEMA
                + """
CREATE TABLE original_sources(evidence_id TEXT PRIMARY KEY REFERENCES evidence(id), content TEXT NOT NULL, raw_sha256 TEXT);
CREATE TABLE source_passages(id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES evidence(id), start INTEGER NOT NULL, end INTEGER NOT NULL, content TEXT NOT NULL, embedding_model TEXT);
CREATE TABLE claim_citations(id INTEGER PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(id), passage_id TEXT NOT NULL REFERENCES source_passages(id), evidence_id TEXT NOT NULL REFERENCES evidence(id), role TEXT NOT NULL, quote TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL);
CREATE TABLE feature_mappings(id TEXT PRIMARY KEY, feature TEXT NOT NULL, tier TEXT NOT NULL, availability TEXT NOT NULL, limitation TEXT NOT NULL, claim_id TEXT NOT NULL REFERENCES claims(id));
CREATE TABLE source_metadata(evidence_id TEXT PRIMARY KEY REFERENCES evidence(id), title TEXT NOT NULL, requested_url TEXT, final_url TEXT, raw_sha256 TEXT, offset_basis TEXT NOT NULL);
CREATE TABLE collection_outcomes(id INTEGER PRIMARY KEY, url TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, final_url TEXT);
CREATE TABLE report_questions(id TEXT PRIMARY KEY, question TEXT NOT NULL, status TEXT NOT NULL, answer_json TEXT, error TEXT, created_at TEXT NOT NULL, processing_options_json TEXT, chat_id TEXT);
CREATE TABLE finding_attributes(claim_id TEXT PRIMARY KEY REFERENCES claims(id), attributes_json TEXT NOT NULL);
"""
            )
            db.execute("CREATE TABLE research_summary(version INTEGER NOT NULL, summary_json TEXT NOT NULL)")
            db.execute("INSERT INTO research_summary VALUES (?,?)", (2, json.dumps(research_summary(r, evidence, inv.processing_options, reference=inv.mode == "demo"), ensure_ascii=False)))
            db.executemany(
                "INSERT INTO metadata VALUES (?,?)",
                [
                    ("schema_version", "3"),
                    ("mode", inv.mode),
                    ("confidence_kind", "heuristic"),
                    ("disclaimer", disclaimer(inv)),
                    ("processing_record", json.dumps(r.get("run", {}))),
                    ("processing_options", json.dumps(inv.processing_options or {})),
                    ("repository_inventory", json.dumps(r.get("repository", {}))),
                    ("technology_declarations", json.dumps(r.get("technologies", []))),
                    ("contract_details", json.dumps({key: r.get(key, []) for key in ("api_endpoints", "entities", "fields", "relationships", "security_schemes", "surface_records")})),
                    ("architecture_contexts", json.dumps(r.get("contexts", []))),
                    ("full_report", json.dumps(r)),
                    ("collection_record", json.dumps((inv.processing_options or {}).get("collection", {}))),
                    ("offset_basis", "normalized Unicode characters, half-open [start,end)"),
                ],
            )
            db.execute(
                "INSERT INTO investigations VALUES (?,?,?,?,?,?,?)",
                (
                    inv.id,
                    inv.domain,
                    inv.mode,
                    r["fixture"],
                    inv.status,
                    inv.created_at.isoformat(),
                    r["summary"],
                ),
            )
            for e in evidence:
                db.execute(
                    "INSERT INTO sources VALUES (?,?,?,?)", (e.id, inv.id, e.source_url, e.source_type)
                )
                db.execute(
                    "INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        e.id,
                        inv.id,
                        e.id,
                        e.category,
                        e.content,
                        e.content_hash,
                        e.collected_at.isoformat(),
                        e.collection_method,
                        e.provenance,
                        json.dumps(e.signals),
                    ),
                )
            for outcome in (inv.processing_options or {}).get("collection", {}).get("outcomes", []):
                db.execute(
                    "INSERT INTO collection_outcomes(url,status,reason,final_url) VALUES (?,?,?,?)",
                    (outcome["url"], outcome["status"], outcome.get("reason"), outcome.get("final_url")),
                )
            for item in evidence:
                signals = item.signals or {}
                db.execute(
                    "INSERT INTO source_metadata VALUES (?,?,?,?,?,?)",
                    (
                        item.id,
                        signals.get("title", item.source_url),
                        signals.get("requested_url"),
                        signals.get("final_url"),
                        signals.get("raw_sha256"),
                        "normalized Unicode characters",
                    ),
                )
                if item.original_content is not None:
                    db.execute(
                        "INSERT INTO original_sources VALUES (?,?,?)",
                        (item.id, original_text(item), item.signals.get("raw_sha256")),
                    )
            for chunk in chunks:
                db.execute(
                    "INSERT INTO source_passages VALUES (?,?,?,?,?,?)",
                    (
                        chunk.id,
                        chunk.evidence_id,
                        chunk.start,
                        chunk.end,
                        chunk.content,
                        chunk.embedding_model,
                    ),
                )
            for c in r["claims"]:
                db.execute(
                    "INSERT INTO claims VALUES (?,?,?,?,?,?,?,?)",
                    (
                        c["id"],
                        inv.id,
                        c["type"],
                        c["description"],
                        c["classification"],
                        c["confidence"],
                        c["confidence_explanation"],
                        inv.updated_at.isoformat(),
                    ),
                )
                if c.get("attributes"):
                    db.execute("INSERT INTO finding_attributes VALUES (?,?)", (c["id"], json.dumps(c["attributes"], ensure_ascii=False)))
                for role in ("supporting", "contradicting"):
                    db.executemany(
                        "INSERT INTO claim_evidence_links VALUES (?,?,?)",
                        [(c["id"], eid, role) for eid in c[role + "_evidence_ids"]],
                    )
                for citation in c.get("citations", []):
                    db.execute(
                        "INSERT INTO claim_citations(claim_id,passage_id,evidence_id,role,quote,start,end) VALUES (?,?,?,?,?,?,?)",
                        (
                            c["id"],
                            citation["chunk_id"],
                            citation["evidence_id"],
                            citation["role"],
                            citation["quote"],
                            citation["start"],
                            citation["end"],
                        ),
                    )
            for feature in r.get("features", []):
                db.execute(
                    "INSERT INTO feature_mappings VALUES (?,?,?,?,?,?)",
                    (
                        feature["id"],
                        feature["feature"],
                        feature["tier"],
                        feature["availability"],
                        feature["limitation"],
                        feature["claim_id"],
                    ),
                )
            for question in questions:
                db.execute(
                    "INSERT INTO report_questions VALUES (?,?,?,?,?,?,?,?)",
                    (
                        question.id,
                        question.question,
                        question.status,
                        json.dumps(question.answer) if question.answer is not None else None,
                        question.error,
                        question.created_at.isoformat(),
                        json.dumps(question.processing_options) if question.processing_options is not None else None,
                        question.chat_id,
                    ),
                )
            for t in r["technologies"]:
                db.execute(
                    "INSERT INTO technologies VALUES (?,?,?,?)",
                    (t["id"], t["name"], t["category"], t["claim_id"]),
                )
            for ep in r["api_endpoints"]:
                db.execute(
                    "INSERT INTO api_endpoints VALUES (?,?,?,?,?)",
                    (ep["id"], ep["method"], ep["path"], ep["classification"], ep["claim_id"]),
                )
            for e in r["entities"]:
                db.execute(
                    "INSERT INTO inferred_entities VALUES (?,?,?,?)",
                    (e["id"], e["name"], e["confidence"], e["claim_id"]),
                )
            for f in r["fields"]:
                db.execute(
                    "INSERT INTO inferred_fields VALUES (?,?,?,?,?)",
                    (f["id"], f["entity_id"], f["name"], f["type"], f["claim_id"]),
                )
            for rel in r["relationships"]:
                db.execute(
                    "INSERT INTO inferred_relationships VALUES (?,?,?,?,?,?)",
                    (
                        rel["id"],
                        rel["source"],
                        rel["target"],
                        rel["field"],
                        rel["cardinality"],
                        rel["claim_id"],
                    ),
                )
            for n in r["nodes"]:
                db.execute(
                    "INSERT INTO architecture_nodes VALUES (?,?,?,?,?,?)",
                    (n["id"], n["label"], n["kind"], n["confidence"], n["classification"], n["claim_id"]),
                )
            for edge in r["edges"]:
                db.execute(
                    "INSERT INTO architecture_edges VALUES (?,?,?,?,?,?,?)",
                    (
                        edge["id"],
                        edge["source"],
                        edge["target"],
                        edge["label"],
                        edge["confidence"],
                        edge["classification"],
                        edge["claim_id"],
                    ),
                )
            db.commit()
            if (
                db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                or db.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise ValueError("Export failed integrity validation")
        with open(path, "rb") as file:
            return file.read()
