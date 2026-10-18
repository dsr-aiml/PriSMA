# Security boundaries

Public DNS domain syntax is validated; IP literals, localhost, local suffixes, credential-bearing URLs, paths, queries, non-HTTP schemes, and custom ports are rejected. Demo processing performs no outbound navigation. **This is not complete SSRF protection for live mode:** DNS, redirect, rebinding, and discovered-link validation must be added before live requests.

Passwords use Argon2; a random cookie token is stored hashed server-side. Cookies are HttpOnly, SameSite=strict, optionally Secure, expire after SESSION_DAYS, and are revoked by logout. Cookie mutations check browser Origin against PUBLIC_ORIGIN and reject cross-site Sec-Fetch-Site. No permissive CORS policy is configured. Backend access is user-filtered for history, details, evidence, questions, and exports. Username changes enforce uniqueness. Password rotation revokes other sessions; session controls retain only the current browser.

Local Compose binds the UI to 127.0.0.1. PostgreSQL, Redis, and API have no host ports. Redis jobs use JSON serialization. Provider credentials are not forwarded to the frontend. Source material renders as text, not injected HTML. Original imported HTML is retained but rendered as escaped text; scripts/styles are removed from normalized passages. Model prompts treat source instructions as untrusted data, and citation/reference validation rejects unmatched output. This does not establish general prompt-injection immunity.

Do not expose this build publicly. Registration/login rate limits, password reset, email verification, quota controls, CSRF hardening review, prompt-injection defenses for LLMs, and crash recovery are future updates. The foundation is not a security guarantee.

Logs contain generated request IDs, status codes, stage transitions, and local exception diagnostics. They intentionally omit passwords, cookies, headers, and request bodies. Avoid logging future provider payloads or secrets. this build has no comprehensive redaction middleware.

Overlay checks validate hashes and paths, preserve .env, reject symlinks and local changes, back up touched files, and never execute archive scripts automatically. Hashes provide integrity relative to the supplied manifest, not cryptographic authenticity: use trusted ZIPs.
