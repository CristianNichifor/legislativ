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


def _payload_values(events: list[dict], *keys: str) -> list[str]:
    values = []
    for event in events:
        payload = event.get("payload") or {}
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip() and value.strip() not in values:
                values.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip() and item.strip() not in values:
                        values.append(item.strip())
    return values


def _event_types(events: list[dict]) -> set[str]:
    return {event.get("event_type", "") for event in events}


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
        "Bază legală / acte afectate:",
    ]
    affected = _payload_values(events, "act_id", "affected_act", "target_act", "celex")
    lines.extend(
        [f"- {value}" for value in affected] or ["- [completează actele naționale/UE vizate]"]
    )
    types = _event_types(events)
    consultation = (
        "consultare deschisă"
        if "public_consultation_opened" in types
        else "consultare închisă"
        if "public_consultation_closed" in types
        else "neconfirmat local"
    )
    parliament = next(
        (
            event.get("stage_label")
            for event in events
            if event.get("source_family") in {"camera", "senat"} and event.get("stage_label")
        ),
        "neconfirmat local",
    )
    lines.extend(
        [
            "",
            "Stadiu consultare publică:",
            f"- {consultation}",
            "",
            "Stadiu parlamentar:",
            f"- {parliament}",
            "",
            "Risc UE / drept european:",
        ]
    )
    eu_refs = _payload_values(events, "celex", "eu_reference", "eu_refs")
    lines.extend([f"- {value}" for value in eu_refs] or ["- [verifică CELEX/articol relevant]"])
    lines.extend(
        [
            "",
            "Obiectul intervenției:",
            "- [completează modificarea normativă urmărită]",
            "",
            "Evenimente procedurale verificate:",
        ]
    )
    lines.extend([_event_line(event) for event in events] or ["- Nu există evenimente locale."])
    lines.extend(
        [
            "",
            "Surse și dovezi:",
            *([_source_line(event) for event in events[:10]] or ["- Nu există surse locale."]),
            "",
            "Verificări înainte de redactare:",
            "- Confirmă stadiul procedural în sursa oficială.",
            "- Completează baza legală și actele afectate.",
            "- Confirmă consultarea publică și termenul-limită.",
            "- Verifică avizele, rapoartele, voturile și publicarea în Monitorul Oficial.",
            "- Verifică efectul asupra actelor naționale și UE relevante.",
            "- Notează lacunele, loopholes sau contradicțiile în dosarul local.",
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
            "affected_acts": len(affected),
            "eu_references": len(eu_refs),
        },
        "limitari": [
            "Ciorna include doar evenimente tracker locale.",
            "Textul rezultat trebuie completat și verificat juridic înainte de folosire.",
        ],
    }
