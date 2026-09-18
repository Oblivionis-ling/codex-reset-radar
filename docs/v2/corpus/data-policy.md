# Historical Corpus Data Policy

## Purpose and boundary

The corpus exists to preserve source evidence, explain coverage, and provide a small number of attributable historical comparisons to the existing DeepSeek Judge. It is not a training dataset, probability model, public mirror, or replacement for current evidence.

## Content classes

Every stored observation distinguishes:

- English/source-language original text;
- Chinese translation;
- browser-translated capture;
- third-party quote;
- third-party summary or classification claim;
- unresolved text conflict.

Chinese text is never translated back to English and presented as Tibo's original. Reply targets, quoted authors, and third-party commentary are not merged into Tibo's own words.

## Verification and completeness

`verification_status` uses `direct_verified`, `source_quoted`, `indexed_only`, or `unverified`. Completeness, context, truncation, time source, and time precision are independent fields. A source's “verified” or “global reset” label is evidence about that source's claim, not automatic V2 confirmation.

## Time semantics

`posted_at` is the post time or a Tweet-snowflake-derived time. `collected_at`/`captured_at` is when evidence was obtained and is never substituted for the event time. Event completion, announced time, effective range, and post-time proxy remain separate.

## Storage and publication

Long-lived local data may include normalized source text, translations, evidence links, verification records, reviewed event/case records, coverage rows, and final structured analyses. Raw pages, fetch diagnostics, model request debugging, and retries are short lived.

Complete source snapshots are written below `data/corpus/`, which is ignored by Git. SQLite, logs, browser storage, Tokens, UIDs, Cookies, notification recipients, and complete copied corpora must not be committed. Repository documents may include only short attributable excerpts needed to explain a result.

## Runtime isolation

Historical imports use `ingestion_mode=historical`, an `import_batch_id`, and a fixed `source_cutoff`. They do not:

- enqueue per-post realtime analysis;
- trigger notifications;
- trigger a Judge per imported row;
- update collector heartbeat state;
- treat an old announcement as newly published;
- promote third-party event labels into `reset_events`;
- move the current Full Reset cycle backwards.

## Retention and deletion

Local evidence needed to support a retained case may remain long term. Temporary network/debug artifacts follow the existing five-day bounded-log policy. A batch rollback operates only on rows recorded by that batch; it restores captured pre-images when safe, removes batch-only evidence/posts, and refuses to overwrite a newer post change.

## Security

Corpus text is untrusted model input. Prompts continue to instruct the model not to follow embedded instructions or expose credentials. Network/model calls occur outside long SQLite write transactions. Secret scanning is required before any future commit.
