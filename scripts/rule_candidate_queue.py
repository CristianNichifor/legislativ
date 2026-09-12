"""Local review queue for validated law-as-code rule candidates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import dosare, rule_candidates

QUEUE_CONTRACT = "rule-candidate-review-queue-v1"
BUCKETS = (
    "needs_more_structure",
    "needs_legal_review",
    "not_codeable",
    "reviewable",
    "human_reviewed",
)
FILTERS = (*BUCKETS, "all")


def _supported(con) -> bool:
    return con.execute("PRAGMA user_version").fetchone()[0] >= 12


def _offset(value) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError("Offset invalid.")
    return value


def _bucket(candidate: dict) -> str:
    if candidate["status"] in {
        "needs_more_structure",
        "needs_legal_review",
        "not_codeable",
    }:
        return candidate["status"]
    if candidate["review_state"] in {"human_reviewed", "legally_validated"}:
        return "human_reviewed"
    if candidate["review_state"] in {"disputed", "obsolete"}:
        return "needs_legal_review"
    return "reviewable"


def _row(row) -> dict:
    candidate = json.loads(row["payload_json"])
    return {
        "id": row["id"],
        "dosar_id": row["dosar_id"],
        "candidate_id": row["candidate_id"],
        "bucket": _bucket(candidate),
        "creat_la": row["creat_la"],
        "candidate": candidate,
        "actiuni": {
            "complete_structure": candidate["status"] == "needs_more_structure",
            "legal_review": _bucket(candidate) == "needs_legal_review",
            "keep_as_non_codeable": candidate["status"] == "not_codeable",
            "promote_to_rule": _bucket(candidate) in {"reviewable", "human_reviewed"},
        },
    }


def _empty(dossier_id: str, offset: int = 0) -> dict:
    return {
        "contract": QUEUE_CONTRACT,
        "dosar_id": dossier_id,
        "offset": offset,
        "limita": 50,
        "total": 0,
        "counts": {bucket: 0 for bucket in BUCKETS},
        "items": [],
        "groups": {bucket: [] for bucket in BUCKETS},
        "limitari": [
            "Coada conține doar candidați validați local cu rule-candidate-v1.",
            "Gruparea este operațională pentru revizie; nu este verdict juridic.",
        ],
    }


def salveaza(path, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"id", "dosar_id", "candidate"}:
        raise ValueError("Cerere candidat regulă invalidă.")
    ident = dosare._id(request["id"])
    dossier_id = dosare._id(request["dosar_id"])
    candidate = rule_candidates.validate(request["candidate"])
    payload = dosare._json(candidate)
    if len(payload.encode("utf-8")) > 20_000:
        raise ValueError("Candidatul de regulă depășește limita.")
    with dosare._open(path, write=True) as con:
        if not con.execute("SELECT 1 FROM dosare WHERE id=?", (dossier_id,)).fetchone():
            raise ValueError("Dosar inexistent.")
        old = con.execute(
            "SELECT * FROM rule_candidate_queue WHERE dosar_id=? AND candidate_id=?",
            (dossier_id, candidate["candidate_id"]),
        ).fetchone()
        if old:
            if old["id"] != ident:
                raise ValueError("Candidatul există deja în coada acestui dosar.")
            return _row(old)
        con.execute(
            "INSERT INTO rule_candidate_queue "
            "(id,dosar_id,candidate_id,provision_id,act_id,locator,status,review_state,"
            "modality,source_hash,text_sha256,payload_json,creat_la) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                dossier_id,
                candidate["candidate_id"],
                candidate["provision_id"],
                candidate["act_id"],
                candidate["locator"],
                candidate["status"],
                candidate["review_state"],
                candidate["modality"],
                candidate["source_hash"],
                candidate["text_sha256"],
                payload,
                datetime.now(UTC).isoformat(),
            ),
        )
        return _row(
            con.execute("SELECT * FROM rule_candidate_queue WHERE id=?", (ident,)).fetchone()
        )


def lista(path, dossier_id: str, offset: int = 0, bucket: str = "all") -> dict:
    dossier_id = dosare._id(dossier_id)
    offset = _offset(offset)
    if bucket not in FILTERS:
        raise ValueError("Filtru coadă invalid.")
    if not Path(path).exists():
        return _empty(dossier_id, offset)
    dosare.citeste(path, dossier_id)
    with dosare._open(path) as con:
        if not _supported(con):
            return _empty(dossier_id, offset)
        rows = [
            _row(row)
            for row in con.execute(
                "SELECT * FROM rule_candidate_queue WHERE dosar_id=? ORDER BY creat_la DESC,id",
                (dossier_id,),
            )
        ]
    counts = {name: 0 for name in BUCKETS}
    groups = {name: [] for name in BUCKETS}
    for row in rows:
        counts[row["bucket"]] += 1
        groups[row["bucket"]].append(row)
    selected = rows if bucket == "all" else groups[bucket]
    return {
        **_empty(dossier_id, offset),
        "total": len(selected),
        "counts": counts,
        "items": selected[offset : offset + 50],
        "groups": {name: values[:20] for name, values in groups.items()},
        "selected_bucket": bucket,
    }


def executa(path, request: dict) -> dict:
    if not isinstance(request, dict) or request.get("action") != "save":
        raise ValueError("Acțiune candidat regulă invalidă.")
    return salveaza(path, {k: v for k, v in request.items() if k != "action"})
