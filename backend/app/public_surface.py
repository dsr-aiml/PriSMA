"""Public page structure and labels; no input values or form submissions."""

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit


def surface_page(text, base, *, http_status=None):
    from .web_observation import safe_url

    class Surface(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.page = {
                "url": safe_url(base),
                "title": "",
                "description": "",
                "navigation": [],
                "forms": [],
                "headings": [],
                "controls": [],
                "public_features": [],
            }
            self.title = False
            self.anchor = self.form = self.label = self.heading = self.control = None
            self.labels = {}
            self.ignored = 0
            self.prose = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag in {"script", "style"}:
                self.ignored += 1
            if tag == "title":
                self.title = True
            if tag == "meta" and a.get("name", "").lower() == "description":
                self.page["description"] = a.get("content", "")[:500]
            if tag == "a" and a.get("href") and len(self.page["navigation"]) < 80:
                try:
                    url = urljoin(base, a["href"])
                    p = urlsplit(url)
                    if (
                        p.scheme in {"http", "https"}
                        and (p.hostname or "").removeprefix("www.") == (urlsplit(base).hostname or "").removeprefix("www.")
                        and not p.username
                        and not p.password
                        and not re.search(r"\.(?:png|jpg|svg|pdf|zip)$", p.path, re.I)
                    ):
                        self.anchor = {"url": safe_url(url), "label": a.get("aria-label", "")[:100]}
                except ValueError:
                    pass
            if tag in {"h1", "h2", "h3"}:
                self.heading = {"level": tag, "text": ""}
            if tag == "label":
                self.label = {"for": a.get("for", ""), "text": ""}
            if (tag in {"button", "summary"} or a.get("role") == "tab") and len(self.page["controls"]) < 24:
                self.control = {
                    "role": a.get("role") or tag,
                    "label": a.get("aria-label", "")[:100],
                    "disclosure": "aria-expanded" in a or "aria-haspopup" in a or tag == "summary",
                }
            if tag == "form" and len(self.page["forms"]) < 8:
                try:
                    action = urljoin(base, a.get("action") or "")
                    p = urlsplit(action)
                    if p.scheme in {"http", "https"} and p.hostname and not p.username and not p.password:
                        self.form = {
                            "action": safe_url(action),
                            "method": (a.get("method") or "GET").upper(),
                            "label": (a.get("aria-label") or "")[:100],
                            "fields": [],
                        }
                except ValueError:
                    pass
            if tag in {"input", "select", "textarea"} and self.form and len(self.form["fields"]) < 30:
                kind = (a.get("type") or "text").lower() if tag == "input" else tag
                name = a.get("name") or a.get("aria-label") or a.get("id")
                if name and kind not in {"hidden", "submit", "button", "reset", "image"}:
                    self.form["fields"].append(
                        {
                            "name": name[:80],
                            "type": kind[:40],
                            "required": "required" in a,
                            "label": a.get("aria-label", "")[:100],
                            "id": a.get("id", "")[:100],
                        }
                    )

        def handle_data(self, data):
            if self.ignored:
                return
            data = re.sub(r"\s+", " ", data).strip()
            if not data:
                return
            if self.title:
                self.page["title"] = (self.page["title"] + data)[:200]
            for current, key in (
                (self.anchor, "label"),
                (self.label, "text"),
                (self.heading, "text"),
                (self.control, "label"),
            ):
                if current is not None:
                    current[key] = (current[key] + " " + data).strip()[: 200 if key == "text" else 100]
            if len(self.prose) < 1000:
                self.prose.append(data[:500])

        def handle_endtag(self, tag):
            if tag in {"script", "style"}:
                self.ignored = max(0, self.ignored - 1)
            if tag == "title":
                self.title = False
            if tag == "a" and self.anchor:
                if self.anchor["label"] and not any(
                    r["url"] == self.anchor["url"] for r in self.page["navigation"]
                ):
                    self.page["navigation"].append(self.anchor)
                self.anchor = None
            if tag == "label" and self.label:
                if self.label["for"]:
                    self.labels[self.label["for"]] = self.label["text"][:100]
                elif self.form and not self.form["label"]:
                    self.form["label"] = self.label["text"][:100]
                self.label = None
            if tag in {"h1", "h2", "h3"} and self.heading:
                if self.heading["text"] and len(self.page["headings"]) < 24:
                    self.page["headings"].append(self.heading)
                self.heading = None
            if tag in {"button", "summary"} and self.control:
                if self.control["label"]:
                    self.page["controls"].append(self.control)
                self.control = None
            if tag == "form" and self.form:
                self.page["forms"].append(self.form)
                self.form = None

    parser = Surface()
    try:
        parser.feed(text[:1_000_000])
        parser.close()
    except (ValueError, RecursionError):
        return None
    # Retained/partial markup can omit closing tags. Keep its declared action
    # so a verification form cannot be mistaken for readable product content.
    if parser.form and len(parser.page["forms"]) < 8:
        parser.page["forms"].append(parser.form)
    for form in parser.page["forms"]:
        for field in form["fields"]:
            identity = field.pop("id", "")
            field["label"] = field["label"] or parser.labels.get(identity, field["name"])
    for prose in parser.prose:
        if (
            re.search(
                r"\b(?:available|included|unlimited|enterprise|premium|paid|pro plan|per month|per seat)\b",
                prose,
                re.I,
            )
            and 12 <= len(prose) <= 400
            and len(parser.page["public_features"]) < 16
        ):
            parser.page["public_features"].append({"text": prose, "status": "publicly_documented"})
    from .page_access import page_access
    state = page_access(
        parser.page["title"] or next((h["text"] for h in parser.page["headings"] if h["level"] == "h1"), ""),
        " ".join(parser.prose[:12]),
        http_status=http_status,
        password_form=any(f["type"] == "password" for form in parser.page["forms"] for f in form["fields"]),
        challenge_form=any(re.search(r"(?:captcha|challenge-platform|challenge-response|verify[-_]?human)", form.get("action", ""), re.I) for form in parser.page["forms"]),
    )
    parser.page.update(state)
    return parser.page
