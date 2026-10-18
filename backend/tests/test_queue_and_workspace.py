import json
import uuid

from rq import Queue
from rq.job import validate_job_id
from sqlalchemy import select
from test_baseline import register

from app import jobs
from app.models import AuthSession, Chunk, Event, Evidence, Investigation, ModelCache, Question, User


def test_real_rq_job_construction_accepts_generated_ids(monkeypatch):
    # Keep real RQ argument, callback, ID and serializer handling; stop only persistence.
    queued = []

    def enqueue_job(self, job, **kwargs):
        queued.append(job)
        return job

    monkeypatch.setattr(Queue, "enqueue_job", enqueue_job)
    identifier = str(uuid.uuid4())
    first, second = jobs.enqueue(identifier), jobs.enqueue(identifier)
    for job in queued:
        validate_job_id(job.id)
        assert ":" not in job.id
        assert job.func_name == "app.jobs.process"
        assert job.args == (identifier,)
        assert json.loads(job.data)[0] == "app.jobs.process"
    assert first.id != second.id and first.timeout == 2400


def preview(client):
    response = client.post(
        "/sources/preview?filename=routes.md",
        content=b"GET /documents returns application document records.",
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_failed_queue_preserves_review_and_retry_reuses_assessment(context, monkeypatch):
    client, factory, _ = context
    register(client)
    reviewed = preview(client)
    body = {
        "domain": "General repository",
        "bundle_id": reviewed["bundle_id"],
        "selected": [r["id"] for r in reviewed["sources"]],
    }
    queued = []

    def submit(identifier):
        queued.append(identifier)
        if len(queued) == 1:
            raise ValueError("Queue submission failed in this controlled test.")

    monkeypatch.setattr(jobs, "enqueue", submit)
    failed = client.post("/investigations/bundle", json=body)
    assert failed.status_code == 503
    identifier = failed.json()["detail"]["investigation_id"]
    with factory() as db:
        assert db.get(ModelCache, reviewed["bundle_id"])
        assert db.get(Investigation, identifier).status == "failed"
    retry = client.post("/investigations/bundle", json=body)
    assert retry.status_code == 202 and retry.json()["id"] == identifier
    repeated = client.post("/investigations/bundle", json=body)
    assert repeated.status_code == 202 and repeated.json()["id"] == identifier
    assert queued == [identifier, identifier]
    with factory() as db:
        assert len(list(db.scalars(select(Investigation)))) == 1
        assert len(list(db.scalars(select(Evidence)))) == 1


def test_data_clear_is_password_checked_and_account_scoped(context):
    client, factory, _ = context
    register(client)
    first = client.post(
        "/investigations/import",
        json={
            "domain": "Owner documents",
            "sources": [
                {
                    "title": "Routes",
                    "origin": "local:routes.md",
                    "content": "GET /documents returns application document records.",
                }
            ],
        },
    ).json()["id"]
    jobs.process(first)
    reference = client.post(
        "/investigations", json={"domain": "atlas.example", "mode": "demo", "depth": "quick"}
    ).json()["id"]
    assert reference == "reference-quick"
    preview(client)
    with factory() as db:
        owner = db.scalar(select(User))
        db.add(ModelCache(id="owner-cache", user_id=owner.id, result={"private": "data"}))
        db.add(Question(investigation_id=first, question="Which routes are documented?", status="completed"))
        db.commit()
        owner_id = owner.id
    client.post("/auth/logout")
    register(client, "other@example.com")
    second = client.post(
        "/investigations/import",
        json={
            "domain": "Other account",
            "sources": [
                {
                    "title": "Routes",
                    "origin": "local:other.md",
                    "content": "POST /tasks starts processing of application tasks.",
                }
            ],
        },
    ).json()["id"]
    jobs.process(second)
    client.post("/auth/logout")
    assert (
        client.post(
            "/auth/login", json={"email": "owner@example.com", "password": "Strong-local-password"}
        ).status_code
        == 200
    )
    assert client.post("/account/data/clear", json={"current_password": "incorrect"}).status_code == 403
    counts = client.get("/account").json()["workspace"]
    assert counts["reports"] == 1 and counts["reference_reports"] == 0 and counts["questions"] == 1
    cleared = client.post("/account/data/clear", json={"current_password": "Strong-local-password"})
    assert cleared.status_code == 200, cleared.text
    assert client.get("/auth/me").status_code == 200
    assert client.get("/account").json()["workspace"]["reports"] == 0
    with factory() as db:
        assert db.get(User, owner_id)
        assert db.scalar(select(AuthSession).where(AuthSession.user_id == owner_id))
        assert (
            db.get(Investigation, second)
            and not db.get(Investigation, first)
            and not db.get(Investigation, reference)
        )
        assert not list(db.scalars(select(ModelCache).where(ModelCache.user_id == owner_id)))
        assert not list(db.scalars(select(Question).where(Question.investigation_id == first)))
        for model in (Event, Chunk, Evidence):
            assert not list(db.scalars(select(model).where(model.investigation_id == first)))


def test_clear_refuses_active_work(context):
    client, _, _ = context
    register(client)
    identifier = client.post(
        "/investigations/import",
        json={
            "domain": "Pending",
            "sources": [
                {
                    "title": "Routes",
                    "origin": "local:pending.md",
                    "content": "GET /documents returns application document records.",
                }
            ],
        },
    ).json()["id"]
    assert (
        client.post("/account/data/clear", json={"current_password": "Strong-local-password"}).status_code
        == 409
    )
    assert client.get(f"/investigations/{identifier}").status_code == 200


def test_history_is_paged_filtered_and_owner_scoped(context):
    client, factory, _ = context
    register(client)
    with factory() as db:
        owner = db.scalar(select(User))
        for index in range(50):
            db.add(
                Investigation(
                    user_id=owner.id, domain=f"Project {index:02}", mode="saved", status="completed"
                )
            )
        db.add(Investigation(user_id=owner.id, domain="atlas.example", mode="demo", status="completed"))
        other = User(email="private@example.com", username="private", password_hash="not-a-password")
        db.add(other)
        db.flush()
        db.add(Investigation(user_id=other.id, domain="Private project", mode="saved", status="completed"))
        db.commit()
    first = client.get("/investigations/history?scope=real&limit=8").json()
    second = client.get("/investigations/history?scope=real&limit=8&offset=8").json()
    assert first["total"] == 50 and first["counts"] == {"reports": 50, "reference": 0}
    assert len(first["items"]) == 8 and not {r["id"] for r in first["items"]} & {
        r["id"] for r in second["items"]
    }
    searched = client.get("/investigations/history?scope=real&q=Project%2049").json()
    assert searched["total"] == 1 and searched["items"][0]["domain"] == "Project 49"
    assert client.get("/investigations/history?scope=reference").json()["total"] == 0
    assert client.get("/investigations/history?scope=real&q=Private").json()["total"] == 0


def test_public_queue_retry_preserves_settings_before_collection(context, monkeypatch):
    from app.config import settings

    client, factory, _ = context
    register(client)
    monkeypatch.setattr(settings(), "tinyfish_enabled", True)
    monkeypatch.setattr(settings(), "tinyfish_api_key", "controlled-test-key")
    submitted = []

    def submit(identifier):
        submitted.append(identifier)
        if len(submitted) == 1:
            raise RuntimeError("Controlled queue failure.")

    monkeypatch.setattr(jobs, "enqueue", submit)
    response = client.post(
        "/investigations/web",
        json={"domain": "https://example.com/docs", "fetch_limit": 2, "search_limit": 0},
    )
    assert response.status_code == 503
    identifier = response.json()["detail"]["investigation_id"]
    retried = client.post(f"/investigations/{identifier}/resume")
    assert retried.status_code == 202 and retried.json()["id"] == identifier
    with factory() as db:
        inv = db.get(Investigation, identifier)
        assert inv.processing_options["fetch_limit"] == 2 and inv.processing_options["search_limit"] == 0
        assert inv.processing_options["queue_submission_failed"] is False
        assert not list(db.scalars(select(Evidence).where(Evidence.investigation_id == identifier)))
    assert submitted == [identifier, identifier]
