# Legislativ v1 completion checklist

Baseline: PR140 merged. This is the finite release scope accepted by the maintainer,
not a claim that the remaining milestones are already implemented. Local-first,
deterministic research and drafting; no reviewer required to operate the app.

| Milestone | Baseline status | Acceptance required before completion |
| --- | --- | --- |
| 1. Structured proposals | Merged in PR139 for supported targets | Explicit act/provision and replace/add/repeal intents, target snapshots, before/after preview, ambiguous-target rejection, free-text drafts and revision history are covered. See supported-target limits in DOSARE.md. |
| 2. Revision-linked analysis | Merged in PR140 for bounded deterministic checks | Explicit saved-revision checks, immutable input/source hashes, distinct partial/unavailable/unsupported states, history, retry, exact-revision exports and no carryover after edits. Five adapters are supported; broader legal assessments remain explicitly unsupported here. See DOSARE.md. |
| 3. Proposal source changes | Implemented; awaiting PR review | Explicit captured-source comparison, metadata/content distinction, bounded before/after text, changed/unavailable states, linked reassessment, retry and immutable history/export. Original basis and unsaved draft text remain intact. See PROPOSAL_SOURCE_CHANGES.md. |
| 4. Domain/applicability workflow | Partial: cited context exists | Known, unknown and heuristic context remain distinct in filtering/comparison; dates, territory, recipients, exceptions and classification have explicit provenance. |
| 5. Bounded Romanian/EU assessment | Partial: acquisition and search exist | National provision/proposal linked to an explicit EU obligation, supporting evidence and potential coverage/conflict/gap; missing text blocks substantive assessment. |
| 6. Everyday UX | Partial | Rename/archive dossiers, recover unfinished drafts, accessible navigation and consistent retry/error states; sharing scope clearly visible. |
| 7. Real-data acceptance | Not complete | Choose and record a bounded domain/source set; run complete workflows on actual documents, measure missing/extraction/false-positive cases and fix release blockers. Fixtures alone do not satisfy this gate. |
| 8. Release readiness | Partial: tests, migrations and backups exist | Clean install, update, realistic backup/restore and upgrade rehearsal; local/static limitations; optional AI deployment/cost audit; versioned release with known limitations. |

Each implementation PR must update this checklist with evidence and remaining scope.
The first completion batch passed 1,224 tests and desktop/mobile browser checks.
The second batch passes 1,258 tests and adds schema-7 analysis records and captured source snapshots, with
tests for revision/ownership isolation, source bounds, migration rollback, concurrent
retry, history and export. Desktop/mobile checks cover lost-response retry after commit,
pending navigation, unsaved text preservation, historical selection and pagination.
Milestones 1/2/3 are implemented within their documented scope; five milestones remain.
The third batch adds explicit source comparison and linked reassessment with no new
schema migration. Source-change workflows pass 1,271 tests and desktop/mobile checks.
Parallel branches prepare milestones 4/6 and acceptance/release rehearsal; those are
not marked complete here until their own implementations are integrated and verified.
Passing unit tests does not establish source completeness or legal accuracy.
The baseline has 1,205 passing tests, proposal revision comparison/export, source
inventory/acquisition, immutable saved evidence and manual evidence checking.

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
