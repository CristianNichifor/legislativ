"""Read-only acceptance dashboard for project finish state."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import acoperire_surse


def _pilot() -> dict:
    path = Path(__file__).resolve().parents[1] / "docs" / "v1_acceptance_pilot_2026-09-11.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unavailable", "acceptance_output": {}, "known_gaps": {}}


def raport(stare) -> dict:
    try:
        sources = acoperire_surse.raport(stare)
    except (OSError, ValueError) as exc:
        sources = {
            "status": "blocked",
            "blockers": [{"kind": "source_coverage", "message": str(exc)}],
        }
    pilot = _pilot()
    output = pilot.get("acceptance_output") or {}
    workbench = output.get("workbench") or {}
    eu = workbench.get("eu_availability") or {}
    known_gaps = pilot.get("known_gaps") or pilot.get("conclusion") or {}
    sections = [
        {
            "key": "local_v1",
            "label": "Local-first v1",
            "status": "attention" if "pending" in pilot.get("status", "") else "ok",
            "summary": pilot.get("status", "Pilot neînregistrat."),
            "metrics": {
                "acts": output.get("acte", 0),
                "search_results": output.get("search_results", 0),
                "provisions": (pilot.get("release") or {}).get("provisions", 0),
            },
        },
        {
            "key": "sources",
            "label": "Surse publice",
            "status": "ok" if sources.get("status") == "ok" else "attention",
            "summary": (
                f"{sources.get('missing_required', 0)} familii lipsă, "
                f"{sources.get('attention_sources', 0)} surse cu atenție."
            ),
            "metrics": {
                "families": len(sources.get("families") or []),
                "blockers": len(sources.get("blockers") or []),
            },
        },
        {
            "key": "eu",
            "label": "Drept UE",
            "status": "ok" if eu.get("text_importat", 0) else "attention",
            "summary": known_gaps.get("eu_text_availability", "Disponibilitate UE nemăsurată."),
            "metrics": {
                "referenced": eu.get("total", 0),
                "imported_text": eu.get("text_importat", 0),
                "romanian_text": eu.get("text_romanian", 0),
                "english_text": eu.get("text_english", 0),
            },
        },
        {
            "key": "ai_mcp",
            "label": "AI / MCP",
            "status": "attention",
            "summary": (
                "Boundary/audit metadata există; calitatea AI și primul workflow MCP real "
                "rămân de măsurat."
            ),
            "metrics": {"measured_models": 0, "mcp_workflows": 0},
        },
    ]
    return {
        "contract": "acceptance-dashboard-v1",
        "status": "attention" if any(s["status"] != "ok" for s in sections) else "ok",
        "sections": sections,
        "source_coverage": sources,
        "pilot": {
            "date": pilot.get("date"),
            "tested_commit": pilot.get("tested_commit"),
            "status": pilot.get("status"),
            "known_gaps": known_gaps,
        },
        "limitari": [
            "Dashboard-ul citește dovezi locale existente; nu reconstruiește seturi de date.",
            "Nu măsoară acuratețe juridică sau acoperire completă fără un set adjudecat.",
        ],
    }
