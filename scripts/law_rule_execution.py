"""First deterministic checks over promoted law-rule drafts."""

from __future__ import annotations

from scripts import dosare, law_rule_drafts
from scripts.servicii import _law_code_delegated_norms

CONTRACT = "law-rule-execution-v1"
ROW_CONTRACT = "law-rule-execution-row-v1"
DRAFT_TEXT_CONTRACT = "law-rule-draft-text-execution-v1"


def _limit(value) -> int:
    if type(value) is not int or not 1 <= value <= 200:
        raise ValueError("Limită invalidă.")
    return value


def _draft_text(value) -> str:
    if not isinstance(value, str):
        raise ValueError("Text proiect invalid.")
    value = value.strip()
    if not value:
        raise ValueError("Text proiect lipsă.")
    if len(value) > 120_000:
        raise ValueError("Text proiect prea lung.")
    return value


def _contains(text: str, value: str) -> bool:
    return bool(value and value.casefold() in text.casefold())


def _draft_text_row(draft: dict, text: str) -> dict:
    checks = {
        "actor_found": _contains(text, draft.get("actor", "")),
        "action_found": _contains(text, draft.get("action", "")),
        "deadline_found": _contains(text, draft.get("deadline", "")),
        "condition_found": _contains(text, draft.get("condition", "")),
    }
    expected = [key for key, value in checks.items() if value]
    missing = [key for key, value in checks.items() if not value]
    status = (
        "possible_match_not_verdict"
        if checks["actor_found"] and checks["action_found"]
        else ("partial_match_needs_review" if expected else "no_local_text_signal")
    )
    return {
        "contract": DRAFT_TEXT_CONTRACT + "-row",
        "rule_draft_id": draft["draft_id"],
        "candidate_id": draft["candidate_id"],
        "status": status,
        "act_id": draft["act_id"],
        "locator": draft["locator"],
        "modality": draft["modality"],
        "source_hash": draft["source_hash"],
        "checks": checks,
        "matched_fields": expected,
        "missing_fields": missing,
        "limitations": [
            "Potrivire textuală deterministă pe proiectul furnizat; nu verdict juridic.",
            "Sinonimele, trimiterile implicite și structurarea pe articole necesită revizie umană.",
        ],
    }


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


def draft_text(path, request: dict) -> dict:
    """Execute promoted rule drafts against a supplied draft/project text."""
    dossier_id = dosare._id(request.get("id", ""))
    act_id = dosare._text(request.get("act", ""), 200)
    limit = _limit(int(request.get("limit", 50)))
    text = _draft_text(request.get("text", ""))
    drafts = law_rule_drafts.lista(path, dossier_id, act_id=act_id)
    eligible = [
        draft
        for draft in drafts["items"]
        if draft.get("modality") in {"obligation", "procedure", "deadline", "competence"}
    ][:limit]
    rows = [_draft_text_row(draft, text) for draft in eligible]
    return {
        "contract": DRAFT_TEXT_CONTRACT,
        "status": "deterministic_draft_text_rule_check",
        "dosar_id": dossier_id,
        "total_rule_drafts": drafts["total"],
        "eligible_rule_drafts": len(eligible),
        "returned": len(rows),
        "possible_matches": sum(1 for row in rows if row["status"] == "possible_match_not_verdict"),
        "partial_matches": sum(1 for row in rows if row["status"] == "partial_match_needs_review"),
        "rows": rows,
        "limitations": [
            "Primește textul proiectului de la utilizator sau dintr-un import explicit.",
            "Nu decide conformitate; marchează doar câmpurile de regulă regăsite textual.",
            "Nu trimite textul la AI și nu consultă surse externe.",
        ],
    }
