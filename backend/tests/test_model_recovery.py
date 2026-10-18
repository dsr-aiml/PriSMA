import json
import sqlite3
from contextlib import nullcontext

import httpx
import pytest
from sqlalchemy import select
from test_baseline import register
from test_saved_sources import imported

from app import jobs
from app import model_gateway as gateway
from app.intelligence import Answer, answer_question
from app.models import Chunk, Investigation, ModelCache


def documents(count=4):
    return [
        {
            "title": f"Service notes {index}",
            "origin": f"local:notes-{index}.md",
            "content": f"The Gateway API service calls the Worker service to process requests. Document {index}.",
        }
        for index in range(count)
    ]


def findings(prompt, names=("Gateway API",)):
    packet = json.loads(prompt.split("\n", 1)[1])
    key, text = next(iter(packet.items()))
    return {
        "findings": [
            {
                "kind": "component",
                "name": name,
                "detail": "The source establishes this request-processing service.",
                "citations": [{"passage": key, "quote": text}],
            }
            for name in names
        ],
        "unknowns": [],
    }, {}


@pytest.mark.parametrize("failure_code", ["timeout", "invalid_json", "invalid_contract"])
def test_later_extraction_failure_retains_partial_report_and_exports(
    context, monkeypatch, tmp_path, failure_code
):
    client, factory, _ = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **kw: "test-model:digest")
    calls = []

    def generate(provider, prompt, schema):
        calls.append(prompt)
        if len(calls) == 2:
            if failure_code == "invalid_contract":
                return {"findings": [{"kind": "invented"}]}, {}
            raise gateway.ModelFailure("Controlled model failure.", code=failure_code)
        return findings(prompt)

    monkeypatch.setattr(gateway, "generate", generate)
    # Embeddings must not start after a timed-out generation request.
    monkeypatch.setattr(gateway, "embed", lambda *a: pytest.fail("Unexpected embedding request"))
    inv_id = imported(client, documents(), "ollama", semantic=True)
    jobs.process(inv_id)
    detail = client.get(f"/investigations/{inv_id}").json()
    report = detail["report"]
    assert detail["status"] == "completed" and detail["error"] is None
    assert len(calls) == 2 and report["nodes"][0]["label"] == "Gateway API"
    run = report["run"]
    assert run["processed_passages"] == 2 and run["passages"] == 4
    assert run["requests"] == 2 and run["failed_requests"] == 1
    assert run["failures"][0]["code"] == failure_code
    assert run["coverage"]["status"] == "partial"
    assert run["retrieval"] == "lexical" and run["semantic_index"] == "not_built"
    assert "Partial assessment saved" in detail["events"][-1]["message"]
    exported = client.get(f"/investigations/{inv_id}/export/json").json()
    assert exported["report"]["run"] == run
    markdown = client.get(f"/investigations/{inv_id}/export/markdown").text
    assert "| Model-reviewed passages | 2 of 4 |" in markdown
    assert markdown.count("| Failed model requests | 1 |") == 1
    path = tmp_path / "partial.sqlite"
    path.write_bytes(client.get(f"/investigations/{inv_id}/export/sqlite").content)
    with sqlite3.connect(path) as db:
        saved = json.loads(db.execute("SELECT value FROM metadata WHERE key='processing_record'").fetchone()[0])
        assert saved == run
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with factory() as db:
        assert len(list(db.scalars(select(ModelCache)))) == 1
        # Exact citation matching remains enforced in a partial report.
        for claim in report["claims"]:
            for citation in claim["citations"]:
                source = next(e for e in detail["evidence"] if e["id"] == citation["evidence_id"])
                assert source["content"][citation["start"]:citation["end"]] == citation["quote"]


def test_first_request_failure_stays_failed_without_substitution(context, monkeypatch):
    client, factory, _ = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **kw: "test-model:digest")
    monkeypatch.setattr(
        gateway, "generate",
        lambda *a: (_ for _ in ()).throw(gateway.ModelFailure("Timed out.", code="timeout")),
    )
    inv_id = imported(client, documents(), "ollama")
    jobs.process(inv_id)
    detail = client.get(f"/investigations/{inv_id}").json()
    assert detail["status"] == "failed" and detail["report"]["run"]["failures"][0]["code"] == "timeout" and not detail["report"]["claims"] and detail["evidence"]
    assert "Timed out" in detail["error"]


def test_relationship_failure_preserves_components(context, monkeypatch):
    client, _, _ = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **kw: "test-model:digest")

    def generate(provider, prompt, schema):
        if prompt.startswith("Extract at most 3 connection"):
            raise gateway.ModelFailure("Timed out.", code="timeout")
        return findings(prompt, ("Gateway API", "Worker"))

    monkeypatch.setattr(gateway, "generate", generate)
    inv_id = imported(client, documents(2), "ollama")
    jobs.process(inv_id)
    report = client.get(f"/investigations/{inv_id}").json()["report"]
    assert len(report["nodes"]) == 2 and not report["edges"]
    assert report["run"]["failures"][0]["stage"] == "relationship review"
    assert report["run"]["processed_passages"] == 2
    assert report["run"]["coverage"]["status"] == "partial"


def test_partial_index_is_never_used_for_semantic_retrieval(context, monkeypatch):
    client, factory, _ = context
    register(client)
    monkeypatch.setattr(
        gateway, "model_identity", lambda *a, **kw: "embed-v1" if kw.get("embedding") else "model-v1"
    )
    monkeypatch.setattr(gateway, "generate", lambda provider, prompt, schema: findings(prompt))
    batches = []

    def embed(provider, texts):
        batches.append(texts)
        if len(batches) == 2:
            raise gateway.ModelFailure("Embedding service disconnected.", code="transport_error")
        return [[1.0] + [0.0] * 7 for _ in texts]

    monkeypatch.setattr(gateway, "embed", embed)
    inv_id = imported(client, documents(17), "ollama", semantic=True)
    jobs.process(inv_id)
    report = client.get(f"/investigations/{inv_id}").json()["report"]
    assert report["run"]["semantic_index"] == "incomplete"
    assert report["run"]["retrieval"] == "lexical"
    assert report["run"]["processed_passages"] == 17
    monkeypatch.setattr(gateway, "embed", lambda *a: pytest.fail("Incomplete index must not be queried"))
    monkeypatch.setattr(gateway, "generate", lambda *a: ({"insufficient_evidence": True, "statements": []}, {}))
    with factory() as db:
        assert any(c.embedding for c in db.scalars(select(Chunk)))
        answer = answer_question(db, db.get(Investigation, inv_id), "Which service processes requests?")
        assert answer["retrieval"] == "lexical"


@pytest.mark.parametrize(
    "outcome,code",
    [("timeout", "timeout"), ("connect", "transport_error"), ("json", "invalid_json"), ("shape", "invalid_response")],
)
def test_transport_failure_categories_are_specific_and_safe(monkeypatch, outcome, code):
    def handler(request):
        if outcome == "timeout":
            raise httpx.ReadTimeout("Secret upstream body must not appear", request=request)
        if outcome == "connect":
            raise httpx.ConnectError("Secret connection details", request=request)
        if outcome == "json":
            return httpx.Response(200, text="private invalid response")
        return httpx.Response(200, json=[])

    client_type = httpx.Client
    monkeypatch.setattr(gateway.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(gateway.ModelFailure) as caught:
        gateway._request("POST", "http://ollama:11434/api/chat")
    assert caught.value.code == code
    assert "Secret" not in str(caught.value) and "private" not in str(caught.value)


def test_request_timeout_configuration_reaches_transport(monkeypatch):
    seen = []
    client_type = httpx.Client

    def client(**kwargs):
        seen.append(kwargs["timeout"])
        return client_type(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})), **kwargs)

    monkeypatch.setattr(gateway.httpx, "Client", client)
    config = gateway.settings().model_copy(update={"model_timeout_seconds": 180})
    monkeypatch.setattr(gateway, "settings", lambda: config)
    gateway._request("GET", "http://ollama:11434/api/tags")
    assert seen[0].read == 180 and seen[0].connect == 5


def test_missing_model_message_is_a_controlled_failure(monkeypatch):
    monkeypatch.setattr(gateway, "model_slot", nullcontext)
    monkeypatch.setattr(gateway, "_request", lambda *a, **kw: {"done": True, "message": None})
    with pytest.raises(gateway.ModelFailure, match="message object"):
        gateway.generate("ollama", "Test", Answer.model_json_schema())
