"""Bounded public client-code evidence. Literal references are never runtime proof."""
import hashlib
import json
import posixpath
import re
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit

from .schemas import ImportedSource
from .web_observation import safe_url, shape


def retained_public_metadata(signals, method):
    """Safe acquisition context for reanalysis/import, never original claims."""
    signals = signals if isinstance(signals, dict) else {}
    original = signals.get("original_collection_method") or method
    result = {"original_collection_method": original} if original in {"browser_script", "browser_dom", "public_file", "source_map", "public_observation", "browser_observation"} else {}
    for key in ("public_page", "linked_from", "derived_from", "embedded_path", "source_map_section", "resource_role", "response_content_type"):
        value = signals.get(key)
        if isinstance(value, str) and len(value) <= 2048:
            result[key] = value
    for key in ("compiled_asset", "inline", "rendered", "path_conflict"):
        if isinstance(signals.get(key), bool):
            result[key] = signals[key]
    if isinstance(signals.get("source_map_index"), int):
        result["source_map_index"] = signals["source_map_index"]
    window = signals.get("content_window")
    if isinstance(window, dict) and all(isinstance(window.get(k), int) and not isinstance(window.get(k), bool) for k in ("start", "end")) and isinstance(window.get("complete"), bool):
        result["content_window"] = {k: window[k] for k in ("start", "end", "complete")}
    if isinstance(signals.get("original_characters"), int):
        result["original_characters"] = signals["original_characters"]
    if isinstance(signals.get("response_status"), int) and not isinstance(signals["response_status"], bool) and 100 <= signals["response_status"] <= 599:
        result["response_status"] = signals["response_status"]
    access = signals.get("page_access")
    if isinstance(access, dict):
        clean = {k: access[k][:500] for k in ("status", "access", "access_reason", "access_text") if isinstance(access.get(k), str)}
        if isinstance(access.get("content_available"), bool):
            clean["content_available"] = access["content_available"]
        result["page_access"] = clean
    return result


class PageScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.current, self.parts = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.current, self.parts = dict(attrs), []

    def handle_data(self, data):
        if self.current is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            text = "".join(self.parts)
            if not self.current.get("src") and text.strip() and len(text) <= 500_000 and len(self.scripts) < 16:
                self.scripts.append((self.current, text))
            self.current = None


def inline_sources(html, url):
    parser = PageScripts()
    parser.feed(html)
    for index, (attrs, text) in enumerate(parser.scripts):
        kind = attrs.get("type", "").casefold()
        if kind in {"application/json", "application/ld+json"}:
            # Hydration values may contain user records. Preserve the data contract only.
            try:
                text = json.dumps({"contract": "prisma.hydration.v1", "page": safe_url(url), "script_id": attrs.get("id", "")[:100], "shape": shape(json.loads(text))}, ensure_ascii=False, indent=2)
            except (ValueError, RecursionError):
                continue
            format = "json"
        elif kind in {"", "module", "text/javascript", "application/javascript"}:
            format = "javascript"
        else:
            continue
        identity = hashlib.sha256(url.encode()).hexdigest()[:16]
        from .resource_policy import resource_role
        yield ImportedSource(title=f"Inline script {index + 1}", origin=f"local:web/{identity}/inline-{index}.{ 'js' if format == 'javascript' else 'json'}", format=format, content=text), {"collection_method": "browser_script", "linked_from": safe_url(url), "public_page": safe_url(url), "inline": True, "resource_role": resource_role(url + ".js", content=text)}


def source_map_sources(text, url, *, maximum=80, page_url=None):
    """Embedded original sources only, including indexed maps. No guessed source reads."""
    from .source_analysis import file_format
    from .source_intake import path_reason
    try:
        root = json.loads(text)
    except (ValueError, RecursionError):
        return
    stack, used, chars = [(root, "root")], 0, 0
    parsed_map = urlsplit(url)
    identity = hashlib.sha256((parsed_map.scheme + "://" + parsed_map.netloc).encode()).hexdigest()[:16]
    while stack and used < maximum:
        document, section = stack.pop()
        if not isinstance(document, dict) or document.get("version") != 3:
            continue
        sections = document.get("sections", [])
        for index, row in reversed(list(enumerate(sections[:32] if isinstance(sections, list) else []))):
            if isinstance(row, dict) and isinstance(row.get("map"), dict) and len(section.split(".")) < 5:
                stack.append((row["map"], section + "." + str(index)))
        names, contents = document.get("sources"), document.get("sourcesContent")
        if not isinstance(names, list) or not isinstance(contents, list):
            continue
        for index, (name, content) in enumerate(zip(names[:maximum], contents[:maximum])):
            if used >= maximum or not isinstance(name, str) or not isinstance(content, str) or not content.strip() or len(content.encode()) > 1_000_000:
                continue
            parsed_name = urlsplit(name) if "://" in name else None
            candidate = (parsed_name.path if parsed_name else name).removeprefix("./").lstrip("/")
            # Source maps commonly address ../src relative to an output folder.
            # Embedded code is never extracted to disk; use a safe virtual root.
            while candidate.startswith("../"):
                candidate = candidate[3:]
            candidate = posixpath.normpath(candidate)
            if any(part.casefold().startswith(".env") for part in PurePosixPath(candidate).parts) or path_reason(candidate) or len(PurePosixPath(candidate).parts) > 30 or chars + len(content) > 3_000_000:
                continue
            used += 1
            chars += len(content)
            namespace = hashlib.sha256((parsed_name.netloc if parsed_name else str(document.get("sourceRoot", ""))).encode()).hexdigest()[:10]
            source = ImportedSource(title=PurePosixPath(candidate).name[:120], origin=f"local:sourcemap/{identity}/{namespace}/" + candidate, format=file_format(candidate), content=content)
            yield source, {"collection_method": "source_map", "derived_from": safe_url(url), "source_map_index": index, "source_map_section": section, "embedded_path": name[:1024], "public_page": safe_url(page_url or url), "resource_role": "application"}


def public_code_facts(item):
    """Client HTTP calls with literal addresses, also useful on minified shipped code."""
    signals = item.signals or {}
    method = signals.get("original_collection_method") or signals.get("collection_method")
    if item.source_type not in {"javascript", "typescript"} or method not in {"browser_script", "public_file", "source_map"}:
        return
    from .document_facts import anchor_fact
    base = (item.signals or {}).get("public_page") or (item.signals or {}).get("linked_from") or item.source_url
    calls = re.compile(r"(?P<call>\bfetch|\baxios\.(?:get|post|put|patch|delete|head)|\bnew\s+WebSocket)\s*\(\s*(?P<quote>['\"])(?P<url>[^'\"\r\n]{1,600})(?P=quote)")
    seen = set()
    for match in list(calls.finditer(item.content[:2_000_000]))[:200]:
        value = match["url"]
        if "${" in value or not (value.startswith(("/", "https://", "http://", "wss://", "ws://"))):
            continue
        try:
            url = safe_url(urljoin(base, value))
            parsed = urlsplit(url)
        except ValueError:
            continue
        if not parsed.hostname or parsed.username or parsed.password:
            continue
        socket = "WebSocket" in match["call"]
        method = match["call"].split(".")[-1].upper() if match["call"].startswith("axios.") else "GET"
        # An explicit literal method in fetch's options; defaults are reported as static references.
        if match["call"] == "fetch":
            tail = item.content[match.end():match.end() + 400]
            explicit = re.match(r"\s*,\s*\{[^{}]{0,250}?\bmethod\s*:\s*['\"](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['\"]", tail, re.I)
            if explicit:
                method = explicit[1].upper()
            elif re.match(r"\s*,", tail):
                method = None
        key = (url, method, socket)
        if key in seen:
            continue
        seen.add(key)
        common = {"context": "public surface", "attributes": {"contract_basis": "static_client_reference", "resource_url": safe_url(item.source_url), "address": url, "transport": "websocket" if socket else "http"}}
        label = ("Realtime interface " if socket else "API interface ") + parsed.hostname
        yield anchor_fact(item, "component", label[:100], "Literal client interface referenced by the shipped script.", match.start(), match.end(), component_kind="api", **common)
        yield anchor_fact(item, "connection", "references WebSocket" if socket else "references " + (method or "HTTP"), "Static client call; execution is established separately by traffic records.", match.start(), match.end(), source_name="Web client", target_name=label[:100], **common)
        if not socket and method and len(parsed.path or "/") <= 300:
            yield anchor_fact(item, "endpoint", method + " " + (parsed.path or "/"), "Literal route referenced by shipped client code.", match.start(), match.end(), method=method, path=parsed.path or "/", source_name=label[:100], **common)
