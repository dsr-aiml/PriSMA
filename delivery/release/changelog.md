# PriSMA 0.8.6

- Fix Reanalyse failing with a generic server error when public collection retained an XML sitemap. XML and CSS now share the validated intake/reanalysis source contract.
- Preserve XML/CSS text and whitespace, and classify extensionless XML as configuration and CSS as source evidence rather than prose for inference.
- Reuse the validated saved-source builder for Reanalyse and repository Refresh. Handle missing or malformed saved titles with the original source label, preserve supported source categories, and return actionable validation errors for incompatible retained fields or legacy settings without echoing document contents.
- Keep original assessments, source attribution, ownership, provider quotas and the 0.8.5 interface behavior intact. Reanalysis still queues a new saved-source report without recollection.

This hotfix targets 0.8.5. No database migration or .env change is needed. User-owned fonts/logo, named volumes, saved reports/chats and installed models are preserved.
