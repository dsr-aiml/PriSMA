# Architecture

Next.js proxies same-origin cookie-authenticated requests to FastAPI. PostgreSQL stores users, sessions, investigations, raw/normalized evidence, passages/embeddings, user-scoped caches, events and questions. Redis/RQ schedules a single JSON worker and serializes inference. SQLite is the portable report and temporary evaluation database.

Overview defaults to real source assessment. /reference is a separate fictional Atlas workspace with scoped history and fixed reference subject. Fixture annotations are used only for demo-mode jobs. Saved and web investigations feed their own evidence into the same analysis pipeline; no failure substitutes fixture findings.

Imports retain originals before paragraph-aware splitting. Live jobs first execute bounded TinyFish Search/Fetch, preserve collection outcomes, and admit only scoped source documents. Explicit parsers extract public API declarations and technology headers. Optional model extraction applies exact citations and conservative component/named-item/negation guards; a separate relationship pass receives established component names. Unresolved references are rejected and opposing pricing evidence is retained. Heuristic ratings are not probabilities, and mechanical guards are not a complete entailment verifier.

Local profiles snapshot model name, limits, memory budget, GPU request, context, threads and embedding model into the investigation. Model identities include installed digests; cache keys include the complete runtime snapshot, task, evidence, contract and owner. Larger profiles require explicit enablement and a sufficient configured budget. A server budget is not measured available host memory. Hosted inference is independently enabled; there is no automatic provider switch.

All originals/passages remain saved even when extraction coverage is bounded. Questions use this report's passages and selected model settings. Changed embedding identities require a new index; malformed or uncited answers are rejected. Every report/question/export read enforces account ownership.

Export contract prisma.report version 3 contains source lineage, processing settings, collection outcomes, claims, citations, architecture, logical resources, features and questions. SQLite additionally checks integrity and foreign keys. Stored earlier reports are not rewritten.

See scaffold-status.md for implementation boundaries and remaining production acceptance.

Version 0.8.1 adds shared resource_policy/public_surface/read_operations foundations, product_inventory synthesis over retained sources, and a query-only Redis research_budget ledger. research_summary v2 includes product pages/workflows/features/data flows with provenance; compact JSON v4, SQLite and Markdown carry the same derived view without rewriting stored historical reports or calling a model during export. Chromium readiness verifies launch and evaluation; partial capture delivery is checkpointed. Parser identity structural-13 and model contract source-units-7 invalidate only compatible interpretation caches.
