# Final Acceptance

Generated: `2026-09-14T23:03:33.474219+00:00`

Commit: `808fc26255c5`

Status: **blocked**

This file is generated from the current product gates. It is not a legal
accuracy claim and it does not replace human domain review.

## Completeness Gate

- Contract: `app-completeness-gate-v1`.
- Completion claim allowed: `false`.
- Summary: `{"missing": 0, "partial": 2, "ready": 7, "total": 9}`.
- Source status: `blocked`.
- Missing required source families: `0`.
- Unsynced required source families: `12`.
- Source attention rows: `0`.

| Gate | Status | Evidence |
| --- | --- | --- |
| Local data separation | ready | Public datasets, private dossier storage and browser-local workspace boundaries are documented and implemented. |
| Public source data availability | partial | Source portfolio and availability dashboard exist, but the current runtime must have every required source family present and out of attention state. |
| Dossier workflow | ready | The vertical runner creates a dossier, saves a source-backed note and assembles an evidence pack. |
| Matrix-to-dossier | ready | The final vertical flow proves matrix drilldown can feed the same dossier evidence path. |
| Lifecycle tracking | partial | Local source registry, tracker events and parliamentary lifecycle stages exist; full lifecycle coverage depends on complete source availability. |
| EU issue note | ready | EU issue notes are source-backed, local-only, hash-preserving and explicitly non-verdict. |
| AI/MCP bounded draft | ready | AI and MCP draft paths produce bounded prompts from selected evidence and require explicit user action. |
| Export, backup and restore | ready | Dossier SQLite backup, browser export/import/restore and historical export preservation are implemented and tested. |
| No hidden legal verdicts | ready | Visible contracts preserve unknown legal effect, human review status and non-verdict notices. |

## Current Blockers

- `public_source_data_availability`: partial - 1 surse nu au încă sync reușit în Legislație română.; 1 surse nu au încă sync reușit în Proiecte parlamentare.; 1 surse nu au încă sync reușit în Camera Deputaților.; 1 surse nu au încă sync reușit în Senat.; 1 surse nu au încă sync reușit în Consultări Guvern.; 1 surse nu au încă sync reușit în Consultări publice · e-consultare.; 1 surse nu au încă sync reușit în Consultări ministere.; 1 surse nu au încă sync reușit în Monitorul Oficial.; 1 surse nu au încă sync reușit în Monitorul Oficial · Partea I.; 1 surse nu au încă sync reușit în Decizii CCR.; 1 surse nu au încă sync reușit în Avize și opinii instituționale.; 1 surse nu au încă sync reușit în Drept UE · Cellar/EUR-Lex.
- `lifecycle_tracking`: partial - Lifecycle tracking is bounded until public-source coverage is complete and current.

## Source Anchor Sync

- Not run in this report.

## Vertical Acceptance

- Status: `passed`.
- Contract: `final-v1-vertical-acceptance-flow-v1`.
- Checks: `{"draft_is_evidence_bound": true, "evidence_pack_has_note_and_events": true, "manifest_valid": true, "matrix_has_drilldown": true, "mcp_executor_records_approved_audit": true, "mcp_uses_same_project": true, "private_backup_restores_ai_rules_and_audit": true, "rule_candidate_is_source_bound": true, "rule_draft_is_promoted_not_verdict": true, "search_finds_law": true, "workbench_tracks_project": true}`.
- Summary: `{"draft_tokens": 646, "evidence_events": 2, "evidence_notes": 1, "law_rule_drafts": 1, "matrix_entries": {"acte": 1, "neconstitutionale": 0, "prevederi": 1, "proiecte": 1, "referinte_ue": 1, "surse_atentie": 0, "surse_incarcate": 0, "surse_lipsa": 1, "surse_partiale": 0, "surse_revizuibile": 0, "surse_stale": 0, "viduri": 1}, "mcp_audit_events": 1, "mcp_timeline_events": 2, "rule_candidates": 1, "search_results": 2, "workbench_rows": 3}`.

## Real Data Evidence

- Real pilot pack: `ready`.
- Domain: `bounded public procurement`.
- Acceptance command: `uv run python -m scripts.acceptare_date_reale /tmp/legislativ-v1-pilot-release --min-acts 2 --pilot-act lege-98-2016 --require-reviewable-finding --require-eu-text`.
- Historical pilot acceptance: `pilot_runtime_path_passed_domain_acceptance_pending`.
- Fixture rehearsal: `fixture_rehearsal_passed`.
- AI eval schema: `unknown`.

## Release Commands

```bash
uv run python -m scripts.app_completeness --data-home ~/.local/share/legislativ --sync-source-anchors --require-complete
uv run python -m scripts.real_pilot_pack
uv run python -m scripts.v1_rehearsal
uv run python -m scripts.acceptare_date_reale /tmp/legislativ-v1-pilot-release --min-acts 2 --pilot-act lege-98-2016 --require-reviewable-finding --require-eu-text
```

## Limitations

- This gate reports current evidence; it does not fetch public sources or call AI/MCP.
- Partial capabilities block a completion claim even when bounded workflows pass.
- Legal correctness, recall and compliance remain human/domain acceptance questions.
- Legal correctness, precision and recall require independent adjudication.
- AI/MCP output remains draft evidence for human review, never a verdict.
- Private dossiers must remain local and outside public dataset manifests.
