"""Keep release history, product capability and current technology declarations distinct."""
import re
from copy import deepcopy
from pathlib import PurePosixPath
from urllib.parse import urlsplit


def history_source(source):
    if source.source_type not in {"markdown", "text", "html"}:
        return False
    path = urlsplit(source.source_url).path if "://" in source.source_url else source.source_url.removeprefix("local:")
    name = PurePosixPath(path).name.casefold()
    return bool(re.fullmatch(r"(?:change[-_]?log|changes|history|release[-_]?notes)(?:[._-].*)?", name))


def technology_exclusion(name, group=""):
    value = str(name).strip()
    if re.fullmatch(r"(?:[0-9a-f]{7,64}|[0-9a-f]{8}-[0-9a-f-]{27,})", value, re.I) and group not in {"dependencies", "devDependencies", "peerDependencies", "optionalDependencies"}:
        return "Commit or object identifier is not a technology declaration."
    if group == "documented_capability" and value.casefold() in {"optional", "required", "experimental", "example", "examples", "planned", "default", "internal", "external", "frontend", "backend", "preview", "beta", "alpha"}:
        return "Parenthetical qualification is not a named technology."
    return None


def technology_role(declaration, claim, sources):
    """Repair legacy roles from parser provenance, never a repository/domain name."""
    group=declaration.get('group','source_reference')
    if group not in {'','source_reference'} or claim.get('extraction_method')!='parser':
        return declaration
    evidence=[sources[key] for key in claim.get('supporting_evidence_ids',[]) if key in sources]
    if not evidence:return declaration
    from .source_intake import source_role
    roles={source_role(source.source_url) for source in evidence}
    if roles=={'test'}:group='test_dependencies'
    elif roles <= {'support','third_party'}:group='build_tool'
    else:
        names=[PurePosixPath(urlsplit(e.source_url).path if '://' in e.source_url else e.source_url.removeprefix('local:')).name.casefold() for e in evidence]
        if all(name=='pyproject.toml' or re.fullmatch(r'requirements(?:[-_.](?:dev|test|prod|production))?\.txt',name) for name in names):
            group='test_dependencies' if all('test' in name for name in names) else 'devDependencies' if all('dev' in name for name in names) else 'dependencies'
        elif all(name.startswith('dockerfile') or name.startswith(('compose','docker-compose')) for name in names) and 'image' in claim.get('description','').casefold():
            group='container_images'
        elif all(e.source_type in {'javascript','typescript','python'} for e in evidence) and 'import' in claim.get('description','').casefold():
            group='source_usage'
    return {**declaration,'group':group} if group!=declaration.get('group') else declaration


def visible_report(report, evidence):
    """Read-only correction of unambiguous historic extraction errors; retain audit metadata."""
    if not report:
        return report
    historical = {source.id for source in evidence if history_source(source)}
    claims = {claim["id"]: claim for claim in report.get("claims", [])}
    sources={source.id:source for source in evidence}
    roles_changed=False
    excluded, hidden = [], set()

    def history_claim(identifier):
        ids = claims.get(identifier, {}).get("supporting_evidence_ids", [])
        return bool(ids) and all(key in historical for key in ids)

    technologies = []
    for technology in report.get("technologies", []):
        declarations = technology.get("declarations") or [{"group": technology.get("dependency_group", ""), "claim_id": technology.get("claim_id", "")}]
        retained = [d for d in declarations if not technology_exclusion(technology["name"], d.get("group", "")) and not history_claim(d.get("claim_id", ""))]
        if not retained:
            ids = technology.get("claim_ids", [technology.get("claim_id")])
            hidden.update(ids)
            excluded.append({"kind": "technology", "id": technology["id"], "name": technology["name"], "claim_ids": ids, "reason": "Identifier or historical release record, rather than a current technology declaration."})
            continue
        if len(retained) != len(declarations):
            removed = [d for d in declarations if d not in retained]
            ids = [d.get("claim_id") for d in removed]
            hidden.update(ids)
            excluded.append({"kind":"technology_declaration", "id":technology["id"], "name":technology["name"], "claim_ids":ids, "reason":"Historical or invalid declaration omitted; valid declarations retained."})
            identifiers = list(dict.fromkeys(d.get("claim_id") for d in retained if d.get("claim_id")))
            technology = {**technology, "declarations":retained, "claim_ids":identifiers, "claim_id":identifiers[0], "category":retained[0].get("group",technology.get("category",""))}
        updated=[technology_role(d,claims.get(d.get('claim_id'),{}),sources) for d in retained]
        if updated!=retained:
            roles_changed=True
            technology={**technology,'declarations':updated,'category':updated[0]['group']}
        technologies.append(technology)
    features = []
    for feature in report.get("features", []):
        if history_claim(feature.get("claim_id", "")):
            hidden.add(feature["claim_id"])
            excluded.append({"kind": "capability", "id": feature["id"], "name": feature["feature"], "claim_ids": [feature["claim_id"]], "reason": "Release-history entry; current capability is not established."})
        else:
            features.append(feature)
    if not excluded and not roles_changed:
        return report
    result = deepcopy(report)
    result["technologies"] = deepcopy(technologies)
    result["features"] = deepcopy(features)
    # Retain any claim which another valid inventory record still references.
    used = {identifier for key in ("nodes", "edges", "technologies", "features", "api_endpoints", "entities", "fields", "relationships") for row in result.get(key, []) for identifier in [row.get("claim_id"), *row.get("claim_ids", [])]}
    result["claims"] = [claim for claim in result["claims"] if claim["id"] not in hidden or claim["id"] in used]
    result["presentation_exclusions"] = excluded
    result["presentation_version"] = 2
    return result
