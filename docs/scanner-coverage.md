# Source scanners and collection

## Shared evidence pipeline

GitHub archives, uploaded ZIPs/folders/files, public resources and supplied HAR captures enter the same normalized evidence and exact-citation pipeline. Archive order does not determine admission. Manifests, declared entrypoints, configuration, architecture and application code precede support material. Translations, tests and third-party material retain their roles and can be selected explicitly. Nothing from an imported repository is installed or executed.

## Syntax capabilities

JavaScript/TypeScript uses TypeScript 5.9.3 in a bounded Node subprocess with a virtual compiler host. It reads JS/JSX/TS/TSX/MJS/CJS/MTS/CTS, declarations, imports, named imported calls, literal request expressions and interface/object-type properties. Python uses AST and symbol-table records for imports, calls, route decorators and declared dataclass/Pydantic/TypedDict properties. Resolution covers retained relative modules, JS-to-TS extension substitution, declared TypeScript path aliases/output directories, and package main/source entries. Dynamic/generated resolution and arbitrary package export conditions are not treated as resolved facts.

Source groups describe code organisation. Architecture and Implementation views separate documented/runtime boundaries from source modules. Module paths, declarations, calls, diagnostics and references remain inspectable. Kotlin, Java, Go, Rust, C#, Swift, PHP, Ruby, Scala and C/C++ use bounded literal declaration/import adapters, explicitly marked partial. JVM resolution indexes retained package symbols, including member imports; Go imports resolve within declared module roots. Kotlin data-class properties retain source types. Vue/Svelte executable script blocks use the TypeScript scanner with padded markup to preserve offsets. Languages without an adapter remain inventory-only. Mermaid supports bounded labelled flowcharts, including standalone .mermaid/.mmd files. OpenAPI, SQL, Compose, manifests and public markup retain their existing structural adapters. HAR maps recorded requests, not inferred private services.

## Budgets

Uploads: 50 MB. ZIP expansion: 120 MB. Individual source files: 2 MB. Combined readable text: 12 million characters by default, configurable with SOURCE_BUNDLE_CHARACTERS from 1 to 24 million. Review: 2,000 retained sources and 20,000 archive/folder entries. Encrypted members, symlinks, nested archives, dependency/generated directories and credential files are excluded. PDF/Word extraction has separate page/XML/text limits.

Native declaration adapters inspect at most 500,000 characters per file and retain at most 500 imports/symbols/schema declarations in each category; complete source text remains available.

JS/TS packets contain at most 32 files and two million source characters. Node heap is capped at 256 MiB; each packet has a 35-second timeout and eight-MB output ceiling. Individual inventories are bounded; shared syntax rows are capped at 30,000, module groups at 64 (including a remaining-modules group) and type fields at 150 per declaration. Coverage records unparsed/unavailable files, unsupported languages, unresolved internal imports, bounded records and ungrouped modules. These are operational bounds, not measured laptop capacity guarantees.

Inference reviews bounded relevant source passages rather than entire repositories. Extraction defaults to 16 new model requests; embeddings use up to 64 new requests in batches of 16 passages. Configure ANALYSIS_MAX_REQUESTS and ANALYSIS_MAX_EMBEDDING_REQUESTS separately. Compatible account-owned responses and syntax records can be reused. A model interruption preserves structural findings and completed review. An incomplete semantic index uses lexical passage search and remains explicitly incomplete.

## Public collection controls

Document fetches: maximum new TinyFish Fetch attempts, including a permitted transient retry. Cached pages also count toward distinct visited-URL scope, preventing unlimited cached crawling.

Discovery searches: maximum TinyFish Search queries, not number of results. Discovery runs on demand after available document candidates are exhausted; a supplied explicit specification can stop further collection.

Linked public files: enable direct reads of the page and explicitly linked specifications/scripts. Direct public reads include the initial page, resources and redirects, independently of TinyFish Search/Fetch allowance. External linked scripts require a separate opt-in. Public source-map links may supply up to 100 bounded original sources; embedded paths/parent attribution are retained, without executing code or guessing endpoints.

Defaults are six Fetch attempts, one discovery Search and eight direct reads. Setting everything to one is a smoke test: the single direct read can be consumed by the page itself. Use the default allowances for an initial investigation if your provider allowance permits; increase only after examining the collection record. Daily quotas and administrative ceilings still apply. Collection need not consume every allowance.

Reanalyse saved sources uses stored snapshots, can change engine/select a subset and creates a new report. Refresh from origin creates a new report and queues fresh repository/live collection; it bypasses the application collection cache, not any upstream service/CDN cache. GitHub downloads retain archive hashes/timestamps. Stop and resume retain per-origin repository checkpoints.

Primary parser references: https://github.com/microsoft/TypeScript/wiki/Using-the-Compiler-API and https://www.typescriptlang.org/docs/handbook/modules/reference .

Optional rendered-page observation has a separate bounded Chromium pass. See `docs/public-observation.md` for the service, scope and request limits. Compiled public bundles are delivery evidence; original modules from source maps or repository files use the syntax scanners.

## Build and application configuration

Gradle/Kotlin DSL, version catalogs actually referenced by builds, Maven dependencies, Go modules, Cargo dependencies, .NET package references and Android manifests receive structural extraction. Test and build dependencies have separate roles. Android manifest registration is linked to an unambiguous retained implementation class; this establishes source organisation, not measured execution. Compiled/minified JavaScript remains inspectable inventory rather than a misleading source-module map.

Technologies shows application declarations, known source imports and observed client/delivery signatures first. Build/test tooling and unresolved namespace references are separately inspectable. A dependency declaration establishes a declaration; browser markers establish observed delivery. Neither automatically establishes a private backend.

Public observations retain navigation, form actions and public field definitions without values. Stylesheet declarations remain in the resource inventory without consuming direct body reads. The optional Chromium observer captures the initial anonymous render; it does not sign in, submit forms, or browse an entire application.

## Technology presentation

Evidence roles are shared across input paths. The application view includes observed client/delivery markers, languages, actual source imports, dependency/container declarations and documented stack sections. Tooling separates development, build, tests and unidentified references. One displayed technology retains its complete declaration list; versions from a tooling-only declaration do not become application versions. Python/Poetry/requirements and npm optional declarations retain explicit roles, version constraints and original citation anchors. Safe legacy role corrections are read-only and use source format and parser provenance, never a project name.
