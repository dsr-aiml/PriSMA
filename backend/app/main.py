import hashlib
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal, get_args

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from redis import Redis
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import delivery, jobs
from .auth import COOKIE, DUMMY_HASH, current_user, establish, hasher, token_hash
from .config import settings
from .db import get_db
from .exports import (
    evidence_bundle,
    evidence_dict,
    evidence_matrix_csv,
    markdown_report,
    report_document,
    sqlite_report,
)
from .logging_config import configure_logging
from .models import (
    AuthSession,
    Chunk,
    Event,
    Evidence,
    Investigation,
    ModelCache,
    Question,
    ResearchChat,
    User,
    now,
)
from .research import research_summary
from .schemas import (
    AskQuestion,
    BundleAssessment,
    ClearWorkspace,
    CreateInvestigation,
    Credentials,
    ImportedSource,
    ImportInvestigation,
    PasswordUpdate,
    ProfileUpdate,
    ReanalysisOptions,
    RefreshOptions,
    Registration,
    WebInvestigation,
)
from .source_semantics import visible_report


@asynccontextmanager
async def lifespan(app):
    configure_logging()
    yield


app = FastAPI(title="PriSMA — Architecture intelligence", version="0.8.7", lifespan=lifespan)
log = logging.getLogger("prisma.api")


@app.middleware("http")
async def request_guard(request: Request, call_next):
    request_id = str(uuid.uuid4())
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        # Browsers send Origin on same-origin mutations. Headerless CLI clients cannot be used for CSRF.
        if origin is not None and origin != settings().public_origin:
            return JSONResponse(
                {"detail": "Request origin is not allowed. Check PUBLIC_ORIGIN."}, status_code=403
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    log.info("request_complete", extra={"request_id": request_id, "status_code": response.status_code})
    return response


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    log.exception("unexpected_api_error")
    return JSONResponse({"detail": "Service unavailable. Inspect the API logs and retry."}, status_code=500)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        Redis.from_url(settings().redis_url, socket_timeout=2, socket_connect_timeout=2).ping()
    except Exception:
        raise HTTPException(503, "Database or Redis is unavailable.") from None
    return {"status": "ready"}


@app.get("/providers")
def providers():
    from .model_gateway import provider_catalog

    return {
        "demo": {"available": True, "fixture": "Atlas 3.0 — fictional"},
        "live": {
            "available": settings().tinyfish_enabled and bool(settings().tinyfish_api_key),
            "limits": {
                "searches": settings().tinyfish_search_max_per_run,
                "url_attempts": settings().tinyfish_fetch_max_per_run,
                "direct_reads": settings().public_file_max_per_run,
            },
            "defaults": {"searches": min(settings().tinyfish_searches_per_run, settings().tinyfish_search_max_per_run),
                         "url_attempts": min(settings().tinyfish_fetch_attempts_per_run, settings().tinyfish_fetch_max_per_run), "direct_reads": min(8, settings().public_file_max_per_run)},
            "reason": "Search and Fetch require explicit server configuration.",
        },
        "models": provider_catalog(),
    }


@app.get("/browser-observer")
def browser_observer(user: User = Depends(current_user)):
    import httpx
    try:
        with httpx.Client(timeout=12, trust_env=False) as client:
            response = client.get(settings().browser_observer_url.rstrip("/") + "/ready")
            response.raise_for_status()
            state = response.json()
            return {"available": state.get("status") == "ready", "reason": state.get("reason")}
    except (httpx.HTTPError, ValueError):
        return {"available": False}


@app.post("/auth/register", status_code=201)
def register(body: Registration, response: Response, db: Session = Depends(get_db)):
    user = User(email=body.email, username=body.username, password_hash=hasher.hash(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This email or username is already registered.") from None
    establish(db, user, response)
    return user_dict(user)


@app.post("/auth/login")
def login(body: Credentials, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    valid = hasher.verify(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "Email or password is incorrect.")
    establish(db, user, response)
    return user_dict(user)


@app.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_dict(user)


def user_dict(user):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "created_at": user.created_at.isoformat(),
    }


@app.get("/account")
def account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {
        **user_dict(user),
        "session_count": db.scalar(
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.expires_at > now())
        ),
        "workspace": workspace_counts(db, user.id),
        "activity": workspace_activity(db, user.id),
    }



def workspace_activity(db, user_id):
    """Owner-scoped UTC aggregates; no source bodies or other accounts are read."""
    current = now()
    today = current.date()
    start = today - timedelta(days=27)
    window_start = current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=27)
    owned = (Investigation.user_id == user_id, Investigation.mode != "demo")
    timestamp = func.timezone("UTC", Investigation.created_at) if db.get_bind().dialect.name == "postgresql" else Investigation.created_at
    day = func.date(timestamp)
    rows = db.execute(select(day, func.count()).where(*owned, Investigation.created_at >= window_start)
                      .group_by(day)).all()
    daily = {str(date): count for date, count in rows}
    outcomes = dict(db.execute(select(Investigation.status, func.count()).where(*owned)
                              .group_by(Investigation.status)).all())
    recent = db.execute(select(Investigation.id, Investigation.domain, Investigation.status,
                               Investigation.created_at).where(*owned)
                        .order_by(Investigation.created_at.desc(), Investigation.id.desc()).limit(4)).all()
    return {"timezone": "UTC", "days": [{"date": str(start + timedelta(days=index)),
             "assessments": daily.get(str(start + timedelta(days=index)), 0)} for index in range(28)],
            "outcomes": outcomes,
            "recent": [{"id": row.id, "name": row.domain, "status": row.status,
                        "created_at": row.created_at.isoformat()} for row in recent]}

def lock_account(db, user_id):
    return db.scalar(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    )


def workspace_counts(db, user_id):
    owned_ids = select(Investigation.id).where(Investigation.user_id == user_id, Investigation.mode != "demo")
    return {
        "reports": db.scalar(
            select(func.count())
            .select_from(Investigation)
            .where(Investigation.user_id == user_id, Investigation.mode != "demo")
        ),
        "reference_reports": 0,
        "sources": db.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.investigation_id.in_(owned_ids))
        ),
        "questions": db.scalar(
            select(func.count()).select_from(Question).where(Question.investigation_id.in_(owned_ids))
        ),
        "active": db.scalar(
            select(func.count())
            .select_from(Investigation)
            .where(
                Investigation.user_id == user_id,
                Investigation.mode != "demo",
                Investigation.status.in_(["queued", "exploring", "analyzing"]),
            )
        )
        + db.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.investigation_id.in_(owned_ids), Question.status.in_(["queued", "analyzing"]))
        ),
        "source_reviews": db.scalar(
            select(func.count())
            .select_from(ModelCache)
            .where(ModelCache.user_id == user_id, ModelCache.id.like("intake:%"))
        ),
    }


@app.post("/account/data/clear")
def clear_account_data(
    body: ClearWorkspace, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    locked = lock_account(db, user.id)
    if not locked or not hasher.verify(body.current_password, locked.password_hash):
        raise HTTPException(403, "Current password is incorrect.")
    counts = workspace_counts(db, user.id)
    if counts["active"]:
        raise HTTPException(
            409, "Finish or stop active assessments and questions before clearing workspace data."
        )
    db.execute(delete(Investigation).where(Investigation.user_id == user.id))
    db.execute(delete(ModelCache).where(ModelCache.user_id == user.id))
    db.commit()
    return {"cleared": counts, "workspace": workspace_counts(db, user.id)}


@app.patch("/account")
def update_account(body: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.username = body.username
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This username is already taken.") from None
    return user_dict(user)


@app.post("/account/password")
def update_password(
    body: PasswordUpdate,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not hasher.verify(body.current_password, user.password_hash):
        raise HTTPException(403, "Current password is incorrect.")
    user.password_hash = hasher.hash(body.new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()
    establish(db, user, response)
    return {"ok": True}


@app.post("/account/sessions/revoke")
def revoke_other_sessions(
    request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    current = token_hash(request.cookies.get(COOKIE, ""))
    result = db.execute(
        delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != current)
    )
    db.commit()
    return {"revoked": result.rowcount}


@app.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    session = db.get(AuthSession, token_hash(token)) if token else None
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie(COOKIE, path="/", samesite="strict")
    return {"ok": True}


def investigation_dict(inv):
    return {
        "id": inv.id,
        "domain": inv.domain,
        "mode": inv.mode,
        "depth": inv.depth,
        "status": inv.status,
        "progress": inv.progress,
        "has_report": bool(inv.report),
        "engine": (inv.report or {}).get("run", {}).get("provider") or (inv.processing_options or {}).get("provider") or ("reference" if inv.mode == "demo" else "rules"),
        "model": (inv.report or {}).get("run", {}).get("model") or ((inv.processing_options or {}).get("model_settings") or {}).get("model"),
        "error": inv.error,
        "created_at": inv.created_at.isoformat(),
        "updated_at": inv.updated_at.isoformat(),
    }


def owned(db, investigation_id, user):
    inv = db.scalar(
        select(Investigation).where(Investigation.id == investigation_id, Investigation.user_id == user.id)
    )
    if not inv:
        raise HTTPException(404, "Investigation not found.")
    return inv


@app.get("/models/readiness")
def model_readiness(
    provider: Literal["rules", "ollama", "gemini"] = "ollama",
    semantic: bool = False,
    profile: Literal["light", "balanced", "advanced"] = "light",
    user: User = Depends(current_user),
):
    from .model_gateway import ModelFailure, model_identity

    try:
        from .model_profiles import snapshot, using

        runtime = snapshot(provider, profile)
        with using({"model_settings": runtime}):
            identity = model_identity(provider)
            if semantic and provider != "rules":
                model_identity(provider, embedding=True)
    except ModelFailure as exc:
        return {"ready": False, "provider": provider, "reason": str(exc)}
    return {
        "ready": True,
        "provider": provider,
        "model": identity,
        "settings": runtime,
        "reason": "Configuration is available; extraction quality and performance require a real run.",
    }


@app.get("/research/configuration")
def research_configuration(user: User = Depends(current_user)):
    cfg = settings()
    return {
        "configured": cfg.allow_hosted_queries and bool(cfg.gemini_api_key),
        "model": cfg.gemini_query_model,
        "reason": "Research queries are disabled." if not cfg.allow_hosted_queries else "" if cfg.gemini_api_key else "Set GEMINI_API_KEY in the server .env and recreate the API and worker services.",
    }


@app.post("/investigations/import", status_code=202)
def import_sources(
    body: ImportInvestigation, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    return create_source_assessment(body, user, db)


def create_source_assessment(body, user, db, *, intake=None, staged=None, signature=None, repository_refresh=None):
    from .intelligence import import_evidence, normalize_source
    from .model_gateway import ModelFailure, ensure_enabled

    lock_account(db, user.id)

    try:
        ensure_enabled(body.provider)
        from .model_profiles import snapshot

        model_settings = snapshot(body.provider, body.model_profile)
        normalized = [normalize_source(source) for source in body.sources]
    except (ValueError, ModelFailure) as exc:
        raise HTTPException(422, str(exc)) from None
    if sum(len(content) for content in normalized) > settings().source_bundle_characters:
        raise HTTPException(
            422,
            f"Use up to {settings().source_bundle_characters:,} readable characters per assessment. Import a focused source folder for additional review.",
        )
    if body.semantic_retrieval and body.provider == "rules":
        raise HTTPException(422, "Semantic retrieval requires local or hosted inference.")
    inv = Investigation(
        user_id=user.id,
        domain=body.domain,
        mode="saved",
        depth="standard",
        processing_options={
            "provider": body.provider,
            "semantic_retrieval": body.semantic_retrieval,
            "model_settings": model_settings,
            **({"intake": intake} if intake is not None else {}),
            **({"repository_refresh": repository_refresh} if repository_refresh else {}),
        },
    )
    db.add(inv)
    db.flush()
    if staged is not None:
        staged.result = {
            **staged.result,
            "last_submission": {"signature": signature, "investigation_id": inv.id},
        }
    collected = [intake.get("source_records", {}).get(source.origin, {"collection_method": "user_import"}) for source in body.sources] if intake and intake.get("source_records") else None
    import_evidence(db, inv, body.sources, normalized, collected=collected)
    db.add(
        Event(
            investigation_id=inv.id,
            stage="queued",
            message="Saved-source analysis queued; original documents and normalized passages retained.",
        )
    )
    db.commit()
    try:
        jobs.enqueue(inv.id)
    except Exception as exc:
        log.exception(
            "assessment_queue_submission_failed",
            extra={"investigation_id": inv.id, "exception_type": type(exc).__name__},
        )
        inv.processing_options = {**inv.processing_options, "queue_submission_failed": True}
        inv.error = (
            "Assessment could not be queued. Sources and selection are saved; retry or inspect the API logs."
        )
        jobs.transition(db, inv, "failed", 0, inv.error)
        raise HTTPException(503, {"message": inv.error, "investigation_id": inv.id}) from None
    return investigation_dict(inv)


@app.post("/sources/preview")
async def preview_sources(
    request: Request,
    filename: str = "sources.json",
    bundle_id: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from .source_intake import UPLOAD_BYTES, inspect_upload

    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > UPLOAD_BYTES:
            raise HTTPException(413, "Upload exceeds 50 MB.")
    try:
        files = None
        # Accept the previous client's accidentally combined MIME header too.
        media_types = {part.split(";", 1)[0].strip().lower() for part in request.headers.get("content-type", "").split(",")}
        if "application/vnd.prisma.files+json" in media_types:
            body = json.loads(raw)
            files = body.get("files") if isinstance(body, dict) else None
            if not isinstance(files, list):
                raise ValueError("Provide a files array.")
        reviewed = await run_in_threadpool(inspect_upload, filename, bytes(raw), files=files)
    except (ValueError, TypeError, RecursionError) as exc:
        raise HTTPException(422, str(exc)) from None
    return stage_review(reviewed, user, db, bundle_id)


@app.post("/sources/repository")
def preview_repository(
    body: dict[str, str], user: User = Depends(current_user), db: Session = Depends(get_db)
):
    from .public_files import PublicFileError, read_public, repository_archive
    from .source_intake import UPLOAD_BYTES, inspect_upload

    try:
        url, name = repository_archive(body.get("url", ""))
        raw, _, _ = read_public(url, allowed_hosts={"codeload.github.com"}, max_bytes=UPLOAD_BYTES)
        reviewed = inspect_upload(name, raw)
    except (PublicFileError, ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from None
    reviewed["repository_url"] = body["url"]
    for row in reviewed["sources"]:
        row["acquisition"] = {"collection_method": "public_repository", "repository_url": body["url"], "archive_url": url, "archive_sha256": hashlib.sha256(raw).hexdigest(), "downloaded_at": now().isoformat()}
    return stage_review(reviewed, user, db, body.get("bundle_id"))


def staged_review(db, user, bundle_id):
    staged = db.get(ModelCache, bundle_id)
    if not staged or staged.user_id != user.id or not staged.id.startswith("intake:"):
        raise HTTPException(404, "Source bundle not found.")
    if staged.created_at.replace(tzinfo=now().tzinfo) < now() - timedelta(hours=1):
        raise HTTPException(410, "Source review expired. Import the bundle again.")
    return staged


def review_response(reviewed, bundle_id):
    return {
        **{k: v for k, v in reviewed.items() if k not in ("sources", "last_submission")}, "bundle_id": bundle_id,
        "sources": [{k: v for k, v in row.items() if k != "source"} | {"title": row["source"]["title"], "path": row["source"]["origin"], "format": row["source"]["format"]} for row in reviewed["sources"]],
    }


def stage_review(reviewed, user, db, bundle_id=None):
    lock_account(db, user.id)
    if bundle_id:
        from .source_intake import merge_reviews
        staged = staged_review(db, user, bundle_id)
        staged.result = merge_reviews(staged.result, reviewed)
        staged.created_at = now()
        db.commit()
        return review_response(staged.result, bundle_id)
    db.execute(
        delete(ModelCache).where(
            ModelCache.user_id == user.id,
            ModelCache.id.like("intake:%"),
            ModelCache.created_at < now() - timedelta(hours=1),
        )
    )
    previous = list(
        db.scalars(
            select(ModelCache)
            .where(ModelCache.user_id == user.id, ModelCache.id.like("intake:%"))
            .order_by(ModelCache.created_at.desc())
        )
    )
    for item in previous[2:]:
        db.delete(item)
    bundle_id = "intake:" + str(uuid.uuid4())
    db.add(ModelCache(id=bundle_id, user_id=user.id, result=reviewed))
    db.commit()
    return review_response(reviewed, bundle_id)


@app.delete("/sources/bundles/{bundle_id}/items/{source_id}")
def remove_staged_source(bundle_id: str, source_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_account(db, user.id)
    staged = staged_review(db, user, bundle_id)
    reviewed = dict(staged.result)
    sources = [row for row in reviewed["sources"] if row["id"] != source_id]
    if len(sources) == len(reviewed["sources"]):
        raise HTTPException(404, "Staged source not found.")
    reviewed.update(sources=sources, retained=len(sources), characters=sum(row["characters"] for row in sources), inventory=[{**row, "status": "removed", "reason": "Removed from staged review"} if row.get("source_id") == source_id else row for row in reviewed.get("inventory", [])])
    reviewed.pop("last_submission", None)
    staged.result = reviewed
    db.commit()
    return review_response(reviewed, bundle_id)


@app.post("/investigations/bundle", status_code=202)
def assess_bundle(body: BundleAssessment, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_account(db, user.id)
    staged = staged_review(db, user, body.bundle_id)
    records = {row["id"]: row for row in staged.result["sources"]}
    selected = list(dict.fromkeys(body.selected))
    if any(identifier not in records for identifier in selected):
        raise HTTPException(422, "The selection contains an unavailable source.")
    intake = {
        "retained": staged.result["retained"],
        "discovered": staged.result.get("discovered", staged.result["retained"]),
        "inventory": staged.result.get("inventory", []),
        "admission_policy": staged.result.get("admission_policy"),
        "limits": staged.result.get("limits", {}),
        "selected": len(selected),
        "excluded": staged.result["excluded"],
        "skip_counts": staged.result["skip_counts"],
        "skipped": staged.result["skipped"],
        "repository_url": staged.result.get("repository_url"),
        "source_records": {records[identifier]["source"]["origin"]: records[identifier].get("acquisition", {"collection_method": "user_import"}) for identifier in selected},
    }
    signature = hashlib.sha256(
        json.dumps({**body.model_dump(), "selected": sorted(selected)}, sort_keys=True).encode()
    ).hexdigest()
    previous = staged.result.get("last_submission", {})
    if previous.get("signature") == signature:
        saved = db.get(Investigation, previous.get("investigation_id"))
        if saved and saved.user_id == user.id:
            if saved.status == "failed" and (saved.processing_options or {}).get("queue_submission_failed"):
                saved.status, saved.progress, saved.error = "queued", 0, None
                saved.processing_options = {**saved.processing_options, "queue_submission_failed": False}
                db.add(
                    Event(
                        investigation_id=saved.id,
                        stage="queued",
                        message="Retrying submission of the retained source assessment.",
                    )
                )
                db.commit()
                try:
                    jobs.enqueue(saved.id)
                except Exception as exc:
                    log.exception(
                        "assessment_queue_submission_failed",
                        extra={"investigation_id": saved.id, "exception_type": type(exc).__name__},
                    )
                    saved.processing_options = {**saved.processing_options, "queue_submission_failed": True}
                    saved.error = "Assessment could not be queued. Sources and selection are saved; retry or inspect the API logs."
                    jobs.transition(db, saved, "failed", 0, saved.error)
                    raise HTTPException(503, {"message": saved.error, "investigation_id": saved.id}) from None
            return investigation_dict(saved)
    return create_source_assessment(
        ImportInvestigation(
            domain=body.domain,
            provider=body.provider,
            model_profile=body.model_profile,
            semantic_retrieval=body.semantic_retrieval,
            sources=[records[identifier]["source"] for identifier in selected],
        ),
        user,
        db,
        intake=intake,
        staged=staged,
        signature=signature,
    )


@app.get("/reference")
def reference(depth: Literal["quick", "standard"] = "standard", user: User = Depends(current_user)):
    from .reference import reference_snapshot

    return reference_snapshot(depth)[0]


@app.post("/reference/{depth}/questions")
def reference_question(depth: Literal["quick", "standard"], body: AskQuestion, user: User = Depends(current_user)):
    from uuid import uuid4

    from .reference import reference_answer
    return {"id": "transient-" + str(uuid4()), "question": body.question, "status": "completed", "answer": reference_answer(body.question, depth), "processing_options": {"provider": "rules"}, "error": None, "created_at": now().isoformat()}


@app.get("/reference/{depth}/export/{format}")
def export_reference(depth: Literal["quick", "standard"], format: Literal["sqlite", "json", "markdown", "evidence", "matrix"], user: User = Depends(current_user)):
    from .reference import reference_material, reference_snapshot

    snapshot, evidence = reference_snapshot(depth)
    _, _, chunks = reference_material(depth)
    inv = Investigation(id=snapshot["id"], user_id=user.id, domain="Atlas", depth=depth, mode="demo", status="completed", progress=100, report=snapshot["report"], processing_options={}, created_at=now(), updated_at=now())
    if format == "matrix":
        data, media, extension = evidence_matrix_csv(inv, evidence), "text/csv; charset=utf-8", "csv"
    elif format == "evidence":
        data, media, extension = evidence_bundle(inv, evidence, chunks, []), "application/zip", "zip"
    elif format == "sqlite":
        data, media, extension = sqlite_report(inv, evidence, chunks, []), "application/vnd.sqlite3", "sqlite"
    elif format == "json":
        data, media, extension = json.dumps(report_document(inv, evidence, chunks, [], compact=True), ensure_ascii=False, indent=2), "application/json", "json"
    else:
        data, media, extension = markdown_report(inv, evidence, chunks, []), "text/markdown; charset=utf-8", "md"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="prisma-atlas-{depth}.{extension}"'})


@app.post("/investigations", status_code=200)
def create(body: CreateInvestigation, user: User = Depends(current_user)):
    # Compatibility for older clients. Reference presentation is now stateless.
    if body.mode != "demo":
        raise HTTPException(503, "Use public web collection to assess a live target.")
    from .reference import reference_snapshot

    return reference_snapshot(body.depth)[0]


@app.get("/investigations")
def listing(
    scope: Literal["all", "real", "reference"] = "all",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return [
        investigation_dict(inv)
        for inv in db.scalars(
            select(Investigation)
            .where(Investigation.user_id == user.id)
            .where(
                False
                if scope == "reference"
                else Investigation.mode != "demo"
                if scope == "real"
                else Investigation.mode != "demo"
            )
            .order_by(Investigation.created_at.desc())
            .limit(100)
        )
    ]


@app.get("/investigations/history")
def report_history(
    scope: Literal["all", "real", "reference"] = "all",
    q: str = Query(default="", max_length=253),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=8, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    condition = [Investigation.user_id == user.id, Investigation.mode != "demo"]
    if scope != "all":
        condition.append(
            False if scope == "reference" else Investigation.mode != "demo"
        )
    for term in q.strip().split()[:8]:
        condition.append(Investigation.domain.icontains(term, autoescape=True))
    total = db.scalar(select(func.count()).select_from(Investigation).where(*condition))
    counts = {
        "reports": db.scalar(
            select(func.count())
            .select_from(Investigation)
            .where(Investigation.user_id == user.id, Investigation.mode != "demo")
        ),
        "reference": 0,
    }
    items = list(
        db.scalars(
            select(Investigation)
            .where(*condition)
            .order_by(Investigation.created_at.desc(), Investigation.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return {
        "items": [investigation_dict(inv) for inv in items],
        "total": total,
        "counts": counts,
        "offset": offset,
        "limit": limit,
    }


@app.get("/models/installed")
def installed_models(user: User = Depends(current_user)):
    from .model_gateway import ModelFailure, _request
    from .model_profiles import profiles

    result = {
        "profiles": profiles(),
        "embedding_model": settings().ollama_embedding_model,
        "memory_budget_bytes": settings().inference_memory_budget_bytes,
        "gpu_layers": settings().local_gpu_layers,
        "models": [],
        "running": [],
        "reason": "",
    }
    try:
        tags = _request("GET", settings().ollama_url.rstrip("/") + "/api/tags")
        result["models"] = [
            {"name": m.get("name"), "size": m.get("size"), "details": m.get("details", {})}
            for m in tags.get("models", [])
        ]
        result["running"] = _request("GET", settings().ollama_url.rstrip("/") + "/api/ps").get("models", [])
    except ModelFailure as exc:
        result["reason"] = str(exc)
    result["note"] = (
        "Capacity refers to the configured inference server. Running-model VRAM is observational; this is not a hardware benchmark."
    )
    return result


@app.post("/investigations/web", status_code=202)
def web_investigation(
    body: WebInvestigation, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    from .model_gateway import ModelFailure
    from .model_profiles import snapshot

    lock_account(db, user.id)

    if not settings().tinyfish_enabled or not settings().tinyfish_api_key:
        raise HTTPException(503, "Web collection is disabled. Configure TinyFish Search/Fetch explicitly.")
    if body.semantic_retrieval and body.provider == "rules":
        raise HTTPException(422, "Semantic retrieval requires local or hosted inference.")
    try:
        runtime = snapshot(body.provider, body.model_profile)
    except ModelFailure as exc:
        raise HTTPException(422, str(exc)) from None
    inv = Investigation(
        user_id=user.id,
        domain=body.domain,
        mode="live",
        depth="standard",
        processing_options={
            "provider": body.provider,
            "semantic_retrieval": body.semantic_retrieval,
            "model_settings": runtime,
            "source_url": body.source_url,
            "public_files": body.public_files,
            "browser_observation": body.browser_observation,
            "browser_page_limit": body.browser_page_limit,
            "browser_read_operations": body.browser_read_operations,
            "browser_interaction_limit": body.browser_interaction_limit,
            "linked_external_scripts": body.linked_external_scripts,
            "refresh_origin": body.refresh_origin,
            "fetch_limit": min(body.fetch_limit, settings().tinyfish_fetch_max_per_run),
            "search_limit": min(body.search_limit, settings().tinyfish_search_max_per_run),
            "direct_read_limit": min(body.direct_read_limit, settings().public_file_max_per_run),
        },
    )
    db.add(inv)
    db.flush()
    db.add(
        Event(
            investigation_id=inv.id,
            stage="queued",
            message="Public web collection queued with Search and Fetch limits.",
        )
    )
    db.commit()
    try:
        jobs.enqueue(inv.id)
    except Exception as exc:
        log.exception(
            "collection_queue_submission_failed",
            extra={"investigation_id": inv.id, "exception_type": type(exc).__name__},
        )
        inv.processing_options = {**inv.processing_options, "queue_submission_failed": True}
        inv.error = (
            "Public assessment could not be queued. Its settings are saved; retry or inspect the API logs."
        )
        jobs.transition(db, inv, "failed", 0, inv.error)
        raise HTTPException(503, {"message": inv.error, "investigation_id": inv.id}) from None
    return investigation_dict(inv)


@app.get("/investigations/{investigation_id}")
def detail(investigation_id: str, include_content: bool = True, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = owned(db, investigation_id, user)
    evidence = list(
        db.scalars(
            select(Evidence).where(Evidence.investigation_id == inv.id).order_by(Evidence.collected_at)
        )
    )
    events = db.scalars(select(Event).where(Event.investigation_id == inv.id).order_by(Event.id))
    report = visible_report(inv.report, evidence)
    return {
        **investigation_dict(inv),
        "report": report,
        "analysis": research_summary(report, evidence, inv.processing_options, reference=inv.mode == "demo"),
        "evidence": [evidence_dict(e) if include_content else source_index(e) for e in evidence],
        "actions": source_actions(inv, evidence),
        "processing_options": {
            **(inv.processing_options or {}),
            "cancel_requested": bool(db.get(ModelCache, "cancel:" + inv.id)),
        },
        "passages": [
            {
                "id": c.id,
                "evidence_id": c.evidence_id,
                **({"content": c.content} if include_content else {}),
                "start": c.start,
                "end": c.end,
                "embedding_model": c.embedding_model,
            }
            for c in db.scalars(
                select(Chunk).where(Chunk.investigation_id == inv.id).order_by(Chunk.evidence_id, Chunk.start)
            )
        ],
        "events": [
            {"id": e.id, "stage": e.stage, "message": e.message, "created_at": e.created_at.isoformat()}
            for e in events
        ],
    }


def source_index(e):
    value = evidence_dict(e)
    value.pop("original_content", None)
    value.update(content=e.content[:400], characters=len(e.content), content_loaded=False)
    value["signals"] = {k: v for k, v in (value.get("signals") or {}).items() if k != "alternate_representations"}
    return value


def source_actions(inv, evidence):
    options = inv.processing_options or {}
    origin = (options.get("intake") or {}).get("live_origin")
    repositories = sorted({(e.signals or {}).get("repository_url") for e in evidence if (e.signals or {}).get("repository_url")})
    return {"refresh_available": inv.mode != "demo" and bool(inv.mode == "live" or origin or repositories), "repositories": repositories, "live_url": options.get("source_url") if inv.mode == "live" else (origin or {}).get("source_url")}


@app.get("/investigations/{investigation_id}/sources/{source_id}")
def source_content(investigation_id: str, source_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = owned(db, investigation_id, user)
    source = db.get(Evidence, source_id)
    if not source or source.investigation_id != inv.id:
        raise HTTPException(404, "Source not found.")
    return {**evidence_dict(source), "content_loaded": True, "characters": len(source.content)}


@app.delete("/investigations/{investigation_id}")
def delete_report(investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_account(db, user.id)
    inv = owned(db, investigation_id, user)
    if inv.status not in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "Finish or stop this assessment before deleting its report.")
    if db.scalar(select(Question.id).where(Question.investigation_id == inv.id, Question.status.in_(("queued", "analyzing"))).limit(1)):
        raise HTTPException(409, "Wait for this report's active question to finish before deleting it.")
    db.execute(delete(ModelCache).where(ModelCache.user_id == user.id, ModelCache.id == "cancel:" + inv.id))
    # Foreign-key cascades remove this report's evidence, passages, questions and events.
    # Shared analysis caches and staged import reviews remain available to other reports.
    db.delete(inv)
    db.commit()
    return {"deleted": True, "investigation_id": investigation_id}


@app.post("/investigations/{investigation_id}/cancel", status_code=202)
def cancel_assessment(
    investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    inv = owned(db, investigation_id, user)
    if inv.mode == "demo" or inv.status in ("completed", "failed", "cancelled"):
        raise HTTPException(409, "This assessment cannot be stopped in its current state.")
    db.merge(ModelCache(id="cancel:" + inv.id, user_id=user.id, result={"requested_at": now().isoformat()}))
    db.add(
        Event(
            investigation_id=inv.id,
            stage=inv.status,
            message="Stop requested. An in-flight request may finish before the worker stops.",
        )
    )
    if inv.status == "queued":
        changed = db.execute(
            update(Investigation)
            .where(Investigation.id == inv.id, Investigation.status == "queued")
            .values(status="cancelled", updated_at=now())
        ).rowcount
        if changed:
            db.add(
                Event(
                    investigation_id=inv.id,
                    stage="cancelled",
                    message="Queued assessment stopped before processing.",
                )
            )
    db.commit()
    db.refresh(inv)
    return investigation_dict(inv)


@app.get("/investigations/{investigation_id}/delivery")
def inspect_delivery(investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = owned(db, investigation_id, user)
    state = delivery.delivery_state(inv.id)
    return {**state, "recoverable": state["recoverable"] and inv.status not in {"completed", "failed", "cancelled"}}


@app.post("/investigations/{investigation_id}/recover")
def recover_delivery(investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_account(db, user.id)
    inv = owned(db, investigation_id, user)
    if inv.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "This assessment has already finished processing.")
    state = delivery.delivery_state(inv.id)
    if not state["recoverable"]:
        raise HTTPException(409 if state["available"] else 503, state["reason"])
    inv.error = "Queue deliveries ended before the final report state was saved. Retained evidence and checkpoints are available."
    if inv.report:
        from copy import deepcopy
        report = deepcopy(inv.report)
        run = report.setdefault("run", {})
        run["outcome"] = "interrupted"
        run.setdefault("coverage", {})["status"] = "partial"
        inv.report = report
    jobs.transition(db, inv, "failed", inv.progress, inv.error)
    return investigation_dict(inv)


@app.post("/investigations/{investigation_id}/resume", status_code=202)
def resume_assessment(
    investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    lock_account(db, user.id)
    inv = owned(db, investigation_id, user)
    if inv.mode == "demo" or inv.status not in ("completed", "failed", "cancelled"):
        raise HTTPException(409, "Only a stopped or saved real assessment can be resumed.")
    retained = db.scalar(select(Evidence.id).where(Evidence.investigation_id == inv.id).limit(1))
    if (
        inv.mode == "live"
        and not retained
        and not (inv.processing_options or {}).get("queue_submission_failed")
    ):
        raise HTTPException(
            409,
            "No collected sources were retained. Start a new public assessment with its collection budget.",
        )
    changed = db.execute(
        update(Investigation)
        .where(Investigation.id == inv.id, Investigation.status == inv.status)
        .values(status="queued", progress=0, error=None, updated_at=now())
    ).rowcount
    if not changed:
        raise HTTPException(409, "Assessment state changed. Refresh its record.")
    inv.processing_options = {**(inv.processing_options or {}), "queue_submission_failed": False}
    db.execute(delete(ModelCache).where(ModelCache.id == "cancel:" + inv.id, ModelCache.user_id == user.id))
    db.add(
        Event(
            investigation_id=inv.id,
            stage="queued",
            message="Reassessment queued using retained source snapshots and compatible cached model responses."
            if retained
            else "Retrying public collection submission within its saved request limits.",
        )
    )
    db.commit()
    db.refresh(inv)
    try:
        jobs.enqueue(inv.id)
    except Exception as exc:
        log.exception(
            "assessment_queue_submission_failed",
            extra={"investigation_id": inv.id, "exception_type": type(exc).__name__},
        )
        inv.processing_options = {**inv.processing_options, "queue_submission_failed": True}
        inv.error = "Assessment could not be queued. Its saved records remain available; retry or inspect the API logs."
        jobs.transition(db, inv, "failed", 0, inv.error)
        raise HTTPException(503, {"message": inv.error, "investigation_id": inv.id}) from None
    return investigation_dict(inv)


@app.get("/investigations/{investigation_id}/compare/{previous_id}")
def compare_assessments(
    investigation_id: str, previous_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    from .run_control import compare_reports

    current, previous = owned(db, investigation_id, user), owned(db, previous_id, user)
    if any(
        inv.mode == "demo" or inv.status not in ("completed", "cancelled", "failed") or not inv.report
        for inv in (current, previous)
    ):
        raise HTTPException(409, "Choose two saved real assessments with retained reports.")
    return {
        "before": investigation_dict(previous),
        "after": investigation_dict(current),
        **compare_reports(previous.report, current.report),
    }


def retained_import_source(source):
    """Validate an owned snapshot without leaking source text in an error."""
    from .source_storage import original_text
    signals = source.signals if isinstance(source.signals, dict) else {}
    title = signals.get("title")
    if not isinstance(title, str) or not title.strip():
        title = source.source_url
    category = source.category if source.category in get_args(ImportedSource.model_fields["category"].annotation) else "other"
    try:
        return ImportedSource(title=title[:120], origin=source.source_url, format=source.source_type,
                              category=category, content=original_text(source))
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors(include_input=False) if error["loc"]})
        log.warning("retained_source_validation_failed", extra={"source_id": source.id, "fields": fields})
        raise HTTPException(422, {"message": "A selected saved source has invalid " + ", ".join(fields) + ". Deselect that source or supply a replacement.",
                                  "source_id": source.id, "fields": fields}) from None


@app.post("/investigations/{investigation_id}/reassess", status_code=202)
def reassess_snapshot(investigation_id: str, body: ReanalysisOptions | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .public_code import retained_public_metadata
    original = owned(db, investigation_id, user)
    if original.mode == "demo" or original.status not in ("completed", "failed", "cancelled"):
        raise HTTPException(409, "Choose a saved source assessment that has finished processing.")
    evidence = list(db.scalars(select(Evidence).where(Evidence.investigation_id == original.id)))
    if not evidence:
        raise HTTPException(409, "This assessment has no retained source snapshots.")
    options = original.processing_options or {}
    overrides = body.model_dump(exclude_none=True) if body else {}
    retained_count = len(evidence)
    if overrides.get("selected"):
        selection = set(overrides["selected"])
        if not selection <= {source.id for source in evidence}:
            raise HTTPException(422, "The selection contains a source outside this assessment.")
        evidence = [source for source in evidence if source.id in selection]
    try:
        body = ImportInvestigation(domain=original.domain, provider=overrides.get("provider", options.get("provider", "rules")),
                               semantic_retrieval=overrides.get("semantic_retrieval", options.get("semantic_retrieval", False)),
                               model_profile=overrides.get("model_profile", (options.get("model_settings") or {}).get("profile", "light")),
                               sources=[retained_import_source(e) for e in evidence])
    except ValidationError:
        raise HTTPException(422, "Saved analysis settings are incompatible. Choose an enabled engine and model profile; narrow the source selection if needed.") from None
    intake = {**(options.get("intake") or {}), "reassessment_of": original.id, "retained": retained_count, "selected": len(evidence),
              "source_records": {e.source_url: {**retained_public_metadata(e.signals, e.collection_method), "collection_method": "retained_snapshot", "original_collection_method": (e.signals or {}).get("original_collection_method") or e.collection_method,
                                               "original_collected_at": e.collected_at.isoformat(), "original_assessment_id": original.id,
                                               "repository_url": (e.signals or {}).get("repository_url")} for e in evidence}}
    if original.mode == "live":
        intake["live_origin"] = {k: options.get(k) for k in ("source_url", "public_files", "browser_observation", "browser_page_limit", "browser_read_operations", "browser_interaction_limit", "linked_external_scripts", "fetch_limit", "search_limit", "direct_read_limit")}
    return create_source_assessment(body, user, db, intake=intake)


@app.post("/investigations/{investigation_id}/refresh", status_code=202)
def refresh_origin(investigation_id: str, body: RefreshOptions | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    original = owned(db, investigation_id, user)
    if original.mode == "demo" or original.status not in {"completed", "failed", "cancelled"}:
        raise HTTPException(409, "Choose a real assessment that has finished processing.")
    options = original.processing_options or {}
    live_origin = options if original.mode == "live" else (options.get("intake") or {}).get("live_origin")
    provider, profile = options.get("provider", "rules"), (options.get("model_settings") or {}).get("profile", "light")
    overrides = body.model_dump(exclude_none=True) if body else {}
    if live_origin:
        request = WebInvestigation(domain=original.domain, source_url=live_origin.get("source_url"), provider=provider, model_profile=profile, semantic_retrieval=options.get("semantic_retrieval", False), public_files=live_origin.get("public_files", True), browser_observation=bool(live_origin.get("browser_observation")), browser_page_limit=live_origin.get("browser_page_limit") or 3, linked_external_scripts=bool(live_origin.get("linked_external_scripts")), browser_read_operations=bool(live_origin.get("browser_read_operations")), browser_interaction_limit=live_origin.get("browser_interaction_limit", 3), fetch_limit=overrides.get("fetch_limit", live_origin.get("fetch_limit") or 6), search_limit=overrides.get("search_limit", live_origin.get("search_limit") if live_origin.get("search_limit") is not None else 1), direct_read_limit=overrides.get("direct_read_limit", live_origin.get("direct_read_limit") or 8), refresh_origin=True)
        result = web_investigation(request, user, db)
        inv = db.get(Investigation, result["id"])
        inv.processing_options = {**inv.processing_options, "refresh_of": original.id}
        db.commit()
        return result
    evidence = list(db.scalars(select(Evidence).where(Evidence.investigation_id == original.id)))
    repositories = source_actions(original, evidence)["repositories"]
    if not repositories:
        raise HTTPException(409, "Uploaded files have no refreshable origin. Add replacement files in the source workspace.")
    if len(repositories) > 3:
        raise HTTPException(422, "Refresh up to three repository origins in one assessment.")
    sources = [retained_import_source(source) for source in evidence if not (source.signals or {}).get("repository_url")]
    records = {source.origin: {"collection_method": "retained_snapshot", "original_assessment_id": original.id} for source in sources}
    intake = {"refresh_of": original.id, "retained": len(sources), "selected": len(sources), "source_records": records}
    # An internal refresh can begin with no local documents; the worker supplies the repository sources.
    request = ImportInvestigation.model_construct(domain=original.domain, provider=provider, model_profile=profile, semantic_retrieval=options.get("semantic_retrieval", False), sources=sources)
    return create_source_assessment(request, user, db, intake=intake, repository_refresh={"urls": repositories, "completed": []})


def question_dict(question):
    return {
        "id": question.id,
        "chat_id": question.chat_id,
        "question": question.question,
        "status": question.status,
        "answer": question.answer,
        "processing_options": question.processing_options,
        "error": question.error,
        "created_at": question.created_at.isoformat(),
    }


def reconcile_questions(db, user_id):
    """Only a known ended RQ delivery can resolve a pending database question."""
    from redis import Redis
    from rq.job import Job
    from sqlalchemy import update
    waiting = list(db.scalars(select(Question).join(Investigation).where(Investigation.user_id == user_id, Question.status.in_(["queued", "analyzing"]))))
    if not waiting:
        return
    try:
        connection = Redis.from_url(settings().redis_url, socket_timeout=.5, socket_connect_timeout=.5)
        ended = []
        for question in waiting:
            try:
                status = Job.fetch("research-" + question.id, connection=connection).get_status(refresh=True)
            except Exception:
                continue
            if status in {"failed", "stopped", "canceled", "finished"}:
                ended.append(question.id)
        if ended:
            db.execute(update(Question).where(Question.id.in_(ended), Question.status.in_(["queued", "analyzing"])).values(status="failed", error="Research delivery stopped. Check the research service and retry.", updated_at=now()))
            db.commit()
    except Exception:
        # Redis or absent job records do not establish that a delivery ended.
        return


@app.get("/investigations/{investigation_id}/questions")
def questions(investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = owned(db, investigation_id, user)
    reconcile_questions(db, user.id)
    return [
        question_dict(q)
        for q in db.scalars(
            select(Question)
            .where(Question.investigation_id == inv.id)
            .order_by(Question.created_at.desc())
            .limit(30)
        )
    ]


@app.get("/investigations/{investigation_id}/chats")
def research_chats(investigation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = owned(db, investigation_id, user)
    reconcile_questions(db, user.id)
    states={}
    for key,status in db.execute(select(Question.chat_id,Question.status).where(Question.investigation_id==inv.id)):
        count,working=states.get(key,(0,False));states[key]=(count+1,working or status in {'queued','analyzing'})
    return [{"id": chat.id, "title": chat.title, "message_count":states.get(chat.id,(0,False))[0],"pending":states.get(chat.id,(0,False))[1], "created_at": chat.created_at.isoformat(), "updated_at": chat.updated_at.isoformat()}
        for chat in db.scalars(select(ResearchChat).where(ResearchChat.investigation_id == inv.id).order_by(ResearchChat.updated_at.desc(), ResearchChat.id).limit(200))]


def owned_chat(db, investigation_id, chat_id, user):
    inv = owned(db, investigation_id, user)
    chat = db.get(ResearchChat, chat_id)
    if chat is None or chat.investigation_id != inv.id:
        raise HTTPException(404, "Chat not found.")
    return chat


@app.get("/investigations/{investigation_id}/chats/{chat_id}")
def research_chat(investigation_id: str, chat_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    chat = owned_chat(db, investigation_id, chat_id, user)
    reconcile_questions(db, user.id)
    return [question_dict(q) for q in db.scalars(select(Question).where(Question.chat_id == chat.id).order_by(Question.created_at, Question.id))]


@app.delete("/investigations/{investigation_id}/chats/{chat_id}", status_code=204)
def delete_research_chat(investigation_id: str, chat_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_account(db, user.id)
    chat = owned_chat(db, investigation_id, chat_id, user)
    if db.scalar(select(Question.id).where(Question.chat_id == chat.id, Question.status.in_(["queued", "analyzing"])).limit(1)):
        raise HTTPException(409, "Wait for the current answer before deleting this chat.")
    # Account-scoped answer caches can contain this conversation. Remove them too.
    db.execute(delete(ModelCache).where(ModelCache.user_id == user.id, ModelCache.result["chat_id"].as_string() == chat.id))
    db.delete(chat)
    db.commit()
    return Response(status_code=204)


@app.post("/investigations/{investigation_id}/questions", status_code=202)
def ask(
    investigation_id: str,
    body: AskQuestion,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    lock_account(db, user.id)
    inv = owned(db, investigation_id, user)
    if inv.mode not in ("saved", "live") or inv.status != "completed":
        raise HTTPException(409, "Questions require a completed saved-source analysis.")
    reconcile_questions(db, user.id)
    pending = db.scalar(
        select(Question)
        .join(Investigation, Question.investigation_id == Investigation.id)
        .where(Investigation.user_id == user.id, Question.status.in_(["queued", "analyzing"]))
        .limit(1)
    )
    if pending:
        raise HTTPException(409, "Your previous question is still processing.")
    chat = owned_chat(db, inv.id, body.chat_id, user) if body.chat_id else None
    if chat and db.scalar(select(func.count()).select_from(Question).where(Question.chat_id == chat.id)) >= 100:
        raise HTTPException(409, "Start a new chat to continue.")
    from .model_gateway import ModelFailure
    from .model_profiles import snapshot

    try:
        runtime = snapshot("gemini", purpose="query")
    except ModelFailure as exc:
        raise HTTPException(422, str(exc)) from None
    # Research has one server-managed answer path. Saved index dimensions and
    # the assessment's engine never change, and querying needs no local model.
    options = {"provider": "gemini", "model_settings": runtime, "semantic_retrieval": False, "answer_path": "report-and-source-matching"}
    if chat is None:
        if db.scalar(select(func.count()).select_from(ResearchChat).where(ResearchChat.investigation_id == inv.id)) >= 200:
            raise HTTPException(409, "Delete an unused chat before starting another.")
        chat = ResearchChat(investigation_id=inv.id, title=body.question.strip()[:120])
        db.add(chat)
        db.flush()
    chat.updated_at = now()
    options["chat_id"] = chat.id
    question = Question(investigation_id=inv.id, chat_id=chat.id, question=body.question.strip(), processing_options=options)
    db.add(question)
    db.commit()
    try:
        jobs.enqueue_question(question.id)
    except Exception:
        question.status, question.error = "failed", "Research queue unavailable. Check Redis and the research service."
        db.commit()
        raise HTTPException(503, {"message": question.error, "question_id": question.id, "chat_id": chat.id, "failure_code": "queue_unavailable"}) from None
    return question_dict(question)


@app.get("/investigations/{investigation_id}/export/{format}")
def export(
    investigation_id: str,
    format: Literal["sqlite", "json", "markdown", "evidence", "matrix"],
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    inv = owned(db, investigation_id, user)
    if inv.status not in ("completed", "cancelled", "failed") or not inv.report:
        raise HTTPException(409, "Exports become available when the report is complete.")
    evidence = list(
        db.scalars(select(Evidence).where(Evidence.investigation_id == inv.id).order_by(Evidence.id))
    )
    if format == "matrix":
        return Response(evidence_matrix_csv(inv, evidence), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="prisma-{inv.id}-matrix.csv"'})
    chunks = list(
        db.scalars(
            select(Chunk).where(Chunk.investigation_id == inv.id).order_by(Chunk.evidence_id, Chunk.start)
        )
    )
    questions = list(
        db.scalars(select(Question).where(Question.investigation_id == inv.id).order_by(Question.created_at))
    )
    if format == "matrix":
        data, media, extension = evidence_matrix_csv(inv, evidence), "text/csv; charset=utf-8", "csv"
    elif format == "evidence":
        data, media, extension = evidence_bundle(inv, evidence, chunks, questions), "application/zip", "zip"
    elif format == "sqlite":
        data, media, extension = (
            sqlite_report(inv, evidence, chunks, questions),
            "application/vnd.sqlite3",
            "sqlite",
        )
    elif format == "json":
        data, media, extension = (
            json.dumps(report_document(inv, evidence, chunks, questions, compact=True), ensure_ascii=False, indent=2),
            "application/json",
            "json",
        )
    else:
        data, media, extension = (
            markdown_report(inv, evidence, chunks, questions),
            "text/markdown; charset=utf-8",
            "md",
        )
    return Response(
        data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="prisma-{inv.id}.{extension}"'},
    )
