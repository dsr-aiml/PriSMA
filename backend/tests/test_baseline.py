import sqlite3

import pytest
from sqlalchemy import select

from app import jobs
from app.models import Event, Evidence, Investigation
from app.schemas import normalize_domain


@pytest.mark.parametrize(
    "domain",
    [
        "localhost",
        "127.0.0.1",
        "169.254.169.254",
        "[::1]",
        "https://user:pass@example.com",
        "example.com:8080",
        "https://example.com/private",
        "service.local",
        "x.internal",
        "example.com?query=1",
        "-bad.com",
        "file://example.com",
    ],
)
def test_reject_targets(domain):
    with pytest.raises(ValueError):
        normalize_domain(domain)


def test_normalize():
    assert normalize_domain(" HTTPS://Example.COM/ ") == "example.com"
    assert normalize_domain("bücher.de") == "xn--bcher-kva.de"


def register(client, email="owner@example.com"):
    r = client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0], "password": "Strong-local-password"},
    )
    assert r.status_code == 201
    assert "HttpOnly" in r.headers["set-cookie"]
    assert "SameSite=strict" in r.headers["set-cookie"]


def test_demo_vertical_slice(context, tmp_path):
    client, factory, queued = context
    register(client)
    r = client.post(
        "/investigations", json={"domain": "https://example.com/", "depth": "standard", "mode": "demo"}
    )
    assert r.status_code == 200
    inv_id = r.json()["id"]
    assert queued == []
    assert client.get(f"/investigations/{inv_id}/export/sqlite").status_code == 404
    detail = r.json()
    assert detail["status"] == "completed" and detail["progress"] == 100
    assert len(detail["evidence"]) == 11
    assert len(detail["report"]["nodes"]) >= 15
    assert len(detail["report"]["api_endpoints"]) == 8
    assert len(detail["report"]["entities"]) == 3
    assert detail["report"]["nodes"] and detail["report"]["edges"]
    ids = {e["id"] for e in detail["evidence"]}
    assert all(
        c["supporting_evidence_ids"] and set(c["supporting_evidence_ids"]) <= ids
        for c in detail["report"]["claims"]
    )
    assert all(set(c["contradicting_evidence_ids"]) <= ids for c in detail["report"]["claims"])
    assert detail["report"]["run"]["provider"] == "rules"
    assert len(detail["report"]["repository"]["modules"]) == 5
    assert detail["report"]["features"]
    for claim in detail["report"]["claims"]:
        for citation in claim["citations"]:
            source = next(e for e in detail["evidence"] if e["id"] == citation["evidence_id"])
            assert source["content"][citation["start"]:citation["end"]] == citation["quote"]
    assert any(field["type"] == "boolean" for field in detail["report"]["fields"])
    node_ids = {node["id"] for node in detail["report"]["nodes"]}
    assert all({edge["source"], edge["target"]} <= node_ids for edge in detail["report"]["edges"])
    assert detail["events"] == []
    with factory() as db:
        assert len(list(db.scalars(select(Evidence)))) == 0
        assert db.get(Investigation, inv_id) is None
    # Download SQLite bytes, independently check constraints, and inspect normalized counts.
    output = client.get("/reference/standard/export/sqlite")
    assert output.status_code == 200
    path = tmp_path / "report.sqlite"
    path.write_bytes(output.content)
    with sqlite3.connect(path) as sql:
        assert sql.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert sql.execute("PRAGMA foreign_key_check").fetchall() == []
        assert sql.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == len(detail["evidence"])
        assert sql.execute("SELECT COUNT(*) FROM inferred_entities").fetchone()[0] == len(detail["report"]["entities"])
        assert sql.execute("SELECT COUNT(*) FROM architecture_edges").fetchone()[0] == len(detail["report"]["edges"])
        assert sql.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == len(detail["report"]["claims"])
    doc = client.get("/reference/standard/export/json").json()
    assert doc["mode"] == "demo" and "Fictional" in doc["disclaimer"]
    assert "Fictional Atlas" in client.get("/reference/standard/export/markdown").text
    client.post("/auth/logout")
    assert client.get("/investigations").status_code == 401
    assert (
        client.post(
            "/auth/login", json={"email": "owner@example.com", "password": "Strong-local-password"}
        ).status_code
        == 200
    )
    assert client.get("/investigations").json() == []


def test_ownership_origin_and_live(context):
    client, factory, queued = context
    register(client)
    inv_id = client.post("/investigations/import", json={"domain":"example.com", "sources":[{"title":"Routes","origin":"local:routes.md","content":"GET /projects lists project records."}]}).json()["id"]
    assert client.post("/investigations", json={"domain": "example.com", "mode": "live"}).status_code == 503
    assert len(queued) == 1
    assert client.post("/investigations", json={"domain": "localhost"}).status_code == 422
    assert client.post("/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    client.post("/auth/logout")
    register(client, "other@example.com")
    assert client.get("/investigations").json() == []
    assert client.get(f"/investigations/{inv_id}").status_code == 404
    assert client.get(f"/investigations/{inv_id}/export/sqlite").status_code == 404


def test_quick_and_provider_failure(context, monkeypatch):
    client, factory, queued = context
    register(client)
    inv_id = client.post("/investigations", json={"domain": "example.com", "depth": "quick"}).json()["id"]
    assert len(client.get("/reference?depth=quick").json()["evidence"]) == 3
    assert client.get("/reference/quick/export/sqlite").status_code == 200


    def broken(_):
        raise ConnectionError("queue down")

    monkeypatch.setattr(jobs, "enqueue", broken)
    assert client.post("/investigations", json={"domain": "example.com"}).status_code == 200
    assert client.post("/investigations/import", json={"domain":"example.com", "sources":[{"title":"Routes","origin":"local:routes.md","content":"GET /projects lists project records."}]}).status_code == 503
    inv_id = client.get("/investigations").json()[0]["id"]
    assert client.get("/investigations").json()[0]["status"] == "failed"
    with factory() as db:
        inv = db.get(Investigation, inv_id)
        with pytest.raises(ValueError):
            jobs.transition(db, inv, "exploring", 10, "impossible")
        assert db.scalar(select(Event).where(Event.investigation_id == inv_id)) is not None
