# Persistent local dossiers (B1)

B1 supplies storage and APIs. The save/reopen UI and review decisions are later
batches. Existing transient matrix dossiers are unchanged.

## Store and migration

The store is derived from the configured initiative database: `initiative.db`
becomes `initiative.dosare.db`. It is separate from collected legislation, initiative
metadata and imported document bytes. Static clients reject persistent dossier
operations explicitly. No hosted authentication or multi-user isolation is provided;
this is a local single-user workspace.

First creation initializes schema 1 and the SQLite application ID in one write
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
