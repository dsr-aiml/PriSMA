# Research queries

Questions use the saved assessment and relevant source passages to produce a natural-language answer through **Gemini 3.5 Flash-Lite** (`gemini-3.5-flash-lite`). The Research page has no engine or local-profile selector. Extraction still uses the engine chosen at intake; its report and embedding index are never rewritten by a question.

## Server setup

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey). Check the model's availability, account quota and billing in that project; a free allowance is not guaranteed. Put the following in the root `.env`, preserving all other settings:

```dotenv
GEMINI_API_KEY=your_actual_key
ALLOW_HOSTED_QUERIES=true
GEMINI_QUERY_MODEL=gemini-3.5-flash-lite
```

Do not put the key in `frontend/`, browser settings, exports, source control or screenshots. The query-specific flag defaults to true, but a missing key prevents queuing a question. `ALLOW_HOSTED_MODELS` governs assessment inference separately and can stay false. Compose passes the query settings only to backend services.

After changing `.env`:

```bash
sudo docker compose up -d --force-recreate api worker research
sudo docker compose ps
```

No model download or Ollama service is needed for Research. A configuration read makes no provider call and does not verify key validity, billing or quota; the first submitted question checks actual access.

## Answer path

1. Check sign-in, report ownership, completed status and the account's pending-question limit. Snapshot the server query model and budget on the new question.
2. Rank report records and normalized passages using identifiers, expanded architecture terms, source diversity and the question's intent. Use source matching even if the assessment has a local semantic index, so questions have no dependency on the original embedding service.
3. Supply a bounded packet containing relevant records, source-unit text, source paths, report counts and processing scope. Up to 96 ranked chunks and citation-backed orientation feed a packet capped at 80 KB plus instructions; this does not send the entire repository or report. Units are selected within that budget. Context defaults to 32,768 tokens and output to 3,000 tokens. Up to 128 exact units (480 characters each) can contribute roughly 10–20k source tokens when enough relevant evidence exists; actual tokenizer counts depend on the source language. The model uses minimal thinking for this focused synthesis.
4. Make one serialized Google generation request after the user submits. No fresh collection, Google Search grounding, embedding request, automatic retry or provider substitution occurs. A validated account-scoped response cache can reuse the same question/context/model.
5. Validate the answer contract and selected source-unit IDs; reconstruct exact quotes and offsets on the server. Remove paragraphs with unresolved citations. Citation matching establishes source attribution, not semantic entailment or guaranteed correctness.
6. Show the answer first, with compact source links. Sources and Details expose quotations, report records, retrieved passages and model provenance. Access, quota, timeout and invalid-output failures remain visible; saved report records are still accessible without pretending they are a generated answer.

Source text and repository instructions are untrusted input. The system instructions require a direct answer, question-appropriate detail, supported mechanisms, preserved conflicts and specific gaps rather than generic caveats or invented implementation. The provider can only answer from the excerpts supplied; it is not an independent live-web investigation.

Atlas questions remain a stateless reference preview derived from its fixture records. They make no Google request, save no question and do not enter report history. Existing questions keep their original recorded provider/settings.

## Manual check

Open a completed real assessment and ask a focused question, such as “How are these components connected?” The page should show paragraphs before records. Open a source link and compare the excerpt; inspect Sources and Details for model identity. Try a question about an absent detail and check it is left unresolved. Export Markdown and verify the natural answer and source references appear in Research discussion; JSON/SQLite preserve complete answer metadata. Incorrect key, missing quota and disabled-query errors must not turn into local or reference answers.

References: [model catalogue](https://ai.google.dev/gemini-api/docs/models), [Flash-Lite model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output), [generation migration](https://ai.google.dev/gemini-api/docs/generate-content/whats-new-gemini-3.6).

## Request diagnostics

The raw REST transport uses the documented enum values `APPLICATION_JSON` and `MINIMAL`, rather than SDK MIME strings/lowercase thinking labels. HTTP 400 errors show validated field paths when Google supplies them. Invalid-key and billing errors are identified separately. Provider messages, prompts, source contents and keys are not echoed into errors. Reference: [REST generation contract](https://ai.google.dev/api/generate-content).

## Conversations

Research belongs to one saved report. A first prompt creates a chat; follow-up prompts use its identifier. Existing questions migrate to individual conversations without changing their answers or model provenance. The sidebar lists up to 200 chats per report; a chat supports up to 100 turns. Deleting it permanently removes messages and conversation answer caches; an active response must finish first. Deleting a report or clearing its owner's data cascades through all chats. Reference conversations remain in browser memory only.

Each answer uses the current prompt, up to four recent completed turns, a bounded report synopsis, relevant report claim anchors and ranked source passages. Follow-up retrieval carries prior referents locally, with no extra model call. Context stays within the configured byte/token budget, at most 80 KB plus task instructions, and orientation never substitutes for supporting source-unit citations. One successful synthesis is retained per prompt, with at most three recorded transport attempts for retryable temporary failures; account-scoped validated caching includes the conversation identity. Opening or selecting chats sends no inference request. The report's extraction engine and embedding index remain unchanged.

JSON and SQLite exports retain chat identifiers per question; Markdown groups recorded exchanges into conversations. These exports retain exact source attribution and per-response provider outcomes.

## Scheduling and recovery

Research has a dedicated `research` worker/queue and a separate hosted scheduling lock. It does not wait behind a repository assessment or contend for the local model's memory slot. Compose starts this worker normally, with a 512 MB memory and one-CPU ceiling. No new inference request is sent when viewing chat history.

Candidate matching runs in the database over up to eight query terms and a bounded source pool; application/documentation orientation supplements lexical matching. Resource roles reduce vendor/tracking prominence, exact duplicate excerpts are omitted, and source diversity limits a single source's share. No embeddings or new web collection are needed for Research.

`RESEARCH_TIMEOUT_SECONDS` remains 45 seconds per HTTP attempt (15–90). `RESEARCH_TOTAL_SECONDS` defaults to 180; the RQ job ceiling is 240 seconds and the query lease spans the complete retry window. Temporary 429/500/502/503 failures allow at most three attempts with exponential backoff, jitter and Retry-After/RetryInfo handling. Failed attempts consume the local allowance too. A 504, ambiguous timeout/transport failure, invalid output/contract, access/configuration error or exhausted daily/zero quota is not retried. No alternate provider or model is substituted. Attempts and selected-context counts are retained in the answer record; source records survive failed interpretation.

Pacing uses an atomic Redis rolling ledger. Defaults are `GEMINI_QUERY_RPM=6` and `GEMINI_QUERY_INPUT_TPM=120000`, conservative server settings rather than claims about a free tier. Set them to the active model/project limits shown in AI Studio. `GEMINI_QUOTA_PROJECT` is an optional shared project label for servers using different keys for the same project; otherwise a key hash identifies the ledger. Admission uses a conservative byte-based input estimate and waits at most `RESEARCH_MAX_WAIT_SECONDS=65` within the overall deadline. The ledger covers this server's Research calls and cannot observe assessment or unrelated application traffic; allocate budget for those separately. Google enforces RPM, input TPM and RPD per project, not per API key. A 503 indicates temporary service capacity trouble, while 429 covers quota/capacity exhaustion. Availability and unsupported source details cannot be guaranteed.

Primary sources verified 13 October 2026: [Gemini limits](https://ai.google.dev/gemini-api/docs/rate-limits), [API errors](https://ai.google.dev/gemini-api/docs/generate-content/api-errors), [troubleshooting](https://ai.google.dev/gemini-api/docs/troubleshooting), [REST response-format contract](https://ai.google.dev/api/generate-content). The raw generateContent API uses `responseFormat.text.mimeType=APPLICATION_JSON`; retain that enum rather than copying the separate Interactions API's MIME string.

## 0.8.3 answer quality

Product and documented-workflow citations supplement report orientation, and are prioritized before incidental runtime snippets in the bounded answer context. Format-only follow-ups retain their prior topic; asking for “100 words, pointers” requests a bullet summary, rather than pointer-event code. The most recent conversation is retained while lower-value packet material is trimmed. Original questions and model settings remain unchanged.

Answers still reconstruct exact spans from source-unit IDs. Additional conservative guards reject unsupported numeric facts, visibly unrelated support and original-repository assertions based only on shipped browser code. This is not a complete semantic entailment check. Rejection reasons and partial-answer states are retained, rejected output is not answer-cached, and no extra validation/model rewrite request is added. The answer-cache namespace advances to v7.
