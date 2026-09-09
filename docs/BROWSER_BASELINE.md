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
published corpus or legal correctness. The independently generated Pyodide worker,
service worker cache, Pagefind index and cold/warm offline static modes are not
covered here. They remain unchanged and need their own integration baseline before
shared-control adoption in the static build. Browser-only request blocking does not
claim to sandbox the backend; this fixture uses no collector or online AI service.
Existing Python tests remain the domain contract. This is not a full accessibility
or visual-diff certification.
