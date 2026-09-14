"""Bounded real-project pilot assembled from checked-in public-source evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from scripts import (
    depozit,
    dosare,
    project_cockpit,
    project_evidence_pack,
    source_registry,
    tracker_events,
)
from scripts.servicii import Stare

CONTRACT = "real-project-pilot-flow-v1"
PROJECT_ID = "PL-x 33/2025"
DOSSIER_ID = "d" * 32


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _pack() -> dict:
    return json.loads((_repo_root() / "data" / "real_pilot_pack.json").read_text(encoding="utf-8"))


def _evidence(pack: dict, key: str) -> dict:
    for requirement in pack.get("requirements", []):
        if requirement.get("key") == key:
            return (requirement.get("evidence") or [{}])[0]
    raise RuntimeError(f"Real pilot evidence missing: {key}")


def _seed(root: Path) -> Stare:
    pack = _pack()
    parliament = _evidence(pack, "parliament_project")
    consultation = _evidence(pack, "public_consultation")
    celex = _evidence(pack, "celex_text")
    law = _evidence(pack, "romanian_law_text")
    stare = Stare(str(root / "corpus.db"), str(root / "initiative.db"), str(root / "graf.db"))
    stare.eu = str(root / "eu.db")
    dosare.creeaza(
        dosare.cale(stare),
        {
            "id": DOSSIER_ID,
            "titlu": "Pilot real PL-x 33/2025",
            "intrebare": "Ce surse publice sunt legate de proiect?",
            "domeniu": "achiziții publice",
            "data_analizei": "2026-09-14",
        },
    )
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,obiect,stadiu,camera_decizionala,"
            "data_inreg,sursa_url,citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                PROJECT_ID,
                2,
                "21949",
                "Pilot real achiziții publice",
                "proiect urmărit din pachetul pilot real",
                "Raport depus",
                "Camera Deputaților",
                "2025-02-01",
                parliament["source_url"],
                "2026-09-14T00:00:00+00:00",
            ),
        )
        con.commit()
    source = source_registry.descopera(
        stare,
        {
            "family": "camera",
            "identifier": PROJECT_ID,
            "url": parliament["source_url"],
            "label": "Fișă CDEP PL-x 33/2025",
        },
    )
    source_registry.pune_in_coada(stare, source["id"])
    source_registry.inregistreaza(
        stare,
        {
            "id": source["id"],
            "state": "fetched",
            "content_hash": parliament["sha256"],
            "parser_version": "real-project-pilot.fixture",
        },
    )
    tracker_events.adauga(
        stare,
        {
            "event_type": "public_consultation_opened",
            "project_id": PROJECT_ID,
            "source_family": "consultare_econsultare",
            "source_url": consultation["source_url"],
            "occurred_at": "2025-01-20T10:00:00+00:00",
            "title": "Consultare publică din pachetul pilot real",
            "payload": {"authority": "Autoritate publică", "celex": celex["id"]},
            "content_hash": consultation["sha256"],
        },
    )
    tracker_events.adauga(
        stare,
        {
            "event_type": "report_filed",
            "project_id": PROJECT_ID,
            "source_family": "camera",
            "source_id": source["id"],
            "source_url": parliament["source_url"],
            "occurred_at": "2025-02-20T10:00:00+00:00",
            "title": "Raport/procedură CDEP din pachetul pilot real",
            "payload": {"celex": celex["id"], "law": law["id"]},
            "content_hash": parliament["sha256"],
        },
    )
    return stare


def run(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    stare = _seed(root)
    cockpit = project_cockpit.build(
        stare, {"project_id": [PROJECT_ID], "dossier_id": [DOSSIER_ID], "event_limit": ["20"]}
    )
    evidence = project_evidence_pack.build(
        stare, {"project_id": [PROJECT_ID], "dossier_id": [DOSSIER_ID], "event_limit": ["20"]}
    )
    checks = {
        "cockpit_loads_real_project": cockpit["project_id"] == PROJECT_ID,
        "consultation_link_visible": cockpit["consultations"]["total"] >= 1,
        "evidence_pack_has_public_events": evidence["summary"]["events"] >= 2,
        "source_links_are_official": all(
            row.get("source_url", "").startswith("https://")
            for row in evidence.get("evidence", [])
            if row.get("source_url")
        ),
    }
    return {
        "contract": CONTRACT,
        "status": "passed" if all(checks.values()) else "blocked",
        "project_id": PROJECT_ID,
        "dossier_id": DOSSIER_ID,
        "checks": checks,
        "summary": {
            "cockpit_events": cockpit["tracker"]["total"],
            "consultations": cockpit["consultations"]["total"],
            "evidence_events": evidence["summary"]["events"],
            "evidence_sources": len(evidence["evidence"]),
        },
        "limitari": [
            "Pilotul folosește dovezi publice deja versionate în repo; nu descarcă surse.",
            "Nu este verdict juridic și nu măsoară recall pe toate proiectele.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded real-project pilot")
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args(argv)
    if args.work_dir:
        out = run(args.work_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="legislativ-real-project-pilot-") as tmp:
            out = run(Path(tmp))
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if out["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
