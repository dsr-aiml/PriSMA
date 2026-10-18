# Public application inspection

A URL assessment combines independently retained layers: authored documents from TinyFish Fetch/Search; DNS-pinned reads of the actual page and linked technical resources; and selected anonymous Chromium page loads. All extraction engines receive the same collected evidence. Collection is bounded, rather than claiming complete access to a private system.

## Browser service

```bash
sudo docker compose --profile browser up --build -d browser
```

New URL assessments enable Browser inspection when its readiness endpoint proves Chromium can launch and evaluate a page. The visible scope includes linked external scripts by default; turn that scope off when external assets should be excluded. Browser pages defaults to three, configurable from one to five. One capture permits 72 anonymous HTTP reads, 20 MB of transport bodies and 70 seconds. Four reads can run concurrently. Navigation uses only published links scored for technical relevance; it does not guess paths or submit forms. Navigation is bounded by selected pages, reads, transfer bytes and elapsed time; per-page gains remain inspectable rather than being used as a claim of coverage.

Chromium runs as a non-root user with its sandbox, a restrictive seccomp profile and a dead proxy. Every allowed HTTP request is reissued by the DNS-pinned reader, including redirect validation. No browser cookie or Authorization header is forwarded. Service workers and WebSockets remain blocked because their sockets cannot currently share the pinned-route guarantee. Images, fonts and media are omitted. Non-GET requests are recorded without execution by default. Up to three disclosed menu/tab controls can be inspected, outside forms and with action labels excluded. Public GraphQL query replay is a separate opt-in: one complete AST-validated query, no mutation/subscription/introspection or credentialed request, no redirects, at most three operations and 16 KB per body. No cookies or authorization are forwarded. Query syntax cannot establish that an arbitrary server implements read semantics correctly; select this scope only for public query inspection. Authentication, form submissions and consent changes remain excluded.

The observer retains rendered page structure, loaded JavaScript, HTTP metadata, request initiators and JSON response types. It records HTTP errors, excluded origins, JavaScript-error counts, elapsed time and all limits. The backend retains script bodies for literal HTTP/WebSocket-reference scanning, and published source maps with embedded original modules for the normal source scanners. Indexed source maps are supported. Relative original paths share a safe virtual source tree across chunks; conflicting versions retain separate scopes rather than overwriting module records. Credential/dependency paths are excluded. A map without embedded sources cannot reconstruct original files; private or guessed map URLs are never requested. Scripts and maps are subject to separate retention/delivery budgets, and omitted records are recorded.

Public JSON response fields appear as **observed response definitions**, not database tables. Shipped-code references, recorded browser responses, blocked request attempts and published API specifications retain different basis values in the interface inspector, findings and exports. An observed request can include its initiating script, status and response shape. This does not establish the implementation behind the endpoint.

## Documents and direct reads

TinyFish Fetch may render JavaScript itself, but its extracted document representation does not replace raw client code or traffic. Defaults remain six Fetch attempts, one Search and eight direct reads; visible limits are operator-bounded. Fetch errors and retries consume the same allowance. Refresh bypasses both the application cache and TinyFish's cache using `ttl: 0`. Collection allows five minutes before browser inspection; individual direct reads use a ten-second timeout. A supplied API specification can end discovery early, but a specification found elsewhere does not stop a website assessment.

Static reads retain stylesheet declarations without spending the technical allowance on their bodies. Framework markers must occur in executable/structural markup or shipped scripts; names in prose are insufficient. Headers identify delivery services without asserting private database or backend choices. Documentation, dependencies, build tools and observed delivery remain separate technology roles.

## Feature traffic supplied by the user

For behavior behind a selected feature, open that site in your own browser, record Network traffic while using the feature, then export the HAR and import it through Files. This is a recorded snapshot; PriSMA never replays its requests. HAR inputs accept up to 15 MB before sanitization, retain up to 1,000 entries and bound the sanitized source text. Cookies, authorization, query values and request/response values are removed **before storage or model use**. JSON payloads retain types and names only. Exclusion counts remain in the sanitized record. Supported methods, origin, route, status and initiator are retained, with static resource traffic distinct from API requests. Prior saved HAR snapshots are not rewritten automatically.

## Check a new assessment

Use a fresh Public URL assessment with Browser inspection enabled. In Activity → Collection → Browser inspection, check pages, requests, retained scripts, original modules, failures and exclusions. Open Sources and a mapped connection to compare the exact supporting record. A blocked page or exhausted allowance must yield a recorded partial view, not fabricated infrastructure. Reanalyse uses the saved sources; Refresh recollects the original scope. Old reports cannot acquire missing traffic through a UI update.

Stop the optional service when unused:

```bash
sudo docker compose --profile browser stop browser
```

## Resource and product inventory

MIME, bounded content inspection and resource context share a classifier with uploaded/source evidence. Extensionless JavaScript remains code. Application entry scripts are prefetched ahead of execution and retained separately: 7 MB application text, 700 KB dependency text and 100 KB per other role, within the total acquisition/delivery ceilings. Tracking code is excluded from executable acquisition. A mixed entry bundle can contain dependencies; role is a prioritization aid, never proof of authorship. A resource above two million characters is retained as a labelled prefix with original length and omitted-content outcome; it is not presented as a complete source.

Static reads prioritize linked specifications and app scripts, preserve inline code, and inspect the standard public robots document for declared sitemap locations. Sitemaps contribute referenced routes rather than inspected-page claims. Rendered/static navigation, bounded router declarations and route-file conventions contribute a product inventory with exact source spans and inspected/declared/referenced states. Form labels, tab/menu controls, account-area references and public feature wording are retained without submitting workflows or asserting private paid functionality. Client literal calls correlate with successful anonymous traffic by method and address; page/initiator, response types, cache controls and access rejection remain separate evidence. Delivery hosts and API interfaces consolidate repeated observations; private backend implementations stay unresolved.

Launch, navigation, navigation timeout, interaction and collection failures have distinct codes. Raw pages and prefetched scripts survive a startup failure; completed page checkpoints survive a wall timeout or process failure. Every capture records whether Chromium launched. `/ready` and `/health` perform a sandboxed launch/execution probe with a bounded cached result. Non-root Chromium, user namespace calls and the dead proxy remain enabled; `clone3` returns ENOSYS for the documented glibc fallback. Temporary and home mounts are ephemeral; the non-root entrypoint creates private cache/NSS directories as the actual runtime user without assuming the base image's numeric UID.

Primary sources: [Playwright Docker guidance](https://playwright.dev/python/docs/docker), [Docker clone3 fallback](https://docs.docker.com/engine/release-notes/23.0/), [GraphQL operation semantics](https://spec.graphql.org/September2025/#sec-Operations).

## 0.8.3 access and useful coverage

Page inventories separate inspected content, publicly documented features/workflows, references, login requirements, subscription requirements and collection failures. A paid-feature mention on a public page does not establish a paywall. Unsupported browser, access challenge, denied response, error page, navigation failure and timeout reasons remain distinct. Multiple acquisition paths retain their barriers alongside usable documentation. Existing saved reports remain unchanged; read-time summaries derive the new inventory from retained source text. Documentation describes published behaviour, never tested execution.

Browser replay uses the isolated Chromium context's own user agent, without forwarding credentials or session headers. Only an unsupported-browser response is refetched to replace the initial generic-agent cache. Each selected page prioritizes up to three published application entry scripts. Stylesheet transfers are bounded to 14 requests; six of the existing 72 reads are reserved for navigation. Browser navigation can prioritize already collected public pages, rather than only the initial DOM's links. These changes keep the same request, transport, sandbox and timeout boundaries; they do not guarantee coverage of every site.

Authenticated or subscribed inspection is not implemented by this release. A public URL does not authorize access to account-only content.
