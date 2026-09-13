"""Replay bounded public tracking snapshots into local source and tracker state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts import source_registry, tracker_events

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "public_tracking_snapshot.json"
CONTRACT = "public-tracking-snapshot-v1"
SEED_CONTRACT = "public-tracking-replay-v1"


def _load(path: Path = FIXTURE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _event_types(data: dict[str, Any]) -> set[str]:
    return {
        event.get("event_type", "")
        for source in data.get("sources") or []
        for snapshot in source.get("snapshots") or []
        for event in snapshot.get("events") or []
    }


def _problems(data: dict[str, Any]) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    if data.get("contract") != CONTRACT:
        problems.append({"key": "contract", "message": "Unexpected public tracking contract."})
    seen_sources: set[str] = set()
    seen_events: set[tuple[str, str]] = set()
    for source in data.get("sources") or []:
        key = str(source.get("key") or "")
        family = source.get("family")
        if family not in source_registry.FAMILIES:
            problems.append({"key": key, "message": "Unknown source family."})
        if key in seen_sources:
            problems.append({"key": key, "message": "Duplicate source key."})
        seen_sources.add(key)
        snapshots = source.get("snapshots") or []
        if not snapshots:
            problems.append({"key": key, "message": "Source has no snapshots."})
        for index, snapshot in enumerate(snapshots):
            content_hash = str(snapshot.get("content_hash") or "")
            if not source_registry.HEX64.fullmatch(content_hash):
                problems.append({"key": key, "message": f"Snapshot {index} has invalid hash."})
            for event in snapshot.get("events") or []:
                event_type = str(event.get("event_type") or "")
                if event_type not in tracker_events.EVENT_TYPES:
                    problems.append({"key": key, "message": f"Unknown event type {event_type}."})
                identity = (key, str(event.get("id") or ""))
                if identity in seen_events:
                    problems.append({"key": key, "message": f"Duplicate event id {identity[1]}."})
                seen_events.add(identity)
    missing = sorted(set(data.get("required_event_types") or []) - _event_types(data))
    for event_type in missing:
        problems.append({"key": event_type, "message": "Required tracker event missing."})
    return problems


def validate(path: Path = FIXTURE) -> dict[str, Any]:
    """Validate the fixture-level monitoring shape without mutating local state."""
    data = _load(path)
    problems = _problems(data)
    event_types = sorted(_event_types(data))
    source_families = sorted({source.get("family", "") for source in data.get("sources") or []})
    snapshot_count = sum(len(source.get("snapshots") or []) for source in data.get("sources") or [])
    return {
        "contract": CONTRACT,
        "status": "blocked" if problems else "ready",
        "project_id": data.get("project_id", ""),
        "sources": len(data.get("sources") or []),
        "source_families": source_families,
        "snapshots": snapshot_count,
        "event_types": event_types,
        "required_event_types": data.get("required_event_types") or [],
        "coverage": {
            "public_consultations": "public_consultation_opened" in event_types,
            "consultation_deadlines": any(
                "deadline" in (snapshot.get("summary") or {})
                for source in data.get("sources") or []
                for snapshot in source.get("snapshots") or []
            ),
            "committees": "committee_assignment" in event_types,
            "opinions": "opinion_received" in event_types,
            "reports": "report_filed" in event_types,
            "votes": "vote_recorded" in event_types,
            "monitor_publication": "published_in_monitor" in event_types,
            "changed_source_alerts": any(
                len(source.get("snapshots") or []) > 1 for source in data.get("sources") or []
            ),
        },
        "problems": problems,
        "limitations": data.get("limitations") or [],
    }


def _snapshot_payload(source: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": "public-tracking-source-snapshot-v1",
        "family": source["family"],
        "identifier": source["identifier"],
        "url": source["url"],
        "label": source["label"],
        "summary": snapshot.get("summary") or {},
        "documents": snapshot.get("documents") or [],
        "events": snapshot.get("events") or [],
        "limitations": [
            "Recorded public tracking snapshot; no live source fetch was performed.",
            "Events are review signals and do not update legal conclusions automatically.",
        ],
    }


def _record_source(stare, source: dict[str, Any]) -> dict[str, Any]:
    row = source_registry.executa(
        stare,
        {
            "action": "discover",
            "family": source["family"],
            "identifier": source["identifier"],
            "url": source["url"],
            "label": source["label"],
        },
    )
    if row["state"] != "queued":
        row = source_registry.executa(stare, {"action": "queue", "id": row["id"]})
    snapshots = source["snapshots"]
    first = snapshots[0]
    source_registry._store_snapshot(
        stare,
        row["id"],
        first["content_hash"],
        _snapshot_payload(source, first),
        source["parser_version"],
    )
    row = source_registry.executa(
        stare,
        {
            "action": "record",
            "id": row["id"],
            "state": "fetched",
            "http_status": 200,
            "content_hash": first["content_hash"],
            "parser_version": source["parser_version"],
            "note": "Public tracking fixture initial snapshot.",
        },
    )
    for snapshot in snapshots[1:]:
        source_registry._store_snapshot(
            stare,
            row["id"],
            snapshot["content_hash"],
            _snapshot_payload(source, snapshot),
            source["parser_version"],
        )
        row = source_registry.executa(
            stare,
            {
                "action": "record",
                "id": row["id"],
                "state": "changed",
                "http_status": 200,
                "content_hash": snapshot["content_hash"],
                "parser_version": source["parser_version"],
                "note": "Public tracking fixture detected changed source snapshot.",
            },
        )
    return row


def _replay_events(
    stare, data: dict[str, Any], source: dict[str, Any], row: dict[str, Any]
) -> list:
    saved = []
    for snapshot in source.get("snapshots") or []:
        content_hash = snapshot["content_hash"]
        for event in snapshot.get("events") or []:
            out = tracker_events.adauga(
                stare,
                {
                    "event_type": event["event_type"],
                    "project_id": data["project_id"],
                    "source_family": source["family"],
                    "source_id": row["id"],
                    "source_url": source["url"],
                    "occurred_at": event["occurred_at"],
                    "observed_at": data["recorded_at"],
                    "title": event["title"],
                    "payload": event.get("payload") or {},
                    "content_hash": content_hash,
                },
            )
            saved.append(out["event"])
    return saved


def replay(stare, path: Path = FIXTURE) -> dict[str, Any]:
    """Seed recorded source snapshots and tracker events into the local workspace."""
    validation = validate(path)
    if validation["status"] != "ready":
        raise ValueError("Public tracking snapshot invalid.")
    data = _load(path)
    sources = []
    events = []
    for source in data["sources"]:
        row = _record_source(stare, source)
        sources.append(row)
        events.extend(_replay_events(stare, data, source, row))
    event_counts: dict[str, int] = {}
    for event in events:
        event_type = event["event_type"]
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    return {
        "contract": SEED_CONTRACT,
        "project_id": data["project_id"],
        "sources": len(sources),
        "events": len(events),
        "event_types": event_counts,
        "attention_sources": sum(
            1 for row in sources if row["state"] in source_registry.ATTENTION_STATES
        ),
        "validation": validation,
        "limitations": data.get("limitations") or [],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args(argv)
    print(json.dumps(validate(args.fixture), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
