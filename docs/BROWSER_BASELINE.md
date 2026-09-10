# Browser Adoption Baseline

`npm run test:browser` exercises the unchanged local application in Chromium,
Firefox and WebKit at 390px and 1440px. The real Python HTTP backend and SQLite
search/lint functions run against one explicitly synthetic law in a temporary
directory. No user's database, draft, credentials or external corpus is read.

The checks search that corpus, submit a draft to the real lint endpoint, switch
tabs, and verify the existing local theme preference survives a reload. External
browser requests are blocked and cause failure. Screenshots and failure traces are
CI artifacts, not committed reference images.

```sh
npm ci --ignore-scripts
npx playwright install --with-deps
npm run test:browser
```

Python 3.12 is required. CI uses the pinned Playwright container, which includes
Python 3.12. Browser tooling is development-only; the application still has no npm
runtime. Playwright owns and stops the fixture server.
Node 20 or newer is required for the development tooling.

## Limits

This verifies the local Python mode with a small synthetic corpus, not the full
published corpus or legal correctness. The static-mode baseline below separately
exercises the generated Pyodide worker and Pagefind index. Browser-only request blocking does not
claim to sandbox the backend; this fixture uses no collector or online AI service.
Existing Python tests remain the domain contract. This is not a full accessibility
or visual-diff certification.

## Static Worker Baseline

Run `npm run test:browser:static` with the same Node, Python and browser prerequisites.
The fixture server copies only Git-tracked files to a temporary directory, builds
the real `--sursa fixturi` application, exports its public four-act corpus and builds
a real Pagefind 1.5.2 index. It does not read a local corpus, publish data, contact an
object store, replace Pyodide, or change the application HTML. Initial boot fetches
the real pinned Pyodide 0.27.2 runtime and SQLite package from the existing CDN.

Chromium, Firefox and WebKit test both `/` and `/nested/` deployments:

- Real worker boot and lint results; the main thread has no `loadPyodide`.
- Successful Pagefind index/fragment responses and search, without silent fallback.
- Service-worker control and actual CacheStorage shell/search entries.
- No outgoing `/api/` requests. The four-act fixture corpus is fetched once from
  the same origin to support dossier analysis. Fixture/slice loading is capped at
  32 MiB; this is not a production full-corpus download or offline guarantee.
- New lint results and a repeated search while the already-loaded tab is offline.
- In Chromium, an offline reload with CDN requests explicitly aborted: the cached shell loads,
  but the new worker reports the unavailable runtime instead of completing lint.
- A fresh offline context cannot load a shell it has never cached.

The unavailable-CDN reload is a deliberately forced boundary, not a claim that
every warm reload fails: ordinary browser HTTP caching can retain external runtime
assets. The site's service worker does not cache those assets, so a completely
offline restart is not guaranteed. The tests do not certify cache eviction, updates
between versions, arbitrary uncached searches, OPFS database downloads or production
object-store Range behavior. Search remains covered against a small public fixture,
not the production corpus. CI uploads screenshots/traces and fails on CDN errors;
there are no mocked runtimes or committed browser caches.

Firefox and WebKit cover real online boot, search, lint, CacheStorage and same-tab
offline use, but Playwright offline navigation fails (`NS_ERROR_OFFLINE` and an
internal browser error respectively); restart coverage is not claimed for those
engines. Worker readiness is observed by a test-only
transparent constructor wrapper that returns the native Worker and records its real
ready message. Detailed external worker-request tracing is asserted in Chromium;
the other engines still execute the actual generated worker and Python code.

This baseline found and guards a no-object-store Pagefind base-path bug: a relative
`./pagefind/` resolved from the client module to `/pagefind/pagefind/`. Resolving the
index base against the document URL preserves root and nested deployments.

## Civic UI adoption

The search surface now opts into Civic UI v0.3.0's native CSS contract for its
search input and type/year selects. The CSS-only archive is vendored under
`app/vendor/civic-ui/` with its public-release checksum in `provenance.json`;
there is no React runtime or remote stylesheet dependency. Existing document
tokens remain authoritative through `civic-ui-adapter.css`. Other editors,
dialogs, graph controls and domain-specific actions remain on their existing
styles until each has an equivalent browser baseline.
