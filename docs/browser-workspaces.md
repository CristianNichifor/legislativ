# Browser workspaces

The static build runs the existing Pyodide Python/SQLite engines. Dossiers use
schema 9 in `/workspace/dosare.db`, explicitly assigned through trusted runtime
`Stare.dosare_db`. `dosare.cale` checks this attribute first. `date_dir` continues
to identify public corpus reports/shards; it is never cleared to enable writes.
The parent can assign its managed private path through the same attribute.

## Persistence and recovery

`app/browser-workspace.js` stores the complete private SQLite file in IndexedDB
`legislativ-private-workspace-v1`, separately from replaceable public caches.
Every dossier request takes a same-origin Web Lock and reloads the committed
snapshot. SQLite service connections close before the snapshot is read. A
strict-durability IndexedDB transaction atomically commits the current snapshot
and up to three previous distinct snapshots. Only transaction completion permits
a successful write response. Failure restores the previous worker file and
returns an error; it neither acknowledges the write nor rotates backups.

Worker requests are serialized, including async search, to prevent reentry while
SQLite/FS state is being replaced. Across tabs, stale revisions are rejected by
the existing service validators. Tabs do not push live UI updates to each other;
refresh the dossier list/metadata to see another tab's changes.

The browser-only controls under saved dossiers export a standalone SQLite backup,
export an older snapshot, import a backup, restore a retained snapshot, or request
persistent browser storage. Import checks the dossier application/schema IDs,
SQLite integrity and foreign keys in a separate candidate file, migrates supported
older schemas using the existing migrations, and converts WAL mode to a standalone
file. The replaced current snapshot remains in backup history. Import/recovery
can replace an unreadable current snapshot without first opening it. Exported
files contain private research; there is no upload endpoint or account. Import
also compares schema objects against the canonical dossier schema before and
after migration; imported DDL is not executed. Import and restore check the
existing draft/inflight guard before replacing state, including after reading an
import file. A cancelled guard leaves the database and backup history unchanged.
Snapshot status and backup export are independent of public-source and Python
boot: the main thread reads IndexedDB under the same private Web Lock. Import and
restore still require the runtime to boot successfully.

HTTPS or localhost, IndexedDB, Web Locks and Web Crypto are required. Unsupported
browsers fail dossier operations explicitly. Browser persistence is not immunity
to eviction, private-mode cleanup, user deletion or device loss. Keep exported
backups elsewhere. A request for persistent storage can be denied. Snapshots are
whole-file copies with a 128 MiB limit; peak memory and storage use can be several
times the file size. This is intended for research workspaces, not corpus storage.

## Public data boundary

The publisher owns the shared `dataset-release.json` and channel contract.
Browser selection uses that contract, with no competing manifest; see
[Browser online generations](browser-online-generations.md). Legacy unversioned OPFS
corpus files are never mounted: they cannot prove membership in the selected
remote generation. A required corpus failure causes an explicit boot failure.
The legacy pinned release tolerates missing optional databases and historical
catalogs, with unavailable coverage explicitly reported. Other build reports are
not mounted alongside that remote release. Selected manifest releases use only
declared assets from the same manifest folder; declared but broken assets fail
validation instead of silently falling back to a different generation.
Future verified caches must be keyed to the parent's release identity and hashes.
Shell cache cleanup is restricted to `legislativ-shell-*`; it does not delete
other same-origin caches belonging to the parent's public dataset manager.
The shell identity includes the Python bundle, worker, page, browser scripts,
fonts, Pagefind client and public catalogs. Runtime-only deployments therefore
retire old cached Python bundles too. Hashing streams these assets, excludes the
monolithic corpus and private files, and ignores the generated manifest version.
The worker fetches `bundle.zip?v=<SHA-256>` and precache uses the identical URL.
An old active service worker cannot match its unqualified or older bundle entry
to this request while a new shell is still installing. There is no retry through
an unqualified bundle URL. Unit fixtures without a bundle use an empty tag.

Fixture/slice builds load their existing corpus file only when it is at most
32 MiB; this enables matrix dossier analysis over that slice. Larger published
datasets continue through remote range reads. The slice does not establish full
corpus coverage. No full 9 GB offline download is promised. Browser selection
retains only metadata and small verified reports, not offline database packages.

The build copies `app/dataset-updates.js` when that parent-owned file exists.
Its controls must hide when their API is unavailable in the static runtime.
Local source acquisition remains explicitly unsupported in the browser. Retained
proposal/review/analysis/context/EU evidence remains readable without reacquiring
sources; new source-dependent analyses/previews retain the engines' missing-source
limitations. Public runtime assets are downloaded on first boot; this is not a
fully offline installation package.

## Verification

Build with `uv run python -m scripts.construieste_web --sursa fixturi`, then serve
`web/` on localhost. Run `tests/browser_workspace.cjs` with `PLAYWRIGHT_MODULE`
pointing to Playwright, optional `CHROMIUM_PATH`, and `BROWSER_BASE_URL` pointing
to that static server (default `http://127.0.0.1:8057`). No application backend is
used. The test uses real Pyodide/SQLite/IndexedDB at desktop and mobile widths,
injects an IndexedDB transaction abort after SQLite execution, exercises concurrent
stale revisions, reloads, retention, import/export/restore, and verifies that no
research network writes occur. It also imports native schema 9 fixture dossiers
and exercises shared proposal, analysis, review, context and retained EU routes.
Screenshots are written to `/tmp/browser-workspace-{1280,390}.png`.

Focused Python tests are in `tests/test_browser_workspace.py`; the existing
dossier/proposal/review/analysis/EU suites continue to cover engine semantics.
