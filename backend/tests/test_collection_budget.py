"""Focused cost and selection regressions; every transport is controlled."""

import json

import httpx
from sqlalchemy import select
from test_baseline import register
from test_collection_scaffold import Budget, enable
from test_saved_sources import sample_sources

from app import jobs
from app import model_gateway as gateway
from app.collection import TinyFishCollector
from app.models import User


def economical(monkeypatch):
    cfg = enable(monkeypatch)
    monkeypatch.setattr(cfg, "tinyfish_searches_per_run", 1)
    monkeypatch.setattr(cfg, "tinyfish_fetch_attempts_per_run", 6)


def test_document_service_does_not_crawl_its_runtime_links(context, monkeypatch):
    client, factory, _ = context
    register(client)
    economical(monkeypatch)
    fetched = []
    root, legacy = "https://example.com/", "https://example.com/legacy"
    endpoints = [root + p for p in ("ip", "uuid", "headers", "get", "anything", "gzip", "status/418")]
    searches = []

    def transport(request):
        if request.method == "GET":
            searches.append(request)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": legacy},
                        {"url": "http://example.com/"},
                        {"url": "http://eu.example.com/"},
                        *[{"url": u} for u in endpoints],
                    ]
                },
            )
        url = json.loads(request.content)["urls"][0]
        fetched.append(url)
        assert url in (root, legacy), "Runtime links must not consume Fetch allowance"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "final_url": url,
                        "text": "HTTP client testing service documentation.\nExample:\nServer: nginx/0.7.67",
                        "links": endpoints + [legacy],
                    }
                ]
            },
        )

    with factory() as db:
        collector = TinyFishCollector(
            db,
            db.scalar(select(User)).id,
            budget=Budget(),
            transport=httpx.MockTransport(transport),
            analysis_provider="rules",
        )
        collector.collect("example.com", lambda *_: None)
        assert fetched == [root, legacy] and len(searches) == 1
        assert collector.record["visited_urls"] == 2
        assert collector.record["url_attempts"] == 2
        assert collector.record["skipped_navigation_links"] >= 7
        assert "No additional document candidates" in collector.record["stop_reason"]
        assert collector.record["limits"] == {"searches": 1, "url_attempts": 6}


def test_supplied_specification_stops_collection_before_search(context, monkeypatch):
    client, factory, _ = context
    register(client)
    economical(monkeypatch)
    requests = []

    def transport(request):
        assert request.method == "POST", "No search is required after finding an explicit specification"
        url = json.loads(request.content)["urls"][0]
        requests.append(url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "final_url": url,
                        "text": sample_sources()[0]["content"]
                        if url.endswith("spec.json")
                        else "Technical documentation for a public API. Specifications are linked below.",
                        "links": ["/spec.json", "/docs/guide", "/pricing"],
                    }
                ]
            },
        )

    with factory() as db:
        collector = TinyFishCollector(
            db,
            db.scalar(select(User)).id,
            budget=Budget(),
            transport=httpx.MockTransport(transport),
            analysis_provider="rules",
        )
        sources = collector.collect("example.com", lambda *_: None, seed_url="https://example.com/spec.json")
        assert requests == ["https://example.com/spec.json"]
        assert sources[-1][0].format == "openapi"
        assert collector.record["search_attempts"] == 0
        assert collector.record["scope"] == "supplied_specification"


def test_six_attempt_budget_includes_retry_and_cached_visits(context, monkeypatch):
    client, factory, _ = context
    register(client)
    economical(monkeypatch)
    calls = []
    timed_out = set()

    def transport(request):
        assert request.method == "POST"
        url = json.loads(request.content)["urls"][0]
        calls.append(url)
        if url.endswith("/docs/0") and url not in timed_out:
            timed_out.add(url)
            return httpx.Response(200, json={"results": [], "errors": [{"error": "timeout"}]})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "text": "Architecture documentation for the API service. Source: " + url,
                        "links": [f"https://example.com/docs/{i}" for i in range(20)],
                    }
                ]
            },
        )

    with factory() as db:
        owner = db.scalar(select(User)).id
        collector = TinyFishCollector(db, owner, budget=Budget(), transport=httpx.MockTransport(transport))
        collector.collect("example.com", lambda *_: None)
        assert len(calls) == 6 and collector.record["url_attempts"] == 6
        assert collector.record["visited_urls"] == 5
        before = len(calls)
        repeated = TinyFishCollector(db, owner, budget=Budget(), transport=httpx.MockTransport(transport))
        repeated.collect("example.com", lambda *_: None)
        assert repeated.record["visited_urls"] == 6
        assert repeated.record["cache_hits"] == 5
        assert len(calls) - before == 1  # One additional page within the six-URL ceiling.


def test_response_json_is_not_a_documentation_source(context, monkeypatch):
    client, factory, _ = context
    register(client)
    economical(monkeypatch)

    def transport(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": []})
        url = json.loads(request.content)["urls"][0]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "text": json.dumps({"origin": "198.51.100.1", "headers": {"Server": "nginx"}})
                        if url.endswith("health")
                        else "Architecture documentation for the API service.",
                        "links": ["/api/health"],
                    }
                ]
            },
        )

    with factory() as db:
        collector = TinyFishCollector(
            db, db.scalar(select(User)).id, budget=Budget(), transport=httpx.MockTransport(transport)
        )
        sources = collector.collect("example.com", lambda *_: None)
        assert len(sources) == 1
        assert any(o.get("reason") == "non_specification_json" for o in collector.record["outcomes"])


def test_missing_local_model_stops_before_creating_collector(context, monkeypatch):
    from app import collection

    client, _, _ = context
    register(client)
    economical(monkeypatch)
    monkeypatch.setattr(gateway, "_request", lambda *a, **kw: {"models": []})
    constructed = []
    monkeypatch.setattr(collection, "TinyFishCollector", lambda *a, **kw: constructed.append(kw))
    response = client.post("/investigations/web", json={"domain": "example.com", "provider": "ollama"})
    assert response.status_code == 202
    inv_id = response.json()["id"]
    jobs.process(inv_id)
    detail = client.get(f"/investigations/{inv_id}").json()
    assert detail["status"] == "failed" and "has not been pulled" in detail["error"]
    assert not constructed and not detail["evidence"]
