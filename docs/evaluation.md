# Reproducible evidence evaluation

backend/evaluation/corpus.json contains two development cases and three held-out cases. The synthetic documents cover public API resources, component descriptions, feature gating/limits, contradictory pricing, missing storage information, and an untrusted instruction. They are fictional and small; scores are regression evidence, not a general accuracy benchmark.

The runner processes sources through the actual saved-source pipeline in temporary SQLite storage, outside your application history. Model calls still use your configured transport and the shared Redis serialization lease. Each run gets a temporary owner and cold cache so previous app results do not inflate timing. Evaluation does not create a usable account or send TinyFish requests.

## Run in the VS Code terminal

After the normal Compose app is running:

```bash
sudo docker compose exec -T api python -m app.evaluate --provider rules --split all > rules-evaluation.json
```

That runs no models and spends no provider quota. For an actual local comparison, start/pull models as documented in local-inference.md, then:

```bash
sudo docker compose exec -T api python -m app.evaluate --provider ollama --profile light --split held_out --semantic > local-evaluation.json
```

This explicitly executes the model. It includes the rules-only baseline for the same held-out cases. To tune prompts/model choice, use --split development. Keep held-out cases unchanged while tuning. --split all is useful for regression inspection but must not be called an unseen benchmark after reviewing those cases.

A deliberately enabled hosted run uses --provider gemini. It sends synthetic source passages to the hosted API and consumes its quota. Run it only after verifying your free tier. There is no automatic hosted evaluation or fallback.

## Inspect the output

| Field | Meaning and limit |
| --- | --- |
| precision / recall / f1 | Exact canonical name/type agreement with the closed-set annotated facts. Paraphrases and additional correct facts can lower precision; inspect unexpected/missing facts manually. |
| exact_citation_rate | Accepted excerpts match stored character spans. This checks attribution, not semantic entailment. |
| forbidden_findings | A database assertion induced by source instructions must not be accepted. Review subtle unsupported interpretations separately. |
| rejected_candidates | Candidates rejected by quote/reference checks; the count is not a complete hallucination rate. |
| conflict_retained | Opposing tier availability remains explicit in supporting/contradicting sources. |
| source_recall | Desired source documents appear among retrieved passages. This does not judge passage usefulness or answer quality. |
| insufficient_evidence / unknown_preserved | Unknown questions should remain unestablished, rather than acquire invented private storage claims. |
| cited_answer_statements | Number of generated answer statements with matching quotes; review their meaning. Rules-only produces excerpts and explicitly insufficient semantic answers. |
| run | Provider/model, contract/parser versions, source hashes, request/cache counts, coverage, options, and elapsed time. |

Small models may produce valid but incomplete findings. Review feature limits, exceptions, named relationships, and conflicts rather than optimizing a single aggregate score. Publish actual local output with model/version and machine conditions once you have run it. No local/hosted inference score or peak laptop RAM has been claimed during packaging. Resource caps alone are not measured peak-memory evidence.

The basic packaging check ran only the deterministic evaluation. The rules-only held-out pricing cases intentionally have low recall: they measure what explicit API parsing cannot do, rather than pretend to perform semantic extraction. Rules-only API coverage and exact citation integrity are checked separately.

## Frozen real-source replay

The scaffold does not label its synthetic corpus as real-world evidence. Curate authorized saved public pages into a separate corpus using the same version/provenance/cases contract. Each case contains id, split (development or held_out), sources, expected [kind, canonical-name] pairs, optional forbidden pairs, and questions with zero-based source_indices. Record capture date, origin, raw hash and annotation rationale; independently review expected claims. Keep development and held-out records disjoint and freeze the held-out set before tuning.

Mount/copy the exact corpus into the API container and use --corpus /tmp/your-corpus.json. Compare profiles using --profile light, balanced or advanced. This executes the selected model, includes a rules-only baseline, creates cold temporary evaluation owners, and writes no app history. Larger profiles must be explicitly configured first. Save actual outputs alongside machine/model conditions and peak resource measurements. The repository supplies a schema/example under backend/evaluation/replay-template.json; it contains no fabricated real-source benchmark results.
