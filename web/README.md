# web — the browser build (proof of concept)

The same app the localhost server drives, running entirely in the browser under
[Pyodide](https://pyodide.org): the engines execute client-side, and **nothing the user types
leaves the tab**. The only network calls are Pyodide (from its CDN) and the static data files
(public law) from this app's own origin — verified: a lint of a draft makes **zero** `/api/`
requests, because the page's `fetch('/api/…')` is redirected in-process to `scripts.servicii`, the
exact functions `scripts/server.py` serves over HTTP. One implementation, two skins; the 218 tests
guard both.

## Build and run

```
uv run python -m scripts.construieste_web      # writes web/{index.html,bundle.zip,data/*.db}
uv run python -m http.server -d web 8080        # then open http://127.0.0.1:8080
```

Everything under `web/` except this file is generated and git-ignored — the build script is the
source. `index.html` is `app/index.html` with one boot block prepended (loads Pyodide + the
`sqlite3` package, unpacks the engines and fixtures into the virtual filesystem, mounts the data
slice, and wires the `fetch` shim).

## What ships, and the honest limits

- `bundle.zip` — the `scripts/` package and the `sources/` consolidation fixtures.
- `data/graf.db` — the **whole** amendment graph (small).
- `data/corpus.db`, `data/initiative.db` — a **slice** (a few hundred acts + a curated handful the
  demo cites). The full corpus is ~4.5 GB and is not shippable to a browser; a real deployment
  fetches per act on demand from a static host (the hosted-consolidated-DB / resync direction).
  Until then, cross-corpus checks (search, "ce atinge", repealed) see only the slice — silent, not
  wrong, where the data does not reach.

## For a public deployment (not done here)

Self-host the Pyodide runtime instead of the CDN, add a strict `Content-Security-Policy`, and ship
no analytics — then the "the draft never leaves your browser" claim is enforced by the page, not
just true of it, and auditable because the code is public.
