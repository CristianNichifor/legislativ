# legislativ

A linter for Romanian legislation. Paste a draft act and it reports **what it touches**, **what
deadlines it creates**, **what terminology it drifts from**, and **which bills already in Parliament
overlap with it** — every finding carrying the document and the article it came from.

Where the data does not reach, the report says so. It never fills a gap with a plausible guess, and
it never says "this is legal" or "this is compliant". Its vocabulary is *candidate issue*, *missing
evidence*, *source changed*, *possible conflict*, *requires human review*.

Local-first: the corpus lives on your machine, the draft you paste never leaves it, and no account
or hosted service is required.

---

## Status

| | |
| --- | --- |
| Phase | v1 product gate closed; full-product finish remains ([`docs/PROJECT_FINISH_BIBLE.md`](docs/PROJECT_FINISH_BIBLE.md), 2026-09-15) |
| Tests | 1 936 (`uv run pytest -q`) |
| Product gate | **ready on verified local data** — `python -m scripts.app_completeness --data-home ~/.local/share/legislativ --sync-source-anchors --require-complete` passed with 9/9 required capabilities ready |
| Corpus | walked once end to end: 25 156 pages → 205 321 documents; a packed release is ~742 MB |
| Public deployment | not published. The `date.cnwebify.dev` channel returned 404 on 2026-09-10; the host has since moved to `date.cristian-nichifor.com` and must still be published and verified by a maintainer |
| Last merged | final source-anchor verification closure and acceptance evidence |
| Next | full-product finish: matrix-first workspace polish, real MCP execution UX, law-as-code authoring/checking, source-specific adapters and release deployment verification |

Both the local server and the static browser build run. The v1 gate is closed on the local verified
runtime, with no unsynced required source families. What is unfinished is the broader product finish:
matrix-first daily workflow polish, source-specific parsers beyond anchor availability, a real MCP
execution surface, stronger law-as-code authoring and final deployment verification.

---

## Quick start

```bash
uv sync --all-groups
./ruleaza.sh                      # http://127.0.0.1:8000
```

You need the corpus once. Download it, if a release exists:

```bash
scripts/ia_corpus.sh https://github.com/CristianNichifor/legislativ/releases/download/<versiune>
```

…or build it locally (a few hours, once, resumable):

```bash
uv run python -m scripts.colector --db corpus.db       # legislation
uv run python -m scripts.cdep     --db initiative.db   # pending bills
```

Keep it current — re-walks the tail and rebuilds the graph:

```bash
uv run python -m scripts.colector --db corpus.db --actualizeaza --graf graf.db
```

Everything else — act pages and the article tree, Parliament transcripts, EU/CELEX import, the
on-device model pass, offline delta packs, repairs to a collected corpus — is in
[`docs/OPERARE.md`](docs/OPERARE.md).

> **Pentru echipa de cercetare:** un singur pas, local — `./ruleaza.sh`. Proiectul lipit rămâne pe
> calculatorul tău și verificarea nu face nicio cerere externă. Ghidul complet, în română, este
> [`docs/OPERARE.md`](docs/OPERARE.md).

---

## What it can do today

**Read the corpus** — search 205 321 collected documents with diacritic-insensitive full text; open
one act with its real article tree (articole, alineate, litere); see who cites it and what it cites;
see the amendment graph and the blast radius of a change before it is made.

**Check a draft** — which acts it amends and how heavily those are already amended; the deadlines it
imposes and their anchors; terminology compared on stems against the terms the law defines;
duplicate detection against bills already moving in Parliament; drafting form under Legea 24/2000.

**The three passes, ordered by what it costs to be wrong:**

| | pass | needs a model | cost of being wrong |
| --- | --- | --- | --- |
| 1 | **Unfulfilled obligations** — norms the law required and nobody ever issued | no | nothing: a date and a failed search, checkable on the spot |
| 2 | **Terminology** | no | ten seconds of a drafter's attention |
| 3 | **Contradictions** | yes | a researcher repeating an invented article in committee |

That ordering is the argument. Built in pipeline order — scrape, parse, graph, ask a model — the
least reliable output meets the reader first; ranked by value over risk it inverts.

Pass 3 is fenced. `scripts/validare.py` drops any finding whose cited provision was not in the
prompt, whose quote is not verbatim, or whose quote is too short to check — and reports the
rejection rate rather than swallowing it, because that rate is the only honest measure of whether a
model can be trusted on this corpus. It runs on-device only
(`LEGISLATIV_MODEL=llama3.1 ./ruleaza.sh`); with no model configured the pass reports *did not run*,
not *found nothing*.

**Constitutional layer** — what the Curtea Constituțională struck, what nobody repaired, on what
constitutional ground, and whether a draft re-enacts struck wording. Deterministic and offline.

**Research workflow** — private local dossiers; manual gap, contradiction and EU-risk notes with
source hash and quote; structured proposals with revision history and before/after previews;
source-change comparison and linked reassessment; immutable saved runs; export, backup and restore.
A public data update never touches private data.

**EU law** — on-demand CELEX import through Cellar, official Romanian text preferred with a labelled
English fallback, split into citable provisions, linked to Romanian provisions with the author's
declared coverage/conflict/gap and a reason.

**Two runtimes** — `scripts/server.py` on localhost, and the same services compiled to a static
browser build under Pyodide (`construieste_web.py`), where the draft never leaves the tab.

---

## What it cannot do

Design limits and measured gaps, not bugs:

- **No legal verdict.** It produces candidates with evidence. Compliance, constitutionality and
  conflict are human conclusions.
- **No consolidation.** It records that a provision changed, on what date and by which act; it does
  not compute what the article now says. Republication renumbering is refused, not remapped —
  nothing in the corpus carries the old-to-new correspondence, so the boundary is a place where the
  tool says *this may not be the same provision*.
- **Court case law is a working mechanism over a fifth of a percent of the material.** 231
  decisions, all 1992–2004, because the chronological collector has not been run past 2008. Every
  row it emits says `blocking` for that reason.
- **Source coverage is verified at family-anchor level, not legally exhaustive.** The local
  completeness gate can pass because all required official entrypoints are reachable and current, but
  this is not full legal-domain coverage and not a substitute for source-specific parser validation.
- **Extraction is measured against too little.** `data/etalon.json` is 36 hand-written cases; the one
  number measured against law this project did not write is **97,2% reference recall** over 822 of
  the portal's own `S_LGI` marks (`scripts.etalon_real`). Neither is a coverage figure for the real
  corpus, and the real figure will be lower. A hundred sentences sampled from actual acts is the
  highest-value hour anyone can spend here.
- **AI is a drafting assistant, unmeasured as an analyst.** The evaluation harness does not exist yet.
- **MCP is not a finished surface**, law-as-code is a foundation rather than a workflow, and there is
  no hosted collaboration, no account and no background crawling.
- **CI never collects.** The portal refuses GitHub Actions runners, so the corpus is built locally.

---

## Roadmap

The v1 product gate is closed; the remaining work is full-product finish, in large vertical PRs
unless a real blocker appears. Per-track scope and acceptance:
[`docs/PROJECT_FINISH_BIBLE.md`](docs/PROJECT_FINISH_BIBLE.md). The product reasoning behind the
sequence: [`docs/ROADMAP_100_PERCENT.md`](docs/ROADMAP_100_PERCENT.md).

| | Track | What it closes |
| --- | --- | --- |
| **Closed v1 gate** | Acceptance | Final source-anchor verification, lifecycle dependency and product completeness gate are green on local verified data |
| **Now** | Matrix workspace | Make the matrix the daily workspace — gaps, overlaps and contradictions inside one legal area, with drilldown to the exact provision and source snapshot |
| | Source adapters | Move from reachable family anchors to stronger source-specific evidence for CDEP/Senate/e-consultare/Monitor/CELEX flows |
| | AI, bounded | Polish the single drafting panel, BYOK/local execution choices and the faithfulness evaluation report |
| | MCP | Turn the bounded preview/audit foundation into a real optional runtime surface with per-call consent |
| | Law as code | Complete authoring UX for rule candidates and deterministic checks that return candidates, never verdicts |
| **Release** | Deployment | Verify public Pages, local install/update, first-run UX, privacy/security and final smoke on the shipped artifact |

Explicitly **outside v1**: independently evaluated AI reasoning, hosted collaboration, OCR, broader
domain coverage, automatic monitoring. They are separate tracks, not v1 requirements.

The app is done when a legislative worker can start from a public source, see its freshness and
coverage gaps, save it to a private dossier, record an issue with exact quote and hash, work the
matrix, draft from selected evidence, use AI only through explicit bounded flows, and export the
whole thing with its limitations intact.

---

## How it works

**One source of record.** `legislatie.just.ro` and its official free SOAP service — checked, not
assumed: N-Lex proxies straight back to the same portal, neither data.europa.eu nor data.gov.ro
carries Romanian legislation as text, and Romania publishes no ELI for it.

**The API is the spine, the HTML is enrichment.** `scripts/api.py` speaks the SOAP dialect directly
with the standard library — `GetToken`, then paged `Search`, full text inline, plus `DataVigoare`,
the in-force date the HTML search will not filter by. That text is flattened, so the article tree and
the publisher's own `S_LGI` citation marks are read from the document HTML, fetched **once, ever**
per document and kept.

**Stored in SQLite**, with FTS5 for diacritic-insensitive search. A graph database loses on this
corpus: the deepest question anyone asks is *what points at this act and what does it point at*,
which is two indexed selects.

**No runtime dependencies.** Every extractor is `re`, `difflib` and `datetime`; the parser is
`html.parser`; the corpus is `sqlite3` — all standard library. `jsonschema` is a dev dependency
only. A model client brings its own and stays outside the package: `analizeaza(..., model=...)`
takes any callable from prompt to string, so Ollama, an endpoint and a recorded fixture are the same
shape.

**Politeness is measured, not assumed.** Three workers and a 0.2 s pause is the fastest rate that
draws no 503s; four workers draws 51 in four minutes and is slower once backoff is counted.

Field notes from the first full walk — the token that dies at ~114 requests behind an HTTP 500, the
citation key that is not a document identity, the FTS5 delete that was a full scan, what the gold set
caught — are in [`docs/CORPUS_NOTES.md`](docs/CORPUS_NOTES.md). The module-by-module map is in
[`docs/MODULE.md`](docs/MODULE.md).

---

## Development

```bash
uv run pytest -q                       # 1 936 tests
uv run python -m scripts.etalon        # precision / recall, with the failures named
uv run python -m scripts.etalon_real   # reference recall against the portal's own marks
uv run python -m scripts.linter        # the worked example
python -m scripts.app_completeness     # the product gate; --require-complete to block on it
```

---

## Provenance rule

Split out of [romania-reforms](https://github.com/CristianNichifor/romania-reforms), whose rule it
keeps: **every finding carries the document and the article it came from, and where the data does not
reach, the report says so instead of filling the gap with a plausible guess.** The vocabulary that
enforces it — `schema/provenance.schema.json`, three confidence levels and three limitation
severities — is vendored from there. It is a copy, copies drift, and `tests/test_date.py` at least
makes the drift loud.

---

## Documents

| | |
| --- | --- |
| [`OPERARE.md`](docs/OPERARE.md) | Ghidul de folosire, în română: colectare, surse, Parlament, UE, delta, reparații |
| [`PROJECT_FINISH_BIBLE.md`](docs/PROJECT_FINISH_BIBLE.md) | The plan of record: definition of 100%, current state, remaining PRs, stop conditions |
| [`RELEASE_V1.md`](docs/RELEASE_V1.md) | v1 scope, milestone by milestone, with acceptance evidence |
| [`APP_COMPLETENESS.md`](docs/APP_COMPLETENESS.md) | The release-blocking product gate and how to run it |
| [`ROADMAP_100_PERCENT.md`](docs/ROADMAP_100_PERCENT.md) | The ten-phase product roadmap behind the PR sequence |
| [`UX_UI_BIBLE.md`](docs/UX_UI_BIBLE.md) | The v1 UX/UI contract: target UX, phase gates, Civic UI extraction and no-verdict rules |
| [`LOCAL_FIRST.md`](docs/LOCAL_FIRST.md) | Update, activation, rollback, and the public/private storage boundary |
| [`INVENTAR_SURSE.md`](docs/INVENTAR_SURSE.md) | What is actually in the local databases — populations and limitations |
| [`CORPUS_NOTES.md`](docs/CORPUS_NOTES.md) · [`MODULE.md`](docs/MODULE.md) | Field notes from collecting the corpus · what each module does |
| [`DREPT_UE.md`](docs/DREPT_UE.md) · [`CONSOLIDARE.md`](docs/CONSOLIDARE.md) · [`DOSARE.md`](docs/DOSARE.md) | The EU flow · how consolidation refuses rather than guesses · local research storage |
| [`DESIGN.md`](docs/DESIGN.md) · [`STIL_DANEZ.md`](docs/STIL_DANEZ.md) | The design system — read before changing a colour · the plain-language target and its honesty rail |
| [`DISCLOSURE.md`](docs/DISCLOSURE.md) | A responsible-disclosure draft for defects found in `legislatie.just.ro` while reading public law through it. **Unsent** — it is for the maintainer to send, from an address they control |

License: [LICENSE](LICENSE).
