"""Published product wording and instructions, never claimed as executed workflows."""

import re
from urllib.parse import urljoin, urlsplit

from .page_access import document_access

ACTION = re.compile(r"\b(?:create|edit|design|collaborate|share|import|upload|select|export|publish|organize|manage|enhance|resize|remove|generate|comment|track|sync|save|click|tap|drag)\w*\b", re.I)


def document_surface(source):
    if source.source_type not in {"markdown", "text"} or not source.source_url.startswith(("http://", "https://")):
        return None
    if urlsplit(source.source_url).path.rstrip("/").rsplit("/", 1)[-1].casefold() == "robots.txt":
        return None
    text = source.content[:200000]
    headings = list(re.finditer(r"(?m)^(#{1,3})\s+([^\n]{3,180})$", text))[:100]
    title = headings[0][2].strip() if headings else (source.signals or {}).get("title", "")
    state = document_access(text, title)
    result = {"url": source.source_url, "title": title or urlsplit(source.source_url).path, "description": "", "navigation": [], "forms": [], "controls": [], "public_features": [], "documented_workflows": [], "rendered": False, **state}
    if not state["content_available"]:
        return result
    result["status"] = "publicly_documented"
    paragraphs = list(re.finditer(r"(?m)^(?!\s*(?:#|[-*]|```|\d+\.))[^\n]{40,600}$", text))
    for paragraph in paragraphs[:12]:
        value = paragraph[0].strip()
        if not re.search(r"skip (?:to|the)|start of|end of|@|https?://", value, re.I) and ACTION.search(value):
            result["description"] = value[:500]
            break
    seen = set()
    for index, heading in enumerate(headings):
        label = heading[2].strip()
        if label.casefold() in seen or re.search(r"testimonials|footer", label, re.I):
            continue
        seen.add(label.casefold())
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end():end].strip()
        if len(heading[1]) >= 2 and ACTION.search(label) and 12 <= len(label) <= 160:
            result["public_features"].append({"text": label, "description": block[:400], "status": "publicly_documented", "commercial_scope": "public_wording"})
        candidates = [p[0].strip() for p in re.finditer(r"(?m)^(?:\*\s+)?[^\n]{50,900}$", block)][:12]
        for paragraph in candidates:
            if len(ACTION.findall(paragraph)) >= 3 and re.search(r"\b(?:then|once|after|first|next|under|steps?|to do this)\b", paragraph, re.I):
                workflow_title = title if re.search(r"frequently asked", label, re.I) else label
                result["documented_workflows"].append({"title": workflow_title, "description": paragraph[:500], "status": "publicly_documented", "kind": "documented_workflow", "execution": "not_tested"})
                break
        if len(result["public_features"]) >= 16:
            break
    for link in list(re.finditer(r"\[([^\]\n]{3,100})\]\(([^\s)]+)\)", text))[:80]:
        url = urljoin(source.source_url, link[2])
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and (parsed.hostname or "").removeprefix("www.") == (urlsplit(source.source_url).hostname or "").removeprefix("www.") and not parsed.username and not parsed.password:
            result["navigation"].append({"url": url, "label": link[1]})
    # Explicit commercial terms remain publisher claims, including conflicts.
    commercial = list(re.finditer(r"(?m)^(?!\s*(?:#|```))(?:[-*]\s+)?[^\n]{40,900}$", text))
    for paragraph in commercial:
        value = paragraph[0].strip().lstrip("*- ")
        if re.search(r"\b(?:available to|included (?:in|with)|premium features|upgrade to|requires (?:a|the)|pro users|paid plan|per seat|per month)\b", value, re.I):
            result["public_features"].append({"text": value[:500], "status": "publicly_documented", "commercial_scope": "public_wording"})
            if len(result["public_features"]) >= 24:
                break
    return result
