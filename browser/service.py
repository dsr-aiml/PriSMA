"""Ephemeral sandboxed Chromium with bounded, DNS-pinned anonymous acquisition."""

import asyncio
import json
import logging
import multiprocessing
import os
import queue
import re
import signal
import threading
import time
from urllib.parse import urljoin, urlsplit

from fastapi import FastAPI, HTTPException
from playwright.async_api import Error, async_playwright
from playwright.async_api import TimeoutError as BrowserTimeout
from pydantic import BaseModel, Field

from app.public_files import LinkedFiles, PublicFileError, decode_public_text, read_public
from app.public_surface import surface_page
from app.page_access import apply_content_coverage
from app.read_operations import validate_read_operation
from app.resource_policy import public_navigation, resource_priority, resource_role, safe_control
from app.web_observation import append_response, new_snapshot, safe_url, shape, signatures

app = FastAPI(docs_url=None, redoc_url=None)
gate = threading.Lock()
readiness = {"status": "starting", "checked": 0}


class Observation(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    external_resources: bool = False
    page_limit: int = Field(default=3, ge=1, le=5)
    read_only_operations: bool = False
    interaction_limit: int = Field(default=3, ge=0, le=5)
    published_pages: list[str] = Field(default_factory=list, max_length=12)


def launch_options():
    return {
        "headless": True,
        "chromium_sandbox": True,
        "proxy": {"server": "http://127.0.0.1:9", "bypass": ""},
        "args": [
            "--disable-quic",
            "--proxy-bypass-list=<-loopback>",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--disable-background-networking",
        ],
    }


async def probe():
    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch(**launch_options())
        try:
            page = await browser.new_page()
            if await page.evaluate("() => 1 + 1") != 2:
                raise RuntimeError("Chromium execution probe failed")
        finally:
            await browser.close()


def startup_reason(exc):
    """Classify an about:blank launch failure without logging target content."""
    message = str(exc)
    if 'sys_chroot("/proc/self/fdinfo/")' in message:
        return "Chromium sandbox chroot failed. Check that the observer seccomp profile permits chroot with container capabilities dropped."
    if (
        "No usable sandbox" in message
        or "Failed to move to new namespace" in message
        or "unprivileged_userns" in message
    ):
        return "Chromium user namespace sandbox is unavailable. Inspect the host namespace/AppArmor policy and the observer seccomp profile."
    return (
        "Sandboxed Chromium could not launch. Run the direct service.probe diagnostic for its startup trace."
    )


def probe_process(results):
    os.setsid()
    try:
        asyncio.run(asyncio.wait_for(probe(), timeout=8))
        results.put({"status": "ready", "sandbox": True})
    except Exception as exc:
        logging.getLogger("prisma.browser").error(
            "Chromium readiness failed (%s): %s", type(exc).__name__, startup_reason(exc)
        )
        results.put(
            {
                "status": "unavailable",
                "code": "browser_startup",
                "reason": startup_reason(exc),
            }
        )


def stop_process(process):
    process.join(timeout=0.2)
    if process.is_alive():
        try:
            if os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.join(timeout=1)


@app.get("/health")
@app.get("/ready")
def health():
    if time.monotonic() - readiness["checked"] < 30:
        if readiness["status"] != "ready":
            raise HTTPException(503, {k: v for k, v in readiness.items() if k != "checked"})
        return {**readiness, "method": "chromium", "max_requests": 72, "max_seconds": 70, "max_pages": 5}
    if not gate.acquire(blocking=False):
        if readiness["status"] == "ready":
            return {**readiness, "busy": True}
        raise HTTPException(
            503, {"code": "browser_startup", "reason": "Chromium readiness is still being checked."}
        )
    results = multiprocessing.get_context("spawn").Queue(maxsize=1)
    process = multiprocessing.get_context("spawn").Process(target=probe_process, args=(results,))
    try:
        process.start()
        try:
            state = results.get(timeout=10)
        except queue.Empty:
            state = {
                "status": "unavailable",
                "code": "browser_startup",
                "reason": "Chromium launch probe timed out.",
            }
        readiness.update(**state, checked=time.monotonic())
        if state["status"] != "ready":
            raise HTTPException(503, state)
        return state
    finally:
        stop_process(process)
        results.close()
        gate.release()


@app.post("/observe")
def observe(body: Observation):
    try:
        parsed = urlsplit(body.url)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 80, 443)
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(422, "Use a public HTTP(S) address without credentials.")
    if not gate.acquire(blocking=False):
        raise HTTPException(429, "Browser observer is currently in use.")
    runtime = multiprocessing.get_context("spawn")
    results = runtime.Queue(maxsize=2)
    process = runtime.Process(target=capture_process, args=(body.model_dump(), results))
    latest = {
        "snapshot": new_snapshot(body.url, "chromium_public_pages"),
        "pages": [],
        "scripts": [],
        "source_maps": [],
    }
    try:
        process.start()
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            try:
                message = results.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
                latest = message["result"]
                if message.get("done"):
                    coverage = latest["snapshot"]["coverage"]
                    if coverage.get("chromium_launched"):
                        readiness.update(status="ready", sandbox=True, checked=time.monotonic())
                    elif any(row.get("code") == "browser_startup" for row in coverage.get("failures", [])):
                        readiness.update(
                            status="unavailable",
                            code="browser_startup",
                            reason="Sandboxed Chromium could not launch. Inspect browser logs.",
                            checked=time.monotonic(),
                        )
                    return bound_result(latest)
            except queue.Empty:
                if not process.is_alive():
                    break
        coverage = latest["snapshot"]["coverage"]
        coverage.update(
            status="partial" if latest["pages"] or latest["scripts"] else "failed", stop_reason="timeout"
        )
        coverage.setdefault("failures", []).append(
            {
                "code": "browser_timeout",
                "stage": "collection",
                "reason": "Browser wall time reached; the latest completed checkpoint was retained.",
            }
        )
        return bound_result(latest)
    finally:
        stop_process(process)
        results.close()
        gate.release()


def capture_process(payload, results):
    os.setsid()

    def checkpoint(result):
        try:
            results.put_nowait({"result": bound_result(result), "done": False})
        except queue.Full:
            pass

    try:
        result = asyncio.run(capture(Observation(**payload), checkpoint))
        results.put({"result": bound_result(result), "done": True}, timeout=2)
    except Exception as exc:
        logging.getLogger("prisma.browser").error("Browser process failed: %s", type(exc).__name__)
        # The parent preserves its latest checkpoint on process failure.


def bound_result(result):
    # Detach before trimming: capture state must not change when a checkpoint is sent.
    result = json.loads(json.dumps(result, ensure_ascii=False))
    coverage = result["snapshot"]["coverage"]
    excluded = []
    while len(json.dumps(result, ensure_ascii=False).encode()) > 10_000_000:
        low_value = [
            s
            for s in result.get("scripts", [])
            if s.get("resource_role") in {"dependency", "delivery", "tracking"}
        ]
        if low_value:
            row = max(low_value, key=lambda s: len(s["content"]))
            result["scripts"].remove(row)
        elif result.get("source_maps"):
            row = result["source_maps"].pop()
        elif any(p.get("html") for p in result.get("pages", [])[1:]):
            row = max(result["pages"][1:], key=lambda p: len(p.get("html", "")))
            row["html"] = ""
        elif result.get("scripts"):
            row = result["scripts"].pop()
        else:
            break
        excluded.append({"url": row["url"], "reason": "Encoded capture response allowance."})
    if excluded:
        coverage.update(status="partial", delivery_exclusions=excluded)
    coverage.update(
        pages=len(result.get("pages", [])),
        scripts_retained=len(result.get("scripts", [])),
        source_maps_retained=len(result.get("source_maps", [])),
    )
    return result


def initiator_record(initiator):
    result = {"type": str(initiator.get("type", "unknown"))[:40]}
    frames = (
        initiator.get("stack", {}).get("callFrames", []) if isinstance(initiator.get("stack"), dict) else []
    )
    for frame in frames[:8]:
        if (
            isinstance(frame, dict)
            and isinstance(frame.get("url"), str)
            and frame["url"].startswith(("http://", "https://"))
        ):
            result.update(
                url=safe_url(frame["url"]), line=frame.get("lineNumber"), column=frame.get("columnNumber")
            )
            break
    if "url" not in result and isinstance(initiator.get("url"), str):
        result["url"] = safe_url(initiator["url"])
    return result


def page_candidates(surface, domain):
    return public_navigation(surface, domain)


async def capture(body, checkpoint=lambda _: None):
    started = time.monotonic()
    snapshot = new_snapshot(body.url, "chromium_public_pages")
    budget = {
        "requests": 0,
        "bytes": 0,
        "request_limit": 72,
        "byte_limit": 20_000_000,
        "time_limit_seconds": 70,
        "page_limit": body.page_limit,
        "read_operations": 0,
        "stylesheet_requests": 0,
        "stylesheet_limit": 14,
        "navigation_reserve": 6,
    }
    blocked, failures, pages, scripts, maps, interactions = [], [], [], [], [], []
    seen_resources, seen_scripts, seen_pages = set(), set(), set()
    domain = urlsplit(body.url).hostname.removeprefix("www.")
    budget_lock = threading.Lock()
    semaphore = asyncio.Semaphore(4)
    cache, traffic, role_bytes = {}, {}, {}
    last_activity = started
    launched = False
    stage = "collection"
    candidates, gains, javascript_errors = [], [], []
    browser_user_agent = None

    def note(rows, url, reason, **meta):
        if len(rows) < 96:
            rows.append({"url": safe_url(url), "reason": reason[:180], **meta})

    def reserve(kind="resource"):
        with budget_lock:
            if budget["requests"] >= 72 or budget["bytes"] >= 20_000_000 or time.monotonic() - started >= 63:
                raise PublicFileError("Browser collection allowance reached.")
            if kind != "document" and budget["requests"] >= 66:
                raise PublicFileError("Resource allowance reached; remaining reads reserved for navigation.")
            if kind == "stylesheet":
                if budget["stylesheet_requests"] >= budget["stylesheet_limit"]:
                    raise PublicFileError("Stylesheet allowance reached; reads reserved for application evidence.")
                budget["stylesheet_requests"] += 1
            budget["requests"] += 1

    def result(final=False):
        limited = bool(candidates or budget["requests"] >= 72 or time.monotonic() - started >= 63)
        material = [r for r in blocked if r.get("resource_type") not in {"image", "media", "font"}]
        snapshot["coverage"] = {
            **budget,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "status": "partial" if failures or limited or material or not final else "complete",
            "chromium_launched": launched,
            "scope": "Anonymous public pages, disclosed tabs and menus; forms are never submitted. GraphQL queries require explicit opt-in.",
            "blocked": blocked,
            "failures": failures,
            "interactions": interactions,
            "retained_bytes_by_role": role_bytes,
            "pages": len(pages),
            "scripts_retained": len(scripts),
            "source_maps_retained": len(maps),
            "unvisited_pages": len(candidates),
            "stop_reason": "allowance" if limited else "selected_navigation_exhausted",
            "service_workers": "blocked",
            "websockets": "blocked",
            "page_gains": gains,
            "javascript_errors": len(javascript_errors),
        }
        apply_content_coverage(snapshot)
        return {"snapshot": snapshot, "pages": pages, "scripts": scripts, "source_maps": maps}

    def retain_script(final, text, page_url, headers, mime):
        if not text or final in seen_scripts:
            return
        role = resource_role(final, mime=mime, content=text, context="script", page_url=page_url)
        original_characters = len(text)
        if len(text) > 2_000_000:
            note(
                blocked,
                final,
                "Large application resource retained as a bounded prefix; remaining content was excluded.",
                resource_type="script",
                resource_role=role,
                original_characters=len(text),
            )
            text = text[:2_000_000]
        size = len(text.encode())
        allowance = 7_000_000 if role == "application" else 700_000 if role == "dependency" else 100_000
        if len(scripts) >= 40 or role_bytes.get(role, 0) + size > allowance:
            note(
                blocked,
                final,
                "Readable content allowance for this resource role.",
                resource_type="script",
                resource_role=role,
                bytes=size,
            )
            return
        scripts.append(
            {
                "url": safe_url(final),
                "content": text,
                "page_url": safe_url(page_url),
                "source_map": headers.get("sourcemap") or headers.get("x-sourcemap"),
                "resource_role": role,
                "response_content_type": mime,
                "original_characters": original_characters,
                "content_window": {
                    "start": 0,
                    "end": len(text),
                    "complete": original_characters == len(text),
                },
            }
        )
        role_bytes[role] = role_bytes.get(role, 0) + size
        seen_scripts.add(final)

    async def read(url, allowed, *, method="GET", request_body=None, kind="resource"):
        async with semaphore:
            remaining = 20_000_000 - budget["bytes"]
            if remaining <= 0 or time.monotonic() - started >= 63:
                raise PublicFileError("Browser collection allowance reached.")
            response = await asyncio.to_thread(
                read_public,
                url,
                allowed_hosts=allowed,
                before_request=lambda: reserve(kind),
                max_bytes=min(4_000_000, remaining),
                include_headers=True,
                method=method,
                request_body=request_body,
                user_agent=browser_user_agent,
                timeout_seconds=max(1, min(8, 63 - (time.monotonic() - started))),
                allow_statuses=tuple(range(200, 300)) + (400, 401, 403, 404, 405, 429, 500, 502, 503),
            )
            with budget_lock:
                budget["bytes"] += len(response[0])
                if budget["bytes"] > 20_000_000:
                    raise PublicFileError("Browser byte allowance reached.")
            return response

    async def settle(page):
        since = time.monotonic()
        while time.monotonic() - since < 3 and time.monotonic() - started < 62:
            await page.wait_for_timeout(200)
            if time.monotonic() - last_activity > 0.8:
                break

    try:
        root = await read(body.url, {domain}, kind="document")
        raw, initial_url, mime, headers, status = root
        html = decode_public_text(raw, mime)
        cache[initial_url] = root
        append_response(snapshot, body.url, initial_url, mime, headers, status, html, "document")
        pages.append(
            {"url": safe_url(initial_url), "html": html[:800000], "title": domain, "rendered": False, "http_status": status}
        )
        checkpoint(result())
        # Reserve useful entry bundles before executing a page whose vendor scripts
        # otherwise arrive first. Both prefetch and rendering use the same cache.
        links = LinkedFiles(initial_url)
        links.feed(html[:1_000_000])
        useful = [
            r
            for r in sorted(links.resources, key=lambda r: resource_priority(r, initial_url))
            if r["kind"] == "script" and resource_role(r["url"], context="script") == "application"
        ]
        for row in useful[:3]:
            p = urlsplit(row["url"])
            same = p.hostname == domain or bool(p.hostname and p.hostname.endswith("." + domain))
            if not same and not body.external_resources:
                continue
            try:
                response = await read(row["url"], {domain} if same else {p.hostname})
                cache[row["url"]] = response
                raw, final, mime, headers, status = response
                if status < 400:
                    retain_script(final, decode_public_text(raw, mime), initial_url, headers, mime)
            except (PublicFileError, ValueError, UnicodeError):
                note(
                    failures,
                    row["url"],
                    "Application entry resource unavailable.",
                    code="resource_collection",
                    stage="collection",
                )
        checkpoint(result())
        async with async_playwright() as runtime:
            stage = "startup"
            browser = await runtime.chromium.launch(**launch_options())
            launched = True
            stage = "collection"
            try:
                context = await browser.new_context(
                    service_workers="block",
                    accept_downloads=False,
                    viewport={"width": 1440, "height": 900},
                    device_scale_factor=1,
                    java_script_enabled=True,
                )
                context.set_default_timeout(1500)
                await context.route_web_socket("**/*", lambda socket: socket.close())
                page = await context.new_page()
                try:
                    agent = await page.evaluate("() => navigator.userAgent")
                    if isinstance(agent, str) and agent.startswith("Mozilla/") and len(agent) <= 512:
                        browser_user_agent = agent
                except Error:
                    pass
                # Retry a compatibility page with this isolated browser's own
                # identity; credentials and session headers remain excluded.
                initial_surface = surface_page(html, initial_url)
                if browser_user_agent and initial_surface and initial_surface.get("access_reason") == "unsupported_browser":
                    cache.pop(initial_url, None)
                    cache.pop(body.url, None)
                context.on(
                    "page", lambda extra: asyncio.create_task(extra.close()) if extra != page else None
                )
                page.on(
                    "pageerror",
                    lambda error: (
                        javascript_errors.append("script_error") if len(javascript_errors) < 100 else None
                    ),
                )
                page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
                session = await context.new_cdp_session(page)
                await session.send("Network.enable")

                def requested(event):
                    request = event.get("request", {})
                    url = request.get("url", "")
                    if url.startswith(("http://", "https://")) and len(traffic) < 300:
                        traffic.setdefault((url, request.get("method", "GET")), []).append(
                            {
                                "page_url": safe_url(page.url),
                                "initiator": initiator_record(event.get("initiator", {})),
                                "request_id": event.get("requestId"),
                            }
                        )

                session.on("Network.requestWillBeSent", requested)

                async def route_request(route):
                    nonlocal last_activity
                    request, url = route.request, route.request.url
                    try:
                        p = urlsplit(url)
                        same = p.hostname == domain or bool(p.hostname and p.hostname.endswith("." + domain))
                        if (
                            p.scheme not in {"http", "https"}
                            or p.username
                            or p.password
                            or p.port not in (None, 80, 443)
                        ):
                            raise PublicFileError("Invalid public address.")
                        operation, payload = None, None
                        if request.method != "GET":
                            if (
                                request.method != "POST"
                                or not body.read_only_operations
                                or not same
                                or budget["read_operations"] >= 3
                                or request.resource_type not in {"fetch", "xhr"}
                            ):
                                raise PublicFileError("Non-read request blocked.")
                            # A credentialed browser request cannot be replayed anonymously.
                            if any(
                                k.casefold() in {"authorization", "cookie", "x-api-key"}
                                for k in await request.all_headers()
                            ):
                                raise PublicFileError("Credentialed operation excluded.")
                            payload = request.post_data
                            operation = validate_read_operation(payload)
                            budget["read_operations"] += 1
                        if not same and (not body.external_resources or request.resource_type == "document"):
                            raise PublicFileError("External origin excluded by selected scope.")
                        if request.resource_type in {"image", "media", "font"}:
                            raise PublicFileError("Visual binary asset excluded.")
                        role = resource_role(url, context=request.resource_type)
                        if role == "tracking":
                            raise PublicFileError("Tracking resource excluded from executable acquisition.")
                        if role == "dependency" and budget["bytes"] >= 14_000_000:
                            raise PublicFileError(
                                "Dependency transfer allowance reached; application capacity reserved."
                            )
                    except (PublicFileError, ValueError) as exc:
                        note(
                            blocked,
                            url,
                            str(exc)[:180],
                            method=request.method,
                            resource_type=request.resource_type,
                            page_url=safe_url(page.url),
                        )
                        await route.abort()
                        return
                    try:
                        response = cache.get(url) if request.method == "GET" else None
                        if response is None:
                            response = await read(
                                url,
                                {domain} if same else {p.hostname},
                                method=request.method,
                                request_body=payload,
                                kind=request.resource_type,
                            )
                            if request.resource_type in {"script", "stylesheet"}:
                                cache[url] = response
                        raw, final, mime, headers, status = response
                        try:
                            text = decode_public_text(raw, mime)
                        except (UnicodeError, PublicFileError):
                            text = ""
                        if request.resource_type == "document" and status < 400:
                            # Prioritize entry bundles on every selected page.
                            linked = LinkedFiles(final)
                            linked.feed(text[:1_000_000])
                            entries = [r for r in sorted(linked.resources, key=lambda r: resource_priority(r, final)) if r["kind"] == "script" and resource_role(r["url"], context="script") == "application"]
                            for entry in entries[:3]:
                                target = urlsplit(entry["url"])
                                if target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password or target.port not in (None, 80, 443):
                                    continue
                                internal = target.hostname == domain or bool(target.hostname and target.hostname.endswith("." + domain))
                                if entry["url"] in cache or (not internal and not body.external_resources):
                                    continue
                                try:
                                    asset = await read(entry["url"], {domain} if internal else {target.hostname}, kind="script")
                                    cache[entry["url"]] = asset
                                    if asset[4] < 400:
                                        retain_script(asset[1], decode_public_text(asset[0], asset[2]), final, asset[3], asset[2])
                                except (PublicFileError, UnicodeError, ValueError):
                                    note(failures, entry["url"], "Application entry resource unavailable.", code="resource_collection", stage="collection")
                        append_response(
                            snapshot, url, final, mime, headers, status, text, request.resource_type
                        )
                        observation = snapshot["responses"][-1]
                        observation.update(
                            page_url=safe_url(page.url),
                            bytes=len(raw),
                            method=request.method,
                            resource_role=resource_role(
                                final, mime=mime, content=text, context=request.resource_type
                            ),
                        )
                        if operation:
                            observation["read_operation"] = operation
                        if status >= 400:
                            note(
                                failures,
                                url,
                                f"HTTP {status} response.",
                                code="resource_collection",
                                stage="collection",
                                resource_type=request.resource_type,
                            )
                        if (
                            request.resource_type in {"fetch", "xhr"}
                            and "json" in mime
                            and len(raw) <= 200_000
                            and status < 400
                        ):
                            try:
                                observation["response_shape"] = shape(json.loads(text))
                            except (ValueError, RecursionError):
                                pass
                        kind = (
                            "script"
                            if request.resource_type == "script"
                            else "stylesheet"
                            if request.resource_type == "stylesheet"
                            else "request"
                        )
                        if final not in seen_resources:
                            snapshot["resources"].append(
                                {
                                    "url": safe_url(final),
                                    "kind": kind,
                                    "observed": status < 400,
                                    "status": status,
                                    "resource_role": observation["resource_role"],
                                }
                            )
                            seen_resources.add(final)
                        if kind == "script" and status < 400:
                            retain_script(final, text, page.url, headers, mime)
                        forwarded = {
                            k: v
                            for k, v in headers.items()
                            if k
                            in {
                                "content-type",
                                "cache-control",
                                "content-security-policy",
                                "access-control-allow-origin",
                                "access-control-allow-credentials",
                            }
                        }
                        await route.fulfill(status=status, headers=forwarded, body=raw)
                        last_activity = time.monotonic()
                    except (PublicFileError, ValueError, UnicodeError) as exc:
                        allowance = isinstance(exc, PublicFileError) and "allowance" in str(exc).casefold()
                        note(
                            blocked if allowance else failures,
                            url,
                            str(exc)[:180] if allowance else "Public resource read failed.",
                            code="resource_allowance" if allowance else "resource_collection",
                            stage="collection",
                            method=request.method,
                            resource_type=request.resource_type,
                        )
                        await route.abort()

                await context.route("**/*", route_request)
                disclosed = public_navigation({"navigation": [{"url": v, "label": "Published page"} for v in body.published_pages if isinstance(v, str) and len(v) <= 2048]}, domain)
                candidates = list(dict.fromkeys([initial_url, *disclosed]))
                while candidates and len(seen_pages) < body.page_limit and time.monotonic() - started < 55:
                    url = candidates.pop(0)
                    if url in seen_pages:
                        continue
                    seen_pages.add(url)
                    before = len(scripts) + len(snapshot["responses"])
                    navigated = False
                    try:
                        await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=min(22000, max(1000, int((62 - (time.monotonic() - started)) * 1000))),
                        )
                        navigated = True
                        await settle(page)
                        controls = page.locator(
                            '[role="tab"], summary, button[aria-expanded], button[aria-haspopup]'
                        )
                        for index in range(min(await controls.count(), 12)):
                            if (
                                len(interactions) >= body.interaction_limit
                                or time.monotonic() - started >= 55
                            ):
                                break
                            control = controls.nth(index)
                            try:
                                role = await control.get_attribute("role") or await control.evaluate(
                                    "e => e.tagName.toLowerCase()"
                                )
                                label = (
                                    await control.get_attribute("aria-label") or await control.inner_text()
                                )[:100].strip()
                                if (
                                    not safe_control(
                                        label,
                                        role,
                                        expanded=await control.get_attribute("aria-expanded"),
                                        has_popup=await control.get_attribute("aria-haspopup"),
                                    )
                                    or not await control.is_visible()
                                    or await control.evaluate("e => !!e.closest('form')")
                                ):
                                    continue
                                await control.click(timeout=800, no_wait_after=True)
                                interactions.append(
                                    {
                                        "page_url": safe_url(page.url),
                                        "label": label,
                                        "role": role,
                                        "status": "inspected",
                                    }
                                )
                                await settle(page)
                            except Error:
                                note(
                                    failures,
                                    url,
                                    "Disclosure control could not be inspected.",
                                    code="interaction",
                                    stage="navigation",
                                )
                    except BrowserTimeout:
                        note(
                            failures,
                            url,
                            "Page navigation reached its timeout.",
                            code="navigation_timeout",
                            stage="navigation",
                        )
                    except Error:
                        note(
                            failures,
                            url,
                            "Page navigation failed.",
                            code="navigation_failed",
                            stage="navigation",
                        )
                    try:
                        html = await page.evaluate(
                            "() => document.documentElement.outerHTML.slice(0, 800000)"
                        )
                        title = (await page.title())[:120]
                    except Error:
                        html, title = "", domain
                    if html and page.url.startswith(("http://", "https://")):
                        main_status = next((r.get("status") for r in reversed(snapshot["responses"]) if r.get("resource_type") == "document" and r.get("final_url") == safe_url(page.url)), None)
                        surface = surface_page(html, page.url, http_status=main_status)
                        if surface:
                            if surface.get("content_available", True):
                                surface.update(status="inspected" if navigated else "partial")
                            surface.update(rendered=True)
                            snapshot["surface"].append(surface)
                            candidates.extend(
                                v
                                for v in page_candidates(surface, domain)
                                if v not in seen_pages and v not in candidates
                            )
                        snapshot["signals"].extend(
                            {**row, "basis": "rendered_markup"}
                            for row in signatures(html, page.url, "text/html")
                        )
                        row = {"url": safe_url(page.url), "html": html, "title": title, "rendered": True, "http_status": main_status}
                        if len(pages) == 1 and pages[0]["url"] == row["url"] and not pages[0]["rendered"]:
                            pages[0] = row
                        else:
                            pages.append(row)
                    gains.append(max(0, len(scripts) + len(snapshot["responses"]) - before))
                    checkpoint(result())
                for row in [*snapshot["responses"], *blocked]:
                    key = next(
                        (k for k in traffic if safe_url(k[0]) == row["url"] and k[1] == row.get("method")),
                        None,
                    )
                    if key and traffic[key]:
                        row.update(traffic[key].pop(0))
                await context.close()
                for script in sorted(
                    scripts, key=lambda s: resource_priority({"url": s["url"], "role": s["resource_role"]})
                ):
                    if script["resource_role"] != "application":
                        continue
                    refs = ([script["source_map"]] if script.get("source_map") else []) + re.findall(
                        r"(?m)//[#@]\s*sourceMappingURL=([^\s]+)", script["content"]
                    )[-1:]
                    for reference in refs[:1]:
                        if (
                            not isinstance(reference, str)
                            or reference.startswith("data:")
                            or len(maps) >= 4
                            or time.monotonic() - started >= 63
                        ):
                            continue
                        url = urljoin(script["url"], reference)
                        p = urlsplit(url)
                        if not p.hostname or (p.hostname != domain and not body.external_resources):
                            continue
                        try:
                            raw, final, mime, headers, status = await read(url, {p.hostname})
                            if status == 200:
                                maps.append(
                                    {
                                        "url": safe_url(final),
                                        "content": decode_public_text(raw, mime),
                                        "script_url": script["url"],
                                        "page_url": script.get("page_url"),
                                    }
                                )
                        except (PublicFileError, ValueError, UnicodeError):
                            note(
                                failures,
                                url,
                                "Declared source map unavailable.",
                                code="resource_collection",
                                stage="collection",
                            )
            finally:
                await browser.close()
    except Exception as exc:
        logging.getLogger("prisma.browser").error("Capture stage failed: %s", type(exc).__name__)
        note(
            failures,
            body.url,
            "Chromium could not launch."
            if stage == "startup"
            else "Public acquisition stopped; completed evidence was retained.",
            code="browser_startup" if stage == "startup" else "resource_collection",
            stage=stage,
        )
    return result(final=True)
