# Legislativ 100% Implementation Bible

Status date: 2026-09-14, after PR341.

This document is the implementation bible. Work that does not move one of the
remaining gates below is drift. The target is a finished, usable Romanian
legislative analysis app, not an endless sequence of infrastructure PRs.

## 0. Definition Of 100%

The app is complete when a Romanian legislative worker can:

1. Start from a public source: law, draft/project, consultation, EU act or
   Monitorul Oficial publication reference.
2. See source freshness, current lifecycle stage, known gaps in coverage and
   limitations.
3. Save the item into a private local dossier.
4. Record a legislative gap, loophole, contradiction, EU risk or implementation
   issue with exact source URL, hash, quote and uncertainty.
5. Use the matrix as the main workspace for "what is wrong or missing in this
   legal area".
6. Draft an issue note or amendment from selected evidence.
7. Use AI only through explicit, bounded local/BYOK/MCP flows.
8. Convert reviewed evidence into law-as-code rule candidates.
9. Run deterministic checks against drafts/proposals and get candidate issues,
   never automatic legal verdicts.
10. Export/backup/restore dossiers with traceable evidence and limitations.
11. Open the public GitHub Pages app or run the downloadable local app without
   losing private work.
12. Pass the final release gate with CI, browser tests, code scanning, public
   smoke, local smoke, real-data acceptance, AI eval and MCP dry run.

The app must never say "this is illegal" or "this is compliant" as truth. It can
say: "candidate issue", "missing evidence", "source changed", "possible conflict",
"requires human review".

## 1. Current State

Already implemented:

- Local-first dossiers, private browser workspace, backup/restore foundations.
- Manual notes for gaps, loopholes, contradictions, EU risks and constitutional
  issues.
- Proposal drafting, revision history and deterministic checks.
- Real workflow entry for CDEP/Senate/e-consultare/ministry consultation/CELEX.
- Source registry with explicit one-source sync, queue, review, retry, source
  impact, changed-source detail and source-to-dossier-note actions.
- Lifecycle tracker with canonical-ish states, filters, evidence coverage,
  missing-stage actions, unknown-label review and source-backed timeline views.
- EU/CELEX on-demand import with official Romanian preference and English
  fallback.
- Law matrix exists with drilldown and matrix-to-note context.
- Law-as-code candidates/checks exist as foundations.
- AI/BYOK/local/MCP concepts exist with bounded prompt/audit preview pieces.
- Public/local release and real-data acceptance scaffolding exists.

Still not complete:

- Source coverage is still incomplete for public drafting work.
- Matrix is not yet the main daily workspace.
- AI is not yet a single polished user flow.
- MCP is not yet a real execution surface.
- Law-as-code is not yet a complete authoring and execution workflow.
- Public Pages/local install/update acceptance has not been closed end to end.
- UX still exposes too many internal words and duplicate panels.
- Final acceptance evidence is not assembled.

Overall progress estimate: 60-65% of a strict v1.

## 2. Non-Negotiable Rules

- No automatic PR merging. The user reviews and merges.
- All commits must be signed and verified.
- Every PR must state the phase, user-facing value and acceptance gate it moves.
- Prefer fewer, larger vertical PRs over tiny plumbing PRs.
- Do not add multi-GB releases or broad data dumps unless the release gate
  explicitly needs them.
- No hidden paid AI. Default is no project-paid AI.
- No committed user keys. BYOK stays local/private.
- No source absence treated as legal absence unless coverage is explicitly
  measured and shown.
- No new backend/account infrastructure until public/local acceptance needs it.
- If CI fails, fixing CI has priority over new work.

## 3. Remaining PR Sequence

Target: 18 large PRs maximum from here to final release gate.

### PR342: Source Coverage Control Center

Phase: C.

Goal: make source coverage understandable and actionable from one screen.

Implement:

- A "Sources" workspace summary grouped by family:
  - Romanian legislation corpus;
  - CDEP;
  - Senate;
  - e-consultare;
  - ministry consultations;
  - CCR;
  - EU CELEX/Cellar;
  - Monitorul Oficial Part I;
  - Monitorul Oficial Local;
  - Monitorul Oficial Parts II-VII metadata-only.
- For each family show:
  - supported/not supported;
  - registry count;
  - fetched count;
  - changed count;
  - failed/unavailable/rate-limited count;
  - last checked;
  - next useful action.
- User actions:
  - add one source;
  - sync selected source;
  - retry failures;
  - create note from missing/failed source;
  - open parser failure details.
- Replace user-facing "rebuild/index/reload/pack" wording in this area with:
  - "update source data";
  - "search data";
  - "refresh view";
  - "optional source data".

Acceptance:

- User can understand what source coverage exists without reading docs.
- User can retry a failed source and create a note if it still fails.
- Public data update boundaries are visible.

### PR343: e-Consultare And Ministry Tracker Completion

Phase: C.

Goal: consultations become first-class trackable sources.

Implement:

- Stronger normalization for e-consultare and ministry consultation metadata.
- Deadline extraction and closed/open/unknown status normalization.
- Attachment/document metadata summary.
- Tracker events for:
  - consultation announced;
  - consultation open;
  - deadline changed;
  - consultation closed;
  - document added;
  - source unavailable/failed.
- Review queue rows for missing deadline/status/authority.

Acceptance:

- One real e-consultare URL can be added, synced, watched, noted and exported.
- One ministry consultation URL can be metadata-tracked even if parser coverage is
  partial.

### PR344: CDEP/Senate Documents, Votes, Reports And Avize

Phase: C.

Goal: parliamentary source coverage supports actual drafting work.

Implement:

- Extract and store project document links where available.
- Normalize committee/report/vote/aviz events into tracker events.
- Preserve raw labels and source URLs.
- Show "documents/reports/votes/avize" counts in lifecycle and source detail.
- Add source failure rows when a project page references unavailable documents.

Acceptance:

- One CDEP project has documents + committee/report/vote evidence visible.
- One Senate project has documents/stage evidence visible.
- User can open evidence from lifecycle and create a note/proposal.

### PR345: Monitorul Oficial Metadata-First Tracking

Phase: C.

Goal: final publication status exists without huge data ingestion.

Implement:

- Monitorul Oficial Part I publication reference model.
- Monitorul Oficial Local metadata registry.
- Parts II-VII metadata-only policy in code and UI.
- Link project/law publication references to lifecycle `published_monitor`.
- On-demand document placeholder state for unsupported/paid/manual documents.

Acceptance:

- User sees publication reference status for a law/project when known.
- User sees honest unavailable/manual states when Monitor source text is not
  locally available.
- No large bulk Monitor ingestion is introduced.

### PR346: Matrix Workspace V1

Phase: D.

Goal: matrix becomes the main "what is wrong/missing" workspace.

Implement:

- Matrix route/workspace with filters:
  - domain/legal area;
  - legal hierarchy;
  - issuer;
  - source family;
  - lifecycle state;
  - review state;
  - source quality;
  - issue type.
- Rows from:
  - manual notes;
  - deterministic gap candidates;
  - contradiction candidates;
  - EU risks;
  - CCR unrepaired candidates;
  - pending project overlaps;
  - missing/failed/changed source states;
  - rule candidates.
- Actions per row:
  - open evidence;
  - open source;
  - create note;
  - create proposal;
  - create law-as-code candidate;
  - prepare AI draft from selected evidence.

Acceptance:

- User starts from a legal domain and ends with a saved note/proposal.
- Every matrix warning has evidence or explicit missing-source state.
- Matrix does not present unsupported legal conclusions.

### PR347: Matrix Evidence Drilldown And Navigation

Phase: D.

Goal: matrix rows become navigable, not just summaries.

Implement:

- Evidence drawer for selected row.
- Source hash/URL/quote/uncertainty displayed together.
- "Related items" links:
  - laws;
  - projects;
  - CELEX;
  - consultations;
  - Monitor publication references;
  - existing notes/proposals/rules.
- Browser tests for top matrix routes.

Acceptance:

- User can move from matrix warning to exact supporting provisions in two clicks.
- Missing-source rows show what is missing and how to collect it.

### PR348: Unified AI Drafting Panel

Phase: E.

Goal: one AI UX, not scattered panels.

Implement:

- AI panel usable from dossier, note, proposal and matrix row.
- Tasks:
  - explain selected issue;
  - draft issue note;
  - draft amendment;
  - reviewer checklist;
  - summarize source change;
  - compare two quoted provisions;
  - extract rule candidate.
- Selected-evidence-only payload builder.
- Prompt manifest preview:
  - task;
  - provider;
  - selected evidence ids;
  - source URLs;
  - hashes;
  - token estimate;
  - limitations.
- Explicit "run" action.

Acceptance:

- User can complete the app without AI.
- User can inspect exactly what would be sent before any AI call.
- Missing evidence blocks confident AI prose.

### PR349: BYOK And Local AI Execution Hardening

Phase: E.

Goal: make online/local AI usable without maintainer cost.

Implement:

- OpenAI-compatible BYOK settings.
- Anthropic-compatible BYOK settings.
- Local model option where supported.
- Secure local key handling; no export, no public upload.
- Request timeout/error/retry states.
- Result imported as draft/unreviewed with audit metadata.

Acceptance:

- User can use their own key for one drafting task.
- Failed AI calls do not create accepted findings.
- Export does not include API keys.

### PR350: AI Evaluation Harness

Phase: E.

Goal: decide what AI is reliable for, with evidence.

Implement:

- Fixture-based evals for:
  - issue explanation;
  - amendment drafting;
  - source-change summary;
  - EU risk note;
  - rule extraction.
- Checks:
  - cites selected evidence;
  - refuses missing evidence;
  - no legal verdict;
  - no invented source;
  - structured output parseable.
- Optional BYOK live eval command.
- JSON report and UI summary.

Acceptance:

- Evaluation report identifies acceptable tasks/providers.
- Local/default mode remains no paid AI.

### PR351: MCP Runtime Surface

Phase: F.

Goal: MCP becomes real product surface.

Implement:

- MCP server list/test connection UI.
- Tool capability discovery.
- Payload preview before execution.
- Explicit approval state for each external call.
- Audit log schema:
  - server;
  - tool;
  - timestamp;
  - payload hash;
  - selected evidence ids;
  - result hash;
  - user action.
- Failure/retry states.

Acceptance:

- App works when MCP is unavailable.
- User can see exactly what would be sent to an MCP tool.
- No hidden external transfer.

### PR352: MCP Workflows

Phase: F.

Goal: useful MCP workflows, not only settings.

Implement:

- AI through MCP from selected dossier/matrix evidence.
- Export dossier to user-selected document/storage MCP.
- Consultation deadline reminder workflow.
- Import source files from user-selected folder.
- Result import into dossier with audit record.

Acceptance:

- One AI MCP workflow works.
- One export/reminder workflow works.
- MCP result is saved as draft/unreviewed.

### PR353: Law-As-Code Authoring UX

Phase: G.

Goal: reviewed evidence can become structured rules.

Implement:

- Rule candidate editor with:
  - provision identity;
  - source URL/hash;
  - actor;
  - action;
  - modality;
  - trigger/condition;
  - effect;
  - deadline/date rule;
  - exceptions;
  - applicability scope;
  - confidence/extraction method;
  - review status.
- Start from:
  - provision;
  - manual note;
  - matrix row;
  - AI/MCP draft.

Acceptance:

- User can create and edit a rule candidate from one provision or note.
- Rule candidate survives backup/restore/export.

### PR354: Law-As-Code Deterministic Checks

Phase: G.

Goal: rules produce candidate issues against drafts/proposals.

Implement first checks:

- Delegated norm required but missing.
- Deadline required but no implementing act found.
- Draft creates obligation with no actor.
- Draft creates procedure with no deadline or competent body.
- Draft amends repealed/changed provision.
- Draft references missing/ambiguous act.
- Draft potentially conflicts with selected EU article.

Acceptance:

- User runs rules against one draft/proposal.
- Output cites exact source and explains uncertainty.
- Output says candidate issue, not verdict.

### PR355: Public Pages And Local App Acceptance

Phase: H.

Goal: prove the app ships and preserves private work.

Implement:

- Public deployment verification script.
- Local install smoke script.
- Data manifest/channel verification.
- Optional source data UI.
- Public mode unavailable states for server-only actions.
- Private data boundary tests.

Acceptance:

- Fresh user can open GitHub Pages and create a private dossier.
- Fresh user can download/run locally.
- Source update does not overwrite private work.
- Rollback preserves private dossiers.

### PR356: First-Run UX And Navigation Cleanup

Phase: I.

Goal: remove the feeling of internal tools.

Implement navigation:

- Start.
- Search.
- Track.
- Matrix.
- Dossiers.
- Sources.
- AI/MCP.
- Settings.

Implement UX states:

- First-run path.
- Empty states.
- Error states.
- Loading states.
- Disabled states with reasons.
- Mobile/keyboard pass.
- Romanian copy pass.

Acceptance:

- User can understand what to do without docs.
- Top five workflows are reachable in two clicks or less.
- No duplicate panels for the same job.

### PR357: Real-Data End-To-End Acceptance

Phase: J.

Goal: prove complete real workflow.

Implement/run:

- One real CDEP project.
- One real Senate project.
- One real e-consultare consultation.
- One real ministry consultation.
- One CELEX/EU act.
- One Monitor publication reference where available.
- One dossier containing all of them.
- One note, one proposal, one matrix issue, one rule candidate.
- Export, backup, restore, rollback.

Acceptance:

- JSON evidence artifact committed under docs/artifacts or generated by test.
- `docs/FINAL_ACCEPTANCE.md` links the run and limitations.

### PR358: Security, Code Scanning And Privacy Gate

Phase: J.

Goal: no untriaged security/privacy risk remains.

Implement:

- Triage/fix code scanning alerts.
- Check key handling and dossier exports.
- Confirm no private data upload in normal workflows.
- Confirm no hidden AI/MCP call.
- Add privacy/security release checklist.

Acceptance:

- Required code scanning is green or documented accepted risk.
- API keys are never exported or uploaded.
- Private dossiers stay local.

### PR359: Final Release Gate

Phase: J.

Goal: call v1 complete.

Required evidence:

- Full Python test suite green.
- Browser tests green.
- Package checks on Linux/macOS/Windows green.
- Code scanning clean or explicitly accepted.
- Public Pages smoke green.
- Local download smoke green.
- Real-data acceptance green.
- AI eval report present.
- MCP dry run present.
- `docs/FINAL_ACCEPTANCE.md` complete.

Acceptance:

- No required failing CI checks.
- No untriaged code scanning alerts.
- No hidden paid external calls.
- No private data upload.
- User-facing limitations are honest and visible.

## 4. Parallelization Rules

Can run in parallel:

- PR342 and PR343 only if they do not edit the same UI section.
- PR343 and PR344 parser work if adapters stay in separate modules.
- PR348 and PR350 after the AI prompt manifest contract is stable.
- PR351 and PR353 after shared audit/rule references are stable.
- PR355 and PR356 if one owns scripts/tests and the other owns navigation copy.

Must not run in parallel:

- Two PRs editing the main `app/index.html` source registry section.
- Two PRs changing source-registry state vocabulary.
- Two PRs changing tracker event vocabulary.
- Data manifest/release work while source-pack generation changes.
- Final acceptance while any feature phase is still unstable.

## 5. Merge Order

Strict order unless a real blocker appears:

1. PR342 source coverage control center.
2. PR343 e-consultare/ministry tracker completion.
3. PR344 CDEP/Senate documents, votes, reports and avize.
4. PR345 Monitorul Oficial metadata-first tracking.
5. PR346 matrix workspace v1.
6. PR347 matrix evidence drilldown.
7. PR348 unified AI drafting panel.
8. PR349 BYOK/local AI execution hardening.
9. PR350 AI evaluation harness.
10. PR351 MCP runtime surface.
11. PR352 MCP workflows.
12. PR353 law-as-code authoring UX.
13. PR354 law-as-code deterministic checks.
14. PR355 public/local acceptance.
15. PR356 first-run UX/navigation cleanup.
16. PR357 real-data end-to-end acceptance.
17. PR358 security/code scanning/privacy gate.
18. PR359 final release gate.

## 6. Stop Conditions

Stop new feature work and fix immediately if:

- CI fails.
- Browser baseline fails on mobile.
- A change risks private dossier loss.
- A flow makes a legal conclusion without evidence.
- A flow sends AI/MCP data without explicit user action.
- Source update touches private data.
- The user reports the work is drifting again.

## 7. Next Action

The next implementation PR after this docs PR is PR342:

`phase-c-source-coverage-control-center`

It should be a user-facing source coverage control center. It should not start
Monitor bulk ingestion, AI, MCP or law-as-code work. Its purpose is to make the
existing source registry and coverage useful to a real user before expanding more
features.
