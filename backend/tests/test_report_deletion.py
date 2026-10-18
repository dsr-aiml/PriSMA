from sqlalchemy import select

from app import jobs
from app.models import Chunk, Event, Evidence, Investigation, ModelCache, Question, User
from test_baseline import register
from test_document_intelligence import run
from test_workspace_baseline import preview


SOURCES = [{"title": "Architecture", "origin": "local:architecture.md", "content": "**Frontend:**\n* React\n**Backend:**\n* Express\n"}]


def test_delete_report_cascades_records_and_preserves_other_data(context):
    client, factory, _ = context
    register(client)
    identifier, before = run(client, SOURCES)
    other_id, other_before = run(client, SOURCES)
    review = preview(client, "# Another source\n", "notes.md").json()
    with factory() as db:
        owner = db.scalar(select(User))
        question = Question(investigation_id=identifier, question="What is declared?", status="completed", answer={"statements": []})
        db.add_all([question, ModelCache(id="cancel:" + identifier, user_id=owner.id, result={}), ModelCache(id="shared-cache", user_id=owner.id, result={"keep": True})])
        db.commit()
        question_id = question.id
    assert client.delete(f"/investigations/{identifier}").json() == {"deleted": True, "investigation_id": identifier}
    assert client.get(f"/investigations/{identifier}").status_code == 404
    assert client.get(f"/investigations/{identifier}/sources/{before['evidence'][0]['id']}").status_code == 404
    assert client.get(f"/investigations/{identifier}/export/json").status_code == 404
    assert client.get(f"/investigations/{other_id}").json() == other_before
    assert client.get("/account").json()["workspace"]["reports"] == 1
    with factory() as db:
        assert db.get(ModelCache, review["bundle_id"]).result["sources"]
        assert db.get(Question, question_id) is None
        assert db.get(ModelCache, "cancel:" + identifier) is None
        assert db.get(ModelCache, "shared-cache").result == {"keep": True}
        for model in (Evidence, Chunk, Event, Question):
            assert not list(db.scalars(select(model).where(model.investigation_id == identifier)))
    assert client.delete(f"/investigations/{identifier}").status_code == 404
    client.post("/auth/logout")
    register(client, "stranger@example.com")
    assert client.delete(f"/investigations/{other_id}").status_code == 404


def test_delete_rejects_processing_and_active_questions(context):
    client, factory, _ = context
    register(client)
    identifier, before = run(client, SOURCES)
    with factory() as db:
        pending = Question(investigation_id=identifier, question="Read this source", status="queued")
        db.add(pending)
        db.commit()
        question_id = pending.id
    assert client.delete(f"/investigations/{identifier}").status_code == 409
    assert client.get(f"/investigations/{identifier}").json() == before
    with factory() as db:
        db.get(Question, question_id).status = "completed"
        db.get(Investigation, identifier).status = "analyzing"
        db.commit()
    assert client.delete(f"/investigations/{identifier}").status_code == 409
    with factory() as db:
        db.get(Investigation, identifier).status = "cancelled"
        db.commit()
    assert client.delete(f"/investigations/{identifier}").status_code == 200


def test_deleted_bundle_submission_creates_a_fresh_report(context):
    client, _, _ = context
    register(client)
    review = preview(client, SOURCES[0]["content"], "architecture.md").json()
    body = {"domain": "Source review", "bundle_id": review["bundle_id"], "selected": [row["id"] for row in review["sources"]]}
    identifier = client.post("/investigations/bundle", json=body).json()["id"]
    jobs.process(identifier)
    assert client.delete(f"/investigations/{identifier}").status_code == 200
    again = client.post("/investigations/bundle", json=body)
    assert again.status_code == 202, again.text
    assert again.json()["id"] != identifier


def test_reference_report_deletion_is_owned_and_saved_sources_are_read_only(context):
    client, _, _ = context
    register(client)
    identifier = client.post("/investigations", json={"domain": "example.com", "mode": "demo"}).json()["id"]
    assert identifier == "reference-standard"
    assert client.delete(f"/investigations/{identifier}").status_code == 404
    assert client.get("/investigations/history?scope=reference").json()["total"] == 0
    real_id, detail = run(client, SOURCES)
    assert client.delete(f"/investigations/{real_id}/sources/{detail['evidence'][0]['id']}").status_code == 405
    assert client.get(f"/investigations/{real_id}").json() == detail
