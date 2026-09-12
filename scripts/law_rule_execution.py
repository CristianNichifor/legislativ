"""First deterministic checks over promoted law-rule drafts."""

from __future__ import annotations

from scripts import dosare, law_rule_drafts
from scripts.servicii import _law_code_delegated_norms

CONTRACT = "law-rule-execution-v1"
ROW_CONTRACT = "law-rule-execution-row-v1"


def _limit(value) -> int:
    if type(value) is not int or not 1 <= value <= 200:
        raise ValueError("Limită invalidă.")
    return value


def _checks_by_rule(stare, act_id: str, limit: int) -> dict[tuple[str, str, str], list[dict]]:
    qs = {"limita": [str(limit)]}
    if act_id:
        qs["act"] = [act_id]
    report = _law_code_delegated_norms(qs, stare)
    out: dict[tuple[str, str, str], list[dict]] = {}
    for check in report.get("checks", []):
        keys = {
            (check.get("provision_id") or "", "", ""),
            ("", check.get("act_id") or "", check.get("locator") or ""),
        }
        for key in keys:
            if any(key):
                out.setdefault(key, []).append(check)
    return out


def _matched_checks(draft: dict, checks: dict[tuple[str, str, str], list[dict]]) -> list[dict]:
    return [
        *checks.get((draft.get("provision_id") or "", "", ""), []),
        *checks.get(("", draft.get("act_id") or "", draft.get("locator") or ""), []),
    ]


def _row(draft: dict, checks: list[dict]) -> dict:
    candidate = bool(checks)
    return {
        "contract": ROW_CONTRACT,
        "rule_draft_id": draft["draft_id"],
        "candidate_id": draft["candidate_id"],
        "status": "candidate_issue_not_verdict" if candidate else "no_local_candidate_signal",
        "check": "delegated_norm_not_found",
        "provision_id": draft["provision_id"],
        "act_id": draft["act_id"],
        "locator": draft["locator"],
        "modality": draft["modality"],
        "source_hash": draft["source_hash"],
        "text_sha256": draft["text_sha256"],
        "matched_checks": checks,
        "actions": [
            {"type": "open_rule_draft", "id": draft["draft_id"], "eticheta": "vezi ciorna"},
            {
                "type": "open_provision",
                "act_id": draft["act_id"],
                "locator": draft["locator"],
                "eticheta": "vezi prevederea",
            },
        ],
        "limitations": [
            "Execuție deterministă pe ciorne law-rule-draft-v1; nu este verdict juridic.",
            "Lipsa unui semnal local nu dovedește că norma de implementare există.",
            "Semnalele depind de acoperirea corpusului și de raportul local "
            "al obligațiilor neîndeplinite.",
        ],
    }


def delegated_norms(stare, path, dossier_id: str, *, act_id: str = "", limit: int = 50) -> dict:
    dossier_id = dosare._id(dossier_id)
    act_id = dosare._text(act_id, 200)
    limit = _limit(limit)
    drafts = law_rule_drafts.lista(path, dossier_id, act_id=act_id)
    eligible = [
        draft
        for draft in drafts["items"]
        if draft.get("modality") in {"obligation", "procedure", "deadline", "competence"}
    ]
    checks = _checks_by_rule(stare, act_id, max(limit, len(eligible), 1))
    rows = [_row(draft, _matched_checks(draft, checks)) for draft in eligible[:limit]]
    return {
        "contract": CONTRACT,
        "status": "deterministic_rule_draft_check_preview",
        "check": "delegated_norm_not_found",
        "dosar_id": dossier_id,
        "total_rule_drafts": drafts["total"],
        "eligible_rule_drafts": len(eligible),
        "returned": len(rows),
        "candidate_issues": sum(
            1 for row in rows if row["status"] == "candidate_issue_not_verdict"
        ),
        "truncated": len(eligible) > limit,
        "rows": rows,
        "limitations": [
            "Consumă doar ciorne de reguli promovate, legate de sursa exactă.",
            "Nu execută reguli ca adevăr juridic și nu aprobă constatări.",
            "Verificarea este limitată la norma delegată negăsită în raportul local.",
        ],
    }
