# UX/UI Bible

Status date: 2026-09-14.

This is the product UX contract for v1. It does not replace
[`PROJECT_FINISH_BIBLE.md`](PROJECT_FINISH_BIBLE.md); it defines how the finished
app must feel, what each UX phase must close, and what the interface must never
claim.

## Target UX

Legislativ is a local-first workbench for Romanian legislative workers. The
first screen must help a user start from a real public source, understand whether
the local data is fresh enough, save evidence into a private dossier, and move
toward a note, proposal, rule candidate or export without learning the internal
pipeline.

The interface should be calm, dense and civic: clear hierarchy, readable legal
text, traceable evidence, explicit limitations and few decorative elements. It
should prefer verbs a researcher understands:

- "update source data", not "rebuild";
- "search data", not "index";
- "refresh view", not "reload";
- "optional source data", not "pack";
- "candidate issue", "missing evidence", "source changed", "possible conflict"
  and "requires human review", never legal verdict language.

## Phases

### UX-1: Source Start

Users can add or open a law, draft/project, consultation, CELEX/EU act or
publication reference from one obvious starting point. Each source shows family,
URL, last checked time, fetched/failed/unsupported state and the next useful
action.

### UX-2: Freshness And Coverage

Users can tell what is covered, stale, failed, unavailable or unsupported before
trusting a result. Empty output must distinguish "nothing found in measured
coverage" from "coverage missing or stale".

### UX-3: Private Dossiers

Users can save sources, notes, proposals, findings, rule candidates and exports
into local dossiers. Private work survives public data updates, backup/restore
is visible, and sharing limitations are stated at the moment of export.

### UX-4: Evidence Notes

Users can record a gap, loophole, contradiction, EU risk, implementation issue
or constitutional concern with exact source URL, source hash, quote, uncertainty
and review state. A note without enough evidence stays unresolved rather than
being promoted.

### UX-5: Matrix Workspace

The matrix becomes the main workspace for "what is wrong or missing in this legal
area". Rows are filterable by domain, source family, lifecycle state, source
quality and issue type. Every warning opens evidence or an explicit missing
source state.

### UX-6: Drafting From Evidence

Users can draft issue notes and amendments from selected evidence. Drafts carry
their basis, revision history and limitations. Generated or assisted text is
labelled as unreviewed until a human accepts it.

### UX-7: Bounded AI

AI appears as one bounded drafting assistant, not scattered panels. It requires
explicit source selection, shows local/BYOK/MCP execution mode, privacy and cost
metadata, and returns only quoted, source-backed suggestions with a rejection or
uncertainty state when evidence is insufficient.

### UX-8: MCP And External Actions

MCP actions require per-call consent, show the tool, input, destination,
privacy/cost impact and expected output before execution, and leave an audit
record. A failed or refused action must be explainable and recoverable without
losing local work.

### UX-9: Law-As-Code And Release Gate

Users can turn reviewed evidence into rule candidates and run deterministic
checks against drafts. Results are candidate issues with source references, not
legal conclusions. Public/local launch, update, rollback, real-data acceptance,
security/privacy and export checks must pass before v1 is considered usable.

## Civic UI Extraction Rule

Reusable interface primitives should be extracted into `app/vendor/civic-ui/`
only after they are proven in the app and are general civic workbench components:
forms, controls, disclosure states, evidence rows, status chips, source cards,
navigation primitives and readable legal text styles.

Do not extract app-specific workflows, domain copy, data schemas, runtime logic or
anything that still changes with the Legislativ product model. Extraction must
preserve provenance in `app/vendor/civic-ui/provenance.json`, keep tokens aligned
with [`DESIGN.md`](DESIGN.md), and avoid making `app/index.html` the source of a
new framework.

## Security, Privacy And No-Verdict Rules

- Local-first is the default. Drafts, dossiers, keys and private notes stay on the
  user's machine unless the user explicitly exports or approves an external call.
- BYOK credentials stay local/private and are never committed, exported by
  default or sent to project infrastructure.
- Public data updates must not overwrite or leak private dossiers.
- External execution, including MCP and hosted AI, must show consent, destination,
  cost/privacy metadata and audit history.
- The app must never claim "legal", "illegal", "compliant",
  "constitutional" or "no conflict" as a verdict. It may present evidence-backed
  candidates, unresolved states and human-review requirements.
- Absence of data is not absence of a legal problem unless measured coverage and
  freshness are visible to the user.
- Source changes invalidate or flag dependent work until reviewed.
- Exports must include limitations, uncertainty and source provenance.

## Acceptance Criteria

UX/UI work is acceptable when:

- a first-time legislative worker can complete source -> evidence -> note or
  proposal -> export without reading developer docs;
- every major panel has one primary purpose and uses user-facing language rather
  than pipeline terms;
- every warning, candidate and draft opens its source, quote, hash, uncertainty
  and review state, or says which source is missing;
- no screen hides privacy, cost, unsupported-source or stale-data boundaries;
- browser tests or read checks cover the changed routes or documents;
- `README.md` or the docs index links this file;
- no app change introduces automatic legal verdicts, hidden network calls,
  committed secrets or private/public storage mixing.
