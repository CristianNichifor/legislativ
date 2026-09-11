# Source registry and incremental sync contract

This is the bounded scaffold for source registry and source-sync work. It does
not introduce a backend scheduler, bulk imports, public data releases or AI
analysis. The first product goal is smaller: add or select one public source,
sync only that source, and show exactly what happened.

## State vocabulary

Every registry or queue row must use one of these states:

| State | Meaning |
| --- | --- |
| `discovered` | Source is known by URL or public identifier; no fetch attempted in this queue. |
| `queued` | Source was selected for one bounded sync attempt. |
| `fetched` | Source bytes or metadata were fetched for the first time. |
| `unchanged` | Fetched source hash matches the previous retained observation. |
| `changed` | Fetched source hash differs from the previous retained observation. |
| `failed` | Fetch or parsing failed for a retryable reason. |
| `unavailable` | Official source is absent, unsupported, removed or outside allowed access. |
| `rate_limited` | Official source asked the app to slow down or returned an equivalent limit. |
| `needs_review` | Source is fetched but cannot safely update derived legal data automatically. |

These states are shared by Romanian legislative portal acts, parliamentary
projects, consultation pages, CCR decisions and EU CELEX sources. Individual
source adapters may keep richer internal status, but public UI/API state must
map back to this vocabulary.

## One-source sync boundary

The first sync implementation must accept one source at a time by public URL or
identifier. A sync attempt may fetch metadata or bytes for that source and its
direct official document target when the existing adapter already supports it.
It must not rebuild the whole corpus, walk a whole portal, publish a release, or
recalculate saved legal conclusions.

Each attempt must record at least:

- source family;
- source identifier or URL;
- attempted timestamp;
- state;
- status code or bounded error category;
- content hash when source content is available;
- parser version when parsing was attempted.

The attempt must not record raw secrets, local filesystem paths, full private
dossier content or unbounded upstream error bodies.

## Change handling

`unchanged` means the newly fetched hash equals the previous retained hash. It
does not mean the law is current, complete or legally unchanged in the wider
world.

`changed` means the source hash differs. It should queue or display work for
human review before dependent findings or proposals are treated as current.
Saved dossier evidence remains historical and must not be overwritten.

`needs_review` is for fetched sources that cannot safely update structured data:
ambiguous document targets, parser drift, unsupported format, multiple candidate
official files, changed legal structure, or conflicting lifecycle signals.

## Acceptance

A first backend slice is acceptable when:

- a test can classify first fetch, unchanged fetch, changed fetch, unavailable
  source, retryable failure and rate limit without network access;
- the app contract says which fields a real attempt will store;
- no large release, bulk download, AI call or dossier mutation is required;
- missing and unavailable sources remain visible as source state, not hidden as
  zero results.

The checked-in pure contract is `scripts/source_sync.py`; its tests are in
`tests/test_source_sync.py`.
