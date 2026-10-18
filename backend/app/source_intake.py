"""Bounded, authenticated import staging. Archives are inspected without extraction."""

import base64
import hashlib
import io
import json
import re
import stat
import zipfile
from collections import Counter
from pathlib import PurePosixPath
from xml.etree import ElementTree

from pydantic import ValidationError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .config import settings
from .schemas import ImportedSource
from .source_analysis import FORMATS, file_format, inspect_document, prepare_source

UPLOAD_BYTES = 50_000_000
EXPANDED_BYTES = 120_000_000
TOTAL_CHARACTERS = settings().source_bundle_characters
FILE_BYTES = 2_000_000
HAR_BYTES = 15_000_000


def input_file_limit(name):
    return HAR_BYTES if name.casefold().endswith(".har") else FILE_BYTES
MAX_SOURCES = 2000
MAX_ENTRIES = 20000
IGNORED_DIRS = {
    ".git",
    ".overlay-backups",
    "node_modules",
    ".next",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    "vendor",
    "coverage",
    ".idea",
    ".vscode",
}
SECRET_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "credentials.txt",
    "service-account.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
}


def path_reason(name):
    path = PurePosixPath(name)
    if (
        len(name) > 1024
        or "\\" in name
        or path.is_absolute()
        or ".." in path.parts
        or re.match(r"^[A-Za-z]:", name)
        or any(ord(c) < 32 for c in name)
    ):
        return "Unsafe archive path"
    if any(part in IGNORED_DIRS for part in path.parts):
        return "Generated or dependency directory"
    if path.name.casefold() in SECRET_NAMES or path.suffix.lower() in (".pem", ".key", ".p12", ".pfx"):
        return "Credential file"
    if path.suffix.lower() in (".zip", ".tar", ".gz", ".7z", ".rar"):
        return "Nested archive"
    if (
        path.suffix.lower() not in FORMATS
        and path.suffix.lower() not in (".pdf", ".docx")
        and path.name.lower()
        not in (
            "dockerfile",
            "requirements.txt",
            "go.mod",
            "gemfile",
            "makefile",
            "procfile",
            ".env.example",
            ".gitignore",
            ".dockerignore",
            "license",
            "licence",
            "copying",
        )
        and not path.name.lower().startswith("dockerfile.")
    ):
        return "Unsupported file format"
    return None


def source_role(name):
    parts = [part.casefold() for part in PurePosixPath(name.removeprefix("local:")).parts]
    if parts[-1] in {"agents.md", "claude.md", "copilot-instructions.md"}:
        return "support"
    if any(part in {"test", "tests", "__tests__", "fixtures", "benchmarks", "examples", "spec", "specs"} for part in parts[:-1]) or re.search(r"(?:\.test\.|\.spec\.|^test_)", parts[-1]):
        return "test"
    if any(part in {"licenses", "licences", "third_party", "third-party"} for part in parts[:-1]):
        return "third_party"
    if any(part in {".github", ".agents", "scripts", "tools"} for part in parts[:-1]):
        return "support"
    if any(part in {"docs", "documentation", "translations", "i18n", "locales"} for part in parts[:-1]) or PurePosixPath(name).suffix.casefold() in {".md", ".rst", ".txt"}:
        return "documentation"
    return "application"


def admission_priority(name):
    """Order admission before reading content; never depend on ZIP member order."""
    path = PurePosixPath(name)
    base = path.name.casefold()
    role = source_role(name)
    if role in {"test", "third_party"}:
        score = 9 if role == "test" else 10
    elif base in {"package.json", "pyproject.toml", "requirements.txt", "cargo.toml", "go.mod", "gemfile", "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "libs.versions.toml", "androidmanifest.xml", "composer.json"} or base.endswith(".csproj"):
        score = 0
    elif base.startswith(("tsconfig", "dockerfile", "compose")) or base in {"server.json", "vercel.json", "amplify.yml", "pnpm-workspace.yaml"}:
        score = 1
    elif path.suffix.casefold() in {".mermaid", ".mmd"} or "architecture" in base or base in {"readme.md", "readme.rst"}:
        score = 2
    elif base.startswith(("index.", "main.", "app.", "server.", "cli.")) or base in {"__main__.py", "__init__.py"}:
        score = 3
    elif role == "application" and file_format(name) in {"python", "javascript", "typescript", "sql", "code"}:
        score = 4
    elif role == "test":
        score = 9
    elif role == "third_party" or re.search(r"readme[._-][a-z]{2}(?:[._-]|\.)", base):
        score = 10
    elif role == "support":
        score = 8
    else:
        score = 6
    return score, len(path.parts), name.casefold(), name


def document_text(name, raw):
    extension = PurePosixPath(name).suffix.casefold()
    if extension == ".har":
        from .traffic_intake import sanitize_har
        return json.dumps(sanitize_har(json.loads(raw)), ensure_ascii=False, indent=2), "json"
    if extension == ".pdf":
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF")
        if len(reader.pages) > 200:
            raise ValueError("PDF page budget exceeded")
        parts, count = [], 0
        for page in reader.pages:
            text = page.extract_text() or ""
            count += len(text)
            if count > 200000:
                raise ValueError("Document text budget exceeded")
            parts.append(text)
        if not any(part.strip() for part in parts):
            raise ValueError("PDF has no extractable text; scanned PDFs require OCR")
        return "\n\n".join(parts), "text"
    if extension == ".docx":
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 2_000_000 or info.file_size > max(1000, info.compress_size * 100):
                raise ValueError("Word document expansion budget exceeded")
            xml = archive.read(info)
        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
            raise ValueError("Unsupported XML declarations")
        root = ElementTree.fromstring(xml)
        text = "\n".join("".join(node.itertext()) for node in root.iter() if node.tag.endswith("}p"))
        if not text.strip():
            raise ValueError("DOCX has no readable paragraph text")
        return text, "text"
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return raw.decode("utf-32"), file_format(name)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), file_format(name)
    sample = raw[:4096]
    if b"\x00" in sample:
        # Some editors write UTF-16 without a BOM. Require a strong alternating
        # NUL pattern instead of treating arbitrary binary data as source text.
        even, odd = sample[::2], sample[1::2]
        for charset, zeros, other in (("utf-16-le", odd, even), ("utf-16-be", even, odd)):
            if len(raw) % 2 == 0 and zeros and zeros.count(0) / len(zeros) >= .65 and other.count(0) / max(1, len(other)) < .05:
                text = raw.decode(charset)
                if not any(ord(c) < 32 and c not in "\t\n\r" for c in text):
                    return text, file_format(name)
        raise ValueError("Binary content; not a text source")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Windows text exports commonly contain typographic quotes in CP1252.
        text = raw.decode("cp1252")
    if any(ord(c) < 32 and c not in "\t\n\r\f" for c in text):
        raise ValueError("Binary control characters; not a text source")
    return text, file_format(name)


def document_failure(error):
    """Explain the failure without exposing source content or parser tracebacks."""
    if isinstance(error, ValidationError):
        fields = sorted({str(row["loc"][0]) for row in error.errors(include_input=False, include_context=False) if row.get("loc")})
        return "Invalid source " + ", ".join(fields)
    if isinstance(error, UnicodeError):
        return "Invalid text encoding; save as UTF-8"
    if isinstance(error, (zipfile.BadZipFile, PyPdfError, ElementTree.ParseError, KeyError)):
        return "Document structure is invalid or incomplete"
    known = {
        "Each source must contain readable content.": "Empty document",
        "Binary content; not a text source": "Binary content",
        "Binary control characters; not a text source": "Binary content",
        "Encrypted PDF": "Encrypted PDF",
        "PDF page budget exceeded": "PDF exceeds 200 pages",
        "Document text budget exceeded": "Document exceeds its text budget",
        "PDF has no extractable text; scanned PDFs require OCR": "Scanned PDF; OCR required",
        "DOCX has no readable paragraph text": "DOCX contains no paragraph text",
        "Word document expansion budget exceeded": "DOCX exceeds its expansion budget",
        "Unsupported XML declarations": "Unsupported XML declarations",
    }
    return known.get(str(error), "Document parsing failed")


def inspect_upload(name, raw, *, files=None):
    from .intelligence import normalize_source

    if len(raw) > UPLOAD_BYTES:
        raise ValueError("Upload exceeds 50 MB. Import a focused repository folder or a smaller archive.")
    sources, records, counts, hashes = [], [], Counter(), set()
    inventory = {}
    total, expanded = 0, 0
    subject = PurePosixPath(name).stem or "Imported project"
    entrypoints = set()

    def manifest_entries(path, content):
        try:
            data = json.loads(content)
        except (ValueError, TypeError, UnicodeError):
            return
        if not isinstance(data, dict):
            return
        values = [data.get("main"), data.get("source")]
        bin_value = data.get("bin")
        values += list(bin_value.values()) if isinstance(bin_value, dict) else [bin_value]
        for value in values:
            if isinstance(value, str):
                candidate = str(PurePosixPath(path).parent / value)
                if not path_reason(candidate):
                    entrypoints.add(candidate)

    def priority(path):
        original = admission_priority(path)
        return (1, *original[1:]) if path in entrypoints else original

    def outcome(path, reason):
        counts[reason] += 1
        if path in inventory:
            inventory[path].update(status="deferred" if "budget" in reason.lower() or "exceeds" in reason.lower() else "excluded", reason=reason)
        if len(records) < 500:
            records.append({"path": path[:1024], "reason": reason})

    def add(source, path, acquisition=None):
        nonlocal total
        try:
            source, _ = prepare_source(source)
            content = normalize_source(source)
            info = inspect_document(source, content)
        except (ValueError, TypeError, RecursionError) as exc:
            outcome(path, document_failure(exc))
            return
        digest = hashlib.sha256(content.encode()).hexdigest()
        if digest in hashes:
            outcome(path, "Duplicate content")
            return
        if len(sources) >= MAX_SOURCES or total + len(content) > TOTAL_CHARACTERS:
            outcome(path, "Analysis bundle budget exceeded")
            return
        hashes.add(digest)
        total += len(content)
        identifier = f"s{len(sources) + 1}"
        metadata = {k: v for k, v in info.items() if k != "parser_data"}
        if path in entrypoints:
            metadata.update(analysis_priority=1, source_role="entrypoint")
        sources.append(
            {
                "id": identifier,
                "source": source.model_dump(),
                "metadata": metadata,
                "characters": len(content),
                "content_hash": digest,
                "preview": content[:1200],
                **({"acquisition": acquisition} if acquisition else {}),
            }
        )
        if path in inventory:
            inventory[path].update(status="retained", source_id=identifier, characters=len(content))

    def restore_report(document, path, reader=None):
        nonlocal subject
        if document.get("schema_version") not in (3, 4) or document.get("mode") not in ("saved", "live"):
            outcome(path, "Unsupported report contract")
            return
        evidence = document.get("evidence")
        if not isinstance(evidence, list) or len(evidence) > MAX_SOURCES:
            raise ValueError("Invalid report source list")
        subject = str(document.get("requested_domain") or subject)[:253]
        inventory.pop(path, None)
        texts = document.get("source_texts") or {}
        if not isinstance(texts, dict):
            raise ValueError("Invalid source text table")
        for entry in sorted(evidence, key=lambda row: admission_priority(str(row.get("source_url", ""))) if isinstance(row, dict) else (99, 0, "", "")):
            try:
                if not isinstance(entry, dict):
                    raise ValueError("Invalid source")
                content = entry.get("original_content") or entry.get("content")
                if content is None and document.get("content_storage") == "bundle_files":
                    if reader is None:
                        raise ValueError("Import the evidence ZIP to restore original documents")
                    content = reader(entry.get("original_ref") or entry["content_ref"]).decode("utf-8")
                if content is None:
                    content = texts.get(entry.get("content_ref"))
                if not isinstance(content, str) or len(content.encode()) > FILE_BYTES:
                    raise ValueError("Source text is missing or exceeds its file budget")
                origin = str(entry.get("source_url", ""))
                inventory[origin] = {"path": origin, "role": source_role(origin), "priority": admission_priority(origin)[0], "status": "pending"}
                source = ImportedSource(title=str((entry.get("signals") or {}).get("title") or entry.get("source_url"))[:120], origin=entry["source_url"], format=entry.get("source_type", "text"), category=entry.get("category", "documentation"), content=content)
                from .public_code import retained_public_metadata
                acquisition = {"collection_method": "user_import", **retained_public_metadata(entry.get("signals"), entry.get("collection_method"))}
                add(source, source.origin, acquisition)
            except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
                outcome(path, "Invalid report source")

    def consume(path, blob):
        reason = path_reason(path)
        if reason:
            outcome(path, reason)
            return
        try:
            if path.casefold().endswith(".json"):
                try:
                    document = json.loads(blob)
                except (ValueError, RecursionError):
                    document = None
                if isinstance(document, dict) and document.get("contract") == "prisma.report":
                    restore_report(document, path)
                    return
            if len(blob) > input_file_limit(path):
                outcome(path, f"Individual file exceeds {input_file_limit(path) // 1_000_000} MB")
                return
            content, format = document_text(path, blob)
            if "-----BEGIN " in content and "PRIVATE KEY-----" in content:
                outcome(path, "Private key material")
                return
            source = ImportedSource(title=PurePosixPath(path).name[:120], origin="local:" + path, format=format, content=content)
            add(source, path)
        except (ValueError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile, ElementTree.ParseError, RecursionError, PyPdfError) as exc:
            outcome(path, document_failure(exc))

    if files is not None:
        if len(files) > MAX_ENTRIES:
            raise ValueError("Use up to 20,000 files per folder review.")
        if any(not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"].strip() for entry in files):
            raise ValueError("Invalid folder file record.")
        for entry in files:
            if PurePosixPath(entry["path"]).name == "package.json" and isinstance(entry.get("content"), str) and len(entry["content"]) < 64000:
                manifest_entries(entry["path"], entry["content"])
        for entry in sorted(files, key=lambda row: priority(row["path"])):
            inventory[entry["path"]] = {"path": entry["path"], "role": source_role(entry["path"]), "priority": admission_priority(entry["path"])[0], "status": "pending"}
            if isinstance(entry.get("size"), int) and entry["size"] > input_file_limit(entry["path"]) and not path_reason(entry["path"]):
                inventory[entry["path"]]["bytes"] = entry["size"]
                outcome(entry["path"], f"Individual file exceeds {input_file_limit(entry['path']) // 1_000_000} MB")
                continue
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError("Invalid folder file record.")
            if isinstance(entry.get("content"), str):
                try:
                    consume(entry["path"], entry["content"].encode())
                except UnicodeError:
                    outcome(entry["path"], "Invalid text encoding")
            elif isinstance(entry.get("data"), str):
                if len(entry["data"]) > input_file_limit(entry["path"]) * 2:
                    outcome(entry["path"], f"Individual file exceeds {input_file_limit(entry['path']) // 1_000_000} MB")
                    continue
                try:
                    blob = base64.b64decode(entry["data"], validate=True)
                except ValueError:
                    outcome(entry["path"], "Invalid file encoding")
                    continue
                consume(entry["path"], blob)
            else:
                raise ValueError("Invalid folder file encoding.")
    elif name.casefold().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ENTRIES:
                    raise ValueError("Archive contains more than 20,000 entries.")
                for entry in entries:
                    if PurePosixPath(entry.filename).name == "package.json" and not path_reason(entry.filename) and entry.file_size < 64000 and not stat.S_ISLNK(entry.external_attr >> 16) and not entry.flag_bits & 1:
                        try:
                            manifest_entries(entry.filename, archive.read(entry))
                        except (OSError, RuntimeError, zipfile.BadZipFile):
                            pass
                evidence_manifest = next((entry for entry in entries if entry.filename == "prisma-evidence.json"), None)
                if evidence_manifest:
                    def read_bundle_member(path):
                        nonlocal expanded
                        if not isinstance(path, str) or path_reason(path):
                            raise ValueError("Unsafe evidence member")
                        entry = archive.getinfo(path)
                        if entry.file_size > FILE_BYTES or entry.file_size > max(1000, entry.compress_size * 100) or expanded + entry.file_size > EXPANDED_BYTES or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                            raise ValueError("Evidence member budget exceeded")
                        expanded += entry.file_size
                        return archive.read(entry)
                    if evidence_manifest.file_size > UPLOAD_BYTES or evidence_manifest.file_size > max(1000, evidence_manifest.compress_size * 100):
                        raise ValueError("Evidence manifest budget exceeded")
                    document = json.loads(archive.read(evidence_manifest))
                    if not isinstance(document, dict) or document.get("contract") != "prisma.report" or document.get("content_storage") != "bundle_files":
                        raise ValueError("Invalid evidence bundle manifest")
                    restore_report(document, evidence_manifest.filename, read_bundle_member)
                    entries = []
                for entry in sorted(entries, key=lambda row: priority(row.filename)):
                    if entry.is_dir():
                        continue
                    inventory[entry.filename] = {"path": entry.filename, "bytes": entry.file_size, "role": source_role(entry.filename), "priority": admission_priority(entry.filename)[0], "status": "pending"}
                    reason = path_reason(entry.filename)
                    mode = entry.external_attr >> 16
                    if reason or stat.S_ISLNK(mode) or entry.flag_bits & 1:
                        outcome(entry.filename, reason or "Symlink or encrypted archive member")
                        continue
                    if (
                        entry.file_size > (UPLOAD_BYTES if entry.filename.casefold().endswith(".json") else input_file_limit(entry.filename))
                        or entry.file_size > max(1000, entry.compress_size * 100)
                        or expanded + entry.file_size > EXPANDED_BYTES
                    ):
                        outcome(entry.filename, "Archive expansion budget exceeded")
                        continue
                    expanded += entry.file_size
                    try:
                        with archive.open(entry) as stream:
                            blob = stream.read((UPLOAD_BYTES if entry.filename.casefold().endswith(".json") else input_file_limit(entry.filename)) + 1)
                    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError):
                        outcome(entry.filename, "Unreadable archive member")
                        continue
                    consume(entry.filename, blob)
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            raise ValueError("The ZIP archive could not be read.") from exc
    else:
        inventory[name] = {"path": name, "bytes": len(raw), "role": source_role(name), "priority": admission_priority(name)[0], "status": "pending"}
        consume(name, raw)
    if not sources:
        failures = "; ".join(row["path"][:140] + ": " + row["reason"] for row in records[:4])
        raise ValueError("No readable sources were found. " + (failures or "The upload is empty."))
    return {
        "subject": subject,
        "sources": sources,
        "skipped": records,
        "skip_counts": dict(counts),
        "characters": total,
        "retained": len(sources),
        "excluded": sum(counts.values()),
        "inventory": list(inventory.values()),
        "discovered": len(inventory) or len(sources),
        "admission_policy": "priority-before-content-1",
        "limits": {
            "upload_bytes": UPLOAD_BYTES,
            "expanded_bytes": EXPANDED_BYTES,
            "sources": MAX_SOURCES,
            "characters": TOTAL_CHARACTERS,
            "file_bytes": FILE_BYTES,
            "har_bytes": HAR_BYTES,
            "entries": MAX_ENTRIES,
        },
    }


def merge_reviews(current, incoming):
    """Append staged documents without confusing paths, replacing files or exceeding a bundle budget."""
    from copy import deepcopy

    result = deepcopy(current)
    sources = result["sources"]
    paths = {row["source"]["origin"]: row for row in sources}
    hashes = {row.get("content_hash") or hashlib.sha256(row["source"]["content"].encode()).hexdigest() for row in sources}
    id_map = {}
    counts = Counter(result.get("skip_counts", {})) + Counter(incoming.get("skip_counts", {}))
    skipped = result.get("skipped", []) + incoming.get("skipped", [])
    characters = sum(row["characters"] for row in sources)
    index = max((int(row["id"][1:]) for row in sources if row["id"].startswith("s") and row["id"][1:].isdigit()), default=0)
    for row in incoming["sources"]:
        origin = row["source"]["origin"]
        digest = row.get("content_hash") or hashlib.sha256(row["source"]["content"].encode()).hexdigest()
        reason = "Duplicate content" if digest in hashes else "Path already reviewed with different content" if origin in paths else "Analysis bundle budget exceeded" if len(sources) >= MAX_SOURCES or characters + row["characters"] > TOTAL_CHARACTERS else None
        if reason:
            counts[reason] += 1
            skipped.append({"path": origin, "reason": reason})
            continue
        index += 1
        id_map[row["id"]] = f"s{index}"
        sources.append({**row, "id": f"s{index}"})
        paths[origin], characters = row, characters + row["characters"]
        hashes.add(digest)
    result.update(sources=sources, characters=characters, retained=len(sources), excluded=sum(counts.values()),
                  skip_counts=dict(counts), skipped=skipped[:500])
    result["inventory"] = result.get("inventory", []) + [{**row, **({"source_id": id_map[row["source_id"]]} if row.get("source_id") in id_map else {})} for row in incoming.get("inventory", [])]
    result["discovered"] = result.get("discovered", len(current["sources"])) + incoming.get("discovered", len(incoming["sources"]))
    result.pop("last_submission", None)
    result.pop("repository_url", None)  # Individual rows retain acquisition provenance in mixed reviews.
    return result
