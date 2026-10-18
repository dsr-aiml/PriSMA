import json
import sqlite3
from contextlib import nullcontext

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_baseline import register

from app import jobs
from app import model_gateway as gateway
from app.intelligence import Answer, answer_question, normalize_source
from app.models import Chunk, Investigation, ModelCache
from app.schemas import ImportedSource


def sample_sources():
    api = {
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1"},
        "paths": {"/projects": {"get": {"summary": "List projects"}}},
        "components": {"schemas": {"Project": {"type": "object", "properties": {"id": {"type": "string"}}}}},
    }
    return [
        {
            "title": "Public API",
            "origin": "local:api.json",
            "format": "openapi",
            "category": "api_reference",
            "content": json.dumps(api),
        }
    ]


def imported(client, sources=None, provider="rules", semantic=False):
    response = client.post(
        "/investigations/import",
        json={
            "domain": "example.com",
            "provider": provider,
            "semantic_retrieval": semantic,
            "sources": sources or sample_sources(),
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_sources_rules_exports_and_queue_ownership(context, monkeypatch, tmp_path, hosted_query):
    client, factory, queued = context
    register(client)
    inv_id = imported(client)
    jobs.process(inv_id)
    detail = client.get(f"/investigations/{inv_id}").json()
    assert detail["status"] == "completed"
    report = detail["report"]
    assert report["run"]["kind"] == "rules_only"
    assert report["run"]["requests"] == 0
    assert report["api_endpoints"][0]["path"] == "/projects"
    assert report["nodes"][0]["label"] == "Public API"
    assert report["entities"][0]["name"] == "Project"
    assert report["fields"][0]["type"] == "string"
    original = detail["evidence"][0]["content"]
    for claim in report["claims"]:
        for citation in claim["citations"]:
            assert original[citation["start"] : citation["end"]] == citation["quote"]
    qqueue = []
    monkeypatch.setattr(jobs, "enqueue_question", qqueue.append)
    monkeypatch.setattr(gateway, "model_identity", lambda *args, **kwargs: "gemini:test-model")
    def reply(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        return {"insufficient_evidence": False, "statements": [{"text": "The declared API includes /projects.", "evidence": [next(iter(packet["passages"]))]}]}, {}
    monkeypatch.setattr(gateway, "generate", reply)
    response = client.post(
        f"/investigations/{inv_id}/questions", json={"question": "Which project routes are documented?"}
    )
    assert response.status_code == 202
    jobs.process_question(qqueue[0])
    answer = client.get(f"/investigations/{inv_id}/questions").json()[0]["answer"]
    assert not answer["insufficient_evidence"] and answer["passages"]
    assert any("/projects" in record["text"] for record in answer["findings"])
    assert client.post(f"/investigations/{inv_id}/questions", json={"question": "     "}).status_code == 422
    doc = client.get(f"/investigations/{inv_id}/export/json").json()
    assert doc["mode"] == "saved" and "Fictional Atlas" not in doc["disclaimer"]
    assert doc["passages"] and doc["questions"]
    assert doc["source_texts"][doc["evidence"][0]["content_ref"]] == detail["evidence"][0]["content"]
    assert "content" not in doc["passages"][0]
    assert "DEMO DATA" not in client.get(f"/investigations/{inv_id}/export/markdown").text
    path = tmp_path / "saved.sqlite"
    path.write_bytes(client.get(f"/investigations/{inv_id}/export/sqlite").content)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()[0] == "saved"
        assert db.execute("SELECT COUNT(*) FROM claim_citations").fetchone()[0] > 0
        assert db.execute("SELECT COUNT(*) FROM original_sources").fetchone()[0] == 1
    client.post("/auth/logout")
    register(client, "other@example.com")
    assert client.get(f"/investigations/{inv_id}/questions").status_code == 404
    assert client.get(f"/investigations/{inv_id}/export/json").status_code == 404


def fake_model(provider, prompt, schema):
    if "insufficient_evidence" in schema["properties"]:
        packet = json.loads(prompt.split("\n", 1)[1])["passages"]
        return {
            "insufficient_evidence": False,
            "statements": [
                {
                    "text": "Source passages conflict about audit export.",
                    "citations": [
                        {"passage": k, "quote": v, "role": "supporting"} for k, v in packet.items()
                    ],
                }
            ],
        }, {}
    packet = json.loads(prompt.split("\n", 1)[1])
    findings = []
    for key, text in packet.items():
        findings.append(
            {
                "kind": "feature",
                "name": "Audit export",
                "detail": "Availability explicitly described for Enterprise.",
                "tier": "Enterprise",
                "availability": "excluded" if "excluded" in text else "included",
                "citations": [{"passage": key, "quote": text}],
            }
        )
    findings.append(
        {
            "kind": "technology",
            "name": "Invented",
            "detail": "This quote must not be accepted.",
            "citations": [{"passage": "p1", "quote": "This sentence does not exist."}],
        }
    )
    findings.append(
        {
            "kind": "connection",
            "name": "Unresolved service link",
            "source_name": "missing",
            "target_name": "missing2",
            "detail": "Valid quote cannot rescue absent nodes.",
            "citations": [{"passage": next(iter(packet)), "quote": next(iter(packet.values()))}],
        }
    )
    return {"findings": findings, "unknowns": ["Physical database engine is unspecified."]}, {}


def test_model_citations_conflicts_cache_and_answers(context, monkeypatch):
    client, factory, queued = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **kw: "test-model:digest")
    monkeypatch.setattr(gateway, "generate", fake_model)
    sources = [
        {
            "title": "Archived",
            "origin": "local:old",
            "category": "pricing",
            "content": "Audit export is included in the Enterprise tier.",
        },
        {
            "title": "Current",
            "origin": "local:new",
            "category": "pricing",
            "content": "Audit export is excluded from the Enterprise tier.",
        },
    ]
    first = imported(client, sources, "ollama")
    jobs.process(first)
    detail = client.get(f"/investigations/{first}").json()
    assert detail["status"] == "completed"
    report = detail["report"]
    assert len(report["features"]) == 2 and report["run"]["rejected_candidates"] == 2
    assert all(
        c["type"] == "feature" and c["contradicting_evidence_ids"] and c["confidence"] <= 45
        for c in report["claims"]
    )
    second = imported(client, sources, "ollama")
    jobs.process(second)
    reused = client.get(f"/investigations/{second}").json()["report"]
    # The batch contains an invented quote, so it must not poison later reassessments.
    assert reused["run"]["cache_hits"] == 0 and reused["run"]["requests"] == 1
    with factory() as db:
        inv = db.get(Investigation, first)
        answer = answer_question(db, inv, "Is audit export included in Enterprise?")
        assert not answer["insufficient_evidence"] and len(answer["statements"][0]["citations"]) == 2
        assert list(db.scalars(select(ModelCache)))
    client.post("/auth/logout")
    register(client, "other@example.com")
    third = imported(client, sources, "ollama")
    jobs.process(third)
    assert client.get(f"/investigations/{third}").json()["report"]["run"]["cache_hits"] == 0


def test_model_failure_preserves_sources_without_substitution(context, monkeypatch):
    client, factory, queued = context
    register(client)
    monkeypatch.setattr(
        gateway,
        "model_identity",
        lambda *a, **kw: (_ for _ in ()).throw(gateway.ModelFailure("Model is not installed.")),
    )
    inv_id = imported(client, provider="ollama")
    jobs.process(inv_id)
    detail = client.get(f"/investigations/{inv_id}").json()
    assert detail["status"] == "completed" and detail["report"]["run"]["coverage"]["status"] == "partial"
    assert detail["report"]["run"]["provider"] == "ollama"
    assert detail["report"]["api_endpoints"]
    assert detail["evidence"] and "not installed" in detail["report"]["run"]["failures"][0]["message"]
    assert (
        client.post(
            "/investigations/import",
            json={"domain": "example.com", "provider": "gemini", "sources": sample_sources()},
        ).status_code
        == 422
    )


def test_semantic_index_retrieval_and_model_change(context, monkeypatch):
    client, factory, queued = context
    register(client)
    monkeypatch.setattr(
        gateway, "model_identity", lambda *a, **kw: "embed-v1" if kw.get("embedding") else "model-v1"
    )
    monkeypatch.setattr(gateway, "generate", lambda *a: ({"findings": [], "unknowns": []}, {}))
    monkeypatch.setattr(gateway, "embed", lambda provider, texts: [[1.0] + [0.0] * 7 for text in texts])
    inv_id = imported(client, provider="ollama", semantic=True)
    jobs.process(inv_id)
    with factory() as db:
        inv = db.get(Investigation, inv_id)
        assert inv.report["run"]["retrieval"] == "semantic"
        assert db.scalar(select(Chunk)).embedding_model == "embed-v1"
        monkeypatch.setattr(
            gateway, "generate", lambda *a: ({"insufficient_evidence": True, "statements": []}, {})
        )
        answer = answer_question(db, inv, "What is not specified?")
        assert answer["retrieval"] == "hybrid" and answer["insufficient_evidence"]
        monkeypatch.setattr(gateway, "model_identity", lambda *a, **kw: "embed-v2")
        with pytest.raises(gateway.ModelFailure, match="changed"):
            answer_question(db, inv, "Another question?")


def test_model_transport_limits_and_json_contract(monkeypatch):
    monkeypatch.setattr(gateway, "model_slot", nullcontext)
    captured = []

    def request(method, url, **kwargs):
        captured.append(kwargs["json"])
        return {
            "done": True,
            "done_reason": "stop",
            "message": {"content": '{"insufficient_evidence":true,"statements":[]}'},
        }

    monkeypatch.setattr(gateway, "_request", request)
    result, usage = gateway.generate("ollama", "Only supplied evidence", Answer.model_json_schema())
    assert result["insufficient_evidence"]
    payload = captured[0]
    assert payload["keep_alive"] == "0" and not payload["think"] and not payload["stream"]
    assert payload["options"]["num_gpu"] == 0 and payload["options"]["num_thread"] <= 3
    monkeypatch.setattr(
        gateway,
        "_request",
        lambda *a, **kw: {"done": True, "done_reason": "length", "message": {"content": "{}"}},
    )
    with pytest.raises(gateway.ModelFailure):
        gateway.generate("ollama", "test", {})


def test_source_validation_and_html():
    source = ImportedSource(
        title="Text",
        origin="local:test",
        format="html",
        content="<h1>Readable heading</h1><script>Do not retain this</script><p>Useful public documentation.</p>",
    )
    assert "Do not retain" not in normalize_source(source)
    malformed = ImportedSource(
        title="API", origin="local:api", format="openapi", content='{"openapi":"3.0.3","paths":[]}'
    )
    with pytest.raises(ValueError):
        normalize_source(malformed)
    with pytest.raises(ValidationError):
        ImportedSource(title="Bad", origin="javascript:alert(1)", content="Useful public documentation.")


def test_hosted_transport_requires_enablement(monkeypatch):
    config = gateway.settings().model_copy(
        update={"allow_hosted_models": True, "gemini_api_key": "local-test-key"}
    )
    monkeypatch.setattr(gateway, "settings", lambda: config)
    monkeypatch.setattr(gateway, "model_slot", nullcontext)
    captured = []

    def request(method, url, **kwargs):
        captured.append((url, kwargs))
        return {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"insufficient_evidence":true,"statements":[]}'}]},
                }
            ]
        }

    monkeypatch.setattr(gateway, "_request", request)
    output, _ = gateway.generate("gemini", "Only source passages", Answer.model_json_schema())
    assert output["insufficient_evidence"]
    assert captured[0][1]["headers"] == {"x-goog-api-key": "local-test-key"}
    assert captured[0][1]["json"]["generationConfig"]["responseFormat"]["text"]["schema"] == Answer.model_json_schema()
    config.allow_hosted_models = False
    with pytest.raises(gateway.ModelFailure, match="disabled"):
        gateway.generate("gemini", "Must never execute", {})
    assert len(captured) == 1


def test_cache_key_changes_with_runtime_options(context, monkeypatch):
    from app.models import User

    client, factory, _ = context
    register(client)
    config = gateway.settings().model_copy()
    monkeypatch.setattr(gateway, "settings", lambda: config)
    from app import model_profiles

    monkeypatch.setattr(model_profiles, "settings", lambda: config)
    calls = []
    with factory() as db:
        owner = db.scalar(select(User)).id

        def operation():
            calls.append(True)
            return {"checked": True}

        assert gateway.cache_call(db, owner, "digest", "extract", "same-source", operation)[1] is False
        assert gateway.cache_call(db, owner, "digest", "extract", "same-source", operation)[1] is True
        config.model_context_tokens = 2048
        assert gateway.cache_call(db, owner, "digest", "extract", "same-source", operation)[1] is False
        assert len(calls) == 2
