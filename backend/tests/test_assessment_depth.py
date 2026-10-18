import json
from contextlib import nullcontext

import httpx
import pytest

from app import jobs
from app import model_gateway as gateway
from app.evidence_units import embedding_segments
from app.intelligence import normalize_source
from app.public_files import PublicFileError, read_public, repository_archive
from app.schemas import ImportedSource


def account(client):
    assert (
        client.post(
            "/auth/register",
            json={"username": "depth_test", "email": "depth@example.com", "password": "assessment-password"},
        ).status_code
        == 201
    )


def source(path, text):
    return {"title": path, "origin": "local:" + path, "format": "text", "content": text}


def assess(client, sources, provider="rules"):
    response = client.post(
        "/investigations/import",
        json={"domain": "Repository assessment", "provider": provider, "sources": sources},
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def detail(client, identifier):
    return client.get("/investigations/" + identifier).json()


def test_nested_mounts_models_contexts_and_export(context):
    client, _, _ = context
    account(client)
    sources = [
        source(
            "Project/Backend/package.json",
            json.dumps(
                {
                    "name": "backend",
                    "dependencies": {"express": "^5", "mongoose": "^8"},
                    "devDependencies": {"vitest": "^3"},
                }
            ),
        ),
        source("Project/Backend/app.js", 'import parent from "./parent.js";\napp.use("/api", parent);'),
        source(
            "Project/Backend/parent.js", 'import child from "./routes.js";\nrouter.use("/documents", child);'
        ),
        source(
            "Project/Backend/routes.js",
            'import path from "node:path";\nrouter.post("/upload", handler);\n// router.get("/invented", fake);',
        ),
        source(
            "Project/Backend/models.js",
            'const document = new mongoose.Schema({name: String, owner: {type: mongoose.Schema.Types.ObjectId, ref: "User"}, tags: [String]});\nconst user = new mongoose.Schema({email: {type: String, required: true}});\nmongoose.model("Document", document);\nmongoose.model("User", user);',
        ),
        source(
            "Project/compose.prod.yml",
            "services:\n  api:\n    image: node:22\n    depends_on: [database]\n  database:\n    image: mongo:8\n",
        ),
        source(
            "Project/compose.dev.yml",
            "services:\n  api:\n    image: node:22\n    depends_on: [database]\n  database:\n    image: mongo:8\n",
        ),
    ]
    identifier = assess(client, sources)
    jobs.process(identifier)
    record = detail(client, identifier)
    report = record["report"]
    routes = report["api_endpoints"]
    assert [(row["method"], row["path"]) for row in routes] == [("POST", "/api/documents/upload")]
    route_claim = next(c for c in report["claims"] if c["id"] == routes[0]["claim_id"])
    assert len(route_claim["supporting_evidence_ids"]) == 3
    assert {row["name"] for row in report["entities"]} == {"Document", "User"}
    assert {row["name"] for row in report["fields"]} == {"name", "owner", "tags", "email"}
    assert len(report["relationships"]) == 1
    assert {"development", "production", "repository"} <= set(report["contexts"])
    assert len([n for n in report["nodes"] if n["label"] == "api"]) == 2
    assert not {"node:path", "path"} & {t["name"] for t in report["technologies"]}
    assert len([t for t in report["technologies"] if t["name"] == "node:22"]) == 1
    assert any(edge["label"] == "backend implements backend API" for edge in report["edges"])
    evidence = {e["id"]: e["content"] for e in record["evidence"]}
    for claim in report["claims"]:
        for citation in claim["citations"]:
            assert evidence[citation["evidence_id"]][citation["start"] : citation["end"]] == citation["quote"]
    for format in ("json", "markdown", "sqlite"):
        assert client.get(f"/investigations/{identifier}/export/{format}").status_code == 200


def test_model_selects_ids_and_rejects_unresolved_units(context, monkeypatch):
    client, _, _ = context
    account(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **k: "test:units")

    def generate(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        key = next(k for k, v in packet.items() if "React" in v)
        assert key in schema["$defs"]["AnchoredFinding"]["properties"]["evidence"]["items"]["enum"]
        return {
            "findings": [
                {
                    "kind": "technology",
                    "name": "React",
                    "detail": "Frontend framework declared in the sources.",
                    "evidence": [key],
                },
                {
                    "kind": "technology",
                    "name": "MongoDB",
                    "detail": "Database declaration in the sources.",
                    "evidence": ["u999"],
                },
            ]
        }, {}

    monkeypatch.setattr(gateway, "generate", generate)
    identifier = assess(
        client,
        [
            source(
                "architecture.md",
                "## Client architecture\nThe frontend application uses React for its interface.",
            )
        ],
        "ollama",
    )
    jobs.process(identifier)
    report = detail(client, identifier)["report"]
    assert [t["name"] for t in report["technologies"]] == ["React"]
    assert report["run"]["processed_passages"] == 1 and report["run"]["rejected_candidates"] == 1


def test_embedding_preserves_unicode_and_pools_per_passage(monkeypatch):
    texts = ["A technical statement. " * 25, "├── architecture 世界 🧭\n" * 30]
    assert all("".join(embedding_segments(text)) == text for text in texts)
    monkeypatch.setattr(gateway, "model_slot", lambda: nullcontext())

    def request(method, url, **kwargs):
        payload = kwargs["json"]
        assert payload["truncate"] is False
        assert all(len(value.encode()) <= 96 for value in payload["input"])
        assert "".join(payload["input"]) == "".join(texts)
        return {"embeddings": [[1.0] * 8 for value in payload["input"]]}

    monkeypatch.setattr(gateway, "_request", request)
    vectors = gateway.embed("ollama", texts)
    assert len(vectors) == 2 and sum(x * x for x in vectors[0]) == pytest.approx(1.0)


def test_public_reader_pins_host_and_rejects_private_redirect():
    calls = []

    def transport(request):
        calls.append(request)
        assert request.url.host == "93.184.216.34" and request.headers["Host"] == "example.com"
        assert request.extensions["sni_hostname"] == "example.com"
        return httpx.Response(302, headers={"location": "http://localhost/private"})

    with pytest.raises(PublicFileError, match="outside"):
        read_public(
            "https://example.com/docs",
            allowed_hosts={"example.com"},
            transport=httpx.MockTransport(transport),
            resolver=lambda _: "93.184.216.34",
        )
    assert len(calls) == 1
    with pytest.raises(PublicFileError, match="Non-public"):
        read_public("https://example.com/docs", allowed_hosts={"example.com"}, resolver=lambda _: "127.0.0.1")
    assert (
        repository_archive("https://github.com/example/repo/tree/main")[0]
        == "https://codeload.github.com/example/repo/zip/main"
    )
    with pytest.raises(PublicFileError):
        repository_archive("https://github.com/example/repo/blob/main/file.js")


def test_stop_checkpoint_resume_cache_and_ownership(context, monkeypatch):
    client, _, _ = context
    account(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **k: "test:units")
    identifier = assess(
        client,
        [
            source(
                "architecture.md",
                "Gateway API is an application service.\n"
                + ("The Gateway API receives requests and serves documents.\n" * 60),
            )
        ],
        "ollama",
    )
    calls = []

    def generate(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        key = next(k for k, v in packet.items() if "Gateway API" in v)
        calls.append(prompt)
        if len(calls) == 1:
            assert client.post(f"/investigations/{identifier}/cancel").status_code == 202
        return {
            "findings": [
                {
                    "kind": "component",
                    "name": "Gateway API",
                    "detail": "Application service described by the sources.",
                    "evidence": [key],
                }
            ]
        }, {}

    monkeypatch.setattr(gateway, "generate", generate)
    jobs.process(identifier)
    stopped = detail(client, identifier)
    assert stopped["status"] == "cancelled" and stopped["report"]["nodes"]
    assert stopped["report"]["run"]["coverage"]["status"] == "partial"
    assert client.get(f"/investigations/{identifier}/export/json").status_code == 200
    assert client.post(f"/investigations/{identifier}/resume").status_code == 202
    jobs.process(identifier)
    resumed = detail(client, identifier)
    assert resumed["status"] == "completed" and resumed["report"]["run"]["cache_hits"] >= 1
    assert len(resumed["evidence"]) == 1
    other = assess(client, [source("routes.md", "GET /documents returns application document records.")])
    jobs.process(other)
    comparison = client.get(f"/investigations/{identifier}/compare/{other}")
    assert comparison.status_code == 200 and comparison.json()["sections"]["components"]["added"]
    client.post("/auth/logout")
    client.post(
        "/auth/register",
        json={"username": "another_user", "email": "other@example.com", "password": "assessment-password"},
    )
    for action in ("cancel", "resume"):
        assert client.post(f"/investigations/{identifier}/{action}").status_code == 404
    assert client.get(f"/investigations/{other}/compare/{identifier}").status_code == 404


def test_fenced_specification_is_detected():
    document = json.dumps({"openapi": "3.0.3", "paths": {"/documents": {"get": {}}}})
    normalized = normalize_source(
        ImportedSource(title="API", origin="local:spec.md", content="```json\n" + document + "\n```")
    )
    assert json.loads(normalized)["paths"]["/documents"] == {"get": {}}


def test_html_bootstrap_is_structural_evidence_with_exact_quotes(context):
    client, _, _ = context
    account(client)
    text = '<!doctype html><html><body><div id="root"></div><script type="module" src="/assets/client.js"></script></body></html>'
    identifier = assess(client, [source("Project/index.html", text)])
    jobs.process(identifier)
    record = detail(client, identifier)
    assert record["report"]["nodes"][0]["label"] == "Web client"
    citation = record["report"]["claims"][0]["citations"][0]
    assert record["evidence"][0]["content"][citation["start"] : citation["end"]] == citation["quote"]
    assert "<script" in citation["quote"]


def test_escaped_script_example_does_not_create_a_client(context):
    client, _, _ = context
    account(client)
    text = '<html><body><p>Example HTML markup for documentation.</p><pre>&lt;script src="/example.js"&gt;&lt;/script&gt;</pre></body></html>'
    identifier = assess(client, [source("example.html", text)])
    jobs.process(identifier)
    assert not detail(client, identifier)["report"]["nodes"]


def test_answer_uses_selected_source_units(context, monkeypatch):
    from app.intelligence import answer_question
    from app.models import Investigation

    client, factory, _ = context
    account(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **k: "test:units")
    identifier = assess(
        client,
        [source("architecture.md", "Gateway API receives requests and serves document records.")],
        "ollama",
    )
    monkeypatch.setattr(gateway, "generate", lambda *a: ({"findings": []}, {}))
    jobs.process(identifier)

    def answer(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])["passages"]
        return {
            "insufficient_evidence": False,
            "statements": [
                {"text": "Gateway API serves document records.", "evidence": [next(iter(packet))]}
            ],
        }, {}

    monkeypatch.setattr(gateway, "generate", answer)
    with factory() as db:
        result = answer_question(db, db.get(Investigation, identifier), "Which API serves document records?")
    assert result["statements"] and not result["insufficient_evidence"]
    assert (
        result["statements"][0]["citations"][0]["quote"]
        == "Gateway API receives requests and serves document records."
    )


def test_linked_public_specification_uses_separate_request_budget(context, monkeypatch):
    from sqlalchemy import select

    from app import public_files
    from app.collection import TinyFishCollector
    from app.models import User

    client, factory, _ = context
    account(client)
    called = []

    def read(url, **kwargs):
        kwargs["before_request"]()
        called.append(url)
        if len(called) == 1:
            return (
                b'<html><body><p>Public API technical documentation.</p><a href="/openapi.json">Specification</a></body></html>',
                url,
                "text/html",
            )
        return (
            json.dumps({"openapi": "3.0.3", "paths": {"/documents": {"get": {}}}}).encode(),
            url,
            "application/json",
        )

    monkeypatch.setattr(public_files, "read_public", read)
    with factory() as db:
        collector = TinyFishCollector(db, db.scalar(select(User)).id, budget=object())
        sources = []
        collector.collect_public_files("https://example.com/", "example.com", sources, set(), lambda *_: None)
        assert len(called) == 3 and collector.record["public_files"]["requests"] == 3
        assert collector.record["url_attempts"] == 0
        assert collector.record["collected_sources"] == 3
        assert any(row[2]["collection_method"] == "public_observation" for row in sources)
        assert sources[-1][2]["collection_method"] == "public_observation"


def test_public_repository_intake_keeps_archive_provenance(context, monkeypatch):
    import io
    import zipfile

    from app import public_files

    client, _, _ = context
    account(client)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(
            "Example-main/package.json", json.dumps({"name": "example", "dependencies": {"express": "^5"}})
        )
    monkeypatch.setattr(
        public_files,
        "read_public",
        lambda *a, **k: (
            archive.getvalue(),
            "https://codeload.github.com/example/repo/zip/HEAD",
            "application/zip",
        ),
    )
    response = client.post("/sources/repository", json={"url": "https://github.com/example/repo"})
    assert response.status_code == 200, response.text
    reviewed = response.json()
    created = client.post(
        "/investigations/bundle",
        json={
            "domain": "Repository test",
            "bundle_id": reviewed["bundle_id"],
            "selected": [row["id"] for row in reviewed["sources"]],
        },
    )
    assert created.status_code == 202, created.text
    identifier = created.json()["id"]
    jobs.process(identifier)
    record = detail(client, identifier)
    assert record["evidence"][0]["collection_method"] == "public_repository"
    assert record["processing_options"]["intake"]["repository_url"] == "https://github.com/example/repo"
