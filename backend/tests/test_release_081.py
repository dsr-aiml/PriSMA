"""0.8.1 regressions: bounded public evidence and hosted Research recovery."""

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from app import jobs, research_budget
from app import model_gateway as gateway
from app.intelligence import import_evidence
from app.model_profiles import snapshot, using
from app.models import Evidence, Investigation
from app.product_inventory import product_inventory
from app.public_files import PublicFileError, read_public
from app.public_surface import surface_page
from app.read_operations import validate_read_operation
from app.resource_policy import resource_format, resource_priority, resource_role, safe_control
from app.schemas import ImportedSource
from app.web_observation import append_response, new_snapshot
from sqlalchemy import select
from test_baseline import register
from test_saved_sources import imported


def observer_module():
    path = Path(__file__).resolve().parents[2] / "browser/service.py"
    spec = importlib.util.spec_from_file_location("prisma_observer_081", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "mime,context,body,expected",
    [
        ("application/javascript", "", "(()=>{})()", "javascript"),
        ("text/plain", "script", "(()=>{})()", "javascript"),
        ("text/plain", "", "export const client = {}", "javascript"),
        ("application/json", "script", '{"items":[]}', "json"),
        ("application/xml", "", "<urlset/>", "xml"),
    ],
)
def test_extensionless_resources_use_mime_context_and_content(mime, context, body, expected):
    assert resource_format("https://assets.example.net/asset/72", mime, body, context) == expected


def test_application_entry_precedes_vendor_and_tracking_even_on_cdn():
    rows = [
        {"url": "https://cdn.example.net/vendor.js", "kind": "script"},
        {"url": "https://cdn.example.net/analytics.js", "kind": "script"},
        {"url": "https://cdn.example.net/main.js", "kind": "script"},
        {"url": "https://example.com/openapi.json", "kind": "document"},
    ]
    assert [r["url"].rsplit("/", 1)[-1] for r in sorted(rows, key=resource_priority)] == [
        "openapi.json",
        "main.js",
        "vendor.js",
        "analytics.js",
    ]
    assert (
        resource_role(rows[2]["url"], mime="application/javascript", content="/* @license React */")
        == "application"
    )
    assert resource_role(rows[0]["url"], context="script") == "dependency"


@pytest.mark.parametrize(
    "body",
    [
        {"query": "mutation { deleteProject(id: 1) { id } }"},
        {"query": "subscription { notifications { id } }"},
        {"query": "{ __schema { types { name } } }"},
        {"query": '{ projects(token:"private") { id } }'},
        {"query": "query($token:String){ projects { id } }", "variables": {"token": "private"}},
        {"query": "{ projects { id } }", "extensions": {"persistedQuery": {"sha256Hash": "x"}}},
        {"query": "query One{projects{id}} query Two{users{id}}"},
        {"query": "{projects{...A}} fragment A on Project {...B} fragment B on Project {...A}"},
        {"query": "{projects{...Missing}}"},
        {"query": "{projects{id}}", "operationName": []},
    ],
)
def test_read_operation_rejects_mutation_credentials_and_ambiguous_documents(body):
    with pytest.raises(ValueError):
        validate_read_operation(json.dumps(body))


def test_valid_query_is_pinned_and_has_no_forwarded_credentials():
    payload = json.dumps(
        {
            "query": "query Catalog($limit:Int){products(limit:$limit){id title}}",
            "variables": {"limit": 2},
            "operationName": "Catalog",
        }
    )
    record = validate_read_operation(payload)
    assert record["operation"] == "Catalog" and set(record["fields"]) == {"products", "id", "title"}
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST" and request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.com"
        assert not {"authorization", "cookie", "x-api-key"} & request.headers.keys()
        assert request.content.decode() == payload
        return httpx.Response(200, json={"data": {"products": []}})

    read_public(
        "https://example.com/graphql",
        allowed_hosts={"example.com"},
        method="POST",
        request_body=payload,
        resolver=lambda _: "93.184.216.34",
        transport=httpx.MockTransport(handler),
    )
    assert len(calls) == 1
    with pytest.raises(PublicFileError, match="redirect"):
        read_public(
            "https://example.com/graphql",
            allowed_hosts={"example.com"},
            method="POST",
            request_body=payload,
            resolver=lambda _: "93.184.216.34",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(307, headers={"location": "http://127.0.0.1/private"})
            ),
        )


def test_safe_disclosures_exclude_form_and_action_controls():
    assert safe_control("Product details", "tab")
    assert safe_control("Navigation", "button", expanded="false")
    assert not safe_control("Delete account", "button", expanded="false")
    assert not safe_control("Buy now", "tab")
    assert not safe_control("Continue", "button")


@pytest.mark.parametrize(
    "title,description,field,route",
    [
        ("Paper catalog", "Find and organize published research papers.", "Search papers", "/catalog"),
        ("Tool documentation", "Build services with a documented public API.", "Search docs", "/docs"),
        ("Workshop store", "Browse handmade workshop products.", "Product search", "/products"),
        ("Team workspace", "Organize public projects and shared work.", "Project name", "/projects"),
    ],
)
def test_product_inventory_keeps_inspection_and_source_spans(title, description, field, route):
    html = f'<html><head><title>{title}</title><meta name="description" content="{description}"></head><body><a href="{route}">Explore</a><a href="/account">Account</a><form aria-label="Search" action="/search"><label for="q">{field}</label><input id="q" name="q" value="never-retain-this"/></form><button role="tab">Details</button><p>Unlimited exports are included in the Pro plan.</p></body></html>'
    row = surface_page(html, "https://example.com/")
    assert row["forms"][0]["fields"][0]["label"] == field
    assert "never-retain-this" not in json.dumps(row)
    data = new_snapshot("https://example.com/")
    append_response(data, data["url"], data["url"], "text/html", {}, 200, html)
    data["surface"][0].update(rendered=True, status="inspected")
    content = json.dumps(data, ensure_ascii=False, indent=2)
    source = SimpleNamespace(
        id="one",
        source_type="json",
        content=content,
        source_url="local:page.json",
        signals={},
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )
    product = product_inventory({}, [source])
    assert product["description"] == description
    assert next(p for p in product["pages"] if p["url"].endswith(route))["status"] == "referenced"
    assert product["workflows"][0]["execution"] == "not_submitted"
    assert product["features"] and product["open_questions"]
    for group in ("pages", "workflows", "features", "purpose"):
        for record in product[group]:
            for ref in record["citations"]:
                assert content[ref["start"] : ref["end"]] == ref["quote"]


def test_browser_launch_failure_keeps_prefetched_application_and_static_page(monkeypatch):
    observer = observer_module()

    def read(url, **kwargs):
        kwargs["before_request"]()
        if url.endswith("/main.js"):
            return b'fetch("/catalog");', url, "application/javascript", {}, 200
        return (
            b'<html><script src="/main.js"></script><title>Catalog</title></html>',
            url,
            "text/html",
            {},
            200,
        )

    class Runtime:
        async def __aenter__(self):
            return SimpleNamespace(
                chromium=SimpleNamespace(launch=AsyncMock(side_effect=RuntimeError("private failure text")))
            )

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(observer, "read_public", read)
    monkeypatch.setattr(observer, "async_playwright", Runtime)
    checkpoints = []
    result = asyncio.run(
        observer.capture(observer.Observation(url="https://example.com/"), checkpoints.append)
    )
    assert result["pages"][0]["rendered"] is False and result["scripts"][0]["content"] == 'fetch("/catalog");'
    assert result["snapshot"]["coverage"]["failures"][-1]["code"] == "browser_startup"
    assert result["snapshot"]["coverage"]["status"] == "partial" and len(checkpoints) == 2
    assert "private failure text" not in json.dumps(result)


def test_delivery_budget_discards_dependencies_before_application():
    observer = observer_module()
    result = {
        "snapshot": new_snapshot("https://example.com/"),
        "pages": [],
        "source_maps": [],
        "scripts": [
            {
                "url": "https://example.com/vendor.js",
                "content": "v" * 6_000_000,
                "resource_role": "dependency",
            },
            {
                "url": "https://example.com/main.js",
                "content": "a" * 5_000_000,
                "resource_role": "application",
            },
        ],
    }
    trimmed = observer.bound_result(result)
    assert len(trimmed["scripts"]) == 1 and trimmed["scripts"][0]["resource_role"] == "application"
    assert len(result["scripts"]) == 2 and trimmed["snapshot"]["coverage"]["scripts_retained"] == 1


def test_real_chromium_probe_failure_is_unavailable(monkeypatch):
    observer = observer_module()
    monkeypatch.setattr(observer.os, "setsid", lambda: None)

    async def fail():
        raise RuntimeError("private path")

    monkeypatch.setattr(observer, "probe", fail)
    results = []
    observer.probe_process(SimpleNamespace(put=results.append))
    assert results[0]["status"] == "unavailable" and results[0]["code"] == "browser_startup"
    assert "private path" not in json.dumps(results)


def test_mixed_origin_append_uses_batch_metadata_and_preserves_report(context):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    with factory() as db:
        inv = db.get(Investigation, identifier)
        original = json.dumps(inv.report, sort_keys=True)
        before = list(db.scalars(select(Evidence).where(Evidence.investigation_id == identifier)))
        source = ImportedSource(
            title="Extra module",
            origin="local:extra/main.py",
            format="python",
            content="def added():\n    return True\n",
        )
        import_evidence(
            db,
            inv,
            [source],
            [source.content],
            [
                {
                    "collection_method": "public_repository",
                    "repository_url": "https://github.com/example/project",
                }
            ],
        )
        db.commit()
        added = list(db.scalars(select(Evidence).where(Evidence.investigation_id == identifier)))
        assert len(added) == len(before) + 1 and added[-1].collection_method == "public_repository"
        assert json.dumps(inv.report, sort_keys=True) == original


def test_503_retries_are_bounded_private_and_recorded(monkeypatch, hosted_query):
    monkeypatch.setattr(research_budget, "admit", lambda *a: 0)
    monkeypatch.setattr(gateway.time, "sleep", lambda _: None)
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise gateway.ModelFailure(
                "Temporary service issue.", code="service_unavailable", http_status=503, retry_after="0"
            )
        return {"usageMetadata": {}}

    monkeypatch.setattr(gateway, "_request_once", request)
    with using({"model_settings": snapshot("gemini", purpose="query")}):
        value = gateway._request(
            "POST", "https://generativelanguage.googleapis.com/v1beta/models/example:generateContent", json={}
        )
    assert len(calls) == 3 and len(value["_prisma_transport"]["attempts"]) == 3
    assert [a["status"] for a in value["_prisma_transport"]["attempts"]] == ["failed", "failed", "success"]


@pytest.mark.parametrize(
    "code,status",
    [
        ("daily_quota", 429),
        ("access_denied", 403),
        ("timeout", None),
        ("invalid_json", None),
        ("service_unavailable", 504),
    ],
)
def test_nonretryable_failures_stop_immediately(monkeypatch, hosted_query, code, status):
    monkeypatch.setattr(research_budget, "admit", lambda *a: 0)
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        raise gateway.ModelFailure("Controlled failure", code=code, http_status=status)

    monkeypatch.setattr(gateway, "_request_once", request)
    with using({"model_settings": snapshot("gemini", purpose="query")}):
        with pytest.raises(gateway.ModelFailure) as error:
            gateway._request(
                "POST",
                "https://generativelanguage.googleapis.com/v1beta/models/example:generateContent",
                json={},
            )
    assert len(calls) == 1 and error.value.transport["attempts"][0]["code"] == code


def test_pacing_reservation_waits_then_admits_and_fails_closed(monkeypatch):
    now = [0.0]
    delays = iter([".5", "0"])
    connection = SimpleNamespace(eval=lambda *a: next(delays))

    def sleep(value):
        now[0] += value

    assert research_budget.admit(100, 10, connection=connection, sleeper=sleep, clock=lambda: now[0]) == 0.55
    broken = SimpleNamespace(eval=lambda *a: (_ for _ in ()).throw(ConnectionError("private")))
    with pytest.raises(gateway.ModelFailure) as error:
        research_budget.admit(100, 10, connection=broken, clock=lambda: 0)
    assert error.value.code == "scheduling_unavailable"


def test_large_query_context_prioritizes_useful_application_over_vendor():
    from app.evidence_units import source_units
    from app.query_engine import question_units, rank_passages

    chunks = []
    evidence = []
    for index in range(30):
        eid = f"app-{index}"
        text = (
            f"Module {index} implements public project search, filters and project export workflows. " * 13
        )[:1000]
        chunks.append(SimpleNamespace(id=eid, evidence_id=eid, start=0, end=len(text), content=text))
        evidence.append(
            SimpleNamespace(
                id=eid, source_url=f"local:src/{index}.ts", signals={"resource_role": "application"}
            )
        )
    for index in range(10):
        eid = f"vendor-{index}"
        text = "project " * 125
        chunks.append(SimpleNamespace(id=eid, evidence_id=eid, start=0, end=len(text), content=text))
        evidence.append(
            SimpleNamespace(
                id=eid, source_url=f"local:vendor/{index}.js", signals={"resource_role": "dependency"}
            )
        )
    ranked = rank_passages(chunks, "Explain project search and export workflows", evidence=evidence, limit=30)
    assert all(not chunk.evidence_id.startswith("vendor") for _, chunk in ranked)
    units = question_units(
        [chunk for _, chunk in ranked], "Explain project workflows", maximum=128, character_budget=50000
    )
    assert len(units) > 32 and sum(len(u.content) for u in units.values()) > 15000
    assert all(12 <= len(u.content) <= 500 for u in units.values())
    assert len(source_units(chunks[:1])) > 1


def test_source_map_client_calls_keep_application_origin_and_exact_span():
    from app.public_code import public_code_facts, source_map_sources

    text = json.dumps(
        {
            "version": 3,
            "sources": ["../src/client.ts"],
            "sourcesContent": ['export async function list(){ return fetch("/catalog"); }'],
            "mappings": "",
        }
    )
    source, metadata = next(
        source_map_sources(text, "https://cdn.example.net/app.js.map", page_url="https://example.com/")
    )
    item = SimpleNamespace(
        id="map-source",
        source_type=source.format,
        source_url=source.origin,
        content=source.content,
        signals=metadata,
    )
    facts = list(public_code_facts(item))
    route = next(row for row in facts if row["kind"] == "endpoint")
    assert route["path"] == "/catalog" and route["attributes"]["address"] == "https://example.com/catalog"
    assert source.content[route["offset"] : route["offset"] + len(route["quote"])] == route["quote"]
