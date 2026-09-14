# Source registry and incremental sync contract

This is the bounded scaffold for source registry and source-sync work. It does
not introduce a backend scheduler, bulk imports, public data releases or AI
analysis. The first product goal is smaller: add or select one public source,
sync only that source, and show exactly what happened.

The v1 acceptance dataset baseline is even narrower: it is a checked-in manifest
of local fixtures and placeholders, documented in
[`V1_SCOPE_AND_ACCEPTANCE_DATASET.md`](V1_SCOPE_AND_ACCEPTANCE_DATASET.md). It
validates sample coverage and missing-source visibility without invoking source
sync, a crawler or release packaging.

The broader source portfolio, Monitorul Oficial ingestion policy, R2 storage
bands and legislative tracker event vocabulary are defined in
[`SOURCE_PORTFOLIO.md`](SOURCE_PORTFOLIO.md).

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

The app UI exposes this boundary from **Matrice → Registru surse urmărite**.
Each row can be placed in the queue or synchronized directly. The result stays
visible after reload as one of the shared states: fetched, unchanged, changed,
failed, unavailable, rate-limited or needs-review. A changed source is a review
signal, not an automatic legal conclusion. A failed, unavailable or rate-limited
source remains visible in the registry instead of becoming an empty result.

`GET /api/registru-surse` returns a `sync_status` object for every source row.
`GET /api/registru-surse?id=src_...` limits the response to one selected row
without starting a sync. The status object is read-only UI/API guidance:

- `state`: one of the shared sync states;
- `label`: human-readable state description;
- `severity`: `ready`, `ok`, `attention` or `blocked`;
- `can_queue`: whether the row can be moved to `queued`;
- `can_sync`: whether this source family has a direct one-source sync adapter;
- `can_review`: whether the row can be manually marked reviewed;
- `next_action`: the safest next user action for that selected source.

This selected-source status endpoint must not fetch upstream sources, rebuild
datasets, recalculate dossiers or mutate the registry.

Static GitHub Pages/browser workspaces do not fetch official sources. They may
show local/public snapshots, but one-source acquisition requires the local Python
server because it writes the source registry and retained source databases.

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

For parliamentary project sources (`parlament`, `camera`, `senat`), a successful
one-source sync also stores a compact `parliament-project-source-snapshot-v1`
record. The snapshot includes the selected PL-x/id, the addressed ficha URL, the
official document links discovered on that ficha, and bounded local initiative
metadata. If a specific official project document URL is synced, the snapshot
records the retained document hash and extraction status instead of raw bytes or
full extracted text.

For `consultare_econsultare`, a successful one-source sync stores a compact
`econsultare-source-snapshot-v1` record. The snapshot keeps the official page
URL, title, initiating authority when visible, deadline/status when visible and
bounded official attachment links. It does not crawl the whole consultation
portal, follow ministry pages, translate documents, run AI or decide whether the
draft is legally compatible with existing law. Pages without a clear title or
document links are retained as `needs_review`, not treated as empty results.

The registry can also run `{"action":"discover_econsultare","limit":50}` against
the official ActionGrid listing. That registers bounded consultation rows as
normal `consultare_econsultare` sources, stores their listing snapshots and emits
tracker events. It does not download attachments; each discovered consultation
remains an individual source that can be inspected or synced separately.
Rows marked `changed` or `needs_review` can be cleared directly from the
e-consultare feed after inspection; the registry records the review as another
source attempt and moves the row back to `unchanged`.

The real pilot fixture is narrower: it keeps one official ActionGrid row from
`https://e-consultare.gov.ro/Consultare-publică`, normalizes it with
`scripts.real_public_consultation`, and proves URL, institution, open stage,
deadline and row hash. It does not retain the full 1998-row listing response or
download attachments.

For `consultare_minister` and `avize`, the first usable slice is metadata-first:
the caller registers one official URL or public identifier and may pass bounded
metadata in a `sync` request. The registry stores a
`manual-source-metadata-snapshot-v1` record with title/authority/deadline and
document link/hash metadata for ministry consultations, or issuer/position/
observations/document-hash metadata for avize. This path intentionally does not
scrape ministry pages, follow portals or infer legal conclusions from document
text. If the metadata is enough to identify a consultation or received opinion,
the sync stores a tracker event candidate and returns `tracker_sync.stored` plus
`tracker_sync.event_types`; otherwise the row remains visible as `needs_review`.

For `ue_cellar`, one-source CELEX import prefers official Romanian text (`RON`)
and falls back to official English text (`ENG`) only as an explicit fallback
state. Import responses expose `language_state` and `language_note` so callers
can distinguish `official_ro`, `official_en_fallback`, `text_unavailable` and
`language_unavailable`. Metadata-only or language-unavailable outcomes stay
visible as source states (`needs_review` or `unavailable`); they are not legal
conclusions about applicability, transposition, current force or compatibility.
The retained text is also split into bounded provision summaries (recitals,
articles and annexes) for citation selection without classifying legal duties.

The registry hash for a project ficha is computed from the official ficha URL,
document links and truncation flag. Local retained-version history is exposed in
snapshot summaries but is excluded from that hash, so importing a document does
not by itself make the upstream ficha look changed. The last few snapshot
headers are returned by `GET /api/registru-surse` beside the existing attempt
history.

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

## Changed source impact

`GET /api/registru-surse` and `GET /api/registru-surse?id=src_...` attach an
`impact` object to each row:

- `contract: changed-source-impact-v1`
- `summary`: local counts for affected dossiers, saved runs, manual notes,
  promoted rule drafts, saved proposals and watchlist entries
- `samples`: bounded representative rows for review screens
- `actions`: UI-safe actions such as inspecting the source, opening evidence,
  creating a review note, retrying sync or marking the source reviewed

For Parliament project sources, affected runs reuse the existing saved-run
dependency scanner behind `/api/dosare/afectate-proiect`. Proposals are counted
when they are attached to those affected runs.

For CELEX and Romanian-law sources, impact is conservative: the registry looks
for direct local references in manual notes, rule draft payloads, saved proposal
text and dossier watchlists. It does not claim a complete legal dependency
graph and it does not reconsult official sources.

Rows in `changed`, `needs_review`, `failed` and `rate_limited` remain review
signals. Closing a `changed` or `needs_review` row should happen only after the
user has inspected the affected local artifacts or recorded why they are not
relevant.

## Source-to-tracker workflow acceptance

The local acceptance contract for one registered source is intentionally narrow:

- register or rediscover one public source through `/api/registru-surse`;
- queue or sync that same source without starting a bulk download or release
  rebuild;
- keep the resulting source id, URL, parser version and content hash visible in
  registry responses;
- record normalized legislative tracker events through `/api/tracker-evenimente`
  with the source id/hash copied into the event, so project and dossier timeline
  filters can show the same event;
- allow a dossier manual note saved through `/api/dosare/note` to reference the
  source by URL/hash and let the registry `impact` sample show that note as a
  local dependency.

The current app infers bounded tracker events for supported parliamentary and
e-consultare syncs, and for metadata-first ministry consultation / avize syncs
when the request supplies enough fields, then reports the stored event counts in
the sync response. It still does not create dossier notes from a source change.
Tests therefore assert the concrete API contracts above: registration/sync writes
the source state, tracker writes make events visible by project and dossier, and
manual notes are counted conservatively as direct source references.

## Bounded public tracking replay

`data/public_tracking_snapshot.json` and `scripts.public_tracking` define the
first offline monitoring slice for legislative project tracking. It records a
small, deterministic source bundle with CDEP, Senat, e-consultare and avize
rows, then replays these already-captured facts into the existing source
registry and tracker event store. The bundle covers:

- CDEP/Senat committee assignment and stage-change signals;
- committee report filing;
- institutional opinion/aviz receipt;
- final vote metadata;
- public-consultation open/closed events and deadline changes;
- changed-source alerts that feed `/api/needs-attention`.

This replay is intentionally not a scheduler and not a crawler. It does not
fetch live public sources, download documents, infer legal effects, create
dossier notes automatically or mark findings as current. Its purpose is to prove
that once source adapters produce these normalized rows, the app can route them
through one visible monitoring path: source registry state, project timeline and
needs-attention review queue.

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
