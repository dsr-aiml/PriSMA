"""Regressions for real collection failures and target-subject contamination."""

import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import DataError
from test_baseline import register
from test_saved_sources import imported

from app import jobs
from app.intelligence import import_evidence, normalize_source
from app.models import Chunk, Evidence, Investigation
from app.schemas import ImportedSource
from app.source_storage import original_text
from app.page_access import apply_content_coverage
from app.public_surface import surface_page
from app.product_inventory import product_inventory
from app.resource_policy import public_navigation, resource_role
from app.target_scope import document_scope


def reject_postgres_nul(connection, cursor, statement, parameters, context, executemany):
    values = parameters.values() if isinstance(parameters, dict) else parameters
    if any(isinstance(value, str) and "\x00" in value for value in values):
        raise DataError(statement, parameters, ValueError("PostgreSQL text rejects NUL"))


@pytest.mark.parametrize("format,content", [
    ("javascript", 'const marker = "\x00";\nfetch("/api/projects");'),
    ("python", 'marker = "\x00"\nname = "Project"'),
    ("html", '<html><h1>Project\x00workspace</h1></html>'),
    ("text", 'Project workspace\nNotes: one\x00two'),
])
def test_nul_snapshot_preserves_original_and_normalized_citation_spans(context, format, content):
    client, factory, _ = context
    register(client)
    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", reject_postgres_nul)
    try:
        identifier = imported(client, [{"title": "Captured source", "origin": "local:captured/source", "format": format, "content": content}])
        jobs.process(identifier)
        with factory() as db:
            source = db.scalar(select(Evidence).where(Evidence.investigation_id == identifier))
            assert "\x00" not in source.content and "\x00" not in source.original_content
            assert original_text(source) == content
            assert source.signals["raw_sha256"] == hashlib.sha256(content.encode()).hexdigest()
            assert source.signals["text_normalization"]["nul_replacements"] == 1
            for chunk in db.scalars(select(Chunk).where(Chunk.investigation_id == identifier)):
                assert source.content[chunk.start:chunk.end] == chunk.content
        bundle = client.get(f"/investigations/{identifier}/export/evidence")
        assert bundle.status_code == 200, bundle.text[:200]
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            manifest = json.loads(archive.read("prisma-evidence.json"))
            row = manifest["evidence"][0]
            assert archive.read(row["original_ref"]).decode() == content
            assert "_original_storage" not in row["signals"]
        reassess = client.post(f"/investigations/{identifier}/reassess", json={"provider": "rules"})
        assert reassess.status_code == 202, reassess.text
        jobs.process(reassess.json()["id"])
        with factory() as db:
            copy = db.scalar(select(Evidence).where(Evidence.investigation_id == reassess.json()["id"]))
            assert original_text(copy) == content
    finally:
        event.remove(engine, "before_cursor_execute", reject_postgres_nul)


def test_one_rejected_database_source_keeps_other_snapshots_and_marks_partial(context):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    sources = [ImportedSource(title="Source", origin=f"local:{index}.md", format="text", content=text)
               for index, text in enumerate(["Useful original evidence.", "rejected marker", "More useful evidence."])]
    engine = factory.kw["bind"]
    def reject_one(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO evidence") and "rejected marker" in parameters:
            raise DataError(statement, parameters, ValueError("Bad source"))
    event.listen(engine, "before_cursor_execute", reject_one)
    try:
        with factory() as db:
            inv = db.get(Investigation, identifier)
            # The existing source is retained, along with both new valid sources.
            import_evidence(db, inv, sources, [normalize_source(source) for source in sources])
            db.commit()
            assert db.is_active
            assert len(list(db.scalars(select(Evidence).where(Evidence.investigation_id == identifier)))) == 3
            assert len(inv.processing_options["source_admission"]["excluded"]) == 1
            appended = ImportedSource(title="Later source", origin="local:later.md", content="Later retained material.")
            import_evidence(db, inv, [appended], [normalize_source(appended)])
            db.commit()
            assert db.get(Evidence, identifier+":source-5") is not None
        jobs.process(identifier)
        report = client.get(f"/investigations/{identifier}").json()["report"]
        assert report["run"]["coverage"]["status"] == "partial"
        assert report["run"]["coverage"]["excluded_sources"] == 1
    finally:
        event.remove(engine, "before_cursor_execute", reject_one)


def document(text, url, identifier, kind="html", **signals):
    return SimpleNamespace(id=identifier, content=text, original_content=text, source_type=kind,
                           source_url=url, signals=signals, collection_method="browser_dom")


def test_target_subject_filters_hosted_articles_and_other_products():
    assert document_scope("https://en.wikipedia.org/wiki/Swagger", "https://www.wikipedia.org/")["role"] == "background_reference"
    assert document_scope("https://aws.amazon.com/api-gateway/", "https://amazon.com/")["role"] == "background_reference"
    assert document_scope("https://example.com/blog/swagger", "https://example.com/")["role"] == "background_reference"
    assert document_scope("https://docs.example.com/api/", "https://www.example.com/")["role"] == "target_product"
    assert document_scope("https://en.wikipedia.org/wiki/Swagger", "https://en.wikipedia.org/wiki/Swagger")["role"] == "target_product"
    target = document('<title>Encyclopedia</title><meta name="description" content="A free encyclopedia written by volunteers.">', "https://www.wikipedia.org/", "root")
    irrelevant = document('# Swagger\n\nBuild and test APIs with an interactive editor.\n\n## API testing', 'https://en.wikipedia.org/wiki/Swagger', 'article', 'markdown')
    product = product_inventory({"run": {"target_url": "https://wikipedia.org/"}}, [irrelevant, target])
    assert "encyclopedia" in product["description"]
    assert not any("Swagger" in str(row) for row in product["features"])
    assert not any(page["url"] == irrelevant.source_url for page in product["pages"])


def test_challenge_is_not_a_product_form_or_successful_browser_inspection():
    html = '<title>Store</title><p>Click the button below to continue shopping</p><form action="/errors/validateCaptcha"><input name="token"><button>Continue shopping</button></form>'
    surface = {**surface_page(html, "https://shop.example/"), "rendered": True}
    assert not surface["content_available"] and surface["access_reason"] == "access_challenge"
    snapshot = {"surface": [surface], "coverage": {"status": "complete", "chromium_launched": True}}
    apply_content_coverage(snapshot)
    assert snapshot["coverage"]["status"] == "partial"
    assert snapshot["coverage"]["content_status"] == "blocked"
    assert snapshot["coverage"]["transport_status"] == "complete"
    product = product_inventory({}, [document(html, 'https://shop.example/', 'gate', rendered=True)])
    assert not product["workflows"]


def test_rendered_recovery_and_primary_description_win_without_erasing_history():
    gate = document('<title>Unsupported browser</title>', 'https://www.design.example/', 'gate')
    editor = document('<title>Photo editor</title><meta name="description" content="Edit photos with an online editor and enhance every detail with powerful editing tools.">', 'https://www.design.example/photo-editor', 'editor')
    root = document('<title>Design suite</title><meta name="description" content="A visual suite for designs, documents and presentations.">', 'https://www.design.example/', 'root', rendered=True)
    product = product_inventory({"run": {"target_url": "https://design.example/"}}, [editor, gate, root])
    assert product["description"].startswith("A visual suite")
    page = next(row for row in product["pages"] if row["url"] == root.source_url)
    assert page["status"] == "inspected" and len(page["access_observations"]) == 2
    assert product["coverage"]["pages_with_barriers"] == 0


def test_observed_host_alias_navigation_and_sdk_roles():
    surface = {"url": "https://www.example.com/", "navigation": [{"url": "https://www.example.com/features", "label": "Features"}, {"url": "https://example.com/docs", "label": "Docs"}, {"url": "https://evil.example/docs", "label": "Docs"}, {"url": "https://example.com/delete", "label": "Delete"}]}
    paths = public_navigation(surface, "example.com")
    assert len(paths) == 2 and all("evil" not in path for path in paths)
    assert resource_role("https://accounts.google.com/gsi/client", context="script") == "dependency"
    assert resource_role("https://cdn.example.com/.sentry_browser.js", context="script") == "tracking"
    assert resource_role("https://app.example.com/assets/editor", mime="application/javascript", context="script") == "application"


def test_account_activity_is_owner_scoped_real_and_excludes_reference_reports(context):
    from datetime import timedelta
    from app.models import User, now
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    with factory() as db:
        owner = db.scalar(select(User))
        stranger = User(email="other@example.com", username="other", password_hash="unused")
        db.add(stranger)
        db.flush()
        db.add_all([
            Investigation(user_id=owner.id, domain="Reference", mode="demo", status="completed"),
            Investigation(user_id=stranger.id, domain="Private other report", mode="import", status="completed"),
            Investigation(user_id=owner.id, domain="Old report", mode="import", status="failed", created_at=now()-timedelta(days=40)),
        ])
        db.commit()
    activity = client.get("/account").json()["activity"]
    assert len(activity["days"]) == 28 and activity["timezone"] == "UTC"
    assert sum(row["assessments"] for row in activity["days"]) == 1
    assert activity["outcomes"] == {"completed": 1, "failed": 1}
    assert {row["name"] for row in activity["recent"]} == {"example.com", "Old report"}
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/account").status_code == 401


def test_worker_failed_flush_rolls_back_before_saving_collection_record(context, monkeypatch):
    from app import collection, intelligence
    from app.models import User
    client, factory, _ = context
    register(client)
    with factory() as db:
        inv = Investigation(user_id=db.scalar(select(User)).id, domain="example.com", mode="live", processing_options={"provider": "rules"})
        db.add(inv)
        db.commit()
        identifier = inv.id
    class Collector:
        def __init__(self, *args, **kwargs):
            self.record = {"status": "complete", "seed_url": "https://example.com/", "collected_sources": 1}
        def collect(self, *args):
            source = ImportedSource(title="Page", origin="https://example.com/", content="Useful source")
            return [(source, source.content, {})]
    def failing_import(db, inv, *args, **kwargs):
        db.add(Evidence(id=inv.id+":bad", investigation_id=inv.id, source_url="local:bad", source_type="text", category="data", content="\x00", content_hash="bad", signals={}, provenance="test", collection_method="test"))
        db.flush()
    monkeypatch.setattr(collection, "TinyFishCollector", Collector)
    monkeypatch.setattr(intelligence, "import_evidence", failing_import)
    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", reject_postgres_nul)
    try:
        jobs.process_saved(identifier)
    finally:
        event.remove(engine, "before_cursor_execute", reject_postgres_nul)
    with factory() as db:
        inv = db.get(Investigation, identifier)
        assert inv.status == "failed" and "Evidence storage was interrupted" in inv.error
        assert inv.processing_options["collection"]["collected_sources"] == 1
        assert db.is_active


@pytest.mark.parametrize("target", ["example.com", "www.example.com"])
def test_url_forms_preserve_redirect_paths_and_accept_host_alias_links(target):
    from app.collection import scoped_url
    for url in ["https://example.com/features", "https://www.example.com/features"]:
        assert scoped_url(url, target) == url
    assert scoped_url("https://notexample.com/features", target) is None
    surface = surface_page('<title>App</title><a href="https://example.com/features">Features</a>', 'https://www.example.com/')
    assert surface["navigation"][0]["url"] == "https://example.com/features"


def test_partial_challenge_markup_and_old_public_classification_are_rechecked():
    from app.web_observation import CONTRACT
    markup = '<form action="/errors/validateCaptcha">\nStore\nClick the button below to continue shopping'
    assert not surface_page(markup, 'https://shop.example/')["content_available"]
    snapshot = {"contract": CONTRACT, "surface": [{"url": "https://shop.example/", "title": "Store", "description": "Click the button below to continue shopping", "rendered": True, "status": "inspected", "content_available": True}], "coverage": {"status": "complete"}}
    product = product_inventory({}, [document(json.dumps(snapshot), 'local:observation.json', 'legacy', 'json')])
    assert product["coverage"]["pages_by_status"] == {"collection_failed": 1}


def test_form_and_origin_consolidation_retains_each_supporting_claim(context):
    from app.web_observation import new_snapshot, append_response
    client, factory, _ = context
    register(client)
    html='<title>Search</title><script src="https://assets.example.net/client.js"></script><form action="/search"><input name="q"></form>'
    snapshot=new_snapshot('https://example.com/', 'chromium_public_pages')
    snapshot['surface']=[{**surface_page(html,'https://example.com/'), 'rendered': True}]
    append_response(snapshot, 'https://example.com/', 'https://example.com/', 'text/html', {'content-type': 'text/html'}, 200, resource_type='document')
    identifier=imported(client,[{'title':'Markup','origin':'https://example.com/','format':'html','content':html}, {'title':'Observation','origin':'local:observation.json','format':'json','content':json.dumps(snapshot)}])
    with factory() as db:
        source=db.scalar(select(Evidence).where(Evidence.investigation_id==identifier, Evidence.source_type=='html'))
        source.collection_method='browser_dom'
        db.commit()
    jobs.process(identifier)
    report=client.get('/investigations/'+identifier).json()['report']
    operations=[row for row in report['api_endpoints'] if row['path']=='/search']
    assert len(operations)==1 and operations[0]['executed'] is False
    assert len(operations[0]['claim_ids'])==2


def test_new_answers_do_not_reuse_legacy_findings_from_background_articles(context):
    from app.intelligence import answer_question
    client, factory, _ = context
    register(client)
    identifier=imported(client,[{'title':'Portal','origin':'https://example.com/','format':'markdown','content':'# Portal\n\nA public encyclopedia written by volunteers.'}, {'title':'Swagger article','origin':'https://example.com/wiki/Swagger','format':'markdown','content':'# Swagger\n\nSwagger Editor is used to design and test API contracts.'}])
    jobs.process(identifier)
    with factory() as db:
        inv=db.get(Investigation,identifier)
        background=db.scalar(select(Evidence).where(Evidence.investigation_id==identifier,Evidence.source_url.contains('/wiki/')))
        inv.processing_options={**inv.processing_options,'source_url':'https://example.com/'}
        legacy={'id':'legacy','type':'component','description':'Swagger Editor: API testing application.','supporting_evidence_ids':[background.id],'citations':[]}
        inv.report={**inv.report,'summary':'Swagger is the application.','claims':[*inv.report['claims'],legacy],'nodes':[*inv.report['nodes'],{'id':'legacy-node','label':'Swagger Editor','description':'API testing application.','claim_id':'legacy','kind':'service'}]}
        db.commit()
        saved=json.dumps(inv.report,sort_keys=True)
        answer=answer_question(db,inv,'Explain the architecture')
        assert 'Swagger' not in json.dumps(answer)
        assert json.dumps(inv.report,sort_keys=True)==saved
