import json
import sqlite3

import httpx
from sqlalchemy import select
from test_baseline import register
from test_saved_sources import imported

from app import jobs
from app import model_gateway as gateway
from app.collection import TinyFishCollector
from app.models import User


def contract():
    return {
        "openapi": "3.1.0",
        "info": {"title": "Commerce contract", "version": "1", "license": {"name": "Apache 2.0"}},
        "servers": [{"url": "/api/v2"}],
        "paths": {"/products": {
            "get": {"summary": "List products", "responses": {"200": {"description": "A collection"}}},
            "post": {"summary": "Create a product", "operationId": "createProduct", "security": [{"api_key": []}],
                     "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Product"}}}},
                     "responses": {"201": {"description": "Created"}}},
        }},
        "components": {
            "securitySchemes": {"api_key": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
            "schemas": {
                "Category": {"type": "object", "properties": {"name": {"type": "string"}}},
                "Product": {"type": "object", "required": ["name"], "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "status": {"type": "string", "enum": ["available", "retired"]},
                    "categories": {"type": "array", "items": {"$ref": "#/components/schemas/Category"}},
                }},
            },
        },
    }


def run(client, sources, provider="rules"):
    identifier = imported(client, sources, provider)
    jobs.process(identifier)
    result = client.get(f"/investigations/{identifier}").json()
    assert result["status"] == "completed", result
    evidence = {e["id"]: e for e in result["evidence"]}
    for claim in result["report"]["claims"]:
        for citation in claim["citations"]:
            assert evidence[citation["evidence_id"]]["content"][citation["start"]:citation["end"]] == citation["quote"]
    return identifier, result


def test_contract_owner_anchors_types_refs_auth_and_exports(context, tmp_path):
    client, _, _ = context
    register(client)
    identifier, detail = run(client, [{"title": "Commerce", "origin": "https://example.com/openapi.json", "content": json.dumps(contract())}])
    report = detail["report"]
    claims = {c["id"]: c for c in report["claims"]}
    entities = {e["id"]: e["name"] for e in report["entities"]}
    name = next(f for f in report["fields"] if entities[f["entity_id"]] == "Product" and f["name"] == "name")
    claim = claims[name["claim_id"]]
    assert name["type"] == "string" and name["required"] is True
    assert claim["attributes"]["document_pointer"] == "/components/schemas/Product/properties/name"
    assert "Apache" not in claim["citations"][0]["quote"]
    assert len(report["relationships"]) == 1 and report["relationships"][0]["cardinality"] == "array"
    route = next(r for r in report["api_endpoints"] if r["method"] == "POST")
    assert '"post"' in claims[route["claim_id"]]["citations"][0]["quote"]
    assert route["servers"] == ["https://example.com/api/v2"] and route["request_body"]["required"]
    assert route["security"] == [{"api_key": []}]
    assert report["security_schemes"][0]["parameter"] == "X-API-Key"
    assert {n["kind"] for n in report["nodes"]} >= {"api", "auth", "schema"}
    assert any(e["label"] == "categories reference" for e in report["edges"])
    markdown = client.get(f"/investigations/{identifier}/export/markdown").text
    assert "### Authentication" in markdown and "array&lt;Category&gt;" in markdown
    path = tmp_path / "contract.sqlite"
    path.write_bytes(client.get(f"/investigations/{identifier}/export/sqlite").content)
    with sqlite3.connect(path) as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        attrs = json.loads(db.execute("SELECT attributes_json FROM finding_attributes WHERE claim_id=?", (name["claim_id"],)).fetchone()[0])
        assert attrs["required"] is True
        assert json.loads(db.execute("SELECT value FROM metadata WHERE key='contract_details'").fetchone()[0])["security_schemes"]


def test_markdown_escaped_spec_is_recovered_with_original_retained(context):
    client, _, _ = context
    register(client)
    raw = json.dumps(contract()).replace("api_key", r"api\_key")
    _, result = run(client, [{"title": "Rendered specification", "origin": "https://example.com/openapi.json", "format": "markdown", "content": raw}])
    assert result["evidence"][0]["source_type"] == "openapi"
    assert result["evidence"][0]["original_content"] == raw
    assert len(result["report"]["api_endpoints"]) == 2


def test_distinct_contracts_do_not_merge_same_named_entities(context):
    client, _, _ = context
    register(client)
    first, second = contract(), contract()
    first["info"]["title"] = "Catalog API"
    second["info"]["title"] = "Admin API"
    second["components"]["schemas"]["Product"]["properties"]["name"]["type"] = "integer"
    _, result = run(client, [{"title": "Contract", "origin": f"local:{index}/openapi.json", "content": json.dumps(doc)} for index, doc in enumerate((first, second))])
    report = result["report"]
    products = [e for e in report["entities"] if e["name"] == "Product"]
    assert len(products) == 2 and {e["context"] for e in products} == {"Catalog API", "Admin API"}
    assert len([n for n in report["nodes"] if n["label"] == "Public API"]) == 2
    types = {next(f["type"] for f in report["fields"] if f["entity_id"] == e["id"] and f["name"] == "name") for e in products}
    assert types == {"string", "integer"}


def test_public_product_markup_yields_resources_forms_and_structured_data(context):
    client, _, _ = context
    register(client)
    html = '''<!doctype html><html><head><title>Example store</title>
    <meta name="generator" content="Commerce Platform 2">
    <script src="/_next/static/app.js"></script><script src="https://assets.example.net/client.js"></script>
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Desk Lamp","offers":{"price":"29.00","priceCurrency":"USD"}}</script>
    </head><body><h1>Desk Lamp</h1><form action="/search" method="get"><input name="q"></form></body></html>'''
    _, result = run(client, [{"title": "Product", "origin": "https://store.example.com/product/lamp", "format": "html", "content": html}])
    report = result["report"]
    assert {n["label"] for n in report["nodes"]} >= {"Web client", "Client assets", "Delivery origin assets.example.net", "Form store.example.com/search"}
    assert {t["name"] for t in report["technologies"]} >= {"Next.js", "Commerce Platform 2"}
    assert report["surface_records"][0]["structured_data"]["offers"]["price"] == "29.00"
    assert {e["label"] for e in report["edges"]} >= {"loads scripts", "declares form"}
    assert report["api_endpoints"][0]["contract_kind"] == "form_action"
    assert not any("database" in n["kind"] for n in report["nodes"])


def test_generic_readme_stack_is_not_limited_by_model_response_count(context):
    client, _, _ = context
    register(client)
    readme = "# Example project\n## Tech Stack\n**Frontend:**\n* React (Vite)\n* Tailwind CSS v4\n**Backend:**\n* Node.js & Express\n* MongoDB & Mongoose\n* Vendor API\n**DevOps:**\n* Docker\n* AWS EC2\n"
    _, result = run(client, [{"title": "README", "origin": "local:Project/README.md", "content": readme}])
    report = result["report"]
    assert {t["name"] for t in report["technologies"]} >= {"React", "Vite", "Tailwind CSS", "Node.js", "Express", "MongoDB", "Mongoose", "Vendor API", "Docker", "AWS EC2"}
    assert {n["label"] for n in report["nodes"]} == {"Frontend", "Backend", "Vendor API"}
    assert len(report["edges"]) == 1
    assert next(t for t in report["technologies"] if t["name"] == "Tailwind CSS")["declarations"][0]["version"] == "4"


def test_model_description_cannot_expand_beyond_selected_units(context, monkeypatch):
    client, _, _ = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **k: "controlled:model")

    def generate(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        key = next(k for k, v in packet.items() if "Billing API" in v)
        return {"findings": [{"kind": "component", "name": "Billing API", "detail": "Frontend and backend both use Redis internally.", "evidence": [key]}]}, {}

    monkeypatch.setattr(gateway, "generate", generate)
    _, result = run(client, [{"title": "Billing", "origin": "local:billing.md", "content": "The Billing API service handles payment requests from the backend service."}], "ollama")
    assert "Redis" not in result["report"]["claims"][0]["description"]
    assert "handles payment requests" in result["report"]["claims"][0]["description"]


def test_rejected_connection_has_a_recorded_reason(context, monkeypatch):
    client, _, _ = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **k: "controlled:model")

    def generate(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        key = next(iter(packet))
        if prompt.startswith("Extract at most 3 connection"):
            return {"findings": [{"kind": "connection", "name": "calls", "source": "Gateway API", "target": "Hidden database", "detail": "Gateway calls a hidden database.", "evidence": [key]}]}, {}
        return {"findings": [{"kind": "component", "name": name, "detail": "A source-declared service.", "evidence": [key]} for name in ("Gateway API", "Worker")]}, {}

    monkeypatch.setattr(gateway, "generate", generate)
    _, result = run(client, [{"title": "Services", "origin": "local:services.md", "content": "The Gateway API service calls the Worker service to process requests."}], "ollama")
    record = result["report"]["run"]
    assert record["rejected_candidates"] == sum(record["rejection_reasons"].values()) == 1
    assert record["rejections"][0]["stage"] == "relationship review"
    assert not result["report"]["edges"]


def test_model_connection_resolves_unique_declared_component_context(context, monkeypatch):
    client, _, _ = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **k: "controlled:model")

    def generate(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        key = next(k for k, value in packet.items() if "Frontend application calls Backend" in value)
        if not prompt.startswith("Extract at most 3 connection"):
            return {"findings": []}, {}
        return {"findings": [{"kind": "connection", "name": "calls", "source": "Frontend", "target": "Backend", "detail": "Calls declared by the source.", "evidence": [key]}]}, {}

    monkeypatch.setattr(gateway, "generate", generate)
    text = "**Frontend:**\n* React\n**Backend:**\n* Express\n\nThe Frontend application calls Backend to submit requests."
    _, result = run(client, [{"title": "Architecture", "origin": "local:architecture.md", "content": text}], "ollama")
    assert result["report"]["edges"][0]["context"] == "documented application"


def test_direct_spec_supersedes_rendered_version_without_double_source_count(context, monkeypatch):
    from app import public_files
    client, factory, _ = context
    register(client)
    monkeypatch.setenv("TINYFISH_ENABLED", "true")
    monkeypatch.setenv("TINYFISH_API_KEY", "test")
    gateway.settings.cache_clear()
    class Budget:
        def reserve(self, *a): pass
    requests = []
    def transport(request):
        requests.append(request.method)
        raw = json.dumps(contract()).replace("api_key", r"api\_key")
        return httpx.Response(200, json={"results": [{"url": "https://example.com/openapi.json", "text": raw}]})
    def read(url, **kwargs):
        kwargs["before_request"]()
        return json.dumps(contract()).encode(), url, "application/json"
    monkeypatch.setattr(public_files, "read_public", read)
    with factory() as db:
        collector = TinyFishCollector(db, db.scalar(select(User)).id, budget=Budget(), transport=httpx.MockTransport(transport), analysis_provider="rules", options={"public_files": True})
        sources = collector.collect("example.com", lambda *a: None, seed_url="https://example.com/openapi.json")
        assert len(sources) == 1 and requests == ["POST"]
        assert sources[0][0].format == "openapi"
        assert sources[0][2]["alternate_representations"]
        assert collector.record["search_attempts"] == 0 and collector.record["status"] == "complete"
