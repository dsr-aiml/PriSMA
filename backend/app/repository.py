"""Static repository relationships. No imported program is run or evaluated."""

import json
import re
from pathlib import PurePosixPath

BUILTINS = set(
    "assert async_hooks buffer child_process cluster console crypto dgram diagnostics_channel dns domain events fs http http2 https inspector module net os path perf_hooks process punycode querystring readline repl stream string_decoder sys timers tls trace_events tty url util v8 vm wasi worker_threads zlib test".split()
)


def clean_js(text):
    """Mask comments, preserving offsets and quoted literals."""
    output = list(text)
    pattern = r"""("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(//[^\n]*|/\*[\s\S]*?\*/)"""
    for match in re.finditer(pattern, text):
        if match[2]:
            output[match.start() : match.end()] = ["\n" if c == "\n" else " " for c in match[0]]
    return "".join(output)


def read_configuration(text):
    """JSON with comments/trailing commas; never alter punctuation inside strings."""
    content = clean_js(text)
    output = list(content)
    quote, escaped = False, False
    for index, character in enumerate(content):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quote = False
        elif character == '"':
            quote = True
        elif character == ",":
            following = index + 1
            while following < len(content) and content[following].isspace():
                following += 1
            if following < len(content) and content[following] in "}]":
                output[index] = " "
    try:
        value = json.loads("".join(output))
        return value if isinstance(value, dict) else {}
    except (ValueError, RecursionError):
        return {}


def balanced(text, start):
    pairs = {"{": "}", "[": "]", "(": ")"}
    if start >= len(text) or text[start] not in pairs:
        return None
    stack, quote, escaped = [], None, False
    for index in range(start, len(text)):
        c = text[index]
        if quote:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                quote = None
            continue
        if c in ('"', "'", "`"):
            quote = c
        elif c in pairs:
            stack.append(pairs[c])
        elif c in "}])":
            if not stack or stack.pop() != c:
                return None
            if not stack:
                return index + 1
    return None


def members(text, start, end):
    """Yield top-level key/value slices of an object, including nested definitions."""
    cursor = start + 1
    while cursor < end - 1:
        match = re.match(r"""\s*(?:["']([\w$.-]+)["']|([\w$]+))\s*:\s*""", text[cursor:end])
        if not match:
            break
        key = match[1] or match[2]
        value_start = cursor + match.end()
        index = value_start
        while index < end - 1:
            c = text[index]
            if c in "{[(":
                boundary = balanced(text, index)
                if boundary is None:
                    return
                index = boundary
            elif c in ('"', "'", "`"):
                quote = c
                index += 1
                while index < end and (text[index] != quote or text[index - 1] == "\\"):
                    index += 1
                index += 1
            elif c == ",":
                break
            else:
                index += 1
        yield key, value_start, index, cursor
        cursor = index + 1


def path_of(item):
    return item.source_url.removeprefix("local:").split("?", 1)[0]


def resolve(base, reference, paths):
    if not reference.startswith("."):
        return None
    parts = list(PurePosixPath(base).parent.parts)
    for part in PurePosixPath(reference).parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        elif part != ".":
            parts.append(part)
    candidate = "/".join(parts)
    for suffix in ("", ".js", ".ts", ".jsx", ".tsx", ".mjs", "/index.js", "/index.ts"):
        if candidate + suffix in paths:
            return candidate + suffix
    return None


def anchor(item, needle):
    return {"evidence_id": item.id, "needle": needle}


def make(item, kind, name, needle, detail, **extra):
    offset = item.content.find(needle)
    if offset < 0:
        return None
    quote = item.content[max(0, offset - 20) : min(len(item.content), offset + len(needle) + 70)][:500]
    if len(quote) < 12:
        return None
    return dict(
        kind=kind,
        name=name[:320],
        detail=detail[:500],
        classification="observed",
        evidence_id=item.id,
        needle=needle,
        quote=quote,
        **extra,
    )


def repository_facts(evidence, syntax=None):
    syntax = {row["path"]: row for row in syntax} if syntax is not None else None
    paths = {path_of(item): item for item in evidence}
    imports, mounts, packages = {}, {}, {}
    for path, item in paths.items():
        if PurePosixPath(path).name == "package.json":
            try:
                manifest = json.loads(item.content)
            except ValueError:
                continue
            if isinstance(manifest, dict):
                packages[str(PurePosixPath(path).parent)] = (str(manifest.get("name") or PurePosixPath(path).parent.name or "Application package")[:100], item)

    def package_for(path):
        candidates = [root for root in packages if root == "." or path.startswith(root + "/")]
        return packages[max(candidates, key=len)] if candidates else None

    for path, item in paths.items():
        if item.source_type not in ("javascript", "typescript"):
            continue
        content = clean_js(item.content)
        imports[path] = {}
        for match in re.finditer(
            r"""\bimport\s+([\w$]+)\s+(?:,.*?)?from\s*['"]([^'"]+)['"]|\b(?:const|let|var)\s+([\w$]+)\s*=\s*require\(\s*['"]([^'"]+)['"]""",
            content,
        ):
            name, reference = (match[1], match[2]) if match[1] else (match[3], match[4])
            target = resolve(path, reference, paths)
            if target:
                imports[path][name] = target
        for match in re.finditer(
            r"""\b(?:app|router|server)\.use\(\s*['"](/[^'"]*)['"]\s*,\s*([\w$]+)\s*\)""", content
        ):
            if syntax is not None and match.start() not in {row["start"] for row in syntax.get(path, {}).get("mounts", [])}:
                continue
            target = imports[path].get(match[2])
            if target:
                mounts.setdefault(target, []).append((path, match[1].rstrip("/"), match[0]))

    def prefixes(path, seen=frozenset()):
        if path in seen or len(seen) >= 40:
            return []
        result = []
        for parent, prefix, needle in mounts.get(path, [])[:20]:
            upstream = prefixes(parent, seen | {path}) or [("", [])]
            for inherited, anchors in upstream:
                result.append((inherited + prefix, anchors + [anchor(paths[parent], needle)]))
        return result[:20]

    for path, item in paths.items():
        if item.source_type not in ("javascript", "typescript"):
            continue
        content = clean_js(item.content)
        owner = package_for(path)
        api_name = (owner[0] + " API") if owner else "Application API"
        for match in re.finditer(
            r"""\b(?:app|router|server)\.(get|post|put|patch|delete|head|options)\s*\(\s*['"](/[^'"]*)['"]""",
            content,
            re.I,
        ):
            if syntax is not None and match.start() not in {row["start"] for row in syntax.get(path, {}).get("routes", [])}:
                continue
            known = prefixes(path)
            for prefix, extra_anchors in known or [("", [])]:
                route = prefix + (match[2] if match[2] != "/" or not prefix else "")
                yield make(
                    item,
                    "endpoint",
                    match[1].upper() + " " + route,
                    match[0],
                    "Mounted application route."
                    if known
                    else "Route declaration; its external mount is not established.",
                    method=match[1].upper(),
                    path=route,
                    context="repository",
                    anchors=extra_anchors,
                    source_path=path,
                    mount_resolved=bool(known),
                    source_name=api_name,
                )
            yield make(
                item,
                "component",
                api_name,
                match[0],
                "HTTP routes declared in repository source.",
                context="repository",
                source_path=path,
            )
            if owner:
                label, package = owner
                yield make(
                    package,
                    "component",
                    label,
                    package.content[:120],
                    "Application package containing the declared routes.",
                    context="repository",
                    source_path=path_of(package),
                )
                yield make(
                    item,
                    "connection",
                    label + " implements " + api_name,
                    match[0],
                    "Route implementation belongs to the enclosing application package.",
                    source_name=label,
                    target_name=api_name,
                    context="repository",
                    anchors=[anchor(package, package.content[:120])],
                )
        schemas = {}
        for match in re.finditer(
            r"\b(?:const|let|var)\s+([\w$]+)\s*=\s*new\s+(?:mongoose\.)?Schema\s*\(\s*\{", content
        ):
            if syntax is not None and not any(row.get("construct") and match.start() <= row["start"] < match.end() for row in syntax.get(path, {}).get("calls", [])):
                continue
            start = match.end() - 1
            end = balanced(content, start)
            if end:
                schemas[match[1]] = (start, end)
        for match in re.finditer(
            r"""\b(?:mongoose\.)?model\s*\(\s*['"]([^'"]+)['"]\s*,\s*([\w$]+)""", content
        ):
            if syntax is not None and match.start() not in {row["start"] for row in syntax.get(path, {}).get("calls", [])}:
                continue
            if match[2] not in schemas:
                continue
            name = match[1]
            yield make(
                item,
                "entity",
                name,
                match[0],
                "Mongoose model declared in repository source.",
                context="repository",
                source_path=path,
            )
            start, end = schemas[match[2]]
            for field, value_start, value_end, key_start in members(content, start, end):
                value = content[value_start:value_end]
                dtype = re.search(r"\btype\s*:\s*([\w.]+)", value)
                dtype = dtype[1] if dtype else (re.match(r"[\w.]+", value) or ["Object"])[0]
                if value.strip().startswith("["):
                    dtype = "Array<" + dtype + ">"
                ref = re.search(r"""\bref\s*:\s*['"]([^'"]+)['"]""", value)
                needle = item.content[key_start : min(value_end, key_start + 300)].strip()
                yield make(
                    item,
                    "field",
                    name + "." + field,
                    needle,
                    "Declared model field: " + value.strip()[:230],
                    source_name=name,
                    field_name=field,
                    data_type=dtype,
                    context="repository",
                    source_path=path,
                )
                if ref:
                    yield make(
                        item,
                        "entity_relationship",
                        name + " references " + ref[1],
                        needle,
                        "Explicit Mongoose reference.",
                        source_name=name,
                        target_name=ref[1],
                        field_name=field,
                        context="repository",
                        source_path=path,
                    )


def repository_inventory(evidence):
    paths = {path_of(item): item for item in evidence}
    modules = []
    for path, item in paths.items():
        references = []
        if item.source_type in ("javascript", "typescript"):
            for match in re.finditer(
                r"""(?:\bfrom\s+|\brequire\(\s*|\bimport\s*)['"]([^'"]+)['"]""", clean_js(item.content)
            ):
                reference = match[1]
                references.append(
                    {
                        "name": reference,
                        "resolved_path": resolve(path, reference, paths),
                        "kind": "internal"
                        if reference.startswith(".")
                        else "builtin"
                        if reference.removeprefix("node:").split("/")[0] in BUILTINS
                        else "external",
                        "offset": match.start(),
                    }
                )
        modules.append(
            {"path": path, "evidence_id": item.id, "format": item.source_type, "imports": references[:200]}
        )
    return {
        "modules": modules,
        "scope": "Static declarations and resolvable relative JavaScript/TypeScript imports. Dynamic imports, generated routes and runtime behavior require additional evidence.",
    }
