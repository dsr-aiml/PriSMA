# ADR 0001 · Foundation stack

Status: accepted for the demo foundation. Date: 2026-10-10.

Use Next.js 16 / React 19 / TypeScript; handcrafted token-based CSS; React Flow for the graph. CSS keeps the first delivery small and establishes shared light/dark tokens without another build layer. Motion uses CSS only and respects reduced motion.

Use Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7, and RQ 2. RQ provides a separate background worker with persisted queue state. JSON serialization avoids pickle job payloads. PostgreSQL holds the source of truth for investigation and report state.

Use opaque random cookie sessions with server-stored SHA-256 token hashes and Argon2 password hashes. This keeps logout revocation direct and avoids browser token storage. the reliability update will add abuse prevention and broader authentication hardening.

Use a runtime Next.js API proxy so the browser calls the same origin, cookie behavior is consistent, and frontend image builds do not depend on the internal backend hostname. No provider key is sent to the UI.

the demo foundation inference is deterministic rules, not an LLM. This creates a credential-free vertical slice and stable evidence-linked outputs. the live integration update adds real TinyFish evidence and structured LLM reasoning.

Production Compose/TLS and remote hosting are deliberately deferred to the deployment update. Current Compose publishes localhost only. Runtime dependency versions are locked in requirements files and npm package-lock.json; container base tags are major-version tags rather than immutable image digests.
