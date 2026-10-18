import hashlib
import logging
import time
import uuid
from copy import deepcopy
from urllib.parse import urlsplit

from redis import Redis
from rq import Queue
from rq.serializers import JSONSerializer
from sqlalchemy import select, update
from sqlalchemy.exc import DataError

from .config import settings
from .db import SessionLocal
from .inference import infer
from .models import Event, Evidence, Investigation, Question, now
from .providers import DemoProvider

log = logging.getLogger("prisma.jobs")
TRANSITIONS = {
    "queued": {"exploring", "failed", "cancelled"},
    "exploring": {"analyzing", "failed", "cancelled"},
    "analyzing": {"completed", "failed", "cancelled"},
    "cancelled": set(),
    "completed": set(),
    "failed": set(),
}


def transition(db, inv, status, progress, message):
    if status not in TRANSITIONS[inv.status]:
        raise ValueError(f"Invalid transition: {inv.status} -> {status}")
    inv.status, inv.progress, inv.updated_at = status, progress, now()
    db.add(Event(investigation_id=inv.id, message=message, stage=status))
    db.commit()
    log.info("investigation_transition", extra={"investigation_id": inv.id, "stage": status})


def enqueue(investigation_id: str):
    redis = Redis.from_url(settings().redis_url, socket_connect_timeout=3, socket_timeout=3)
    return Queue("investigations", connection=redis, serializer=JSONSerializer).enqueue(
        "app.jobs.process",
        investigation_id,
        job_id=investigation_id + "-" + str(uuid.uuid4()),
        job_timeout=2400,
        result_ttl=86400,
        failure_ttl=604800,
        on_failure="app.jobs.on_failure",
    )


def on_failure(job, connection, type, value, traceback):
    """RQ failure callback, including timeout. Never expose provider exception text to the client."""
    fail(job.args[0])


def fail(investigation_id):
    with SessionLocal() as db:
        inv = db.get(Investigation, investigation_id)
        if inv and inv.status not in {"completed", "failed", "cancelled"}:
            inv.error = "Processing stopped before the final report was saved. Resume retained work or inspect the worker log."
            transition(db, inv, "failed", inv.progress, inv.error)


def process(investigation_id: str):
    with SessionLocal() as db:
        inv = db.get(Investigation, investigation_id)
        saved = bool(inv and inv.mode in ("saved", "live"))
    if saved:
        return process_saved(investigation_id)
    try:
        with SessionLocal() as db:
            # Compare-and-set prevents two deliveries from processing the same queued investigation.
            changed = db.execute(
                update(Investigation)
                .where(Investigation.id == investigation_id, Investigation.status == "queued")
                .values(status="exploring", progress=10, updated_at=now())
            ).rowcount
            if not changed:
                db.rollback()
                return
            inv = db.get(Investigation, investigation_id)
            db.add(
                Event(
                    investigation_id=inv.id,
                    stage="exploring",
                    message="Loading fictional Atlas fixtures; no website is contacted.",
                )
            )
            db.commit()
            items = DemoProvider().collect(inv.depth)
            for index, item in enumerate(items):
                evidence = Evidence(
                    id=f"{inv.id}:{item.key}",
                    investigation_id=inv.id,
                    source_url=item.source_url,
                    source_type=item.source_type,
                    category=item.category,
                    content=item.content,
                    signals=item.signals,
                    content_hash=hashlib.sha256(item.content.encode()).hexdigest(),
                    collection_method="versioned_fixture",
                    provenance="Atlas 2.0 — fictional demonstration data",
                )
                db.add(evidence)
                db.add(
                    Event(
                        investigation_id=inv.id,
                        stage="exploring",
                        message=f"Stored fixture evidence: {item.category}.",
                    )
                )
                inv.progress = 10 + round((index + 1) / len(items) * 55)
                db.commit()
                time.sleep(max(0, min(settings().demo_step_seconds, 5)))
            transition(
                db,
                inv,
                "analyzing",
                80,
                "Applying deterministic evidence rules and heuristic confidence rubric.",
            )
            evidence = list(db.scalars(select(Evidence).where(Evidence.investigation_id == inv.id)))
            inv.report = infer(evidence)
            time.sleep(max(0, min(settings().demo_step_seconds, 5)))
            transition(db, inv, "completed", 100, "Report model and exports are ready.")
    except Exception:
        log.exception("investigation_failed", extra={"investigation_id": investigation_id})
        fail(investigation_id)
        raise


def process_saved(investigation_id):
    from .collection import CollectionFailure, TinyFishCollector
    from .intelligence import analyze_saved, import_evidence
    from .model_gateway import ModelFailure, model_identity
    from .model_profiles import using
    from .run_control import RunCancelled, check_cancelled

    try:
        with SessionLocal() as db:
            changed = db.execute(
                update(Investigation)
                .where(Investigation.id == investigation_id, Investigation.status == "queued")
                .values(status="exploring", progress=10, updated_at=now())
            ).rowcount
            if not changed:
                db.rollback()
                return
            inv = db.get(Investigation, investigation_id)
            db.add(
                Event(
                    investigation_id=inv.id,
                    stage="exploring",
                    message="Checking the selected engine and preparing public document collection."
                    if inv.mode == "live"
                    else "Reading supplied source snapshots; no target website is contacted.",
                )
            )
            db.commit()
            check_cancelled(inv.id)
            retained = db.scalar(select(Evidence.id).where(Evidence.investigation_id == inv.id).limit(1))
            if (inv.processing_options or {}).get("repository_refresh"):
                from .repository_collection import collect_repositories
                def repository_progress(value, message):
                    inv.progress = value
                    db.add(Event(investigation_id=inv.id, stage="exploring", message=message))
                    db.commit()
                try:
                    collect_repositories(db, inv, repository_progress, lambda: check_cancelled(inv.id))
                except ValueError as exc:
                    raise CollectionFailure("Repository collection stopped: " + str(exc)) from exc
            if inv.mode == "live" and not retained:
                provider = inv.processing_options.get("provider", "rules")
                # Check selected local weights/capacity before any provider allowance
                # is spent. This reads installed-model metadata; it does not infer.
                with using(inv.processing_options):
                    model_identity(provider)
                    if inv.processing_options.get("semantic_retrieval"):
                        model_identity(provider, embedding=True)
                collector = TinyFishCollector(
                    db,
                    inv.user_id,
                    analysis_provider=provider,
                    options=inv.processing_options,
                    stop=lambda: check_cancelled(inv.id),
                )

                def collection_progress(value, message):
                    # JSON columns need detached snapshots: later collector mutations must
                    # not mutate SQLAlchemy's last committed value behind its dirty tracking.
                    inv.processing_options = {
                        **inv.processing_options,
                        "collection": deepcopy(collector.record),
                    }
                    db.add(Event(investigation_id=inv.id, stage="exploring", message=message))
                    db.commit()

                try:
                    seed_url = inv.processing_options.get("source_url")
                    if seed_url and (urlsplit(seed_url).path not in ("", "/") or urlsplit(seed_url).query):
                        records = collector.collect(inv.domain, collection_progress, seed_url=seed_url)
                    else:
                        records = collector.collect(inv.domain, collection_progress)
                    import_evidence(
                        db,
                        inv,
                        [r[0] for r in records],
                        [r[1] for r in records],
                        collected=[r[2] for r in records],
                    )
                except RunCancelled:
                    records = collector.saved_records
                    if records:
                        import_evidence(
                            db,
                            inv,
                            [r[0] for r in records],
                            [r[1] for r in records],
                            collected=[r[2] for r in records],
                        )
                    raise
                finally:
                    snapshot = deepcopy(collector.record)
                    if not db.is_active:
                        # A failed flush expires ORM attributes. Roll back and
                        # reload before saving the detached collection record.
                        db.rollback()
                        inv = db.get(Investigation, investigation_id)
                    inv.processing_options = {
                        **(inv.processing_options or {}),
                        "collection": snapshot,
                    }
                    db.commit()
            transition(
                db,
                inv,
                "analyzing",
                20,
                "Parsing explicit evidence and preparing the selected analysis engine.",
            )

            def progress(value, message):
                inv.progress = value
                inv.updated_at = now()
                db.add(Event(investigation_id=inv.id, stage="analyzing", message=message))
                db.commit()
                check_cancelled(inv.id)

            inv.report = analyze_saved(db, inv, progress)
            check_cancelled(inv.id)
            if inv.report["run"].get("failures") and not inv.report["claims"]:
                inv.error = inv.report["run"]["failures"][0]["message"]
                transition(
                    db,
                    inv,
                    "failed",
                    inv.progress,
                    "Assessment interrupted; the analysis record and sources are retained. " + inv.error,
                )
                return
            partial = inv.report["run"]["coverage"]["status"] == "partial"
            transition(
                db,
                inv,
                "completed",
                100,
                "Partial assessment saved; review coverage and limitations in the analysis record."
                if partial
                else "Source assessment saved; findings and citations are ready to review.",
            )
    except RunCancelled:
        with SessionLocal() as db:
            inv = db.get(Investigation, investigation_id)
            if inv and inv.status not in ("completed", "failed", "cancelled"):
                if inv.report:
                    report = deepcopy(inv.report)
                    report["run"]["coverage"]["status"] = "partial"
                    report["run"]["outcome"] = "cancelled"
                    report["summary"] += " Processing was stopped; retained findings cover completed work."
                    if report["run"].get("semantic_index") == "pending":
                        report["run"]["semantic_index"] = "incomplete"
                    inv.report = report
                transition(
                    db,
                    inv,
                    "cancelled",
                    inv.progress,
                    "Assessment stopped. Retained sources and validated findings remain available; resume uses the saved evidence.",
                )
    except DataError:
        log.error("source_storage_failed", extra={"investigation_id": investigation_id})
        with SessionLocal() as db:
            inv = db.get(Investigation, investigation_id)
            if inv and inv.status not in ("completed", "failed", "cancelled"):
                inv.error = "Evidence storage was interrupted. The collection record and earlier saved sources are retained."
                transition(db, inv, "failed", inv.progress, inv.error)
    except (ModelFailure, CollectionFailure) as exc:
        log.warning(
            "Source assessment stopped (%s); underlying exception: %s",
            getattr(exc, "code", "collection_failure"),
            type(exc.__cause__).__name__ if exc.__cause__ else "none",
            extra={"investigation_id": investigation_id},
        )
        with SessionLocal() as db:
            inv = db.get(Investigation, investigation_id)
            if inv and inv.status not in ("completed", "failed", "cancelled"):
                inv.error = str(exc)
                transition(db, inv, "failed", inv.progress, inv.error)
    except Exception:
        log.exception("saved_analysis_failed", extra={"investigation_id": investigation_id})
        fail(investigation_id)
        raise


def enqueue_question(question_id):
    connection = Redis.from_url(settings().redis_url, socket_connect_timeout=3, socket_timeout=3)
    return Queue("research", connection=connection, serializer=JSONSerializer).enqueue(
        "app.jobs.process_question",
        question_id,
        job_timeout=240,
        job_id="research-" + question_id,
        on_failure="app.jobs.question_failure",
        result_ttl=86400,
    )


def question_failure(job, connection, type, value, traceback):
    with SessionLocal() as db:
        question = db.get(Question, job.args[0])
        if question and question.status not in ("completed", "failed"):
            question.status = "failed"
            question.error = "Question processing stopped. Check the worker and try again."
            db.commit()


def process_question(question_id):
    from .intelligence import answer_question
    from .model_gateway import ModelFailure

    with SessionLocal() as db:
        changed = db.execute(
            update(Question)
            .where(Question.id == question_id, Question.status == "queued")
            .values(status="analyzing", updated_at=now())
        ).rowcount
        db.commit()
        if not changed:
            return
        question = db.get(Question, question_id)
        inv = db.get(Investigation, question.investigation_id)
        try:
            target = inv
            if question.processing_options:
                from types import SimpleNamespace
                history=[]
                if question.chat_id:
                    previous=list(db.scalars(select(Question).where(Question.chat_id==question.chat_id, Question.id!=question.id, Question.status=="completed", Question.created_at<=question.created_at).order_by(Question.created_at.desc(), Question.id.desc()).limit(6)))
                    for turn in reversed(previous):
                        history.append({"question":turn.question,"answer":"\n\n".join(s['text'] for s in (turn.answer or {}).get('statements',[]))[:1600],"citations":[c for s in (turn.answer or {}).get('statements',[]) for c in s.get('citations',[])][:6]})
                target = SimpleNamespace(id=inv.id, user_id=inv.user_id, domain=inv.domain,
                    conversation_history=history, chat_id=question.chat_id,
                    processing_options=question.processing_options,
                    report={**(inv.report or {}), "run": {**(inv.report or {}).get("run", {}), "retrieval": "semantic" if question.processing_options.get("semantic_retrieval") else "lexical"}})
            question.answer = answer_question(db, target, question.question)
            question.status = "completed"
        except ModelFailure as exc:
            from .query_engine import structured_answer
            from .source_semantics import visible_report

            evidence = list(db.scalars(select(Evidence).where(Evidence.investigation_id == inv.id)))
            foundation = structured_answer(visible_report(inv.report, evidence), evidence, question.question)
            question.answer = {**foundation, "answer_version": 2, "insufficient_evidence": True, "statements": [], "passages": [], "provider": (question.processing_options or inv.processing_options or {}).get("provider", "rules"), "retrieval": "lexical", "interpretation_status": "unavailable", "failure_code": exc.code, "http_status": exc.http_status, "transport": exc.transport}
            question.status, question.error = "failed", str(exc)
        except Exception:
            log.exception("question_failed", extra={"question_id": question_id})
            question.status, question.error = (
                "failed",
                "Question processing failed. Inspect the worker logs and retry.",
            )
        question.updated_at = now()
        db.commit()
