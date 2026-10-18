"""Shared, bounded resource classification. Roles describe evidence, not ownership."""

import re
from urllib.parse import urlsplit

ROLE_ORDER = {"contract": 0, "application": 1, "page": 2, "dependency": 4, "delivery": 5, "tracking": 6}
TRACKING = re.compile(
    r"(?:^|[/._-])(?:analytics|telemetry|tracking|tracker|advertising|ads|pixel|beacon|gtag|gtm|sentry(?:_browser)?|mixpanel|amplitude|newrelic)(?:[/._-]|$)",
    re.I,
)
DEPENDENCY = re.compile(
    r"(?:^|[/._-])(?:vendor|vendors|polyfills?|runtime|jquery|bootstrap|react-dom|lodash|sdk)(?:[/._-]|$)", re.I
)
APPLICATION = re.compile(
    r"(?:^|[/._-])(?:main|app|application|index|entry|pages?|routes?|chunks)(?:[/._-]|$)", re.I
)


def resource_format(url, mime="", content="", context=""):
    """Response MIME wins over suffixes; inspect ambiguous text conservatively."""
    path = urlsplit(url).path.casefold()
    mime = mime.split(";", 1)[0].strip().casefold()
    sample = content.lstrip()[:6000]
    if mime in {"text/javascript", "application/javascript", "application/ecmascript", "text/ecmascript"}:
        return "javascript"
    if mime in {"text/html", "application/xhtml+xml"} or sample.casefold().startswith(
        ("<!doctype html", "<html")
    ):
        return "html"
    if mime == "text/css":
        return "css"
    if "json" in mime or (
        sample.startswith(("{", "[")) and not re.match(r"^\{\s*(?:function|const|let|var)\b", sample)
    ):
        return "json"
    if "xml" in mime or sample.startswith("<?xml") or re.match(r"<(?:urlset|sitemapindex)\b", sample):
        return "xml"
    if path.endswith((".js", ".mjs", ".cjs")) or context == "script":
        return "javascript"
    if path.endswith((".ts", ".tsx", ".jsx")):
        return "typescript" if not path.endswith(".jsx") else "javascript"
    if path.endswith((".yaml", ".yml")):
        return "yaml"
    if path.endswith(".css"):
        return "css"
    if path.endswith((".md", ".mdx")):
        return "markdown"
    if re.search(
        r"(?:^|[;\n])\s*(?:import\s+.+?\s+from\s+['\"]|export\s+(?:default|const|function)|(?:const|let|var)\s+\w+\s*=|\(?function\s*\()",
        sample,
    ):
        return "javascript"
    return "text"


def resource_role(url, *, mime="", content="", context="", page_url=""):
    path = urlsplit(url).path
    format = resource_format(url, mime, content, context)
    if re.search(r"(?:openapi|swagger|(?:^|/)schema\.(?:json|ya?ml))", path, re.I) or re.search(
        r'"(?:openapi|swagger)"\s*:', content[:3000]
    ):
        return "contract"
    if format == "html" or context == "document":
        return "page"
    if (
        TRACKING.search(path)
        or TRACKING.search(urlsplit(url).hostname or "")
        or re.search(r"\b(?:gtag|fbq)\s*\(|GoogleAnalyticsObject|window\.dataLayer", content[:8000])
    ):
        return "tracking"
    if format in {"javascript", "typescript"} and (re.search(r"/(?:gsi|identity)/client/?$", path, re.I) or re.search(r"@license[^\n]*(?:identity|authentication) SDK", content[:8000], re.I)):
        return "dependency"
    if format in {"javascript", "typescript"} and APPLICATION.search(path) and not DEPENDENCY.search(path):
        return "application"
    if DEPENDENCY.search(path) or re.search(
        r"@license\s+(?:React|jQuery)|lodash\.com|core-js/modules", content[:8000], re.I
    ):
        return "dependency"
    if format in {"javascript", "typescript"}:
        # App bundles frequently live on a CDN. Same origin is neither necessary
        # nor sufficient to establish authorship; retain the classification basis.
        return "application"
    return "delivery"


def resource_priority(row, page_url=""):
    url = row.get("url", "")
    role = row.get("role") or resource_role(url, context=row.get("kind", ""), page_url=page_url)
    path = urlsplit(url).path
    entry = bool(re.search(r"(?:^|[/._-])(?:main|_?app|entry|index|pages)(?:[/._-]|$)", path, re.I))
    return (ROLE_ORDER[role], 0 if entry else 1, len(url))


def public_navigation(surface, domain):
    candidates = []
    forbidden = {
        "logout",
        "signout",
        "signin",
        "login",
        "signup",
        "register",
        "delete",
        "remove",
        "checkout",
        "purchase",
        "cart",
        "download",
        "billing",
    }
    useful = {
        "docs",
        "documentation",
        "developer",
        "api",
        "architecture",
        "integration",
        "security",
        "product",
        "features",
        "platform",
        "pricing",
        "about",
        "help",
        "search",
        "explore",
        "catalog",
        "projects",
        "dashboard",
        "account",
        "settings",
    }
    for row in surface.get("navigation", [])[:80]:
        try:
            url = row.get("url", "")
            p = urlsplit(url)
        except ValueError:
            continue
        words = set(re.findall(r"[a-z]+", p.path.casefold() + " " + row.get("label", "").casefold()))
        if (
            p.scheme not in {"http", "https"}
            or (p.hostname or "").removeprefix("www.") != (urlsplit(surface.get("url", "")).hostname or domain).removeprefix("www.")
            or p.query
            or p.username
            or p.password
            or words & forbidden
            or p.path.endswith((".zip", ".pdf"))
        ):
            continue
        score = len(words & useful)
        # Ordinary public product routes are useful even with unfamiliar labels.
        if row.get("label") and p.path not in {"", "/"}:
            candidates.append((-score, len(p.path), url))
    return list(dict.fromkeys(row[2] for row in sorted(candidates)))


def safe_control(label, role, *, expanded=None, has_popup=None):
    """Only disclosure controls and tabs, never general action buttons or forms."""
    if (
        not label
        or len(label) > 100
        or re.search(
            r"\b(?:submit|send|save|buy|purchase|checkout|delete|remove|logout|sign.?out|subscribe|create|upload|download|connect|authorize|accept|reject|agree)\b",
            label,
            re.I,
        )
    ):
        return False
    return role in {"tab", "summary"} or (
        role == "button" and (expanded is not None or has_popup in {"menu", "true"})
    )


def code_signal_score(text):
    return len(
        re.findall(
            r"\b(?:fetch|axios|createClient|initializeApp|createRouter|createFileRoute|useQuery|graphql|path|lazy|import)\b|/api/|/graphql|type=[\"']|<form|<Route",
            text[:2000],
        )
    )
