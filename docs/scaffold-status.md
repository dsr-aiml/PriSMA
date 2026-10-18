# Assessment implementation — 0.7.3

This update provides runnable application boundaries and focused regression coverage. It is not a production-readiness certification or a measured model-quality claim.

| Area | Implemented | Acceptance still required |
| --- | --- | --- |
| Reference isolation | Dedicated /reference page, scoped histories, fixed fictional subject, distinct collection/cache paths | Browser navigation, deep-link routing, separate account histories |
| Model selection | Lightweight default, explicitly enabled Balanced/Advanced profiles, installed model catalog, configured capacity, observed running-model VRAM, per-report settings and cache identity | Actual CPU/GPU suitability, peak RAM/VRAM, JSON reliability, latency and multitasking benchmarks |
| Extraction | Paragraph-aware overlapping passages, original text/hashes, normalized offsets, heading/named-item/negation guards, second relationship pass over established components, source-balanced passage selection | Real-model Beacon result and a broader frozen real-source corpus; semantic entailment beyond conservative structural guards |
| Collection | Opt-in TinyFish Search/Fetch, domain/subdomain filtering, post-fetch redirect checks, homepage-first document selection, one Search/six Fetch attempts by default, explicit-parser early stop, shared counters, user-scoped TTL cache, partial/error records | Authorized provider contract tests, account-specific allowance verification, real blocked/redirected/malformed pages |
| Reporting | Report-specific summaries, compact source previews, separate report-download row, formal Markdown, versioned JSON, normalized SQLite with source/collection metadata | Visual review, executive readability, external JSON consumers and SQLite tools |
| Evaluation | Rules/model comparison runner with explicit profile and external corpus selection; cold evaluation cache | Independently curated development/held-out real-source records; actual model/resource measurements |

Intake now supports repository ZIPs/folders, PDF text, DOCX, Markdown/HTML/text, JSON/YAML OpenAPI, manifests, configuration and source code. A compact inventory review preserves paths, formats, classification, selected files and exclusions. Budgets and exact parser scope are in source-intake.md. Generic source languages can be retained for inspection without a language-specific extractor; scanned/encrypted PDFs are not supported.

Direct extractors cover OpenAPI declarations, documented HTTP routes, package/Python dependencies, Compose services/startup dependencies, Python AST imports and route decorators, JavaScript/TypeScript static imports/routes, Docker base images and simple SQL tables/columns. These establish declarations in supplied artifacts, not live deployed behavior. Dynamic route assembly, nested SQL grammar, complete call/data-flow graphs and all language/framework variants remain outside this release.

Model review uses compact three-finding responses and separates pricing batches from topology batches. Source classification excludes response/data examples from semantic extraction and prioritizes relevant documents under the 48-passage default and 20-minute analysis budget. Source-level parse warnings and run-level rejection counts remain inspectable. Partial semantic indexes are identified explicitly and lexical retrieval remains active. The 180-second default timeout does not prove model reliability or latency.

Profile capacity checks use installed weight bytes and a conservative working-memory estimate, not a physical RAM/VRAM probe or an accuracy guarantee. Running-model VRAM is observable through Ollama; an unloaded model provides no proof of GPU readiness. Profiles run on the inference server, which may be different from the browser machine. Heavy profiles remain disabled until explicitly configured; no automatic upgrade, model download or hosted fallback occurs.

Cooperative cancellation, checkpoint reports, cached reassessment and saved-report comparison are implemented. Pending production work includes crash reconciliation, request/rate hardening, deployment/HTTPS, retention controls, backups/restore drills, monitoring, and a wider adversarial source corpus. Fuzzy aliases and a separately evaluated semantic-entailment verifier are not represented as completed work in this scaffold.

The current deeper repository and model contracts are documented in assessment-depth.md. Historical records retain their original parser and contract versions; use Reassess saved sources or import their source export to apply this version.

Research now uses a separately configured Gemini Flash-Lite answer path with bounded saved-source context and no local-model dependency. Contract/citation and mocked transport checks passed; real provider access, answer quality and visual acceptance remain manual. See research-queries.md.
