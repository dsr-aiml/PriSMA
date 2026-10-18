import io
import json
import zipfile

from test_baseline import register
from test_document_intelligence import run

from app import jobs, model_gateway as gateway
from app.config import settings
from app.models import ModelCache
from app.run_control import compare_reports


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for path, text in files.items():
            zipped.writestr(path, text)
    return output.getvalue()


def preview(client, text, filename="architecture.md", bundle=None):
    return client.post("/sources/preview", params={"filename": filename, **({"bundle_id": bundle} if bundle else {})},
                       content=text.encode() if isinstance(text, str) else text, headers={"content-type": "application/octet-stream"})


def test_documented_hosting_features_and_licence_are_separate(context):
    client, _, _ = context
    register(client)
    text = """# Beacon
## Features
- Real-time response streaming using Server-Sent Events (SSE)
- Document export with metadata
- Markdown rendering (remark-gfm).
- Deployed on free tier using Amplify(frontend) and EC2 virtual servers (Backend).
## Tech Stack
**Frontend:**
* React (Vite)
**Backend:**
* Node.js & Express
* Vendor API
**DevOps:**
* AWS Amplify
* AWS EC2 virtual servers
## License
Licensed under the GNU General Public License v3.0. See the LICENSE file for details.
"""
    _, detail = run(client, [{"title": "README", "origin": "local:README.md", "content": text}])
    report = detail["report"]
    nodes = {n["id"]: n for n in report["nodes"]}
    deployment = {(nodes[e["source"]]["label"], nodes[e["target"]]["label"]) for e in report["edges"] if e["label"] == "deployed on"}
    assert deployment == {("Frontend", "AWS Amplify"), ("Backend", "AWS EC2")}
    assert all(n["kind"] == "infrastructure" for n in nodes.values() if n["label"] in {"AWS Amplify", "AWS EC2"})
    assert len(report["features"]) == 3
    assert {t["name"] for t in report["technologies"]} >= {"Server-Sent Events", "remark-gfm", "AWS EC2"}
    assert not any("License" in t["name"] for t in report["technologies"])
    assert report["repository"]["licenses"][0]["name"] == "GNU General Public License v3.0"
    assert len({tuple(n["position"].values()) for n in nodes.values()}) == len(nodes)


def test_proposed_and_negated_deployments_do_not_become_active_paths(context):
    client, _, _ = context
    register(client)
    text = "**Frontend:**\n* React\n\nFrontend may be deployed on Render.\nBackend is not hosted on AWS EC2.\n"
    _, detail = run(client, [{"title": "Plan", "origin": "local:plan.md", "content": text}])
    assert not detail["report"]["edges"]
    assert not any(n["kind"] == "infrastructure" for n in detail["report"]["nodes"])


def test_mermaid_paths_are_scoped_and_exactly_cited(context):
    client, _, _ = context
    register(client)
    text = """# Architecture
```mermaid
flowchart LR
  W[Web client] -->|calls| A[Orders API]
  A -->|stores orders| D[(Orders database)]
  A -.-> Q[Orders queue]
```
"""
    _, detail = run(client, [{"title": "Architecture", "origin": "local:one/architecture.md", "content": text},
                             {"title": "Architecture", "origin": "local:two/architecture.md", "content": text.replace("stores orders", "reads orders")}])
    report = detail["report"]
    assert len(report["nodes"]) == 8 and len(report["edges"]) == 6
    assert len({n["context"] for n in report["nodes"]}) == 2
    assert all(n["kind"] == "database" for n in report["nodes"] if n["label"] == "Orders database")
    assert all(e["classification"] == "observed" for e in report["edges"])


def test_mermaid_chain_and_formatted_deployment_are_complete(context):
    client, _, _ = context
    register(client)
    text = "# Architecture\n**Frontend** is hosted on Render.\n```mermaid\nflowchart LR\nA[Gateway API] --> B[Orders service] --> C[Orders database]\n```\n"
    _, detail = run(client, [{"title": "Architecture", "origin": "local:architecture.md", "content": text}])
    assert len(detail["report"]["edges"]) == 3
    assert any(n["label"] == "Render" and n["kind"] == "infrastructure" for n in detail["report"]["nodes"])


def test_source_append_remove_ownership_and_saved_report_isolation(context):
    client, factory, _ = context
    register(client)
    first = preview(client, "# First document\nTechnology: React\n").json()
    second = preview(client, "# Second document\nTechnology: FastAPI\n", "server.md", first["bundle_id"]).json()
    assert second["bundle_id"] == first["bundle_id"] and len(second["sources"]) == 2
    identifier = client.post("/investigations/bundle", json={"domain": "Project", "bundle_id": second["bundle_id"], "selected": [r["id"] for r in second["sources"]]}).json()["id"]
    jobs.process(identifier)
    before = client.get(f"/investigations/{identifier}").json()
    removed = client.delete(f"/sources/bundles/{second['bundle_id']}/items/{second['sources'][0]['id']}").json()
    assert len(removed["sources"]) == 1
    assert client.get(f"/investigations/{identifier}").json() == before
    third = preview(client, "# Third document\nTechnology: Redis\n", "cache.md", second["bundle_id"]).json()
    assert third["sources"][0]["id"] == second["sources"][1]["id"]
    client.post("/auth/logout")
    register(client, "other@example.com")
    assert client.delete(f"/sources/bundles/{second['bundle_id']}/items/{third['sources'][0]['id']}").status_code == 404
    assert preview(client, "# New document\nTechnology: SQLite\n", bundle=second["bundle_id"]).status_code == 404
    with factory() as db:
        assert len(db.get(ModelCache, first["bundle_id"]).result["sources"]) == 2


def test_append_keeps_duplicate_and_path_conflict_outcomes(context):
    client, _, _ = context
    register(client)
    first = preview(client, "# A document\nTechnology: FastAPI\n").json()
    duplicate = preview(client, "# A document\nTechnology: FastAPI\n", "duplicate.md", first["bundle_id"]).json()
    assert duplicate["retained"] == 1 and duplicate["skip_counts"]["Duplicate content"] == 1
    conflict = preview(client, "# Different document\nTechnology: React\n", bundle=first["bundle_id"]).json()
    assert conflict["retained"] == 1 and conflict["skip_counts"]["Path already reviewed with different content"] == 1


def test_github_and_uploaded_sources_keep_individual_acquisition(context, monkeypatch):
    from app import public_files
    client, _, _ = context
    register(client)
    calls = []
    def read(url, **kwargs):
        calls.append((url, kwargs["allowed_hosts"]))
        return archive({"repo-main/README.md": "# Public service\nTechnology: FastAPI\n", "repo-main/.env": "PRIVATE=value"}), url, "application/zip"
    monkeypatch.setattr(public_files, "read_public", read)
    first = preview(client, "# Local architecture\nTechnology: React\n").json()
    reviewed = client.post("/sources/repository", json={"url": "https://github.com/example/repo", "bundle_id": first["bundle_id"]}).json()
    assert calls == [("https://codeload.github.com/example/repo/zip/HEAD", {"codeload.github.com"})]
    assert reviewed["retained"] == 2 and reviewed["skip_counts"]["Credential file"] == 1
    identifier = client.post("/investigations/bundle", json={"domain": "Mixed project", "bundle_id": reviewed["bundle_id"], "selected": [row["id"] for row in reviewed["sources"]]}).json()["id"]
    jobs.process(identifier)
    detail = client.get(f"/investigations/{identifier}").json()
    assert {e["collection_method"] for e in detail["evidence"]} == {"user_import", "public_repository"}
    public = next(e for e in detail["evidence"] if e["collection_method"] == "public_repository")
    assert public["signals"]["repository_url"] == "https://github.com/example/repo"
    assert "not independently fetched" in next(e for e in detail["evidence"] if e["collection_method"] == "user_import")["provenance"]


def test_reassessment_creates_a_new_report_without_collection(context):
    client, _, _ = context
    register(client)
    old_id, original = run(client, [{"title": "API", "origin": "local:api.md", "content": "**Backend:**\n* Express\n* Vendor API\n"}])
    new = client.post(f"/investigations/{old_id}/reassess")
    assert new.status_code == 202, new.text
    new_id = new.json()["id"]
    assert new_id != old_id
    jobs.process(new_id)
    retained = client.get(f"/investigations/{new_id}").json()
    assert retained["evidence"][0]["collection_method"] == "retained_snapshot"
    assert retained["evidence"][0]["content_hash"] == original["evidence"][0]["content_hash"]
    assert retained["processing_options"]["intake"]["reassessment_of"] == old_id
    assert client.get(f"/investigations/{old_id}").json() == original
    assert client.get(f"/investigations/{new_id}/compare/{old_id}").json()["same_source_documents"] is True


def test_comparison_does_not_collapse_same_label_connections():
    def report(edges):
        return {"nodes": [{"id": n, "label": n, "context": "App"} for n in "ABC"], "edges": edges}
    def edge(source, target):
        return {"source": source, "target": target, "label": "deployed on", "context": "App", "claim_id": source+target}
    changes = compare_reports(report([edge("A", "B"), edge("A", "C")]), report([edge("A", "B")]))["sections"]["connections"]
    assert len(changes["removed"]) == 1 and changes["removed"][0]["target_label"] == "C"


def test_collection_defaults_and_selectable_ceiling_are_distinct(context):
    client, _, _ = context
    cfg = settings()
    catalogue = client.get("/providers").json()["live"]
    assert catalogue["limits"] == {"searches": cfg.tinyfish_search_max_per_run, "url_attempts": cfg.tinyfish_fetch_max_per_run, "direct_reads": cfg.public_file_max_per_run}
    assert catalogue["defaults"]["url_attempts"] == min(cfg.tinyfish_fetch_attempts_per_run, cfg.tinyfish_fetch_max_per_run)


def test_model_licence_and_unsupported_role_are_guarded(context, monkeypatch):
    client, _, _ = context
    register(client)
    monkeypatch.setattr(gateway, "model_identity", lambda *a, **k: "controlled:model")
    def generate(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1]);key = next(iter(packet))
        return {"findings": [{"kind": "technology", "name": "GPL", "detail": "Database engine", "evidence": [key]}]}, {}
    monkeypatch.setattr(gateway, "generate", generate)
    _, detail = run(client, [{"title": "Service", "origin": "local:service.md", "content": "The Beacon service uses a GPL license for its source repository."}], "ollama")
    assert not detail["report"]["technologies"]
    assert any("licence" in reason for reason in detail["report"]["run"]["rejection_reasons"])
