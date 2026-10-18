import json
from types import SimpleNamespace

from sqlalchemy import func, select
from test_baseline import register
from test_saved_sources import imported

from app import jobs, model_gateway
from app.intelligence import answer_question
from app.models import Chunk, Event, Evidence, Investigation, ModelCache, Question
from app.query_engine import rank_passages, structured_answer


def test_reference_does_not_persist_or_queue(context):
    client, factory, queued = context
    assert client.get("/reference").status_code == 401
    register(client)
    for _ in range(3):
        detail = client.get("/reference?depth=standard").json()
        assert detail["ephemeral"] and detail["status"] == "completed"
        assert len(detail["report"]["nodes"]) >= 15
        assert detail["events"] == []
        assert detail["evidence"][0]["content_loaded"]
    assert len(client.get("/reference?depth=quick").json()["evidence"]) == 3
    old_client = client.post("/investigations", json={"domain": "example.com", "mode": "demo"})
    assert old_client.status_code == 200 and old_client.json()["ephemeral"]
    assert queued == [] and client.get("/investigations/history").json()["total"] == 0
    with factory() as db:
        for table in (Investigation, Evidence, Chunk, Event, Question, ModelCache):
            assert db.scalar(select(func.count()).select_from(table)) == 0


def test_reference_exports_remain_stateless(context):
    client, factory, queued = context
    register(client)
    for format in ("json", "markdown", "sqlite", "evidence"):
        response = client.get("/reference/standard/export/" + format)
        assert response.status_code == 200, response.text[:200]
        assert "attachment;" in response.headers["content-disposition"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Investigation)) == 0
    assert not queued


def test_explicit_query_answers_from_records_with_exact_spans(context, monkeypatch):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    monkeypatch.setattr(model_gateway, "generate", lambda *a: (_ for _ in ()).throw(AssertionError("Explicit answer must not invoke inference")))
    with factory() as db:
        inv = db.get(Investigation, identifier)
        answer = answer_question(db, inv, "Which API operations are declared?")
        assert answer["answer_version"] == 2 and answer["provider"] == "rules"
        record = next(r for r in answer["findings"] if "/projects" in r["text"])
        sources = {e.id: e for e in db.scalars(select(Evidence))}
        assert record["claim_ids"] and record["evidence_ids"]
        assert record["citations"]
        for citation in record["citations"]:
            assert sources[citation["evidence_id"]].content[citation["start"]:citation["end"]] == citation["quote"]
        missing = answer_question(db, inv, "Which database engine is used?")
        assert missing["insufficient_evidence"] and not missing["findings"]


def test_query_engine_is_independent_and_does_not_change_assessment(context, monkeypatch, hosted_query):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    original = client.get("/investigations/" + identifier).json()["report"]
    queue = []
    monkeypatch.setattr(jobs, "enqueue_question", queue.append)
    monkeypatch.setattr(model_gateway, "model_identity", lambda *a, **kw: "query-model:verified")

    def generate(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        assert provider == "gemini" and packet["retained_records"] and packet["assessment"]["counts"]["api_endpoints"]
        return {"insufficient_evidence": False, "statements": [{"text": "The API exposes a project listing operation.", "evidence": [next(iter(packet["passages"]))]}]}, {}

    monkeypatch.setattr(model_gateway, "generate", generate)
    response = client.post("/investigations/" + identifier + "/questions", json={"question": "Which API operations are declared?", "provider": "ollama", "model_profile": "light"})
    assert response.status_code == 202, response.text
    assert response.json()["processing_options"]["provider"] == "gemini"
    assert response.json()["processing_options"]["model_settings"]["model"] == "gemini-3.5-flash-lite"
    jobs.process_question(queue[0])
    item = client.get("/investigations/" + identifier + "/questions").json()[0]
    assert item["status"] == "completed" and item["answer"]["model"] == "query-model:verified"
    assert item["answer"]["statements"][0]["citations"]
    assert client.get("/investigations/" + identifier).json()["report"] == original
    doc = client.get("/investigations/" + identifier + "/export/json").json()
    assert doc["questions"][0]["processing_options"]["provider"] == "gemini"
    markdown = client.get("/investigations/" + identifier + "/export/markdown").text
    assert "/projects" in markdown
    recorded = markdown.split("## Research discussion", 1)[1]
    assert "The API exposes a project listing operation." in recorded
    assert "characters " not in recorded


def test_query_failure_keeps_structural_records_and_explains_failure(context, monkeypatch, hosted_query):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    queue = []
    monkeypatch.setattr(jobs, "enqueue_question", queue.append)
    monkeypatch.setattr(model_gateway, "model_identity", lambda *a, **kw: (_ for _ in ()).throw(model_gateway.ModelFailure("Model service unavailable.")))
    response = client.post("/investigations/" + identifier + "/questions", json={"question": "Which API operations are declared?", "provider": "ollama"})
    jobs.process_question(response.json()["id"])
    item = client.get("/investigations/" + identifier + "/questions").json()[0]
    assert item["status"] == "failed" and "unavailable" in item["error"]
    assert item["answer"]["interpretation_status"] == "unavailable"
    assert item["answer"]["findings"] and not item["answer"]["statements"]
    assert item["answer"]["provider"] == "gemini"


def test_hybrid_retrieval_has_zero_norm_guard_and_snapshot_diversity():
    chunks = [SimpleNamespace(id="one", evidence_id="a", start=0, content="Authentication uses OAuth tokens."),
              SimpleNamespace(id="mirror", evidence_id="b", start=0, content="Authentication uses OAuth tokens."),
              SimpleNamespace(id="other", evidence_id="c", start=0, content="Project routes require authentication.")]
    ranked = rank_passages(chunks, "How is authentication declared?", semantic_scores={c.id: 0 for c in chunks})
    assert len(ranked) == 2
    assert len({c.content for _, c in ranked}) == 2


def test_dependency_question_ranks_static_connections_without_runtime_claims():
    source = SimpleNamespace(id="s", content="from core import parser\n", source_url="local:main.py")
    report = {"claims": [], "nodes": [], "repository": {"modules": [
        {"path": "main.py", "evidence_id": "s", "imports": [{"name": "core.parser", "resolved_path": "parser.py", "offset": 0}]},
        {"path": "parser.py", "evidence_id": "s", "imports": []},
    ]}}
    answer = structured_answer(report, [source], "Which modules have the most dependency connections?")
    assert answer["findings"] and all("static source references" in r["text"] for r in answer["findings"])
    assert answer["findings"][0]["connections"] == 1
    citation = answer["findings"][0]["citations"][0]
    assert source.content[citation["start"]:citation["end"]] == citation["quote"]
