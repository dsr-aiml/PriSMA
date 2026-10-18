# Evidence-grounded architecture intelligence

PriSMA now implements imported-source analysis, optional local Ollama inference, optional explicitly enabled Gemini inference, semantic embeddings, and cited questions. The Atlas reference remains a separate deterministic fixture. Actual model execution/quality and hardware acceptance are manual checks; this delivery does not claim benchmarked model performance.

## Implemented route

1. Import bounded saved documentation, HTML/text, pricing, or JSON OpenAPI specifications. Preserve original text, normalized text, hashes, attribution, provenance, and overlapping source passages.
2. Parse explicit API declarations and named header/technology declarations deterministically. Public resources describe logical entities, never recovered private tables.
3. Optionally run a small local model or explicitly enabled hosted model for semantic component/relationship extraction, technology references, feature tiers, availability, and limits. Require structured candidates with exact quotations.
4. Validate candidates, source ownership, quote spans, and graph/entity references. Reject unmatched quotes and unresolved references. Keep inferred/proposed classifications separate and confidence as an evidence-strength rubric.
5. Optionally save embeddings in the existing PostgreSQL passage records. Rank passages in-process; no mandatory Qdrant service. Answer questions asynchronously from retrieved passages, with citations and insufficient-evidence handling.
6. Retain opposing feature/tier availability statements, run/model provenance, timings, contract versions, cache behavior, and downloadable SQLite/JSON/Markdown reports.
7. Compare actual execution with an explicit-parsing baseline using separated development/held-out cases. Inspect accuracy, quote integrity, retrieval relevance, conflict behavior, and laptop responsiveness manually.

Model computation is serialized, CPU-bounded, and unloaded between requests. The default qwen3:1.7b can be replaced by qwen3:0.6b before sacrificing laptop multitasking. A larger model is not a prerequisite for the application. See local-inference.md and evaluation.md for exact commands and limits.

## Remaining live integration

TinyFish collection remains deliberately disabled to preserve credits. SavedSourceCollector and the disabled TinyFishSearchFetch boundary define the collection entry point; supplying a key does not activate it. Later implementation must connect actual Search/Fetch outputs, budget bounded runs, preserve snapshots for replay, validate target/redirect scope, and show actual information flowing into the same assessment pipeline.

The supplied hackathon's AI/ML route requires meaningful AI and functional TinyFish usage. Source-grounded semantic tasks are the current AI work; a rules-only Atlas demonstration does not establish model inference or sponsor integration. Actual TinyFish execution must be added and demonstrated before submission. Existing-code eligibility remains unresolved in the provided listing; retain truthful ordered patch history and do not fabricate authorship, dates, or commits.

Do not add guessed private stacks, probability-looking percentages, physical database recovery, or anomaly detection without an observed network corpus and evaluation. API naming and DOM shape alone are weak evidence. Broader contradiction resolution, crash reconciliation, cancellation, source pagination, production quotas, and deployment hardening remain future work.
