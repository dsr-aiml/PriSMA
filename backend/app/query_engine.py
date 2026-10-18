"""Bounded research retrieval and answers derived from retained report records."""

import math
import re
from collections import Counter

STOP = set("a an and are as at be can could describe do does explain for from how i in is it me of on or please project show tell than that the their there these they this to using was what which who why will with would has have had can should need needs where when".split())
CONCEPTS = {
    "architecture": {"architecture", "architectural", "system", "component", "components", "structure", "topology", "flow", "connect", "connected", "connects", "connections"},
    "dependencies": {"dependency", "dependencies", "imports", "import", "depends", "coupling", "modules", "module"},
    "api": {"api", "endpoint", "endpoints", "route", "routes", "operation", "operations", "request", "response", "contract"},
    "data": {"data", "schema", "schemas", "entity", "entities", "field", "fields", "database", "tables", "model", "models"},
    "security": {"security", "auth", "authentication", "authorization", "login", "token", "oauth", "permissions", "authenticate"},
    "technologies": {"stack", "technology", "technologies", "language", "languages", "framework", "frameworks", "libraries", "packages"},
    "capabilities": {"feature", "features", "capability", "capabilities", "pricing", "price", "tier", "plan", "enterprise", "limits"},
    "conflicts": {"conflict", "conflicts", "contradiction", "contradictions", "uncertain", "unknown", "missing", "gaps"},
}


def words(text):
    # Retain both identifiers and their path/camel-case pieces.
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    return {w for w in re.findall(r"[\w]+", text.casefold()) if len(w) > 1 and w not in STOP}


def intent_for(question):
    tokens = words(question)
    matches = [(len(tokens & aliases), key) for key, aliases in CONCEPTS.items()]
    return max(matches)[1] if max(matches)[0] else "general"


def expanded_terms(question):
    tokens = words(question)
    for aliases in CONCEPTS.values():
        if tokens & aliases:
            tokens |= aliases
    return tokens


def _rank_text(text, question):
    tokens = words(text)
    direct = words(question) & tokens
    expanded = expanded_terms(question) & tokens
    return len(direct) * 3 + len(expanded - direct) * .35


def _references(claim_ids, claims, sources):
    citations, evidence_ids = [], []
    for claim_id in dict.fromkeys(claim_ids):
        claim = claims.get(claim_id, {})
        evidence_ids.extend(claim.get("supporting_evidence_ids", []))
        evidence_ids.extend(claim.get("contradicting_evidence_ids", []))
        for citation in claim.get("citations", []):
            source = sources.get(citation.get("evidence_id"))
            start, end = citation.get("start"), citation.get("end")
            if source is not None and isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(source.content) and source.content[start:end] == citation.get("quote"):
                citations.append({"chunk_id": citation.get("chunk_id", ""), **citation})
    unique = {(c["evidence_id"], c["start"], c["end"], c.get("role", "supporting")): c for c in citations}
    return list(unique.values())[:6], [key for key in dict.fromkeys(evidence_ids) if key in sources][:12]


def structured_answer(report, evidence, question, limit=12):
    """Select actual records; never manufacture infrastructure from source keywords."""
    report = report or {}
    claims = {c["id"]: c for c in report.get("claims", [])}
    sources = {e.id: e for e in evidence}
    intent = intent_for(question)
    records = []
    concept_words = set().union(*CONCEPTS.values())
    filler = set("main key used use uses declared declaration defined define definition roles role requirements requirement written built implemented implementation retained documented available highest most central largest serve sources source documentation records record details exactly together fit its about only all".split())
    focus = words(question) - concept_words - filler

    def add(kind, title, text, ids, context="", keywords=""):
        ids = [key for key in dict.fromkeys(ids) if key in claims]
        citations, source_ids = _references(ids, claims, sources)
        if not source_ids:
            return
        relevance = _rank_text(" ".join([title, text, context, keywords]), question)
        if intent == kind or intent == "architecture" and kind in {"architecture", "dependencies"}:
            relevance += 2
        if focus and not focus & words(" ".join([title, text, context, keywords])):
            relevance = 0
        records.append({"kind": kind, "title": title, "text": text, "context": context, "claim_ids": ids, "evidence_ids": source_ids, "citations": citations, "score": relevance})

    nodes = {n["id"]: n for n in report.get("nodes", [])}
    for node in nodes.values():
        kind = "dependencies" if node.get("kind") == "module_group" else "architecture"
        suffix = " Source-code grouping; deployment is not established." if kind == "dependencies" else ""
        add(kind, node["label"], node.get("description") or (node["label"] + " is retained as a " + node.get("kind", "component") + "."), [node.get("claim_id")] + node.get("claim_ids", []), node.get("context", ""), " ".join(node.get("module_paths", [])))
        if suffix and records and records[-1]["title"] == node["label"]:
            records[-1]["text"] += suffix
    for edge in report.get("edges", []):
        a, b = nodes.get(edge["source"]), nodes.get(edge["target"])
        if not a or not b:
            continue
        implementation = a.get("kind") == "module_group" or b.get("kind") == "module_group"
        label = edge.get("label", "Declared relationship")
        add("dependencies" if implementation else "architecture", a["label"] + " → " + b["label"], a["label"] + " → " + b["label"] + ": " + label + ".", [edge.get("claim_id")], edge.get("context", ""), "relationship connection flow dependency")
    modules = (report.get("repository") or {}).get("modules", [])
    incoming = Counter(ref.get("resolved_path") for module in modules for ref in module.get("imports", []) if ref.get("resolved_path"))
    if intent == "dependencies":
        for module in modules:
            source = sources.get(module.get("evidence_id"))
            if source is None:
                continue
            imports = module.get("imports", [])
            resolved = [ref for ref in imports if ref.get("resolved_path")]
            text = module["path"] + ": " + str(len(resolved)) + " resolved imports, " + str(incoming[module["path"]]) + " incoming module references"
            if resolved:
                text += ". Resolved targets: " + ", ".join(dict.fromkeys(ref["resolved_path"] for ref in resolved[:6]))
            text += ". These are static source references."
            quotes = []
            for ref in imports[:8]:
                offset = ref.get("offset")
                if isinstance(offset, int) and 0 <= offset < len(source.content):
                    start = source.content.rfind("\n", 0, offset) + 1
                    end = source.content.find("\n", offset)
                    end = len(source.content) if end < 0 else end
                    end = min(end, start + 500)
                    if end > start:
                        quotes.append({"chunk_id": "", "evidence_id": source.id, "quote": source.content[start:end], "start": start, "end": end, "role": "supporting"})
            records.append({"kind": "dependencies", "title": module["path"], "text": text, "context": "repository", "claim_ids": [], "evidence_ids": [source.id], "citations": quotes[:3], "score": (_rank_text(module["path"] + " " + text, question) + 2) if not focus or focus & words(module["path"] + " " + text) else 0, "connections": len(resolved) + incoming[module["path"]]})
    for technology in report.get("technologies", []):
        declarations = technology.get("declarations", [])
        detail = "; ".join(dict.fromkeys(" ".join([d.get("group", "declaration"), d.get("version", "")]).strip() for d in declarations))
        add("technologies", technology["name"], technology["name"] + " is declared" + (" in " + detail if detail else " as " + technology.get("category", "a technology")) + ".", [technology.get("claim_id")] + technology.get("claim_ids", []), keywords="technology stack framework library language")
    for route in report.get("api_endpoints", []):
        name = route.get("method", "") + " " + route.get("path", "")
        summary = route.get("summary") or "Retained operation"
        detail = summary + "."
        if route.get("security"):
            detail += " Security requirements: " + ", ".join(dict.fromkeys(key for scheme in route["security"] for key in scheme)) + "."
        elif route.get("security") == []:
            detail += " This operation explicitly declares no security requirement."
        add("api", name, name + " — " + detail, [route.get("claim_id")], route.get("context", ""), route.get("operation_id", ""))
    for scheme in report.get("security_schemes", []):
        name = scheme.get("security_scheme", "Authentication definition")
        add("security", name, name + ": " + ", ".join(str(scheme[key]) for key in ("type", "scheme", "location", "parameter") if scheme.get(key)) + ".", [scheme.get("claim_id")], keywords="auth security login token")
    for entity in report.get("entities", []):
        fields = [f for f in report.get("fields", []) if f.get("entity_id") == entity["id"]]
        names = ", ".join(f["name"] + (": " + f["type"] if f.get("type") not in (None, "unknown") else " (type unspecified)") for f in fields[:10])
        text = entity["name"] + (" — " + names if names else ": no field definitions retained") + "."
        if len(fields) > 10:
            text += " " + str(len(fields) - 10) + " additional retained fields."
        add("data", entity["name"], text, [entity.get("claim_id")] + [f.get("claim_id") for f in fields], entity.get("context", ""), "schema data fields entity")
    for feature in report.get("features", []):
        text = feature["feature"] + "."
        if feature.get("commercial_scope") == "declared" or not feature.get("commercial_scope") and feature.get("tier", "").casefold() not in {"", "unspecified", "unknown"}:
            text = feature["feature"] + " — " + feature["tier"] + ": " + feature.get("availability", "unknown") + "."
        if feature.get("limitation"):
            text += " " + feature["limitation"]
        add("capabilities", feature["feature"], text, [feature.get("claim_id")], keywords="feature capability pricing availability")
    for claim in claims.values():
        if claim.get("contradicting_evidence_ids"):
            add("conflicts", "Conflicting source records", claim["description"], [claim["id"]], claim.get("context", ""), "conflict contradiction")
        elif intent == "general" or not records or intent == "security" and _rank_text(claim["description"], question) > 0:
            add("general", claim.get("type", "Finding").replace("_", " "), claim["description"], [claim["id"]], claim.get("context", ""))
    # Engine/vendor questions cannot be answered by logical schema names.
    if re.search(r"\b(?:database|storage)\s+(?:engine|vendor)\b", question, re.I):
        records = [r for r in records if r["kind"] in {"technologies", "architecture"} and _rank_text(r["text"], question) > 0 and re.search(r"database|storage|sql|mongo|redis|dynamo|cassandra|sqlite|postgres", r["text"], re.I)]
    selected, seen = [], set()
    central = intent == "dependencies" and bool(words(question) & {"most", "highest", "central", "largest"})
    for record in sorted(records, key=lambda r: (-r.get("connections", -1) if central else -r["score"], -r["score"], r["context"], r["title"])):
        identity = (record["context"], record["text"])
        if record["score"] <= 0 or identity in seen:
            continue
        seen.add(identity)
        selected.append(record)
        if len(selected) > limit:
            selected.pop()
    gaps = []
    for claim in selected:
        if any(claim_id in claims and claims[claim_id].get("contradicting_evidence_ids") for claim_id in claim["claim_ids"]):
            gaps.append("The cited sources contain conflicting records; their dates and contexts need review.")
            break
    if (report.get("run") or {}).get("coverage", {}).get("status") == "partial":
        gaps.append("Analysis coverage is partial; these records cover the work retained before processing ended.")
    if not selected:
        gaps.append("No retained structured record establishes an answer to this question.")
    gaps.extend(gap for gap in report.get("unknowns", []) if _rank_text(gap, question) > .5)
    return {"intent": intent, "findings": selected, "gaps": list(dict.fromkeys(gaps))[:5], "matched_records": len(seen)}


def rank_passages(chunks, question, semantic_scores=None, evidence=None, limit=8):
    """BM25-style lexical ranking plus semantic relevance and source diversity."""
    if not chunks:
        return []
    query = expanded_terms(question)
    roles = {e.id: (e.signals or {}).get("resource_role") for e in evidence or []}
    metadata = {e.id: e.source_url + " " + str((e.signals or {}).get("title", "")) for e in evidence or []}
    documents = [words(c.content) for c in chunks]
    frequency = Counter(word for document in documents for word in document if word in query)
    average = sum(len(d) for d in documents) / len(documents) or 1
    ranked = []
    for chunk, tokens in zip(chunks, documents, strict=True):
        relevance = sum(math.log(1 + (len(chunks) - frequency[t] + .5) / (frequency[t] + .5)) / (.6 + .4 * len(tokens) / average) for t in tokens & query)
        relevance += .2 * _rank_text(metadata.get(chunk.evidence_id, ""), question)
        if semantic_scores is not None:
            relevance += max(0, semantic_scores.get(chunk.id, 0)) * 3
        if roles.get(chunk.evidence_id) in {"tracking", "dependency", "delivery"}:
            relevance *= .25
        if relevance > 0:
            ranked.append((relevance, chunk))
    ranked.sort(key=lambda row: (-row[0], row[1].evidence_id, row[1].start))
    chosen, counts, snapshots = [], Counter(), set()
    for score, chunk in ranked:
        snapshot = chunk.content.strip()
        if snapshot in snapshots or counts[chunk.evidence_id] >= 3:
            continue
        chosen.append((score, chunk))
        counts[chunk.evidence_id] += 1
        snapshots.add(snapshot)
        if len(chosen) == limit:
            break
    return chosen


def question_units(chunks, question, maximum=32, character_budget=6200):
    from .evidence_units import source_units

    units = source_units(chunks, maximum=2400 if maximum > 32 else 600, width=480 if maximum > 32 else 280)
    ranked = sorted(units.values(), key=lambda u: (not u.id.startswith("product:"), -_rank_text(u.content, question), u.evidence_id, u.start))
    chosen, size, seen = {}, 0, set()
    counts = Counter()
    distinct = len({unit.evidence_id for unit in ranked}) or 1
    per_source = max(8, math.ceil(maximum / distinct)) if maximum > 32 else maximum
    for unit in ranked:
        if unit.content in seen or size + len(unit.content) > character_budget or counts[unit.evidence_id] >= per_source:
            continue
        chosen["u" + str(len(chosen) + 1)] = unit
        counts[unit.evidence_id] += 1
        seen.add(unit.content)
        size += len(unit.content)
        if len(chosen) >= maximum:
            break
    return chosen
