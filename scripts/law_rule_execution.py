"""Deterministic checks over promoted law-rule drafts.

These checks are deliberately conservative: every output is a candidate issue
for human review, never a legal verdict.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from scripts import dosare, law_rule_drafts
from scripts.servicii import _law_code_delegated_norms

CONTRACT = "law-rule-execution-v1"
ROW_CONTRACT = "law-rule-execution-row-v1"
DRAFT_TEXT_CONTRACT = "law-rule-draft-text-execution-v1"
ISSUE_CONTRACT = "law-rule-deterministic-issue-v1"

STRUCTURAL_MODALITIES = {"obligation", "procedure", "deadline", "competence"}


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


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _issue(
    *,
    code: str,
    severity: str,
    explanation: str,
    uncertainty: str,
    source: dict,
    evidence: dict | None = None,
) -> dict:
    material = {
        "code": code,
        "severity": severity,
        "explanation": explanation,
        "source": source,
        "evidence": evidence or {},
    }
    return {
        "contract": ISSUE_CONTRACT,
        "issue_id": _digest(dosare._json(material))[:32],
        "status": "candidate_issue_not_legal_verdict",
        "code": code,
        "severity": severity,
        "explanation": explanation,
        "uncertainty": uncertainty,
        "source": source,
        "evidence": evidence or {},
        "limitations": [
            "Semnal determinist pentru revizie; nu verdict juridic.",
            "Textul citat și sursa exactă rămân autoritatea.",
        ],
    }


def _rule_source(draft: dict) -> dict:
    candidate = draft.get("source_candidate") or {}
    return {
        "kind": "law_rule_draft",
        "rule_draft_id": draft["draft_id"],
        "candidate_id": draft["candidate_id"],
        "provision_id": draft.get("provision_id", ""),
        "act_id": draft.get("act_id", ""),
        "locator": draft.get("locator", ""),
        "source_hash": draft.get("source_hash", ""),
        "text_sha256": draft.get("text_sha256", ""),
        "source_url": candidate.get("source_url", ""),
        "quote": candidate.get("text") or "",
    }


def _draft_source(text: str, quote: str = "") -> dict:
    return {
        "kind": "supplied_draft_text",
        "text_sha256": _digest(text),
        "quote": quote[:1200],
    }


def _structural_issues(draft: dict, text: str, checks: dict[str, bool]) -> list[dict]:
    source = _rule_source(draft)
    issues: list[dict] = []
    modality = draft.get("modality")
    if modality == "obligation" and checks["action_found"] and not checks["actor_found"]:
        issues.append(
            _issue(
                code="obligation_actor_missing",
                severity="blocking",
                explanation=(
                    "Acțiunea regulii apare în text, dar actorul revizuit nu apare explicit."
                ),
                uncertainty=(
                    "Poate exista un actor exprimat prin sinonim, articol anterior "
                    "sau structură implicită."
                ),
                source=source,
                evidence={
                    "matched_action": draft.get("action", ""),
                    "missing_actor": draft.get("actor", ""),
                },
            )
        )
    if modality in {"procedure", "deadline"} and not checks["deadline_found"]:
        issues.append(
            _issue(
                code="procedure_deadline_missing",
                severity="material",
                explanation=(
                    "Regula revizuită cere termen/procedură, dar termenul nu este regăsit textual."
                ),
                uncertainty="Termenul poate fi exprimat diferit sau în alt articol al proiectului.",
                source=source,
                evidence={"expected_deadline": draft.get("deadline", "")},
            )
        )
    if (
        modality == "procedure"
        and checks["action_found"]
        and not (checks["condition_found"] or _contains(text, draft.get("effect", "")))
    ):
        issues.append(
            _issue(
                code="procedure_body_missing",
                severity="material",
                explanation=(
                    "Proiectul pare să atingă procedura, dar nu conține corpul/condițiile "
                    "structurii revizuite."
                ),
                uncertainty=(
                    "Parserul verifică doar câmpurile revizuite textual, nu reconstruiește "
                    "procedura completă."
                ),
                source=source,
                evidence={
                    "expected_condition": draft.get("condition", ""),
                    "expected_effect": draft.get("effect", ""),
                },
            )
        )
    if modality == "deadline" and not checks["actor_found"]:
        issues.append(
            _issue(
                code="deadline_body_missing",
                severity="material",
                explanation=(
                    "Există o regulă de termen, dar textul furnizat nu indică explicit "
                    "corpul/actorul urmărit."
                ),
                uncertainty="Actorul poate fi moștenit din titlu sau din articolul anterior.",
                source=source,
                evidence={"expected_actor": draft.get("actor", "")},
            )
        )
    return issues


def _reference_issues(text: str) -> list[dict]:
    from scripts.referinte import referinte

    issues: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ref in referinte(text):
        if not ref.locator or ref.act is not None:
            continue
        key = (ref.text, ref.locator.id)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            _issue(
                code="reference_missing_or_ambiguous_act",
                severity="material",
                explanation=(
                    "Trimiterea indică un locator, dar nu indică actul normativ în "
                    "același fragment."
                ),
                uncertainty=(
                    "Poate fi o trimitere internă legitimă dacă actul-gazdă este clar "
                    "pentru cititor."
                ),
                source=_draft_source(text, ref.text),
                evidence={"locator": ref.locator.id, "span": [ref.start, ref.end]},
            )
        )
    return issues


def _graph_issues(stare, text: str) -> tuple[list[dict], list[str]]:
    if stare is None:
        return [], ["Graful de modificări nu a fost disponibil pentru acest apel."]
    if not getattr(stare, "are_graf", lambda: False)():
        return [], [
            "Baza locală de graf nu este disponibilă; abrogările și modificările nu "
            "au fost verificate."
        ]
    try:
        from scripts.graf import _deschide_graf
        from scripts.servicii import _republicari_citate
        from scripts.vigoare import citari_calificate, citari_moarte

        graf = _deschide_graf(stare.graf, readonly=True)
        try:
            republicari = _republicari_citate(text, stare)
            issues = [
                _issue(
                    code="amends_repealed_provision",
                    severity=item.severitate,
                    explanation=item.motiv,
                    uncertainty=(
                        "Abrogarea este calificată de o republicare; locatorul trebuie "
                        "verificat manual."
                        if item.peste_republicare
                        else "Semnalul depinde de acoperirea locală a grafului."
                    ),
                    source=_draft_source(text, item.text),
                    evidence={
                        "act_id": item.act_id,
                        "locator": item.locator,
                        "whole_act": item.abrogare.este_intregul_act,
                    },
                )
                for item in citari_moarte(text, graf, republicari)
            ]
            issues.extend(
                _issue(
                    code="amends_changed_or_qualified_provision",
                    severity="material",
                    explanation=item.motiv,
                    uncertainty="Semnalul indică suspendare/derogare/prorogare, nu abrogare.",
                    source=_draft_source(text, item.text),
                    evidence={
                        "act_id": item.act_id,
                        "locator": item.locator,
                        "qualification": item.eticheta,
                    },
                )
                for item in citari_calificate(text, graf, republicari)
            )
            return issues, []
        finally:
            graf.close()
    except (OSError, sqlite3.Error, ValueError):
        return [], ["Graful local nu a putut fi citit; verificarea abrogărilor a fost omisă."]


def _delegated_issues(draft: dict, matched: list[dict]) -> list[dict]:
    source = _rule_source(draft)
    issues: list[dict] = []
    for check in matched:
        evidence = check.get("evidence") or {}
        issues.append(
            _issue(
                code="delegated_norm_missing",
                severity=check.get("severity") or check.get("severitate") or "material",
                explanation=check.get("summary")
                or check.get("explanation")
                or "Norma delegată așteptată nu a fost găsită în raportul local.",
                uncertainty=(
                    "Lipsa depinde de acoperirea corpusului și de tipul de instrument căutat."
                ),
                source=source,
                evidence={
                    "local_check_status": check.get("status", ""),
                    "expected_instrument": evidence.get("expected_instrument")
                    or check.get("expected_instrument")
                    or "",
                    "near_candidates": evidence.get("near_candidates") or [],
                    "quote": evidence.get("quote") or "",
                },
            )
        )
    return issues


def _eu_link_issues(path, dossier_id: str, text: str) -> tuple[list[dict], list[str]]:
    if not Path(path).exists():
        return [], ["Legăturile UE salvate nu sunt disponibile fără baza de dosare."]
    try:
        with dosare._open(path) as con:
            if con.execute("PRAGMA user_version").fetchone()[0] < 9:
                return [], ["Schema dosarelor nu include încă legături UE salvate."]
            rows = con.execute(
                "SELECT l.rezultat_json FROM legaturi_ue l "
                "JOIN propuneri p ON p.id=l.propunere_id "
                "JOIN rulari r ON r.id=p.rulare_id "
                "WHERE r.dosar_id=? ORDER BY l.seq DESC LIMIT 20",
                (dossier_id,),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return [], ["Legăturile UE salvate nu au putut fi citite."]
    issues: list[dict] = []
    for row in rows:
        try:
            result = json.loads(row["rezultat_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        candidate = result.get("substantive_candidate") or {}
        if candidate.get("ipoteza") != "potential_conflict":
            continue
        obligation = candidate.get("obligatie") or ""
        celex = ((result.get("baza") or {}).get("selection") or {}).get("celex", "")
        overlap = _contains(text, obligation[:160]) or _contains(text, celex)
        if not overlap and obligation:
            words = [w for w in obligation.casefold().split() if len(w) > 6]
            overlap = sum(1 for word in words[:20] if word in text.casefold()) >= 3
        if overlap:
            issues.append(
                _issue(
                    code="selected_eu_article_potential_conflict",
                    severity="material",
                    explanation=(
                        "Textul proiectului se suprapune cu o legătură UE salvată ca "
                        "ipoteză de conflict."
                    ),
                    uncertainty=(
                        "Ipoteza UE este declarată de autor și trebuie verificată cu "
                        "articolul UE citat."
                    ),
                    source={
                        "kind": "saved_eu_link",
                        "celex": celex,
                        "article_locator": ((result.get("baza") or {}).get("selection") or {}).get(
                            "locator", ""
                        ),
                        "link_state": result.get("state", ""),
                        "quote": obligation[:1200],
                    },
                    evidence={
                        "hypothesis": candidate.get("ipoteza"),
                        "reason": candidate.get("motiv", ""),
                    },
                )
            )
    if not rows:
        return issues, [
            "Nu există legături UE salvate pentru acest dosar; conflictul UE nu a fost verificat."
        ]
    return issues, []


def _draft_text_row(draft: dict, text: str, delegated: list[dict]) -> dict:
    checks = {
        "actor_found": _contains(text, draft.get("actor", "")),
        "action_found": _contains(text, draft.get("action", "")),
        "deadline_found": _contains(text, draft.get("deadline", "")),
        "condition_found": _contains(text, draft.get("condition", "")),
    }
    issues = [*_structural_issues(draft, text, checks), *_delegated_issues(draft, delegated)]
    expected = [key for key, value in checks.items() if value]
    missing = [key for key, value in checks.items() if not value]
    if issues:
        status = "candidate_issue_not_verdict"
    elif checks["actor_found"] and checks["action_found"]:
        status = "possible_match_not_verdict"
    else:
        status = "partial_match_needs_review" if expected else "no_local_text_signal"
    return {
        "contract": DRAFT_TEXT_CONTRACT + "-row",
        "rule_draft_id": draft["draft_id"],
        "candidate_id": draft["candidate_id"],
        "status": status,
        "act_id": draft["act_id"],
        "locator": draft["locator"],
        "modality": draft["modality"],
        "source_hash": draft["source_hash"],
        "source": _rule_source(draft),
        "checks": checks,
        "matched_fields": expected,
        "missing_fields": missing,
        "issue_candidates": issues,
        "candidate_issues": len(issues),
        "limitations": [
            "Potrivire textuală deterministă pe proiectul furnizat; nu verdict juridic.",
            "Sinonimele, trimiterile implicite și structurarea pe articole necesită revizie umană.",
        ],
    }


def _checks_by_rule(stare, act_id: str, limit: int) -> dict[tuple[str, str, str], list[dict]]:
    if stare is None or not hasattr(stare, "vid"):
        return {}
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
    issues = _delegated_issues(draft, checks)
    candidate = bool(issues)
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
        "issue_candidates": issues,
        "candidate_issues": len(issues),
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


def draft_text(path, request: dict, stare=None) -> dict:
    """Execute promoted rule drafts against a supplied draft/project text."""
    dossier_id = dosare._id(request.get("id", ""))
    act_id = dosare._text(request.get("act", ""), 200)
    limit = _limit(int(request.get("limit", 50)))
    text = _draft_text(request.get("text", ""))
    drafts = law_rule_drafts.lista(path, dossier_id, act_id=act_id)
    eligible = [
        draft for draft in drafts["items"] if draft.get("modality") in STRUCTURAL_MODALITIES
    ][:limit]
    delegated_available = stare is not None and hasattr(stare, "vid")
    delegated = _checks_by_rule(stare, act_id, max(limit, len(eligible), 1))
    rows = [_draft_text_row(draft, text, _matched_checks(draft, delegated)) for draft in eligible]
    reference_issues = _reference_issues(text)
    graph_issues, graph_limitations = _graph_issues(stare, text)
    eu_issues, eu_limitations = _eu_link_issues(path, dossier_id, text)
    global_issues = [*reference_issues, *graph_issues, *eu_issues]
    issue_count = sum(row["candidate_issues"] for row in rows) + len(global_issues)
    return {
        "contract": DRAFT_TEXT_CONTRACT,
        "status": "deterministic_draft_text_rule_check",
        "dosar_id": dossier_id,
        "text_sha256": _digest(text),
        "total_rule_drafts": drafts["total"],
        "eligible_rule_drafts": len(eligible),
        "returned": len(rows),
        "possible_matches": sum(1 for row in rows if row["status"] == "possible_match_not_verdict"),
        "partial_matches": sum(1 for row in rows if row["status"] == "partial_match_needs_review"),
        "candidate_issues": issue_count,
        "issue_candidates": global_issues,
        "checks": {
            "reviewed_rule_text_match": True,
            "structural_fields": True,
            "reference_resolution": True,
            "graph_repeal_or_change": not graph_limitations,
            "delegated_norms": delegated_available,
            "saved_eu_links": not eu_limitations,
        },
        "rows": rows,
        "limitations": [
            "Primește textul proiectului de la utilizator sau dintr-un import explicit.",
            "Nu decide conformitate; marchează doar câmpurile de regulă regăsite textual.",
            "Nu trimite textul la AI și nu consultă surse externe.",
            *(
                []
                if delegated_available
                else ["Raportul local de norme delegate nu este disponibil."]
            ),
            *graph_limitations,
            *eu_limitations,
        ],
    }
