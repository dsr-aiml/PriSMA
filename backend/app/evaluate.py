"""Run annotated saved-source cases without writing to the application database."""

import argparse
import json
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .db import Base
from .intelligence import analyze_saved, answer_question, import_evidence, normalize_source, retrieve
from .model_profiles import snapshot, using
from .models import Evidence, Investigation, User, uid
from .schemas import ImportedSource


def facts(report):
    result = set()
    for claim in report["claims"]:
        if claim["type"] in ("component", "entity", "technology", "field", "entity_relationship", "endpoint"):
            result.add((claim["type"], claim["description"].split(": ", 1)[0].casefold()))
    for feature in report.get("features", []):
        result.add(
            ("feature", "|".join((feature["feature"], feature["tier"], feature["availability"])).casefold())
        )
    return result


def run_case(case, provider, semantic, profile="light"):
    with tempfile.TemporaryDirectory(prefix="prisma-evaluation-") as directory:
        engine = create_engine("sqlite:///" + directory + "/evaluation.sqlite")
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as db:
            user = User(
                id=uid(),
                username="evaluation",
                email="evaluation@example.com",
                password_hash="not-an-account",
            )
            db.add(user)
            db.flush()
            inv = Investigation(
                id=uid(),
                user_id=user.id,
                domain="beacon.example",
                mode="saved",
                status="analyzing",
                processing_options={
                    "provider": provider,
                    "semantic_retrieval": semantic,
                    "model_settings": snapshot(provider, profile),
                },
            )
            db.add(inv)
            db.flush()
            sources = [ImportedSource.model_validate(item) for item in case["sources"]]
            import_evidence(db, inv, sources, [normalize_source(source) for source in sources])
            db.commit()
            inv.report = analyze_saved(db, inv, lambda *_: None)
            db.commit()
            actual = facts(inv.report)
            expected = {(kind, name.casefold()) for kind, name in case["expected"]}
            forbidden = {(kind, name.casefold()) for kind, name in case.get("forbidden", [])}
            overlap = actual & expected
            precision = len(overlap) / len(actual) if actual else (1.0 if not expected else 0.0)
            recall = len(overlap) / len(expected) if expected else 1.0
            evidence = {
                item.id: item
                for item in db.scalars(select(Evidence).where(Evidence.investigation_id == inv.id))
            }
            citations = [
                citation for claim in inv.report["claims"] for citation in claim.get("citations", [])
            ]
            exact = sum(
                evidence[c["evidence_id"]].content[c["start"] : c["end"]] == c["quote"] for c in citations
            )
            questions = []
            for query in case.get("questions", []):
                with using(inv.processing_options):
                    ranked, mode = retrieve(db, inv, query["text"])
                desired = {f"{inv.id}:source-{i + 1}" for i in query["source_indices"]}
                matched = {chunk.evidence_id for _, chunk in ranked}
                answer = answer_question(db, inv, query["text"])
                answer_cites = [c for statement in answer["statements"] for c in statement["citations"]]
                questions.append(
                    {
                        "question": query["text"],
                        "retrieval": mode,
                        "source_recall": len(desired & matched) / len(desired),
                        "insufficient_evidence": answer["insufficient_evidence"],
                        "unknown_preserved": answer["insufficient_evidence"]
                        if query.get("insufficient")
                        else None,
                        "exact_answer_citations": all(
                            evidence[c["evidence_id"]].content[c["start"] : c["end"]] == c["quote"]
                            for c in answer_cites
                        ),
                        "cited_answer_statements": len(answer["statements"]),
                    }
                )
            result = {
                "case": case["id"],
                "split": case["split"],
                "provider": provider,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0,
                "expected_facts": len(expected),
                "returned_facts": len(actual),
                "unexpected_facts": sorted(actual - expected),
                "missing_facts": sorted(expected - actual),
                "forbidden_findings": sorted(actual & forbidden),
                "citation_count": len(citations),
                "exact_citation_rate": exact / len(citations) if citations else None,
                "conflict_retained": bool(any(c["contradicting_evidence_ids"] for c in inv.report["claims"]))
                if case.get("expect_conflict")
                else None,
                "questions": questions,
                "run": inv.report["run"],
            }
        engine.dispose()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("rules", "ollama", "gemini"), default="rules")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--profile", choices=("light", "balanced", "advanced"), default="light")
    parser.add_argument(
        "--corpus", type=Path, default=Path(__file__).parent.parent / "evaluation/corpus.json"
    )
    parser.add_argument("--split", choices=("development", "held_out", "all"), default="held_out")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.semantic and args.provider == "rules":
        parser.error("Semantic retrieval requires a model provider.")
    corpus = json.loads(args.corpus.read_text())
    cases = [case for case in corpus["cases"] if args.split == "all" or case["split"] == args.split]
    providers = ["rules"] if args.provider == "rules" else ["rules", args.provider]
    results = [
        run_case(case, provider, args.semantic and provider != "rules", args.profile)
        for provider in providers
        for case in cases
    ]
    document = {
        "corpus_version": corpus["version"],
        "scope": corpus["provenance"],
        "split": args.split,
        "results": results,
        "interpretation": "Closed-set exact-name scoring can penalize valid paraphrases or additional valid facts. Review unexpected facts and answer semantics manually. Exact quotes validate attribution, not entailment. No model score is estimated without executing that provider.",
    }
    output = json.dumps(document, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
