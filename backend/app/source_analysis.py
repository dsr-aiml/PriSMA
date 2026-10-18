"""Content classification and static facts. Imported code is never executed."""

import ast
import json
import re
import tomllib
from html.parser import HTMLParser
from pathlib import PurePosixPath

import yaml
from packaging.requirements import InvalidRequirement, Requirement

from .repository import BUILTINS, clean_js, read_configuration, repository_facts

FORMATS = {
    ".md": "markdown",
    ".mdx": "markdown",
    ".txt": "text",
    ".html": "html",
    ".htm": "html",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".mermaid": "text",
    ".mmd": "text",
    ".har": "json",
    ".sql": "sql",
    ".prisma": "code",
    ".ini": "config",
    ".conf": "config",
    ".cfg": "config",
    ".env.example": "config",
}
KINDS = {
    "documentation": "Documentation",
    "architecture": "Architecture",
    "api_reference": "API reference",
    "pricing": "Pricing",
    "source_code": "Source code",
    "configuration": "Configuration",
    "manifest": "Dependency manifest",
    "api_response": "Response example",
    "data": "Data",
    "other": "Other",
    "runtime_trace": "Public observation",
    "release_history": "Release history",
}


class ScriptEntries(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("src"):
            self.entries.append(self.get_starttag_text())


FORMATS.update(
    {
        extension: "code"
        for extension in (
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".cs",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".rb",
            ".php",
            ".swift",
            ".scala",
            ".vue",
            ".svelte",
            ".graphql",
            ".gql",
            ".css",
            ".scss",
            ".tf",
        )
    }
)
FORMATS.update({".csv": "text", ".xml": "text", ".rst": "text", ".log": "text"})
FORMATS.update({".kts":"code", ".gradle":"config", ".properties":"config", ".csproj":"config", ".vbproj":"config", ".fsproj":"config"})


def file_format(name):
    base = PurePosixPath(name).name.lower()
    if re.fullmatch(r"requirements(?:[-_.](?:dev|test|prod|production))?\.txt",base):
        return "config"
    if base.startswith("dockerfile"):
        return "dockerfile"
    if base in (
        "requirements.txt",
        "go.mod",
        "cargo.lock",
        "gemfile",
        "makefile",
        "procfile",
        ".env.example",
        ".gitignore",
        ".dockerignore",
    ):
        return "config"
    return FORMATS.get(PurePosixPath(base).suffix, "text")


def bounded_tree(value, *, depth=0, ancestors=None, counter=None):
    ancestors = set() if ancestors is None else ancestors
    counter = [0] if counter is None else counter
    counter[0] += 1
    if counter[0] > 30000 or depth > 40:
        raise ValueError("Structured document exceeds the parser budget.")
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            raise ValueError("Cyclic document aliases are unsupported.")
        ancestors.add(id(value))
        for child in value.values() if isinstance(value, dict) else value:
            bounded_tree(child, depth=depth + 1, ancestors=ancestors, counter=counter)
        ancestors.remove(id(value))


def structured(content, format):
    if format == "yaml":
        result = yaml.safe_load(content)
    elif format == "toml":
        result = tomllib.loads(content)
    else:
        result = json.loads(content)
    bounded_tree(result)
    return result


def prepare_source(source):
    """Detect formats using content; retain the raw supplied document separately."""
    if source.origin.casefold().endswith(".har"):
        from .traffic_intake import sanitize_har
        sanitized = json.dumps(sanitize_har(json.loads(source.content)), ensure_ascii=False, indent=2)
        source = source.model_copy(update={"content": sanitized, "format": "json"})
    detected = file_format(source.origin.removeprefix("local:"))
    format = source.format
    if format in ("text", "markdown") and detected not in ("text", "markdown"):
        format = detected
    if format == "text" and detected == "text":
        from .resource_policy import resource_format
        format = resource_format(source.origin, content=source.content)
    candidate = source.content.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[^\n]*\n|\n```\s*$", "", candidate).strip()
    if candidate.startswith("{") and format in ("text", "markdown", "json"):
        format = "json"
    if format in ("json", "yaml", "openapi"):
        try:
            try:
                data = structured(candidate, "json" if format == "openapi" else format)
            except ValueError:
                # Markdown renderers escape punctuation inside otherwise valid JSON.
                # Recover specifications only, and keep the original bytes separate.
                if format == "yaml" or not re.search(r'"(?:openapi|swagger)"\s*:', candidate):
                    raise
                repaired = re.sub(r"(?<!\\)\\([_*`#])", r"\1", candidate)
                data = structured(repaired, "json")
            if isinstance(data, dict) and (data.get("openapi") or data.get("swagger")):
                # A canonical readable copy enables deterministic spans for JSON or YAML.
                return source.model_copy(update={"format": "openapi"}), json.dumps(
                    data, ensure_ascii=False, indent=2
                )
        except (ValueError, TypeError, RecursionError, yaml.YAMLError):
            pass
    return source.model_copy(
        update={"format": format}
    ), candidate if candidate != source.content.strip() else None


def inspect_document(source, content):
    origin = getattr(source, "origin", getattr(source, "source_url", ""))
    name = PurePosixPath(origin.removeprefix("local:").split("?", 1)[0]).name.casefold()
    format = getattr(source, "format", getattr(source, "source_type", "text"))
    kind, priority, eligible = "documentation", 5, True
    warnings = []
    data = None
    if format in ("json", "yaml", "toml", "openapi"):
        try:
            data = structured(content, "json" if format == "openapi" else format)
        except (ValueError, TypeError, RecursionError, yaml.YAMLError):
            data = read_configuration(content) if name.startswith("tsconfig") and name.endswith(".json") else None
            if not data:
                warnings.append("Structured content could not be parsed; original text is retained.")
    if format == "openapi":
        kind, priority, eligible = "api_reference", 0, False
    elif isinstance(data, dict) and data.get("contract") == "prisma.public-observation.v1":
        kind, priority, eligible = "runtime_trace", 1, False
    elif name in {"changelog.md", "changelog.txt", "changes.md", "history.md", "release_notes.md", "release-notes.md"}:
        kind, priority, eligible = "release_history", 8, False
    elif name.endswith(".har") and isinstance(data, dict) and isinstance(data.get("log"), dict) and isinstance(data["log"].get("entries"), list):
        kind, priority, eligible = "runtime_trace", 1, False
    elif name in ("package.json", "pyproject.toml", "requirements.txt", "cargo.toml", "go.mod", "gemfile", "pom.xml", "build.gradle", "build.gradle.kts", "libs.versions.toml", "composer.json") or name.endswith(".csproj") or re.fullmatch(r"requirements[-_.](?:dev|test|prod|production)\.txt",name):
        kind, priority, eligible = "manifest", 1, False
    elif (name.startswith("tsconfig") and name.endswith(".json")) or name in {"server.json", "vercel.json", "amplify.yml", "pnpm-workspace.yaml"}:
        kind, priority, eligible = "configuration", 1, False
    elif isinstance(data, dict) and isinstance(data.get("services"), dict):
        kind, priority, eligible = "configuration", 1, False
    elif format in ("yaml", "toml", "dockerfile", "config", "xml") or name.endswith(".xml") or name in {"settings.gradle.kts", "androidmanifest.xml"}:
        kind, priority, eligible = "configuration", 3, False
    elif (
        format == "html"
        and len(re.sub(r"<script\b[^>]*>", "", content, flags=re.I).strip()) < 200
        and re.search(r"<script\b[^>]*\bsrc\s*=", content, re.I)
    ):
        kind, priority, eligible = "source_code", 2, False
    elif format in ("python", "javascript", "typescript", "sql", "code", "css"):
        kind, priority, eligible = "source_code", 2, False
    elif format == "json":
        response_keys = {"origin", "uuid", "headers", "args", "gzipped", "brotli", "deflated", "user-agent"}
        echoed = isinstance(data, dict) and set(data) & response_keys
        markdown_json = re.search(r'"(?:headers|user-agent|gzipped|deflated|brotli|args)"\s*:', content)
        kind = "api_response" if echoed or markdown_json else "data"
        priority, eligible = 9, False
    elif re.search(r"(?:unicode\s+demo|UTF-8 encoded sample plain-text file)", content[:500], re.I):
        kind, priority, eligible = "data", 9, False
    elif source.category == "pricing" or re.search(
        r"\b(pricing|subscription plans|per month|per seat)\b", content[:1500], re.I
    ):
        kind, priority = "pricing", 2
    elif re.search(
        r"\b(architecture|deployment|data flow|system design|worker|queue|database|gateway)\b",
        content[:2000],
        re.I,
    ):
        kind, priority = "architecture", 1
    elif re.search(
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+/|\bAPI reference\b|\bReturns (?:GET|POST|PUT|PATCH|DELETE) data",
        content,
    ):
        kind, priority = "api_reference", 2
    elif len(content) < 200 and not re.search(
        r"\b(API|service|application|server|integration|framework)\b", content, re.I
    ):
        kind, priority, eligible = "data", 9, False
    if format == "python":
        try:
            ast.parse(content)
        except (SyntaxError, ValueError, RecursionError):
            warnings.append("Python syntax could not be parsed; source text is retained.")
    from .source_intake import source_role
    role = source_role(origin)
    if role in {"test", "third_party", "support"} and kind != "api_reference" and name not in {"package.json", "pyproject.toml", "requirements.txt"}:
        priority, eligible = 9, False
    if re.search(r"readme[._-][a-z]{2}(?:[._-]|\.)", name):
        priority, eligible = 9, False
    if name.endswith((".mermaid", ".mmd")):
        kind, priority, eligible = "architecture", 1, False
        if not re.match(r"\s*(?:flowchart|graph)\s+(?:TD|TB|BT|LR|RL)\b", content):
            warnings.append("Diagram grammar is retained but not supported by the flowchart scanner.")
    reason = (
        "Inventory retained"
        if format == "code"
        else "Structural review"
        if not eligible and priority < 9
        else "Background material"
        if not eligible
        else "Semantic review"
    )
    normalization_steps = []
    if format == "openapi":
        normalization_steps.append("Canonical specification text; original content retained")
        raw = getattr(source, "content", "")
        if re.search(r"(?<!\\)\\[_*`#]", raw):
            normalization_steps.append("Markdown punctuation escapes recovered")
    return {
        "document_kind": kind,
        "source_role": role,
        "kind_label": KINDS.get(kind, kind),
        "analysis_priority": priority,
        "eligible_for_model": eligible,
        "format_detected": format,
        "parse_warnings": warnings,
        "normalization_steps": normalization_steps,
        "analysis_reason": reason,
        "parser_data": data,
    }


def declared_facts(evidence, scanner=None):
    """Return facts with exact document anchors; no adoption inferred from examples."""
    for item in evidence:
        content = item.content
        format = item.source_type
        name = PurePosixPath(item.source_url.removeprefix("local:").split("?", 1)[0]).name.casefold()

        def fact(kind, label, needle, detail, **extra):
            if not isinstance(needle, str) or needle not in content:
                return None
            offset = content.index(needle)
            quote = content[max(0, offset - 20) : min(len(content), offset + len(needle) + 80)]
            if len(quote) < 12:
                return None
            if kind == 'technology':
                from .source_intake import source_role
                role=source_role(item.source_url)
                if role in {'test','support','third_party'}:
                    original=extra.get('dependency_group','source_reference')
                    extra['dependency_group']={'test':'test_dependencies','support':'build_tool','third_party':'third_party'}[role]
                    extra.setdefault('attributes',{})['original_dependency_group']=original
            return {
                "kind": kind,
                "name": label[:320],
                "detail": detail[:500],
                "classification": "observed",
                "evidence_id": item.id,
                "needle": needle,
                "quote": quote[:500],
                **extra,
            }

        def emit(*args, **kwargs):
            value = fact(*args, **kwargs)
            return [value] if value else []

        data = None
        if format in ("json", "yaml", "toml"):
            try:
                data = structured(content, format)
            except (ValueError, TypeError, RecursionError, yaml.YAMLError):
                continue
        if isinstance(data, dict) and isinstance(data.get("services"), dict):
            services = data["services"]
            context = (
                "production"
                if re.search(r"(?:prod|production)", name)
                else "development"
                if re.search(r"(?:dev|development)", name)
                else name
            )
            marks = {}
            if format in ("yaml", "json"):
                document_node = yaml.compose(content)
                if isinstance(document_node, yaml.MappingNode):
                    service_node = next(
                        (value for key, value in document_node.value if key.value == "services"), None
                    )
                    if isinstance(service_node, yaml.MappingNode):
                        marks = {key.value: (key, value) for key, value in service_node.value}
            for service, definition in services.items():
                if not isinstance(service, str) or not isinstance(definition, dict):
                    continue
                yield from emit(
                    "component",
                    service,
                    service,
                    f"Service declared in {name}.",
                    context=context,
                    source_path=item.source_url,
                )
                image = definition.get("image")
                if isinstance(image, str):
                    yield from emit("technology", image, image, f"Container image declared for {service}.", dependency_group="container_images")
                dependencies = definition.get("depends_on", [])
                if isinstance(dependencies, (list, dict)):
                    for target in dependencies:
                        if isinstance(target, str) and target in services:
                            # Config declarations establish dependency, not runtime traffic.
                            extra_quotes = []
                            if service in marks:
                                _, node = marks[service]
                                dependency_node = (
                                    next(
                                        (value for key, value in node.value if key.value == "depends_on"),
                                        None,
                                    )
                                    if isinstance(node, yaml.MappingNode)
                                    else None
                                )
                                if isinstance(dependency_node, yaml.SequenceNode):
                                    target_node = next(
                                        (value for value in dependency_node.value if value.value == target),
                                        None,
                                    )
                                elif isinstance(dependency_node, yaml.MappingNode):
                                    target_node = next(
                                        (key for key, _ in dependency_node.value if key.value == target), None
                                    )
                                else:
                                    target_node = None
                                if target_node:
                                    start, end = target_node.start_mark.index, target_node.end_mark.index
                                    extra_quotes.append(
                                        content[max(0, start - 30) : min(len(content), end + 30)]
                                    )
                            yield from emit(
                                "connection",
                                f"{service} depends on {target}",
                                service,
                                "Declared startup dependency.",
                                source_name=service,
                                target_name=target,
                                extra_quotes=extra_quotes,
                                context=context,
                            )
                build = definition.get("build")
                build_context = build.get("context") if isinstance(build, dict) else build
                if isinstance(build_context, str) and build_context.startswith("."):
                    parts = list(PurePosixPath(item.source_url.removeprefix("local:")).parent.parts)
                    for part in PurePosixPath(build_context).parts:
                        if part == ".." and parts:
                            parts.pop()
                        elif part not in (".", ".."):
                            parts.append(part)
                    package_path = "/".join(parts) + "/package.json"
                    package = next(
                        (e for e in evidence if e.source_url.removeprefix("local:") == package_path), None
                    )
                    if package:
                        declaration = read_configuration(package.content)
                        package_name = str(declaration.get("name") or PurePosixPath(package_path).parent.name)[:100]
                        yield from emit(
                            "connection",
                            service + " builds " + package_name,
                            build_context,
                            "Container build context resolves to the supplied application package.",
                            source_name=service,
                            target_name=package_name,
                            context=context,
                            target_context="repository",
                            anchors=[{"evidence_id": package.id, "needle": package.content[:120]}],
                        )
        if name == "package.json" and isinstance(data, dict):
            label = str(data.get("name") or PurePosixPath(item.source_url.removeprefix("local:")).parent.name or "Application package")[:100]
            yield from emit(
                "component",
                label,
                content[:120],
                "Application package declared by its dependency manifest.",
                context="repository",
                source_path=item.source_url,
                component_kind="application",
            )
            license_name = data.get("license")
            if isinstance(license_name, str):
                match = re.search(r'"license"\s*:\s*"(?:\\.|[^"\\])*"', content)
                if match:
                    yield from emit("assessment", license_name, match[0], "Licence declared by the application package manifest.", attributes={"license": license_name, "license_scope": "package_manifest", "source_path": item.source_url})
            for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                values = data.get(section, {})
                if isinstance(values, dict):
                    for package, version in list(values.items())[:150]:
                        if isinstance(package, str):
                            yield from emit(
                                "technology",
                                package,
                                json.dumps(package),
                                f"{section}: {str(version)[:120]}.",
                                dependency_group=section,
                                version=str(version)[:120],
                                source_path=item.source_url,
                            )
        if name == "pyproject.toml" and isinstance(data, dict):
            project = data.get("project", {})
            if isinstance(project, dict) and isinstance(project.get("name"), str):
                yield from emit("component", project["name"][:100], project["name"], "Python application package declared by its project manifest.", context="repository", source_path=item.source_url, component_kind="application")
            sections=[("dependencies", project.get("dependencies", []))] if isinstance(project,dict) else []
            optional=project.get("optional-dependencies",{}) if isinstance(project,dict) else {}
            if isinstance(optional,dict):
                for group,values in list(optional.items())[:30]:
                    role="test_dependencies" if group in {"test","tests","testing"} else "devDependencies" if group in {"dev","development","lint","docs"} else "optionalDependencies"
                    sections.append((role,values))
            for role,values in sections:
                for dependency in values[:150] if isinstance(values,list) else []:
                    if not isinstance(dependency,str):continue
                    try: requirement=Requirement(dependency)
                    except InvalidRequirement:continue
                    yield from emit("technology", requirement.name, dependency, "Declared Python project dependency.",dependency_group=role,version=str(requirement.specifier),attributes={"extras":sorted(requirement.extras),"marker":str(requirement.marker) if requirement.marker else ""})
            poetry=data.get("tool",{}).get("poetry",{}) if isinstance(data.get("tool"),dict) else {}
            for section,role in (("dependencies","dependencies"),("dev-dependencies","devDependencies")):
                values=poetry.get(section,{}) if isinstance(poetry,dict) else {}
                for package,value in list(values.items())[:150] if isinstance(values,dict) else []:
                    if package.lower()=="python":continue
                    match=re.search(r'(?m)^\s*(?:'+re.escape(package)+r'|"'+re.escape(package)+r'")\s*=.*$',content)
                    if match:
                        version=value if isinstance(value,str) else value.get("version","") if isinstance(value,dict) else ""
                        yield from emit("technology",package,match[0],"Declared Poetry dependency.",dependency_group=role,version=str(version)[:120])
        if name == "requirements.txt" or re.fullmatch(r"requirements[-_.](?:dev|test|prod|production)\.txt",name):
            role="test_dependencies" if "test" in name else "devDependencies" if "dev" in name else "dependencies"
            for line in content.splitlines():
                dependency=re.split(r"\s+#",line.strip(),1)[0]
                if not dependency or dependency.startswith(("#","-")):continue
                try:requirement=Requirement(dependency)
                except InvalidRequirement:continue
                yield from emit("technology", requirement.name, line, "Declared Python dependency.",dependency_group=role,version=str(requirement.specifier),attributes={"marker":str(requirement.marker) if requirement.marker else ""})
        if format == "dockerfile":
            for match in re.finditer(r"(?im)^FROM\s+(?:--\S+\s+)?([^\s]+)", content):
                yield from emit("technology", match[1], match[0], "Declared container base image.",dependency_group="container_images")
        if format == "python" and scanner is None:
            try:
                tree = ast.parse(content)
            except (SyntaxError, ValueError, RecursionError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                    for module in names:
                        if module:
                            yield from emit(
                                "technology",
                                module,
                                ast.get_source_segment(content, node),
                                "Module imported by this source file.",
                            )
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in node.decorator_list:
                        if not isinstance(decorator, ast.Call) or not isinstance(
                            decorator.func, ast.Attribute
                        ):
                            continue
                        method = decorator.func.attr.upper()
                        if (
                            method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
                            or not decorator.args
                        ):
                            continue
                        path = decorator.args[0]
                        if (
                            isinstance(path, ast.Constant)
                            and isinstance(path.value, str)
                            and path.value.startswith("/")
                        ):
                            yield from emit(
                                "component",
                                "Application API",
                                ast.get_source_segment(content, decorator),
                                "Route declarations in application source.",
                            )
                            yield from emit(
                                "endpoint",
                                method + " " + path.value,
                                ast.get_source_segment(content, decorator),
                                f"Route handled by {node.name}.",
                                method=method,
                                path=path.value,
                            )
        if format in ("javascript", "typescript") and scanner is None:
            for match in re.finditer(r"(?:\bfrom\s+|\brequire\(\s*)['\"]([^'\"]+)['\"]", clean_js(content)):
                if (
                    not match[1].startswith((".", "/"))
                    and match[1].removeprefix("node:").split("/")[0] not in BUILTINS
                ):
                    yield from emit(
                        "technology", match[1], match[0], "Module reference in application source."
                    )
        if format == "sql":
            for match in re.finditer(
                r"(?is)\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?([\w.]+)[\"`\]]?\s*\((.*?)\)\s*;",
                content,
            ):
                table = match[1]
                yield from emit(
                    "entity",
                    table,
                    match[0][: min(180, len(match[0]))],
                    "Table declared in the supplied SQL.",
                )
                for column in re.finditer(
                    r"(?:^|,)\s*[\"`\[]?([\w]+)[\"`\]]?\s+([A-Za-z][\w]*(?:\(\d+(?:,\s*\d+)?\))?)", match[2]
                ):
                    if column[1].upper() not in ("PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK"):
                        yield from emit(
                            "field",
                            table + "." + column[1],
                            column[0].lstrip(","),
                            f"Declared SQL column type: {column[2]}.",
                            source_name=table,
                            field_name=column[1],
                            data_type=column[2],
                        )
        if format in ("markdown", "text", "html"):
            for match in re.finditer(
                r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(`?)(/[^\s`<>]+)\2", content
            ):
                yield from emit(
                    "component", "Public API", match[0], "HTTP methods and paths documented in this source."
                )
                yield from emit(
                    "endpoint",
                    match[1] + " " + match[3],
                    match[0],
                    "Documented HTTP route.",
                    method=match[1],
                    path=match[3],
                )
            # Consecutive path and method-bearing descriptions in prose references.
            for match in re.finditer(
                r"(?m)^(/[^\s`<>]+)\s*\n(?:```\s*\n)?\s*\n?(Returns|Accepts)\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+[^\n]+",
                content,
            ):
                yield from emit(
                    "component", "Public API", match[0], "HTTP methods and paths documented in this source."
                )
                yield from emit(
                    "endpoint",
                    match[3] + " " + match[1],
                    match[0],
                    "Documented HTTP route.",
                    method=match[3],
                    path=match[1],
                )

    if scanner is not None:
        yield from scanner["facts"]
        parsed_ids = {m["evidence_id"] for m in scanner["inventory"]["modules"] if m["status"] == "parsed"}
        repository_sources = [e for e in evidence if e.source_type not in {"javascript", "typescript"} or e.id in parsed_ids]
    else:
        repository_sources = evidence
    yield from (value for value in repository_facts(repository_sources, scanner["inventory"]["modules"] if scanner else None) if value)
    from .runtime_evidence import har_facts
    yield from (value for value in har_facts(evidence) if value)
