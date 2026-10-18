"""Read supplied HAR request records; this adapter never sends network requests."""
import json
import re
from urllib.parse import urlsplit
from .repository import make


def har_facts(evidence):
    for item in evidence:
        if not item.source_url.casefold().endswith(".har"):
            continue
        try:
            data = json.loads(item.content)
            entries = data.get("log", {}).get("entries", [])
        except (ValueError, TypeError, AttributeError):
            continue
        if not isinstance(entries, list):
            continue
        context = "traffic:" + item.source_url[-100:]
        for entry in entries[:1000]:
            if not isinstance(entry, dict):
                continue
            request, response = entry.get("request") or {}, entry.get("response") or {}
            if not isinstance(request, dict) or not isinstance(response, dict):
                continue
            url, method = request.get("url"), request.get("method")
            if not isinstance(url, str) or method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                continue
            needle = json.dumps(url, ensure_ascii=False)
            if needle not in item.content:
                needle = json.dumps(url)
            host = parsed.hostname[:100]
            common = {"context": context, "source_path": item.source_url}
            yield make(item, "component", "Browser session", needle, "Client request records retained in the supplied HAR capture.", component_kind="frontend", **common)
            yield make(item, "component", host, needle, "HTTP host addressed by the recorded client requests.", component_kind="resource", **common)
            yield make(item, "connection", "recorded HTTP request", needle, "Request recorded in the supplied capture.", source_name="Browser session", target_name=host, attributes={"relationship_kind": "captured_request", "method": method, "path": parsed.path or "/", "status": response.get("status"), "initiator": entry.get("_initiator") if isinstance(entry.get("_initiator"), dict) else None}, **common)
            # Recorded image, script and style reads are delivery evidence, not API operations.
            mime = str((response.get("content") or {}).get("mimeType", "")) if isinstance(response.get("content"), dict) else ""
            binary_or_asset = bool(re.search(r"\.(?:js|mjs|css|map|png|jpe?g|svg|gif|webp|ico|woff2?|ttf|otf|mp4)$", parsed.path, re.I)) or mime.startswith(("image/", "font/", "text/css", "text/html", "application/javascript"))
            if len(parsed.path or "/") <= 300 and not binary_or_asset:
                yield make(item, "endpoint", method + " " + (parsed.path or "/"), needle, "Request route recorded in the supplied HAR capture.", method=method, path=parsed.path or "/", source_name=host, attributes={"capture_status": response.get("status"), "captured_host": host, "contract_basis": "captured_request", "response_shape": (response.get("content") or {}).get("_shape"), "request_shape": request.get("_bodyShape")}, **common)
