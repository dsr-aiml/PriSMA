"""Access-aware evidence and regressions found in the first live URL export."""

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.answer_support import format_statements, support_problem
from app.page_access import document_access, page_access
from app.product_inventory import product_inventory
from app.public_files import PublicFileError, read_public
from app.public_surface import surface_page
from app.query_engine import question_units
from app.research import research_summary
from app.research_context import conversation_query, report_units
from app.resource_policy import resource_priority, resource_role


def source(text, kind="markdown", url="https://example.com/editor", identifier="s1"):
    return SimpleNamespace(id=identifier, content=text, original_content=text, source_type=kind, source_url=url, signals={}, collection_method="tinyfish_fetch", content_hash=hashlib.sha256(text.encode()).hexdigest())


@pytest.mark.parametrize("title,text,status,expected,reason", [
    ("Unsupported client", "Please update your browser", 200, "collection_failed", "unsupported_browser"),
    ("Verify you are human", "", 403, "collection_failed", "access_challenge"),
    ("Sign in to continue", "", 200, "requires_login", "authentication_required"),
    ("Projects", "", 401, "requires_login", "authentication_required"),
    ("Subscription required", "Subscribe to read this article.", 200, "requires_subscription", "subscription_required"),
    ("Error (500)", "Sorry, we had an unexpected error.", 200, "collection_failed", "error_page"),
    ("Access denied", "", 403, "collection_failed", "access_denied"),
    ("Photo editor", "Create images. Pro users have extra tools.", 200, "inspected", ""),
])
def test_access_classification(title, text, status, expected, reason):
    row = page_access(title, text, http_status=status)
    assert row["status"] == expected and row["access_reason"] == reason
    assert row["content_available"] == (expected == "inspected")


def test_paid_marketing_and_signup_links_do_not_make_a_public_page_restricted():
    html = '<html><title>Photo editing</title><h1>Create photos</h1><a href="/login">Sign in</a><p>Premium tools are available to Pro users.</p><p>Sign up to use the workspace.</p></html>'
    row = surface_page(html, "https://example.com/")
    assert row["content_available"] and row["access"] == "public"
    assert row["public_features"]
    assert page_access("Pricing", "Premium exports: subscription required. Read the public feature list.")["content_available"]
    assert document_access("# Error (500)\n\nSorry, we had an unexpected error.")["status"] == "collection_failed"


def test_public_docs_describe_features_and_steps_without_claiming_execution():
    text = '# Image editor\n\nCreate images and collaborate with your team in the online editor.\n\n## Enhance your photo\n\nUpload and select your image, then click Edit. Drag the sharpness slider and save the result.\n\n## Collaborate in real time\n\nShare projects with teammates and track their changes.\n\nPremium features are available to Pro users.\n'
    item = source(text)
    product = product_inventory({}, [item])
    assert product["pages"][0]["status"] == "publicly_documented"
    assert any(w["execution"] == "not_tested" for w in product["workflows"])
    assert any("Collaborate" in f["text"] for f in product["features"])
    assert product["coverage"]["workflows_inspected"] == 0
    for group in ("purpose", "pages", "workflows", "features"):
        for row in product[group]:
            for c in row["citations"]:
                assert text[c["start"]:c["end"]] == c["quote"]


def test_successful_documentation_and_failed_browser_path_both_survive():
    doc = source('# Design app\n\nCreate designs, edit photos and share your work with collaborators.', url="https://example.com/", identifier="docs")
    gate = source('<html><title>Unsupported client</title><h1>Please update your browser</h1></html>', "html", "https://example.com/", "browser")
    gate.signals = {"rendered": True}
    product = product_inventory({}, [doc, gate])
    assert len(product["pages"]) == 1
    page = product["pages"][0]
    assert page["status"] == "publicly_documented" and not page["rendered"]
    assert any(o["access_reason"] == "unsupported_browser" for o in page["access_observations"])
    assert product["coverage"]["pages_with_barriers"] == 1 and product["open_questions"]
    assert "Unsupported" not in product["description"]


def test_insights_and_purpose_are_deduplicated():
    text = '# Design app\n\nCreate designs and publish anywhere with your collaborators.\n\n## Create presentations\n\nBuild presentations from templates.'
    item = source(text)
    summary = research_summary({"claims": [], "run": {}, "nodes": [], "edges": [], "api_endpoints": []}, [item])
    keys = [i["id"] for i in summary["insights"]]
    assert len(keys) == len(set(keys))
    assert any(i["kind"] == "product" for i in summary["insights"])


def test_format_followups_retain_topic_but_explicit_pointer_questions_do_not():
    history = [{"question": "Explain repository structure."}, {"question": "Make it shorter."}]
    assert conversation_query("tell me in 100 words pointers", history) == history[0]["question"]
    assert conversation_query("Explain pointer events in 100 words", history) == "Explain pointer events in 100 words"
    assert conversation_query("Explain database tables", history) == "Explain database tables"
    result = format_statements([{"text": "A complete sentence about the architecture.", "citations": []}], "tell me in 100 words pointers")
    assert result[0]["text"].startswith("• ") and sum(len(r["text"].split()) for r in result) <= 100


def test_quote_matching_does_not_accept_unsupported_dates_or_repository_claims():
    quotes = [{"quote": "Chrome Firefox Safari Edge", "role": "supporting"}]
    assert support_problem("The platform launched in 2013.", quotes) == "unsupported_number"
    assert support_problem("This tool launched in 2013.", [{"quote": "The tool launched in 2013.", "role": "supporting"}]) == ""
    assert support_problem("The repository is structured around Next.js.", [{"quote": "Next.js client bundles", "role": "supporting"}], browser_code_only=True) == "repository_scope"
    assert support_problem("The original repository structure is not established.", [{"quote": "Original repository structure is not established.", "role": "supporting"}], browser_code_only=True) == ""


def test_product_excerpt_reaches_query_packet_ahead_of_incidental_runtime_code():
    item = source('# Editor\n\nCreate images and collaborate with teammates.', identifier="product")
    product = product_inventory({}, [item])
    orientation = report_units({"product": product, "claims": []}, [item], "Explain this project")
    noise = SimpleNamespace(id="code", evidence_id="runtime", start=0, content="project project project pointer render client runtime")
    units = question_units([*orientation, noise], "Explain this project", maximum=128)
    assert next(iter(units.values())).evidence_id == "product"


def test_page_with_analytics_stays_a_page_and_entry_bundle_has_priority():
    assert resource_role("https://example.com/", mime="text/html", content="<html><script>window.dataLayer=[];</script></html>") == "page"
    assert resource_role("https://example.com/analytics.js", context="script") == "tracking"
    rows = [{"url": "https://cdn.example.com/chunks/15.js", "kind": "script"}, {"url": "https://cdn.example.com/chunks/pages/editor-long.js", "kind": "script"}]
    assert sorted(rows, key=resource_priority)[0] == rows[1]


def test_public_reader_can_use_isolated_browser_identity_without_credentials():
    seen = []
    transport = httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200, text="Public page"))
    read_public("https://example.com/", allowed_hosts={"example.com"}, resolver=lambda _: "93.184.216.34", transport=transport, user_agent="Mozilla/5.0 isolated-browser")
    assert seen[0].headers["user-agent"] == "Mozilla/5.0 isolated-browser"
    assert not any(name in seen[0].headers for name in ("cookie", "authorization", "x-api-key"))
    with pytest.raises(PublicFileError, match="user agent"):
        read_public("https://example.com/", allowed_hosts={"example.com"}, user_agent="bad\r\nCookie: secret")


def test_research_rejects_bad_support_keeps_good_answer_and_does_not_cache_it(context, monkeypatch, hosted_query):
    from sqlalchemy import select
    from test_baseline import register
    from test_saved_sources import imported

    from app import jobs
    from app import model_gateway as gateway
    from app.models import ModelCache

    client, factory, _ = context
    register(client)
    identifier = imported(client)
    jobs.process(identifier)
    queued = []
    monkeypatch.setattr(jobs, "enqueue_question", queued.append)
    def reply(provider, prompt, schema):
        packet = json.loads(prompt.split("\n", 1)[1])
        first = next(iter(packet["passages"]))
        proper = next(key for key, value in packet["passages"].items() if "/projects" in value)
        return {"insufficient_evidence": False, "statements": [{"text": "The platform launched in 2013.", "evidence": [first]}, {"text": "The specification declares /projects.", "evidence": [proper]}]}, {}
    monkeypatch.setattr(gateway, "generate", reply)
    result = client.post(f"/investigations/{identifier}/questions", json={"question": "Explain the project API."})
    assert result.status_code == 202
    jobs.process_question(queued[0])
    answer = client.get(f"/investigations/{identifier}/questions").json()[0]["answer"]
    assert answer["insufficient_evidence"] and answer["rejection_reasons"] == {"unsupported_number": 1}
    assert len(answer["statements"]) == 1 and "/projects" in answer["statements"][0]["text"]
    with factory() as db:
        assert not any(row.result.get("answer") for row in db.scalars(select(ModelCache)))


def test_browser_compatibility_retry_and_stylesheet_reserve(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "browser/service.py"
    spec = importlib.util.spec_from_file_location("observer_083", path)
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)
    reads, fulfilled, aborted = [], [], []
    page = SimpleNamespace(url="about:blank", html="", on=lambda *a: None)
    context = SimpleNamespace(set_default_timeout=lambda *a: None, route_web_socket=AsyncMock(), close=AsyncMock())
    async def route(pattern, handler):
        context.handler = handler
    context.route = route
    context.new_page = AsyncMock(return_value=page)
    context.on = lambda *a: None
    session = SimpleNamespace(send=AsyncMock(), on=lambda *a: None)
    context.new_cdp_session = AsyncMock(return_value=session)
    async def evaluate(expression):
        return "Mozilla/5.0 isolated Chromium" if "navigator.userAgent" in expression else page.html
    page.evaluate = evaluate
    page.title = AsyncMock(return_value="Design workspace")
    async def wait(milliseconds):
        await asyncio.sleep(.005)
    page.wait_for_timeout = wait
    page.locator = lambda *a: SimpleNamespace(count=AsyncMock(return_value=0))
    async def issue(url, kind):
        request = SimpleNamespace(url=url, method="GET", resource_type=kind)
        async def fulfill(**kwargs):
            fulfilled.append(url)
            if kind == "document":
                page.html = kwargs["body"].decode()
        async def abort():
            aborted.append(url)
        await context.handler(SimpleNamespace(request=request, fulfill=fulfill, abort=abort))
    async def goto(url, **kwargs):
        page.url = url
        await issue(url, "document")
        if url.endswith("/"):
            for i in range(18):
                await issue(f"https://example.com/styles/{i}.css", "stylesheet")
    page.goto = goto
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    class Runtime:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
        async def __aexit__(self, *a):
            pass
    monkeypatch.setattr(observer, "async_playwright", Runtime)
    def read(url, **kwargs):
        kwargs["before_request"]()
        reads.append((url, kwargs.get("user_agent")))
        if url.endswith(".css"):
            return b"body{color:black}", url, "text/css", {}, 200
        html = '<html><title>Unsupported client</title><h1>Please update your browser</h1></html>' if not kwargs.get("user_agent") else '<html><title>Design workspace</title><h1>Create designs</h1></html>'
        return html.encode(), url, "text/html", {}, 200
    monkeypatch.setattr(observer, "read_public", read)
    result = asyncio.run(observer.capture(observer.Observation(url="https://example.com/", published_pages=["https://example.com/docs"], page_limit=2)))
    coverage = result["snapshot"]["coverage"]
    assert coverage["chromium_launched"] and coverage["stylesheet_requests"] == 14
    assert len([r for r in reads if r[0] == "https://example.com/"]) == 2
    assert ("https://example.com/docs", "Mozilla/5.0 isolated Chromium") in reads
    assert len(aborted) == 4 and not coverage["failures"]
    assert all(s["status"] != "inspected" for s in result["snapshot"]["surface"] if s.get("access_reason") == "unsupported_browser")
