"""Worker-side repository refresh with per-origin checkpoints and bounded intake."""

import hashlib
from copy import deepcopy

from sqlalchemy import select

from .models import Evidence, now
from .public_files import PublicFileError, read_public, repository_archive
from .source_intake import TOTAL_CHARACTERS, UPLOAD_BYTES, inspect_upload


def collect_repositories(db, inv, progress, stop):
    from .intelligence import import_evidence, normalize_source

    plan = deepcopy(inv.processing_options["repository_refresh"])
    completed = plan.setdefault("completed", [])
    for url in plan["urls"]:
        if url in completed:
            continue
        stop()
        archive_url, name = repository_archive(url)
        requests = 0
        def reserve():
            nonlocal requests
            stop()
            requests += 1
        raw, _, _ = read_public(archive_url, allowed_hosts={"codeload.github.com"}, max_bytes=UPLOAD_BYTES, before_request=reserve)
        reviewed = inspect_upload(name, raw)
        rows = [row for row in reviewed["sources"] if row["metadata"]["analysis_priority"] < 9]
        existing = list(db.scalars(select(Evidence).where(Evidence.investigation_id == inv.id)))
        origins = {e.source_url for e in existing}
        rows = [row for row in rows if row["source"]["origin"] not in origins]
        if len(rows) + len(existing) > 2000 or sum(row["characters"] for row in rows) + sum(len(e.content) for e in existing) > TOTAL_CHARACTERS:
            raise PublicFileError("Refreshed sources exceed the combined assessment budget. Import a focused repository folder.")
        snapshot = {"repository_url": url, "archive_url": archive_url, "archive_sha256": hashlib.sha256(raw).hexdigest(), "downloaded_at": now().isoformat(), "direct_requests": requests}
        from .schemas import ImportedSource
        sources = [ImportedSource(**row["source"]) for row in rows]
        import_evidence(db, inv, sources, [normalize_source(source) for source in sources], collected=[{"collection_method": "public_repository", **snapshot} for _ in rows])
        completed.append(url)
        plan.setdefault("snapshots", []).append(snapshot)
        intake = deepcopy(inv.processing_options.get("intake") or {})
        intake["discovered"] = intake.get("discovered", 0) + reviewed["discovered"]
        intake["excluded"] = intake.get("excluded", 0) + reviewed["excluded"]
        intake["retained"] = intake.get("retained", 0) + reviewed["retained"]
        intake["selected"] = len(existing) + len(rows)
        intake["inventory"] = (intake.get("inventory", []) + reviewed.get("inventory", []))[:20000]
        intake["skipped"] = (intake.get("skipped", []) + reviewed["skipped"])[:500]
        from collections import Counter
        intake["skip_counts"] = dict(Counter(intake.get("skip_counts", {})) + Counter(reviewed["skip_counts"]))
        inv.processing_options = {**inv.processing_options, "repository_refresh": deepcopy(plan), "intake": intake}
        progress(15, f"Repository snapshot retained: {len(rows)} selected sources; {len(completed)} of {len(plan['urls'])} origins refreshed.")
