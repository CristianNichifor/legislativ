# Legislativ v1 completion checklist

Baseline: PR140 merged. This is the finite release scope accepted by the maintainer,
not a claim that the remaining milestones are already implemented. Local-first,
deterministic research and drafting; no reviewer required to operate the app.

| Milestone | Baseline status | Acceptance required before completion |
| --- | --- | --- |
| 1. Structured proposals | Merged in PR139 for supported targets | Explicit act/provision and replace/add/repeal intents, target snapshots, before/after preview, ambiguous-target rejection, free-text drafts and revision history are covered. See supported-target limits in DOSARE.md. |
| 2. Revision-linked analysis | Merged in PR140 for bounded deterministic checks | Explicit saved-revision checks, immutable input/source hashes, distinct partial/unavailable/unsupported states, history, retry, exact-revision exports and no carryover after edits. Five adapters are supported; broader legal assessments remain explicitly unsupported here. See DOSARE.md. |
| 3. Proposal source changes | Merged in PR141 | Explicit captured-source comparison, metadata/content distinction, bounded before/after text, changed/unavailable states, linked reassessment, retry and immutable history/export. Original basis and unsaved draft text remain intact. See PROPOSAL_SOURCE_CHANGES.md. |
| 4. Domain/applicability workflow | Merged in PR142 for saved-finding context | Filter and compare loaded target/context revisions by field, declared-known/unknown/heuristic state, value and citation. Dates, territory, recipients, exceptions and classification retain author/source provenance; no applicability verdict or global cross-domain inference. See APPLICABILITY_WORKFLOW.md. |
| 5. Bounded Romanian/EU assessment | Implemented for structured proposals / retained EU articles; awaiting PR review | Explicit saved proposal revision, retained EU snapshot/article and exact body quote; author-declared potential coverage/conflict/gap with reason. Missing bodies, unresolved targets and invalid hashes block linking. Schema 9 retains immutable basis, retry, history/export; no automated compliance verdict. See LEGATURI_UE.md. |
| 6. Everyday UX | Merged in PR143 for local dossiers/editor | Rename/archive and restore dossiers, explicitly preserve/recover/delete editor and finding drafts, keyboard tab navigation, conflict/retry states and local storage/sharing disclosures. Recovery is manual, not autosave; see DOSARE.md for excluded transient forms. Schema 8 adds dossier metadata and recovery copies. |
| 7. Real-data acceptance | Bounded runtime path measured, not complete | The 2026-09-11 pilot release passed activation, search, workbench save as `fisa-act-v1` and private rollback survival. Missing/extraction/false-positive measurements remain incomplete, and the run had 0 authentic gap/CCR findings, so real finding-to-proposal save still needs reviewed data/wording. See V1_ACCEPTANCE.md. |
| 8. Release readiness | Rehearsal implemented; deployment sign-off pending | Isolated clean-runtime, populated backup/restore and schema 7 -> 9 rehearsal in V1_RELEASE_REHEARSAL.md. Actual deployment inventory, install/update, complete database/document backup, AI cost ownership and versioned release remain unverified. |

Each implementation PR must update this checklist with evidence and remaining scope.
The first completion batch passed 1,224 tests and desktop/mobile browser checks.
The second batch passes 1,258 tests and adds schema-7 analysis records and captured source snapshots, with
tests for revision/ownership isolation, source bounds, migration rollback, concurrent
retry, history and export. Desktop/mobile checks cover lost-response retry after commit,
pending navigation, unsaved text preservation, historical selection and pagination.
Milestones 1 through 6 are implemented within their documented scope; two milestones remain.
The third batch adds explicit source comparison and linked reassessment with no new
schema migration. Source-change workflows pass 1,271 tests and desktop/mobile checks.
The integrated source/context workflow passes 1,272 tests and desktop/mobile checks.
Integrated usability passes 1,296 tests, including a regression
for edits made during a recovery save and validation of restored draft records.
The offline schema-7 to schema-8 rehearsal preserves historical exports and verifies
pre/post-upgrade backups. Release preparation alone does not satisfy real-data acceptance.
The integrated EU workflow passes 1,322 tests. The isolated schema-7 to schema-9
rehearsal preserves reassessment history, recovery copies, archived metadata and
a synthetic EU link through backup/restore and offline history/export retries.
This fixture evidence is not real-data domain acceptance or a deployment audit.
The complete integrated preparation batch passes 1,333 tests, repository-wide
Ruff checks, desktop/mobile workflows and a fresh dependency-free Python rehearsal
(normal and optimized execution). See V1_RELEASE_REHEARSAL.md and its current JSON.
Passing unit tests does not establish source completeness or legal accuracy.
The baseline has 1,205 passing tests, proposal revision comparison/export, source
inventory/acquisition, immutable saved evidence and manual evidence checking.
The act workbench save flow reuses local dossiers for search-origin law dossiers:
`filtre.act` runs save as `fisa-act-v1`, preserve act-scoped gap/CCR examples,
project and UE context, and reopen through the same saved-run UI. Focused storage,
review/evidence and desktop/mobile browser checks pass.
The real-data acceptance runner now exercises the public-release activation path,
search, private dossier persistence, law workbench save as `fisa-act-v1` and
rollback survival without a synthetic finding. Domain acceptance remains pending
until it is run against the approved release folder and reviewer-approved
finding/proposal evidence exists.
The 2026-09-11 bounded pilot run is recorded in
`docs/v1_acceptance_pilot_2026-09-11.json`: 2 authentic acts, 1,635 provisions,
3 search results, 8 EU references signaled, 0 imported EU texts, 0 reviewable
gap/CCR findings, and rollback survival passed. It proves the local/public runtime
path, not legal coverage, EU-law assessment or proposal correctness.

## Execution order

1. Finish structured targeting before proposal checks and source reassessment.
2. Complete everyday workflow gaps alongside those integrations where ownership is separate.
3. Add source-backed context filtering and a bounded EU obligation workflow.
4. Run real-data acceptance and release rehearsals; fix their blockers, freeze scope and release.

No bulk source crawl, paid inference, external publication or PR merge is authorized
implicitly by this checklist. The pilot domain and actual deployed data/configuration
must be recorded before declaring milestones 7/8 complete. A functional pilot can
run without a legal reviewer; validated legal-reliability claims cannot.

## Outside v1

Independently evaluated AI reasoning, MCP integration, hosted collaboration,
broader-domain/OCR coverage and automatic monitoring remain separate tracks.
Do not add them as new v1 completion requirements.

The original `/home/cristianvn/legislativ-evolution-plan.md` is a PR120-era strategic
document. This checked-in checklist supersedes its delivery-status assumptions,
while retaining evidence provenance, unknown states and no automatic legal verdicts.
