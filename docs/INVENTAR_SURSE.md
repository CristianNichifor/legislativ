# Source inventory: A1 contract

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
extraction states and static fallback. This batch adds the contract and export;
the visual freshness panel, deployed-corpus audit, backup/restore exercise and
pilot-domain dataset selection remain separate roadmap work.
