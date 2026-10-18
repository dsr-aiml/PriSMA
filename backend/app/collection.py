"""Opt-in TinyFish Search/Fetch only. Remote pages never trigger Agent/Browser calls."""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit, urlunsplit

import httpx
from redis import Redis

from .config import settings
from .models import ModelCache, now
from .schemas import ImportedSource, normalize_domain
from .target_scope import document_scope


class CollectionFailure(Exception):
    pass


def scoped_url(value, domain):
    if not isinstance(value, str):
        return None
    try:
        p = urlsplit(value)
        host = normalize_domain(p.hostname or "")
        if p.scheme not in ("http", "https") or p.username or p.password or p.port not in (None, 80, 443):
            return None
        scope_host = domain.removeprefix("www.")
        if host.removeprefix("www.") != scope_host and not host.endswith("." + scope_host):
            return None
        if len(value) > 2048 or any(ord(c) < 32 for c in value):
            return None
        return urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))
    except (ValueError, UnicodeError):
        return None


def document_exclusion(url):
    """Conservative document crawl policy, independent of the assessed host.

    Being on-domain does not establish authorship or relevance. Payload mirrors
    and generated responses are excluded before spending a Fetch allowance.
    These guards do not certify the relevance of every remaining document.
    """
    parts = urlsplit(url)
    segments = [unquote(segment).casefold() for segment in parts.path.split("/") if segment]
    if any(segment.startswith(".env") or segment in {"credentials.json", "id_rsa", "id_ed25519", "service-account.json"} or segment.endswith((".pem", ".key")) for segment in segments):
        return "credential_file"
    if any(len(segment) > 128 for segment in segments):
        return "encoded_or_oversized_path"
    if any(re.search(r"[{}<>]", segment) for segment in segments):
        return "parameterized_endpoint"
    if segments and segments[0] in ("base64", "decode", "encode", "echo", "reflect", "redirect-to"):
        return "generated_content_endpoint"
    if any(
        key.casefold()
        in {
            "body",
            "html",
            "payload",
            "content",
            "data",
            "url",
            "redirect",
            "redirect_uri",
            "redirect_url",
            "access_token",
            "token",
        }
        for key, _ in parse_qsl(parts.query)
    ):
        return "parameterized_content"
    if re.search(
        r"\.(png|jpe?g|gif|webp|svg|ico|woff2?|ttf|otf|mp[34]|zip|tar|gz|exe|dmg)$", parts.path, re.I
    ):
        return "non_document_asset"
    return None


def document_priority(url):
    parts = urlsplit(url)
    if parts.path in ("", "/") and not parts.query:
        return 0
    words = set(re.findall(r"[a-z0-9]+", unquote(parts.path).casefold()))
    if words & {"openapi", "swagger", "spec", "specification", "architecture"}:
        return 1
    if words & {"docs", "documentation", "reference", "api", "developer", "developers"} or (
        parts.hostname or ""
    ).split(".")[0] in {"docs", "developer", "developers"}:
        return 2
    if words & {"pricing", "plans", "integrations", "features", "platform", "security", "technology"}:
        return 3
    return 4


RESERVE = """
for i,key in ipairs(KEYS) do
 if tonumber(redis.call('GET',key) or '0') + tonumber(ARGV[1]) > tonumber(ARGV[i*2]) then return 0 end
end
for i,key in ipairs(KEYS) do
 redis.call('INCRBY',key,ARGV[1]); redis.call('EXPIRE',key,ARGV[i*2+1])
end
return 1
"""


class UsageBudget:
    def __init__(self):
        cfg = settings()
        self.redis = Redis.from_url(cfg.redis_url, socket_timeout=3, socket_connect_timeout=3)
        self.account = hashlib.sha256(cfg.tinyfish_api_key.encode()).hexdigest()[:20]

    def reserve(self, product, count=1):
        cfg = settings()
        stamp = datetime.now(timezone.utc)
        limits = [
            (
                stamp.strftime("%Y%m%d"),
                cfg.tinyfish_search_daily_limit if product == "search" else cfg.tinyfish_fetch_daily_limit,
                172800,
            ),
            (stamp.strftime("%Y%m%d%H%M"), 20 if product == "search" else 100, 120),
            (stamp.strftime("%Y%m%d%H"), 200 if product == "search" else 1000, 7200),
        ]
        keys = [f"prisma:collection:{self.account}:{product}:{window}" for window, _, _ in limits]
        args = [count] + [v for _, limit, expiry in limits for v in (limit, expiry)]
        try:
            permitted = self.redis.eval(RESERVE, len(keys), *keys, *args)
        except Exception as exc:
            raise CollectionFailure("Collection accounting is unavailable. No request was sent.") from exc
        if not permitted:
            raise CollectionFailure(
                "The application collection allowance is exhausted. Retry after the allowance resets."
            )


class TinyFishCollector:
    def __init__(
        self,
        db,
        user_id,
        *,
        budget=None,
        transport=None,
        analysis_provider=None,
        options=None,
        stop=lambda: None,
    ):
        self.db, self.user_id = db, user_id
        self.budget = budget or UsageBudget()
        self.transport = transport
        self.analysis_provider = analysis_provider
        self.options, self.stop = options or {}, stop
        self.saved_records = []
        self.deadline = time.monotonic() + 300
        self.record = {
            "provider": "tinyfish_search_fetch",
            "search_attempts": 0,
            "url_attempts": 0,
            "cache_hits": 0,
            "outcomes": [],
            "status": "pending",
            "limits": {
                "searches": min(
                    self.options.get("search_limit", settings().tinyfish_searches_per_run),
                    settings().tinyfish_search_max_per_run,
                ),
                "url_attempts": min(
                    self.options.get("fetch_limit", settings().tinyfish_fetch_attempts_per_run),
                    settings().tinyfish_fetch_max_per_run,
                ),
            },
            "policy": "document-selection-7",
            "search_queries": 0,
            "visited_urls": 0,
            "started_at": now().isoformat(),
        }

    def request(self, product, payload):
        self.stop()
        cfg = settings()
        if time.monotonic() + 45 > self.deadline:
            raise CollectionFailure(
                "The collection time budget has been reached. Collected documents are retained."
            )
        if not cfg.tinyfish_enabled or not cfg.tinyfish_api_key:
            raise CollectionFailure(
                "Web collection is disabled. Configure TINYFISH_ENABLED and TINYFISH_API_KEY explicitly."
            )
        key = hashlib.sha256(
            json.dumps(["tinyfish-contract-1", self.user_id, product, payload], sort_keys=True).encode()
        ).hexdigest()
        cached = self.db.get(ModelCache, key)
        if cached and cfg.tinyfish_cache_seconds and not self.options.get("refresh_origin"):
            age = (now() - cached.created_at.replace(tzinfo=timezone.utc)).total_seconds()
            if age < cfg.tinyfish_cache_seconds:
                self.record["cache_hits"] += 1
                return cached.result
        counter, maximum = (
            ("search_attempts", self.record["limits"]["searches"])
            if product == "search"
            else ("url_attempts", self.record["limits"]["url_attempts"])
        )
        count = 1 if product == "search" else len(payload["urls"])
        if self.record[counter] + count > maximum:
            raise CollectionFailure("The investigation collection limit has been reached.")
        self.budget.reserve(product, count)
        self.record[counter] += count  # Includes network failures and retries, never refunded.
        try:
            with httpx.Client(
                timeout=httpx.Timeout(45, connect=8),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(
                    "GET" if product == "search" else "POST",
                    f"https://api.{product}.tinyfish.ai",
                    headers={"X-API-Key": cfg.tinyfish_api_key},
                    **({"params": payload} if product == "search" else {"json": payload}),
                ) as response:
                    if response.status_code == 402:
                        raise CollectionFailure(
                            "TinyFish allowance is exhausted. Collection stopped; no paid fallback was used."
                        )
                    if response.status_code == 429:
                        raise CollectionFailure(
                            "TinyFish rate limit reached. Collection stopped; retry later."
                        )
                    if response.status_code >= 300:
                        raise CollectionFailure(
                            "TinyFish rejected the request or is unavailable. Check account access and retry later."
                        )
                    body = bytearray()
                    for block in response.iter_bytes():
                        if time.monotonic() > self.deadline:
                            raise CollectionFailure("The collection time budget has been reached.")
                        body.extend(block)
                        if len(body) > 2_000_000:
                            raise CollectionFailure("Collection response exceeds the application size limit.")
                    data = json.loads(body)
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("results"), list)
                or not isinstance(data.get("errors", []), list)
            ):
                raise ValueError("Invalid collection response")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise CollectionFailure("Collection timed out or returned an invalid response.") from exc
        # Error-bearing fetch responses are not cached; a manual rerun may succeed.
        if not data.get("errors"):
            self.db.merge(ModelCache(id=key, user_id=self.user_id, result=data, created_at=now()))
            self.db.commit()
        return data

    def collect(self, domain, progress, *, seed_url=None):
        from .intelligence import normalize_source

        domain = normalize_domain(domain)
        seed = scoped_url(seed_url, domain) if seed_url else "https://" + domain + "/"
        if not seed or document_exclusion(seed):
            raise CollectionFailure("The supplied URL is outside the supported public document scope.")
        urls = [seed]
        self.record["seed_url"] = seed
        sources, hashes, processed, total = [], set(), set(), 0
        self.saved_records = sources
        excluded = set()
        navigation_skips = set()
        fallback_urls = set()
        maximum = self.record["limits"]["url_attempts"]
        linked_urls = {seed}
        topics = iter(
            (
                "official product features documentation",
                "official developer documentation integrations architecture",
                "official pricing plans features",
                "official API reference specification",
                "official product engineering documentation",
            )[: self.record["limits"]["searches"]]
        )

        def discover(value, *, search=False):
            candidate = scoped_url(value, domain)
            if not candidate or candidate in processed or candidate in urls or candidate in excluded:
                return
            reason = document_exclusion(candidate)
            scope = document_scope(candidate, seed, linked=not search)
            if not reason and scope["role"] == "background_reference":
                reason = scope["reason"]
            if not search:
                linked_urls.add(candidate)
            if not reason and urlsplit(candidate).path in ("", "/"):
                host = urlsplit(candidate).hostname or ""
                if host == domain or host.split(".")[0] not in ("docs", "developer", "developers"):
                    reason = "alternate_or_duplicate_root"
            if not reason and document_priority(candidate) == 4:
                if not search:
                    navigation_skips.add(candidate)
                    self.record["skipped_navigation_links"] = len(navigation_skips)
                    return
                # One search-discovered fallback permits unusual documentation
                # routes without turning every unclassified link into a crawl.
                if fallback_urls:
                    reason = "unclassified_search_candidate"
                else:
                    fallback_urls.add(candidate)
            if reason:
                excluded.add(candidate)
                self.record["excluded_discovery_urls"] = len(excluded)
                if len(excluded) <= 100:
                    self.record["outcomes"].append(
                        {"url": candidate, "status": "excluded", "reason": reason, "stage": "discovery"}
                    )
            elif len(urls) < 100:
                urls.append(candidate)
            else:
                self.record["discovery_queue_truncated"] = True
                worst = max(urls, key=document_priority)
                if document_priority(candidate) < document_priority(worst):
                    urls.remove(worst)
                    urls.append(candidate)

        self.record["status"] = "collecting"
        try:
            while len(processed) < maximum and self.record["url_attempts"] < maximum:
                if not urls:
                    topic = next(topics, None)
                    if topic is None:
                        break
                    self.record["search_queries"] += 1
                    data = self.request(
                        "search",
                        {
                            "query": domain + " " + topic,
                            "include_domains": domain,
                            "purpose": "Find documentation and capabilities of the requested product itself. Exclude articles about other software, tutorials, samples, other products from the same company, runtime API calls and generated payload pages.",
                        },
                    )
                    for item in data["results"][:30]:
                        if isinstance(item, dict):
                            discover(item.get("url", ""), search=True)
                    progress(
                        10,
                        f"Selected {len(urls)} document URLs from discovery; {self.record['search_queries']} search queries.",
                    )
                    continue
                urls.sort(key=document_priority)
                url = urls.pop(0)
                if url in processed:
                    continue
                processed.add(url)
                self.record["visited_urls"] = len(processed)
                payload = {"urls": [url], "format": "markdown", "links": True, "per_url_timeout_ms": 30000, "purpose": "Retain technical descriptions, product interfaces, architecture, integrations and API contracts for an evidence-backed system assessment."}
                if self.options.get("refresh_origin"):
                    payload["ttl"] = 0
                data = self.request("fetch", payload)
                errors = data.get("errors", [])
                # One retry for explicit transient per-URL failures, charged to the same cap.
                if (
                    errors
                    and isinstance(errors[0], dict)
                    and errors[0].get("error") in ("timeout", "target_unreachable", "proxy_error")
                    and self.record["url_attempts"] < maximum
                ):
                    data = self.request("fetch", payload)
                for error in data.get("errors", []):
                    self.record["outcomes"].append(
                        {
                            "url": url,
                            "status": "unavailable",
                            "reason": str(error.get("error", "unknown"))[:80]
                            if isinstance(error, dict)
                            else "invalid_error",
                        }
                    )
                if not data["results"] and not data.get("errors"):
                    self.record["outcomes"].append(
                        {"url": url, "status": "unavailable", "reason": "missing_result"}
                    )
                for page in data["results"][:1]:
                    if not isinstance(page, dict):
                        raise CollectionFailure("Collection returned an invalid page record.")
                    final = scoped_url(page.get("final_url") or url, domain)
                    if page.get("url") != url or not final:
                        self.record["outcomes"].append(
                            {"url": url, "status": "excluded", "reason": "redirect_outside_scope"}
                        )
                        continue
                    reason = document_exclusion(final)
                    scope = document_scope(final, seed, linked=url in linked_urls)
                    if not reason and scope["role"] == "background_reference":
                        reason = scope["reason"]
                    if reason:
                        self.record["outcomes"].append(
                            {"url": url, "final_url": final, "status": "excluded", "reason": reason}
                        )
                        continue
                    text = page.get("text")
                    if not isinstance(text, str) or len(text) < 20 or len(text) > 200000:
                        self.record["outcomes"].append(
                            {"url": url, "status": "excluded", "reason": "unsupported_or_oversized_content"}
                        )
                        continue
                    from .page_access import document_access
                    access = document_access(text, str(page.get("title") or ""))
                    from .source_analysis import prepare_source

                    format = "markdown"
                    unwrapped = re.sub(r"^```[^\n]*\n|\n```\s*$", "", text.strip()).strip()
                    try:
                        document = json.loads(unwrapped)
                        if isinstance(document, dict) and (
                            document.get("openapi") or document.get("swagger")
                        ):
                            format = "openapi"
                        else:
                            self.record["outcomes"].append(
                                {"url": url, "status": "excluded", "reason": "non_specification_json"}
                            )
                            continue
                    except ValueError:
                        pass
                    source = ImportedSource(
                        title=str(page.get("title") or final)[:120],
                        origin=final,
                        format=format,
                        category="pricing"
                        if "pricing" in final.lower()
                        else "api_reference"
                        if format == "openapi"
                        else "documentation",
                        content=text,
                    )
                    try:
                        source, _ = prepare_source(source)
                        content = normalize_source(source)
                    except ValueError:
                        self.record["outcomes"].append(
                            {"url": url, "status": "excluded", "reason": "invalid_document"}
                        )
                        continue
                    digest = hashlib.sha256(content.encode()).hexdigest()
                    if digest in hashes:
                        self.record["outcomes"].append(
                            {"url": url, "status": "duplicate", "final_url": final}
                        )
                        continue
                    if total + len(content) > 100000:
                        self.record["outcomes"].append(
                            {"url": url, "status": "excluded", "reason": "document_budget"}
                        )
                        continue
                    total += len(content)
                    hashes.add(digest)
                    sources.append(
                        (
                            source,
                            content,
                            {
                                "requested_url": url,
                                "final_url": final,
                                "title": source.title,
                                "etag": page.get("etag"),
                                "last_modified": page.get("last_modified"),
                                "page_access": access,
                                "target_scope": scope,
                                "linked_from_target": url in linked_urls,
                            },
                        )
                    )
                    self.record["outcomes"].append(
                        {"url": url, "final_url": final, "status": "collected" if access["content_available"] else access["status"], "reason": access["access_reason"], "sha256": digest}
                    )
                    links = page.get("links") or []
                    if not isinstance(links, list):
                        links = []
                    for link in links[:100]:
                        if isinstance(link, str):
                            try:
                                discover(urljoin(final, link))
                            except ValueError:
                                continue
                progress(
                    10,
                    f"Retained {len(sources)} documents; {len(processed)} URLs reviewed; {self.record['url_attempts']} new Fetch attempts.",
                )
                if self.analysis_provider == "rules" and any(s[0].format == "openapi" and s[0].origin == seed for s in sources):
                    self.record["stop_reason"] = (
                        "An explicit API specification was retained. Further discovery was not required for this parser-only assessment."
                    )
                    self.record["scope"] = "supplied_specification" if seed == url else "first_explicit_specification"
                    break
            if urls:
                self.record["unvisited_urls"] = len(urls)
                self.record.setdefault(
                    "stop_reason",
                    ("Collection reached its bounded scope; additional discovered URLs were not visited."),
                )
            if "stop_reason" not in self.record:
                self.record["stop_reason"] = (
                    "The configured URL budget was reached."
                    if len(processed) >= maximum or self.record["url_attempts"] >= maximum
                    else "No additional document candidates were selected within the configured discovery budget."
                )
            self.record["status"] = (
                "partial"
                if urls
                or len(processed) >= maximum
                or self.record["url_attempts"] >= maximum
                or self.record.get("skipped_navigation_links")
                or self.record.get("scope") == "first_explicit_specification"
                or self.record.get("discovery_queue_truncated")
                or any(o["status"] not in ("collected", "duplicate") for o in self.record["outcomes"])
                else "complete"
            )
            if self.record.get("scope") == "supplied_specification":
                self.record["status"] = "complete"
        except CollectionFailure as exc:
            self.record["status"], self.record["stop_reason"] = "partial" if sources else "failed", str(exc)
            if not sources and not self.options.get("public_files"):
                raise
        finally:
            self.record["finished_at"] = now().isoformat()
            self.record["document_characters"] = total
            self.record["collected_sources"] = len(sources)
        if self.options.get("public_files"):
            self.collect_public_files(seed, domain, sources, hashes, progress)
        if self.options.get("browser_observation") and self.record.get("scope") != "supplied_specification":
            self.collect_browser_observation(seed, sources, hashes, progress)
        self.record["retained_layers"] = sorted({row[2].get("collection_method", "document") for row in sources})
        if sources and not any(row[2].get("collection_method") == "browser_script" or row[0].format == "openapi" for row in sources):
            self.record["technical_coverage"] = "documents_and_delivery"
        else:
            self.record["technical_coverage"] = "client_code_or_contract"
        if not sources:
            self.record["status"] = "failed"
            raise CollectionFailure("No usable public documents were collected. See the collection record.")
        return sources

    def collect_public_files(self, seed, domain, sources, hashes, progress):
        from .intelligence import normalize_source
        from .public_code import inline_sources
        from .public_files import LinkedFiles, PublicFileError, decode_public_text, read_public
        from .resource_policy import resource_format, resource_priority, resource_role
        from .source_analysis import prepare_source
        from .web_observation import append_response, new_snapshot, safe_url

        snapshot = new_snapshot(seed)
        record = {"requests": 0, "limit": min(self.options.get("direct_read_limit", 8), settings().public_file_max_per_run), "outcomes": []}
        self.record["public_files"] = record
        queue, seen = [seed], set()
        external, parents, contexts = set(), {}, {}
        for source, _, _ in sources:
            for value in re.findall(r"https?://[^\s<>\)\]\"]+", source.content)[:100]:
                if scoped_url(value, domain) and not document_exclusion(value) and any(word in value.casefold() for word in ("openapi", "swagger", "schema", ".js", ".mjs")) and value not in queue:
                    queue.append(value)
                    parents[value] = source.origin

        def reserve():
            self.stop()
            if record["requests"] >= record["limit"] or time.monotonic() >= self.deadline:
                raise PublicFileError("Public file request budget reached.")
            record["requests"] += 1

        while queue and record["requests"] < record["limit"]:
            queue.sort(key=lambda value: resource_priority({"url": value, "kind": contexts.get(value, "document" if value == seed else "")}))
            url = queue.pop(0)
            if resource_role(url, context=contexts.get(url, "")) == "tracking":
                record["outcomes"].append({"url": url, "status": "excluded", "reason": "tracking_resource"})
                seen.add(url)
                continue
            if url in seen or (not scoped_url(url, domain) and url not in external) or document_exclusion(url):
                continue
            seen.add(url)
            try:
                response = read_public(url, allowed_hosts={domain.removeprefix("www.")} if url not in external else {urlsplit(url).hostname}, max_bytes=2_000_000, before_request=reserve, include_headers=True, timeout_seconds=10, allow_statuses=(200, 401, 402, 403, 404, 429, 500, 502, 503))
                raw, final, mime = response[:3]
                headers, status = response[3:] if len(response) == 5 else ({}, 200)
                if urlsplit(final).path.casefold().endswith((".pdf", ".docx")):
                    from .source_intake import document_text
                    text, _ = document_text(urlsplit(final).path, raw)
                else:
                    text = decode_public_text(raw, mime)
                format = resource_format(final, mime, text, contexts.get(url, ""))
                role = resource_role(final, mime=mime, content=text, context=contexts.get(url, ""), page_url=parents.get(url, seed))
                resource_type = "script" if format == "javascript" else "stylesheet" if urlsplit(final).path.endswith(".css") else "document" if "html" in mime else "technical_document"
                append_response(snapshot, url, final, mime, headers, status, text, resource_type)
                if status >= 400:
                    from .page_access import page_access
                    from .public_surface import surface_page
                    state = (surface_page(text, final, http_status=status) if format == "html" else None) or page_access(http_status=status)
                    if format != "html":
                        snapshot["surface"].append({"url": safe_url(final), "title": "", **state})
                    record["outcomes"].append({"url": url, "status": state["status"], "reason": state["access_reason"], "http_status": status})
                    continue
                if "html" in mime or text.lstrip().lower().startswith(("<!doctype html", "<html")):
                    from .public_surface import surface_page
                    page_state = surface_page(text, final, http_status=status) or {}
                    if not page_state.get("content_available", True):
                        record["outcomes"].append({"url": url, "status": page_state.get("status", "collection_failed"), "reason": page_state.get("access_reason", "unavailable")})
                        # Keep the access observation, without treating gate
                        # markup as application content or chasing its scripts.
                        continue
                    links = LinkedFiles(final)
                    links.feed(text)
                    snapshot["resources"].extend({"url": safe_url(r["url"]), "kind": r["kind"]} for r in links.resources[:200])
                    for resource in sorted(links.resources, key=lambda row: resource_priority(row, final))[:60]:
                        link = resource["url"]
                        contexts[link] = resource["kind"]
                        # Stylesheets are already declared in the snapshot. Preserve the
                        # read allowance for executable resources and technical documents.
                        if resource["kind"] == "stylesheet":
                            continue
                        if document_exclusion(link):
                            continue
                        if scoped_url(link, domain):
                            if link not in queue and link not in seen:
                                queue.append(link)
                                parents[link] = final
                        elif resource["kind"] in {"script", "stylesheet"} and self.options.get("linked_external_scripts"):
                            parsed = urlsplit(link)
                            if parsed.scheme in {"http", "https"} and not parsed.username and not parsed.password and parsed.port in (None, 80, 443):
                                external.add(link)
                                queue.append(link)
                                parents[link] = final
                    format = "html"
                    for inline, metadata in inline_sources(text, final):
                        if metadata.get("resource_role") == "tracking":
                            continue
                        normalized_inline = normalize_source(inline)
                        inline_hash = hashlib.sha256(normalized_inline.encode()).hexdigest()
                        if inline_hash not in hashes and sum(len(row[1]) for row in sources) + len(normalized_inline) <= 10_000_000:
                            sources.append((inline, normalized_inline, metadata))
                            hashes.add(inline_hash)
                    # Robots is a standardized public discovery document. Follow
                    # sitemap locations it declares, never invent API endpoints.
                    robots = urljoin(final, "/robots.txt")
                    if robots not in queue and robots not in seen:
                        queue.append(robots)
                        contexts[robots] = "discovery"
                        parents[robots] = final
                if urlsplit(final).path.endswith("/robots.txt"):
                    for reference in re.findall(r"(?im)^sitemap:\s*(https?://\S+)", text)[:4]:
                        if scoped_url(reference, domain):
                            queue.append(reference)
                            contexts[reference] = "sitemap"
                            parents[reference] = final
                if format == "xml" and contexts.get(url) == "sitemap" and not re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
                    from xml.etree import ElementTree
                    try:
                        tree = ElementTree.fromstring(text)
                        locations = [node.text for node in tree.iter() if node.tag.rsplit("}", 1)[-1] == "loc" and node.text][:100]
                        snapshot.setdefault("sitemap_routes", []).extend({"url": safe_url(value), "sitemap": safe_url(final), "status": "referenced"} for value in locations if scoped_url(value, domain))
                        if tree.tag.rsplit("}", 1)[-1] == "sitemapindex":
                            for value in locations[:2]:
                                if scoped_url(value, domain):
                                    queue.append(value)
                                    contexts[value] = "sitemap"
                    except ElementTree.ParseError:
                        record["outcomes"].append({"url": safe_url(final), "status": "unavailable", "reason": "invalid_sitemap"})
                    format = "text"
                if resource_type == "stylesheet":
                    record["outcomes"].append({"url": url, "status": "observed_stylesheet"})
                    continue
                if format not in ("html", "json", "yaml", "javascript", "typescript", "markdown", "text"):
                    raise PublicFileError("Unsupported public technical file format.")
                if len(text) > 2_000_000:
                    raise PublicFileError("Public source exceeds the text budget.")
                if format == "javascript":
                    for reference in re.findall(r"(?m)//[#@]\s*sourceMappingURL=([^\s]+)", text)[-2:]:
                        linked = urljoin(final, reference)
                        if not reference.startswith("data:") and scoped_url(linked, domain) and not document_exclusion(linked):
                            queue.append(linked)
                            parents[linked] = final
                source = ImportedSource(
                    title=urlsplit(final).path.rsplit("/", 1)[-1] or domain,
                    origin=final,
                    format=format,
                    content=text,
                )
                source, _ = prepare_source(source)
                normalized = normalize_source(source)
                digest = hashlib.sha256(normalized.encode()).hexdigest()
                previous = next((index for index, row in enumerate(sources) if row[0].origin == final), None)
                if previous is not None and source.format == "openapi":
                    old_source, old_text, old_meta = sources[previous]
                    metadata = {"requested_url": url, "final_url": final, "title": source.title, "collection_method": "public_file",
                                "alternate_representations": [{"collection_method": old_meta.get("collection_method", "tinyfish_fetch"),
                                                               "raw_content": old_source.content, "normalized_sha256": hashlib.sha256(old_text.encode()).hexdigest()}]}
                    sources[previous] = (source, normalized, metadata)
                    hashes.discard(hashlib.sha256(old_text.encode()).hexdigest())
                    hashes.add(digest)
                    record["outcomes"].append({"url": url, "status": "preferred_representation", "sha256": digest})
                    if self.analysis_provider == "rules" and final == seed:
                        self.record["scope"] = "supplied_specification"
                        self.record["status"] = "complete"
                        self.record["stop_reason"] = "The supplied API specification was retained for structural assessment."
                    continue
                if digest not in hashes and sum(len(row[1]) for row in sources) + len(normalized) <= min(10_000_000, settings().source_bundle_characters):
                    sources.append(
                        (
                            source,
                            normalized,
                            {
                                "requested_url": url,
                                "final_url": final,
                                "title": source.title,
                                "collection_method": "public_file",
                                "linked_from": parents.get(url),
                                "resource_role": role,
                                "response_content_type": mime,
                                "external_resource": url in external,
                                "compiled_asset": format == "javascript" and (len(text) > 16000 and max(map(len, text.splitlines()), default=0) > 8000 or urlsplit(final).path.endswith(".min.js")),
                            },
                        )
                    )
                    hashes.add(digest)
                    record["outcomes"].append({"url": url, "status": "collected", "sha256": digest})
                    if source.format == "openapi" and self.analysis_provider == "rules" and final == seed:
                        self.record["scope"] = "supplied_specification"
                        self.record["status"] = "complete"
                else:
                    record["outcomes"].append({"url": url, "status": "duplicate_or_budget"})
                if source.format == "json":
                    try:
                        source_map = json.loads(text)
                    except (ValueError, RecursionError):
                        source_map = None
                    if isinstance(source_map, dict) and source_map.get("version") == 3:
                        from .public_code import source_map_sources
                        retained = 0
                        for derived, metadata in source_map_sources(text, final, page_url=seed):
                            if any(row[0].origin == derived.origin and row[0].content != derived.content for row in sources):
                                version = hashlib.sha256(derived.content.encode()).hexdigest()[:12]
                                derived = derived.model_copy(update={"origin": derived.origin.replace("local:sourcemap/", "local:sourcemap/" + version + "/", 1)})
                                metadata = {**metadata, "path_conflict": True}
                                self.record["status"] = "partial"
                            derived_text = normalize_source(derived)
                            derived_hash = hashlib.sha256(derived_text.encode()).hexdigest()
                            if derived_hash in hashes or sum(len(row[1]) for row in sources) + len(derived_text) > 8_000_000:
                                continue
                            sources.append((derived, derived_text, {"title": derived.title, **metadata}))
                            hashes.add(derived_hash)
                            retained += 1
                        record["outcomes"].append({"url": final, "status": "source_map_expanded", "retained_sources": retained})
            except (PublicFileError, UnicodeError, ValueError, RecursionError, TypeError) as exc:
                record["outcomes"].append({"url": url, "status": "unavailable", "reason": str(exc)[:200]})
            progress(
                15, f"Public file review: {record['requests']} requests; {len(sources)} retained sources."
            )
        record["unvisited_resources"] = len(set(queue) - seen)
        snapshot["coverage"] = {"requests": record["requests"], "limit": record["limit"], "unvisited_resources": record["unvisited_resources"], "outcomes": record["outcomes"]}
        if any(row["resource_type"] == "document" for row in snapshot["responses"]):
            self.retain_observation(snapshot, sources, hashes, "public_observation")
        if record["unvisited_resources"] or any(row["status"] == "unavailable" for row in record["outcomes"]):
            self.record["status"] = "partial"
        if self.record["status"] == "failed" and sources:
            self.record["status"] = "partial"
        self.record["collected_sources"] = len(sources)
        self.record["document_characters"] = sum(len(row[1]) for row in sources)
        self.record["finished_at"] = now().isoformat()


    def retain_observation(self, snapshot, sources, hashes, method):
        content = json.dumps(snapshot, ensure_ascii=False, indent=2)
        digest = hashlib.sha256(content.encode()).hexdigest()
        if digest not in hashes:
            source = ImportedSource(title="Public application observation", origin="local:observations/" + method + ".json", format="json", content=content)
            sources.append((source, content, {"title": source.title, "collection_method": method, "observed_url": snapshot["url"]}))
            hashes.add(digest)

    def collect_browser_observation(self, seed, sources, hashes, progress):
        from .intelligence import normalize_source
        from .public_code import inline_sources, source_map_sources
        from .resource_policy import resource_priority
        from .source_analysis import prepare_source
        from .web_observation import collect_browser
        from .page_access import apply_content_coverage
        progress(16, "Inspecting rendered pages, traffic and client code.")
        retained = {"scripts": 0, "pages": 0, "source_map_modules": 0}

        def retain(source, metadata):
            if metadata.get("collection_method") == "source_map" and any(row[0].origin == source.origin and row[0].content != source.content for row in sources):
                # Conflicting published versions retain separate scopes instead
                # of overwriting a scanner path or inventing cross-version imports.
                version = hashlib.sha256(source.content.encode()).hexdigest()[:12]
                source = source.model_copy(update={"origin": source.origin.replace("local:sourcemap/", "local:sourcemap/" + version + "/", 1)})
                metadata = {**metadata, "path_conflict": True}
            try:
                source, _ = prepare_source(source)
                content = normalize_source(source)
            except (ValueError, TypeError, RecursionError):
                return False
            digest = hashlib.sha256(content.encode()).hexdigest()
            if digest in hashes or sum(len(row[1]) for row in sources) + len(content) > min(10_000_000, settings().source_bundle_characters):
                return False
            sources.append((source, content, {"title": source.title, **metadata}))
            hashes.add(digest)
            return True

        try:
            published = [s.origin for s, _, meta in sources if getattr(s, "format", "text") in {"html", "markdown", "text"} and scoped_url(s.origin, urlsplit(seed).hostname) and (meta.get("page_access") or {}).get("content_available", True)]
            result = collect_browser({**self.options, "browser_published_pages": list(dict.fromkeys(published))[:12]}, seed, self.stop)
            apply_content_coverage(result["snapshot"])
            self.record["browser"] = result["snapshot"]["coverage"]
            pages = result.get("pages", []) or ([{"url": seed, "html": result.get("html"), "title": result.get("title")}] if result.get("html") else [])
            for page in pages[:6]:
                self.stop()
                if not isinstance(page, dict) or not isinstance(page.get("html"), str) or not isinstance(page.get("url"), str) or not page["html"].strip():
                    continue
                source = ImportedSource(title=page.get("title") or "Rendered page", origin=page["url"], format="html", content=page["html"])
                retained["pages"] += retain(source, {"collection_method": "browser_dom" if page.get("rendered", True) else "public_file", "rendered": page.get("rendered", True), "resource_role": "page", "response_status": page.get("http_status")})
                for source, meta in inline_sources(page["html"], page["url"]):
                    retained["scripts"] += retain(source, meta)
            for script in sorted(result.get("scripts", []), key=lambda row: resource_priority({"url": row.get("url", ""), "role": row.get("resource_role", "application")}))[:40]:
                self.stop()
                if not isinstance(script, dict) or not isinstance(script.get("url"), str) or not isinstance(script.get("content"), str) or not script["content"].strip():
                    continue
                source = ImportedSource(title=urlsplit(script["url"]).path.rsplit("/", 1)[-1][:120] or "Client script", origin=script["url"], format="javascript", content=script["content"])
                retained["scripts"] += retain(source, {"collection_method": "browser_script", "public_page": script.get("page_url") or seed, "resource_role": script.get("resource_role", "application"), "response_content_type": script.get("response_content_type", ""), "content_window": script.get("content_window"), "original_characters": script.get("original_characters"), "compiled_asset": len(script["content"]) > 16000 and max(map(len, script["content"].splitlines()), default=0) > 8000})
            for source_map in result.get("source_maps", [])[:4]:
                if not isinstance(source_map, dict) or not isinstance(source_map.get("content"), str) or not isinstance(source_map.get("url"), str):
                    continue
                for source, meta in source_map_sources(source_map["content"], source_map["url"], page_url=source_map.get("page_url") or seed):
                    self.stop()
                    retained["source_map_modules"] += retain(source, meta)
            result["snapshot"]["coverage"]["analysis_retained"] = dict(retained)
            self.record["browser"] = json.loads(json.dumps(result["snapshot"]["coverage"]))
            self.retain_observation(result["snapshot"], sources, hashes, "browser_observation")
            if self.record["browser"].get("status") == "partial":
                self.record["status"] = "partial"
        except (httpx.HTTPError, ValueError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            self.record["browser"] = {"status": "unavailable", "reason": "Browser service could not complete the selected observation.", "http_status": status}
            self.record["status"] = "partial" if sources else "failed"
        self.record["collected_sources"] = len(sources)
        self.record["document_characters"] = sum(len(row[1]) for row in sources)
        self.record["finished_at"] = now().isoformat()
        progress(18, f"Retained {len(sources)} snapshots, including {retained['scripts']} client scripts and {retained['source_map_modules']} original modules.")
