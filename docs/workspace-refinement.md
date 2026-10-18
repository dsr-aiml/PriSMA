# Workspace behavior

The workspace uses shared cool-neutral colour tokens, shallow surface highlights and opaque panels. A page-level theme crossfade keeps the palette change synchronized where the browser supports View Transitions; other browsers use a uniform fallback. Reduced motion changes the theme immediately.

The landing illustration is generated in CSS. Its layers represent source structure, system relationships and evidence. It contains no assessment values and requires no image or WebGL download. Pointer movement adjusts its perspective; hidden-page and offscreen checks pause the decorative sheen.

The sidebar and content width use the same navigation variable. Collapsing navigation preserves the footer's height and hides sign out in its compact state. The evidence inspector starts at 460px and can be resized between 340px and 700px on wide screens. Narrow screens use a sheet.

## Research queries

New questions use one server-managed hosted model, Gemini 3.5 Flash-Lite by default. Query settings are recorded separately from assessment settings. Historical answers and their provider/settings remain intact. The Research interface has no engine selector; setup and privacy are in [research queries](research-queries.md).

Report records identify relevant components, directed relationships, technologies, APIs, data definitions and capabilities. Source matching ranks normalized passages using lexical relevance, expanded architecture terms, source diversity and bounded source-unit selection. Query synthesis makes no embedding calls or fresh collection, so an original local semantic index can remain unloaded.

The model receives the question, relevant report records and exact source units. It returns concise answer paragraphs linked to source-unit IDs; the server reconstructs quotations and checks offsets. The answer appears first, with Sources and Details below. Quote validation establishes attribution, not semantic entailment. Errors remain visible, records remain accessible, and no alternate inference provider is substituted. Markdown presents the answer with source references; JSON/SQLite retain full metadata.

## Reference exploration

Atlas opens immediately as transient presentation. It creates no investigation, evidence, question, event, model cache or queued job. Its exports are generated on request without saving an assessment. Reloading returns to the reference selection. Previously stored reference records are excluded from workspace history and counts; this update does not delete historical database rows.

## Exploration

The repository explorer opens its first retained module, follows resolved imports and incoming static references, and exposes source text, declarations, diagnostics and linked findings. Its index is virtualized. Full selected paths remain readable; index previews provide the complete path as a tooltip.

The constellation starts with the complete retained map. System boundaries and source-code groups can be isolated without promoting implementation groups into deployed services. Node and connection routing use the same computed layout. Map controls are available inside and outside the expanded view. 

Ctrl+K searches workspace pages, real reports and the current assessment's sources, components, modules, API operations, data definitions and findings. Multiword report queries match each word independently. Requests are debounced and canceled when stale; keyboard selection opens the corresponding view and record.

Export selection prepares the download before closing the menu, retains preparation errors in place and uses the authenticated report route. Schema and definition layouts wrap long property names and values rather than hiding them.
