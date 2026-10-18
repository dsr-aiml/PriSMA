# Manual checks in VS Code / Kubuntu

Compilation and focused API/pipeline checks are recorded in delivery/release/verification.md. These checks cover your actual Docker runtime, browser, assets, and hardware. Apply the database backup/update instructions in delivery/release/migration.md first.

## Start and inspect

Open the existing project folder in VS Code, then use Terminal → New Terminal:

```bash
python3 scripts/overlay.py --target . --verify-installed
sudo docker compose config --quiet
sudo docker compose up --build -d
sudo docker compose ps -a
sudo docker compose logs --tail=100 migrate api worker frontend
curl -fsS http://localhost:3000/api/health
curl -fsS http://localhost:3000/api/ready
sudo docker compose exec -T api alembic current
sudo docker compose exec -T api alembic check
```

Expected: migrate exits 0 at revision 4c17a862be39, db/redis/api/frontend become healthy, worker is running, health says ok, readiness says ready, and Alembic finds no pending schema changes. The optional model service is not required for startup.

## Landing and account acceptance

Open http://localhost:3000 using the exact PUBLIC_ORIGIN address.

- Confirm the landing contains floating PriSMA branding and a theme toggle, with no navigation/header band. Architecture intelligence and SEE THE SIGNALS share the left alignment; the hero is slightly larger. Light mode retains the cool glossy white palette.
- Place your icon.png in frontend/public/ and rebuild frontend if needed. Check clarity at 48px desktop and 40px compact workspace sizing; excessive transparent image padding can make the visible artwork look smaller.
- Toggle light/dark repeatedly, reload, and check the preference persists without an initial flash. The crescent opens toward the top-right. Test reduced motion and keyboard focus.
- Placeholders remain muted; typed email/username/password become rich theme text. Click the borderless eye control: show/hide must preserve the value/caret and have an accessible label. Check at desktop, 390px, and 320px widths without horizontal overflow.
- Register with username test_user-23, a valid email, and a password of at least 10 characters. Uppercase, spaces, dots, and duplicate usernames must be rejected. The sidebar shows the larger username rather than the email.
- Existing accounts sign in with their unchanged email/password and receive a generated user_ name. Open Accounts, save a chosen username, and refresh; the sidebar must follow the saved name.
- Open another browser session for the same account. From Accounts, sign out other sessions and verify the other browser requires sign-in. Change the password: this browser stays signed in, other sessions expire, the old password fails, and the new password works.
- Sign into a second account: the first account's history, sources, questions, and exports must remain inaccessible.

## Reference and saved-source acceptance

- Open Reference and run Complete platform for the fixed Atlas subject. Expect eleven sources, five source modules, API/resource definitions and declared capabilities; Essentials uses three core sources. It remains visibly fictional. Existing stored reports retain their earlier content.
- Confirm Processing history is a connected vertical timeline of saved events and timestamps. Refresh mid-job and reopen from history.
- Expand the constellation: about 90% viewport, no background scroll/focus, Escape closes and restores focus. Pan/zoom, search, layer filter, select a component/connection, and inspect both supporting and contradicting evidence.
- Return to Overview; confirm reference history/counts are absent. Saved documents is the default. Import delivery/samples/beacon.openapi.json, label beacon.example, and select Explicit parsing. The report must use supplied sources rather than Atlas. Expect /projects GET/POST, /events GET, logical Project/Event resources, fields with unestablished physical types, and exact quote spans in Inspect source.
- Import beacon-notes.md with a configured model as described in local-inference.md. Inspect actual component/technology extraction, feature tiers, limits, coverage, model identity, and timings. Do not assume small-model output matches an exact component count.
- With semantic retrieval selected and its embedding model installed, ask a supported question and an unknown storage question in Questions. Answers must show exact citations or an insufficient-evidence state, never guessed private tables. Check opposing pricing statements from two imported sources remain reviewable.
- Select an unavailable model/configuration: it must fail clearly with sources retained and no Atlas substitution. Importing a URL must never navigate to it. Public web remains disabled until you explicitly configure TinyFish.
- Export SQLite, JSON, and Markdown for each workflow. Saved-source exports must retain real supplied-source provenance, original text, passages, citations, feature mappings, questions, and run metadata. Reference exports must keep fictional provenance.

## Inspect an exported SQLite file

Use your downloaded file's actual path:

```bash
python3 - ~/Downloads/prisma-YOUR-INVESTIGATION-ID.sqlite <<'PY'
import sqlite3, sys
from pathlib import Path
path = Path(sys.argv[1])
assert path.is_file(), 'Choose the actual downloaded report'
with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
    print('Integrity:', db.execute('PRAGMA integrity_check').fetchall())
    print('Foreign keys:', db.execute('PRAGMA foreign_key_check').fetchall())
    print('Metadata:', db.execute('SELECT * FROM metadata').fetchall())
    print('Claims:', db.execute('SELECT COUNT(*) FROM claims').fetchone()[0])
    print('Citations:', db.execute('SELECT COUNT(*) FROM claim_citations').fetchone()[0])
PY
```

Expected: integrity ok, no foreign-key failures, SQLite export schema_version 3 and the correct mode. Reference reports have no span citations; saved-source reports do.

## Restart and laptop checks

After a completed report:

```bash
sudo docker compose down
sudo docker compose up -d
```

Accounts, history, sources, questions, and exports should remain. If using local inference afterward, restart the optional service with sudo docker compose --profile inference up -d ollama. Never add -v when preserving storage.

Use docs/local-inference.md for RAM/CPU/multitasking acceptance and the smaller-model fallback. Use docs/evaluation.md for actual inference-versus-baseline results. Inspect DevTools Console/Network for errors, rejected cookies, or failed polling. Browser E2E, actual model runs, and peak laptop memory are not packaging checks.

## Optional repeatable code checks

```bash
sudo docker compose exec -T api python -m compileall -q app
sudo docker compose exec -T api ruff check app tests alembic/versions/2b74c193ad06_accounts_and_sources.py
sudo docker compose exec -T api python -m pytest -q
python3 scripts/test_overlay.py
python3 scripts/test_upgrade.py
```

With Node 22+ installed:

```bash
cd frontend
npm ci
npm run typecheck
npm run build
# Optional; the application must be running. Creates its own test account/report.
npx playwright install chromium
npm run test:e2e
cd ..
```

If a job remains queued, inspect worker/redis logs. If migration/API startup fails, inspect migrate logs and keep the backup intact. A changed .env password does not change an existing PostgreSQL volume's password. Preserve local changes before resolving an overlay hash refusal. Share only relevant error lines, excluding passwords, cookies, keys, and private source content.

## Integration scaffold acceptance

- Confirm Reference has its own history and real reports never contain Atlas counts, names, annotations or fictional provenance. Open a reference deep link from Overview and confirm it routes to Reference.
- Check model profiles: Lightweight is default; larger options are disabled until configured. Installed model bytes and loaded-model VRAM are capacity observations, not benchmark claims. Confirm unavailable/over-budget models fail explicitly.
- With actual local inference, analyze Beacon notes. Inspect Web client, Gateway API, Job queue and Worker, and their documented links. Document titles must not become components. Inspect quotes rather than assuming count equality proves correct extraction.
- Compare genuinely different saved source collections; summaries and findings must differ. Test negated technology adoption, pricing tables, contradictory terms, long documents, duplicate pages, malformed OpenAPI and unknown storage questions.
- Configure and test TinyFish only when ready using docs/tinyfish-integration.md. Check dashboard usage against recorded attempts and all failed/partial outcomes. No failure may substitute Atlas data.
- Download all three formats. Markdown should read as a formal assessment; JSON must identify prisma.report schema_version 4; SQLite must retain source_metadata and collection_outcomes and pass integrity/foreign-key checks. Hover underlining remains on report links.
- Run profile/corpus comparisons and monitor multitasking as in docs/local-inference.md and docs/evaluation.md. These are required before claiming hardware suitability or generalized production accuracy.

Current release-specific acceptance, including actual Chromium launch and unrelated public-site coverage, is in [0.8.1 verification](../delivery/release/verification.md).
