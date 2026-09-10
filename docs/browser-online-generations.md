# Browser online generations

The Pages build offers explicit `Verifica actualizarile` and `Schimba versiunea
online` controls, separate from the local server updater. It consumes the shared
publisher `scripts.dataset_release` contract: channel JSON points to a hashed
`dataset-release.json`. Only `corpus.db` is required by that contract. Optional
undeclared reports and databases are unavailable, not substituted from the build.

Checking does not select a release or download the corpus. Selection first
validates metadata, downloads and hashes the small reports used by the runtime,
and probes each declared database. The selected release and one previous release
are committed in separate public IndexedDB storage under a Web Lock. The current
tab retains its runtime until explicit reload. Draft/inflight guards run before
preparation and again before selection; the same guard protects reload, private
import and restore. A concurrent selection is rejected using the expected
manifest hash. Failed acknowledgement is reported as unconfirmed and reconciled
through a status read, never described as proof that selection stayed unchanged.

On reload, the manifest and retained report bytes are verified again, and remote
databases are probed again. All selected database URLs derive from the manifest
folder. Pagefind, build search shards and build reports are disabled for selected
releases; search uses the existing SQLite engine. Dossiers remain in their
independent private store. No research data is sent to a release host.
Coverage for the active tab is displayed independently of offered or pending
releases; merely checking an offer does not change active-source limitations.

## Integrity and limits

- Metadata is bounded to 256 KiB per file; each used report has the publisher's
  4 MiB limit. Unused `index.json` is not downloaded. Reports are stored within
  the selected/previous manifest identity, not as unversioned cache entries.
- Database probes require matching HEAD length, byte-range support, an exact
  206 Content-Range and a standalone SQLite header. Runtime reads remain online
  HTTP ranges. These checks do **not** verify the complete database SHA-256.
- Immutable release folders and correctly configured CORS remain deployment
  requirements. Same-size remote replacement cannot be detected cryptographically
  by range reads alone. No full-corpus offline support or database package download
  is implemented. Legacy unversioned OPFS databases remain disabled; any future
  OPFS cache must be qualified by release identity and verified hashes.
- A selected release that cannot load fails explicitly. Recovery controls remain
  available to clear selection or choose another release. No silent fallback to
  the included generation occurs. Inaccessible IndexedDB also fails explicitly,
  even on first boot, because absence of a previous selection cannot be established.
  A blocked open rejects promptly; it does not leave controls waiting indefinitely.
- Private snapshot status and current/retained backup export run on the main
  thread under the existing private Web Lock, without Python or public boot.
  They remain available when a selected source or the Python CDN cannot load.
  Import/restore still require successful runtime boot in this bounded version.
- Missing legacy optional sources show human-readable coverage limitations.
  Required corpus failures still fail boot. A declared optional file in a selected
  manifest must pass validation; omission is different from corruption.

## Deployment gate

The configured default is `https://date.cristian-nichifor.com/channel.json`. The parent
reported this endpoint as 404 during integration; this change does not publish it.
Production selection remains gated on publisher deployment, immutable release
assets and CORS for the Pages origin. Expose `Accept-Ranges`, `Content-Range` and
`Content-Length`; support HEAD and GET Range with 206 responses, including CORS on
errors. Redirects and foreign manifest origins are rejected. Fetches omit
credentials. A missing channel does not change the included or selected release.

`--canal-browser` configures an HTTPS channel. HTTP is accepted only for explicit
loopback fixtures using `--permite-http-local-browser`. The build CSP permits the
configured origin. No deployment, upload, account or paid service is needed for
the fixture tests.

## Verification

The publisher module must already be integrated before building this follow-up.
For the loopback fixture, run these commands in separate terminals:

```sh
uv run python -m scripts.construieste_web --sursa fixturi --canal-browser http://127.0.0.1:8058/channel.json --permite-http-local-browser
uv run python -m http.server 8057 --bind 127.0.0.1 --directory web
uv run python -m tests.browser_generation_fixture
node tests/browser_generation.cjs
```

Set `PLAYWRIGHT_MODULE` and `CHROMIUM_PATH` if not using the default installation.
The suite uses real Pyodide, SQLite and IndexedDB at 1280 and 390 pixel widths.
It covers reload/search across releases, corpus-only manifests, report/hash/origin/
duplicate-key/CORS/redirect/Range failures, lost acknowledgements, blocked storage,
cancelled draft guards, private backup preservation, and failed-boot recovery.
Screenshots: `/tmp/browser-generation-1280.png` and
`/tmp/browser-generation-390.png`. Release HTTP requests use preloaded fixture
bytes, not request-derived filesystem reads. Native contract tests live in
`tests/test_browser_generation.py`; private recovery tests remain separate.
