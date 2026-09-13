"""Validate and exercise the bounded real-pilot reviewable finding."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from scripts import dosare, note_manuale, propuneri, revizuiri

ROOT = Path(__file__).resolve().parents[1]
FINDING = ROOT / "data" / "real_reviewable_finding.json"
CONTRACT = "real-reviewable-finding-v1"
DOSSIER_ID = "10000000000000000000000000000001"
PROPOSAL_ID = "10000000000000000000000000000002"
NOTE_ID = "10000000000000000000000000000003"
REVIEW_ID = "10000000000000000000000000000004"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_text(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text)


def _load(path: Path = FINDING) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_entries(data: dict) -> list[dict]:
    return [data["finding"], *(data.get("related_sources") or [])]


def validate(path: Path = FINDING, *, root: Path = ROOT) -> dict:
    data = _load(path)
    problems: list[dict[str, str]] = []

    if data.get("contract") != CONTRACT:
        problems.append({"key": "contract", "message": "Unexpected reviewable-finding contract."})
    if data.get("status") != "reviewed":
        problems.append({"key": "status", "message": "Finding is not reviewer-approved."})
    if data.get("issue_type") not in {"lacuna", "contradictie", "constitutionalitate", "risc_ue"}:
        problems.append({"key": "issue_type", "message": "Unsupported pilot issue type."})

    proposal = data.get("proposal") or {}
    if not (proposal.get("wording") or "").strip():
        problems.append({"key": "proposal", "message": "Proposed wording is required."})

    verified_sources = 0
    for entry in _source_entries(data):
        rel_path = entry.get("source_path")
        if not rel_path:
            problems.append({"key": "source_path", "message": "Source path is required."})
            continue
        source_path = root / rel_path
        if not source_path.exists():
            problems.append({"key": rel_path, "message": "Source file is missing."})
            continue
        expected = entry.get("source_sha256")
        if expected and _sha256(source_path) != expected:
            problems.append({"key": rel_path, "message": "Source hash mismatch."})
            continue
        quote = re.sub(r"\s+", " ", str(entry.get("quote") or "")).strip()
        if quote and quote not in _source_text(source_path):
            problems.append({"key": rel_path, "message": "Quote not found in source snapshot."})
            continue
        verified_sources += 1

    return {
        "contract": CONTRACT,
        "status": "ready" if not problems else "blocked",
        "id": data.get("id"),
        "issue_type": data.get("issue_type"),
        "review_status": data.get("status"),
        "proposal_ready": bool((proposal.get("wording") or "").strip()),
        "verified_sources": verified_sources,
        "problems": problems,
        "limitations": data.get("limitations") or [],
    }


def _report(data: dict) -> dict:
    finding = data["finding"]
    return {
        "gasit": True,
        "rand": {
            "exemple": {
                "viduri": [
                    {
                        "act_id": finding["act_id"],
                        "locator": finding["locator"],
                        "text": finding["quote"],
                        "tip_constatare": data["issue_type"],
                        "rationament": finding["reasoning"],
                        "sursa_url": finding["source_url"],
                        "sursa_sha256": finding["source_sha256"],
                        "pilot_finding_id": data["id"],
                    }
                ]
            }
        },
        "markdown": (
            "# Constatare pilot revizuită\n\n"
            + data["title"]
            + "\n\nNu este verdict juridic; este o constatare pilot sursată."
        ),
    }


def seed_dossier(work_dir: Path, artifact: Path = FINDING) -> dict:
    validation = validate(artifact)
    if validation["status"] != "ready":
        raise ValueError("Real reviewable finding is not ready.")
    data = _load(artifact)
    work_dir.mkdir(parents=True, exist_ok=True)
    state = SimpleNamespace(initiative=work_dir / "initiative.db", date_dir=None)
    path = dosare.cale(state)
    dossier = dosare.creeaza(
        path,
        {
            "id": DOSSIER_ID,
            "titlu": "Pilot achiziții publice: constatare revizuită",
            "intrebare": data["title"],
            "domeniu": data["domain"],
            "data_analizei": "2026-09-14",
        },
    )
    report = _report(data)
    payload = dosare._json(
        {
            "engine_version": "real-reviewable-finding-pilot-v1",
            "filtre": {"emitent": "Parlamentul"},
            "raport": report,
            "dovezi": {
                "acte": {data["finding"]["act_id"]: data["finding"]},
                "pilot_reviewable_finding": data,
                "manifest": {
                    "contract": CONTRACT,
                    "finding_id": data["id"],
                    "sources": [
                        {
                            "path": entry["source_path"],
                            "sha256": entry["source_sha256"],
                            "url": entry["source_url"],
                        }
                        for entry in _source_entries(data)
                    ],
                },
            },
        }
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    with dosare._open(path, write=True) as con:
        con.execute(
            "INSERT OR IGNORE INTO rulari VALUES (?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                DOSSIER_ID,
                datetime.now(UTC).isoformat(),
                "real-reviewable-finding-pilot-v1",
                digest,
                dosare._json({"emitent": "Parlamentul"}),
                dosare._json(report),
                dosare._json(json.loads(payload)["dovezi"]),
            ),
        )
        run_id = con.execute(
            "SELECT id FROM rulari WHERE dosar_id=? AND sha256=?", (DOSSIER_ID, digest)
        ).fetchone()[0]
    run = dosare.rulari(path, DOSSIER_ID, run_id)
    finding_id = revizuiri.constatari(run)[0]["id"]
    review = revizuiri.salveaza(
        path,
        {
            "id": REVIEW_ID,
            "dosar_id": DOSSIER_ID,
            "rulare_id": run_id,
            "constatare_id": finding_id,
            "revizie": 0,
            "stare": "confirmed_by_reviewer",
            "evaluator": data["reviewer"]["name"],
            "motiv": data["reviewer"]["note"],
        },
    )
    note = note_manuale.salveaza(
        path,
        {
            "id": NOTE_ID,
            "dosar_id": DOSSIER_ID,
            "revizie": 0,
            "title": data["title"],
            "type": data["issue_type"],
            "act_id": data["finding"]["act_id"],
            "locator": data["finding"]["locator"],
            "evidence_quote": data["finding"]["quote"],
            "source_url": data["finding"]["source_url"],
            "source_hash": data["finding"]["source_sha256"],
            "reasoning": data["finding"]["reasoning"],
            "status": "reviewed",
        },
    )
    proposal = propuneri.salveaza(
        path,
        {
            "id": PROPOSAL_ID,
            "dosar_id": DOSSIER_ID,
            "rulare_id": run_id,
            "constatare_id": finding_id,
            "revizie": 0,
            "titlu": data["proposal"]["title"],
            "text": data["proposal"]["wording"],
            "motiv": data["proposal"]["rationale"],
        },
    )
    export = propuneri.exporta(path, DOSSIER_ID, run_id, finding_id, 1)
    return {
        "contract": "real-reviewable-finding-dossier-flow-v1",
        "db": str(path),
        "dossier": dossier,
        "run_id": run_id,
        "finding_id": finding_id,
        "review": review,
        "note": note,
        "proposal": proposal,
        "export_sha256": hashlib.sha256(export["markdown"].encode("utf-8")).hexdigest(),
        "export_contains_proposal": data["proposal"]["wording"] in export["markdown"],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=FINDING)
    parser.add_argument("--seed-work-dir", type=Path)
    args = parser.parse_args(argv)
    result = validate(args.artifact)
    if args.seed_work_dir:
        result["dossier_flow"] = seed_dossier(args.seed_work_dir, args.artifact)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
