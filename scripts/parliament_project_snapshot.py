"""Validate and seed one bounded real parliamentary project snapshot."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts import depozit, source_registry
from scripts.cdep import parseaza_fisa
from scripts.parcurs import parseaza_parcurs

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ROOT / "data" / "parliament_project_snapshots.json"
CONTRACT = "parliament-project-snapshots-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path = SNAPSHOTS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot(pack: dict, key: str) -> dict:
    for item in pack.get("snapshots") or []:
        if item.get("key") == key:
            return item
    raise ValueError("Snapshot parlamentar necunoscut.")


def _idp_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "www.cdep.ro":
        raise ValueError("URL CDEP invalid.")
    values = parse_qs(parsed.query).get("idp") or []
    if not values or not values[0].isdigit():
        raise ValueError("URL CDEP fără idp valid.")
    return values[0]


def _read_html(root: Path, snapshot: dict) -> tuple[Path, bytes, str]:
    rel_path = snapshot.get("snapshot_path")
    if not isinstance(rel_path, str) or not rel_path:
        raise ValueError("Snapshot fără cale.")
    path = root / rel_path
    data = path.read_bytes()
    html = gzip.decompress(data).decode("utf-8", errors="replace")
    return path, data, html


def parse_snapshot(snapshot: dict, *, root: Path = ROOT) -> dict:
    """Return parsed project facts from one recorded CDEP Fișa snapshot."""
    path, data, html = _read_html(root, snapshot)
    expected_hash = snapshot.get("snapshot_sha256")
    actual_hash = hashlib.sha256(data).hexdigest()
    if expected_hash and actual_hash != expected_hash:
        raise ValueError("Hash snapshot CDEP diferit.")
    idp = _idp_from_url(snapshot.get("source_url") or "")
    initiative = parseaza_fisa(html, idp, 2, url=snapshot["source_url"])
    route = parseaza_parcurs(html, initiative.plx_id, idp)
    return {
        "key": snapshot["key"],
        "path": str(path.relative_to(root)),
        "sha256": actual_hash,
        "project_id": initiative.plx_id,
        "idp": initiative.idp,
        "senate_id": initiative.senat_id,
        "title": initiative.titlu,
        "stage": initiative.stadiu,
        "procedure_date": initiative.data_inreg,
        "chamber": initiative.camera_decizionala,
        "source_url": initiative.sursa_url,
        "route_counts": {
            "stages": len(route.etape),
            "opinions": len(route.avize),
            "votes": len(route.voturi),
        },
        "first_stage_date": next((stage.data for stage in route.etape if stage.data), None),
        "last_stage_date": next(
            (stage.data for stage in reversed(route.etape) if stage.data), None
        ),
    }


def validate(path: Path = SNAPSHOTS, *, root: Path = ROOT) -> dict:
    """Validate snapshot bytes and expected parliamentary metadata without network access."""
    pack = _load(path)
    problems: list[dict[str, str]] = []
    parsed: list[dict] = []
    if pack.get("contract") != CONTRACT:
        problems.append({"key": "contract", "message": "Unexpected snapshot contract."})
    for snapshot in pack.get("snapshots") or []:
        key = str(snapshot.get("key") or "")
        try:
            item = parse_snapshot(snapshot, root=root)
        except (OSError, ValueError, gzip.BadGzipFile) as exc:
            problems.append({"key": key, "message": str(exc)})
            continue
        checks = {
            "project_id": item["project_id"] == snapshot.get("project_id"),
            "idp": item["idp"] == snapshot.get("idp"),
            "senate_id": item["senate_id"] == snapshot.get("senate_id"),
            "procedure_date": item["procedure_date"] == snapshot.get("procedure_date"),
            "stage": (snapshot.get("stage_contains") or "").lower() in item["stage"].lower(),
            "title": (snapshot.get("title_contains") or "").lower() in item["title"].lower(),
        }
        for field, ok in checks.items():
            if not ok:
                problems.append({"key": key, "message": f"Unexpected {field}."})
        parsed.append(item)
    return {
        "contract": CONTRACT,
        "status": "blocked" if problems else "ready",
        "snapshots": parsed,
        "problems": problems,
        "limitations": [
            "Offline recorded CDEP fixture; no live parliamentary crawl is performed.",
            "The snapshot proves one project/procedure shape, not source freshness.",
        ],
    }


def seed_state(stare, key: str = "plx-33-2025", *, root: Path = ROOT) -> dict:
    """Seed the local initiative database from a recorded CDEP Fișa snapshot."""
    pack = _load()
    snapshot = _snapshot(pack, key)
    _, _, html = _read_html(root, snapshot)
    idp = _idp_from_url(snapshot["source_url"])
    initiative = parseaza_fisa(html, idp, 2, url=snapshot["source_url"])
    route = parseaza_parcurs(html, initiative.plx_id, idp)
    with depozit.deschide(stare.initiative) as con:
        depozit.scrie_initiativa(con, initiative)
        depozit.scrie_parcurs(con, route)
        con.commit()
    return parse_snapshot(snapshot, root=root)


def register_source(stare, key: str = "plx-33-2025", *, root: Path = ROOT) -> dict:
    """Register the seeded snapshot's project as one bounded Camera source."""
    parsed = seed_state(stare, key, root=root)
    return source_registry.executa(
        stare,
        {
            "action": "discover",
            "family": "camera",
            "identifier": parsed["project_id"],
            "label": f"{parsed['project_id']} · {parsed['stage']}",
        },
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    args = parser.parse_args(argv)
    print(json.dumps(validate(args.snapshots), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
