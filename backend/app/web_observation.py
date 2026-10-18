"""Public delivery observations and exact citations. No stack guessing from URLs."""
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CONTRACT = "prisma.public-observation.v1"
PRIVATE_QUERY = re.compile(r"token|secret|password|authorization|session|api.?key|signature", re.I)


def safe_url(url):
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        netloc = ("[" + host + "]" if ":" in host else host) + (":" + str(p.port) if p.port else "")
    except (ValueError, TypeError):
        return "invalid:address"
    return urlunsplit((p.scheme, netloc, p.path, urlencode([(k, "[redacted]" if PRIVATE_QUERY.search(k) else v) for k, v in parse_qsl(p.query, keep_blank_values=True)]), ""))


def shape(value, depth=0):
    """Retain types, never response values, tokens or customer records."""
    if depth > 3:
        return "object" if isinstance(value, dict) else "array" if isinstance(value, list) else "value"
    if isinstance(value, dict):
        return {str(k)[:80]: shape(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    return "null" if value is None else "boolean" if isinstance(value, bool) else "number" if isinstance(value, (int, float)) else "string"


def signatures(text, url, mime, headers=None):
    """Specific shipped markers; names in ordinary marketing prose don't qualify."""
    result = []
    patterns = [
        ("Next.js", r'__NEXT_DATA__|self\.__next_f\.push|/_next/static/'),
        ("Nuxt", r'__NUXT__|__NUXT_DATA__|/_nuxt/'),
        ("SvelteKit", r'__sveltekit_[a-z0-9_]+|/_app/immutable/'),
        ("Angular", r'ng-version\s*=\s*[\"\'][^\"\']+|@angular/core'),
        ("React", r'react\.production(?:\.min)?\.js|react-dom/client|react\.element|react\.transitional\.element'),
        ("Vue.js", r'__VUE__|__VUE_OPTIONS_API__|vue\.runtime(?:\.esm)?'),
        ("Astro", r'astro-island|data-astro-cid-'),
        ("Supabase client SDK", r'@supabase/supabase-js|supabase\.createClient'),
        ("Firebase client SDK", r'firebase/app|firebase\.initializeApp'),
        ("Apollo Client", r'@apollo/client|ApolloClient\s*\('),
        ("Bootstrap", r'Bootstrap v[0-9]+\.[0-9]+|bootstrap\.bundle\.min\.js'),
    ]
    # Javascript and HTML contain executable/structural signatures; documentation does not.
    if "html" in mime:
        class Markers(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts, self.executable = [], False

            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag in {"script", "link", "astro-island"} or "ng-version" in values:
                    self.parts.append(self.get_starttag_text())
                if tag == "script":
                    self.executable = values.get("type", "").casefold() in {"", "module", "text/javascript", "application/javascript"}

            def handle_endtag(self, tag):
                if tag == "script":
                    self.executable = False

            def handle_data(self, data):
                if self.executable:
                    self.parts.append(data)
        markup = Markers()
        markup.feed(text)
        text = "\n".join(markup.parts)
    if "html" in mime or "javascript" in mime or urlsplit(url).path.endswith((".js", ".mjs")):
        for name, pattern in patterns:
            match = re.search(pattern, text)
            if match:
                result.append({"name": name, "basis": "shipped_marker", "marker": match[0][:160], "url": safe_url(url)})
    headers = headers or {}
    for key, names in {"server": {"nginx": "NGINX", "apache": "Apache HTTP Server", "caddy": "Caddy", "cloudflare": "Cloudflare"}, "x-powered-by": {"express": "Express", "php": "PHP", "next.js": "Next.js", "asp.net": "ASP.NET"}}.items():
        for token, name in names.items():
            if re.search(r"(?<![a-z])" + re.escape(token) + r"(?![a-z])", headers.get(key, ""), re.I):
                result.append({"name": name, "basis": "response_header", "header": key, "marker": headers[key][:160], "url": safe_url(url)})
    if headers.get("x-vercel-id"):
        result.append({"name": "Vercel", "basis": "response_header", "header": "x-vercel-id", "marker": headers["x-vercel-id"][:160], "url": safe_url(url)})
    if headers.get("cf-ray") and not any(r["name"] == "Cloudflare" for r in result):
        result.append({"name": "Cloudflare", "basis": "response_header", "header": "cf-ray", "marker": headers["cf-ray"][:160], "url": safe_url(url)})
    return result


def new_snapshot(url, method="static_public_reads"):
    return {"contract": CONTRACT, "url": safe_url(url), "method": method, "responses": [], "resources": [], "signals": [], "surface":[], "coverage": {}}


def append_response(snapshot, url, final, mime, headers, status, text="", resource_type="document"):
    snapshot["responses"].append({"url": safe_url(url), "final_url": safe_url(final), "status": status, "method": "GET", "resource_type": resource_type, "content_type": mime[:160], "headers": headers})
    snapshot["signals"].extend(signatures(text, final, mime, headers))
    if resource_type == "document" and "html" in mime:
        from .public_surface import surface_page
        surface=surface_page(text, final, http_status=status)
        if surface: surface.update(rendered=False)
        if surface and len(snapshot.setdefault('surface',[]))<12:snapshot['surface'].append(surface)


def observation_facts(item):
    if item.source_type != "json":
        return
    try:
        data = json.loads(item.content)
    except (ValueError, RecursionError):
        return
    if not isinstance(data, dict) or data.get("contract") != CONTRACT:
        return
    if not isinstance(data.get("url"), str) or not all(isinstance(data.get(key), list) for key in ("responses", "resources", "signals")):
        return
    try:
        for row in data["responses"][:120]:
            if not isinstance(row, dict) or not isinstance(row.get("url"), str) or not isinstance(row.get("content_type"), str) or not isinstance(row.get("status"), int):
                return
            if row.get("final_url") is not None and not isinstance(row["final_url"], str):
                return
            urlsplit(row.get("final_url") or row["url"])
        for row in data["resources"][:200]:
            if not isinstance(row, dict) or not isinstance(row.get("url"), str) or not isinstance(row.get("kind"), str):
                return
        for row in data["signals"][:80]:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(row.get("marker"), str):
                return
    except ValueError:
        return
    from .document_facts import anchor_fact, pointer_index
    marks = pointer_index(item.content)
    context = "public surface"

    def fact(kind, name, detail, anchor_path, **extra):
        if anchor_path not in marks:
            return None
        start, end = marks[anchor_path]
        attrs = extra.setdefault("attributes", {})
        attrs.update({"document_pointer": "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in anchor_path), "observation_method": data.get("method")})
        return anchor_fact(item, kind, name, detail, start, end, context=context, **extra)

    responses = data.get("responses", [])[:120]
    if not any(isinstance(row, dict) and row.get("resource_type") == "document" and "html" in row.get("content_type", "") and row.get("status", 0) < 400 for row in responses):
        return
    yield fact("component", "Web client", "Public page retained during the selected observation.", ("url",), component_kind="frontend")
    api_hosts = {urlsplit(r.get("final_url") or r.get("url", "")).hostname for r in responses if r.get("resource_type") in {"fetch", "xhr"}}
    emitted = set()
    for index, row in enumerate(responses):
        if not isinstance(row, dict):
            continue
        host = urlsplit(row.get("final_url") or row.get("url", "")).hostname
        label = (("API interface " if host in api_hosts else "Delivery origin ") + (host or ""))[:100]
        if host and host not in emitted and (host not in api_hosts or row.get("resource_type") in {"fetch", "xhr"}):
            emitted.add(host)
            yield fact("component", label, "Public API interface reached by anonymous reads." if host in api_hosts else "Public origin delivering pages or client resources; private hosting is not established.", ("responses", index), component_kind="api" if host in api_hosts else "infrastructure")
            yield fact("connection", "reads public interface" if host in api_hosts else "receives public resources", "Anonymous HTTP response observed during page collection.", ("responses", index), source_name="Web client", target_name=label, attributes={"relationship_kind": "observed_response" if host in api_hosts else "observed_delivery"})
        if row.get("resource_type") in {"fetch", "xhr"} and row.get("response_shape") is not None and 200 <= row.get("status", 0) < 400:
            path = urlsplit(row.get("url", "")).path or "/"
            method = row.get("method", "GET")
            if method not in {"GET", "POST"} or method == "POST" and not row.get("read_operation"):
                continue
            yield fact("endpoint", method + " " + path, "Anonymous JSON response observed during public navigation.", ("responses", index), method=method, path=path[:300], source_name=label, attributes={"servers": [urlsplit(row.get("final_url") or row.get("url")).scheme + "://" + host] if host else [], "response_shape": row["response_shape"], "contract_basis": "observed_response", "status": row.get("status"), "initiator": row.get("initiator"), "page_url": row.get("page_url"), "cache_control": row.get("headers", {}).get("cache-control"), "read_operation": row.get("read_operation")})
        response_shape = row.get("response_shape")
        if row.get("resource_type") in {"fetch", "xhr"} and isinstance(response_shape, dict) and 200 <= row.get("status", 0) < 400:
            path = urlsplit(row.get("url", "")).path or "/"
            name = ("Response " + (host or "") + path)[:100]
            pointer = ("responses", index, "response_shape")
            yield fact("entity", name, "Observed JSON response structure.", pointer, attributes={"schema_role": "observed_response"})
            for key, value in list(response_shape.items())[:30]:
                if not isinstance(key, str):
                    continue
                kind = "object" if isinstance(value, dict) else "array" if isinstance(value, list) else value if value in {"string", "number", "boolean", "null", "object", "array", "value"} else "unknown"
                yield fact("field", name + "." + key, "Field type in the observed public response.", pointer + (key,), source_name=name, field_name=key, data_type=kind, attributes={"schema_role": "observed_response"})
    coverage = data.get("coverage", {})
    attempts = coverage.get("blocked", []) if isinstance(coverage, dict) else []
    for index, attempt in enumerate(attempts[:96] if isinstance(attempts, list) else []):
        if not isinstance(attempt, dict) or attempt.get("method") not in {"POST", "PUT", "PATCH", "DELETE", "OPTIONS"} or attempt.get("resource_type") not in {"fetch", "xhr"} or not isinstance(attempt.get("url"), str):
            continue
        try:
            parsed = urlsplit(attempt["url"])
        except ValueError:
            continue
        if not parsed.hostname or parsed.scheme not in {"http", "https"}:
            continue
        label = ("API interface " + parsed.hostname)[:100]
        pointer = ("coverage", "blocked", index)
        yield fact("component", label, "Client request destination; the non-read request was blocked.", pointer, component_kind="api")
        yield fact("connection", "attempts " + attempt["method"], "Request initiated by the page, recorded without execution.", pointer, source_name="Web client", target_name=label, attributes={"relationship_kind": "observed_request_attempt", "initiator": attempt.get("initiator")})
        if len(parsed.path or "/") <= 300:
            yield fact("endpoint", attempt["method"] + " " + (parsed.path or "/"), "Client request attempt; response and server behavior were not observed.", pointer, method=attempt["method"], path=parsed.path or "/", source_name=label, attributes={"contract_basis": "observed_request_attempt", "executed": False})
    for kind, label in (("script", "Client assets"), ("stylesheet", "Presentation assets"), ("manifest", "Application manifest")):
        resources = [(i, row) for i, row in enumerate(data.get("resources", [])[:200]) if isinstance(row, dict) and row.get("kind") == kind]
        if resources:
            path = ("resources", resources[0][0])
            yield fact("component", label, "Resources explicitly linked by the public page.", path, component_kind="resource", attributes={"resource_count": len(resources), "resource_urls": [r.get("url") for _, r in resources][:40]})
            yield fact("connection", "links " + kind + " resources", "The page declares these linked resources; execution is recorded separately.", path, source_name="Web client", target_name=label)
    signal_keys = set()
    for index, signal in enumerate(data.get("signals", [])[:80]):
        key = (signal.get("name"), signal.get("basis"), signal.get("url"))
        if key in signal_keys:
            continue
        signal_keys.add(key)
        if isinstance(signal, dict) and signal.get("name") and signal.get("marker"):
            yield fact("technology", str(signal["name"]), "Shipped application marker." if signal.get("basis") in {"shipped_marker", "rendered_markup"} else "Technology identified by an observed HTTP response header.", ("signals", index), dependency_group="observed_delivery" if signal.get("basis") == "response_header" else "shipped_application", attributes={"marker": signal["marker"], "basis": signal.get("basis"), "resource_url": signal.get("url")})
    surfaces=data.get('surface',[])
    for index,page in enumerate(surfaces[:12] if isinstance(surfaces,list) else []):
        if not isinstance(page,dict):continue
        from .page_access import surface_access
        state = surface_access(page)
        if not page.get('content_available', state['content_available']) or not state['content_available']:
            continue
        if isinstance(page.get('navigation'),list) and page['navigation']:
            routes=[row for row in page['navigation'][:24] if isinstance(row,dict) and isinstance(row.get('url'),str) and isinstance(row.get('label'),str)]
            yield fact('component','Page navigation','Public navigation declared by the page.',('surface',index,'navigation'),component_kind='resource',attributes={'routes':routes})
            yield fact('connection','provides navigation','Links present in the observed page.',('surface',index,'navigation'),source_name='Web client',target_name='Page navigation',attributes={'relationship_kind':'page_navigation'})
        forms=page.get('forms',[])
        for form_index,form in enumerate(forms[:8] if isinstance(forms,list) else []):
            if not isinstance(form,dict) or not isinstance(form.get('action'),str) or not isinstance(form.get('fields'),list):continue
            try:parsed=urlsplit(form['action'])
            except ValueError:continue
            if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:continue
            label=form.get('label');label=label if isinstance(label,str) else ''
            name=('Form '+parsed.netloc+(parsed.path or '/'))[:100];path=('surface',index,'forms',form_index)
            yield fact('component',name,'Public form interface declared in markup.',path,component_kind='api',attributes={'action':form['action'],'method':form.get('method'),'structure_kind':'public_form','label':label})
            yield fact('connection','declares form','Public form rendered within the page.',path,source_name='Web client',target_name=name,attributes={'relationship_kind':'form_interface'})
            yield fact('entity',name,'Fields declared by a public form; not a private database schema.',path,attributes={'schema_role':'public_form'})
            for field_index,field in enumerate(form['fields'][:30]):
                if not isinstance(field,dict) or not isinstance(field.get('name'),str):continue
                yield fact('field',name+'.'+field['name'],'Field declared in the form interface.',path+('fields',field_index),source_name=name,field_name=field['name'],data_type=str(field.get('type','text')),attributes={'required':bool(field.get('required')),'schema_role':'public_form'})
            method=form.get('method','GET')
            if isinstance(method,str) and method in {'GET','POST'}:yield fact('endpoint',method+' '+(parsed.path or '/'),'HTML form action; not an independently verified API contract.',path,method=method,path=(parsed.path or '/')[:300],source_name=name,attributes={'contract_basis':'form_action','contract_kind':'form_action','executed':False})


def collect_browser(options, seed, stop=lambda: None):
    """Internal service is configured by the operator, never supplied by the target."""
    import httpx

    from .config import settings
    stop()
    with httpx.Client(timeout=80, trust_env=False) as client:
        response = client.post(settings().browser_observer_url.rstrip("/") + "/observe", json={"url": seed, "external_resources": bool(options.get("linked_external_scripts")), "page_limit": options.get("browser_page_limit", 3), "read_only_operations": bool(options.get("browser_read_operations", False)), "interaction_limit": options.get("browser_interaction_limit", 3), "published_pages": options.get("browser_published_pages", [])})
        response.raise_for_status()
        if len(response.content) > 12_000_000:
            raise ValueError("Browser observation exceeds the response budget.")
        result = response.json()
    stop()
    if not isinstance(result, dict) or result.get("snapshot", {}).get("contract") != CONTRACT:
        raise ValueError("Browser observation contract did not validate.")
    return result
