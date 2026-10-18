"""Cooperative stopping and immutable comparison of account-owned assessments."""

from .models import ModelCache
from .prose_structure import canonical_name


class RunCancelled(Exception):
    pass


def check_cancelled(investigation_id, db=None):
    if db is not None:
        if db.get(ModelCache, "cancel:" + investigation_id):
            raise RunCancelled()
        return
    from .jobs import SessionLocal

    # Read through a new session: the worker's identity map may hold an old snapshot.
    with SessionLocal() as db:
        if db.get(ModelCache, "cancel:" + investigation_id):
            raise RunCancelled()


def compare_reports(before, after):
    def connections(report):
        nodes = {n["id"]: n for n in report.get("nodes", [])}
        return [{**edge, "source_label": nodes.get(edge["source"], {}).get("label", edge["source"]),
                 "target_label": nodes.get(edge["target"], {}).get("label", edge["target"]),
                 "source_context": nodes.get(edge["source"], {}).get("context", ""),
                 "target_context": nodes.get(edge["target"], {}).get("context", "")} for edge in report.get("edges", [])]

    def fields(report):
        owners = {entity["id"]: entity for entity in report.get("entities", [])}
        return [{**field, "entity_name": owners.get(field["entity_id"], {}).get("name", ""),
                 "context": owners.get(field["entity_id"], {}).get("context", "")} for field in report.get("fields", [])]

    before = {**before, "edges": connections(before), "fields": fields(before)}
    after = {**after, "edges": connections(after), "fields": fields(after)}
    sections = {
        "components": ("nodes", lambda x: (canonical_name(x["label"]).casefold(), x.get("context", ""))),
        "connections": ("edges", lambda x: (canonical_name(x["source_label"]).casefold(), canonical_name(x["target_label"]).casefold(), x["label"].casefold(), x["source_context"], x["target_context"])),
        "routes": ("api_endpoints", lambda x: (x["method"], x["path"], x.get("context", ""))),
        "technologies": ("technologies", lambda x: (canonical_name(x["name"]).casefold(),)),
        "entities": ("entities", lambda x: (x["name"].casefold(), x.get("context", ""))),
        "features": ("features", lambda x: (x["feature"].casefold(), x["tier"].casefold())),
        "fields": ("fields", lambda x: (x["entity_name"].casefold(), x["name"].casefold(), x.get("context", ""))),
    }
    result = {}

    def fingerprint(row):
        if "declarations" in row:
            return sorted((x["group"], x["version"]) for x in row["declarations"])
        return {
            key: row.get(key)
            for key in ("description", "availability", "limitation", "classification", "kind", "type", "required", "schema", "parameters", "request_body", "responses", "security", "servers", "operation_id")
            if key in row
        }

    for section, (name, key) in sections.items():
        left = {key(row): row for row in before.get(name, [])}
        right = {key(row): row for row in after.get(name, [])}
        result[section] = {
            "added": [right[k] for k in sorted(right.keys() - left.keys())],
            "removed": [left[k] for k in sorted(left.keys() - right.keys())],
            "changed": [
                {"before": left[k], "after": right[k]}
                for k in sorted(left.keys() & right.keys())
                if fingerprint(left[k]) != fingerprint(right[k])
            ],
        }
    return {
        "sections": result,
        "scope": "Differences between retained findings; absence can reflect changed source coverage.",
        "before_sources": before.get("run", {}).get("source_hashes", []),
        "after_sources": after.get("run", {}).get("source_hashes", []),
        "same_source_documents": sorted(before.get("run", {}).get("source_hashes", [])) == sorted(after.get("run", {}).get("source_hashes", [])),
        "before_engine": before.get("run", {}).get("provider", ""),
        "after_engine": after.get("run", {}).get("provider", ""),
    }
