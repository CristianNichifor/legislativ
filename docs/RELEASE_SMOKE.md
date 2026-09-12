# Release Smoke

Run this before calling a release or public deploy usable:

```bash
uv run python -m scripts.release_smoke --json
uv run pytest -q tests/test_release_smoke.py tests/test_local_launch.py
npm run test:browser:static
```

The smoke check is intentionally small. It verifies that the repo has the public browser app,
local launchers, private local data-home wiring, browser test scripts and GitHub Pages workflow
wiring.

It does not rebuild the legislative corpus, upload multi-GB artifacts, prove source freshness or
measure legal accuracy. Those stay in the dataset acceptance and reviewer/evaluation tracks.
