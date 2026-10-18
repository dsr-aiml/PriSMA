# TinyFish Search/Fetch

The opt-in adapter uses only Search and Fetch. No Agent/Browser endpoint is invoked and no paid-product fallback exists. Official contracts were reviewed on 2026-10-11; no real TinyFish call was executed during packaging.

- Search: GET https://api.search.tinyfish.ai with X-API-Key, query and include_domains. Search snippets discover URLs; they are not promoted to architectural evidence.
- Fetch: POST https://api.fetch.tinyfish.ai with the same server-side key, one URL, Markdown output, links enabled, and a 30-second per-URL timeout. The client allows 150 seconds for the response. JSON documents declaring OpenAPI are parsed as specifications.
- The default run allows one Search query and six new Fetch attempts, including one retry for explicit transient per-URL errors. TINYFISH_SEARCHES_PER_RUN (1–5) and TINYFISH_FETCH_ATTEMPTS_PER_RUN (1–20) configure displayed defaults. Selectable ceilings are TINYFISH_SEARCH_MAX_PER_RUN (0–5), TINYFISH_FETCH_MAX_PER_RUN (1–20) and PUBLIC_FILE_MAX_PER_RUN (1–12); users choose the allowance for each run. Direct reads default to three and have independent counts. The same URL limit bounds distinct visited URLs, including cache hits; new attempts still count retries. HTTP quota/rate failures stop collection. No exponential retry loop or blind paid fallback occurs.
- Returned URLs are validated independently of the provider search filter. Only the requested domain and its subdomains are accepted; credential URLs, local/IP targets and custom ports are rejected. Redirected results outside scope are discarded. A remote Fetch service can already have followed that redirect; this is an evidence-admission boundary, not control over provider egress.
- Original retrieved provider text, normalized text, raw/normalized hashes, requested/final URLs, timing, collection method, and partial/error outcomes are retained. Provider-converted Markdown is not the original site's raw DOM or a captured network trace.

## Enable deliberately

Add to root .env:

```dotenv
TINYFISH_ENABLED=true
TINYFISH_API_KEY=your-private-key
TINYFISH_SEARCH_DAILY_LIMIT=100
TINYFISH_FETCH_DAILY_LIMIT=200
TINYFISH_CACHE_SECONDS=3600
TINYFISH_SEARCHES_PER_RUN=1
TINYFISH_FETCH_ATTEMPTS_PER_RUN=6
```

```bash
sudo docker compose up -d --force-recreate api worker
```

Overview → Public web → enter a public domain → choose the engine → Assess domain. Start with a small documentation site you are authorized to assess. Keys never enter frontend bundles, reports, exports, or logs.

## Allowances and accounting

Application counters are shared across users/workers by a key fingerprint in Redis. Reservations are atomic and count failures. Default caps are 100 searches/day and 200 fetched URLs/day, plus fixed minute/hour caps below advertised rates. UTC windows reset; a provider rolling-window limiter may still reject boundary bursts, which stop explicitly. If accounting is unavailable, no new request is sent. Successful response caches are user-scoped and expire after one hour; cache hits do not spend application request counters. Failed per-URL responses are not cached.

The pricing page advertises free Search (30/minute, 500/hour) and Fetch (150 URLs/minute, 1,000/day), whereas API billing references describe wallet-backed requests after some free allowances. Account and legacy conditions may differ. The application caps cannot account for usage of the same key outside PriSMA, nor guarantee zero spend against a funded wallet or after Redis loss. Verify the actual account policy before live use. A 402 or 429 stops collection; collected documents produce a partial assessment, and no usable documents produce a failed record.

Daily counters survive ordinary Redis restarts with AOF storage but are not a financial ledger. Never clear volumes to reset provider usage. Agent and Browser remain outside this adapter.

## Manual contract checks

Confirm Search returns results with URLs; Fetch returns results/errors arrays with requested/final URL, text and optional links. Test a good page, login wall, 404, scope-changing redirect, duplicate page, long document, and transient timeout. Confirm outcomes, request counts, coverage and actual dashboard usage. Re-run with the same user within TTL to observe cache hits; another account must not reuse private cache entries.

Sources: [Search reference](https://docs.tinyfish.ai/search-api/reference), [Fetch reference](https://docs.tinyfish.ai/fetch-api/reference), [pricing](https://www.tinyfish.ai/pricing).

## Document admission

The collector prioritizes API specifications, architecture, documentation and pricing URLs within its bounded queue. Domain membership alone does not establish that a page describes the assessed product. Before Fetch, it excludes first-level payload mirror/echo/redirect endpoints, URL path segments longer than 128 decoded characters, parameterized endpoint templates, content-bearing query parameters and selected non-document assets. It applies the same checks to final redirect URLs. These conservative guards are domain-independent and can omit legitimate unusual URLs; exclusions are recorded, not silently treated as analyzed evidence. Remaining documents still need relevance and authorship review. This is not a general-purpose crawler or a guarantee of comprehensive site coverage.

Discovery exclusions do not spend Fetch attempts. At most 100 individual discovery exclusion outcomes are saved; the total excluded count is retained separately. A full discovery queue retains better-priority candidates and records truncation. Markdown summarizes discovery exclusion reasons; JSON and SQLite retain recorded URL outcomes. Collection progress and its final status use detached database snapshots so counters and exports agree.

Explicit parsing processes valid OpenAPI/Swagger JSON and `Technology:` annotations in user-imported plain text. It does not treat a `Server:` or `X-Powered-By:` line inside page/document text as an observed response header. Ordinary web prose requires a selected inference engine and accepted supporting excerpts to produce components; an empty graph can be the correct result. Inference is still subject to source review.

Existing reports are historical records. Re-run an assessment after an update to obtain the new admission policy and parser behavior.

## Select before spending

The homepage is fetched first. Likely specification, documentation, architecture and pricing links are admitted; unclassified navigation links are counted and skipped. A Search query is used only after the selected link queue is exhausted. Search allows one unclassified fallback URL across the run, supporting an unusual documentation route without following every generic result. Root aliases and non-document subdomain roots are excluded; documentation/developer subdomain roots remain candidates. Relative links resolve against the actual final source URL. Non-OpenAPI JSON response bodies are recorded as exclusions rather than documentation. This conservative policy can omit useful documents with unusual paths or JSON formats; imported documents remain available for manual assessment.

Rules-only web collection stops after a valid API specification is retained. The record identifies this limited scope and preserves omitted URL counts. Model availability/weight-budget checks run before live collection for the selected local engine; requested embeddings are checked too. These metadata checks do not load the model, benchmark it, establish inference quality or guarantee hosted quota.

Provider-cached response text remains reusable within TTL; selection policy is applied again on every assessment. Timeline counts separate distinct visited URLs from new Fetch attempts. Search query count includes cached queries; new Search attempts count only outgoing requests.

## Reuse collected text

The source library accepts real-source PriSMA report JSON, individual documents, project folders and repository ZIPs. Report imports restore original documents and attribution, reclassify the contents and recommend relevant sources. They do not recollect URLs or copy old findings. Reference exports are rejected. Old collection dates/counters remain part of the old report.

Review uploads before analysis. Limits are 20 MB upload, 4,000 archive entries, 1,000 retained sources and 3 million normalized characters. Individual files cap at 800 KB and document text at 200,000 characters. The archive expansion cap is 40 MB; highly compressed entries, nested archives, unsafe paths, symlinks, generated/dependency folders and recognized credential files are excluded with recorded reasons. No uploaded source code is executed.

Public assessment accepts a full document URL or domain. A supplied path is fetched first; discovery stays within the domain/subdomains and the configured provider allowance. URL acceptance does not mean that the site is accessible or that all repository contents are cloned. Use a repository ZIP or folder for local static source inspection.
