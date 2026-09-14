# Release Smoke

Run this before calling a release or public deploy usable:

```bash
uv run python -m scripts.release_smoke --json
uv run python -m scripts.public_local_acceptance --json
uv run pytest -q tests/test_release_smoke.py tests/test_local_launch.py
uv run pytest -q tests/test_public_local_acceptance.py tests/test_source_dataflow_acceptance.py
npm run test:browser:static
```

The smoke check is intentionally small. It verifies that the repo has the public browser app,
local launchers, private local data-home wiring, browser test scripts and GitHub Pages workflow
wiring.

The public/local acceptance gate is the product-facing release check for this slice. It verifies
that Pages deployment wiring exists, the local ZIP/checksum path exists, channel/manifest validation
is enforced, public unavailable states are covered, and source update/rollback keeps private dossier
data outside public data updates.

It does not rebuild the legislative corpus, upload multi-GB artifacts, prove source freshness or
measure legal accuracy. Those stay in the dataset acceptance and reviewer/evaluation tracks.
