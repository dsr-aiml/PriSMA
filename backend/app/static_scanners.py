"""Bounded syntax adapters, repository resolution and source-backed module maps."""

import ast
import hashlib
import json
import os
import posixpath
import re
import subprocess
import symtable
import tempfile
import tomllib
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

from .models import ModelCache
from .repository import BUILTINS, clean_js, make, path_of, read_configuration
from .source_intake import source_role
from .native_scanners import LANGUAGES, declaration_scan, build_facts

VERSION = "syntax-scanners-7"
CODE_FORMATS = {"javascript", "typescript", "python"}
SCRIPT = Path(__file__).resolve().parents[1] / "scanners" / "javascript.cjs"


def python_scan(path, content):
    row = dict(path=path, parser="python-ast", status="parsed", imports=[], symbols=[], schemas=[], calls=[], routes=[], mounts=[], resources=[], diagnostics=[], truncated=False)
    try:
        tree = ast.parse(content)
        symbols = symtable.symtable(content, path, "exec")
    except (SyntaxError, ValueError, RecursionError) as exc:
        row.update(status="unparsed", diagnostics=[{"message": str(exc)[:200]}])
        return row
    lines = content.splitlines(keepends=True)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    tables = {(symbols.get_name(), symbols.get_lineno()): symbols}
    queue = [symbols]
    while queue:
        table = queue.pop()
        for child in table.get_children():
            tables[(child.get_name(), child.get_lineno())] = child
            queue.append(child)
    scope_imports = {}
    def scope(node):
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return current.name, current.lineno
            if isinstance(current, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                return {ast.Lambda:"lambda", ast.ListComp:"listcomp", ast.SetComp:"setcomp", ast.DictComp:"dictcomp", ast.GeneratorExp:"genexpr"}[type(current)], current.lineno
            current = parents.get(current)
        return symbols.get_name(), symbols.get_lineno()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.name if isinstance(node, ast.Import) else "." * node.level + (node.module or "")
                local = alias.asname or alias.name.split(".")[0]
                scope_imports[(scope(node), local)] = (name, alias.name if isinstance(node, ast.ImportFrom) else "")
    starts, cursor = [], 0
    for line in lines:
        starts.append(cursor)
        cursor += len(line)

    def span(node):
        def offset(line, column):
            return starts[line - 1] + len(lines[line - 1].encode()[:column].decode("utf-8", errors="ignore"))
        return {"start": offset(node.lineno, node.col_offset), "end": offset(node.end_lineno, node.end_col_offset)}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.name if isinstance(node, ast.Import) else "." * node.level + (node.module or "")
                row["imports"].append({"name": name, "bindings": [{"local": alias.asname or alias.name.split(".")[0], "imported": alias.name if isinstance(node, ast.ImportFrom) else "*"}], **span(node)})
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            row["symbols"].append({"name": node.name, "kind": type(node).__name__, **span(node)})
            if isinstance(node, ast.ClassDef) and (any(ast.unparse(base).split(".")[-1] in {"BaseModel", "TypedDict"} for base in node.bases) or any(ast.unparse(decorator).split("(")[0].split(".")[-1] == "dataclass" for decorator in node.decorator_list)):
                fields = [{"name": statement.target.id, "type": ast.unparse(statement.annotation)[:120], "required": statement.value is None, **span(statement)} for statement in node.body if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)]
                row["schemas"].append({"name": node.name, "kind": "python_declared_type", "fields": fields[:150], **span(node)})
            for decorator in getattr(node, "decorator_list", []):
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.args:
                    method = decorator.func.attr.upper()
                    route = decorator.args[0]
                    if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} and isinstance(route, ast.Constant) and isinstance(route.value, str) and route.value.startswith("/"):
                        row["routes"].append({"method": method, "path": route.value, "receiver": ast.unparse(decorator.func.value), "handler": node.name, **span(decorator)})
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = ast.unparse(node.func)
            else:
                continue
            root = name.split(".")[0]
            table = tables.get(scope(node), symbols)
            reference = None
            imported_name = ""
            try:
                symbol = table.lookup(root)
                if symbol.is_imported() and not symbol.is_assigned():
                    reference, imported_name = scope_imports.get((scope(node), root), (None, ""))
                elif symbol.is_global() and symbols.lookup(root).is_imported() and not symbols.lookup(root).is_assigned():
                    reference, imported_name = scope_imports.get(((symbols.get_name(), symbols.get_lineno()), root), (None, ""))
            except KeyError:
                pass
            row["calls"].append({"name": name[:200], "imported_binding": reference is not None, "reference": reference, "imported_name": imported_name, **span(node)})
    for key in ("imports", "symbols", "calls", "routes", "schemas"):
        if len(row[key]) > 1600:
            row["truncated"] = True
            row[key] = row[key][:1600]
    return row


def js_batch(files):
    environment = dict(os.environ)
    # Native development uses the frontend's installed compiler; images bundle it.
    installed = SCRIPT.parent / "node_modules"
    development = SCRIPT.parents[2] / "frontend" / "node_modules"
    environment["NODE_PATH"] = str(installed if installed.exists() else development)
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(["node", "--max-old-space-size=256", str(SCRIPT)], input=json.dumps({"files": files}).encode(), stdout=output, stderr=subprocess.PIPE, env=environment, timeout=35, check=False)
            output.seek(0, 2)
            if result.returncode or output.tell() > 8_000_000:
                raise ValueError("Syntax scanner did not finish within its resource budget.")
            output.seek(0)
            packet = json.load(output)
            if packet.get("version") != VERSION or len(packet.get("files", [])) != len(files):
                raise ValueError("Invalid scanner contract.")
            return packet["files"]
        except (OSError, subprocess.TimeoutExpired, ValueError, RecursionError):
            return [{"path": f["path"], "parser": "typescript-5.9.3", "status": "unavailable", "imports": [], "symbols": [], "schemas": [], "calls": [], "routes": [], "mounts": [], "resources": [], "diagnostics": [{"message": "JavaScript syntax scanner unavailable or resource budget reached."}], "truncated": False} for f in files]


def candidate_paths(value):
    yield value
    suffix = PurePosixPath(value).suffix
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        replacement = {".js": (".ts", ".tsx", ".d.ts"), ".jsx": (".tsx",), ".mjs": (".mts", ".d.mts"), ".cjs": (".cts", ".d.cts")}[suffix]
        for extension in replacement:
            yield value[:-len(suffix)] + extension
    if not suffix:
        for extension in (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".py"):
            yield value + extension
        for extension in (".ts", ".tsx", ".js", ".mjs", ".cts", ".py"):
            yield value + "/index" + extension
        yield value + "/__init__.py"


def config_document(content):
    return read_configuration(content)


def scan_repository(evidence, *, db=None, user_id=None, stop=lambda: None):
    paths = {path_of(item): item for item in evidence}
    packages, configs = {}, {}
    go_projects = []
    for path, item in paths.items():
        base = PurePosixPath(path).name
        if base == 'go.mod':
            module = re.search(r'(?m)^\s*module\s+(\S+)',item.content)
            if module:go_projects.append((module[1],str(PurePosixPath(path).parent)))
        if base == "package.json":
            data = config_document(item.content)
            if isinstance(data, dict):
                root = str(PurePosixPath(path).parent)
                packages[root] = {"name": str(data.get("name") or PurePosixPath(root).name or "Application package")[:100], "item": item, "data": data}
        if base.startswith("tsconfig") and base.endswith(".json"):
            configs[path] = config_document(item.content)
        if base == "pyproject.toml":
            try:
                data = tomllib.loads(item.content)
                name = data.get("project", {}).get("name")
                if isinstance(name, str):
                    packages[str(PurePosixPath(path).parent)] = {"name": name[:100], "item": item, "data": data}
            except (ValueError, TypeError):
                pass

    def package_for(path):
        roots = [root for root in packages if root == "." or path.startswith(root + "/")]
        return max(roots, key=len) if roots else None

    @lru_cache(maxsize=2048)
    def compiler_options(path):
        candidates = [p for p in configs if str(PurePosixPath(p).parent) == "." or path.startswith(str(PurePosixPath(p).parent) + "/")]
        if not candidates:
            return {}, "."
        selected = min(candidates, key=lambda p: (-len(PurePosixPath(p).parts), 0 if PurePosixPath(p).name == "tsconfig.json" else 1, p))
        seen = set()
        def merge(name):
            if name in seen or len(seen) > 12:
                return {}
            seen.add(name)
            data = configs.get(name, {})
            if not isinstance(data, dict):
                return {}
            extended = data.get("extends", "")
            base = {}
            if isinstance(extended, str) and extended.startswith("."):
                parent = posixpath.normpath(posixpath.join(posixpath.dirname(name), extended))
                base = merge(parent if parent.endswith(".json") else parent + ".json")
            current = data.get("compilerOptions", {})
            return {**base, **current} if isinstance(current, dict) else base
        return merge(selected), posixpath.dirname(selected) or "."

    def resolve(path, reference, imported=""):
        candidates = []
        if paths[path].source_type == "python":
            if reference.startswith("."):
                level = len(reference) - len(reference.lstrip("."))
                directory = posixpath.dirname(path)
                for _ in range(level - 1):
                    directory = posixpath.dirname(directory)
                suffix = reference.lstrip(".").replace(".", "/")
                candidates.append(posixpath.join(directory, suffix))
            else:
                root = package_for(path)
                roots = [root or ".", str(PurePosixPath(path).parts[0]) if len(PurePosixPath(path).parts) > 1 else ".", posixpath.dirname(path)]
                candidates.extend(posixpath.join(root, reference.replace(".", "/")) for root in roots)
        elif reference.startswith("."):
            candidates.append(urljoin(path, reference) if urlsplit(path).scheme in {"http", "https"} else posixpath.join(posixpath.dirname(path), reference))
        else:
            options, directory = compiler_options(path)
            base = posixpath.join(directory, str(options.get("baseUrl", ".")))
            mapping = options.get("paths", {})
            if isinstance(mapping, dict):
                for alias, targets in mapping.items():
                    pattern = "^" + re.escape(alias).replace(r"\*", "(.*)") + "$"
                    match = re.match(pattern, reference)
                    if match and isinstance(targets, list):
                        for target in targets[:8]:
                            if isinstance(target, str):
                                candidates.append(posixpath.join(base, target.replace("*", match[1] if match.groups() else "")))
            if options.get("baseUrl"):
                candidates.append(posixpath.join(base, reference))
            for root, package in packages.items():
                name = package["name"]
                if reference == name:
                    entry = package["data"].get("source") or package["data"].get("main") or "index"
                    if isinstance(entry, str):
                        candidates.append(posixpath.join(root, entry))
                elif reference.startswith(name + "/"):
                    candidates.append(posixpath.join(root, reference[len(name) + 1:]))
        for candidate in candidates:
            candidate = candidate if urlsplit(candidate).scheme in {"http", "https"} else posixpath.normpath(candidate)
            if candidate.startswith("../"):
                continue
            if imported and paths[path].source_type == "python":
                for option in candidate_paths(candidate + "/" + imported):
                    if option in paths:
                        return option
            for option in candidate_paths(candidate):
                if option in paths:
                    return option
            # A declared output directory can map a generated .js reference to its source tree.
            for config_path, data in configs.items():
                if not isinstance(data, dict):
                    continue
                options = data.get("compilerOptions", {})
                if not isinstance(options, dict) or not options.get("outDir") or not options.get("rootDir"):
                    continue
                directory = posixpath.dirname(config_path)
                output = posixpath.normpath(posixpath.join(directory, str(options["outDir"])))
                source = posixpath.normpath(posixpath.join(directory, str(options["rootDir"])))
                if candidate.startswith(output + "/"):
                    mapped = source + candidate[len(output):]
                    for option in candidate_paths(mapped):
                        if option in paths:
                            return option
        return None

    records, misses = {}, []
    for path, item in paths.items():
        native = PurePosixPath(path).suffix.casefold() in LANGUAGES and not path.endswith(".gradle.kts")
        sfc = path.endswith((".vue", ".svelte"))
        if item.source_type not in CODE_FORMATS and not native and not sfc:
            continue
        key = hashlib.sha256(json.dumps([VERSION, user_id, path, item.content_hash], sort_keys=True).encode()).hexdigest()
        cached = db.get(ModelCache, key) if db is not None else None
        compiled = item.source_type=='javascript' and (path.endswith('.min.js') or len(item.content)>16000 and max(map(len,item.content.splitlines()),default=0)>8000)
        if (item.signals or {}).get("compiled_asset") or compiled:
            records[path] = dict(path=path, parser="compiled-asset-inventory", status="inventory_only", imports=[], symbols=[], schemas=[], calls=[], routes=[], mounts=[], resources=[], diagnostics=[{"message":"Compiled asset retained for delivery signatures; original modules require supplied source maps or repository files."}], truncated=False)
        elif cached and cached.result.get("status") in {"parsed", "partial", "unparsed"}:
            records[path] = cached.result
        elif native:
            records[path] = declaration_scan(path, item.content)
            if db is not None:
                db.merge(ModelCache(id=key, user_id=user_id, result=records[path]))
        elif sfc:
            # Parse only executable script blocks, padding markup to preserve offsets.
            output = ['\n' if c == '\n' else ' ' for c in item.content]
            for match in re.finditer(r'<script\b[^>]*>([\s\S]*?)</script\s*>', item.content, re.I):
                output[match.start(1):match.end(1)] = match[1]
            records[path] = js_batch([{"path":path+".ts", "content":''.join(output)}])[0]
            records[path]["path"] = path
        elif item.source_type == "python":
            records[path] = python_scan(path, item.content)
            if db is not None:
                db.merge(ModelCache(id=key, user_id=user_id, result=records[path]))
        else:
            misses.append((path, item, key))
    batch, characters = [], 0
    def flush():
        stop()
        if not batch:
            return
        rows = js_batch([{"path": path, "content": item.content} for path, item, _ in batch])
        for (path, _, key), row in zip(batch, rows, strict=True):
            records[path] = row
            if db is not None and row["status"] != "unavailable":
                db.merge(ModelCache(id=key, user_id=user_id, result=row))
        batch.clear()
    for path, item, key in misses:
        if len(batch) >= 32 or characters + len(item.content) > 2_000_000:
            flush()
            characters = 0
        batch.append((path, item, key))
        characters += len(item.content)
    flush()
    if db is not None:
        db.flush()

    jvm_symbols, jvm_packages = defaultdict(list), defaultdict(list)
    for path, row in records.items():
        package = row.get("package_name", "")
        if package:
            jvm_packages[package].append(path)
            for symbol in row["symbols"]:
                qualified=package+'.'+symbol["name"]
                if path not in jvm_symbols[qualified]:jvm_symbols[qualified].append(path)
    package_prefix = os.path.commonprefix([key.split('.') for key in jvm_packages]) if jvm_packages else []
    # A single-package repository still needs its actual package name for grouping.
    package_prefix = '.'.join(package_prefix)
    modules, bindings, unresolved = [], {}, 0
    remaining_rows = 30000
    for path, row in sorted(records.items()):
        row = dict(row)
        for key in ("imports", "symbols", "calls", "routes", "mounts", "resources", "schemas"):
            values = row[key]
            row[key] = values[:remaining_rows]
            remaining_rows -= len(row[key])
            if len(row[key]) < len(values):
                row["truncated"] = True
        item = paths[path]
        bindings[path] = {}
        imports = []
        for reference in row["imports"]:
            bound = reference.get("bindings", [])
            imported = bound[0].get("imported", "") if bound else ""
            candidates = jvm_symbols.get(reference["name"], []) or jvm_packages.get(reference["name"].removesuffix('.*'), [])
            if not candidates and reference['name'].count('.')>1:
                parts=reference['name'].split('.')
                for length in range(len(parts)-1,1,-1):
                    matches=jvm_symbols.get('.'.join(parts[:length]),[])
                    if len(matches)==1:candidates=matches;break
            suffix=PurePosixPath(path).suffix
            go_internal=False
            if suffix=='.go':
                for name,root in go_projects:
                    if reference['name']==name or reference['name'].startswith(name+'/'):
                        go_internal=True
                        directory=posixpath.normpath(posixpath.join(root,reference['name'][len(name):].lstrip('/')))
                        candidates=[p for p in records if posixpath.dirname(p)==directory and p.endswith('.go')]
                        break
            if suffix in {'.c','.cpp','.h','.hpp'}:
                candidate=posixpath.normpath(posixpath.join(posixpath.dirname(path),reference['name']))
                if candidate in records:candidates=[candidate]
            if len(candidates)>1 and suffix!='.go' and not reference['name'].endswith('.*'):candidates=[]
            target = candidates[0] if candidates else resolve(path, reference["name"], imported)
            builtin = reference["name"].removeprefix("node:").split("/")[0] in BUILTINS if item.source_type != "python" else reference["name"].split(".")[0] in __import__("sys").stdlib_module_names
            options, _ = compiler_options(path)
            declared_aliases = options.get("paths", {}) if isinstance(options, dict) else {}
            mapped_alias = isinstance(declared_aliases, dict) and any(re.fullmatch(re.escape(alias).replace(r"\*", ".*"), reference["name"]) for alias in declared_aliases)
            native = PurePosixPath(path).suffix in LANGUAGES
            builtin |= native and reference["name"].startswith(('java.', 'javax.', 'kotlin.', 'System.', 'std::', 'core::', 'alloc::'))
            builtin |= suffix=='.go' and '.' not in reference['name'].split('/')[0]
            builtin |= suffix in {'.c','.cpp','.h','.hpp'} and reference['name'] in {'stdio.h','stdlib.h','string.h','stdint.h','stdbool.h','math.h','iostream','vector','string','memory','algorithm','utility','map','set'}
            internal = bool(target) or go_internal or mapped_alias or reference["name"].startswith((".", "@/", "~/", "#", 'crate::', 'self::', 'super::')) or bool(native and package_prefix and (reference["name"]==package_prefix or reference["name"].startswith(package_prefix+'.')))
            kind = "internal" if internal else "builtin" if builtin else "external"
            unresolved += int(internal and not target)
            imports.append({**reference, "offset": reference["start"], "kind": kind, "resolved_path": target, "resolved_paths":candidates[:20]})
            if len(candidates)>20:row['truncated']=True
            if target:
                for binding in bound:
                    bindings[path][binding["local"]] = target
        modules.append({**row, "evidence_id": item.id, "format": item.source_type, "role": (item.signals or {}).get("resource_role") or source_role(path), "imports": imports})

    entrypoints = []
    for root, package in packages.items():
        data = package["data"]
        values = [data.get("main"), data.get("source")]
        bins = data.get("bin")
        values += list(bins.values()) if isinstance(bins, dict) else [bins]
        for value in values:
            if isinstance(value, str):
                reference = value if value.startswith(".") else "./" + value
                target = resolve(path_of(package["item"]), reference)
                entrypoints.append({"declaration": value, "resolved_path": target, "package": package["name"], "evidence_id": package["item"].id})
    entry_paths = {entry["resolved_path"] for entry in entrypoints if entry["resolved_path"]}
    def original_module(module):
        item = paths[module["path"]]
        signals = item.signals or {}
        method = signals.get("original_collection_method") or item.collection_method
        return method not in {"browser_script", "public_file"} or bool(signals.get("embedded_path"))

    # Delivered URL paths do not establish original modules or deployed services.
    core = [m for m in modules if original_module(m) and (m["role"] == "application" or m["path"] in entry_paths) and (m["status"] == "parsed" or m["parser"] == "declarations-1")]
    groups, module_group = {}, {}
    try:
        common_root = os.path.commonpath(list(paths)) if paths else "."
    except ValueError:
        common_root = "."
    if common_root in paths:
        common_root = posixpath.dirname(common_root) or "."
    for module in core:
        path = module["path"]
        owner = package_for(path)
        relative = posixpath.relpath(path, owner or common_root or ".")
        parts = PurePosixPath(relative).parts
        if path in entry_paths and module["role"] != "application":
            directory = "Entrypoints"
        elif module.get("package_name"):
            package = module["package_name"]
            relative_package = package.removeprefix(package_prefix).strip('.') or package.split('.')[-1]
            # Functional package segments retain useful boundaries across JVM source trees.
            directory = '/'.join(relative_package.split('.')[:2])
            if '/src/' in path:
                directory = path.split('/src/',1)[0].rsplit('/',1)[-1] + '/' + directory
        elif len(parts) > 2 and parts[0] in {"src", "app", "lib", "packages", "services"}:
            directory = "/".join(parts[:2])
        elif len(parts) > 1:
            directory = parts[0]
        else:
            directory = "Application modules"
        context = "modules:" + (owner or common_root or ".")
        key = (directory, context[:120])
        if key not in groups and len(groups) >= 63:
            key = ("Other source modules", "modules:remaining")
            directory, context = key
        group = groups.setdefault(key, {"label": directory[:100], "context": context[:120], "package": packages.get(owner, {}).get("name"), "modules": [], "symbols": 0})
        group["modules"].append(path)
        group["symbols"] += len(module["symbols"])
        module_group[path] = key

    facts = [fact for fact in build_facts(evidence) if fact]
    def anchored(source_path, kind, name, start, end, detail, **extra):
        item = paths[source_path]
        needle = item.content[start:min(end, start + 300)]
        if len(needle) < 12:
            needle = item.content[max(0, start - 12):min(len(item.content), max(end, start + 30))]
        value = make(item, kind, name, needle, detail, source_path=item.source_url, **extra)
        if value:
            offset = max(0, start - 20)
            value["quote"] = item.content[offset:min(len(item.content), start + max(12, len(needle)) + 70)][:500]
            value["offset"] = offset
            facts.append(value)

    for (label, context), group in groups.items():
        path = group["modules"][0]
        anchored(path, "component", label, 0, min(120, len(paths[path].content)), f"Source module group containing {len(group['modules'])} files and {group['symbols']} declarations.", context=context, component_kind="module_group", attributes={"level": 1, "module_paths": group["modules"], "parent_label": group["package"], "parent_context": "repository", "structure_kind": "source_group"})
        owner = package_for(path)
        if owner:
            package = packages[owner]
            needle = package["item"].content[:120]
            anchored(path, "connection", "contains modules", 0, min(120, len(paths[path].content)), "Module paths belong to the supplied package root.", source_name=package["name"], target_name=label, context="repository", target_context=context, anchors=[{"evidence_id": package["item"].id, "needle": needle}], attributes={"relationship_kind": "contains"})

    for declaration in list(facts):
        android_class=declaration.get('attributes',{}).get('android_class')
        if not android_class:continue
        matches=[path for qualified,targets in jvm_symbols.items() if qualified==android_class or android_class.startswith('.') and qualified.endswith(android_class) for path in targets]
        if len(matches)!=1:continue
        path=matches[0];group=module_group.get(path)
        if not group:continue
        symbol=next((s for s in records[path]['symbols'] if s['name']==android_class.split('.')[-1]),None)
        if symbol:
            anchored(path,'connection','implements registered component',symbol['start'],symbol['end'],'Retained class declaration matches the component registered in the manifest.',source_name=group[0],target_name=declaration['name'],context=group[1],target_context='Android application',anchors=[{'evidence_id':declaration['evidence_id'],'needle':declaration['needle']}],attributes={'relationship_kind':'implements'})

    edges_seen = set()
    languages_seen=set()
    for module in modules:
        path, source = module["path"], module_group.get(module["path"])
        if module["status"] != "parsed" and module["parser"] != "declarations-1":
            continue
        if module["role"] == "application":
            language=LANGUAGES.get(PurePosixPath(path).suffix) or {'javascript':'JavaScript','typescript':'TypeScript','python':'Python'}.get(module['format'])
            basis=next(iter(module.get('symbols',[]) or module.get('imports',[])),None)
            if language and language not in languages_seen and basis:
                languages_seen.add(language)
                anchored(path,'technology',language,basis['start'],basis['end'],'Language present in retained application source.',dependency_group='source_language')
            for schema in module.get("schemas", []):
                context = ("types:" + path[-110:])[:120]
                anchored(path, "entity", schema["name"][:100], schema["start"], schema["end"], "Type definition declared in the supplied source code.", context=context, attributes={"schema_role": schema["kind"]})
                for field in schema["fields"]:
                    anchored(path, "field", schema["name"] + "." + field["name"], field["start"], field["end"], "Property declared by the source type definition.", source_name=schema["name"][:100], field_name=field["name"][:80], data_type=field["type"], context=context, attributes={"required": field["required"]})
        for reference in module["imports"]:
            if reference["kind"] == "external" and module["role"] == "application":
                name = reference["name"]
                dependency_group = "source_usage"
                if PurePosixPath(path).suffix in {'.kt','.java','.scala'}:
                    prefixes={'androidx.compose':'Jetpack Compose','androidx.room':'Room','androidx.media3':'Android Media3','kotlinx.coroutines':'Kotlin Coroutines','kotlinx.serialization':'Kotlin Serialization','io.ktor':'Ktor','dagger':'Dagger','android':'Android SDK'}
                    matched = next((label for prefix,label in prefixes.items() if name==prefix or name.startswith(prefix+'.')), None)
                    name = matched or '.'.join(name.split('.')[:3])
                    if matched is None:dependency_group = "source_reference"
                elif module["format"] in {'javascript','typescript'}:
                    name = '/'.join(name.split('/')[:2]) if name.startswith('@') else name.split('/')[0]
                elif module["format"] == 'python': name = name.split('.')[0]
                elif PurePosixPath(path).suffix in {'.cs','.php','.c','.cpp','.h','.hpp'}:
                    dependency_group='source_reference'
                elif PurePosixPath(path).suffix=='.rs':name=name.split('::')[0]
                # Native namespaces/headers are import inventory, not identified
                # libraries. Keep them in Repository rather than fabricate a stack.
                if dependency_group != 'source_reference':
                    anchored(path, "technology", name, reference["start"], reference["end"], "Imported by application source.", dependency_group=dependency_group)
            targets = reference.get('resolved_paths') or [reference["resolved_path"]]
            for resolved in targets:
                target = module_group.get(resolved)
                if source and target and source != target:
                    key = (source, target, "imports")
                    if key not in edges_seen:
                        edges_seen.add(key)
                        anchored(path, "connection", "imports", reference["start"], reference["end"], "Static import resolves to a retained module in the target group.", source_name=source[0], target_name=target[0], context=source[1], target_context=target[1], attributes={"relationship_kind": "imports", "resolved_path": resolved})
        for call in module["calls"]:
            if not call.get("imported_binding"):
                continue
            target_path = resolve(path, call["reference"], call.get("imported_name", "")) if call.get("reference") else bindings[path].get(call["name"].split(".")[0])
            target = module_group.get(target_path)
            if source and target and source != target:
                key = (source, target, "calls")
                if key not in edges_seen:
                    edges_seen.add(key)
                    anchored(path, "connection", "calls imported symbol", call["start"], call["end"], "Call expression refers to an imported binding whose source module is retained.", source_name=source[0], target_name=target[0], context=source[1], target_context=target[1], attributes={"relationship_kind": "static_call", "symbol": call["name"], "resolved_path": target_path})
        for route in module["routes"]:
            # Restrict route receivers to conventional router declarations; HTTP clients also have .get().
            if route.get("receiver", "").split(".")[-1].lower() not in {"app", "router", "server", "api", "application", "fastify"}:
                continue
            api = (packages.get(package_for(path), {}).get("name", "Application") + " API")[:100]
            anchored(path, "component", api, route["start"], route["end"], "HTTP route boundary declared in source code.", context="repository", component_kind="api")
            if module["format"] == "python" or route.get("receiver") not in {"app", "router", "server"}:
                anchored(path, "endpoint", route["method"] + " " + route["path"], route["start"], route["end"], "Route declaration" + (" handled by " + route["handler"] if route.get("handler") else "."), method=route["method"], path=route["path"], context="repository", source_name=api)
            if source:
                anchored(path, "connection", "implements routes", route["start"], route["end"], "Route handlers are declared in this module group.", source_name=source[0], target_name=api, context=source[1], target_context="repository", attributes={"relationship_kind": "implements"})
        for resource in module.get("resources", []):
            if not source:
                continue
            label = ("Request " + resource["url"].split("?", 1)[0])[:100]
            anchored(path, "component", label, resource["start"], resource["end"], "Request URL written literally in the retained source code.", context=source[1], component_kind="resource")
            anchored(path, "connection", "declares request URL", resource["start"], resource["end"], "Static request expression; execution is not established by this declaration.", source_name=source[0], target_name=label, context=source[1], attributes={"relationship_kind": "request_literal", "operation": resource["operation"]})

    counts = Counter(row["status"] for row in modules)
    return {"facts": facts, "inventory": {"modules": modules, "groups": list(groups.values()), "entrypoints": entrypoints, "packages": [{"name": p["name"], "path": root, "evidence_id": p["item"].id} for root, p in packages.items()], "scanner_version": VERSION,
        "coverage": {"code_files": len(modules), "parsed": counts["parsed"], "partial": counts["partial"], "unparsed": counts["unparsed"], "unavailable": counts["unavailable"], "inventory_only": counts["inventory_only"] + sum(item.source_type == "code" and path_of(item) not in records for item in evidence), "unresolved_internal_imports": unresolved, "bounded_files": sum(row["truncated"] for row in modules), "ungrouped_modules": len(core) - len(module_group)},
        "scope": "JavaScript/TypeScript and Python syntax, SFC script blocks and bounded native-language declarations. Resolved imports describe code organisation; execution paths require runtime evidence."}}
