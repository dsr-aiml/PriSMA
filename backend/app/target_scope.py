"""Separate a product's evidence from content merely hosted by its organisation."""

import re
from urllib.parse import unquote, urlsplit

DOCUMENT_FORMATS = {"markdown", "text", "html", "openapi"}
TECHNICAL_HOSTS = {"docs", "doc", "documentation", "developer", "developers", "api", "help", "support", "reference"}


def host_family(host):
    # Relationship comparison only. Never rewrite a request or claim a redirect.
    return (host or "").casefold().rstrip(".").removeprefix("www.")


def document_scope(url, target, *, linked=False):
    if not target or not url.startswith(("https://", "http://")):
        return {"role": "target_product", "reason": "supplied_or_local_source"}
    page, seed = urlsplit(url), urlsplit(target)
    host, root = host_family(page.hostname), host_family(seed.hostname)
    if host == root and page.path.rstrip("/") == seed.path.rstrip("/"):
        return {"role": "target_product", "reason": "requested_page"}
    if host != root:
        prefix = host[:-(len(root)+1)].split(".") if host.endswith("."+root) else []
        if not prefix or not set(prefix) <= TECHNICAL_HOSTS:
            return {"role": "background_reference", "reason": "different_product_or_hosted_content"}
    if not linked and re.search(r"/(?:wiki|articles?|blog|blogs|tutorials?|examples?|samples?|questions|posts)/", unquote(page.path), re.I):
        return {"role": "background_reference", "reason": "article_tutorial_or_example"}
    return {"role": "target_product", "reason": "published_product_resource"}


def source_scope(source, target):
    signals = source.signals or {}
    if source.source_type not in DOCUMENT_FORMATS:
        return {"role": "target_product", "reason": "code_or_collection_record"}
    return document_scope(source.source_url, target, linked=bool(signals.get("linked_from_target")))


def target_from_options(options, *, live=False, domain=""):
    return (options.get("source_url") or ((options.get("intake") or {}).get("live_origin") or {}).get("source_url")
            or ((options.get("collection") or {}).get("seed_url")) or ("https://"+domain+"/" if live and domain else None))
