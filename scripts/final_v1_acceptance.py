"""Final v1 vertical acceptance runner.

This proves the small checked-in v1 manifest can drive one local legislative
workflow without a release rebuild, crawler, network call or model call.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from scripts import (
    ai_drafting,
    depozit,
    dosare,
    mcp_tools,
    note_manuale,
    project_evidence_pack,
    source_registry,
    source_tracker_workbench,
    tracker_events,
    v1_acceptance_dataset,
)
from scripts.parsare import Provizie
from scripts.servicii import Stare, _cauta, _matrice_dosar

CONTRACT = "final-v1-vertical-acceptance-flow-v1"
PROJECT_ID = "PL-x acceptance-procurement-001"
DOSSIER_ID = "f" * 32
NOTE_ID = "e" * 32
SOURCE_HASH = "9" * 64


class FinalV1AcceptanceError(RuntimeError):
    """The v1 vertical acceptance workflow is disconnected."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FinalV1AcceptanceError(message)


def _item(manifest: dict, item_id: str) -> dict:
    for item in manifest["items"]:
        if item["id"] == item_id:
            return item
    raise FinalV1AcceptanceError(f"v1 manifest item missing: {item_id}")


def _insert_law(con: sqlite3.Connection, item: dict) -> None:
    con.execute(
        "INSERT INTO acte (id, cheie_citare, tip, numar, an, titlu, emitent, publicat,"
        " id_portal, sursa_url, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            item["identifier"],
            item["identifier"],
            "lege",
            "98",
            2016,
            item["title"],
            "Parlamentul",
            "2016-05-23",
            item["identifier"],
            item.get("official_url") or "",
            "2026-09-13T00:00:00+00:00",
        ),
    )
    depozit.scrie_provizii(
        con,
        item["identifier"],
        [
            Provizie(
                "art7",
                "Guvernul aprobă normele metodologice privind achizițiile publice.",
            ),
            Provizie("art12", "Directiva 2014/24/UE se aplică achizițiilor publice."),
        ],
    )


def _seed_state(root: Path, manifest: dict) -> Stare:
    law = _item(manifest, "v1-law-lege-98-2016")
    project = _item(manifest, "v1-project-camera-procurement")
    econsultare = _item(manifest, "v1-consultare-econsultare-procurement")
    celex = _item(manifest, "v1-celex-32014l0024")
    reports = root / "reports"
    reports.mkdir()
    stare = Stare(
        str(root / "corpus.db"),
        str(root / "initiative.db"),
        str(root / "graf.db"),
        str(root / "eu.db"),
        reports_dir=str(reports),
    )
    stare.vid = [
        {
            "act_id": law["identifier"],
            "locator": "art7",
            "text": "Guvernul aprobă normele metodologice privind achizițiile publice.",
            "instrument": "hg",
            "severitate": "blocking",
        }
    ]
    stare.neconstitutional = []

    with depozit.deschide(stare.corpus) as con:
        _insert_law(con, law)
        con.commit()
    with depozit.deschide(stare.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,obiect,stadiu,camera_decizionala,"
            "data_inreg,sursa_url,citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                PROJECT_ID,
                2,
                "acceptance-procurement-001",
                project["title"],
                "modificarea Legii nr. 98/2016 pentru achiziții publice",
                "Raport depus",
                "Camera Deputaților",
                "2026-09-01",
                "https://www.cdep.ro/proiecte/acceptance-procurement-001",
                "2026-09-13T00:00:00+00:00",
            ),
        )
        con.execute(
            "INSERT INTO initiative_fts(titlu, obiect, plx_id) VALUES (?,?,?)",
            (project["title"], "modificarea Legii nr. 98/2016", PROJECT_ID),
        )
        con.execute(
            "INSERT INTO initiativa_etapa(plx_id,ord,data,camera,actiune,comisii) "
            "VALUES (?,?,?,?,?,?)",
            (PROJECT_ID, 1, "2026-09-12", "Camera Deputaților", "Raport depus", "Comisia juridică"),
        )
        con.execute(
            "INSERT INTO initiative_tinta(plx_id, act_id, locator) VALUES (?,?,?)",
            (PROJECT_ID, law["identifier"], "art7"),
        )
        con.commit()

    source = source_registry.descopera(
        stare,
        {
            "family": "camera",
            "identifier": PROJECT_ID,
            "url": "https://www.cdep.ro/proiecte/acceptance-procurement-001",
            "label": project["title"],
        },
    )
    source_registry.pune_in_coada(stare, source["id"])
    source_registry.inregistreaza(
        stare,
        {
            "id": source["id"],
            "state": "fetched",
            "content_hash": "8" * 64,
            "parser_version": "final-v1-acceptance.fixture",
        },
    )
    source_registry.inregistreaza(
        stare,
        {
            "id": source["id"],
            "state": "changed",
            "content_hash": SOURCE_HASH,
            "parser_version": "final-v1-acceptance.fixture",
        },
    )
    tracker_events.adauga(
        stare,
        {
            "event_type": "public_consultation_opened",
            "project_id": PROJECT_ID,
            "source_family": "consultare_econsultare",
            "source_url": "https://e-consultare.gov.ro/consultare/acceptance-procurement-001",
            "occurred_at": "2026-09-05T10:00:00+00:00",
            "title": econsultare["title"],
            "payload": {"authority": "MDLPA", "affected_act": law["identifier"]},
            "content_hash": SOURCE_HASH,
        },
    )
    event = tracker_events.adauga(
        stare,
        {
            "event_type": "report_filed",
            "project_id": PROJECT_ID,
            "source_family": "camera",
            "source_id": source["id"],
            "source_url": "https://www.cdep.ro/proiecte/acceptance-procurement-001",
            "occurred_at": "2026-09-12T10:00:00+00:00",
            "title": "Raport depus",
            "payload": {
                "committee": "Comisia juridică",
                "affected_act": law["title"],
                "celex": celex["identifier"],
            },
            "content_hash": SOURCE_HASH,
        },
    )["event"]
    tracker_events.marcheaza_revizuit(
        stare,
        {
            "id": event["id"],
            "reviewer": "acceptance",
            "note": "Eveniment folosit în fluxul final v1.",
        },
    )
    dosare.creeaza(
        dosare.cale(stare),
        {
            "id": DOSSIER_ID,
            "titlu": "Dosar acceptanță v1 achiziții publice",
            "intrebare": "Ce trebuie verificat înainte de redactare?",
            "domeniu": "achiziții publice",
            "data_analizei": "2026-09-13",
        },
    )
    note_manuale.salveaza(
        dosare.cale(stare),
        {
            "id": NOTE_ID,
            "dosar_id": DOSSIER_ID,
            "revizie": 0,
            "title": "Lacună norme achiziții",
            "type": "lacuna",
            "act_id": PROJECT_ID,
            "locator": "art7",
            "evidence_quote": "Guvernul aprobă normele metodologice privind achizițiile publice.",
            "source_url": law.get("official_url") or "",
            "source_hash": law["sha256"],
            "reasoning": (
                "Dovada selectată cere verificarea normelor metodologice înainte de draft."
            ),
            "status": "ready_for_review",
        },
    )
    return stare


def run(root: Path) -> dict:
    manifest = v1_acceptance_dataset.validate()
    stare = _seed_state(root, manifest)
    law = _item(manifest, "v1-law-lege-98-2016")
    celex = _item(manifest, "v1-celex-32014l0024")

    search = _cauta("publice", stare, limita=5)
    workbench = source_tracker_workbench.build(
        stare, {"source_limit": ["10"], "event_limit": ["10"]}
    )
    matrix = _matrice_dosar({"emitent": ["Parlamentul"], "problema": ["semnale"]}, stare)
    evidence = project_evidence_pack.build(
        stare, {"project_id": [PROJECT_ID], "dossier_id": [DOSSIER_ID], "event_limit": ["10"]}
    )
    selected = {
        "label": "Lacună norme achiziții",
        "act_id": law["identifier"],
        "locator": "art7",
        "source_url": law.get("official_url") or "",
        "source_hash": law["sha256"],
        "quote": "Guvernul aprobă normele metodologice privind achizițiile publice.",
        "language": "RON",
    }
    draft = ai_drafting.preview(
        {
            "task": "issue_note",
            "type": "lacuna",
            "title": "Notă acceptanță v1",
            "context": f"Proiect {PROJECT_ID}; verifică și CELEX {celex['identifier']}.",
            "evidence": [selected],
        }
    )
    mcp_timeline = mcp_tools.call_tool(stare, "get_project_timeline", {"project_id": PROJECT_ID})
    mcp_bundle = mcp_tools.call_tool(
        stare, "get_evidence_bundle", {"project_id": PROJECT_ID, "dossier_id": DOSSIER_ID}
    )
    mcp_draft = mcp_tools.call_tool(
        stare,
        "draft_from_evidence",
        {
            "task": "issue_note",
            "type": "lacuna",
            "title": "Notă acceptanță v1",
            "context": "Același payload prin MCP.",
            "evidence": [selected],
        },
    )

    checks = {
        "manifest_valid": manifest["contract"] == v1_acceptance_dataset.CONTRACT,
        "search_finds_law": any(
            r["act_id"] == law["identifier"] for r in search.get("results", [])
        ),
        "workbench_tracks_project": any(
            row.get("project_id") == PROJECT_ID for row in workbench.get("rows", [])
        ),
        "matrix_has_drilldown": bool(matrix.get("gasit"))
        and matrix.get("drilldown", {}).get("contract") == "matrice-drilldown-v1",
        "evidence_pack_has_note_and_events": evidence["summary"]["events"] >= 2
        and evidence["summary"]["notes"] == 1,
        "draft_is_evidence_bound": draft["contract"] == "ai-evidence-draft-v1"
        and draft["approval"]["server_calls_model"] is False
        and draft["evidence_count"] == 1,
        "mcp_uses_same_project": mcp_timeline["project_id"] == PROJECT_ID
        and mcp_bundle["summary"]["notes"] == 1
        and mcp_draft["approval"]["server_calls_model"] is False,
    }
    failed = [key for key, value in checks.items() if not value]
    if failed:
        raise FinalV1AcceptanceError("Flux v1 incomplet: " + ", ".join(failed))

    return {
        "contract": CONTRACT,
        "status": "passed",
        "project_id": PROJECT_ID,
        "dossier_id": DOSSIER_ID,
        "manifest": {
            "version": manifest["version"],
            "items": len(manifest["items"]),
            "large_release_required": manifest["scope"]["large_release_required"],
        },
        "checks": checks,
        "summary": {
            "search_results": len(search.get("results", [])),
            "workbench_rows": len(workbench.get("rows", [])),
            "matrix_entries": matrix.get("drilldown", {}).get("summary", {}),
            "evidence_events": evidence["summary"]["events"],
            "evidence_notes": evidence["summary"]["notes"],
            "draft_tokens": draft["estimated_tokens"],
            "mcp_timeline_events": len(mcp_timeline["events"]),
        },
        "next_actions": [
            "Înlocuiește fixture-ul cu primul set mic de date reale adjudecat.",
            "Rulează același flux în browser înainte de marcarea v1 ca release candidate.",
            "Adaugă exportul final issue note + amendament după acceptarea juridică.",
        ],
        "limitari": [
            "Runnerul nu descarcă surse publice și nu reconstruiește dataseturi.",
            (
                "CELEX este reprezentat prin identificatorul din manifest; "
                "textul UE real rămâne de importat."
            ),
            "Ciorna AI/MCP este doar preview din dovezi selectate; serverul nu apelează modele.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run final v1 vertical acceptance")
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args(argv)
    if args.work_dir:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        out = run(args.work_dir)
    else:
        with tempfile.TemporaryDirectory(prefix="legislativ-final-v1-") as tmp:
            out = run(Path(tmp))
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
