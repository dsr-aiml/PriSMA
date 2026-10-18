"""Bounded access observations; a public pricing mention is never a paywall."""

import re


def page_access(title="", text="", *, http_status=None, password_form=False, challenge_form=False):
    heading = re.sub(r"\s+", " ", title).strip()[:300]
    lead = re.sub(r"\s+", " ", text).strip()[:1600]
    # Long product documentation often mentions signup or paid plans. Only
    # opening gate copy and page headings establish restricted page content.
    probe = heading + "\n" + (lead[:500] if len(lead) <= 650 else "")
    if challenge_form or (len(lead) < 650 and re.search(r"^(?:click (?:the )?button below to continue|robot check|security verification|please verify your identity)", lead, re.I)):
        return {"status": "collection_failed", "access": "unknown", "access_reason": "access_challenge", "access_text": "Verification page", "content_available": False}
    rules = (
        (r"unsupported (?:client|browser)|please update your browser", "collection_failed", "unsupported_browser"),
        (r"verify (?:that )?you are human|checking your browser|__cf_chl_opt|enable javascript and cookies to continue|captcha", "collection_failed", "access_challenge"),
        (r"subscribe to (?:continue|read|unlock|access)|subscription required|subscribers?[- ]only|paywall|upgrade (?:your plan )?to (?:access|unlock|continue)|purchase (?:a )?subscription to", "requires_subscription", "subscription_required"),
        (r"(?:sign[ -]?in|log[ -]?in) (?:is required|to (?:continue|access|view|read))|authentication required|you must (?:sign[ -]?in|log[ -]?in)", "requires_login", "authentication_required"),
        (r"access denied|permission denied|forbidden", "collection_failed", "access_denied"),
        (r"^(?:error\s*\(?[45]\d\d\)?|internal server error|service unavailable|page not found|something went wrong|sorry, we had an unexpected error)", "collection_failed", "error_page"),
    )
    for pattern, state, reason in rules:
        match = re.search(pattern, probe, re.I | re.M)
        if state in {"requires_login", "requires_subscription"} and not re.search(pattern, heading, re.I):
            opening = lead[len(heading):].lstrip() if heading and lead.casefold().startswith(heading.casefold()) else lead
            if not re.match(r"(?:please\s+)?(?:" + pattern + r")", opening, re.I):
                continue
        if match:
            return {"status": state, "access": state if state.startswith("requires_") else "unknown", "access_reason": reason, "access_text": match[0], "content_available": False}
    if http_status == 401 or (password_form and re.search(r"\b(?:sign[ -]?in|log[ -]?in|account access)\b", heading, re.I)):
        return {"status": "requires_login", "access": "requires_login", "access_reason": "authentication_required", "access_text": heading, "content_available": False}
    if isinstance(http_status, int) and http_status >= 400:
        return {"status": "collection_failed", "access": "unknown", "access_reason": "http_" + str(http_status), "access_text": heading, "content_available": False}
    return {"status": "inspected", "access": "public", "access_reason": "", "access_text": "", "content_available": True}


def document_access(text, title="", *, http_status=None):
    """Use opening headings rather than arbitrary login/paid mentions in a document."""
    lines = [line.strip().lstrip("# ") for line in text[:4000].splitlines() if line.strip()]
    heading = next((line for line in lines[:6] if not line.startswith(("<", "[", "```"))), title)
    return page_access(heading or title, " ".join(lines[:8]), http_status=http_status)



def surface_access(page):
    forms = [form for form in page.get("forms", []) if isinstance(form, dict)]
    return page_access(page.get("title", ""), page.get("description", ""), http_status=page.get("http_status"),
                       password_form=any(field.get("type") == "password" for form in forms for field in form.get("fields", []) if isinstance(field, dict)),
                       challenge_form=any(re.search(r"captcha|challenge-platform|challenge-response|verify[-_]?human", form.get("action", ""), re.I) for form in forms))

def observation_access(snapshot):
    """Useful rendered coverage is separate from Chromium's transport readiness."""
    states = {}
    for page in snapshot.get("surface", [])[:24]:
        if not isinstance(page, dict):
            continue
        fresh = surface_access(page)
        available = fresh["content_available"] and page.get("content_available", True)
        rendered = bool(page.get("rendered"))
        row = states.setdefault(page.get("url", ""), {"inspected": False, "blocked": False})
        row["inspected"] |= available and rendered
        row["blocked"] |= not available
    if not states:
        return {"content_status": "not_rendered", "rendered_inspected_pages": 0, "access_blocked_pages": 0}
    inspected = sum(row["inspected"] for row in states.values())
    blocked = sum(row["blocked"] and not row["inspected"] for row in states.values())
    return {"content_status": "partial" if inspected and blocked else "available" if inspected else "blocked" if blocked else "not_rendered",
            "rendered_inspected_pages": inspected, "access_blocked_pages": blocked}


def apply_content_coverage(snapshot):
    coverage = snapshot.setdefault("coverage", {})
    coverage.update(observation_access(snapshot))
    if coverage["content_status"] == "blocked" and coverage.get("status") == "complete":
        coverage.update(transport_status="complete", status="partial", stop_reason="access_barrier")
    return snapshot
