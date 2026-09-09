# Source inventory: A1 contract

## Parliamentary acquisition workspace

The Matrice tab now has a separate `Surse parlamentare` workspace. Local search
by PL-x or title returns 25 initiatives per page. Opening a row reads only local
metadata, import versions and recorded attempts; it never consults an official
website. Missing imports, inaccessible storage and unknown freshness are distinct.
The latest 100 retained versions are selectable, with explicit truncation.

`Consultă documentele oficiale` explicitly fetches the parliamentary sheet.
Import and update actions reuse the existing allowlisted PDF/DOCX importer, its
size/extraction limits, membership validation and immutable content hashes.
Users can inspect extracted text separately, including OCR-needed/empty states.
An import date is the first retention date for those bytes, not the date of every
successful check. Language remains unknown because this importer does not verify
or record it. Importing does not replace editor text, recalculate analyses, or
change dossier evidence, decisions or context notes.

`GET /api/surse-proiecte` supports `q` (literal substring, max 200 characters),
`offset` (0..100000), or `plx` for detail; `plx` plus `versiune` returns retained
text with ownership validation. The read endpoints use escaped, read-only SQLite
URIs and do not create or migrate stores. List/detail inventory reads have a
bounded query budget. `POST /api/surse-proiecte` accepts `plx` and `operatie`:
`descopera`, `importa` (with `url`), or `actualizeaza` (with `versiune`). Requests
are limited to 16 KB, localhost Host/matching Origin, and no-store responses.
The static browser build explicitly reports acquisition as unavailable.

Explicit actions in this workspace lazily create an `achizitii` table beside
`documente` in `initiative.documente.db`. Each (initiative, action, URL) retains
the latest attempt, bounded error category, previous successful date, and the
selected version for update retries. This is not a full audit log. A failed
attempt never clears the previous successful date or deletes imported versions.
Repeated imports of identical bytes reuse the existing immutable version. A
successful download with OCR-needed text is distinct from a failed request.
Offline discovery is recorded as failed, even when local imports remain readable.
If recording fails after a successful import, the response reports that warning
rather than claiming the import failed. Interrupted processes may leave a stored
version without a recorded attempt; local reload and explicit retry are available.

Attempt tracking starts with this new workspace. Older imports and actions in
the existing comparison UI have no retrospectively invented attempt history.
Only the latest 100 source/action entries are displayed. Search uses SQLite's
literal LIKE matching; Romanian diacritic folding is not provided here.
EU/Cellar and national-corpus acquisition remain on their existing separate paths;
this batch does not add remote EU imports or bulk corpus synchronization.

## Coverage panel (A2)

The Matrice tab loads a global inventory above its filters, independently of the
matrix request. Each source has a summary of availability, its own stored-record
count and any measured HTML/extraction problems. Expand a source for all available
metrics and UTC timestamps. Unknown freshness is always visible; an accessible
database is not labeled complete or current.

Reopening the matrix reuses the report. `Reîncarcă inventarul` explicitly reloads
local database counts, not official websites. `Exportă JSON` downloads the exact
displayed API response, including generation time and limitations. During reload
the old report is cleared and export is disabled; failures allow retry without
interrupting the matrix. The static app displays the local-inventory limitation
and can export that limitation response, not fabricated counts.

The panel does not filter counts with matrix filters or add incompatible
populations into a combined coverage percentage. It does not infer stale/current
status from retrieval dates. Production-data auditing and backup/restore checks
remain separate work.

The local read-only report is available as `GET /api/inventar-surse` and JSON CLI:

```bash
uv run python -m scripts.inventar_surse --corpus corpus.db --initiative initiative.db --eu eu.db
```

The import history path is derived from the initiative path with `.documente.db`.
HTTP callers cannot select database paths. No source fetching, AI calls, migrations,
database creation or data updates are performed. This is a local snapshot of each
database independently, not a transaction across all four databases.

## Contract version 1

- `schema_version`: report contract version, independent of database migrations.
- `generat_la`: report generation time in UTC, not a source synchronization time.
- `mod`: `local_readonly`; static clients return `static` with an explicit limitation
  and no source metrics. They do not scan remote byte-range databases or pretend
  the shipped slice is the complete local corpus.
- `acoperire_juridica`: always `necunoscuta`; this inventory is not legal analysis.
- `surse`: `corpus`, `initiative`, `ue`, `importuri`.
- Source `stare`: `lipsa` (file absent), `inaccesibil` (cannot read SQLite), `partial`
  (one or more queries unavailable), or `disponibil` (all queries ran, even if empty).
- Each metric has `stare` and `valoare`: `masurat` with a measured value including
  zero; `necunoscut` with null for absent/unparseable dates; `indisponibil` with null
  for missing databases/tables/columns or failed/budget-exceeded queries.
- `sqlite_user_version`: SQLite header value, null if unreadable. The current
  databases can report zero; this is not a verified application migration version.
- `actualitate` remains `necunoscuta`; `ultima_sincronizare_completa` remains null.

## Populations and time semantics

Counts of `acte`, source `documente` and `prevederi` have different denominators.
`acte_cu_prevederi` counts existing acts with at least one nonblank provision.
`acte_cu_structura` further requires a locator other than `text`, matching the
existing structural heuristic without certifying parser correctness.

HTML attempts count rows in `surse`. A success means status `ok` with non-null HTML.
Failures are the complement. `documente_fara_sursa_reusita` counts stored source
documents without a successful HTML row; it does not count uncollected official law.
The successful/failed populations can include sources outside the stored document set.

Dates are normalized to UTC by SQLite date functions; invalid dates produce null
when no valid value exists. The source table records the latest attempt per document,
not a full attempt history. Its latest remaining successful row is not necessarily
the most recent successful attempt ever made. Stored-record timestamps and completed
collection pages do not prove a complete synchronization. No stale threshold is invented.

EU provision counts do not certify FTS index integrity; initiative target counts do
not certify full draft availability. Snapshot OCR/extraction states describe imported
files, not all documents on parliamentary pages. Unknown extraction status is counted
separately. No legal-clearance or contradiction count is produced.

## Bounds and verification

Each database has a one-second SQLite lock timeout and a shared query execution
budget of approximately 200 million SQLite VM instructions. Budget exhaustion leaves
metrics unavailable and the source partial. Counts require scans; no raw texts,
private filesystem paths or raw database errors are included in the report.

Tests cover absent versus empty data, old schemas, malformed databases, URI-special
filenames, unchanged database bytes, mixed HTML results, UTC timestamp ordering,
extraction states and static fallback. A2 adds the visual panel and export download.
The deployed-corpus audit, backup/restore exercise and pilot-domain dataset selection
remain separate roadmap work.
