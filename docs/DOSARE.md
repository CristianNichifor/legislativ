# Persistent local dossiers (B1)

B1 supplies storage and APIs; B2 adds the save/reopen UI; B3 adds review decisions
and append-only history for findings retained in a saved run.

## Review decisions (B3)

Saved gap/CCR examples and contradiction candidates receive deterministic finding
IDs from their category and canonical saved evidence. Duplicate identical evidence
within a category is one reviewable finding. Aggregate counts without retained
examples are not fabricated into findings. The report itself remains unchanged.

Each finding starts `unreviewed`. A reviewer may record `needs_evidence`,
`confirmed_by_reviewer`, `dismissed` or return it to `unreviewed`. Every event requires
a declared reviewer label (120 characters) and a reason/note (2000 characters).
Confirmation is a human assessment, not an official legal determination. Labels
are not authenticated identities, and a local database is not a tamper-proof audit log.

`GET /api/dosare/revizuiri?id=<dossier>&rulare_id=<run>` returns findings, latest
states/revisions, recent history, limitations, the original saved run and Markdown.
UI filters include unresolved (`unreviewed` and `needs_evidence`). JSON/Markdown
exports include all findings regardless of the UI filter, original evidence and
report hash. Each finding's newest 20 events are included; `istoric_trunchiat` and
the Markdown warning explicitly mark truncated history. All events remain stored.
The history UI loads older pages through the same GET route with `constatare_id`
and `offset` (20 per page). This is a bounded export, not an assertion of complete
history when the flag is present. Backups retain all events.

`POST /api/dosare/revizuiri` accepts exactly `id` (32-character retry UUID),
`dosar_id`, `rulare_id`, `constatare_id`, `revizie` (expected current revision),
`stare`, `evaluator` and `motiv`. Run ownership and finding membership are checked
against stored evidence, not a client-provided finding. Concurrent stale edits fail
with a reload instruction; exact retries reuse their event. Events are inserted in
a write transaction, and UPDATE/DELETE triggers reject modification of old events.
An authorized local database owner can still bypass these controls by changing the
database schema; this is not cryptographic immutability.

Schema 2 adds `revizuiri`. Version-1 stores remain readable without migration and
show no review events. The next explicit dossier/review write upgrades them
transactionally; failed writes roll back the migration. Backup before upgrading;
older application code rejects schema 2. Reviews belong to a saved run and never
transfer automatically to a different run, even with similar evidence.

Unsaved review text is retained while filtering or reloading reviews within the
same displayed run. It is not persisted until the decision is saved. Errors permit
retry; source-change invalidation and cross-run review carryover remain Phase C work.

## Interface (B2)

The matrix tab's `Dosare salvate` section supports creating a dossier with a title,
research question and declared domain, browsing 50 dossiers per page and selecting
a saved analysis. Selecting a dossier keeps it as the save destination while
browsing another page. No metadata or report is kept in browser localStorage.

Open a matrix row's working dossier and use `Recalculează și salvează în dosarul
ales` to persist a fresh server-generated report. A destination must be selected
first. The button does not imply that the previously displayed transient report
is saved verbatim. Identical reports reuse the existing run. Failed dossier creation
retains its retry ID while the form contents are unchanged.

Reopened reports are labeled historical and show saved time, detector contract
version and report SHA-256. Copy includes the saved timestamp/hash and Markdown.
Provision buttons are labeled `Text curent`: they open current corpus evidence,
not an archived historical provision. The saved report itself is not recalculated.
Run lists retain B1's latest-100 limit and partial-list warning.

Stale run/dossier responses are ignored after selection changes. Failed requests
show an error; the library can be reloaded. Static clients display the local-only
limitation and do not expose the creation form. This is a single-user local
workspace, not a shared review or authenticated collaboration feature.

## Store and migration

The store is derived from the configured initiative database: `initiative.db`
becomes `initiative.dosare.db`. It is separate from collected legislation, initiative
metadata and imported document bytes. Static clients reject persistent dossier
operations explicitly. No hosted authentication or multi-user isolation is provided;
this is a local single-user workspace.

First creation initializes schema 2 and the SQLite application ID in one write
transaction. Reads do not create or migrate files. An unrelated nonempty database
or incompatible application/schema version is rejected, not reset. A failure during
initialization rolls back tables and version markers together. Future migrations
must preserve this transaction boundary and have prior-version tests.

Tables:

- `dosare`: caller-generated stable ID, title, research question, user-supplied
  domain label, optional analysis date and creation time.
- `rulari`: generated ID, owning dossier, creation time, detector contract version,
  filters, full generated report, evidence manifest and content hash.

Domain and analysis date are research metadata, not verified classifications or
instructions to reconstruct the historical corpus. Stored reports preserve their
existing coverage limits, candidate status and Markdown. No legal conclusion is
introduced by saving them.

## API

Requests use the local server's `localhost:<port>` or `127.0.0.1:<port>` Host.
Cross-origin browser requests and unexpected Hosts are rejected for these routes.
Responses use `Cache-Control: no-store`. This is not an authentication system and
does not protect against other programs running as the same local user.

`POST /api/dosare` creates a dossier:

```json
{
  "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "titlu": "Research question",
  "intrebare": "Which provisions require further review?",
  "domeniu": "Pilot domain",
  "data_analizei": "2026-09-09"
}
```

Clients generate a random UUID encoded as 32 lowercase hexadecimal characters.
The example ID is illustrative. Repeating the same ID and normalized content returns
the original dossier. Reusing it with different content fails rather than overwrites.
The title is required (200 characters); question is limited to 4000 characters and
domain to 200. The date is optional. Unknown fields are rejected.

- `GET /api/dosare?offset=0`: newest 50 dossiers, total and offset. Missing store
  returns an empty list without creating files.
- `GET /api/dosare?id=<id>`: dossier metadata; unknown IDs fail.
- `POST /api/dosare/rulari`: generate and save a current matrix report.
- `GET /api/dosare/rulari?id=<dossier-id>`: latest 100 run summaries with total and
  explicit `trunchiat` if more exist. Older runs remain readable by their saved IDs.
- `GET /api/dosare/rulari?id=<dossier-id>&rulare_id=<run-id>`: complete saved run.
  A run from another dossier is rejected even if its ID is known.

Save-run request:

```json
{
  "dosar_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "filtre": {"emitent": "Parlamentul", "tip": "lege"}
}
```

Allowed filters: `emitent` (required), `tip`, `rang`, `domeniu`, `problema`, at most
300 characters each. The server calls the existing matrix dossier service; callers
cannot provide a report, evidence or hashes. Saving recalculates from currently
available data, not necessarily the report previously visible in a browser. The B2
UI must make that behavior clear rather than silently promising an old snapshot.

Identical filters, detector contract version and report content reuse a run within
the same dossier. Changed content creates a new run and never mutates the previous
one. `engine_version=matrice-dosar-v1` is a manually versioned detector contract,
not a Git commit or model ID; increment it when changing the saved report semantics.

The SHA-256 covers canonical JSON of filters, engine version and report. It is not
a signature, a hash of original official bytes or a guarantee of historical source
availability. The evidence manifest preserves act references, EU references and
candidate provision evidence returned by the report. Full official document
version linkage and source-change re-review remain Phase C work.

POST bodies are capped at 16000 bytes; serialized report payloads at 4 MB. Reports
over the limit fail without truncating saved evidence. Existing detector limits
still apply. Dossier writes use a five-second SQLite lock timeout and atomic
transactions; invalid references fail before inserting a run. Errors use 400 for
invalid input/incompatible schema and 503 for unavailable storage, without raw
filesystem/database diagnostics in HTTP responses.

## Backup and restore

```bash
uv run python -m scripts.dosare --db initiative.dosare.db --backup research-backup.db
```

This uses SQLite's backup API, including committed WAL data, not a raw copy of a
potentially active database file. The destination must not exist; it is created
exclusively. Failed backup creation removes only the newly created destination.
Protect backups as private research data. Files are not encrypted by this module;
new stores and backups are created with owner-only permissions (0600 on POSIX).
Existing file permissions are not changed; disk encryption and access to the
parent directory remain deployment responsibilities.

To restore, stop application processes, preserve the current store and any SQLite
sidecars, and restore into an unused location first. Verify dossier IDs, run counts,
hashes and saved evidence through the read APIs before switching the configured
initiative path to the matching restored `.dosare.db` path. Do not overwrite a
running store or leave old WAL sidecars next to a replaced main database. No HTTP
backup/restore endpoint or automatic destructive replacement is provided.

The tests restore a backup into a fresh database and verify metadata plus complete
saved run/evidence equality. They also cover concurrent duplicate creation, schema
rollback, incompatible schemas, bounds, ownership and HTTP origin/Host checks.
