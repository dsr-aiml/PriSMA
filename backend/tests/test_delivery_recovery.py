from sqlalchemy import select
from test_baseline import register
from app import delivery
from app.models import Investigation, User


def test_recovery_requires_ended_delivery_and_preserves_checkpoints(context, monkeypatch):
    client, factory, _ = context
    register(client)
    with factory() as db:
        inv = Investigation(user_id=db.scalar(select(User)).id, domain="Saved project", mode="saved", status="analyzing", progress=65, report={"nodes": [], "claims": [], "run": {"requests": 2, "coverage": {"status": "complete"}}})
        db.add(inv)
        db.commit()
        identifier = inv.id
    monkeypatch.setattr(delivery, "delivery_state", lambda _: {"available": True, "state": "active", "recoverable": False, "reason": "Active delivery"})
    assert client.post(f"/investigations/{identifier}/recover").status_code == 409
    monkeypatch.setattr(delivery, "delivery_state", lambda _: {"available": True, "state": "ended", "recoverable": True, "reason": "Ended delivery"})
    assert client.post(f"/investigations/{identifier}/recover").status_code == 200
    with factory() as db:
        saved = db.get(Investigation, identifier)
        assert saved.status == "failed" and saved.progress == 65
        assert saved.report["run"]["requests"] == 2
        assert saved.report["run"]["coverage"]["status"] == "partial"
    client.post("/auth/logout")
    register(client, "stranger@example.com")
    assert client.get(f"/investigations/{identifier}/delivery").status_code == 404
    assert client.post(f"/investigations/{identifier}/recover").status_code == 404


def test_missing_or_mixed_delivery_records_are_not_recoverable(monkeypatch):
    class Connection:
        def ping(self): pass
        def exists(self, key): return False
        def scan_iter(self, **kwargs): return iter([])
        def hget(self, *args): return b"failed"
        def close(self): pass
    connection = Connection()
    monkeypatch.setattr(delivery.Redis, "from_url", lambda *args, **kwargs: connection)
    assert not delivery.delivery_state("report")["recoverable"]
    connection.scan_iter = lambda **kwargs: iter(["first", "second"])
    connection.hget = lambda key, field: b"failed" if key == "first" else b"started"
    assert not delivery.delivery_state("report")["recoverable"]
    connection.hget = lambda *args: b"failed"
    assert delivery.delivery_state("report")["recoverable"]
