"""Conservative document declarations: hosting, capabilities, licences and simple Mermaid maps."""

import re

TECHNOLOGY_ALIASES = {
    "aws amplify": ("AWS Amplify", "Amplify"),
    "aws ec2": ("AWS EC2", "EC2", "AWS EC2 virtual servers", "EC2 virtual servers"),
    "google gemini api": ("Google Gemini API", "Gemini API"),
    "node.js": ("Node.js", "NodeJS"),
    "postgresql": ("PostgreSQL", "Postgres"),
}
UNCERTAIN = re.compile(r"\b(may|might|could|would|planned|proposed|consider(?:ing)?|not|never|without|no longer)\b", re.I)
INTERACTION = re.compile(r"\b(send\w*|request\w*|call\w*|dispatch\w*|publish\w*|consum\w*|writ\w*|read\w*|enqueue\w*|connect\w*|rout\w*|stor\w*|deliver\w*|access\w*|invok\w*|receiv\w*|fetch\w*|quer\w*|flow\w*|return\w*|serv\w*|use\w*|host\w*|deploy\w*|run\w*)\b", re.I)


def clean_label(value):
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    return re.sub(r"\s+", " ", value.replace("**", "").replace("`", "")).strip(" *:-.")


def aliases(name):
    for variants in TECHNOLOGY_ALIASES.values():
        if name.casefold() in {v.casefold() for v in variants}:
            return variants
    return (name,)


def canonical_name(name):
    return aliases(clean_label(name))[0]


def mentions(name, text):
    return any(re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.I) for value in aliases(name))


def component_role(name, excerpt=""):
    text = name.casefold()
    for pattern, kind in ((r"\b(frontend|client|browser|web ui)\b", "frontend"),
                          (r"\b(database|postgres|postgresql|mysql|mongodb|redis|cache)\b", "database"),
                          (r"\b(queue|broker|kafka|rabbitmq)\b", "queue"),
                          (r"\b(api|gateway)\b", "api"),
                          (r"\b(amplify|ec2|kubernetes|hosting|cdn|load balancer)\b", "infrastructure")):
        if re.search(pattern, text):
            return kind
    if re.search(r"\b(app|application|workspace|product)\b", text):
        return "application"
    # Interpret a role only near this item's own name, never another node's role.
    match = next((m for m in re.finditer(re.escape(name), excerpt, re.I)), None)
    own = excerpt[match.end():match.end() + 100] if match else ""
    if re.search(r"\b(application|workspace)\b", own) and not re.search(r"\b(service|api|worker)\b", own):
        return "application"
    return "service"


def concise_excerpt(name, text, limit=155):
    text = clean_label(text)
    text = re.sub(r"\b(premium|beautifully|well-polished|unparalleled|absolute power of)\b", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) > 1 and re.search(r"\bnot just\b", sentences[0], re.I):
        text = sentences[1]
    else:
        text = sentences[0]
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return text or name + " is described in the source."


def document_declarations(item):
    from .document_facts import anchor_fact

    if item.source_type not in {"markdown", "text", "html"}:
        return
    from .source_semantics import history_source
    if history_source(item):
        return
    content = item.content
    context = "documented application"

    def fact(kind, name, detail, start, end, **extra):
        return anchor_fact(item, kind, name, detail, start, end, **extra)

    # Hosting is a source declaration. A deployment mention is not a measured request path.
    for line in re.finditer(r"(?m)^.*\b(?:deployed|hosted|hosting|runs on)\b[^\n]*$", content, re.I):
        if UNCERTAIN.search(line[0]):
            continue
        text = clean_label(line[0])
        pairs = [(m[2], m[1]) for m in re.finditer(r"\b((?!(?i:using|on|tier|and|deployed|hosted|the|free)\b)[A-Za-z][\w.+-]*(?: [A-Z][\w.+-]*){0,3})(?: virtual servers)?\s*\(\s*((?i:Frontend|Backend|Client|Server))\s*\)", text)]
        # The parenthetical form above can capture prose: require a concise platform label.
        pairs = [(role.title(), host) for role, host in pairs if not re.search(r"\b(using|tier|and|on|deployed|hosted)\b", host, re.I)]
        for match in re.finditer(r"\b((?i:Frontend|Backend|Client|Server))\s+(?:is |are )?(?:deployed|hosted|runs)\s+(?:on|using|in)\s+([A-Z][\w.+-]*(?: [A-Z][\w.+-]*){0,3})", text):
            pairs.append((match[1].title(), match[2]))
        for role, raw_host in dict.fromkeys(pairs):
            host = canonical_name(re.sub(r"\s+virtual servers$", "", raw_host, flags=re.I))
            if not host or len(host) > 80:
                continue
            yield fact("component", role, role + " application declared in deployment documentation.", line.start(), line.end(), component_kind="frontend" if role in {"Frontend", "Client"} else "service", context=context)
            yield fact("component", host, "Hosting platform for the " + role.lower() + ".", line.start(), line.end(), component_kind="infrastructure", context=context, attributes={"aliases": list(aliases(host)), "declaration_kind": "hosting"})
            yield fact("connection", "deployed on", role + " deployment on " + host + ".", line.start(), line.end(), source_name=role, target_name=host, context=context, attributes={"relationship_kind": "deployment"})

    # Feature lists retain every declared capability without guessing commercial entitlements.
    headings = list(re.finditer(r"(?m)^(?:#{1,6}\s+|\*\*)([^\n]+?)(?:\*\*)?\s*$", content))
    for index, heading in enumerate(headings):
        title = clean_label(heading[1]).casefold()
        if not re.search(r"\b(features|capabilities)\b", title):
            continue
        stop = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        for bullet in list(re.finditer(r"(?m)^\s*[-*]\s+([^\n]{12,500})$", content[heading.end():stop]))[:80]:
            text = clean_label(bullet[1])
            if re.search(r"\b(deployed|hosted|hosting)\b", text, re.I) or UNCERTAIN.search(text) or "http" in text:
                continue
            name = re.split(r"\s+(?:using|via|with)\s+|\s*\([^)]*\)\s*$", text, maxsplit=1, flags=re.I)[0].strip()
            if not 5 <= len(name) <= 160:
                continue
            start, end = heading.end() + bullet.start(), heading.end() + bullet.end()
            yield fact("feature", name, concise_excerpt(name, text), start, end, attributes={"capability_declared": True, "commercial_scope": "not_specified"})
            for library in re.findall(r"\(([a-z][a-z0-9_.-]{2,40})\)", text):
                from .source_semantics import technology_exclusion
                if not technology_exclusion(library, "documented_capability") and library not in {"frontend", "backend"}:
                    yield fact("technology", library, "Library named in the capability documentation.", start, end, dependency_group="documented_capability")
            protocol = re.search(r"\bServer-Sent Events\s*\(SSE\)", text, re.I)
            if protocol:
                yield fact("technology", "Server-Sent Events", "Declared response-streaming protocol.", start, end, dependency_group="documented_protocol")

    for line in re.finditer(r"(?im)^.*\b(?:licensed under|license:|licence:)\s+(?:the\s+)?([^\n]+)$", content):
        value = clean_label(re.split(r"\.\s+(?:See|Refer)|\s*\[", line[1], maxsplit=1)[0])
        if not value or len(value) > 160 or value.casefold() in {"this", "license", "licence"} or re.search(r"associated with|license agreement", value, re.I):
            continue
        value = re.split(r"[.;]\s+(?:Third.party|Other|The|This)", value, maxsplit=1, flags=re.I)[0]
        origin = item.source_url.removeprefix("local:")
        scope = "third_party" if re.search(r"(?:^|/)(?:licenses|licences|third.party)/", origin, re.I) else "source_document"
        yield fact("assessment", value, "Declared licence in this source document.", line.start(), line.end(), attributes={"license": value, "license_scope": scope, "source_path": origin})


def mermaid_declarations(item):
    from .document_facts import anchor_fact

    if item.source_type not in {"markdown", "text"}:
        return
    blocks = [(match.start(1), match[1]) for match in re.finditer(r"```mermaid\s*\n([\s\S]*?)```", item.content)][:12]
    if not blocks and re.match(r"\s*(?:flowchart|graph)\s+(?:TD|TB|BT|LR|RL)\b", item.content):
        blocks = [(0, item.content)]
    for number, (block_start, block_text) in enumerate(blocks, 1):
        if not re.match(r"\s*(?:flowchart|graph)\s+(?:TD|TB|BT|LR|RL)\b", block_text):
            continue
        context = "diagram " + str(number) + " · " + item.source_url.removeprefix("local:")[-90:]
        nodes = {}
        # Only labelled, simple nodes are interpreted. IDs alone do not invent components.
        pattern = r'\b([A-Za-z][\w-]{0,60})\s*(?:\[\("?([^\]\n]+?)"?\)\]|\["?([^\]\n]+?)"?\]|\("?([^\)\n]+?)"?\))'
        for match in list(re.finditer(pattern, block_text))[:80]:
            name = clean_label(next(value for value in match.groups()[1:] if value))
            if not name or len(name) > 100 or "<" in name or "{" in name:
                continue
            start = block_start + match.start()
            nodes[match[1]] = name
            yield anchor_fact(item, "component", name, "Component declared in the architecture diagram.", start, block_start + match.end(), context=context, component_kind=component_role(name), attributes={"declaration_kind": "mermaid_node", "diagram_id": match[1]})
        for line in re.finditer(r"[^\n]+", block_text):
            simplified = re.sub(pattern, lambda m: m[1], line[0])
            for edge in re.finditer(r'(?=\b([A-Za-z][\w-]*)\s*(-->|-\.->|==>|<-->)\s*(?:\|([^|\n]{1,80})\|\s*)?([A-Za-z][\w-]*)\b)', simplified):
                source, target = nodes.get(edge[1]), nodes.get(edge[4])
                if not source or not target or source == target:
                    continue
                label = clean_label(edge[3] or "diagram connection")
                start = block_start + line.start()
                declaration = {"kind": "connection", "name": label, "detail": "Diagram declares " + source + " → " + target + ".", "context": context, "source_name": source, "target_name": target, "attributes": {"relationship_kind": "documented_topology"}}
                value = anchor_fact(item, **declaration, start=start, end=block_start + line.end())
                if value:
                    yield value
                    if edge[2] == "<-->":
                        yield {**value, "source_name": target, "target_name": source}
