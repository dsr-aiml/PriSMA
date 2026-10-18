# Report export contract

Default JSON identifies `prisma.report` schema version 4, defined in `backend/contracts/report-v4.schema.json`. Original version 3 report imports remain supported. Stored report snapshots retain their own internal schema version.

Compact JSON stores each normalized source once in `source_texts`, addressed by the evidence record's `content_ref`. Passage records contain source IDs and half-open Unicode offsets rather than another copy of the passage text. Evidence metadata, exact finding quotations, questions, collection counters, scanner coverage and model provenance remain in the document. This format can be re-imported as normalized source snapshots.

The Evidence ZIP contains `prisma-evidence.json` and content-addressed original/normalized text under `evidence/`. Its manifest uses version 4 with `content_storage: bundle_files`; source references point to ZIP members. Import this bundle when original formatting matters. The importer reads named members without extracting or executing the archive and applies the ordinary per-source/bundle budgets. It restores sources, attribution and safe original acquisition context, never old claims or answers.

Markdown is a reader-oriented assessment: executive summary, research highlights, system relationships, technology roles, interfaces, data definitions, capabilities, implementation groups, open points and the assessment record. Complete compact finding/source registers preserve supporting and contradicting references. Large presentation inventories state their shown/total counts; JSON, SQLite and the evidence bundle retain detailed records and exact excerpts. Completed Research answers are included only when their source spans still validate. Exporting invokes no additional model inference.

Evidence matrix CSV contains every finding row and every distinct source-snapshot column, grouped by content hash exactly like the dashboard. Cells distinguish Supporting, Contradicting, Both and no link. It is independent of screen filters, virtualization and pagination. CSV uses UTF-8 with a BOM, standard quoting/newlines and spreadsheet-formula protection. The authenticated matrix route is also stateless for reference assessments.

SQLite retains normalized claims/evidence links, architecture, declared entities/fields/references, source passages, original source metadata, exact citations, questions and full report/processing records. It is the assessment database, not a reconstruction of private physical storage.

Offsets refer to normalized Unicode character positions using [start,end). Code and structured source whitespace is preserved; original text has its own hash. No raw-to-normalized offset map is claimed. Scores are heuristic evidence strength; exact quotations establish attribution rather than independent semantic entailment.
