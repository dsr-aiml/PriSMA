"""Read-only research summaries of validated report records.

No collection, model calls or mutation of historical findings occurs here.
"""
import hashlib
import re
from collections import Counter, defaultdict


def research_summary(report, evidence, options=None, *, reference=False):
    if not report:
        return None
    from .product_inventory import product_inventory
    product = product_inventory(report, evidence)
    sources = {e.id: e for e in evidence}
    claims = {c["id"]: c for c in report.get("claims", [])}
    run = report.get("run") or {}
    coverage = run.get("coverage") or {}
    modules = (report.get("repository") or {}).get("modules", [])
    nodes = report.get("nodes", [])
    edges = report.get("edges", [])
    routes = report.get("api_endpoints", [])
    insights = []
    insight_keys = set()

    def source_key(eid):
        source = sources[eid]
        return source.content_hash or hashlib.sha256(source.content.encode()).hexdigest()

    def refs(ids, extra=()):
        return sorted({eid for cid in ids if cid in claims for eid in claims[cid].get("supporting_evidence_ids", []) + claims[cid].get("contradicting_evidence_ids", []) if eid in sources} | {eid for eid in extra if eid in sources})

    def add(kind, title, observation, ids=(), extra=(), *, context="", section="insights", priority=50, citations=(), data=None):
        ids = sorted({cid for cid in ids if cid in claims})
        eids = refs(ids, extra)
        basis = sorted({claims[cid].get("classification", "inferred") for cid in ids})
        key = hashlib.sha256((kind + "\0" + context + "\0" + title + "\0" + observation).encode()).hexdigest()[:20]
        if key in insight_keys:
            return
        insight_keys.add(key)
        insights.append({"id": key, "kind": kind, "title": title, "observation": observation,
                         "context": context, "section": section, "priority": priority,
                         "claim_ids": ids[:24], "evidence_ids": eids[:32], "basis": basis,
                         "distinct_snapshots": len({source_key(eid) for eid in eids}),
                         "citations": list(citations)[:8], "data": data or {}})

    for row in product["purpose"][:2]:
        add("product", "Product purpose", row["text"], extra=row["evidence_ids"], section="product", priority=98, citations=row["citations"])
    for row in product["workflows"][:12]:
        labels = ", ".join(f.get("label") or f.get("name", "") for f in row.get("fields", [])[:6])
        detail = row.get("description", "") if row["kind"] == "documented_workflow" else ("Public form presents " + labels + ". No form submission was performed.") if labels else "Public " + str(row["kind"]) + " control; " + ("disclosure inspected." if row["status"] == "inspected" else "referenced without interaction.")
        add("workflow", row["title"], detail, extra=row["evidence_ids"], context=row.get("page_url", ""), section="product", priority=90, citations=row["citations"], data=row)
    for row in product["features"][:8]:
        add("product", row["text"][:160], row.get("description") or row["text"], extra=row["evidence_ids"], context=row.get("page_url", ""), section="product", priority=86, citations=row["citations"], data=row)
    for row in product["data_flows"][:12]:
        detail = row["method"] + " " + row["target"] + ". " + ("Observed anonymous response" + (" (HTTP " + str(row["status"]) + ")" if row.get("status") else "") if row["basis"] == "observed_response" else "Static client reference" + (" correlated with a captured response" if row.get("correlated_response") else "; execution remains unestablished")) + "."
        add("flow", "Client and service flow", detail, extra=row["evidence_ids"], context=row.get("page_url") or "", section="api", priority=88, citations=row["citations"], data=row)

    conflicts = [c for c in claims.values() if any(eid in sources for eid in c.get("supporting_evidence_ids", [])) and any(eid in sources for eid in c.get("contradicting_evidence_ids", []))]
    for claim in conflicts[:8]:
        add("conflict", "Conflicting evidence", claim["description"], [claim["id"]], context=claim.get("context", ""), priority=100)

    conflict_ids = {c["id"] for c in conflicts}
    # Consolidate repeated claims within a context; a mirrored snapshot adds no breadth.
    grouped = defaultdict(list)
    for claim in claims.values():
        if not refs([claim["id"]]):
            continue
        key = (claim.get("type"), claim.get("context", ""), re.sub(r"\s+", " ", claim.get("description", "").strip()).casefold())
        grouped[key].append(claim)
    for rows in grouped.values():
        ids = [c["id"] for c in rows]
        breadth = len({source_key(eid) for eid in refs(ids)})
        if breadth >= 2 and not any(c["id"] in conflict_ids for c in rows):
            add("corroboration", "Supported across source snapshots", rows[0]["description"], ids,
                context=rows[0].get("context", ""), priority=75, data={"snapshots": breadth})
    important = [rows[0] for rows in grouped.values() if rows[0].get("type") in {"component", "assessment", "feature", "deployment", "connection", "relationship"}]
    important.sort(key=lambda c: (c["id"] in conflict_ids, c.get("classification") == "observed", c.get("type") == "component", len(refs([c["id"]]))), reverse=True)
    for claim in important[:8]:
        add("finding", "Retained finding", claim["description"], [claim["id"]], context=claim.get("context", ""), section="architecture" if claim.get("type") in {"component", "connection", "relationship"} else "features", priority=60)

    api_groups = defaultdict(list)
    for route in routes:
        path = route.get("path", "")
        resource = next((part for part in path.split("/") if part and part.lower() not in {"api", "rest"} and not re.fullmatch(r"v\d+", part, re.I) and not part.startswith("{") and not part.startswith(":")), "/")
        api_groups[(route.get("context", ""), resource)].append(route)
    api_surface = []
    for (context, resource), operations in sorted(api_groups.items()):
        api_surface.append({"context": context, "resource": resource, "methods": dict(sorted(Counter(row["method"].upper() for row in operations).items())), "operations": len(operations), "operation_ids": [row["id"] for row in operations]})
        if len(insights) < 40:
            methods = ", ".join(sorted({row["method"].upper() for row in operations}))
            add("api", "/" + resource.strip("/") + " surface", f"{len(operations)} retained operations across {methods}.", [row.get("claim_id") for row in operations], context=context, section="api", priority=55, data={"resource": resource, "operations": len(operations)})
    protected = [row for row in routes if row.get("security")]
    if protected:
        add("authentication", "Authentication requirements are declared", f"{len(protected)} operations carry explicit security requirements in the retained operation records.", [row.get("claim_id") for row in protected], section="api", priority=80, data={"operations": len(protected)})

    # Count only resolved imports between retained modules. No runtime claim is made.
    module_by_path = {m["path"]: m for m in modules}
    inbound = defaultdict(set)
    for module in modules:
        for reference in module.get("imports", []):
            target = reference.get("resolved_path")
            if target in module_by_path and target != module["path"]:
                inbound[target].add(module["path"])
    for target, callers in sorted(inbound.items(), key=lambda row: (-len(row[1]), row[0]))[:6]:
        if len(callers) < 2:
            continue
        eids = [module_by_path[path].get("evidence_id") for path in sorted(callers)]
        citations = []
        for path in sorted(callers)[:4]:
            module = module_by_path[path]
            source = sources.get(module.get("evidence_id"))
            reference = next(r for r in module["imports"] if r.get("resolved_path") == target)
            offset = reference.get("offset")
            if source and isinstance(offset, int) and 0 <= offset < len(source.content):
                start = source.content.rfind("\n", 0, offset) + 1
                end = source.content.find("\n", offset)
                end = min(len(source.content) if end < 0 else end, start + 800)
                if start <= offset < end and reference.get("name", "") in source.content[start:end]:
                    citations.append({"evidence_id": source.id, "start": start, "end": end, "quote": source.content[start:end], "role": "supporting"})
        add("dependency", "Shared module: " + target, f"{len(callers)} retained modules import this module. This is a static dependency relationship.", extra=eids, section="repository", priority=70, citations=citations, data={"path": target, "callers": sorted(callers)})
    repository_groups = []
    directory_groups = defaultdict(list)
    for module in modules:
        directory_groups[(module.get("role", "application"), module["path"].rsplit("/", 1)[0] if "/" in module["path"] else "Root")].append(module)
    for (role, path), members in sorted(directory_groups.items(), key=lambda row: (-len(row[1]), row[0])):
        repository_groups.append({"path": path, "role": role, "modules": len(members), "declarations": sum(len(m.get("symbols", [])) for m in members), "resolved_imports": sum(bool(i.get("resolved_path")) for m in members for i in m.get("imports", []))})

    technology_roles = defaultdict(list)
    for tech in report.get("technologies", []):
        declarations = tech.get("declarations") or [{"group": tech.get("category", "other"), "claim_id": tech.get("claim_id")}]
        for declaration in declarations:
            role = declaration.get("group") or tech.get("category", "other")
            technology_roles[role].append({"name": tech["name"], "version": declaration.get("version", ""), "claim_id": declaration.get("claim_id") or tech.get("claim_id")})
    technology_roles = [{"role": role, "items": list({(i["name"], i["version"], i["claim_id"]): i for i in items}.values())} for role, items in sorted(technology_roles.items())]
    for group in technology_roles[:6]:
        add("stack", group["role"].replace("_", " "), ", ".join(dict.fromkeys(item["name"] for item in group["items"][:12])), [item["claim_id"] for item in group["items"]], section="technologies", priority=45)

    for claim in claims.values():
        attributes = claim.get("attributes", {})
        initiator = attributes.get("initiator")
        if attributes.get("contract_basis") != "observed_response" or not isinstance(initiator, dict) or not initiator.get("url"):
            continue
        origin = str(attributes.get("page_url") or "Page load")
        script = str(initiator["url"])
        add("api", "Client request trace", origin + " → " + script + ". " + claim["description"], [claim["id"]], context=claim.get("context", ""), section="api", priority=82, data={"page": origin, "initiator": script, "status": attributes.get("status"), "response_shape": attributes.get("response_shape")})

    connected = {eid for edge in edges for eid in (edge["source"], edge["target"])}
    standalone = [node for node in nodes if node["id"] not in connected]
    if standalone and len(nodes) > 1:
        add("coverage", "Relationships remain unestablished", f"{len(standalone)} of {len(nodes)} mapped components have no retained connection. Inspect their sources before extending the map.", [node["claim_id"] for node in standalone], section="architecture", priority=65)
    fields = report.get("fields", [])
    unspecified = [field for field in fields if field.get("type") in (None, "", "unknown")]
    if unspecified:
        add("data", "Some field types are unspecified", f"{len(unspecified)} of {len(fields)} retained fields have no established type.", [field.get("claim_id") for field in unspecified], section="data", priority=65)

    source_coverage = []
    supported = defaultdict(set)
    contradicted = defaultdict(set)
    for claim in claims.values():
        for eid in claim.get("supporting_evidence_ids", []):
            supported[eid].add(claim["id"])
        for eid in claim.get("contradicting_evidence_ids", []):
            contradicted[eid].add(claim["id"])
    for source in evidence:
        info = source.signals or {}
        source_coverage.append({"id": source.id, "title": info.get("title") or source.source_url, "kind": info.get("kind_label") or source.source_type, "path": source.source_url, "characters": len(source.content), "findings": len(supported[source.id]), "conflicts": len(contradicted[source.id]), "snapshot": source_key(source.id)})
    repository_input = bool(modules) or any(e.source_type == "code" or (e.signals or {}).get("repository_url") or e.collection_method == "public_repository" for e in evidence)
    contract_input = any(e.source_type == "openapi" for e in evidence)
    network_input = any(edge.get("relationship_kind") == "captured_request" for edge in edges)
    web_input = any(e.source_type == "html" or e.collection_method in {"tinyfish_fetch", "public_file", "source_map"} for e in evidence)
    kind = "reference" if reference else "mixed" if repository_input and contract_input else "repository" if repository_input else "api_contract" if contract_input else "network_capture" if network_input else "public_web" if web_input else "documents"
    counts = {"sources": len(evidence), "distinct_snapshots": len({source_key(eid) for eid in sources}), "claims": len(claims), "components": len(nodes), "connections": len(edges), "modules": len(modules), "api_operations": len(routes), "api_resources": len(api_groups), "entities": len(report.get("entities", [])), "fields": len(fields), "technologies": len(report.get("technologies", [])), "capabilities": len(report.get("features", [])), "conflicts": len(conflicts)}
    coverage_rows = [{"key": key, "label": label, "value": coverage.get(key)} for key, label in (("discovered_files", "Discovered"), ("retained_files", "Retained"), ("selected_files", "Selected"), ("excluded_files", "Excluded or deferred")) if isinstance(coverage.get(key), int)]
    code = run.get("structural_coverage") or {}
    inventory = [{"kind": name, "sources": count} for name, count in sorted(Counter((e.signals or {}).get("kind_label") or e.source_type for e in evidence).items())]
    insights.sort(key=lambda row: (-row["priority"], row["context"], row["title"], row["id"]))
    return {"version": 2, "product": product, "input_kind": kind, "counts": counts, "insights": insights[:60], "insights_total": len(insights),
            "basis": dict(Counter(c.get("classification", "unknown") for c in claims.values())),
            "source_kinds": inventory, "sources": source_coverage, "api_surface": api_surface,
            "repository_groups": repository_groups, "technology_roles": technology_roles,
            "coverage": {"status": coverage.get("status", "not_recorded"), "intake": coverage_rows, "syntax": code,
                         "model_reviewed_files": coverage.get("model_reviewed_files"), "reviewed_passages": run.get("processed_passages"), "eligible_passages": coverage.get("eligible_passages"), "parsed_documents": run.get("parsed_documents")},
            "open_questions": list(dict.fromkeys(report.get("unknowns", []) + product["open_questions"]))[:20]}
