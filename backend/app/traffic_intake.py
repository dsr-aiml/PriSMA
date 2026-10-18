"""HAR privacy boundary: retain protocol/shape, never cookies or payload values."""
import json
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .web_observation import safe_url, shape

SAFE_HEADERS = {"content-type", "server", "x-powered-by", "x-vercel-id", "cf-ray", "cache-control", "access-control-allow-origin"}
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def safe_shape(value, depth=0):
    if depth > 4:
        return "value"
    if isinstance(value, dict):
        return {str(k)[:80]: safe_shape(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [safe_shape(value[0], depth + 1)] if value else []
    return value if isinstance(value, str) and value in {"null", "boolean", "number", "string", "object", "array", "value"} else "value"


def private_url(url):
    value = urlsplit(safe_url(url))
    return urlunsplit((value.scheme, value.netloc, value.path, urlencode([(key, "[redacted]") for key, _ in parse_qsl(value.query, keep_blank_values=True)]), ""))


def sanitize_har(document):
    entries = document.get("log", {}).get("entries", []) if isinstance(document, dict) and isinstance(document.get("log"), dict) else None
    if not isinstance(entries, list):
        raise ValueError("Invalid HAR entries")
    clean = []
    retained_characters = 0
    for entry in entries[:1000]:
        if not isinstance(entry, dict):
            continue
        request, response = entry.get("request"), entry.get("response")
        if not isinstance(request, dict) or not isinstance(response, dict) or request.get("method") not in METHODS or not isinstance(request.get("url"), str):
            continue
        parsed = urlsplit(request["url"])
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            continue
        content = response.get("content") if isinstance(response.get("content"), dict) else {}
        result = {"request": {"method": request["method"], "url": private_url(request["url"]), "headers": []}, "response": {"status": response.get("status") if isinstance(response.get("status"), int) else 0, "content": {"mimeType": str(content.get("mimeType", ""))[:160]}, "headers": []}, "_resourceType": str(entry.get("_resourceType", ""))[:40]}
        for side in ("request", "response"):
            headers = entry[side].get("headers", [])
            result[side]["headers"] = [{"name": h["name"].casefold(), "value": h["value"][:1000]} for h in headers[:100] if isinstance(h, dict) and isinstance(h.get("name"), str) and isinstance(h.get("value"), str) and h["name"].casefold() in SAFE_HEADERS] if isinstance(headers, list) else []
        initiator = entry.get("_initiator")
        if isinstance(initiator, dict):
            result["_initiator"] = {"type": str(initiator.get("type", "unknown"))[:40]}
            stack = initiator.get("stack", {})
            frames = stack.get("callFrames", []) if isinstance(stack, dict) else []
            for frame in frames[:8] if isinstance(frames, list) else []:
                if isinstance(frame, dict) and isinstance(frame.get("url"), str) and frame["url"].startswith(("http://", "https://")):
                    result["_initiator"]["url"] = private_url(frame["url"])
                    break
        if "_shape" in content:
            result["response"]["content"]["_shape"] = safe_shape(content["_shape"])
        if "_bodyShape" in request:
            result["request"]["_bodyShape"] = safe_shape(request["_bodyShape"])
        text = content.get("text")
        if isinstance(text, str) and len(text) <= 200000 and "json" in str(content.get("mimeType", "")) and not content.get("encoding"):
            try:
                result["response"]["content"]["_shape"] = shape(json.loads(text))
            except (ValueError, RecursionError):
                pass
        post = request.get("postData")
        if isinstance(post, dict) and isinstance(post.get("text"), str) and len(post["text"]) <= 200000 and "json" in str(post.get("mimeType", "")):
            try:
                result["request"]["_bodyShape"] = shape(json.loads(post["text"]))
            except (ValueError, RecursionError):
                pass
        size = len(json.dumps(result, ensure_ascii=False, indent=2))
        if retained_characters + size > 1_650_000:
            break
        retained_characters += size
        clean.append(result)
    return {"log": {"version": "1.2", "creator": {"name": "PriSMA", "version": "sanitized-traffic-1"}, "entries": clean}, "privacy": "Headers, cookies and payload values removed; retained bodies describe types only.", "excluded_entries": max(0, len(entries) - len(clean)) + (document.get("excluded_entries", 0) if document.get("privacy") and isinstance(document.get("excluded_entries"), int) and 0 <= document["excluded_entries"] <= 20000 else 0)}
