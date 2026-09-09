# Legislativ v1 completion checklist

Baseline: PR138 merged. This is the finite release scope accepted by the maintainer,
not a claim that the remaining milestones are already implemented. Local-first,
deterministic research and drafting; no reviewer required to operate the app.

| Milestone | Baseline status | Acceptance required before completion |
| --- | --- | --- |
| 1. Structured proposals | Implemented for supported targets; awaiting PR review | Explicit act/provision and replace/add/repeal intents, target snapshots, before/after preview, ambiguous-target rejection, free-text drafts and revision history are covered. See supported-target limits in DOSARE.md. |
| 2. Revision-linked analysis | Partial: existing checks are separate | Applicable checks run on an exact saved proposal revision; unsupported/unavailable distinct from clear; old results remain historical after edits. |
| 3. Proposal source changes | Partial: finding evidence checks exist | Proposal dependency warnings and explicit reassessment preserve original basis and draft text. |
| 4. Domain/applicability workflow | Partial: cited context exists | Known, unknown and heuristic context remain distinct in filtering/comparison; dates, territory, recipients, exceptions and classification have explicit provenance. |
| 5. Bounded Romanian/EU assessment | Partial: acquisition and search exist | National provision/proposal linked to an explicit EU obligation, supporting evidence and potential coverage/conflict/gap; missing text blocks substantive assessment. |
| 6. Everyday UX | Partial | Rename/archive dossiers, recover unfinished drafts, accessible navigation and consistent retry/error states; sharing scope clearly visible. |
| 7. Real-data acceptance | Not complete | Choose and record a bounded domain/source set; run complete workflows on actual documents, measure missing/extraction/false-positive cases and fix release blockers. Fixtures alone do not satisfy this gate. |
| 8. Release readiness | Partial: tests, migrations and backups exist | Clean install, update, realistic backup/restore and upgrade rehearsal; local/static limitations; optional AI deployment/cost audit; versioned release with known limitations. |

Each implementation PR must update this checklist with evidence and remaining scope.
The first completion batch passes 1,224 tests and desktop/mobile browser checks.
It adds schema-6 structured proposal snapshots and composer round-trip checks; it
does not complete milestone 2's broader proposal analysis or milestone 3's warnings.
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
