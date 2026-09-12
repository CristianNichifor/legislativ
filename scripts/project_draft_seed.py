"""Draft seed text from local legislative project tracker events."""

from __future__ import annotations

import re

from scripts import tracker_events

CONTRACT = "project-draft-seed-v1"
TOKEN = re.compile(r"^[a-z0-9_.:/ -]{1,200}$", re.I)


def _token(value: object) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Identificator proiect invalid.")
    value = value.strip()
    if not value or len(value) > 200 or "\x00" in value or not TOKEN.fullmatch(value):
        raise ValueError("Identificator proiect invalid.")
    return value


def _event_line(event: dict) -> str:
    label = event.get("display_label") or event.get("event_label") or event["event_type"]
    date = event.get("occurred_at", "").split("T", 1)[0]
    source = event.get("source_family") or "sursă necunoscută"
    title = event.get("title") or label
    return f"- {date}: {label} ({source}) - {title}"


def _source_line(event: dict) -> str:
    source = event.get("source_url") or "sursă locală fără URL"
    digest = event.get("content_hash") or "fără hash"
    return f"- {event.get('source_family') or 'sursă'}: {source} [{digest}]"


def build(stare, query: dict | None = None) -> dict:
    query = query or {}
    project_id = _token((query.get("project_id") or query.get("proiect") or [""])[0])
    out = tracker_events.lista(stare, {"project_id": [project_id], "limit": ["50"]})
    events = out.get("events", [])
    title = next((event.get("title") for event in events if event.get("title")), project_id)
    lines = [
        f"Proiect urmărit: {project_id}",
        f"Titlu de lucru: {title}",
        "",
        "Obiectul intervenției:",
        "- [completează modificarea normativă urmărită]",
        "",
        "Evenimente procedurale verificate:",
    ]
    lines.extend([_event_line(event) for event in events] or ["- Nu există evenimente locale."])
    lines.extend(
        [
            "",
            "Surse și dovezi:",
            *([_source_line(event) for event in events[:10]] or ["- Nu există surse locale."]),
            "",
            "Verificări înainte de redactare:",
            "- Confirmă stadiul procedural în sursa oficială.",
            "- Verifică avizele, rapoartele, voturile și publicarea în Monitorul Oficial.",
            "- Verifică efectul asupra actelor naționale și UE relevante.",
            "",
            "Notă: acest text este un punct de pornire factual, nu verdict juridic.",
        ]
    )
    return {
        "contract": CONTRACT,
        "project_id": project_id,
        "text": "\n".join(lines),
        "summary": {
            "events": len(events),
            "sources": len(
                {event.get("source_url") for event in events if event.get("source_url")}
            ),
        },
        "limitari": [
            "Ciorna include doar evenimente tracker locale.",
            "Textul rezultat trebuie completat și verificat juridic înainte de folosire.",
        ],
    }
