import io
import json
import zipfile

from sqlalchemy import select
from test_baseline import register
from test_document_intelligence import run
from test_workspace_baseline import preview

from app import jobs, model_gateway as gateway, public_files, source_intake
from app.models import Investigation, ModelCache, User
from app.source_intake import inspect_upload


def zipped(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in files:
            archive.writestr(path, text)
    return buffer.getvalue()


def project():
    return [
        ("repo/package.json", json.dumps({"name": "signal-service", "type": "module", "bin": {"signal": "scripts/start.mjs"}})),
        ("repo/tsconfig.json", '{"compilerOptions":{"baseUrl":".","paths":{"@core/*":["src/core/*"]}}}'),
        ("repo/tsconfig.build.json", '{"compilerOptions":{"rootDir":"src","outDir":"dist"}}'),
        ("repo/scripts/start.mjs", 'import { start } from "../dist/api/index.js";\nstart();\n'),
        ("repo/src/api/index.ts", '// Unicode 🙂\nimport { load as read } from "@core/store.js";\nexport function start() { return read(); }\n'),
        ("repo/src/core/store.ts", 'export function load() { return [{id: 1}]; }\n'),
        ("repo/docs/architecture.mermaid", 'flowchart LR\nC[Web client] -->|calls| A[Orders API]\nA --> D[(Order database)]\n'),
        ("repo/README.fr.md", "# Traduction\nDocumentation supplementary material.\n"),
        ("repo/tests/fake.ts", '// import { bad } from "../private";\nexport const fake = true;\n'),
    ]


def test_admission_is_order_independent_and_core_wins_budget(monkeypatch):
    monkeypatch.setattr(source_intake, "TOTAL_CHARACTERS", 1400)
    support = [(f"repo/scripts/check-{i}.js", f"// verifier {i}\nexport const checks = " + repr(list(range(100))) + ";\n") for i in range(15)]
    inputs = support + project()
    first = inspect_upload("repo.zip", zipped(inputs))
    second = inspect_upload("repo.zip", zipped(list(reversed(inputs))))
    assert [(r["source"]["origin"], r["content_hash"]) for r in first["sources"]] == [(r["source"]["origin"], r["content_hash"]) for r in second["sources"]]
    origins = {r["source"]["origin"] for r in first["sources"]}
    assert {"local:repo/src/api/index.ts", "local:repo/src/core/store.ts", "local:repo/scripts/start.mjs", "local:repo/docs/architecture.mermaid"} <= origins
    assert first["discovered"] == len(inputs)
    assert any(row["status"] == "deferred" for row in first["inventory"])


def test_syntax_resolution_groups_and_document_diagram(context):
    client, _, _ = context
    register(client)
    review = preview(client, zipped(project()), "repo.zip").json()
    selected = [r["id"] for r in review["sources"] if r["metadata"]["analysis_priority"] < 9]
    result = client.post("/investigations/bundle", json={"domain": "Signal", "bundle_id": review["bundle_id"], "selected": selected})
    identifier = result.json()["id"]
    jobs.process(identifier)
    detail = client.get(f"/investigations/{identifier}").json()
    assert detail["status"] == "completed", detail
    report = detail["report"]
    nodes = {n["id"]: n for n in report["nodes"]}
    assert "signal-service" in {n["label"] for n in nodes.values()}
    assert any(n["label"] == "Entrypoints" for n in nodes.values())
    assert any(n["label"] == "Order database" for n in nodes.values())
    modules = {m["path"]: m for m in report["repository"]["modules"]}
    assert modules["repo/src/api/index.ts"]["imports"][0]["resolved_path"] == "repo/src/core/store.ts"
    assert modules["repo/scripts/start.mjs"]["imports"][0]["resolved_path"] == "repo/src/api/index.ts"
    assert any(e.get("relationship_kind") == "static_call" and nodes[e["source"]]["label"] == "src/api" and nodes[e["target"]]["label"] == "src/core" for e in report["edges"])
    sources = {e["id"]: e for e in detail["evidence"]}
    for claim in report["claims"]:
        for citation in claim["citations"]:
            assert sources[citation["evidence_id"]]["content"][citation["start"]:citation["end"]] == citation["quote"]
    assert all(m["format"] in {"javascript", "typescript", "python"} for m in modules.values())
    assert report["run"]["coverage"]["status"] == "partial"  # Intentional selection excludes background files.


def test_shadowed_calls_and_comment_imports_are_not_connections(context):
    client, _, _ = context
    register(client)
    sources = [
        {"title": "Caller", "origin": "local:src/client/caller.ts", "content": 'import { send } from "../worker/task.js";\nfunction run(send: Function) { return send(); }\n// import missing from "./ghost";\n'},
        {"title": "Worker", "origin": "local:src/worker/task.ts", "content": 'export function send() { return "done"; }\n'},
    ]
    _, detail = run(client, sources)
    assert any(e.get("relationship_kind") == "imports" for e in detail["report"]["edges"])
    assert not any(e.get("relationship_kind") == "static_call" for e in detail["report"]["edges"])
    assert not any(ref["name"] == "./ghost" for module in detail["report"]["repository"]["modules"] for ref in module["imports"])


def test_missing_model_preserves_structural_findings(context, monkeypatch):
    client, _, _ = context
    register(client)
    def unavailable(*args, **kwargs):
        raise gateway.ModelFailure("Model service unavailable", code="transport")
    monkeypatch.setattr(gateway, "model_identity", unavailable)
    _, detail = run(client, [{"title": "Architecture", "origin": "local:architecture.md", "content": "**Frontend:**\n* React\n**Backend:**\n* Express\n"}], "ollama")
    assert detail["report"]["nodes"]
    assert detail["report"]["run"]["provider"] == "ollama"
    assert detail["report"]["run"]["requests"] == 0
    assert detail["report"]["run"]["coverage"]["status"] == "partial"


def test_compact_and_original_bundle_roundtrip_and_lazy_content(context):
    client, _, _ = context
    register(client)
    raw = "# Architecture\r\n\r\n**Backend:**\r\n* Express\r\n"
    identifier, detail = run(client, [{"title": "Architecture", "origin": "local:README.md", "content": raw}])
    compact = client.get(f"/investigations/{identifier}/export/json").json()
    assert compact["schema_version"] == 4 and "content" not in compact["passages"][0]
    assert compact["source_texts"][compact["evidence"][0]["content_ref"]] == detail["evidence"][0]["content"]
    restored = preview(client, json.dumps(compact), "compact.json")
    assert restored.status_code == 200, restored.text
    bundle = client.get(f"/investigations/{identifier}/export/evidence")
    restored_original = inspect_upload("evidence.zip", bundle.content)
    assert restored_original["sources"][0]["source"]["content"] == raw
    lazy = client.get(f"/investigations/{identifier}?include_content=false").json()
    assert lazy["evidence"][0]["content_loaded"] is False and "content" not in lazy["passages"][0]
    eid = detail["evidence"][0]["id"]
    assert client.get(f"/investigations/{identifier}/sources/{eid}").json()["original_content"] == raw


def test_repository_refresh_is_queued_and_reassessment_does_not_download(context, monkeypatch):
    client, factory, _ = context
    register(client)
    calls = []
    def read(url, **kwargs):
        calls.append(url)
        if kwargs.get("before_request"):
            kwargs["before_request"]()
        return zipped(project()), url, "application/zip"
    monkeypatch.setattr(public_files, "read_public", read)
    review = client.post("/sources/repository", json={"url": "https://github.com/example/signal"}).json()
    result = client.post("/investigations/bundle", json={"domain": "Signal", "bundle_id": review["bundle_id"], "selected": [r["id"] for r in review["sources"] if r["metadata"]["analysis_priority"] < 9]})
    identifier = result.json()["id"]
    jobs.process(identifier)
    old = client.get(f"/investigations/{identifier}").json()
    clone = client.post(f"/investigations/{identifier}/reassess").json()["id"]
    assert len(calls) == 1
    jobs.process(clone)
    refreshed = client.post(f"/investigations/{identifier}/refresh")
    assert refreshed.status_code == 202, refreshed.text
    assert len(calls) == 1  # Collection belongs to the worker, not a blocking API call.
    jobs.process(refreshed.json()["id"])
    assert len(calls) == 2
    fresh = client.get(f"/investigations/{refreshed.json()['id']}").json()
    assert fresh["status"] == "completed"
    assert fresh["processing_options"]["repository_refresh"]["completed"]
    assert client.get(f"/investigations/{identifier}").json() == old


def test_har_capture_maps_recorded_requests_without_fetching(context):
    client, _, _ = context
    register(client)
    capture = {"log": {"entries": [{"request": {"method": "GET", "url": "https://api.example.com/orders"}, "response": {"status": 200}}]}}
    _, detail = run(client, [{"title": "Network capture", "origin": "local:network.har", "format": "json", "content": json.dumps(capture)}])
    assert {"Browser session", "api.example.com"} <= {n["label"] for n in detail["report"]["nodes"]}
    assert detail["report"]["api_endpoints"][0]["path"] == "/orders"
    assert detail["report"]["edges"][0]["relationship_kind"] == "captured_request"


def test_declared_types_keep_owners_and_code_string_whitespace(context):
    client, _, _ = context
    register(client)
    code = 'const text = `first\n\n\nlast  `;\ninterface Order { id: string; total?: number; }\ninterface User { id: number; }\n'
    _, detail = run(client, [{"title": "Types", "origin": "local:src/types.ts", "content": code}])
    assert detail["evidence"][0]["content"] == code
    entities = {row["id"]: row["name"] for row in detail["report"]["entities"]}
    assert {(entities[row["entity_id"]], row["name"], row["type"]) for row in detail["report"]["fields"]} == {("Order", "id", "string"), ("Order", "total", "number"), ("User", "id", "number")}
    claims = {row["id"]: row for row in detail["report"]["claims"]}
    user_field = next(row for row in detail["report"]["fields"] if entities[row["entity_id"]] == "User")
    assert claims[user_field["claim_id"]]["citations"][0]["start"] >= code.index("interface User") - 20


def test_focused_reanalysis_preserves_original_and_rejects_foreign_ids(context):
    client, _, _ = context
    register(client)
    identifier, original = run(client, [{"title": "Frontend", "origin": "local:web.md", "content": "**Frontend:**\n* React\n"}, {"title": "Backend", "origin": "local:api.md", "content": "**Backend:**\n* Express\n"}])
    response = client.post(f"/investigations/{identifier}/reassess", json={"selected": [original["evidence"][0]["id"]], "provider": "rules"})
    assert response.status_code == 202, response.text
    jobs.process(response.json()["id"])
    assert len(client.get(f"/investigations/{response.json()['id']}").json()["evidence"]) == 1
    assert client.get(f"/investigations/{identifier}").json() == original
    assert client.post(f"/investigations/{identifier}/reassess", json={"selected": ["not-owned"]}).status_code == 422


def test_public_reads_expand_explicit_source_map_and_refresh_bypasses_cache(context, monkeypatch):
    import httpx
    from test_collection_scaffold import Budget, enable
    from app.collection import TinyFishCollector
    client, factory, _ = context
    register(client)
    enable(monkeypatch)
    paid = []
    def transport(request):
        paid.append(request.url)
        url = json.loads(request.content)["urls"][0]
        return httpx.Response(200, json={"results": [{"url": url, "final_url": url, "text": "# Public service\nDocumentation for the application.", "links": []}]})
    reads = []
    def read(url, **kwargs):
        reads.append(url)
        kwargs["before_request"]()
        if url.endswith("app.js"):
            return b'export const start = () => 1;\n//# sourceMappingURL=app.js.map', url, "application/javascript"
        if url.endswith(".map"):
            data = {"version": 3, "sources": ["src/api.ts"], "sourcesContent": ['export function list() { return fetch("/api/orders"); }']}
            return json.dumps(data).encode(), url, "application/json"
        return b'<html><body>Public service<script src="/app.js"></script></body></html>', url, "text/html; charset=utf-8"
    monkeypatch.setattr(public_files, "read_public", read)
    with factory() as db:
        owner = db.scalar(select(User)).id
        options = {"public_files": True, "fetch_limit": 1, "search_limit": 1, "direct_read_limit": 3}
        first = TinyFishCollector(db, owner, budget=Budget(), transport=httpx.MockTransport(transport), analysis_provider="rules", options=options)
        records = first.collect("example.com", lambda *_: None)
        assert first.record["search_attempts"] == 0 and first.record["url_attempts"] == 1
        assert first.record["public_files"]["requests"] == 3
        assert any(meta.get("collection_method") == "source_map" for _, _, meta in records)
        cached = TinyFishCollector(db, owner, budget=Budget(), transport=httpx.MockTransport(transport), options={"fetch_limit": 1, "search_limit": 0})
        cached.collect("example.com", lambda *_: None)
        assert len(paid) == 1 and cached.record["cache_hits"] == 1
        fresh = TinyFishCollector(db, owner, budget=Budget(), transport=httpx.MockTransport(transport), options={"fetch_limit": 1, "search_limit": 0, "refresh_origin": True})
        fresh.collect("example.com", lambda *_: None)
        assert len(paid) == 2 and fresh.record["cache_hits"] == 0


def test_utf16_and_json_configuration_punctuation_are_preserved():
    from app.repository import read_configuration
    text = "# Architecture\n**Frontend:**\n* React\n"
    review = inspect_upload("readme.md", text.encode("utf-16"))
    assert review["sources"][0]["source"]["content"] == text
    assert read_configuration('{"compilerOptions": {"paths":{"@x/*":["src/odd, }/*"],},},}') == {"compilerOptions": {"paths": {"@x/*": ["src/odd, }/*"]}}}
