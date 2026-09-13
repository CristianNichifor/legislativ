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


def _real_pilot_pack() -> dict:
    path = Path(__file__).resolve().parents[1] / "data" / "real_pilot_pack.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unavailable", "requirements": []}


def raport(stare) -> dict:
    try:
        sources = acoperire_surse.raport(stare)
    except (OSError, ValueError) as exc:
        sources = {
            "status": "blocked",
            "blockers": [{"kind": "source_coverage", "message": str(exc)}],
        }
    pilot = _pilot()
    pack = _real_pilot_pack()
    output = pilot.get("acceptance_output") or {}
    workbench = output.get("workbench") or {}
    eu = workbench.get("eu_availability") or {}
    known_gaps = pilot.get("known_gaps") or pilot.get("conclusion") or {}
    requirements = pack.get("requirements") or []
    required = [item for item in requirements if item.get("required")]
    ready_required = [item for item in required if item.get("status") == "ready"]
    ready_keys = {item.get("key") for item in ready_required}
    current_pack_ready = pack.get("status") == "ready" and len(ready_required) == len(required) == 5
    celex_ready = "celex_text" in ready_keys
    reviewable_ready = "reviewable_finding" in ready_keys
    capabilities = [
        {
            "key": "manual_gap_workspace",
            "label": "Note/dosare manuale",
            "state": "ready",
            "evidence": "note_manuale + dosare locale + export",
        },
        {
            "key": "single_source_sync",
            "label": "Sync sursă individuală",
            "state": "partial",
            "evidence": "registru surse + sync parlamentar/CELEX punctual",
        },
        {
            "key": "lifecycle_tracking",
            "label": "Lifecycle proiecte",
            "state": "partial",
            "evidence": "timeline/stage feed local; consultările guvern/ministere rămân incomplete",
        },
        {
            "key": "eu_checks",
            "label": "Verificare UE",
            "state": "ready" if celex_ready else "partial",
            "evidence": (
                "real pilot pack: official CELEX text fixture ready"
                if celex_ready
                else "CELEX la cerere + note risc UE; text UE oficial încă nepregătit"
            ),
        },
        {
            "key": "law_as_code",
            "label": "Law as code",
            "state": "partial",
            "evidence": "candidate -> draft rule -> delegated-norm check preview",
        },
        {
            "key": "ai_byok",
            "label": "AI BYOK/local",
            "state": "partial",
            "evidence": "prompt/evidence/cost/approval UI; calitatea modelelor nu este măsurată",
        },
        {
            "key": "mcp",
            "label": "MCP",
            "state": "partial",
            "evidence": "handoff/audit boundary; fără executor MCP real",
        },
        {
            "key": "acceptance_metrics",
            "label": "Metrici acceptanță",
            "state": "ready" if current_pack_ready and reviewable_ready else "partial",
            "evidence": (
                "real pilot pack: 5/5 ingrediente pregătite pentru gate închis"
                if current_pack_ready and reviewable_ready
                else "pilot runtime + dashboard; lipsesc precizie/recall și test UX complet"
            ),
        },
    ]
    ready = sum(1 for item in capabilities if item["state"] == "ready")
    partial = sum(1 for item in capabilities if item["state"] == "partial")
    missing_capabilities = sum(1 for item in capabilities if item["state"] == "missing")
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
            "status": "ok" if celex_ready else "attention",
            "summary": (
                "Current real pilot pack has an official CELEX text fixture ready."
                if celex_ready
                else known_gaps.get("eu_text_availability", "Disponibilitate UE nemăsurată.")
            ),
            "metrics": {
                "referenced": eu.get("total", 0),
                "official_texts_ready": 1 if celex_ready else 0,
                "romanian_texts_ready": 1 if celex_ready else 0,
                "english_texts_ready": 0,
            },
        },
        {
            "key": "real_pilot_pack",
            "label": "Pachet pilot real",
            "status": "ok" if current_pack_ready else "attention",
            "summary": (
                "All 5 required ingredients are ready for the closed-gate acceptance command."
                if current_pack_ready
                else "Pachetul pilot real nu are încă toate ingredientele obligatorii pregătite."
            ),
            "metrics": {
                "required_ready": len(ready_required),
                "required_total": len(required),
                "reviewable_findings_ready": 1 if reviewable_ready else 0,
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
        "capability_summary": {
            "ready": ready,
            "partial": partial,
            "missing": missing_capabilities,
            "total": len(capabilities),
        },
        "capabilities": capabilities,
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
