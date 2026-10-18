"""Bounded declaration scanners for additional languages; never execute source.

These adapters are deliberately labelled partial: they resolve literal declarations,
not type inference, generated code, macro expansion or dynamic execution.
"""
import re
from pathlib import PurePosixPath
from .repository import clean_js, make, path_of

LANGUAGES = {".kt":"Kotlin", ".kts":"Kotlin", ".java":"Java", ".go":"Go", ".rs":"Rust", ".cs":"C#", ".swift":"Swift", ".php":"PHP", ".rb":"Ruby", ".scala":"Scala", ".c":"C", ".h":"C", ".cpp":"C++", ".hpp":"C++"}


def declaration_scan(path, content):
    suffix = PurePosixPath(path).suffix.casefold()
    row = dict(path=path, parser="declarations-1", status="partial", imports=[], symbols=[], schemas=[], calls=[], routes=[], mounts=[], resources=[], diagnostics=[{"message":"Literal declarations only; expressions, generated code and type resolution are not evaluated."}], truncated=False)
    clean = clean_js(content[:500_000])
    # Mask strings as well for declarations; keep offsets in the original Unicode text.
    masked = re.sub(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`[^`]*`', lambda m: ''.join('\n' if c=='\n' else ' ' for c in m[0]), clean)
    package = re.search(r"(?m)^\s*package\s+([\w.]+)", masked)
    row["package_name"] = package[1] if package else ""
    pattern = r"(?m)^\s*import\s+(?:static\s+)?([\w.*]+)(?:\s+as\s+(\w+))?" if suffix in {".kt", ".java", ".scala"} else r"(?m)^\s*(?:using\s+|use\s+)([\w.:]+)"
    for match in re.finditer(pattern, masked):
        row["imports"].append({"name":match[1],"bindings":[{"local":match[2] if match.lastindex and match.lastindex > 1 and match[2] else match[1].split('.')[-1],"imported":""}],"start":match.start(),"end":match.end()})
    if suffix == ".go":
        for block in re.finditer(r'(?m)^\s*import\s+(?:\([\s\S]*?\)|(?:\w+\s+)?"[^"\n]+")', clean):
            for match in re.finditer(r'"([^"\n]+)"', block[0]):
                row["imports"].append({"name":match[1],"bindings":[],"start":block.start()+match.start(),"end":block.start()+match.end()})
    if suffix in {".php", ".rb", ".c", ".cpp", ".h", ".hpp", ".swift"}:
        pattern = {".php":r'(?m)^\s*use\s+([\w\\]+)',".rb":r'(?m)^\s*require\s*[\( ]\s*["\']([^"\']+)',".swift":r'(?m)^\s*import\s+(\w+)'}.get(suffix, r'(?m)^\s*#\s*include\s*["<]([^">]+)')
        for match in re.finditer(pattern, clean):
            row["imports"].append({"name":match[1],"bindings":[],"start":match.start(),"end":match.end()})
    for match in re.finditer(r"\b(class|interface|object|struct|enum|trait|record|fun|func|fn)\s+([A-Za-z_]\w*)", masked):
        row["symbols"].append({"name":match[2],"kind":match[1],"start":match.start(),"end":match.end()})
    if suffix == ".kt":
        for match in re.finditer(r"\bdata\s+class\s+(\w+)\s*\(", masked):
            # Balanced parentheses prevent fields spilling into methods/next class.
            cursor, depth = match.end(), 1
            while cursor < len(masked) and depth:
                depth += (masked[cursor] == '(') - (masked[cursor] == ')')
                cursor += 1
            if depth: continue
            fields=[]
            for field in re.finditer(r"\b(?:val|var)\s+(\w+)\s*:\s*([\w.]+(?:<[^>\n]{1,100}>)?\??)", masked[match.end():cursor-1]):
                start=match.end()+field.start();end=match.end()+field.end()
                default=masked[match.end()+field.end():cursor-1].lstrip().startswith('=')
                fields.append({"name":field[1],"type":field[2].strip().rstrip(',')[:120],"required":not default,"start":start,"end":end})
            row["schemas"].append({"name":match[1],"kind":"kotlin_data_class", "fields":fields[:150],"start":match.start(),"end":cursor})
    for key in ("imports", "symbols", "schemas"):
        if len(row[key]) > 500: row["truncated"] = True
        row[key] = row[key][:500]
    row["truncated"] |= len(content) > len(clean)
    return row


def build_facts(evidence):
    """Literal coordinates, module declarations and applied plugins, not lockfile noise."""
    for item in evidence:
        path=path_of(item); name=PurePosixPath(path).name.casefold(); clean=clean_js(item.content)
        def fact(kind,label,match,detail,**kw):
            return make(item,kind,label, item.content[match.start():match.end()],detail,source_path=path,**kw)
        if name.endswith((".gradle", ".gradle.kts")):
            for m in re.finditer(r'\b(implementation|api|runtimeOnly|compileOnly|testImplementation|androidTestImplementation|ksp|kapt)\s*(?:\(\s*)?["\']([\w.-]+):([\w.-]+)(?::([^"\']+))?["\']', clean):
                yield fact("technology", m[2]+":"+m[3], m, "Dependency declared by the build configuration.", dependency_group="test_dependencies" if 'test' in m[1].lower() else "build_tool" if m[1] in {"ksp","kapt"} else "dependencies",version=m[4] or "")
            for m in re.finditer(r'\bid\s*\(\s*["\']([\w.-]+)["\']\s*\)', clean):
                yield fact("technology",m[1],m,"Applied build plugin.",dependency_group="build_tool")
            for m in re.finditer(r'\b(?:implementation|api)\s*\(\s*project\s*\(\s*["\'](:[^"\']+)["\']',clean):
                source=PurePosixPath(path).parent.name; target=m[1].strip(':').replace(':','/')
                yield fact("component",source,m,"Build module declaring a project dependency.",context="build modules",component_kind="application")
                yield fact("component",target,m,"Project module explicitly referenced by the build.",context="build modules",component_kind="module_group")
                yield fact("connection","depends on project",m,"Literal project dependency in the supplied build.",source_name=source,target_name=target,context="build modules",attributes={"relationship_kind":"build_dependency"})
        if name == "libs.versions.toml":
            import tomllib
            try: data=tomllib.loads(item.content)
            except ValueError: continue
            # Catalog entries become technologies only when referenced by an applied build.
            builds=[e.content for e in evidence if path_of(e).endswith((".gradle", ".gradle.kts")) and not any(p in path_of(e).split('/') for p in ('test','tests'))]
            for alias,row in data.get("libraries",{}).items():
                if not isinstance(row,dict) or not any(re.search(r'\blibs\.'+re.escape(alias.replace('-','.').replace('_','.'))+r'\b', c) for c in builds): continue
                module=row.get("module") or (str(row.get("group",""))+":"+str(row.get("name","")))
                if not re.fullmatch(r'[\w.-]+:[\w.-]+',module):continue
                needle=re.search(re.escape(module),item.content)
                if needle: yield fact("technology",module,needle,"Version-catalog library referenced by a supplied build.",dependency_group="dependencies")
        if name in {"pom.xml", "androidmanifest.xml"} or name.endswith(".csproj"):
            from xml.etree import ElementTree as ET
            if re.search(r'<!DOCTYPE|<!ENTITY',item.content,re.I):continue
            try: root=ET.fromstring(item.content)
            except ET.ParseError:continue
            if name == "pom.xml":
                for row in root.iter():
                    if row.tag.rsplit('}',1)[-1] != 'dependency': continue
                    vals={ch.tag.rsplit('}',1)[-1]:ch.text or '' for ch in row}
                    group,artifact=vals.get('groupId'),vals.get('artifactId')
                    if group and artifact:
                        m=re.search(r'<(?:\w+:)?artifactId>\s*'+re.escape(artifact)+r'\s*</(?:\w+:)?artifactId>',item.content)
                        if m:yield fact("technology",group+":"+artifact,m,"Maven dependency declaration.",dependency_group="test_dependencies" if vals.get('scope')=='test' else "dependencies", version=vals.get('version',''))
            elif name == "androidmanifest.xml":
                application=re.search(r'<application\b[^>]*>',item.content)
                if application:yield fact("component","Android application",application,"Application registered in the supplied manifest.",context="Android application",component_kind="application")
                for m in re.finditer(r'<(activity|service|provider|receiver)\b[^>]*\bandroid:name\s*=\s*"([^"]+)"',item.content):
                    yield fact("component",m[2].split('.')[-1],m,"Android "+m[1]+" registered in the application manifest.",context="Android application",component_kind="service" if m[1]=='service' else "application",attributes={"android_role":m[1],"android_class":m[2]})
                    if application:yield fact("connection","registers "+m[1],m,"Application manifest registers this component.",source_name="Android application",target_name=m[2].split('.')[-1],context="Android application",attributes={"relationship_kind":"registers"})
            else:
                for m in re.finditer(r'<PackageReference\b[^>]*Include="([^"]+)"[^>]*',item.content):
                    yield fact("technology",m[1],m,".NET package reference.",dependency_group="dependencies")
        if name == 'go.mod':
            for m in re.finditer(r'(?m)^\s*(?:require\s+)?([\w.-]+\.[\w.-]+/[^\s]+)\s+(v[^\s]+)',item.content):
                yield fact("technology",m[1],m,"Go module dependency.",dependency_group="dependencies",version=m[2])
        if name == 'cargo.toml':
            import tomllib
            try: data=tomllib.loads(item.content)
            except ValueError:continue
            for section in ('dependencies','dev-dependencies','build-dependencies'):
                for key,value in data.get(section,{}).items():
                    m=re.search(r'(?m)^\s*'+re.escape(key)+r'\s*=.*$',item.content)
                    if m:yield fact("technology",key,m,"Rust crate dependency.",dependency_group="dependencies" if section=='dependencies' else "test_dependencies" if section=='dev-dependencies' else "build_tool",version=value if isinstance(value,str) else str(value.get('version','')))
