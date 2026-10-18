"""Document-scoped structural facts and exact path anchors; no imported execution."""

import hashlib
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import yaml


def pointer_index(content):
    """JSON/YAML node marks identify the owner, even when keys repeat."""
    root = yaml.compose(content)
    result = {}

    def walk(node, path=(), key=None, depth=0):
        if depth > 40 or len(result) >= 30000:
            return
        result[path] = ((key or node).start_mark.index, node.end_mark.index)
        if isinstance(node, yaml.MappingNode):
            for child_key, child in node.value:
                walk(child, (*path, child_key.value), child_key, depth + 1)
        elif isinstance(node, yaml.SequenceNode):
            for index, child in enumerate(node.value):
                walk(child, (*path, index), depth=depth + 1)

    walk(root)
    return result


def anchor_fact(item, kind, name, detail, start, end, **extra):
    start = max(0, start)
    end = min(len(item.content), max(end, start + 12), start + 450)
    if end - start < 12:
        start = max(0, end - 12)
    quote = item.content[start:end]
    if len(quote) < 12:
        return None
    return {
        "kind": kind,
        "name": name[:320],
        "detail": str(detail)[:500],
        "classification": "observed",
        "evidence_id": item.id,
        "quote": quote,
        "offset": start,
        "source_path": item.source_url,
        **extra,
    }


def specification_facts(item, context=""):
    if item.source_type != "openapi":
        return
    doc = json.loads(item.content)
    marks = pointer_index(item.content)
    schemas_key = ("components", "schemas") if "components" in doc else ("definitions",)
    schemas = doc.get("components", {}).get("schemas", doc.get("definitions", {}))

    def fact(kind, name, detail, pointer_path, **extra):
        if pointer_path not in marks:
            return None
        start, end = marks[pointer_path]
        attrs = extra.setdefault("attributes", {})
        attrs.setdefault("document_pointer", "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in pointer_path))
        if context:
            suffixes = {"API resources": " resources", "API authentication": " authentication"}
            extra["context"] = context + suffixes.get(extra.get("context"), "")
            if extra.get("target_context") in suffixes:
                extra["target_context"] = context + suffixes[extra["target_context"]]
        return anchor_fact(item, kind, name, detail, start, end, **extra)

    version_key = "openapi" if "openapi" in doc else "swagger"
    yield fact("component", "Public API", "Published API boundary.", (version_key,), component_kind="api")
    yield fact("technology", "OpenAPI", "API description format.", (version_key,))
    servers = doc.get("servers", [])
    if not servers and doc.get("host"):
        servers = [{"url": (doc.get("schemes") or ["https"])[0] + "://" + doc["host"] + doc.get("basePath", "")}]
    server_urls = [urljoin(item.source_url, s["url"]) for s in servers if isinstance(s, dict) and isinstance(s.get("url"), str)][:8] if isinstance(servers, list) else []
    security = doc.get("components", {}).get("securitySchemes", doc.get("securityDefinitions", {}))
    for name, scheme in security.items() if isinstance(security, dict) else []:
        if not isinstance(scheme, dict):
            continue
        path = ("components", "securitySchemes", name) if "components" in doc else ("securityDefinitions", name)
        yield fact("assessment", name, "Declared authentication scheme.", path,
                   attributes={"security_scheme": name, "type": scheme.get("type"), "scheme": scheme.get("scheme"),
                               "location": scheme.get("in"), "parameter": scheme.get("name"), "flows": scheme.get("flows", {})})
        yield fact("component", name, "Authentication scheme declared by the API contract.", path,
                   context="API authentication", component_kind="auth")
        yield fact("connection", "declares authentication", "Authentication scheme declaration.", path,
                   source_name="Public API", target_name=name, target_context="API authentication")

    def references(value):
        found = []
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str):
                found.append(ref)
            for child in value.values():
                found.extend(references(child))
        elif isinstance(value, list):
            for child in value:
                found.extend(references(child))
        return list(dict.fromkeys(found))[:30]

    for path, methods in doc.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "head", "options", "trace"} or not isinstance(operation, dict):
                continue
            parameters = [p for group in (methods.get("parameters", []), operation.get("parameters", [])) if isinstance(group, list) for p in group if isinstance(p, dict)]
            attrs = {
                "operation_id": operation.get("operationId", ""), "summary": operation.get("summary", ""),
                "tags": operation.get("tags", []), "servers": server_urls,
                "security": operation.get("security", doc.get("security", [])),
                "parameters": parameters[:24], "request_body": operation.get("requestBody", {}),
                "responses": operation.get("responses", {}), "schema_references": references(operation),
                "deprecated": operation.get("deprecated", False),
                "operation": operation,
                "document_pointer": "/paths/" + path.replace("~", "~0").replace("/", "~1") + "/" + method,
            }
            yield fact("endpoint", method.upper() + " " + path, operation.get("summary") or "Declared API operation.",
                       ("paths", path, method), method=method.upper(), path=path, source_name="Public API", attributes=attrs)
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        base = (*schemas_key, name)
        yield fact("entity", name, schema.get("description") or "Public resource schema.", base,
                   attributes={"schema_type": schema.get("type", "object"), "required_fields": schema.get("required", []),
                               "composition": {key: schema[key] for key in ("allOf", "oneOf", "anyOf", "$ref") if key in schema}})
        yield fact("component", name, "Resource schema declared by the API contract.", base,
                   component_kind="schema", context="API resources")
        yield fact("connection", "declares resource", "Resource definition in the API contract.", base,
                   source_name="Public API", target_name=name, target_context="API resources")
        property_sets = [(schema.get("properties", {}), (*base, "properties"), schema.get("required", []))]
        for key in ("allOf", "oneOf", "anyOf"):
            for index, branch in enumerate(schema.get(key, [])):
                if isinstance(branch, dict):
                    property_sets.append((branch.get("properties", {}), (*base, key, index, "properties"), branch.get("required", [])))
        for properties, prop_path, required in property_sets:
            for field, definition in properties.items() if isinstance(properties, dict) else []:
                if not isinstance(definition, dict):
                    continue
                ref = definition.get("$ref", "")
                items = definition.get("items", {})
                ref = ref or (items.get("$ref", "") if isinstance(items, dict) else "")
                field_type = definition.get("type", "reference" if ref else "unknown")
                if isinstance(field_type, list):
                    field_type = " | ".join(str(v) for v in field_type)
                if field_type == "array" and isinstance(items, dict):
                    field_type = "array<" + str(items.get("type", ref.rsplit("/", 1)[-1] if ref else "unknown")) + ">"
                attrs = {key: definition[key] for key in ("format", "enum", "default", "example", "nullable", "readOnly", "writeOnly", "minimum", "maximum", "pattern", "description") if key in definition}
                attrs.update(required=field in required or field in schema.get("required", []), schema_reference=ref, schema=definition)
                yield fact("field", name + "." + field, definition.get("description") or "Declared resource property.",
                           (*prop_path, field), source_name=name, field_name=field, data_type=str(field_type)[:120], attributes=attrs)
                for reference in references(definition):
                    target = reference.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
                    if reference.startswith(("#/components/schemas/", "#/definitions/")) and target in schemas:
                        yield fact("entity_relationship", name + " references " + target, "Declared schema reference.",
                                   (*prop_path, field), source_name=name, target_name=target, field_name=field,
                                   attributes={"cardinality": "array" if definition.get("type") == "array" else "single", "schema_reference": reference})
                        yield fact("connection", field + " reference", "Resource property references another declared schema.",
                                   (*prop_path, field), source_name=name, target_name=target, context="API resources")
        for key in ("allOf", "oneOf", "anyOf"):
            for index, branch in enumerate(schema.get(key, [])):
                if isinstance(branch, dict) and branch.get("$ref", "").rsplit("/", 1)[-1] in schemas:
                    target = branch["$ref"].rsplit("/", 1)[-1]
                    yield fact("entity_relationship", name + " " + key + " " + target, "Declared schema composition.",
                               (*base, key, index), source_name=name, target_name=target, field_name=key,
                               attributes={"cardinality": "composition", "composition": key})


class PublicMarkup(HTMLParser):
    """Preserve meaningful declarative markup, not arbitrary inline executable code."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries, self.jsonld, self.buffer = [], [], []
        self.in_jsonld = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        keep = (tag == "script" and values.get("src")) or (tag == "form" and values.get("action")) or (
            tag == "meta" and values.get("name", "").lower() == "generator"
        ) or (tag == "link" and values.get("rel") in {"stylesheet", "preconnect", "modulepreload"})
        if keep and len(self.entries) < 60:
            # Serialize only relevant attributes so huge embedded values cannot dominate.
            pairs = [(k, v) for k, v in attrs if k in {"src", "action", "method", "name", "content", "href", "rel", "type"} and v and len(v) < 2048]
            self.entries.append("<" + tag + " " + " ".join(k + "=" + json.dumps(v) for k, v in pairs) + ">")
        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self.in_jsonld, self.buffer = True, []

    def handle_data(self, data):
        if self.in_jsonld and sum(map(len, self.buffer)) < 50000:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.in_jsonld:
            self.in_jsonld = False
            try:
                data = json.loads("".join(self.buffer))
                # Reuse the source parser's expansion limits.
                from .source_analysis import bounded_tree
                bounded_tree(data)
                if len(self.jsonld) < 8:
                    self.jsonld.append(json.dumps(data, ensure_ascii=False, indent=2))
            except (ValueError, RecursionError):
                pass

    def retained(self):
        return "\n".join(self.entries + ["<script type=\"application/ld+json\">\n" + value + "\n</script>" for value in self.jsonld])


def markup_facts(item):
    if item.source_type != "html":
        return
    parser = PublicMarkup()
    from .source_storage import original_text
    parser.feed(original_text(item))
    from .public_surface import surface_page
    surface = surface_page(original_text(item), item.source_url)
    if surface and not surface.get("content_available", True):
        return
    context = "public surface" if item.collection_method in {"public_file", "tinyfish_fetch", "browser_dom"} else "source markup"
    base = item.source_url if item.source_url.startswith(("https://", "http://")) else ""

    def fact(kind, name, detail, quote, **extra):
        start = item.content.find(quote)
        if start < 0:
            return None
        return anchor_fact(item, kind, name, detail, start, start + len(quote), context=context, **extra)

    if parser.entries or parser.jsonld:
        first = next((entry for entry in parser.entries if entry in item.content), '<script type="application/ld+json">' if parser.jsonld else None)
        if first:
            yield fact("component", "Web client", "Public page and its declared browser resources.", first, component_kind="frontend")
    for tag in parser.entries:
        values = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
        reference = values.get("src") or values.get("href") or values.get("action")
        if tag.startswith("<meta") and values.get("content"):
            yield fact("technology", values["content"], "Page generator declared in metadata.", tag, dependency_group="page_generator")
        if not reference or not base or not parser.entries:
            continue
        resolved = urljoin(base, reference)
        parsed = urlsplit(resolved)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            continue
        if tag.startswith("<script"):
            target = "Delivery origin " + parsed.hostname if parsed.hostname != urlsplit(base).hostname else "Client assets"
            yield fact("component", target, "Declared script resource origin.", tag, component_kind="infrastructure", attributes={"resource_url": resolved})
            yield fact("connection", "loads scripts", "Script resource declared by the page.", tag,
                       source_name="Web client", target_name=target)
            if "/_next/" in parsed.path:
                yield fact("technology", "Next.js", "Next.js client asset path present in markup.", tag, dependency_group="client_asset_marker")
        elif tag.startswith("<form"):
            target = "Form " + parsed.netloc + (parsed.path or "/")
            yield fact("component", target, "Declared form submission boundary.", tag, component_kind="api", attributes={"action": resolved})
            yield fact("connection", "declares form", "Form action declared by the page.", tag, source_name="Web client", target_name=target)
            method = values.get("method", "GET").upper()
            if method in {"GET", "POST"}:
                yield fact("endpoint", method + " " + (parsed.path or "/"), "Declared HTML form action.", tag,
                           method=method, path=parsed.path or "/", source_name=target,
                           attributes={"origin": parsed.netloc, "contract_kind": "form_action", "contract_basis": "form_action", "executed": False})
    for value in parser.jsonld:
        value = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines())
        start = item.content.find(value)
        if start < 0:
            continue
        data = json.loads(value)
        objects = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        marks = pointer_index(value)
        for index, obj in enumerate(objects[:30]):
            if not isinstance(obj, dict):
                continue
            type_name = obj.get("@type")
            if isinstance(type_name, list):
                type_name = next((v for v in type_name if isinstance(v, str)), None)
            if not isinstance(type_name, str):
                continue
            name = obj.get("name")
            if isinstance(name, str):
                path = (index, "name") if isinstance(data, list) else ("@graph", index, "name") if "@graph" in data else ("name",)
                if path not in marks:
                    continue
                left, right = marks[path]
                yield anchor_fact(item, "assessment", name, "Published " + type_name + " structured data.", start + left, start + right,
                                  context=context, attributes={"structured_type": type_name, "structured_data": {k: obj[k] for k in ("name", "description", "offers", "brand", "sku", "url") if k in obj}})


def prose_facts(item):
    """Explicit stack sections are declarations; no hidden stack guessed from prose."""
    if item.source_type not in {"markdown", "text", "html"}:
        return
    from .source_semantics import history_source
    if history_source(item):
        return
    content = item.content
    pattern = r"(?im)^(?:#{1,6}\s*|\*\*)?(Frontend|Backend|Client|Server|Tech Stack|Technology Stack|Dependencies|DevOps)\s*:?(?:\*\*)?\s*$"
    headings = list(re.finditer(pattern, content))
    for index, match in enumerate(headings):
        section = match[1]
        next_heading = re.search(r"(?m)^(?:#{1,6}\s+|\*\*[^\n*]{2,80}\*\*:?\s*$)", content[match.end():])
        boundaries = [len(content), match.end() + 1500]
        if index + 1 < len(headings):
            boundaries.append(headings[index + 1].start())
        if next_heading:
            boundaries.append(match.end() + next_heading.start())
        stop = min(boundaries)
        region = content[match.end():stop]
        entries = list(re.finditer(r"(?m)^\s*[-*]\s+([^\n]+)", region))[:24]
        if not entries:
            continue
        boundary = section if section.lower() in {"frontend", "backend", "client", "server"} else ""
        if boundary:
            yield anchor_fact(item, "component", boundary, "Application boundary declared in the technology stack.", match.start(), match.end() + min(len(region), 100),
                              component_kind="frontend" if section.lower() in {"frontend", "client"} else "service", context="documented application")
        for entry in entries:
            parenthetical = re.findall(r"\(([A-Z][A-Za-z0-9._+-]{1,30})\)", entry[1])
            label = re.sub(r"\([^)]*\)", "", entry[1]).strip().strip("`*")
            if len(label) > 100 or re.search(r"\b(uses|used|supports|provides|not|without)\b|https?://|[.!?]\s", label, re.I):
                continue
            for part in [*re.split(r"\s+&\s+|\s+and\s+", label), *parenthetical]:
                version = re.search(r"\s+v?(\d+(?:\.\d+)*(?:\.x)?)$", part)
                technology = part[:version.start()].strip() if version else part.strip()
                from .source_semantics import technology_exclusion
                if not technology or len(technology) < 2 or technology_exclusion(technology, "documented_stack"):
                    continue
                offset = match.end() + entry.start()
                yield anchor_fact(item, "technology", technology, "Declared in the " + section + " stack.", offset, match.end() + entry.end(),
                                  dependency_group="documented_" + section.lower().replace(" ", "_"), version=version[1] if version else "")
                if boundary and re.search(r"\bAPI\b", technology):
                    yield anchor_fact(item, "component", technology, "API integration listed under " + boundary + ".", offset, match.end() + entry.end(),
                                      component_kind="integration", context="documented application")
                    yield anchor_fact(item, "connection", "declares API integration", "Integration declaration in the " + boundary + " stack.", match.start(), match.end() + entry.end(),
                                      source_name=boundary, target_name=technology, context="documented application")


def document_facts(evidence):
    from .public_code import public_code_facts
    from .prose_structure import document_declarations, mermaid_declarations
    from .web_observation import observation_facts
    from .commercial_facts import commercial_facts
    specifications = [item for item in evidence if item.source_type == "openapi"]
    labels = {}
    for item in specifications:
        data = json.loads(item.content)
        info = data.get("info", {})
        labels[item.id] = str(info.get("title") or "API contract") if isinstance(info, dict) else "API contract"
    for item in evidence:
        context = ""
        if len(specifications) > 1 and item.id in labels:
            context = labels[item.id][:80]
            if list(labels.values()).count(labels[item.id]) > 1:
                context += " (" + hashlib.sha256((item.source_url + item.content_hash).encode()).hexdigest()[:8] + ")"
        yield from (f for f in specification_facts(item, context) or [] if f)
        yield from (f for f in markup_facts(item) or [] if f)
        yield from (f for f in prose_facts(item) or [] if f)
        yield from (f for f in document_declarations(item) or [] if f)
        yield from (f for f in mermaid_declarations(item) or [] if f)
        yield from (f for f in observation_facts(item) or [] if f)
        yield from (f for f in commercial_facts(item) or [] if f)
        yield from (f for f in public_code_facts(item) or [] if f)
