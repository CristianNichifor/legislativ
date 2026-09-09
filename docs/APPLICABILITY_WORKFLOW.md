# Saved context filtering and comparison

The saved-finding context panel compares two targets or two loaded revisions of
one target. Filters select a field, information state, textual comparison state,
or literal value/citation substring. Counts describe fields, not applicable laws.
The default comparison selects the current A/B contexts when both exist.
Single-target findings compare the current context with itself until another
revision is selected. Older history pages become selectable after loading them.

- **Known declared** requires both a saved value and citation. The citation is
  unverified; known means the declaration is present, not legally established.
- **Unknown** includes absent context and empty values. Two unknown values never
  become an equal or compatible result. Empty dates are not unbounded intervals;
  empty exceptions do not assert that there are none.
- **Heuristic** uses only the candidate's saved domain key and nonempty metadata
  evidence from the existing domain classifier. A label without that evidence is
  unknown. Candidate domain hints are not attributed to either target act.

Dates, territory, recipients, exceptions, transitional provisions and normative
classification retain separate citations. Comparison is exact textual equality
or difference, with both citations and event ID/revision/author/time visible.
It performs no interval-based applicability verdict, geographic interpretation,
recipient matching, exception reasoning or organic-law inference from act rank.
Equal declarations with different citations remain visibly distinct sources.

This is a context workflow within one saved finding, not a global applicability
registry or a cross-dossier search. Matrix metadata filters remain heuristic.
The comparison uses saved values only; unsaved editor text is not substituted.
Filtering does not alter the report, decisions, source checks or export scope.
Existing JSON/Markdown exports retain the full saved contexts and provenance.
Context filter selections are transient and reset when the finding is rerendered.

Storage and APIs remain unchanged at schema 7. The existing `evaluator` wire field
is an unauthenticated author label; no reviewer qualification or review decision
is required to use context. No migration, network acquisition or inference is
introduced. Older contexts are never backfilled with current corpus metadata.

Verification: `uv run pytest tests/test_applicability_workflow.py
tests/test_context_juridic.py tests/test_dossier_ui.py`. The first test executes
production JavaScript with Node; the latter suites cover storage, ownership,
history, retry, schema compatibility and existing UI behavior.

The next bounded evidence-linking interface is specified in
[CONTEXT_UE_CONTRACT.md](CONTEXT_UE_CONTRACT.md). A contract alone does not complete M5.

## Browser fixture check

Start the existing server with `--port 8042 --initiative
.context-fixture/initiative.db --corpus .context-fixture/corpus.db --graf
.context-fixture/graf.db --eu .context-fixture/eu.db --fara-browser` using
`uv run python -m scripts.server`. Then run
`PLAYWRIGHT_MODULE=/path/to/playwright node tests/context_workflow_browser.cjs`.
No package install or source download is needed when Playwright is available.
The seed creates disposable schema-7 dossiers in this worktree only.

Verified at 1280px and 390px: state/field/text filtering, visible metadata evidence,
A/B and historical revision comparison, older-page selection, HTML escaping,
unsaved context preservation and no horizontal overflow or JavaScript errors.
Screenshots are local artifacts in `.context-fixture/context-1280.png` and
`.context-fixture/context-390.png`; do not stage fixture databases or screenshots.
