# Dataset publication contract v1

`dataset-release.json` describes a curated, immutable public release. It is separate
from the existing `manifest.json`, which contains corpus counts. No release or channel
is made available merely by adding this contract to the repository.

```json
{
  "schema_version": 1,
  "release": "2026-09-10",
  "created_at": "2026-09-10T12:00:00Z",
  "app_contract": 1,
  "files": [
    {"name": "corpus.db", "bytes": 4096, "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
  ]
}
```

The digest above is illustrative, not an available release. Exact fields and types
are required; no coercion of strings, floats or booleans to integers. Versions must
equal integer 1. Unknown fields, duplicate JSON keys, duplicate filenames, empty
files and missing `corpus.db` are errors. JSON is UTF-8, at most 256 KiB.

Release IDs are real calendar dates `YYYY-MM-DD`, optionally followed by a hyphen
and 1-64 ASCII characters matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. Timestamps
are valid UTC `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` (1-6 fractional digits when present).
Digests are exactly 64 lowercase hexadecimal characters, over the complete raw file.

Allowed payload names:

- Required: `corpus.db`.
- Optional databases: `initiative.db`, `graf.db`, `eu.db`; each database <= 1 TiB.
- Optional index: `index.json`, <= 256 MiB (the existing slim index is about 16.8 MB,
  and the full index about 91 MB; see `scripts/shard.py`).
- Optional reports: `termeni.json`, `manifest.json`, `vid.json`,
  `neconstitutional.json`, `norme_lovite.json`, `considerente.json`, `parlament.json`,
  `ue_acoperire.json`; each report <= 4 MiB.

There are at most 13 entries. All payloads are uncompressed full files; there are no
deltas in v1. Filenames are single allowlisted basenames relative to the immutable
manifest's folder, with no per-file URLs. Serve raw bytes without content transformation
and support HTTP Range for resumable downloads and SQLite reads. Resume must still
end with verification of the complete byte count and SHA-256.

## Consumer API and trust

`scripts.dataset_release.validate(manifest)` (also `validate_manifest`) returns the
validated dictionary without type coercion. `load_manifest(raw_bytes_or_text)` adds
bounded JSON parsing and duplicate-key rejection. Errors are `ReleaseError`, a
`ValueError` subclass. `validate_channel(channel, trusted_origin=...)` and
`load_channel(raw, trusted_origin=...)` handle channel pointers; the default origin
is `https://date.cristian-nichifor.com`. The schema is `schema/dataset_release.schema.json`,
with channel shape in `$defs/channel`. Runtime validation additionally enforces real
calendar dates, filename uniqueness, strict Python integer types and byte limits.

The configured trusted channel URL is `https://date.cristian-nichifor.com/channel.json`:

```json
{
  "schema_version": 1,
  "manifest": "https://date.cristian-nichifor.com/2026-09-10/dataset-release.json",
  "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

The channel is a separate small pointer, never a manifest at `/latest/`: resolving
relative payloads beside such a mutable path would select the wrong release. Its hash
covers the exact manifest bytes, including whitespace and trailing newline. Consumers
must enforce their configured trusted origin, reject redirects, userinfo, queries,
fragments and traversal, verify the manifest hash before using it, and require the
manifest release to match the URL's release segment. A loopback HTTP exception belongs
only to an explicit consumer CLI testing flag, never the production publisher.
SHA-256 supplies integrity; trust comes from the configured HTTPS channel, not a
self-signed digest. First run must not automatically access the network. An explicitly
requested channel that is not yet published must produce an honest availability error.

## Build and verify locally

Stop writers and curate a dedicated folder containing only allowed public payloads.
The builder rejects unknown files, directories, symlinks, SQLite WAL/SHM/journal
sidecars, WAL-mode database headers, invalid databases and private/build-time SQLite
objects containing `private`, `dossier`, `dosar`, `documente` or `eu_achizitii`.
The presence of `eu_achizitii` marks a managed private EU generation, even when
empty: its personal acquisition-attempt metadata is not public. Passing such a
database as `--published-eu` fails before copying it or writing a release manifest.
Public law-text history such as `eu_instantanee` remains permitted. This is a guardrail,
not a general privacy classifier: the operator must curate report contents and DBs.
Do not rename a collector or private database into the allowlist.

```bash
uv run python -m scripts.dataset_release build /tmp/release-2026-09-10 \
  --release 2026-09-10 --published-corpus /path/to/publicat.db
uv run python -m scripts.dataset_release verify /tmp/release-2026-09-10
uv run python -m scripts.dataset_release channel /tmp/release-2026-09-10 \
  --manifest-url https://date.cristian-nichifor.com/2026-09-10/dataset-release.json \
  --output /tmp/channel-proposal.json
```

Before uploading or promoting the channel, run the real-data local-runtime
acceptance against the prepared folder. Use a filesystem with enough free space for
another copy of the release:

```bash
uv run python -m scripts.acceptare_date_reale /tmp/release-2026-09-10
```

The runner prints download progress, activates the release through `/api/date`,
runs a real search, creates and updates a private dossier, rolls back to a prior
release and confirms the private dossier survived. It uses a file-backed HTTPS
transport, so it does not publish or upload anything.

The optional `--published-corpus` copies a regular, standalone `publicat.db` to
`corpus.db`, never mutating its source. Alternatively curate `corpus.db` directly.
Files are hashed in 1 MiB chunks. Existing manifests and output proposals are not
overwritten. Failed builds may leave a partial staging folder; start a fresh folder.
Freeze staging files throughout building, verification and uploading.

`--published-eu /path/to/curated-eu.db` explicitly copies a public standalone EU
database to `eu.db`. The source is checked for WAL/sidecars and private objects
before copying; it is never checkpointed, mutated or discovered automatically.
`--public-reports /path/to/curated-reports` copies only allowlisted report filenames
(including `ue_acoperire.json`). It rejects private/unknown files, directories,
symlinks and collisions with already staged files. Keep this directory limited to
additional public reports; generated `index.json`, `termeni.json` and `manifest.json`
are already staged by the shell publisher. `termeni.json` remains bounded at 4 MiB;
the existing generator selects at most 800 definitions, and oversize output fails
explicitly rather than being silently omitted.

## Publisher sequence

`infra/republica.sh [--latest]` creates fresh public copies and staging files per run.
It validates the prefix, builds the sidecar, and refuses an occupied remote prefix or
a failed prefix listing. Run only one publisher for a given release ID: the listing
is not a distributed lock. Failed partial uploads require a new release suffix.
Set optional `EU_PUBLIC_DB` and `PUBLIC_REPORTS_DIR` to pass the explicitly curated
EU database and additional public reports into this sequence. An ordinary `eu.db`
in the collector workspace is never implicitly selected.

1. Upload listed payloads to a new immutable `<release>/` prefix.
2. Upload legacy browser search assets (outside this consumer contract).
3. Download-check uploaded payload bytes and reverify the local manifest.
4. Upload `dataset-release.json` last with overwrite protection, then download-check it.
5. Generate a local `channel.json` proposal. Only explicit `--latest` publishes it
   to the bucket root, after all verification succeeds.

The production app configuration is never edited. No channel is automatically advanced
by a normal run. The CLI's local `channel` command does not verify remote availability;
manual promotion must follow the same remote verification sequence. Configure short
cache lifetime for `/channel.json`, immutable caching for release paths, and preserve
older releases. Browser search shards are not local-first payloads and are not covered
by this sidecar. No live R2 writes are needed to test this implementation.

## Local update panel

`app/dataset-updates.js` mounts in `#dataset-updates` above the workspace tabs. The
browser build must copy this asset beside `index.html`; the local server must serve
it there. Asset routing and build integration are maintained by their respective
owners, outside this change.

Startup and periodic polling only GET the local `/api/date` status. Unsupported
endpoints and non-local modes hide the panel. Checking the trusted channel is an
explicit POST action. Download confirmation shows the offered version and total
size. Only `download` and `activate` POST `{action, sha256}` to pin the offer;
`check`, `cancel` and `rollback` POST exactly `{action}`. The UI never sends editor
or private workspace contents.

Ready downloads require explicit activation. Activation, rollback and the separate
reload button honor the app's existing cancellable `beforeunload` draft guards.
No automatic reload occurs. Transfer failures leave the current version visible;
the server remains responsible for preserving the active release and validating
all state transitions. The panel is separate from browser workspace storage UI.
Activation and rollback have no client deadline: full corpus verification and EU
merging may take minutes. A spinner marks the pending mutation, update controls
are disabled, and the surrounding workspace is temporarily inert to prevent edits.
No status polling runs until that request settles. A lost mutation response is
treated as uncertain, never as proof that the installed release was preserved;
only a subsequent successful local status read unlocks the workspace. This read
also has no deadline while reconciling a mutation. Failed mutations are never
automatically retried.

Offline browser checks (desktop and mobile, mocked HTTP only):

```bash
PLAYWRIGHT_MODULE=/path/to/node_modules/playwright node tests/dataset_updates_browser.cjs
```

The same fixture is available through `tests/test_dataset_updates_ui.py` when
`PLAYWRIGHT_MODULE` is set. It covers empty state, explicit requests, confirmation,
hash pinning, progress/cancel, draft guards, activation without reload, rollback,
disk errors, escaped server text and unsupported endpoints.
