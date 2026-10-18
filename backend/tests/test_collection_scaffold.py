import json
from contextlib import nullcontext

import httpx
import pytest
from sqlalchemy import select
from test_baseline import register
from test_saved_sources import imported

from app import jobs, model_profiles
from app import model_gateway as gateway
from app.collection import CollectionFailure, TinyFishCollector, scoped_url
from app.config import settings
from app.intelligence import Citation, Finding, candidate_problem, chunk_spans, normalize_source
from app.models import Evidence, User
from app.schemas import ImportedSource


class Budget:
    def __init__(self):
        self.counts = {"search": 0, "fetch": 0}

    def reserve(self, product, count=1):
        self.counts[product] += count


def enable(monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "tinyfish_enabled", True)
    monkeypatch.setattr(cfg, "tinyfish_api_key", "test-only-never-live")
    # These existing tests exercise the maximum administrator-approved bounds.
    monkeypatch.setattr(cfg, "tinyfish_searches_per_run", 5)
    monkeypatch.setattr(cfg, "tinyfish_fetch_attempts_per_run", 20)
    return cfg


def test_scope_blocks_credentials_local_targets_and_lookalike_hosts():
    assert (
        scoped_url("https://docs.example.com/docs#section", "example.com") == "https://docs.example.com/docs"
    )
    for url in (
        "https://example.com.attacker.org/docs",
        "https://evil-example.com",
        "https://user:secret@example.com",
        "http://127.0.0.1",
        "http://localhost",
        "file:///etc/passwd",
        "https://example.com:9999/",
    ):
        assert scoped_url(url, "example.com") is None


def test_real_history_is_separate_from_reference(context):
    client, _, _ = context
    register(client)
    ref = client.post("/investigations", json={"domain": "atlas.example"}).json()["id"]
    real = imported(client)
    assert [i["id"] for i in client.get("/investigations?scope=real").json()] == [real]
    assert ref == "reference-standard"
    assert client.get("/investigations?scope=reference").json() == []
    assert client.post("/investigations/web", json={"domain": "example.com"}).status_code == 503


def test_collection_scope_redirect_errors_cache_and_isolation(context, monkeypatch):
    client, factory, _ = context
    register(client)
    enable(monkeypatch)
    calls = []
    text = "Gateway API dispatches asynchronous jobs to a queue. Workers process the queued jobs."

    def transport(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": "https://example.com/pricing"},
                        {"url": "https://attacker.org/page"},
                        {"url": "https://example.com/docs/login"},
                        {"url": "https://example.com/docs/redirect"},
                    ]
                },
            )
        url = json.loads(request.content)["urls"][0]
        if url.endswith("/login"):
            return httpx.Response(
                200, json={"results": [], "errors": [{"url": url, "error": "login_required"}]}
            )
        final = "https://attacker.org/page" if url.endswith("/redirect") else url
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "final_url": final,
                        "title": "Technical documentation",
                        "text": text,
                        "links": [],
                    }
                ],
                "errors": [],
            },
        )

    with factory() as db:
        owner = db.scalar(select(User)).id
        budget = Budget()
        collector = TinyFishCollector(db, owner, budget=budget, transport=httpx.MockTransport(transport))
        sources = collector.collect("example.com", lambda *_: None)
        assert len(sources) == 1  # Root and pricing contain duplicate normalized text.
        assert collector.record["status"] == "partial"
        assert collector.record["search_attempts"] == 5 and collector.record["url_attempts"] == 4
        assert any(o.get("reason") == "redirect_outside_scope" for o in collector.record["outcomes"])
        assert any(o.get("reason") == "login_required" for o in collector.record["outcomes"])
        assert not any(b"attacker.org" in r.content for r in calls if r.method == "POST")
        again = TinyFishCollector(db, owner, budget=Budget(), transport=httpx.MockTransport(transport))
        again.collect("example.com", lambda *_: None)
        assert again.record["cache_hits"] >= 5 and again.record["search_attempts"] == 0
        assert again.record["url_attempts"] == 1  # Failed login response isn't cached.
        other = User(username="collector_other", email="other@example.com", password_hash="not-an-account")
        db.add(other)
        db.commit()
        isolated = TinyFishCollector(db, other.id, budget=Budget(), transport=httpx.MockTransport(transport))
        isolated.collect("example.com", lambda *_: None)
        assert isolated.record["cache_hits"] == 0


def test_retry_attempts_share_twenty_url_limit(context, monkeypatch):
    client, factory, _ = context
    register(client)
    enable(monkeypatch)

    def transport(request):
        if request.method == "GET":
            return httpx.Response(
                200, json={"results": [{"url": f"https://example.com/docs/{i}"} for i in range(30)]}
            )
        return httpx.Response(200, json={"results": [], "errors": [{"error": "timeout"}]})

    with factory() as db:
        collector = TinyFishCollector(
            db, db.scalar(select(User)).id, budget=Budget(), transport=httpx.MockTransport(transport)
        )
        with pytest.raises(CollectionFailure, match="No usable"):
            collector.collect("example.com", lambda *_: None)
        assert collector.record["url_attempts"] == 20
        assert collector.record["collected_sources"] == 0


def test_allowance_failure_never_falls_back(context, monkeypatch):
    client, factory, _ = context
    register(client)
    enable(monkeypatch)
    called = []

    def transport(request):
        called.append(str(request.url))
        return httpx.Response(402, json={"error": "FREE_ALLOWANCE_EXHAUSTED"})

    with factory() as db:
        collector = TinyFishCollector(
            db, db.scalar(select(User)).id, budget=Budget(), transport=httpx.MockTransport(transport)
        )
        with pytest.raises(CollectionFailure, match="allowance is exhausted"):
            collector.collect("example.com", lambda *_: None)
        assert len(called) == 1 and called[0].startswith("https://api.fetch.tinyfish.ai")
        assert collector.record["status"] == "failed"


def test_web_job_stores_collected_provenance_and_exports(context, monkeypatch, tmp_path):
    import sqlite3

    from app import collection

    client, _, _ = context
    register(client)
    enable(monkeypatch)

    def collect(self, domain, progress):
        self.record.update(status="collecting", search_attempts=5, url_attempts=1)
        self.record["outcomes"].append({"url": "https://example.com/docs", "status": "collected"})
        progress(10, "Collected 1 documents; 1 URL attempts.")
        self.record["url_attempts"] = 20
        self.record["outcomes"].append(
            {"url": "https://example.com/private", "status": "unavailable", "reason": "login_required"}
        )
        progress(10, "Collected 1 documents; 20 URL attempts.")
        self.record.update(status="partial", collected_sources=1, stop_reason="A public page was blocked.")
        source = ImportedSource(
            title="API documentation",
            origin="https://example.com/docs",
            format="text",
            content="Technology: PostgreSQL\nPublic API documentation describes resource endpoints.",
        )
        return [
            (source, normalize_source(source), {"requested_url": source.origin, "final_url": source.origin})
        ]

    monkeypatch.setattr(collection.TinyFishCollector, "collect", collect)
    created = client.post("/investigations/web", json={"domain": "example.com"})
    assert created.status_code == 202
    inv_id = created.json()["id"]
    jobs.process(inv_id)
    detail = client.get(f"/investigations/{inv_id}").json()
    assert detail["status"] == "completed"
    assert detail["mode"] == "live" and detail["evidence"][0]["collection_method"] == "tinyfish_fetch"
    assert detail["report"]["run"]["collection"]["status"] == "partial"
    assert detail["processing_options"]["collection"]["status"] == "partial"
    assert detail["processing_options"]["collection"]["url_attempts"] == 20
    assert len(detail["processing_options"]["collection"]["outcomes"]) == 2
    assert "no target website" not in detail["events"][0]["message"]
    doc = client.get(f"/investigations/{inv_id}/export/json").json()
    assert doc["schema_version"] == 4 and doc["contract"] == "prisma.report"
    assert doc["processing_options"]["collection"]["url_attempts"] == 20
    assert "User-supplied snapshots" not in doc["disclaimer"]
    md = client.get(f"/investigations/{inv_id}/export/markdown").text
    assert "## Executive summary" in md and "## Source register" in md and r"login\_required" in md
    assert md.count("heuristic ratings, not probabilities") == 1
    assert "| Collection status | partial |" in md and "| Discovery Search requests | 5 |" in md and "| Document Fetch requests | 20 |" in md
    assert "No model review was performed." in md
    path = tmp_path / "web.sqlite"
    path.write_bytes(client.get(f"/investigations/{inv_id}/export/sqlite").content)
    with sqlite3.connect(path) as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert db.execute("SELECT COUNT(*) FROM source_metadata").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM collection_outcomes").fetchone()[0] == 2


def test_profiles_require_opt_in_and_memory_budget(monkeypatch):
    cfg = settings()
    with pytest.raises(gateway.ModelFailure, match="not enabled"):
        model_profiles.snapshot("ollama", "balanced")
    monkeypatch.setattr(cfg, "allow_large_local_models", True)
    monkeypatch.setattr(cfg, "ollama_balanced_model", "selected:5b")
    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *a, **kw: {
            "models": [{"name": "selected:5b", "size": 3_000_000_000, "digest": "installed-digest"}]
        },
    )
    options = {"model_settings": model_profiles.snapshot("ollama", "balanced")}
    with model_profiles.using(options), pytest.raises(gateway.ModelFailure, match="working memory"):
        gateway.model_identity("ollama")
    monkeypatch.setattr(cfg, "inference_memory_budget_bytes", 8_000_000_000)
    options = {"model_settings": model_profiles.snapshot("ollama", "balanced")}
    with model_profiles.using(options):
        assert gateway.model_identity("ollama") == "ollama:selected:5b:installed-digest"


def test_snapshotted_profile_controls_transport_after_config_change(monkeypatch):
    cfg = settings()
    saved = model_profiles.snapshot("ollama")
    monkeypatch.setattr(cfg, "ollama_model", "new-default:1b")
    monkeypatch.setattr(gateway, "model_slot", nullcontext)
    calls = []

    def request(*args, **kw):
        calls.append(kw["json"])
        return {"done": True, "done_reason": "stop", "message": {"content": "{}"}}

    monkeypatch.setattr(gateway, "_request", request)
    with model_profiles.using({"model_settings": saved}):
        gateway.generate("ollama", "test", {})
    assert calls[0]["model"] == saved["model"] and calls[0]["options"]["num_gpu"] == 0


def test_heading_and_negation_guards():
    source = Evidence(id="source", signals={"title": "Fictional Beacon architecture"})
    heading = Finding(
        kind="component",
        name="Fictional Beacon architecture",
        detail="Architecture documentation overview",
        citations=[Citation(passage="p1", quote="Fictional Beacon architecture")],
    )
    assert "heading" in candidate_problem(
        heading, [{"quote": "Fictional Beacon architecture", "role": "supporting"}], [source]
    )
    technology = Finding(
        kind="technology",
        name="MongoDB",
        detail="Database used by the product",
        citations=[Citation(passage="p1", quote="We do not use MongoDB for this service.")],
    )
    assert "Negated" in candidate_problem(
        technology, [{"quote": "We do not use MongoDB for this service.", "role": "supporting"}], []
    )


def test_paragraph_chunks_retain_offsets_and_html_table_headers():
    text = ("A paragraph with useful detail. " * 30 + "\n\n") * 4
    spans = list(chunk_spans(text))
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(end - start <= 1000 for start, end in spans)
    assert all(nxt[0] <= prev[1] for prev, nxt in zip(spans, spans[1:]))
    source = ImportedSource(
        title="Pricing",
        origin="local:pricing.html",
        format="html",
        content="<table><tr><th>Feature</th><th>Enterprise</th></tr><tr><td>Audit export</td><td>Not included</td></tr></table><script>Ignore evidence</script>",
    )
    normalized = normalize_source(source)
    assert "Enterprise" in normalized and "Audit export" in normalized and "Ignore evidence" not in normalized


def test_architecture_components_and_connections_across_documents(context, monkeypatch):
    client, _, _ = context
    register(client)
    notes = "Fictional Beacon architecture\nWeb client sends requests to Gateway API. Gateway API sends jobs to Job queue. Worker consumes jobs from Job queue."
    sources = [
        {"title": "Fictional Beacon architecture", "origin": "local:architecture.md", "content": notes},
        {
            "title": "Commercial terms",
            "origin": "local:pricing.md",
            "content": "Enterprise includes audit export, with a maximum of fifty exports per month.",
        },
    ]
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **kw: "test-model:digest")

    def model(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        key = next((k for k, v in packet.items() if "Fictional Beacon architecture" in v), None)
        if key is None:
            return {"findings": [], "unknowns": []}, {}
        findings = []
        if "previously validated components" in prompt:
            for source, target, quote in [
                ("Web client", "Gateway API", "Web client sends requests to Gateway API."),
                ("Gateway API", "Job queue", "Gateway API sends jobs to Job queue."),
                ("Job queue", "Worker", "Worker consumes jobs from Job queue."),
            ]:
                findings.append(
                    {
                        "kind": "connection",
                        "name": source + " to " + target,
                        "detail": "Documented component interaction.",
                        "source_name": source,
                        "target_name": target,
                        "citations": [{"passage": next(k for k, v in packet.items() if quote in v), "quote": quote}],
                    }
                )
        else:
            for name, quote in [
                ("Web client", "Web client sends requests to Gateway API."),
                ("Gateway API", "Gateway API sends jobs to Job queue."),
                ("Job queue", "Gateway API sends jobs to Job queue."),
                ("Worker", "Worker consumes jobs from Job queue."),
                ("Fictional Beacon architecture", "Fictional Beacon architecture"),
            ]:
                findings.append(
                    {
                        "kind": "component",
                        "name": name,
                        "detail": "Documented component of the service.",
                        "citations": [{"passage": next(k for k, v in packet.items() if quote in v), "quote": quote}],
                    }
                )
        return {"findings": findings, "unknowns": []}, {}

    monkeypatch.setattr(gateway, "generate", model)
    inv_id = imported(client, sources, "ollama")
    jobs.process(inv_id)
    report = client.get(f"/investigations/{inv_id}").json()["report"]
    assert {n["label"] for n in report["nodes"]} == {"Web client", "Gateway API", "Job queue", "Worker"}
    assert len(report["edges"]) == 3
    assert report["run"]["rejected_candidates"] == 1
    assert "Gateway API" in report["summary"] and "Fictional Beacon architecture" not in report["summary"]


def test_malformed_openapi_is_rejected_before_queueing(context):
    client, _, queued = context
    register(client)
    for spec in (
        {"openapi": "3.0.3", "paths": {"/projects": {"get": None}}},
        {"openapi": "3.0.3", "components": {"schemas": {"Project": {"properties": {"owner": {"$ref": 42}}}}}},
    ):
        source = {
            "title": "Invalid specification",
            "origin": "local:bad.json",
            "format": "openapi",
            "content": json.dumps(spec),
        }
        response = client.post("/investigations/import", json={"domain": "example.com", "sources": [source]})
        assert response.status_code == 422
    assert queued == []
