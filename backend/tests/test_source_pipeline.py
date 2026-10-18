import io
import json
import stat
import zipfile

import pytest
from test_baseline import register
from test_saved_sources import imported

from app import jobs
from app import model_gateway as gateway
from app.intelligence import normalize_source
from app.schemas import ImportedSource, WebInvestigation
from app.source_intake import inspect_upload


def archive(files, extras=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as output:
        for path, content in files.items():
            output.writestr(path, content)
        for info, content in extras:
            output.writestr(info, content)
    return buffer.getvalue()


def repository():
    return {
        "app/package.json": json.dumps(
            {"name": "application", "dependencies": {"react": "19", "next": "16"}}
        ),
        "app/compose.yaml": "services:\n  api:\n    image: example/api:1\n    depends_on:\n      - worker\n  worker:\n    image: example/worker:1\n",
        "app/api.py": 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/projects")\ndef projects():\n    return {"projects": []}\n',
        "app/schema.sql": "CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT);",
        "app/README.md": "The API service accepts project requests and dispatches jobs to the worker service.",
        "app/.env": "API_KEY=private-values-must-not-be-imported",
        "app/node_modules/vendor/index.js": "export const ignore = 'dependency code';",
        "app/logo.png": b"\x89PNG\r\n\x1a\n",
    }


def preview(client, raw, name="project.zip"):
    response = client.post(
        "/sources/preview",
        params={"filename": name},
        content=raw,
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_repository_preview_assessment_citations_and_exports(context):
    client, _, _ = context
    register(client)
    reviewed = preview(client, archive(repository()))
    assert reviewed["retained"] == 5 and reviewed["excluded"] == 3
    assert {row["metadata"]["document_kind"] for row in reviewed["sources"]} == {
        "manifest",
        "configuration",
        "source_code",
        "architecture",
    }
    assert all("source" not in row for row in reviewed["sources"])
    assert "private-values" not in json.dumps(reviewed)
    response = client.post(
        "/investigations/bundle",
        json={
            "domain": "Application",
            "provider": "rules",
            "bundle_id": reviewed["bundle_id"],
            "selected": [row["id"] for row in reviewed["sources"]],
        },
    )
    assert response.status_code == 202, response.text
    inv_id = response.json()["id"]
    jobs.process(inv_id)
    detail = client.get(f"/investigations/{inv_id}").json()
    assert detail["status"] == "completed"
    report = detail["report"]
    assert {"api", "worker", "application API"} <= {node["label"] for node in report["nodes"]}
    assert report["edges"] and report["api_endpoints"][0]["path"] == "/projects"
    assert {"react", "next", "fastapi", "example/api:1"} <= {t["name"] for t in report["technologies"]}
    assert {f["type"] for f in report["fields"]} == {"INTEGER", "TEXT"}
    source_map = {e["id"]: e for e in detail["evidence"]}
    assert "    return" in next(e["content"] for e in detail["evidence"] if e["source_type"] == "python")
    for claim in report["claims"]:
        for citation in claim["citations"]:
            source = source_map[citation["evidence_id"]]["content"]
            assert source[citation["start"] : citation["end"]] == citation["quote"]
    document = client.get(f"/investigations/{inv_id}/export/json").json()
    assert document["processing_options"]["intake"]["excluded"] == 3
    assert "Application" in client.get(f"/investigations/{inv_id}/export/markdown").text


def test_report_import_reclassifies_responses_and_restores_documents(context):
    client, _, _ = context
    register(client)
    old = {
        "contract": "prisma.report",
        "schema_version": 3,
        "mode": "live",
        "requested_domain": "example.com",
        "evidence": [
            {
                "source_url": "https://example.com/docs",
                "source_type": "markdown",
                "category": "documentation",
                "content": "GET /projects\nReturns a list of projects.\nPOST /projects\nCreates a project.",
                "signals": {"title": "API reference"},
            },
            {
                "source_url": "https://example.com/ip",
                "source_type": "markdown",
                "category": "documentation",
                "content": '{"origin": "203.0.113.7"}',
                "signals": {},
            },
        ],
        "report": {"nodes": [{"label": "Do not copy old claims"}]},
    }
    reviewed = preview(client, json.dumps(old).encode(), "report.json")
    assert reviewed["subject"] == "example.com"
    assert [r["metadata"]["document_kind"] for r in reviewed["sources"]] == ["api_reference", "api_response"]
    assert not reviewed["sources"][1]["metadata"]["eligible_for_model"]
    response = client.post(
        "/investigations/bundle",
        json={
            "domain": "example.com",
            "bundle_id": reviewed["bundle_id"],
            "selected": [reviewed["sources"][0]["id"]],
        },
    )
    inv_id = response.json()["id"]
    jobs.process(inv_id)
    report = client.get(f"/investigations/{inv_id}").json()["report"]
    assert [n["label"] for n in report["nodes"]] == ["Public API"]
    assert len(report["api_endpoints"]) == 2
    assert len([c for c in report["claims"] if c["type"] == "component"]) == 1


def test_bundle_ownership_invalid_selection_and_reuse(context):
    client, _, _ = context
    register(client)
    reviewed = preview(client, archive(repository()))
    body = {"domain": "Project", "bundle_id": reviewed["bundle_id"], "selected": ["not-a-source"]}
    assert client.post("/investigations/bundle", json=body).status_code == 422
    client.post("/auth/logout")
    register(client, "other@example.com")
    body["selected"] = [reviewed["sources"][0]["id"]]
    assert client.post("/investigations/bundle", json=body).status_code == 404


def test_archive_member_guards_and_deduplication():
    link = zipfile.ZipInfo("app/link.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    files = {
        "app/readme.md": "The API service handles requests from the web client.",
        "app/copy.md": "The API service handles requests from the web client.",
        "../escape.py": "print('must not be extracted')",
        "app/embedded.zip": b"not another archive",
        "app/huge.txt": "x" * 200000,
    }
    reviewed = inspect_upload("app.zip", archive(files, [(link, "../../private")]))
    assert reviewed["retained"] == 1 and reviewed["excluded"] == 5
    assert {
        "Unsafe archive path",
        "Duplicate content",
        "Nested archive",
        "Archive expansion budget exceeded",
        "Symlink or encrypted archive member",
    } <= reviewed["skip_counts"].keys()


def test_hundreds_of_source_files_are_reviewed_without_execution():
    files = {
        f"project/module_{index}.py": f"import os\nvalue = {index}\n# Source inspection only, never executed.\n"
        for index in range(250)
    }
    reviewed = inspect_upload("project.zip", archive(files))
    assert reviewed["retained"] == 250
    assert all(row["metadata"]["document_kind"] == "source_code" for row in reviewed["sources"])
    assert all(not row["metadata"]["eligible_for_model"] for row in reviewed["sources"])


def test_yaml_specification_and_cyclic_configuration():
    spec = ImportedSource(
        title="API",
        origin="local:openapi.yaml",
        format="yaml",
        content="openapi: 3.0.3\ninfo:\n  title: Project API\n  version: '1'\npaths:\n  /projects:\n    get:\n      summary: List projects\n",
    )
    assert json.loads(normalize_source(spec))["paths"]["/projects"]["get"]
    reviewed = inspect_upload(
        "settings.yaml", b"config: &loop\n  child: *loop\n# Original retained for inspection.\n"
    )
    assert reviewed["retained"] == 1 and reviewed["sources"][0]["metadata"]["parse_warnings"]


def test_focused_model_contract_and_background_filter(context, monkeypatch):
    client, _, _ = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **kw: "test-model:digest")
    prompts = []

    def model(provider, prompt, schema):
        prompts.append(prompt)
        assert schema["properties"]["findings"]["maxItems"] == 3
        packet = json.loads(prompt.split("\n", 1)[1])
        key = next(iter(packet))
        return {
            "findings": [
                {
                    "kind": "component",
                    "name": "Gateway API",
                    "detail": "Receives application requests.",
                    "passage": key,
                    "quote": packet[key],
                }
            ]
        }, {}

    monkeypatch.setattr(gateway, "generate", model)
    sources = [
        {
            "title": "Architecture",
            "origin": "local:architecture.md",
            "content": "Gateway API is the service that receives application requests.",
        },
        {
            "title": "Response",
            "origin": "local:response.json",
            "content": '{"headers": {"Host": "example.com"}}',
        },
    ]
    inv_id = imported(client, sources, "ollama")
    jobs.process(inv_id)
    report = client.get(f"/investigations/{inv_id}").json()["report"]
    assert report["nodes"][0]["label"] == "Gateway API"
    assert len(prompts) == 1 and '"headers"' not in prompts[0]
    assert report["run"]["coverage"]["eligible_passages"] == 1
    assert report["run"]["coverage"]["background_passages"] == 1
    assert report["run"]["coverage"]["status"] == "complete"


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/docs",
        "http://127.0.0.1/api",
        "https://name:secret@example.com/docs",
        "file:///tmp/code",
    ],
)
def test_public_target_rejects_local_and_credential_urls(url):
    with pytest.raises(ValueError):
        WebInvestigation(domain=url)


def test_public_target_preserves_document_path():
    target = WebInvestigation(domain="https://example.com/docs/openapi.json")
    assert target.domain == "example.com" and target.source_url == "https://example.com/docs/openapi.json"


def test_docx_and_unreadable_pdf():
    docx = archive(
        {
            "word/document.xml": '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>The Gateway API service receives project requests.</w:t></w:r></w:p></w:body></w:document>'
        }
    )
    reviewed = inspect_upload("architecture.docx", docx)
    assert "Gateway API" in reviewed["sources"][0]["source"]["content"]
    with pytest.raises(ValueError, match="No readable sources"):
        inspect_upload("broken.pdf", b"This is not a readable PDF file and must be rejected.")
