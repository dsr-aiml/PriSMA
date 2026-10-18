# Research workspace

See [workspace refinements](workspace-refinement.md) for current query, reference, theme and navigation behavior.


Source, module, API, schema and technology views share contextual evidence inspection. Wide screens use an adjacent inspector with a keyboard-resizable divider. Narrow screens use a focused sheet. Ctrl+K searches pages, reports, components, modules, sources, API operations, schema definitions and findings. Report library search identifies the recorded analysis engine. Reference exploration is stateless and does not enter saved history; saved sources are read-only and whole reports have deletion controls.

## Insight derivation

The backend derives a versioned research summary without collection or model calls. It preserves API contexts, resolved module references and source/claim identities. Identical normalized hashes add no distinct snapshot support. Cross-source support is conservative and does not establish publisher independence. Dependency counts describe retained static imports, not runtime load. Recorded network captures are identified separately from contracts. Model interpretation and the original findings are unchanged.

Research highlights appear in Markdown. JSON and Evidence ZIP include the same structured analysis summary; SQLite adds a research_summary table. Existing v3/v4 import behavior remains compatible: import restores source snapshots and reanalysis produces current findings, not copied old insights. Evidence ZIP preserves stored original/normalized text snapshots; binary formats retain the reader's stored representations and provenance.

## Reading and rendering limits

- Long source/module/support inventories use virtualization or bounded expansion. Search addresses the full retained inventory.
- Source reading shows up to 80 original lines and 20,000 UTF-16 characters per reading segment. Large minified lines have segment navigation. Full normalized text can be copied/downloaded. Exact verified citations are converted from Unicode character offsets before highlighting; malformed ranges are not highlighted.
- The derived response includes up to 60 prioritized insights, 24 linked finding IDs and 32 source IDs per insight. Complete findings and sources remain in their inventories/exports.
- ELK layout executes in a worker with a 12-second limit for maps up to 600 nodes/3,500 edges. On a failure or larger graph, the retained layout remains usable. Layout cache is bounded.
- Loaders pause offscreen/in hidden tabs and honor reduced motion. Activity waves are activity indicators, not CPU telemetry or a model reasoning visualization. Job percentages are not presented as measured work completion.

## Interrupted delivery

Check worker delivery reads the owned assessment's bounded RQ delivery records. Reconciliation is offered only if all recorded deliveries ended while the database assessment remains active. Active, missing, excessive or unavailable delivery records block it. Reconciliation preserves sources/checkpoints and request counts, marks retained work partial, and records interruption. Resume/reanalysis is a separate user action. No background guess based on elapsed time stops work.

## Operator notes

Keep Docker services private as configured, use a controlled HTTPS proxy for external access, and set PUBLIC_ORIGIN and COOKIE_SECURE for the actual origin. Configure provider credentials only in server environment files. Retain per-run and shared daily request ceilings; browsing a saved report does not recollect sources.

Before an externally accessible deployment, verify session rotation/revocation, owner isolation, per-user deletion, input/archive limits, source/import retention, provider failures and backups on the actual stack. Visual changes and offline compilation do not replace those operational checks.

A database backup can be created without clearing volumes:

```bash
cd ~/Desktop/Codes/Kritical
mkdir -p backups
sudo docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "backups/prisma-$(date +%Y%m%d-%H%M).dump"
```

Confirm the command succeeded and the backup is non-empty. Test restoration against an isolated database before depending on it; do not restore over an active workspace as an update step. Keep model weights in their existing volume. No new model pull or asset download is required by this release.
