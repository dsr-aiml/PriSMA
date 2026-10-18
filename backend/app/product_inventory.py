"""Product-oriented synthesis from retained evidence, with exact provenance.

No live requests or inference; every record retains whether it was inspected,
declared in client code, or merely referenced. No private workflow is invented.
"""

import json
import re
from collections import Counter
from urllib.parse import urljoin, urlsplit

from .public_surface import surface_page
from .web_observation import CONTRACT, safe_url
from .target_scope import host_family, source_scope

STATUS = {"referenced": 0, "declared": 1, "collection_failed": 2, "requires_login": 3, "requires_subscription": 3, "publicly_documented": 4, "partial": 5, "inspected": 6}


def product_inventory(report, evidence):
    pages, workflows, features, flows = {}, {}, {}, {}
    purpose = []
    sources = {e.id: e for e in evidence}
    target = report.get("run", {}).get("target_url") or (report.get("run", {}).get("collection") or {}).get("seed_url")
    if not target:
        target = next((e.source_url for e in evidence if (e.signals or {}).get("target_scope", {}).get("reason") == "requested_page"), None)

    def citation(source, needle):
        if not isinstance(needle, str) or not needle:
            return []
        start = source.content.find(needle)
        if start < 0:
            needle = json.dumps(needle, ensure_ascii=False)[1:-1]
            start = source.content.find(needle)
        if start < 0:
            return []
        end = min(len(source.content), start + min(500, max(12, len(needle))))
        start = max(0, min(start, end - 12))
        return [
            {
                "evidence_id": source.id,
                "start": start,
                "end": end,
                "quote": source.content[start:end],
                "role": "supporting",
            }
        ]

    def add(rows, key, record, source, needle):
        record.update(evidence_ids=[source.id], citations=citation(source, needle))
        previous = rows.get(key)
        if previous:
            ids = list(dict.fromkeys(previous["evidence_ids"] + [source.id]))
            refs = {
                (c["evidence_id"], c["start"], c["end"]): c
                for c in previous["citations"] + record["citations"]
            }
            observations = previous.get("access_observations", []) + record.get("access_observations", [])
            if STATUS.get(record.get("status"), 0) > STATUS.get(previous.get("status"), 0):
                rows[key] = record
            rows[key].update(evidence_ids=ids, citations=list(refs.values())[:8])
            if observations:
                rows[key]["access_observations"] = list({json.dumps(v, sort_keys=True): v for v in observations}.values())[:12]
            if record.get("rendered") and record.get("status") == "inspected":
                rows[key]["rendered"] = True
        else:
            rows[key] = record

    def page(url, title, status, source, needle, **extra):
        try:
            parsed = urlsplit(url)
        except ValueError:
            return
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return
        url = safe_url(url)
        if len(pages) >= 160 and url not in pages:
            return
        add(
            pages,
            url,
            {"url": url, "title": (title or parsed.path or parsed.hostname)[:160], "status": status, **extra},
            source,
            needle,
        )

    def surface(row, source):
        if not isinstance(row, dict) or not isinstance(row.get("url"), str):
            return
        from .page_access import surface_access
        state = surface_access(row)
        if "content_available" not in row or not state["content_available"]:
            row = {**row, **{k: v for k, v in state.items() if k != "status"}}
            if not state["content_available"]:
                row["status"] = state["status"]
        url = row["url"]
        status = row.get("status", "inspected")
        state = {k: row[k] for k in ("access", "access_reason", "content_available") if k in row}
        observations = [{**state, "status": status, "rendered": bool(row.get("rendered")), "evidence_id": source.id}] if state else []
        page(url, row.get("title"), status, source, row.get("access_text") or row.get("title") or url, rendered=bool(row.get("rendered")) and status == "inspected", access_observations=observations, **state)
        if row.get("description") and row.get("content_available", True) and len(purpose) < 32:
            purpose.append(
                {
                    "text": row["description"],
                    "evidence_ids": [source.id],
                    "citations": citation(source, row["description"]),
                    "page_url": row["url"],
                    "rendered": bool(row.get("rendered")),
                    "primary": bool(target and host_family(urlsplit(row["url"]).hostname) == host_family(urlsplit(target).hostname) and urlsplit(row["url"]).path.rstrip("/") == urlsplit(target).path.rstrip("/")),
                }
            )
        for link in row.get("navigation", [])[:80]:
            if isinstance(link, dict) and isinstance(link.get("url"), str):
                page(link["url"], link.get("label"), "referenced", source, link.get("label") or link["url"])
        if not row.get("content_available", True):
            return
        for workflow in row.get("documented_workflows", [])[:12]:
            add(workflows, (url, workflow["title"]), {**workflow, "page_url": url}, source, workflow["description"])
        for form in row.get("forms", [])[:8]:
            if not isinstance(form, dict):
                continue
            fields = [f for f in form.get("fields", [])[:30] if isinstance(f, dict)]
            title = form.get("label") or "Form: " + ", ".join(
                f.get("label") or f.get("name", "") for f in fields[:3]
            )
            key = (url, form.get("action"), title)
            add(
                workflows,
                key,
                {
                    "title": title[:160],
                    "page_url": url,
                    "status": status,
                    "kind": "form",
                    "fields": [
                        {k: f[k] for k in ("name", "label", "type", "required") if k in f} for f in fields
                    ],
                    "action": form.get("action"),
                    "method": form.get("method", "GET"),
                    "execution": "not_submitted",
                },
                source,
                form.get("label") or (fields[0].get("name") if fields else form.get("action")),
            )
        for control in row.get("controls", [])[:24]:
            if (
                not isinstance(control, dict)
                or not control.get("label")
                or (control.get("role") not in {"tab", "summary"} and not control.get("disclosure"))
            ):
                continue
            add(
                workflows,
                (url, control["label"]),
                {
                    "title": control["label"],
                    "page_url": url,
                    "status": "referenced",
                    "kind": control["role"],
                    "execution": "not_inspected",
                },
                source,
                control["label"],
            )
        for feature in row.get("public_features", [])[:16]:
            if isinstance(feature, dict) and isinstance(feature.get("text"), str):
                add(
                    features,
                    (url, feature["text"]),
                    {
                        "text": feature["text"],
                        "page_url": url,
                        "status": "publicly_documented",
                        "commercial_scope": "public_wording",
                        "description": feature.get("description", ""),
                    },
                    source,
                    feature["text"],
                )

    snapshots = set()
    for source in sorted(
        evidence, key=lambda s: ((s.signals or {}).get("analysis_priority", 9), s.source_url)
    ):
        digest = getattr(source, "content_hash", "")
        if digest and digest in snapshots:
            continue
        snapshots.add(digest)
        info = source.signals or {}
        if source_scope(source, target)["role"] == "background_reference":
            continue
        from .document_product import document_surface
        documented = document_surface(source)
        if documented:
            surface(documented, source)
        if source.source_type == "html":
            from .source_storage import original_text
            row = surface_page(original_text(source), source.source_url, http_status=info.get("response_status"))
            if row:
                row.update(rendered=bool(info.get("rendered")))
                surface(row, source)
        if source.source_type == "json":
            try:
                data = json.loads(source.content)
            except (ValueError, RecursionError):
                continue
            if isinstance(data, dict) and data.get("contract") == CONTRACT:
                for row in (data.get("surface") if isinstance(data.get("surface"), list) else [])[:20]:
                    surface(row, source)
                for failure in data.get("coverage", {}).get("failures", [])[:30]:
                    if isinstance(failure, dict) and failure.get("stage") == "navigation" and failure.get("url"):
                        page(failure["url"], "", "collection_failed", source, failure["url"], access="unknown", access_reason=failure.get("code", "navigation_failed"), content_available=False)
                for outcome in data.get("coverage", {}).get("outcomes", [])[:30]:
                    if isinstance(outcome, dict) and outcome.get("status") in {"requires_login", "requires_subscription", "collection_failed"}:
                        page(outcome.get("url", ""), "", outcome["status"], source, outcome.get("url"), access=outcome["status"] if outcome["status"].startswith("requires_") else "unknown", access_reason=outcome.get("reason", ""), content_available=False)
                for row in data.get("sitemap_routes", [])[:100]:
                    if isinstance(row, dict):
                        page(
                            row.get("url", ""), "", "referenced", source, row.get("url"), discovery="sitemap"
                        )
                for interaction in data.get("coverage", {}).get("interactions", [])[:5]:
                    if not isinstance(interaction, dict):
                        continue
                    add(
                        workflows,
                        (interaction.get("page_url"), interaction.get("label")),
                        {
                            "title": interaction.get("label", "Disclosure"),
                            "page_url": interaction.get("page_url"),
                            "kind": interaction.get("role"),
                            "status": "inspected",
                            "execution": "disclosure_only",
                        },
                        source,
                        interaction.get("label"),
                    )
                for row in (data.get("responses") if isinstance(data.get("responses"), list) else [])[:200]:
                    if not isinstance(row, dict) or row.get("resource_type") not in {"fetch", "xhr"}:
                        continue
                    target = row.get("final_url") or row.get("url")
                    if not isinstance(target, str):
                        continue
                    key = (row.get("page_url"), row.get("method", "GET"), target)
                    add(
                        flows,
                        key,
                        {
                            "page_url": row.get("page_url"),
                            "target": target,
                            "method": row.get("method", "GET"),
                            "status": row.get("status"),
                            "basis": "observed_response",
                            "initiator": row.get("initiator"),
                            "response_shape": row.get("response_shape"),
                            "cache": row.get("headers", {}).get("cache-control"),
                            "authentication": "access_rejected"
                            if row.get("status") in {401, 403}
                            else "anonymous_read",
                            "read_operation": row.get("read_operation"),
                        },
                        source,
                        target,
                    )
        if source.source_type in {"javascript", "typescript"} and info.get("resource_role") not in {
            "tracking",
            "dependency",
        }:
            base = info.get("public_page") or info.get("linked_from") or source.source_url
            # Router declarations only; arbitrary strings are not routes.
            pattern = r'(?:\bpath\s*[:=]\s*|\b(?:createFileRoute|createRoute)\s*\(\s*)[\'"](?P<path>/[^\'"\r\n]{0,200})[\'"]'
            route_path = info.get("embedded_path") or source.source_url.removeprefix("local:")
            match_file = re.search(
                r"(?:^|/)(app|pages|routes)/(.+?)(?:/(?:page|\+page)|(?:/index)?)(?:\.[cm]?[jt]sx?|\.svelte|\.vue)$",
                route_path,
            )
            if match_file:
                parts = [
                    part
                    for part in match_file[2].split("/")
                    if part not in {"index"} and not part.startswith("(") and not part.startswith("@")
                ]
                declared = "/" + "/".join(parts)
                origin = (
                    urljoin(base, declared)
                    if urlsplit(base).scheme in {"http", "https"}
                    else "route:" + declared
                )
                add(
                    pages,
                    origin,
                    {
                        "url": origin,
                        "title": declared,
                        "status": "declared",
                        "discovery": "route_file_convention",
                        "source_path": route_path,
                    },
                    source,
                    source.content[:80],
                )
            for match in list(re.finditer(pattern, source.content[:2_000_000]))[:60]:
                if "${" not in match["path"] and urlsplit(base).scheme in {"http", "https"}:
                    page(
                        urljoin(base, match["path"]),
                        match["path"],
                        "declared",
                        source,
                        match[0],
                        discovery="client_router",
                    )
    for route in report.get("api_endpoints", []):
        if route.get("contract_basis") != "static_client_reference":
            continue
        claim = next((c for c in report.get("claims", []) if c["id"] == route.get("claim_id")), {})
        attrs = claim.get("attributes", {})
        target = attrs.get("address")
        if not target:
            continue
        source = sources.get(next(iter(claim.get("supporting_evidence_ids", [])), None))
        if source:
            observed = any(
                f["target"] == target
                and f["method"] == route.get("method")
                and f["basis"] == "observed_response"
                for f in flows.values()
            )
            key = (attrs.get("resource_url"), route.get("method"), target)
            add(
                flows,
                key,
                {
                    "target": target,
                    "method": route.get("method"),
                    "initiator": {"url": attrs.get("resource_url")},
                    "basis": "static_client_reference",
                    "correlated_response": observed,
                },
                source,
                target if target in source.content else route.get("path"),
            )
    for feature in report.get("features", []):
        claim = next((c for c in report.get("claims", []) if c["id"] == feature.get("claim_id")), {})
        eids = [eid for eid in claim.get("supporting_evidence_ids", []) if eid in sources]
        if eids:
            features[(feature.get("tier"), feature.get("feature"))] = {
                "text": feature.get("description") or feature.get("feature"),
                "tier": feature.get("tier"),
                "availability": feature.get("availability"),
                "commercial_scope": feature.get("commercial_scope"),
                "status": "declared",
                "evidence_ids": eids,
                "citations": claim.get("citations", []),
            }
    descriptions = []
    seen_purpose = set()
    for row in purpose:
        key = re.sub(r"\s+", " ", row["text"]).casefold()
        if row["citations"] and key not in seen_purpose:
            seen_purpose.add(key)
            descriptions.append(row)
    descriptions.sort(key=lambda p: (-bool(p.get("primary")), -bool(p.get("rendered")),
                                    -bool(re.search(r"\b(?:is (?:a|an)|platform|suite|application|tool)\b", p["text"], re.I)), len(p["text"])))
    headline = descriptions[0]["text"] if descriptions else ""
    return {
        "version": 2,
        "description": headline,
        "purpose": descriptions[:3],
        "pages": list(pages.values()),
        "workflows": sorted(workflows.values(), key=lambda w: (-STATUS.get(w.get("status"), 0), w.get("kind") != "documented_workflow"))[:80],
        "features": sorted(features.values(), key=lambda f: (-bool(re.search(r"\b(?:create|edit|design|collaborate|import|share|enhance|remove|generate|resize|export)\w*\b", f["text"], re.I)), -bool(f.get("description"))))[:80],
        "data_flows": list(flows.values())[:120],
        "coverage": {
            "pages_by_status": dict(Counter(p["status"] for p in pages.values())),
            "workflows_inspected": sum(w["status"] == "inspected" for w in workflows.values()),
            "correlated_calls": sum(bool(f.get("correlated_response")) for f in flows.values()),
            "pages_with_barriers": sum(not (p.get("rendered") and p["status"] == "inspected") and (p["status"] in {"collection_failed", "requires_login", "requires_subscription"} or any(o.get("status") in {"collection_failed", "requires_login", "requires_subscription"} for o in p.get("access_observations", []))) for p in pages.values()),
            "barrier_observations": sum(o.get("status") in {"collection_failed", "requires_login", "requires_subscription"} for p in pages.values() for o in p.get("access_observations", [])),
        },
        "open_questions": list(dict.fromkeys([p["url"] + ": " + str(o.get("access_reason") or o.get("status")).replace("_", " ") + "; restricted content was not inspected." for p in pages.values() for o in p.get("access_observations", []) if not (p.get("rendered") and p["status"] == "inspected") and o.get("status") in {"collection_failed", "requires_login", "requires_subscription"}]))[:12] + (["Referenced account areas and private workflows remain uninspected."] if any(re.search(r"account|login|signin|dashboard", p["url"], re.I) and p["status"] == "referenced" for p in pages.values()) else []),
    }
