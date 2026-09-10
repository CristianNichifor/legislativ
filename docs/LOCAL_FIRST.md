# Local-first delivery

The application has two delivery modes: the static GitHub Pages application and
a downloaded Python runtime serving localhost. Public legislation and private
research have separate lifecycles. Neither requires an account or a hosted
private-workspace database.

## Public updates

The local update command is download-only:

1. Explicitly check the configured HTTPS channel.
2. Inspect the offered release and download size, then confirm download.
3. Download into staging, resuming interrupted files with HTTP Range where
   supported. Verify the manifest digest, file sizes, SHA-256 digests and SQLite
   integrity before offering activation.
4. Explicitly activate. Prepare the private EU view and a complete runtime before
   atomically replacing `active.json`. A failed preparation leaves the old active
   pointer and runtime intact.
5. Revert to the retained previous public release if needed. Rollback creates a
   new private EU view from the latest private observations; it does not restore
   an old private-workspace backup.

The channel and manifest must remain on the configured origin. Redirects and
arbitrary file URLs are rejected. The channel is trusted through HTTPS; hashes
detect corruption and inconsistent publication, not compromise of the publisher.
An older release date is not evidence that the underlying law is out of force,
and a newer package date does not establish legal completeness or correctness.

Full files are transferred initially. Delta updates and automatic pruning are
not implemented. Allow space for the old and new public releases, staging and a
new private EU generation. Completed releases remain on disk. Remove obsolete
files only with the application stopped and after checking `active.json` and its
previous generation; do not delete the private directory to free corpus space.

## Storage boundaries

| Data | Managed local location | Update behavior |
| --- | --- | --- |
| Public corpus, graph, initiatives, reports | `datasets/<manifest-sha256>/` | Immutable generation |
| Download in progress | `staging/<manifest-sha256>/` | Resumable, never served as active |
| Dossiers, drafts, proposals, reviews | `private/dosare.db` | Not uploaded or replaced |
| Imported parliamentary documents | `private/initiative.documente.db` | Stable private sidecar |
| EU observations and retained source snapshots | `private/eu-generations/<uuid>/eu.db` | Preserved when preparing updates or rollback |

A process-lifetime data-directory lock prevents concurrent managed runtimes
from writing different private EU generations. Browser persistence is separate
from these local files, and separate browser profiles or origins do not share a
workspace automatically. Backups are private data and need private storage.

Existing developer-mode databases are not moved implicitly. Stop the old server
and retain a complete backup before migrating existing research. Installing a
new runtime never grants permission to overwrite an existing personal database.

## Distribution and deployment

- [Runtime installation and artifact build](local-launch.md).
- [Manifest, publisher and channel promotion](DATASET_RELEASE.md).
- [Private EU merge and preservation contract](private-data-boundaries.md).
- [Browser persistence and backup limitations](browser-workspaces.md).

The runtime package contains application code and assets, not Python, the corpus
or private research. Python 3.12+ must be installed separately. First launch does
not fetch legislation, collect sources or invoke paid AI.

The new production channel `https://date.cnwebify.dev/channel.json` returned HTTP
404 during the integration check on 2026-09-10. Building this feature does not
publish that channel. A maintainer must publish and verify a curated public
release, explicitly promote the channel, review the application PR, and approve
release distribution. No R2 credentials or private research are included in
runtime artifacts. No pull requests are merged automatically.

This work does not implement shared accounts, bidirectional private sync,
background crawling, legal-review sign-off, or a guarantee that an entire corpus
fits in browser storage. Those remain separate decisions, not prerequisites for
using an installed local dataset and private workspace.
