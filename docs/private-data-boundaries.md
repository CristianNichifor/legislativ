# Private data during dataset activation

`scripts.date_personale.prepare_eu(public_db, previous_effective_db, target_db)`
prepares a new effective EU database and returns its absolute `Path`. It does not
switch `active.json`, configure the server, download sources, or move dossiers.

## Parent integration contract

Published generations remain immutable under `ROOT/datasets/<manifest-sha256>/`.
The parent creates private directories with appropriate permissions and passes:

- `state.dosare_db = ROOT/private/dosare.db` (owned by the dossier/browser work).
- `state.documente_db = ROOT/private/initiative.documente.db` for imported
  parliamentary documents. `documente_proiecte.cale_store` uses this explicit
  attribute; its absence retains the legacy path beside `state.initiative`.
  An invalid explicit value fails rather than falling back to the public dataset.
- `state.eu = ROOT/private/eu-generations/<id>/eu.db`, produced by this helper.

### Managed-server handoff (Halley)

The active record carries `private_generation`, a fresh UUID as 32 lowercase hex
characters **per activation**, independent of the public release fingerprint.
The manager validates this identifier and resolves:

```text
ROOT/private/eu-generations/<active.private_generation>/eu.db
```

The server factory uses that exact path on startup/restart. Restart does not
prepare a new DB or fall back to published `eu.db`; a missing recorded private DB
is an error requiring recovery. Reactivation after rollback gets a fresh UUID;
downloading the already-active release is rejected. `prepare_eu` rejects an existing target, including a target
containing recent imports, instead of overwriting it.

The `.previous` record stores only previous public generation/release information.
For rollback, take the public source from `.previous`, the private source from the
**current active record**, and allocate a new `private_generation`. Prepare first;
then publish the new active record with both its public and private identifiers.
The parent owns UUID generation, validation, private directory creation, activation
serialization, active-record persistence, and server lifecycle. The helper API
needs no changes for this layout.

Preparation requires an existing public EU DB and an absent target in an existing
private directory. Pass `None` for the previous DB only on first activation.
A supplied missing previous DB is an error, never permission to discard history.
For legacy migration, pass the old writable EU DB as the previous effective DB.

Stop/quiesce **all** EU writers before preparation and keep them stopped until
the parent has atomically activated the new pointer and switched server state.
The helper's SQLite read transactions provide consistent input reads but cannot
carry forward imports committed after those reads. This includes CLI writers and
other processes; the interactive import lock alone is insufficient. Keep the old
effective DB for recovery. Once imports resume, future activations must use the
latest effective DB, including its new writes. Rolling back to an older private
DB directly would hide subsequent imports.

Rollback uses the same helper: pass the older release as `public_db`, the **latest**
effective private DB as `previous_effective_db`, and a new target generation.
Then activate that newly prepared DB. Never derive the previous private DB solely
from the historical release pointer being restored. This preserves acquisitions
made after the release being rolled back to, including private-only CELEX records.

```python
from scripts.date_personale import prepare_eu

effective = prepare_eu(
    public_db=root / "datasets" / release / "eu.db",
    previous_effective_db=previous_eu,  # None only for first activation
    target_db=root / "private" / "eu-generations" / generation / "eu.db",
)
# Parent atomically activates its pointer and starts the server with eu=effective.
```

Existing parliamentary document stores need a separate parent-controlled migration
to the stable private path before switching the attribute. This change only routes
the explicit path; it does not migrate or create its parent directory.

## Merge rules

1. Copy every previous archived snapshot byte-for-byte, including its original ID.
   Also preserve published archives and archive every valid input current row via
   the existing `instantanee_ue` payload/hash format. This retains legacy current
   observations even when their DB predates the archive table.
2. Copy all previous `eu_achizitii` records unchanged, including failed attempts,
   previous success timestamps, and metadata-only attempts. Ignore published
   acquisition records: downloading a release is not a local official retrieval.
3. For CELEX identifiers recorded in previous `eu_achizitii`, keep the previous
   current text when present and its manifestation set. This rule includes failed
   and metadata-only attempts. If no previous current text exists, published text
   may supply the current row while local metadata and attempt history remain.
4. Otherwise prefer the published current row and manifestation set where supplied.
   A published current act with no manifestations clears stale public metadata.
   Previous-only acts and metadata remain available. Legacy imports without an
   acquisition marker remain archived but do not override a published current row.
5. Rebuild provisions and FTS using `cellar.scrie_provizii_celex` from selected
   current text. Historical observations are accessible through existing snapshot
   APIs, not through current-text search.

`citit_la`, source URLs, content hashes, and original snapshot JSON are never
restamped. Activation does not call `scrie_celex` or record an acquisition attempt.
Snapshot hash/integrity failures and conflicting bytes for the same ID abort the
whole preparation; neither history is silently replaced.

## Bounds and failure behavior

Inputs open with SQLite `mode=ro`, `query_only`, and `trusted_schema=OFF`. Only
fixed, known columns of ordinary source tables are read. Views, virtual tables,
generated columns, and incompatible relevant table layouts are rejected. Source
DDL, triggers, indexes, and FTS contents are never replayed. Optional archive,
manifestation, and acquisition tables may be absent; `eu_acte` is required.
Unrelated tables are not copied: this is an EU schema helper, not a general backup.

Preparation streams rows, with at most 1,000,000 rows per copied table, 8 MB per
row, 4 GB of cumulative copied input values, and a SQLite progress limit per
input connection. Oversized inputs fail without truncation. Limits are constants
in the helper; larger deployments need an explicit reviewed adjustment.

The destination uses only the application's schema. A mode-0600 temporary file
in the target directory is committed, checkpointed out of WAL, and fsynced before
an atomic exclusive hard link publishes it at the requested target. An existing
target is never overwritten. Failed preparation removes temporary DB sidecars;
the parent must activate nothing on failure. The parent owns directory durability,
the atomic active pointer, retention, and cleanup of unactivated generations.

## Verification

`uv run pytest -q tests/test_date_personale.py tests/test_instantanee_ue.py
tests/test_achizitii_ue.py tests/test_documente_proiecte.py`

Fixtures use the real Cellar schema and snapshot/detail APIs, fixed timestamps,
local and published conflicts, legacy archives, repeat activation, writable private
imports, FTS, metadata-only attempts, input byte preservation, incompatible schemas,
size bounds, and failure cleanup. No server or UI changes are required here.
