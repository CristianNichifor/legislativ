"""Source-backed Romanian/EU issue notes, saved as manual dossier notes.

This module resolves already-retained local sources only. It does not fetch,
translate, call AI or decide whether national law complies with EU law.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts import achizitii_proiecte, documente_proiecte, dosare, legaturi_ue, note_manuale

CONTRACT = "ro-eu-issue-note-v1"
ISSUE_STATES = {
    "possible_conflict": "Conflict posibil",
    "possible_gap": "Lacună posibilă",
    "possible_coverage": "Acoperire posibilă",
}
LIMITATIONS = [
    "Notă de lucru revizuibilă, nu verdict juridic sau aviz.",
    "Sursele sunt citate din copii locale deja păstrate; nu se descarcă nimic în acest flux.",
    "Limba, hash-ul și incertitudinea sunt păstrate explicit.",
    "Aplicabilitatea, transpunerea și actualitatea juridică rămân pentru revizie umană.",
]
PROPOSAL_CONTEXT_LIMITATIONS = [
    "Context pentru propunere, nu verdict de conformitate.",
    "Autorul trebuie să verifice aplicabilitatea, transpunerea, actualitatea și textul oficial.",
    "Folosește numai citatele și hash-urile salvate în această notă.",
]
PREVIEW_FIELDS = {"dosar_id", "national", "eu", "issue_state"}
SAVE_FIELDS = PREVIEW_FIELDS | {"id", "base_sha256", "title", "uncertainty", "rationale", "status"}


def _sha(value) -> str:
    return hashlib.sha256(dosare._json(value).encode()).hexdigest()


def _source_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _text(value, limit: int, *, required: bool = False) -> str:
    try:
        return dosare._text(value, limit, required)
    except ValueError as exc:
        raise ValueError("Câmp invalid în nota UE.") from exc


def _issue_state(value) -> str:
    key = str(value or "").strip().lower().replace("-", "_")
    if key not in ISSUE_STATES:
        raise ValueError("Stare a ipotezei UE invalidă.")
    return key


def _excerpt(text: str, limit: int = 1800) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _national_provision(stare, data: dict) -> tuple[dict | None, list[dict]]:
    act_id = _text(data.get("act_id"), 200, required=True)
    locator = _text(data.get("locator"), 120, required=True)
    path = getattr(stare, "corpus", None)
    if path is None:
        return None, [{"side": "national", "code": "corpus_unavailable"}]
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            con.execute("BEGIN")
            act = con.execute(
                "SELECT id,titlu,sursa_url,citit_la FROM acte WHERE id=?", (act_id,)
            ).fetchone()
            rows = con.execute(
                "SELECT locator,ord,text,vigoare_de_la,vigoare_pana_la FROM provizii "
                "WHERE act_id=? AND locator=? ORDER BY ord LIMIT 51",
                (act_id, locator),
            ).fetchall()
    except (OSError, sqlite3.Error):
        return None, [{"side": "national", "code": "corpus_unavailable"}]
    if not act:
        return None, [{"side": "national", "code": "act_missing"}]
    if not rows:
        return None, [{"side": "national", "code": "locator_missing"}]
    if len(rows) > 50:
        return None, [{"side": "national", "code": "capture_limit"}]
    text = "\n".join(r["text"] or "" for r in rows).strip()
    if not text:
        return None, [{"side": "national", "code": "missing_text"}]
    evidence = {
        "kind": "prevedere",
        "act_id": act_id,
        "locator": locator,
        "language": "RON",
        "quote": _excerpt(text),
        "text_sha256": _source_sha(text),
        "source_url": act["sursa_url"] or "",
        "captured_at": act["citit_la"] or "",
        "title": act["titlu"] or act_id,
        "provisions": [dict(r) for r in rows],
    }
    return evidence, []


def _national_project(stare, data: dict) -> tuple[dict | None, list[dict]]:
    plx = _text(data.get("plx"), 120, required=True)
    version_id = _text(data.get("version_id"), 64)
    try:
        meta = achizitii_proiecte.detaliu(stare, plx)
    except (OSError, sqlite3.Error, ValueError):
        return None, [{"side": "national", "code": "project_unavailable"}]
    if not version_id:
        if len(meta.get("versiuni") or []) == 1:
            version_id = meta["versiuni"][0]["id"]
        else:
            return None, [{"side": "national", "code": "project_version_required"}]
    try:
        version = documente_proiecte.citeste(stare, plx, version_id)
    except (OSError, sqlite3.Error, ValueError):
        return None, [{"side": "national", "code": "project_version_missing"}]
    text = (version.get("text") or "").strip()
    if not text:
        return None, [{"side": "national", "code": "missing_text"}]
    evidence = {
        "kind": "proiect",
        "plx": plx,
        "version_id": version["id"],
        "language": "RON",
        "quote": _excerpt(text),
        "text_sha256": _source_sha(text),
        "source_url": version.get("url") or meta.get("fisa_url") or "",
        "captured_at": version.get("preluat_la") or meta.get("citit_la") or "",
        "title": meta.get("titlu") or plx,
        "stage": meta.get("stadiu") or "",
        "status": version.get("status") or "",
        "document_sha256": version.get("sha256") or "",
    }
    return evidence, []


def _national(stare, data) -> tuple[dict | None, list[dict]]:
    if not isinstance(data, dict):
        raise ValueError("Dovadă națională invalidă.")
    kind = str(data.get("kind") or "").strip().lower()
    if kind == "prevedere":
        return _national_provision(stare, data)
    if kind == "proiect":
        return _national_project(stare, data)
    raise ValueError("Tip de dovadă națională invalid.")


def _eu(stare, data) -> tuple[dict | None, list[dict]]:
    if not isinstance(data, dict):
        raise ValueError("Dovadă UE invalidă.")
    celex = _text(data.get("celex"), 50, required=True).upper()
    snapshot_id = _text(data.get("instantanee"), 64, required=True)
    locator = _text(data.get("locator"), 80, required=True)
    snapshot, blockers = legaturi_ue._eu(stare, celex, snapshot_id)
    if blockers:
        return None, blockers
    articles, blockers = legaturi_ue._articles(snapshot)
    if blockers:
        return None, blockers
    matches = [a for a in articles if a["locator"] == locator]
    if len(matches) != 1 or not matches[0].get("selectabil"):
        return None, [{"side": "eu", "code": "ambiguous_or_missing_locator"}]
    article = matches[0]
    body = legaturi_ue.article_body(article)
    if not body:
        return None, [{"side": "eu", "code": "missing_text"}]
    source = snapshot["sursa"]
    evidence = {
        "kind": "eu_article",
        "celex": celex,
        "instantanee": snapshot_id,
        "locator": locator,
        "language": source["limba"],
        "quote": _excerpt(body),
        "article_sha256": _sha(article),
        "text_sha256": source["text_sha256"],
        "source_url": source.get("item_url") or source.get("sursa_url") or "",
        "captured_at": source.get("citit_la") or "",
        "title": source.get("titlu") or celex,
        "article": article,
    }
    return evidence, []


def _selection(request: dict, fields: set[str]) -> dict:
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError("Cerere de notă UE invalidă.")
    return {
        "dosar_id": dosare._id(request["dosar_id"]),
        "national": request["national"],
        "eu": request["eu"],
        "issue_state": _issue_state(request["issue_state"]),
    }


def preview(stare, request: dict) -> dict:
    selected = _selection(request, PREVIEW_FIELDS)
    dosare.citeste(dosare.cale(stare), selected["dosar_id"])
    national, blockers = _national(stare, selected["national"])
    eu, eu_blockers = _eu(stare, selected["eu"])
    blockers += eu_blockers
    base = {
        "contract": CONTRACT,
        "selection": selected,
        "issue_state": selected["issue_state"],
        "national_evidence": national,
        "eu_evidence": eu,
        "blockers": blockers,
        "legal_effect": "unknown",
    }
    if len(dosare._json(base).encode()) > dosare.MAX_REPORT_BYTES:
        raise ValueError("Baza notei UE depășește limita de 4 MB.")
    return {
        "contract": CONTRACT,
        "state": "blocked_evidence" if blockers else "ready_for_human_review",
        "issue_state": selected["issue_state"],
        "issue_label": ISSUE_STATES[selected["issue_state"]],
        "base": base,
        "base_sha256": _sha(base),
        "blockers": blockers,
        "note_candidate": None,
        "limitari": LIMITATIONS,
    }


def save(stare, request: dict) -> dict:
    selected = _selection(request, SAVE_FIELDS)
    note_id = dosare._id(request["id"])
    base_hash = legaturi_ue.digest(request["base_sha256"])
    title = _text(request["title"], 200, required=True)
    uncertainty = _text(request["uncertainty"], 2000, required=True)
    rationale = _text(request["rationale"], 4000, required=True)
    status = str(request["status"] or "").strip().lower().replace("-", "_")
    if status not in {"needs_evidence", "ready_for_review", "reviewed"}:
        raise ValueError("Stare de revizie umană invalidă.")
    resolved = preview(stare, {k: request[k] for k in PREVIEW_FIELDS})
    if resolved["blockers"]:
        raise ValueError("Nota UE are dovezi lipsă sau ambigue.")
    if resolved["base_sha256"] != base_hash:
        raise ValueError("Baza notei UE s-a schimbat. Refa previzualizarea.")
    base = resolved["base"]
    national = base["national_evidence"]
    eu = base["eu_evidence"]
    payload = {
        "contract": CONTRACT,
        "base_sha256": base_hash,
        "issue_state": selected["issue_state"],
        "issue_label": ISSUE_STATES[selected["issue_state"]],
        "uncertainty": uncertainty,
        "human_review_status": status,
        "rationale": rationale,
        "national": national,
        "eu": eu,
        "limitations": LIMITATIONS,
    }
    proposal_context = {
        "contract": "ro-eu-proposal-context-v1",
        "kind": "possible_eu_issue",
        "note_id": note_id,
        "note_title": title,
        "issue_state": selected["issue_state"],
        "issue_label": ISSUE_STATES[selected["issue_state"]],
        "human_review_status": status,
        "legal_effect": "unknown",
        "national": {
            "kind": national["kind"],
            "title": national["title"],
            "act_id": national.get("act_id", ""),
            "locator": national.get("locator", ""),
            "plx": national.get("plx", ""),
            "version_id": national.get("version_id", ""),
            "language": national["language"],
            "quote": national["quote"],
            "text_sha256": national["text_sha256"],
            "source_url": national["source_url"],
            "captured_at": national["captured_at"],
        },
        "eu": {
            "celex": eu["celex"],
            "snapshot_id": eu["instantanee"],
            "locator": eu["locator"],
            "language": eu["language"],
            "quote": eu["quote"],
            "article_sha256": eu["article_sha256"],
            "text_sha256": eu["text_sha256"],
            "source_url": eu["source_url"],
            "captured_at": eu["captured_at"],
            "title": eu["title"],
        },
        "rationale": rationale,
        "uncertainty": uncertainty,
        "limitations": PROPOSAL_CONTEXT_LIMITATIONS,
    }
    payload["proposal_context"] = proposal_context
    evidence_quote = (
        f"[RO {national['language']}] {national['quote']}\n\n[UE {eu['language']}] {eu['quote']}"
    )
    source_url = eu["source_url"] or national["source_url"]
    note = note_manuale.salveaza(
        dosare.cale(stare),
        {
            "id": note_id,
            "dosar_id": selected["dosar_id"],
            "revizie": 0,
            "title": title,
            "type": "risc_ue",
            "act_id": national.get("act_id") or national.get("plx") or "",
            "locator": national.get("locator") or national.get("version_id") or "",
            "evidence_quote": evidence_quote[:4000],
            "source_url": source_url,
            "source_hash": _sha(payload),
            "reasoning": dosare._json(payload),
            "status": status,
        },
    )
    return {
        **note,
        "eu_issue_note": payload,
        "proposal_context": proposal_context,
        "limitari": LIMITATIONS,
    }
