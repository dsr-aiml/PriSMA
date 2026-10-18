"""Real-report regressions use controlled documents; no provider calls."""

import json

import httpx
import pytest
from sqlalchemy import select
from test_baseline import register
from test_collection_scaffold import Budget, enable
from test_saved_sources import imported, sample_sources

from app import jobs
from app.collection import TinyFishCollector, document_exclusion
from app.intelligence import Finding, candidate_problem
from app.models import User


def test_payload_endpoints_are_not_documents():
    for origin in ("https://example.com", "https://docs.other.org"):
        for path in (
            "/base64/aGVsbG8=",
            "/echo/hello",
            "/redirect-to?url=https://elsewhere.org",
            "/pages/" + "a" * 129,
            "/render?html=%3Ch1%3EHello",
            "/assets/logo.png",
            "/api/{resource}",
        ):
            assert document_exclusion(origin + path)
        for path in ("/docs/base64", "/api/reference", "/openapi.json", "/pricing?locale=en", "/docs/api/v1"):
            assert document_exclusion(origin + path) is None


def test_discovery_filters_before_fetch_and_prioritizes_specs(context, monkeypatch):
    client, factory, _ = context
    register(client)
    enable(monkeypatch)
    fetched = []
    payload = "https://example.com/base64/" + "a" * 180
    spec = "https://example.com/spec.json"

    def transport(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": payload},
                        *[{"url": f"https://example.com/blog/{i}"} for i in range(27)],
                        {"url": "https://example.com/render?html=hello"},
                        {"url": spec},
                    ]
                },
            )
        url = json.loads(request.content)["urls"][0]
        fetched.append(url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "final_url": url,
                        "title": "Public documentation",
                        "text": sample_sources()[0]["content"]
                        if url == spec
                        else "HTTP client testing documentation.\nExample response:\nServer: nginx/0.7.67",
                        "links": [payload, "https://example.com/echo/hello"],
                    }
                ]
            },
        )

    with factory() as db:
        collector = TinyFishCollector(
            db, db.scalar(select(User)).id, budget=Budget(), transport=httpx.MockTransport(transport)
        )
        sources = collector.collect("example.com", lambda *_: None)
        assert fetched[:2] == ["https://example.com/", spec]
        assert len(fetched) == 2  # Background articles no longer consume a fallback Fetch.
        assert not any(document_exclusion(url) for url in fetched)
        assert any(source.format == "openapi" for source, _, _ in sources)
        assert collector.record["excluded_discovery_urls"] >= 3
        assert any(o.get("reason") == "article_tutorial_or_example" for o in collector.record["outcomes"])
        assert collector.record["status"] == "partial"


def test_same_domain_payload_redirect_is_rejected(context, monkeypatch):
    client, factory, _ = context
    register(client)
    enable(monkeypatch)

    def transport(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": [{"url": "https://example.com/redirect"}]})
        url = json.loads(request.content)["urls"][0]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": url,
                        "final_url": "https://example.com/base64/aGVsbG8="
                        if url.endswith("redirect")
                        else url,
                        "text": "Public API documentation for HTTP client testing.",
                        "links": [],
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
        assert any(o.get("reason") == "generated_content_endpoint" for o in collector.record["outcomes"])


@pytest.mark.parametrize("format", ["text", "markdown", "html"])
def test_document_headers_are_not_deployed_technology(context, format):
    client, _, _ = context
    register(client)
    content = (
        "Example HTTP response:\nServer: nginx/0.7.67\nX-Powered-By: Express\nDocumentation example only."
    )
    if format == "html":
        content = "<pre>" + content + "</pre>"
    inv_id = imported(
        client,
        sources=[
            {
                "title": "HTTP reference",
                "origin": "https://example.com/legacy",
                "format": format,
                "content": content,
            }
        ],
    )
    jobs.process(inv_id)
    report = client.get(f"/investigations/{inv_id}").json()["report"]
    assert not report["technologies"] and not report["nodes"]
    assert report["summary"].startswith("1 source document supports 0 findings.")
    assert report["run"]["explicit_specifications"] == 0
    from app.intelligence import PARSER_VERSION
    assert report["run"]["parser_version"] == PARSER_VERSION


def test_imported_plain_text_declarations_remain_supported(context):
    client, _, _ = context
    register(client)
    inv_id = imported(
        client,
        sources=[
            {
                "title": "Supplied technology inventory",
                "origin": "local:inventory.txt",
                "format": "text",
                "content": "Technology: PostgreSQL\nThis inventory is supplied for assessment.",
            }
        ],
    )
    jobs.process(inv_id)
    report = client.get(f"/investigations/{inv_id}").json()["report"]
    assert report["technologies"][0]["name"] == "PostgreSQL"
    assert report["summary"].startswith("1 source document supports 1 finding.")


def test_semantic_header_quote_does_not_establish_adoption():
    finding = Finding(
        kind="technology",
        name="nginx",
        detail="nginx serves the target",
        citations=[{"passage": "p1", "quote": "Server: nginx/0.7.67"}],
    )
    assert candidate_problem(finding, [{"role": "supporting", "quote": "Server: nginx/0.7.67"}], [])
