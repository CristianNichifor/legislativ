# Legislativ 100% Finish Bible

This is the execution plan from the current post-PR330 state to a complete app.
It supersedes loose chat planning. Work that does not move one of these phases to
acceptance is drift.

## 0. Product Finish Line

The product is complete when a Romanian legislative worker can use the app to:

1. Find a law, draft/project, consultation or EU act from public sources.
2. See its current lifecycle status and source freshness.
3. Save it into a local/private dossier.
4. Identify or manually record a legislative gap, loophole, contradiction, EU risk
   or implementation issue.
5. Attach exact supporting provisions, source URLs, hashes and uncertainty.
6. Draft a proposed amendment or issue note from selected evidence.
7. Use AI only as a bounded drafting assistant, with BYOK/local/MCP options.
8. Convert reviewed findings into structured law-as-code candidates.
9. Export a dossier with traceable evidence and limitations.
10. Update public source data incrementally without destroying private work.

The app must not claim legal truth automatically. It must show evidence, source
state, confidence/uncertainty and review state.

## 1. Non-Negotiable Execution Rules

- No more tiny plumbing PRs unless they unblock a user-visible acceptance test.
- No large rebuild/release work unless it directly serves a real-data workflow.
- No hidden AI calls, no project-paid AI default, no committed user keys.
- No automatic legal verdicts.
- No source absence treated as legal absence unless coverage is explicitly measured
  and declared complete for that scope.
- Every phase must end with a user-facing acceptance flow, not only unit tests.
- Every PR must say which phase and acceptance item it advances.
- Prefer one large vertical slice over many internal horizontal slices.

## 2. Current Baseline After PR330

Implemented foundations:

- Local-first dossiers and browser workspace persistence.
- Manual notes for gaps, contradictions, loopholes and EU risks.
- Structured proposals, revision history and deterministic checks.
- Source registry, source sync concepts and changed-source impact.
- Project tracker event storage and partial lifecycle UI.
- Law matrix, drilldown and matrix-to-note context.
- On-demand CELEX import with official Romanian preference and English fallback.
- Source-backed EU issue-note backend and PR330 source-manager bridge.
- AI draft boundaries, BYOK settings and MCP preview concepts.
- Release rehearsal and real-data acceptance runner scaffolding.

Known product gaps:

- Real public source coverage is still too thin.
- Lifecycle tracking is not complete end to end.
- The matrix is not yet the main daily workspace.
- AI/MCP exists as pieces, not a polished user flow.
- Law-as-code exists as rule candidates/checks, not a complete authoring workflow.
- Public GitHub Pages/local app/data update path still needs final acceptance.
- UX still exposes too many internal concepts: rebuild, index, reload, pack.

## 3. Phase A: Real-Data Vertical Slice

Goal: prove one complete real workflow works before expanding features.

User story:

A user starts with a real public project or consultation URL, saves it into a
dossier, sees lifecycle/source status, finds related laws/EU references, writes an
issue note and exports the dossier.

Deliverables:

- One primary workflow screen: "Urmărește proiect / consultare".
- Accepts:
  - CDEP project URL or PL-x id;
  - Senate project URL or B id;
  - e-consultare URL;
  - ministry consultation URL when supported;
  - CELEX id or EUR-Lex/Cellar URL.
- Shows:
  - title;
  - source family;
  - latest known stage;
  - deadline when present;
  - public source URL;
  - last fetched time;
  - changed/unchanged/failed state;
  - missing data warnings.
- Actions:
  - add to dossier;
  - watch for changes;
  - create note;
  - import related CELEX;
  - export dossier.

Acceptance:

- Run one real CDEP project through the flow.
- Run one real e-consultare consultation through the flow.
- Run one real CELEX through the flow.
- Create one dossier containing all three.
- Export includes all source URLs, hashes, statuses and limitations.
- Private dossier survives reload, backup and rollback.

PR shape:

- One large PR named `real-data-workflow-v1`.
- It may touch UI, tracker, source registry and acceptance tests.
- It must not add broad crawling or large data packs.

## 4. Phase B: Lifecycle Tracker Completion

Goal: make legislative status tracking a core feature, not a log table.

Canonical lifecycle states:

- `consultation_announced`
- `consultation_open`
- `consultation_closed`
- `ministry_drafting`
- `government_agenda`
- `government_adopted`
- `sent_to_parliament`
- `registered_chamber`
- `registered_senate`
- `committee_assigned`
- `committee_opinion_requested`
- `committee_opinion_received`
- `committee_report_issued`
- `plenary_scheduled`
- `adopted_first_chamber`
- `adopted_decision_chamber`
- `rejected`
- `promulgation_sent`
- `promulgated`
- `published_monitor`
- `withdrawn`
- `archived`
- `unknown`

Source families to map:

- CDEP project pages.
- Senate project pages.
- e-consultare pages.
- Ministry consultation pages.
- Government decision/project pages where available.
- Monitorul Oficial publication references.

Deliverables:

- Unified timeline per project/consultation.
- Source-backed event snapshots.
- Stage normalization with original raw label preserved.
- Committee, vote, aviz and report extraction where available.
- Deadline extraction for consultations.
- Watchlist events for stage/deadline/source changes.
- Review queue for unknown/new lifecycle labels.

Acceptance:

- A project can be followed from consultation to Parliament when public links exist.
- Timeline never overwrites prior state; it appends events.
- Unknown labels are visible and reviewable.
- User can filter by "needs attention", "deadline soon", "committee stage",
  "vote/adoption", "published".

PR shape:

- One PR for lifecycle model + UI.
- One PR for source-family adapters if the diff becomes too large.
- No more than two PRs for this phase.

## 5. Phase C: Source Coverage That Actually Helps Drafting

Goal: ingest the sources an MP/adviser needs to write law, without trying to store
the internet.

Must-have sources:

- Legislatie.just.ro / Romanian law corpus.
- CDEP projects, documents, stages, votes, reports.
- Senate projects, documents, stages, votes, reports.
- e-consultare.gov.ro consultations.
- Ministry consultation pages.
- CCR decisions.
- EU CELEX / Cellar / EUR-Lex metadata and text.
- Monitorul Oficial publication references for laws and final publication status.

Selective/metadata-first sources:

- Monitorul Oficial Local: metadata and URL registry first; documents only on
  demand or by opted-in local packs.
- Monitorul Oficial Parts II-VII: do not full-ingest by default. Use metadata,
  references and user-requested documents first.
- Local authority acts: registry/watchlist first, domain packs later.

Storage policy:

- Base public dataset stays small.
- Source packs are optional by family/domain.
- Documents are fetched on demand unless they are essential for the accepted v1
  workflow.
- R2 stores public source packs and manifests, not private dossiers or user keys.
- Private dossiers remain browser/local runtime data.

Deliverables:

- Source registry UI that says "add source", "sync selected", "watch", "open
  source", "create note".
- No user-facing "rebuild/index/reload" wording except in developer diagnostics.
- Source status vocabulary:
  - discovered;
  - queued;
  - fetched;
  - unchanged;
  - changed;
  - failed;
  - unavailable;
  - rate_limited;
  - needs_review.
- Parser failure dashboard grouped by source family.

Acceptance:

- User can add one URL/id and sync only that source.
- User can see why a source failed and retry it.
- User can create a note from a failed/missing source state.
- Public data update does not touch private user data.

PR shape:

- One PR for source registry UX simplification.
- One PR for e-consultare/ministry source completion.
- One PR for Monitorul Oficial policy + metadata-first tracker.

## 6. Phase D: Law Matrix As Main Workspace

Goal: make the matrix the central "what is wrong or missing in this legal area"
screen.

Matrix dimensions:

- Domain/legal area.
- Legal hierarchy:
  - Constitution;
  - organic law;
  - ordinary law;
  - emergency ordinance;
  - ordinance;
  - government decision;
  - ministerial order;
  - local act;
  - EU regulation;
  - EU directive;
  - EU decision.
- Issuer.
- Institution/person affected.
- Obligation/prohibition/permission/procedure/sanction.
- Applicability date.
- Territory.
- Source quality.
- Lifecycle state.
- Review state.

Rows must include:

- Manual issue notes.
- Deterministic gap candidates.
- Contradiction candidates.
- CCR unrepaired candidates.
- Pending project overlaps.
- EU risks.
- Missing source rows.
- Changed source rows.

Actions from each row:

- Open evidence.
- Open source.
- Add/watch source.
- Create note.
- Create proposal.
- Run AI draft from selected evidence.
- Create law-as-code candidate.

Acceptance:

- A user can start from domain and end with a saved note/proposal.
- Every matrix warning has supporting evidence or explicit missing-source state.
- Matrix does not present unsupported legal conclusions.

PR shape:

- One large matrix workspace PR.
- One follow-up only if browser/UX tests require it.

## 7. Phase E: AI Drafting, BYOK and Local AI

Goal: make AI useful, cheap for the maintainer and safe for the user.

AI policy:

- Default: no paid app-owned AI.
- Primary online mode: BYOK.
- Optional local AI: browser/local runtime where hardware supports it.
- Optional MCP AI: user-approved external MCP server.
- Every request has preview, cost/token estimate where possible and explicit send.
- Keys are not committed, exported in dossiers or uploaded to public source data.

Supported tasks:

- Explain selected issue.
- Draft issue note.
- Draft amendment text.
- Draft reviewer checklist.
- Summarize source changes.
- Compare two selected quoted provisions.
- Extract proposed rule candidate from selected text.

Hard blockers:

- AI cannot invent sources.
- AI cannot silently use unselected source text.
- AI cannot mark a finding reviewed/accepted.
- AI output must be stored as draft/unreviewed.
- Missing evidence must produce refusal/uncertainty, not confident prose.

Deliverables:

- Unified AI panel in dossier and matrix.
- Provider setup:
  - OpenAI-compatible endpoint;
  - Anthropic-compatible endpoint;
  - local model option;
  - MCP option.
- Prompt manifest for every request.
- Result import with audit trail.
- AI evaluation harness wired to fixtures and optional BYOK live eval.

Acceptance:

- User can complete the full app workflow without AI.
- User can use BYOK AI to draft from selected evidence.
- User can inspect exactly what text was sent.
- Evaluation report identifies which models are acceptable for which task.

PR shape:

- One PR for unified AI UX.
- One PR for provider execution hardening.
- One PR for evaluation/reporting.

## 8. Phase F: MCP Product Surface

Goal: MCP becomes a real integration surface, not just a payload preview.

Use cases:

- User AI subscription through MCP.
- Export dossier to user documents/storage.
- Create calendar/task reminders for consultation deadlines.
- Import source files from a user-selected folder.
- Optional GitHub issue/PR creation from reviewed findings.

Deliverables:

- MCP server list/test connection UI.
- Tool capability discovery.
- Data preview before execution.
- Explicit approval per external call.
- Audit log:
  - server;
  - tool;
  - timestamp;
  - payload hash;
  - selected evidence ids;
  - result hash;
  - user action.
- Result import into dossier.
- Failure/retry states.

Acceptance:

- User can run one AI MCP workflow from selected dossier evidence.
- User can run one export/reminder workflow.
- App works when MCP is unavailable.
- No hidden external data transfer exists.

PR shape:

- One MCP UX/runtime PR.
- One MCP workflow PR.

## 9. Phase G: Law-As-Code V1

Goal: convert reviewed legal text into structured, testable rules without claiming
the law is fully executable.

Rule candidate fields:

- Source provision identity.
- Source hash.
- Actor.
- Action.
- Modality:
  - obligation;
  - prohibition;
  - permission;
  - condition;
  - exception;
  - deadline;
  - sanction;
  - competence;
  - procedure.
- Trigger/condition.
- Effect.
- Deadline/date rule.
- Exceptions.
- Applicability scope.
- Confidence/source extraction method.
- Review status.

Rule workflow:

1. Select provision/evidence.
2. Extract candidate deterministically or with AI draft.
3. Human edits structured rule.
4. Save as unreviewed/reviewed.
5. Run deterministic checks against draft/proposal.
6. Report candidate issue, not verdict.

First supported checks:

- Delegated norm required but missing.
- Deadline required but no implementing act found.
- Draft creates obligation with no actor.
- Draft creates procedure with no deadline/competent body.
- Draft amends repealed/changed provision.
- Draft references missing/ambiguous act.
- Draft potentially conflicts with selected EU article.

Acceptance:

- A user can create a rule candidate from one provision.
- A user can run it against one draft.
- Output cites exact source and explains uncertainty.
- Reviewed rule candidates survive backup/restore/export.

PR shape:

- One PR for rule authoring UX.
- One PR for deterministic execution/reporting.
- One PR for AI/MCP rule extraction.

## 10. Phase H: Public App, Local App and Data Updates

Goal: make the app actually shippable from GitHub Pages and runnable locally.

Supported modes:

- GitHub Pages public app:
  - small base dataset;
  - browser-local private workspace;
  - optional source packs;
  - no server-only features unless clearly marked unavailable.
- Downloadable local app:
  - easy start command;
  - local SQLite data;
  - source sync;
  - backup/restore;
  - optional local AI/MCP.

Deliverables:

- Public deployment verification script.
- Local install smoke script.
- Data manifest/channel verification.
- Optional source pack UI.
- Update button wording:
  - "Check for source updates";
  - "Download selected source pack";
  - "Activate update";
  - "Rollback source update".
- Private data boundary tests.

Acceptance:

- Fresh user can open GitHub Pages and create a private dossier.
- Fresh user can download and run locally.
- Updating public data does not overwrite private work.
- Rollback preserves private dossiers.
- User sees unavailable states instead of broken buttons.

PR shape:

- One public/local acceptance PR.
- One UX wording cleanup PR if needed.

## 11. Phase I: Final UX Cleanup

Goal: remove the feeling of a pile of internal tools.

Navigation should become:

- Start
- Search
- Track
- Matrix
- Dossiers
- Sources
- AI/MCP
- Settings

Language cleanup:

- Replace "rebuild" with "update source data" unless developer-only.
- Replace "index" with "search data" unless developer-only.
- Replace "reload" with "refresh view" or remove it.
- Replace "pack" with "optional source data" in user-facing text.
- Use "source state", "last checked", "needs attention", "watch" consistently.

Deliverables:

- First-run path.
- Empty states.
- Error states.
- Loading states.
- Disabled states with reasons.
- Mobile pass.
- Keyboard pass.
- Romanian copy pass.

Acceptance:

- User can understand what to do without reading docs.
- Top five workflows are reachable in two clicks or less.
- No duplicate panels for the same job.
- Browser tests cover the main routes.

PR shape:

- One UX consolidation PR.

## 12. Phase J: Final Reliability, Security and Release Gate

Goal: final confidence before calling the app complete.

Required checks:

- Full Python test suite.
- Browser tests.
- Package checks on Linux/macOS/Windows.
- Code scanning/security alerts clean or explicitly accepted.
- Signed commits.
- Backup/restore drill.
- Public Pages smoke.
- Local download smoke.
- Real-data acceptance run.
- AI eval run if AI is enabled.
- MCP dry run if MCP is enabled.

Release evidence:

- `docs/FINAL_ACCEPTANCE.md`
- latest source coverage JSON
- latest real-data workflow JSON
- latest AI evaluation JSON
- latest MCP audit fixture
- latest public/local install verification
- known limitations

Acceptance:

- No failing required CI checks.
- No untriaged code scanning alerts.
- No hidden paid external calls.
- No private data upload in normal workflows.
- User-facing limitations are honest and visible.

PR shape:

- One final release gate PR.

## 13. Execution Order From Here

Do this order. Do not reorder unless a blocker is real.

1. Phase A: real-data vertical workflow.
2. Phase B: lifecycle tracker completion.
3. Phase C: source coverage for e-consultare, ministries, CDEP/Senate and
   Monitorul Oficial metadata-first.
4. Phase D: matrix as main workspace.
5. Phase E: AI drafting/BYOK/local workflow.
6. Phase F: MCP execution workflow.
7. Phase G: law-as-code rule candidate authoring and execution.
8. Phase H: public/local app and data updates.
9. Phase I: UX cleanup.
10. Phase J: final release gate.

## 14. Parallelization Rules

Can run in parallel:

- Lifecycle adapters and source registry UX, if they do not touch the same files.
- AI provider UX and AI evaluation harness.
- MCP audit/runtime and law-as-code rule schema.
- Public/local smoke scripts and UX wording cleanup.

Must not run in parallel:

- Two PRs editing the same major section of `app/index.html`.
- Schema migrations that affect the same database.
- Source registry state vocabulary changes and tracker event vocabulary changes
  unless one PR owns the shared contract.
- Release manifest changes while data pack generation is changing.

## 15. Stop Conditions

Stop and ask before continuing if:

- A change would require storing multi-GB data by default.
- A change would require paid app-owned AI.
- A change would upload private dossiers or keys.
- A phase needs a legal reviewer to claim legal correctness.
- CI failures are unrelated to the phase and would require broad refactoring.

Do not stop for:

- Normal test failures caused by the current change.
- Missing polish that is inside the phase acceptance.
- Needing to add focused tests.

## 16. PR Size Standard

A good PR now should usually be one vertical slice:

- 300-1200 changed lines is acceptable.
- It may touch backend, UI, tests and docs together.
- It must have one user-facing workflow acceptance.
- It must not be only renaming, only copy changes or only plumbing unless it fixes
  a blocker in the current phase.

## 17. What 100% Does Not Mean

100% does not mean:

- every EU act downloaded locally;
- all Monitorul Oficial parts fully ingested by default;
- AI gives legal advice;
- the app certifies compliance;
- the maintainer pays for all users' AI calls;
- every Romanian legal domain is perfect on day one.

100% means:

- the app has complete workflows for the agreed scope;
- sources are traceable;
- gaps are explicit;
- missing data is visible;
- AI/MCP are controlled and user-owned;
- law-as-code candidates are reviewable and testable;
- public and local usage are reliable.

