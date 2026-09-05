# web — the app in the browser, no server

The same app the localhost server drives, running entirely in the browser under
[Pyodide](https://pyodide.org): the engines execute client-side, and **nothing the user types
leaves the tab**. The page's `fetch('/api/…')` is redirected in-process to `scripts.servicii` — the
exact functions `scripts/server.py` serves over HTTP — so it is one implementation with two skins,
and the test suite guards both.

## The privacy guarantee is enforced, not just claimed

The page ships a `Content-Security-Policy` whose load-bearing line is
`connect-src 'self' https://cdn.jsdelivr.net`. Even a compromised or injected script cannot send
the draft anywhere but this origin and the Pyodide CDN. Verified in a browser: after linting a
draft, `performance.getEntriesByType('resource')` shows **zero** `/api/` requests, and a deliberate
`fetch('https://example.com', {method:'POST', body:'DRAFT'})` is **blocked** by the policy. The
only network calls are Pyodide (runtime + the `sqlite3` package) and the static public-law data.

## Instant on repeat, offline, and it resyncs itself

A service worker (`sw.js`) caches this origin's shell and data cache-first, so a second visit and a
repeat query are instant and the whole tool works offline once loaded. The cache name carries a
**content hash of the corpus and graph** (`versiune` in `manifest.json`); when the data changes the
hash changes, the browser sees a different `sw.js`, installs it, and `activate` deletes every older
cache. That is the resync — the client follows the server's data with no manual clear. Verified in a
browser: the page is SW-controlled, the shell and databases are cached on first load, and per-act
shards join the cache the moment a search first touches them.

## Where the data comes from — fixtures now, a collected release as it grows

The Pages build takes its data from a **dataset release** (`date-latest`, asset `date.tar.gz`) when
one is published, and falls back to the committed 4-act fixtures otherwise — so the site always
builds, and grows when there is more law to show. The release is produced by `.github/workflows/
collect.yml`: a manual, bounded walk of the SOAP service that extends the corpus incrementally
(seeding from the previous release), rebuilds the graph and the search shards, and republishes.
Collection is server-side and slow; it never runs in a browser. Monitorul Oficial is a second
source to add to that job later.

Note the current tension this exposes: search reads the shards (per-query), but the other
corpus-reading passes still open the whole `corpus.db`, which the worker downloads once (then the
service worker caches it). That is fine for a bounded release of tens of MB; the full body of law
needs those passes moved onto the same per-act shard layer and a prebuilt terminology dictionary —
the next follow-on.

## The UI never freezes

Pyodide, the engines and the data all live in a **Web Worker** (`worker.js`), off the main thread.
The page (`index.html`) owns no engine — it starts the worker and turns each `fetch('/api/…')` into
a message to it, awaiting the reply. So neither boot (a few seconds) nor a heavy lint or search ever
blocks the page. Verified in a browser: during a deliberately heavy 15.8-second lint the main thread
painted 948 animation frames — ~60 fps throughout — where main-thread Pyodide would have frozen it
solid. `typeof loadPyodide` on the page is `undefined`; it exists only in the worker.

## Build and run

```
uv run python -m scripts.construieste_web --sursa fixturi   # reproducible demo, from sources/*.gz
uv run python -m http.server -d web 8088                     # open http://127.0.0.1:8088
```

`--sursa fixturi` builds a small, real corpus by parsing the committed `sources/` pages (Legea
98/2016 and the acts around it) to their article tree — ~4 acts, ~2,460 provisions, a graph of the
edges between them — needing nothing git-ignored, so **CI builds the same bytes**. `--sursa corpus`
(the default when `corpus.db` exists) instead ships a slice of the full collected corpus, for a
local preview against more breadth.

Everything under `web/` except this file is generated and git-ignored — the build script is the
source. `index.html` is `app/index.html` with the CSP `<meta>` and one boot block injected (loads
Pyodide + `sqlite3`, unpacks the engines and fixtures into the virtual filesystem, mounts the data,
wires the `fetch` shim).

## Deploy

`.github/workflows/pages.yml` builds `--sursa fixturi` and publishes `web/` to GitHub Pages on push
to `main`. To turn it on: **Settings → Pages → Source: GitHub Actions** (and make the repo public,
or use Pages on a plan that allows private). No secrets are needed.

## Search covers the corpus without shipping it

Search is the first check moved off the shipped slice and onto **fetch-on-demand shards**
(`scripts/shard.py` builds them, `scripts/cauta_web.py` reads them, in Pyodide). A query fetches
only the inverted-index shards its own tokens fall in, ranks the acts those postings name, and
fetches the provisions of just the top few to cut snippets. Verified in a browser: searching
`autoritate contractantă` fetched `idx/au.json` + `idx/co.json` and three act files — nothing else.

The economics, measured on the 11 272-act corpus collected so far:

| Piece | Size | When it loads |
| --- | --- | --- |
| `index.json` (act catalogue) | 0.70 MB gzipped | once |
| inverted index (795 prefix shards) | 6.82 MB gzipped total | **only the ~1 shard per query token** (~8 KB each) |
| `acte/<id>.json` (provisions) | 111 MB total | **one file per result, on demand** |

So a 259 MB SQLite corpus becomes ~0.7 MB up front and a few kilobytes per search. It scales the
same way to the full body of law; the next optimisation is to shard the act index itself (0.7 MB
for 11k grows with the corpus) and to serve a data release rather than rebuild in CI.

## The remaining limit, and where it goes

The lint passes that read the corpus ("ce atinge", repealed, terminology) still use the shipped
slice — silent, never wrong, where the data does not reach; moving them onto the same shard layer
(and the graph onto per-act shards) is the follow-on. A hardened build would also self-host the
Pyodide runtime and externalise the inline scripts to drop `'unsafe-inline'`; neither changes the
exfiltration guarantee, which rests on `connect-src`.
