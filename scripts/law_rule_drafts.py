"""Immutable draft rules promoted from reviewed rule candidates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import dosare, rule_candidate_queue

CONTRACT = "law-rule-draft-v1"
MAX_NOTE_CHARS = 1_200


def _supported(con) -> bool:
    return con.execute("PRAGMA user_version").fetchone()[0] >= 13


def _offset(value) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError("Offset invalid.")
    return value


def _row(row) -> dict:
    return json.loads(row["payload_json"])


def _empty(dossier_id: str, offset: int = 0) -> dict:
    return {
        "contract": "law-rule-draft-list-v1",
        "dosar_id": dossier_id,
        "offset": offset,
        "limita": 50,
        "total": 0,
        "items": [],
        "limitari": [
            "Regulile sunt ciorne revizuite, nu concluzii juridice.",
            "Execuția automată trebuie să citească doar reguli legate de sursa exactă.",
        ],
    }


def _draft_payload(
    *,
    draft_id: str,
    queue_id: str,
    dossier_id: str,
    candidate: dict,
    accepted_by: str,
    acceptance_note: str,
    created_at: str,
) -> dict:
    return {
        "contract": CONTRACT,
        "draft_id": draft_id,
        "dosar_id": dossier_id,
        "queue_id": queue_id,
        "candidate_id": candidate["candidate_id"],
        "status": "draft_rule_not_legal_verdict",
        "provision_id": candidate["provision_id"],
        "act_id": candidate["act_id"],
        "locator": candidate["locator"],
        "modality": candidate["modality"],
        "source_hash": candidate["source_hash"],
        "text_sha256": candidate["text_sha256"],
        "actor": candidate["actor"],
        "condition": candidate["condition"],
        "action": candidate["action"],
        "deadline": candidate["deadline"],
        "exceptions": candidate["exceptions"],
        "effect": candidate["effect"],
        "accepted_by": accepted_by,
        "acceptance_note": acceptance_note,
        "creat_la": created_at,
        "source_candidate": candidate,
        "limitari": [
            "Ciorna nu este regulă executabilă validată juridic.",
            "Textul sursă și identitatea prevederii rămân autoritatea.",
        ],
    }


def promoveaza(path, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {
        "id",
        "dosar_id",
        "queue_id",
        "accepted_by",
        "acceptance_note",
    }:
        raise ValueError("Cerere promovare regulă invalidă.")
    draft_id = dosare._id(request["id"])
    dossier_id = dosare._id(request["dosar_id"])
    queue_id = dosare._id(request["queue_id"])
    accepted_by = dosare._text(request["accepted_by"], 160, True)
    acceptance_note = dosare._text(request["acceptance_note"], MAX_NOTE_CHARS, True)

    with dosare._open(path, write=True) as con:
        if not _supported(con):
            raise ValueError("Ciornele de reguli cer schema dosarelor 13.")
        row = con.execute(
            "SELECT * FROM rule_candidate_queue WHERE id=? AND dosar_id=?",
            (queue_id, dossier_id),
        ).fetchone()
        if not row:
            raise ValueError("Candidatul din coadă nu există.")
        candidate = json.loads(row["payload_json"])
        queued = rule_candidate_queue._row(row)
        if candidate.get("contract") != "rule-candidate-v1":
            raise ValueError("Candidatul din coadă nu este valid.")
        if queued["bucket"] not in {"reviewable", "human_reviewed"}:
            raise ValueError("Candidatul nu poate fi promovat fără structură revizuibilă.")
        old = con.execute(
            "SELECT * FROM law_rule_drafts WHERE dosar_id=? AND candidate_id=?",
            (dossier_id, candidate["candidate_id"]),
        ).fetchone()
        if old:
            if old["id"] != draft_id:
                raise ValueError("Candidatul este deja promovat în acest dosar.")
            return _row(old)
        created_at = datetime.now(UTC).isoformat()
        payload = _draft_payload(
            draft_id=draft_id,
            queue_id=queue_id,
            dossier_id=dossier_id,
            candidate=candidate,
            accepted_by=accepted_by,
            acceptance_note=acceptance_note,
            created_at=created_at,
        )
        con.execute(
            "INSERT INTO law_rule_drafts "
            "(id,dosar_id,candidate_id,queue_id,provision_id,act_id,locator,modality,"
            "source_hash,text_sha256,accepted_by,acceptance_note,payload_json,creat_la) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                draft_id,
                dossier_id,
                candidate["candidate_id"],
                queue_id,
                candidate["provision_id"],
                candidate["act_id"],
                candidate["locator"],
                candidate["modality"],
                candidate["source_hash"],
                candidate["text_sha256"],
                accepted_by,
                acceptance_note,
                dosare._json(payload),
                created_at,
            ),
        )
        return payload


def lista(
    path,
    dossier_id: str,
    offset: int = 0,
    *,
    act_id: str | None = None,
    provision_id: str | None = None,
) -> dict:
    dossier_id = dosare._id(dossier_id)
    offset = _offset(offset)
    act_id = dosare._text(act_id or "", 200)
    provision_id = dosare._text(provision_id or "", 240)
    if not Path(path).exists():
        return _empty(dossier_id, offset)
    dosare.citeste(path, dossier_id)
    with dosare._open(path) as con:
        if not _supported(con):
            return _empty(dossier_id, offset)
        filters = ["dosar_id=?"]
        params: list[str] = [dossier_id]
        if act_id:
            filters.append("act_id=?")
            params.append(act_id)
        if provision_id:
            filters.append("provision_id=?")
            params.append(provision_id)
        where = " AND ".join(filters)
        rows = [
            _row(row)
            for row in con.execute(
                f"SELECT * FROM law_rule_drafts WHERE {where} ORDER BY creat_la DESC,id",
                params,
            )
        ]
    return {
        **_empty(dossier_id, offset),
        "total": len(rows),
        "items": rows[offset : offset + 50],
        "filtre": {"act_id": act_id, "provision_id": provision_id},
    }


def executa(path, request: dict) -> dict:
    if not isinstance(request, dict) or request.get("action") != "promote":
        raise ValueError("Acțiune ciornă regulă invalidă.")
    return promoveaza(path, {k: v for k, v in request.items() if k != "action"})
