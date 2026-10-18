import json
import sqlite3
from copy import deepcopy
from types import SimpleNamespace

from test_baseline import register
from test_document_intelligence import contract, run
from app.research import research_summary


def test_summary_keeps_api_contexts_and_matches_export_contract(context, tmp_path):
    client, _, _ = context
    register(client)
    first, second = contract(), contract()
    first["info"]["title"] = "Catalog"
    second["info"]["title"] = "Admin"
    identifier, detail = run(client, [{"title": "Contract", "origin": f"local:{i}/openapi.json", "content": json.dumps(doc)} for i, doc in enumerate((first, second))])
    summary = detail["analysis"]
    assert summary["counts"]["api_operations"] == 4
    assert {row["context"] for row in summary["api_surface"]} == {"Catalog", "Admin"}
    assert len({row["id"] for row in summary["insights"]}) == len(summary["insights"])
    ids = {c["id"] for c in detail["report"]["claims"]}
    eids = {e["id"] for e in detail["evidence"]}
    assert all(set(i["claim_ids"]) <= ids and set(i["evidence_ids"]) <= eids for i in summary["insights"])
    assert client.get(f"/investigations/{identifier}/export/json").json()["analysis"] == summary
    assert "Research highlights" in client.get(f"/investigations/{identifier}/export/markdown").text
    path = tmp_path / "research.sqlite"
    path.write_bytes(client.get(f"/investigations/{identifier}/export/sqlite").content)
    with sqlite3.connect(path) as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert json.loads(db.execute("SELECT summary_json FROM research_summary").fetchone()[0]) == summary
    assert client.get(f"/investigations/{identifier}?include_content=false").json()["analysis"] == summary


def test_mirrored_content_is_not_independent_support_and_findings_are_immutable():
    sources = [SimpleNamespace(id=id, content_hash="same", content="React", source_url=id, source_type="markdown", collection_method="user_import", signals={}) for id in ("a", "b")]
    report = {"claims": [{"id": "one", "type": "component", "description": "Web client", "classification": "observed", "supporting_evidence_ids": ["a", "b"], "contradicting_evidence_ids": []}], "nodes": [], "edges": []}
    original = deepcopy(report)
    result = research_summary(report, sources)
    assert result["counts"]["distinct_snapshots"] == 1
    assert not any(i["kind"] == "corroboration" for i in result["insights"])
    assert report == original
    sources[1].content_hash = "different"
    result = research_summary(report, sources)
    assert any(i["kind"] == "corroboration" and i["distinct_snapshots"] == 2 for i in result["insights"])


def test_dependency_insight_uses_resolved_modules_and_exact_unicode_spans():
    text = '// 🙂\nimport { load } from "./store";\nload();'
    sources = [SimpleNamespace(id=id, content_hash=id, content=text, source_url=id, source_type="code", collection_method="user_import", signals={}) for id in ("a", "b", "c")]
    report = {"claims": [], "repository": {"modules": [
        {"path": "a.ts", "evidence_id": "a", "imports": [{"name": "./store", "resolved_path": "store.ts", "offset": text.index('"./store"')}]},
        {"path": "b.ts", "evidence_id": "b", "imports": [{"name": "./store", "resolved_path": "store.ts", "offset": text.index('"./store"')}]},
        {"path": "store.ts", "evidence_id": "c", "imports": []},
    ]}}
    result = research_summary(report, sources)
    insight = next(i for i in result["insights"] if i["kind"] == "dependency")
    assert insight["data"]["callers"] == ["a.ts", "b.ts"]
    assert all(text[c["start"]:c["end"]] == c["quote"] for c in insight["citations"])
    report["repository"]["modules"][1]["imports"][0]["resolved_path"] = "missing.ts"
    assert not any(i["kind"] == "dependency" for i in research_summary(report, sources)["insights"])


def test_captured_requests_do_not_become_contract_declarations(context):
    client, _, _ = context
    register(client)
    capture={"log":{"entries":[{"request":{"method":"GET","url":"https://api.example.com/orders"},"response":{"status":200}}]}}
    _, detail=run(client,[{"title":"Network capture","origin":"local:network.har","format":"json","content":json.dumps(capture)}])
    assert detail["analysis"]["input_kind"] == "network_capture"
    assert all("declared operations" not in i["observation"] for i in detail["analysis"]["insights"] if i["kind"] == "api")
