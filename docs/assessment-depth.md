# Architecture assessment — 0.6.0

## Sources and findings

Intake accepts existing report sources, documents, repository ZIPs/folders and public GitHub branch archives. Selection remains explicit. Format, exclusions, original text, normalized spans, hashes and ownership are retained. Nothing executes imported code. Raw/normalized source text is independent of claims; reference fixtures remain confined to /reference.

Explicit parsing now resolves supported static JavaScript/TypeScript relative imports, nested Express router mounts, Mongoose model fields/references, application package boundaries and Compose build contexts. Compose configurations retain separate source contexts, including production filenames; the unqualified default file keeps its filename instead of assuming a development deployment. Connections describe declared build or startup relationships, not observed network traffic. Technology rows group identical names while retaining all declarations, versions, dependency groups and citations. Built-in Node modules stay in the module inventory rather than implying installed third-party technology.

HTML intake preserves actual script entry tags as structural source evidence; escaped documentation examples do not create a client boundary. The Repository tab exposes files, resolved/unresolved imports and linked findings. API routes retain their implementation file, component and whether a mount was resolved. The constellation uses separate configuration lanes. Component details retain implementation paths and alternative declarations. Generic code remains inspectable when no grammar exists; dynamic execution, decorators beyond the supported patterns, computed mounts and complete runtime call graphs are not inferred.

## Local inference

Each extraction batch supplies short exact source units. The model selects their IDs and names the supported finding; PriSMA reconstructs the original excerpt and character offsets. Invalid IDs, negated adoption, unsupported names and unresolved graph/entity references are rejected. Matching a unit proves attribution, not entailment. No automatic retry, download or provider fallback occurs. The lightweight default remains qwen3:1.7b with its existing resource budgets.

Ollama embeddings split each full passage into at most 96-byte UTF-8 segments, submit a single bounded batch and pool each passage's returned vectors using byte weights and L2 normalization. Extraction and answer statements both use selected source-unit IDs. Every embedding character is retained and truncation is disabled. This conservative pooling supports small embedding contexts but is not equivalent to long-context whole-passage encoding; semantic retrieval quality requires measurement. The embedding identity includes pool96 so old and new vectors cannot be mixed. HTTP status and specific context/endpoint/memory errors are retained without raw provider error bodies. An incomplete index uses lexical passage search and remains marked incomplete.

An extraction interruption retains its diagnostic record. With no accepted findings the assessment is failed; earlier accepted findings produce a partial saved report. Empty results distinguish insufficient structural evidence from rejected candidates. Successful transport alone is never treated as a useful architectural finding.

## Public collection

Users can reduce Search/Fetch limits for each run; server maxima still apply. The page's Public files checkbox defaults to eight separate HTTP requests, with an operator ceiling of twelve, for the supplied page and directly linked specifications/scripts within the domain. It does not guess paths, access credentials or interact with login walls. The separate opt-in observer can record initial anonymous DOM and network evidence; see `docs/public-observation.md`. Original direct file text is retained with a public_file collection method. Bounded reads pin a validated public address, retain TLS SNI, check each redirect and reject scope changes. The UI and exports distinguish direct reads from TinyFish attempts. Provider Markdown remains useful readable evidence, not raw DOM.

If a script exceeds the byte/text cap, its outcome is recorded rather than partially parsed as a complete artifact. Large or dynamically split applications can require an imported repository or explicit technical source URL. A web assessment is bounded source collection, not a completeness guarantee.

## Stopping, reassessment and comparison

Stop requests are persisted and checked between stages/requests. An in-flight provider request may complete before stopping. Sources collected so far and completed validated checkpoints are retained. Reassess saved sources reuses source snapshots and account-owned compatible response caches; it reparses with the current implementation. It does not make new TinyFish requests or expand the discovery scope. A run with no collected web sources requires a new budgeted web assessment.

Comparison lists additions, removals and changes in component, connection, API, technology, entity and feature inventories. Source hashes remain attached. Absence can reflect different evidence coverage, so the comparison describes reports rather than asserting real deployment changes. Reassessment updates that run; import a report's source JSON as a new assessment when an immutable before/after pair is desired.

JSON and SQLite retain the full report, configuration contexts, repository inventory and technology declarations. Markdown has contextual architecture rows and a source-module inventory. Historic exports remain valid and are not rewritten.

## Workspace update — 0.6.1

The sidebar consistently exposes separate report/reference libraries, compact recent records and a searchable paged picker across all workspace pages. Intake, public collection limits, model choices and switches share the same neutral control styling. Accounts presents profile, access and data counts with focused editors. Data clearing removes only the current owner's assessments (including reference reports), evidence/passages/events/questions, import reviews and response caches. Password confirmation and idle-work checks precede the transaction; the account, browser sessions, other users, installed models and provider usage ledger remain intact.

Queue submission now uses RQ-compatible unique attempt IDs. Source reviews survive submission failure and unchanged retries reuse the retained investigation. API logs distinguish the underlying submission exception from application health checks; an API/Redis readiness ping is not a job-submission test.
