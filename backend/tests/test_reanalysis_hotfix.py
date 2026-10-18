"""Retained MIME-detected sources must remain valid for saved-source analysis."""
import pytest
from sqlalchemy import func, select
from test_baseline import register
from test_saved_sources import imported

from app import jobs, public_files
from app.intelligence import normalize_source
from app.models import Evidence, Investigation
from app.resource_policy import resource_format
from app.schemas import ImportedSource
from app.source_analysis import inspect_document


@pytest.mark.parametrize("format,origin,text", [
    ("xml", "https://example.com/sitemap.xml", '<?xml version="1.0"?><urlset><url><loc>https://example.com/editor</loc></url></urlset>'),
    ("css", "https://example.com/styles", '/* Stylesheet */\n.card::before { content: "two  spaces"; }'),
])
def test_detected_public_formats_can_be_reanalysed_without_collection(context, monkeypatch, format, origin, text):
    client, factory, _ = context
    register(client)
    # A saved source may have been MIME-detected after its intake validation.
    identifier = imported(client, [{"title": "Public file", "origin": origin, "format": "text", "content": text}])
    jobs.process(identifier)
    if format == "css":
        # Extensionless CSS is retained with its observed response format.
        with factory() as db:
            source = db.scalar(select(Evidence).where(Evidence.investigation_id == identifier))
            source.source_type = "css"
            source.signals = {**source.signals, "response_content_type": "text/css"}
            db.commit()
    original = client.get(f"/investigations/{identifier}").json()
    monkeypatch.setattr(public_files, "read_public", lambda *a, **k: pytest.fail("Saved-source analysis must not recollect"))
    result = client.post(f"/investigations/{identifier}/reassess", json={"provider": "rules"})
    assert result.status_code == 202, result.text
    cloned = client.get(f"/investigations/{result.json()['id']}").json()
    assert cloned["evidence"][0]["source_type"] == format
    with factory() as db:
        source = db.scalar(select(Evidence).where(Evidence.investigation_id == result.json()["id"]))
        assert source.original_content == text
    assert cloned["evidence"][0]["collection_method"] == "retained_snapshot"
    jobs.process(result.json()["id"])
    assert client.get(f"/investigations/{identifier}").json() == original


def test_invalid_retained_format_has_a_safe_validation_error(context):
    client, factory, queued = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    with factory() as db:
        evidence = db.scalar(select(Evidence).where(Evidence.investigation_id == identifier))
        evidence.source_type = "unsupported-legacy-format"
        evidence.original_content = "private-content-must-not-appear-in-the-error"
        db.commit()
        count = db.scalar(select(func.count()).select_from(Investigation))
    before = client.get(f"/investigations/{identifier}").json()
    queued_before = len(queued)
    response = client.post(f"/investigations/{identifier}/reassess", json={"provider": "rules"})
    assert response.status_code == 422
    assert "format" in response.text and "private-content" not in response.text
    assert len(queued) == queued_before
    assert client.get(f"/investigations/{identifier}").json() == before
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Investigation)) == count


@pytest.mark.parametrize("title", [None, "", 42])
def test_legacy_empty_or_invalid_title_uses_the_saved_origin(context, title):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    with factory() as db:
        evidence = db.scalar(select(Evidence).where(Evidence.investigation_id == identifier))
        evidence.signals = {**evidence.signals, "title": title}
        db.commit()
    response = client.post(f"/investigations/{identifier}/reassess")
    assert response.status_code == 202, response.text


def test_selected_xml_and_provider_settings_preserve_other_reports(context):
    client, factory, _ = context
    register(client)
    identifier = imported(client, [{"title": "Pages", "origin": "https://example.com/sitemap.xml", "format": "text", "content": '<?xml version="1.0"?><sitemapindex/>'}, {"title": "Guide", "origin": "local:guide.md", "format": "markdown", "content": "# Application\n\nPublic application documentation."}])
    jobs.process(identifier)
    original = client.get(f"/investigations/{identifier}").json()
    source_id = next(e["id"] for e in original["evidence"] if e["source_type"] == "xml")
    response = client.post(f"/investigations/{identifier}/reassess", json={"selected": [source_id], "provider": "rules", "semantic_retrieval": False})
    assert response.status_code == 202, response.text
    cloned = client.get(f"/investigations/{response.json()['id']}").json()
    assert len(cloned["evidence"]) == 1
    assert cloned["evidence"][0]["source_type"] == "xml"
    assert cloned["processing_options"]["intake"]["selected"] == 1
    assert cloned["processing_options"]["provider"] == "rules"
    assert client.get(f"/investigations/{identifier}").json() == original


@pytest.mark.parametrize("mime,text", [
    ("text/xml", '<?xml version="1.0"?><sitemapindex/>'),
    ("text/css", '.card { color: red; }'),
    ("application/javascript", 'export const route = "/editor";'),
    ("application/json", '{"resource":"project"}'),
    ("text/html", '<html><h1>Application</h1></html>'),
])
def test_mime_classification_output_is_accepted_by_the_source_contract(mime, text):
    format = resource_format("https://example.com/resource", mime=mime, content=text)
    source = ImportedSource(title="Resource", origin="https://example.com/resource", format=format, content=text)
    assert source.format == format


@pytest.mark.parametrize("format,text", [
    ("xml", '<?xml version="1.0"?>\n<root>\n  <![CDATA[ two  spaces ]]>\n</root>\n'),
    ("css", '.card::before {\n  content: "two  spaces";\n}\n'),
])
def test_xml_and_css_keep_exact_text_and_do_not_become_prose_for_inference(format, text):
    source = ImportedSource(title="Resource", origin="https://example.com/resource", format=format, content=text)
    assert normalize_source(source) == text
    assert not inspect_document(source, text)["eligible_for_model"]


def test_invalid_legacy_analysis_settings_have_a_validation_error(context):
    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    with factory() as db:
        inv = db.get(Investigation, identifier)
        inv.processing_options = {**inv.processing_options, "provider": "unknown-legacy-provider"}
        db.commit()
    response = client.post(f"/investigations/{identifier}/reassess")
    assert response.status_code == 422
    assert "settings" in response.text
    assert "Service unavailable" not in response.text
