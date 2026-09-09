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

Schema 2 added `revizuiri`; schema 3 added evidence-check history and recalculation
links; schema 4 adds reviewer-supplied legal context. Version-1/2/3 stores remain
readable without migration; absent history is
shown as uncaptured, never backfilled. The next explicit dossier/review write upgrades them
transactionally; failed writes roll back the migration. Backup before upgrading;
older application code rejects schema 4. Reviews belong to a saved run and never
transfer automatically to a different run, even with similar evidence.

Unsaved review text is retained while filtering or reloading reviews within the
same displayed run. It is not persisted until the decision is saved. Errors permit
retry; source-change invalidation and cross-run review carryover remain Phase C work.

## Interface (B2)

The saved-run workspace presents a searchable finding list and one active finding,
with readable saved evidence, legal context and decision controls together. Full
report/provenance and check history are collapsible, rather than repeated above every
finding. Current-local-text buttons explicitly query the current corpus; saved evidence
remains unchanged. Opening the workspace does not run a new source check.

Within the browser session, each run retains its search, filter, preferred finding,
selected historical check and check-section state. Filtering can temporarily hide the
preferred finding; clearing the filter restores it unless another finding was selected.
No workspace state or unsaved notes are written to browser persistent storage. Reloading
the entire page still loses unsaved work; saved records remain in SQLite.

Review and legal-context drafts survive finding changes and review reloads. A drafts
button returns to an unsaved finding even when filters hide it. Explicit cancel buttons
discard the corresponding draft; dossier/run selectors and queues block navigation while
drafts remain. Review retries retain their request identity and original revision across
finding changes/reloads, so stale drafts cannot silently overwrite another revision.
Failed run/history loads expose retry controls. Exports still contain all retained
findings and the selected check, not just the currently displayed finding.

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

First creation initializes schema 4 and the SQLite application ID in one write
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

## Evidence Dependencies

New runs use the `matrice-dosar-v2` contract and store a version-1 dependency
manifest at `dovezi.manifest`. Each retained gap, CCR example or contradiction
candidate links its existing finding ID to deduplicated corpus dependencies.
Contradictions retain both sides. Only exact `act_id` matches are used; an absent
locator means an act-level dependency, never a guessed article. Repeated locators
include every matching provision ordered by `ord`.

Captured dependencies contain source URL, portal IDs, collection timestamp,
provision count and `sha256_continut`. The `sha256-json-prevederi-v1` algorithm
hashes the UTF-8 encoding of canonical JSON (sorted keys, compact separators,
unescaped Unicode) for the ordered list of `locator`, `ord`, `text`,
`vigoare_de_la` and `vigoare_pana_la` records. This fingerprints parsed corpus
content, not official document bytes. Source metadata is kept separately from
that fingerprint. Full source text is not archived in the manifest.

Missing references, missing acts/provisions, unavailable sources and limits are
explicit states without a content hash. Reads are local, read-only and use one
SQLite snapshot without migrations or network access. Capture is limited to
2,000 provisions and 2 MB of canonical provision content per dependency; exceeding
either limit emits no partial fingerprint. The 4 MB saved-payload limit also
includes the manifest and retained evidence.

The report and dependency capture are separate reads. The manifest therefore
records the corpus observed at save time, not a certified snapshot of the source
used earlier by every detector. It does not establish current legal applicability
or freshness. EU references and CCR decision documents are not source dependencies.
Parliamentary snapshots use the separate contract below. Aggregate counts without retained
examples also have no finding dependencies.

The v2 run hash covers canonical `{engine_version, filtre, raport, dovezi}`.
Unchanged content deduplicates; a changed dependency or source metadata produces a
new run even when the report is unchanged. There is no per-capture clock value in
the hash; the run's existing `creat_la` records save time. Older v1 runs retain
their original hash contract and are never backfilled from current sources.
Review JSON and Markdown exports include the manifest; legacy Markdown explicitly
states that it was not captured. No review decisions are changed or transferred.
No database migration or new endpoint is required. Changed-evidence comparisons
and re-review queues are described below.

## Local Evidence Rechecks

`GET /api/dosare/dovezi?id=<dossier>&rulare_id=<run>` explicitly compares a saved
manifest with the current local corpus. It shares the dossier API's local-only
Host/Origin checks and no-store responses; static deployments reject it. It does
not fetch official sources, write to the dossier database or change review events.

The response contains `verificat_la`, per-dependency saved/current fingerprints
and source metadata, per-finding status, and counts. Status is `schimbat` only when
two compatible captured content hashes differ. Metadata-only changes are reported
separately. `neschimbat` means equal captured content, not up-to-date legislation
or a legal validity assessment. Missing current sources, uncaptured baselines,
unsupported manifest/hash versions and exceeded capture limits are `indisponibil`,
never unchanged or presumed repealed. A finding with both changed and unavailable
dependencies remains changed and also has `comparatie_incompleta=true`.

In the saved-run review panel, **Verifica si salveaza dovezile** runs and saves a check on demand.
The filter offers changed-evidence and unavailable-comparison queues for the
selected run, independently of human review status. Dependency details retain
both fingerprints. The old report remains visible, but full historical source
text is not archived and no reconstructed full-text diff is claimed. Check results
and their timestamp are included in the UI's JSON/Markdown exports. The panel loads
saved history, not current source data, when opened. Rechecking after source
collection remains an explicit user action. The original GET comparison endpoint
is still read-only and does not itself save results.

**Recalculeaza pentru reevaluare** runs the saved filters against current data and
opens the resulting saved run. If content is identical, deduplication preserves
the existing run and its decisions. Otherwise the new run starts unreviewed and
requires explicit reviewer decisions; earlier decisions remain historical. Unsaved
notes block this action's navigation, including notes entered while recalculation is in flight.
No acknowledgement on an old run dismisses its evidence-change warning.

The manifest's scope and separate-read limitations still apply. EU documents and
CCR decision documents are not compared here.

## Parliamentary Snapshot Dependencies

The draft comparison form can now save comparisons when **both** inputs are
selected imported versions. Edited/pasted text remains usable for transient
comparison but is not represented as an immutable official snapshot. Saving
recomputes the report server-side from the selected imports; clients cannot submit
a report, text or source hash for storage through this API.

`POST /api/dosare/rulari` accepts optional `proiecte` with exactly `a` and `b`,
each containing `plx_id` and `versiune_id`. The initiatives must differ, own their
snapshots, and pass the existing active-initiative/filter checks. Both snapshots
must have extracted text and pass byte-hash and content-addressed-ID validation.
Draft runs use `matrice-proiecte-v1` and retain `raport.selectie_proiecte`.
Original snapshot IDs appear in candidate evidence, so human review applies to
the specific retained versions rather than a moving draft.

Draft findings (`proiect`) are included in the existing review workflow. Each
retained conflict links both imported snapshots and the corpus provisions targeted
by its two amendment operations. Repeated dependencies are deduplicated. Manifest
schema 2 adds `proiect_importat` dependencies alongside corpus records; ordinary
corpus runs retain manifest schema 1. The target law's locator is not interpreted
as an article locator inside the draft: draft dependencies are whole-document.

Checks read the local `.documente.db` store without discovery, downloads, extraction
or migrations. They compare against the newest distinct stored import with the
**same initiative and exact URL**. A different attachment URL is never substituted.
Tied latest import timestamps are ambiguous and unavailable. Reimporting identical
bytes does not refresh the old snapshot timestamp in the existing import store;
therefore this is not a current official-source observation or a reliable signal
of a source reverting to earlier bytes.

`sha256_octeti` fingerprints original bytes; `sha256_continut` uses SHA-256 over
the exact UTF-8 extracted text (`sha256-text-import-v1`). Checks expose separate
`octeti_schimbati` and `text_schimbat` flags. A byte-only change is still flagged
for review but is not called a textual change. OCR/empty extraction, missing files,
integrity mismatches, ambiguous ordering or limits produce unavailable comparisons,
not compatibility or unchanged findings. Bounds follow the importer byte limit
and cap extracted text at 2 MB per dependency. The report comparator also retains
its stricter 60,000-character input limit.

The saved finding's version button opens the existing imported-version diff tool.
Its text diff has its own whitespace/heading normalization and limits, while the
dependency fingerprint is exact text. Checking the official URL remains a separate
explicit action in that tool; it never replaces the historical report. Check JSON
and Markdown exports and the cross-dossier queue include draft dependencies.

Recalculation from a draft run explicitly selects the latest comparable local
imports at the same URLs, pins their IDs in the resulting run, and records the
existing recalculation link. It fails on unavailable extraction; it does not fetch
sources or overwrite draft input. Existing reports and review decisions remain
unchanged. Directly choosing another attachment requires a new explicit comparison.

Parliamentary dependencies required no migration beyond schema 3; the current store
version is 4 for legal context. Back up both the dossier
database and the imported-document database using SQLite's backup mechanism.
The dossier backup alone preserves reports/checks/links but cannot restore original
snapshot bytes or full imported text. Missing restored imports remain unavailable.
EU dependencies and automatic legal-compliance conclusions are outside this batch.

## Persistent Check History and Queue

`POST /api/dosare/verificari` accepts exactly `id` (32-character retry UUID),
`dosar_id` and `rulare_id`. Results are generated server-side, bounded to 4 MB,
and saved as append-only events in `verificari_dovezi`. Reusing a successful ID
for the same run returns the original check without rereading sources, even after
sources change; a different run is rejected. Concurrent retries insert only one
event. Each deliberate new check uses a fresh ID. The queue's latest event is
defined by database insertion sequence, not client clocks or UUID ordering.

`GET /api/dosare/verificari?id=<dossier>&rulare_id=<run>&offset=0` returns 20 check
summaries, total count, and the latest full result as `selectata`. Supplying
`verificare_id` retrieves that historical result after validating run ownership.
The UI history picker and paging controls expose older checks without overwriting
the current source manifest. Exports include the selected check ID and timestamp,
not the entire check history; the database backup preserves all events.

`GET /api/dosare/coada?stare=toate&offset=0` returns 50 runs across all local
dossiers with their latest saved check and title. Supported filters are `toate`,
`schimbat`, `indisponibil`, `neverificat` and `neschimbat`. Changed and incomplete
comparisons can overlap; runs with no comparable findings are not classified as
unchanged. The queue performs no source scans and does not imply present freshness.
Old runs remain visible even after recalculation. Open a run from the queue to
perform a new check or review. No scheduled or bulk-source checking is introduced.

`POST /api/dosare/rulari` also accepts optional `sursa_rulare_id`. It must belong
to the same dossier and have identical filters. An append-only `recalculari` row
links the source and resulting run in the same transaction as the run save.
Repeated identical links deduplicate; identical self-recalculations add no link.
Run content and hashes remain unchanged. Recalculation can rediscover an existing
historical run, so these are operation links, not a guaranteed acyclic ancestry
graph, and existing decisions on a deduplicated run are retained. Check history
returns up to 100 incoming links with an explicit truncation flag; UI and exports
include them. Backup preserves every link.

Schema-3 tables have no-update/no-delete triggers. They prevent accidental changes
through ordinary SQL, not tampering by the local database owner. Reads never
migrate version-1/2 stores. New writes migrate atomically; failed migrations roll
back. Back up before upgrading because older application versions reject schema 4.
New routes retain local Host/Origin guards, no-store responses and static-mode
rejection. Stores and backups remain private, unencrypted local research data.

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
## Context juridic declarat

Constatările salvate pot avea context juridic declarat de evaluator. Pentru comparații,
contextul este separat pentru țintele A și B din dovada salvată; pentru celelalte constatări se
referă la constatarea individuală. Nu este un registru global de clasificare a actelor.

Fiecare câmp are o valoare și o citare textuală (act și prevedere): începutul/sfârșitul
aplicabilității, teritoriul, destinatarii, excepțiile, dispozițiile tranzitorii și clasificarea
organică/ordinară/altă clasificare. Valoarea și citarea goale înseamnă **necunoscut**, nu lipsa
unei excepții sau aplicabilitate nelimitată. Valorile completate necesită citare; nu sunt
deduse din titlu, domeniu, model AI sau rangul euristic. Datele trebuie să fie ISO YYYY-MM-DD,
iar un interval complet trebuie să fie ordonat. Nu se calculează efecte juridice din aceste date.

Citările sunt furnizate de evaluator și **nu sunt verificate sau descărcate automat**. Nu
constituie o nouă arhivă de surse, nu sunt dependente urmărite automat și nu certifică încadrarea
juridică. Evaluatorul este o etichetă declarată, nu o identitate autentificată. Pentru corectarea
unei afirmații se salvează o nouă revizie, inclusiv revenirea explicită la necunoscut.

Salvarea cere evaluator și motivarea reviziei. Contextul are istoric append-only, control optimist
al concurenței și cheie de retry, independente de deciziile asupra constatărilor. Contextul nu
modifică detectorii, rezultatul analizei, deciziile sau cozile de verificare și nu se transferă
automat la alte rulări. Notele de context nesalvate sunt păstrate la filtrare/reîncărcare și
blochează navigarea din cozi și recalcularea, la fel ca notele de revizuire. După un conflict,
reîncărcarea păstrează textul nesalvat; renunțarea explicită permite pornirea de la noua revizie.

Schema dosarelor este acum **4**. Citirea schemelor 1–3 nu migrează baza; următoarea scriere o
actualizează tranzacțional. Tabelul `contexte_juridice` este inclus în backup-ul SQLite al dosarelor.
Trigger-ele append-only nu protejează împotriva proprietarului local al bazei de date.

`GET /api/dosare/context` citește istoricul unei ținte, în pagini de 20; `POST` adaugă o revizie.
Se aplică aceleași restricții locale Host/Origin, cache `no-store` și limita de 16 KB pe cerere.
Valorile au maximum 500 de caractere, citările 300, evaluatorul 120 și motivarea 2.000; limita de
octeți a cererii se aplică separat. Interfața încarcă editorul la cerere, lângă dovezile constatării.
Exporturile revizuirii includ contextul curent și ultimele 20 de revizii per țintă, cu marcarea
trunchierii; istoricul complet rămâne în bază și poate fi parcurs prin API. Varianta statică nu
oferă scriere sau stocare de context juridic.
