"""Validate the bounded real public-consultation pilot fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import achizitii_econsultare

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "real_public_consultation_snapshot.json"
CONTRACT = "real-public-consultation-snapshot-v1"


def _load(path: Path = FIXTURE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(path: Path = FIXTURE) -> dict:
    data = _load(path)
    problems: list[dict[str, str]] = []
    if data.get("contract") != CONTRACT:
        problems.append({"key": "contract", "message": "Unexpected consultation contract."})
    try:
        achizitii_econsultare.url_oficial(data.get("official_listing_url", ""))
        achizitii_econsultare.url_oficial(data.get("official_endpoint", ""))
    except ValueError as exc:
        problems.append({"key": "official_url", "message": str(exc)})

    row = data.get("row") or {}
    expected = data.get("expected") or {}
    snapshot = achizitii_econsultare.snapshot_din_actiongrid(
        row, listing_url=data.get("official_listing_url", "")
    )
    source_hash = achizitii_econsultare.actiongrid_row_hash(row)
    if source_hash != expected.get("row_hash"):
        problems.append({"key": "row_hash", "message": "Official row hash mismatch."})
    summary = snapshot["summary"]
    checks = {
        "detail_url": snapshot["url"],
        "authority": summary["authority"],
        "stage": summary["status"],
        "published": snapshot["source_metadata"]["published"],
        "deadline": summary["deadline"],
    }
    for key, actual in checks.items():
        if actual != expected.get(key):
            problems.append(
                {"key": key, "message": f"Expected {expected.get(key)!r}, got {actual!r}."}
            )
    if expected.get("title_contains") not in summary["title"]:
        problems.append({"key": "title", "message": "Expected title fragment missing."})

    event = achizitii_econsultare.tracker_event_candidate(
        snapshot,
        source_id=f"econsultare-{row.get('id', '')}",
        content_hash=achizitii_econsultare.snapshot_hash(snapshot),
        observed_at=data.get("recorded_at", ""),
    )
    return {
        "contract": CONTRACT,
        "status": "blocked" if problems else "ready",
        "source_family": data.get("source_family"),
        "source_id": f"econsultare-{row.get('id', '')}",
        "source_url": snapshot["url"],
        "source_hash": source_hash,
        "summary": summary,
        "tracker_event": {
            "event_type": event["event_type"],
            "project_id": event["project_id"],
            "occurred_at": event["occurred_at"],
            "source_family": event["source_family"],
            "payload": event["payload"],
        },
        "problems": problems,
        "limitations": data.get("limitations") or [],
    }


def seed_registry(stare, path: Path = FIXTURE) -> dict:
    """Register the fixture as one local source and tracker event."""
    from scripts import source_registry, tracker_events

    data = _load(path)
    validation = validate(path)
    if validation["status"] != "ready":
        raise ValueError("Fixture consultare publică invalid.")
    snapshot = achizitii_econsultare.snapshot_din_actiongrid(
        data["row"], listing_url=data["official_listing_url"]
    )
    source = source_registry.executa(
        stare,
        {
            "family": "consultare_econsultare",
            "identifier": validation["source_id"],
            "url": validation["source_url"],
            "label": validation["summary"]["title"],
        },
    )
    if source["state"] != "queued":
        source = source_registry.executa(stare, {"action": "queue", "id": source["id"]})
    source_registry.executa(
        stare,
        {
            "action": "record",
            "id": source["id"],
            "state": "fetched",
            "http_status": 200,
            "content_hash": validation["source_hash"],
            "parser_version": achizitii_econsultare.PARSER_VERSION,
            "note": "Rând ActionGrid e-consultare reținut ca fixture real pilot.",
        },
    )
    source = source_registry.executa(
        stare,
        {
            "action": "record",
            "id": source["id"],
            "state": "changed",
            "http_status": 200,
            "content_hash": validation["source_hash"],
            "parser_version": achizitii_econsultare.PARSER_VERSION,
        },
    )
    event = achizitii_econsultare.tracker_event_candidate(
        snapshot,
        source_id=source["id"],
        content_hash=validation["source_hash"],
        observed_at=data.get("recorded_at", ""),
    )
    tracker = tracker_events.adauga(stare, event)
    return {
        "contract": "real-public-consultation-registry-seed-v1",
        "source": source,
        "tracker_event": tracker["event"],
        "validation": validation,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args(argv)
    print(json.dumps(validate(args.fixture), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
