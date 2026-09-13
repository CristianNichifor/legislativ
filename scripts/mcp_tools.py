"""Bounded local tool surface for MCP-compatible clients.

This is not an MCP transport and it does not execute remote calls. It is a
small, dependency-free adapter that external AI clients can wrap as tools while
the app keeps the same local-first/BYOK boundary as the browser and localhost
server.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts import ai_drafting, project_evidence_pack, tracker_events
from scripts.servicii import Stare, _cauta

CONTRACT = "bounded-mcp-tools-v1"
MAX_LIMIT = 50
MAX_TIMELINE_EVENTS = 100
FORBIDDEN_TOOL_NAMES = {
    "legal_verdict",
    "compliance_verdict",
    "decide_legality",
    "decide_constitutionality",
    "ai_legal_verdict",
}


def _int_arg(args: dict, key: str, default: int, maximum: int) -> int:
    value = args.get(key, default)
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Argument numeric MCP invalid.") from exc
    if not 1 <= out <= maximum:
        raise ValueError("Argument numeric MCP invalid.")
    return out


def _offset(args: dict) -> int:
    value = args.get("offset", 0)
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Offset MCP invalid.") from exc
    if not 0 <= out <= 100_000:
        raise ValueError("Offset MCP invalid.")
    return out


def _text_arg(args: dict, key: str, *, required: bool = False, limit: int = 200) -> str:
    value = args.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("Argument text MCP invalid.")
    value = value.strip()
    if required and not value:
        raise ValueError("Argument MCP obligatoriu lipsă.")
    if len(value) > limit or "\x00" in value:
        raise ValueError("Argument text MCP invalid.")
    return value


def _project_query(project_id: str, limit: int, offset: int = 0) -> dict[str, list[str]]:
    return {"project_id": [project_id], "limit": [str(limit)], "offset": [str(offset)]}


def _tool_schema(
    name: str,
    description: str,
    properties: dict[str, dict],
    required: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required or [],
        },
    }


def tool_schemas() -> dict:
    tools = [
        _tool_schema(
            "search_laws",
            "Search local law provisions by text with optional type/year filters.",
            {
                "q": {"type": "string", "minLength": 1, "maxLength": 200},
                "tip": {"type": "string", "maxLength": 40},
                "an_min": {"type": "integer"},
                "an_max": {"type": "integer"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                "offset": {"type": "integer", "minimum": 0},
            },
            ["q"],
        ),
        _tool_schema(
            "search_projects",
            "Search local legislative projects and their bounded lifecycle status.",
            {
                "q": {"type": "string", "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT},
                "offset": {"type": "integer", "minimum": 0},
                "stale_days": {"type": "integer", "minimum": 1, "maximum": 3660},
            },
        ),
        _tool_schema(
            "get_source_status",
            (
                "Report which local data stores are present without synchronizing "
                "or fetching remotely."
            ),
            {},
        ),
        _tool_schema(
            "get_project_timeline",
            "Return local tracker events for one project as a procedural timeline.",
            {
                "project_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TIMELINE_EVENTS},
                "offset": {"type": "integer", "minimum": 0},
            },
            ["project_id"],
        ),
        _tool_schema(
            "get_evidence_bundle",
            "Assemble selected local tracker and dossier evidence for one project.",
            {
                "project_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "dossier_id": {"type": "string", "maxLength": 200},
                "event_limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "note_limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ["project_id"],
        ),
        _tool_schema(
            "draft_from_evidence",
            "Build a source-grounded draft prompt from selected evidence; no model is called.",
            {
                "task": {"type": "string"},
                "type": {"type": "string"},
                "title": {"type": "string", "maxLength": 200},
                "context": {"type": "string", "maxLength": 2000},
                "evidence": {"type": "array", "minItems": 1, "maxItems": ai_drafting.MAX_EVIDENCE},
            },
            ["evidence"],
        ),
    ]
    return {
        "contract": CONTRACT,
        "transport": "local_command_or_module",
        "tools": tools,
        "forbidden_tools": sorted(FORBIDDEN_TOOL_NAMES),
        "execution": {
            "external_calls": False,
            "model_calls": False,
            "credentials_stored": False,
            "cost_owner": "none_until_user_wraps_with_byok_or_mcp_client",
        },
        "limitari": [
            "Suprafața este locală și bounded; nu sincronizează surse și nu apelează modele.",
            "Nu există unelte pentru verdict juridic, conformitate sau constituționalitate.",
            "Ciornele din dovezi sunt prompturi nerevizuite, nu concluzii juridice.",
        ],
    }


def search_laws(stare: Stare, args: dict) -> dict:
    limit = _int_arg(args, "limit", 10, MAX_LIMIT)
    offset = _offset(args)
    an_min = args.get("an_min")
    an_max = args.get("an_max")
    out = _cauta(
        _text_arg(args, "q", required=True),
        stare,
        tip=_text_arg(args, "tip", limit=40) or None,
        an_min=int(an_min) if an_min not in (None, "") else None,
        an_max=int(an_max) if an_max not in (None, "") else None,
        limita=limit,
        offset=offset,
    )
    return {
        "contract": "bounded-mcp-search-laws-v1",
        "tool": "search_laws",
        **out,
        "limitari": [
            (
                "Căutare full-text în corpusul local; rezultatele sunt locatori "
                "și fragmente, nu verdict."
            )
        ],
    }


def search_projects(stare: Stare, args: dict) -> dict:
    from scripts.lifecycle import project_lifecycle_summary

    out = project_lifecycle_summary(
        stare,
        query=_text_arg(args, "q"),
        limit=_int_arg(args, "limit", 10, MAX_LIMIT),
        offset=_offset(args),
        stale_days=_int_arg(args, "stale_days", 30, 3660),
    )
    return {
        "contract": "bounded-mcp-search-projects-v1",
        "tool": "search_projects",
        **out,
        "limitari": [
            *out.get("limitari", []),
            "Stadiile sunt normalizări locale ale surselor parlamentare, nu evaluări juridice.",
        ],
    }


def get_source_status(stare: Stare, args: dict | None = None) -> dict:
    del args
    report_root = getattr(stare, "report_root", None)
    stores = {
        "corpus": Path(stare.corpus),
        "initiative": Path(stare.initiative),
        "tracker_events": tracker_events.cale(stare),
        "eu": Path(stare.eu),
        "reports": Path(report_root) if report_root is not None else None,
    }
    shaped = {}
    present = 0
    for key, path in stores.items():
        available = bool(path and (path.is_dir() if key == "reports" else path.is_file()))
        present += int(available)
        shaped[key] = {
            "available": available,
            "path": str(path) if path else "",
            "kind": "directory" if key == "reports" else "sqlite",
        }
    return {
        "contract": "bounded-mcp-source-status-v1",
        "tool": "get_source_status",
        "mode": "local_first",
        "source_status": "ok" if present == len(stores) else "partial" if present else "missing",
        "stores": shaped,
        "external_calls": False,
        "model_calls": False,
        "credentials_stored": False,
        "limitari": [
            "Statusul inspectează numai fișiere locale; nu descarcă și nu sincronizează surse.",
            "Prezența unui fișier nu este verdict de completitudine sau actualitate juridică.",
        ],
    }


def get_project_timeline(stare: Stare, args: dict) -> dict:
    project_id = _text_arg(args, "project_id", required=True)
    query = _project_query(
        project_id,
        _int_arg(args, "limit", 50, MAX_TIMELINE_EVENTS),
        _offset(args),
    )
    out = tracker_events.lista(stare, query)
    return {
        "contract": "bounded-mcp-project-timeline-v1",
        "tool": "get_project_timeline",
        "project_id": project_id,
        "source_status": out.get("source_status", "unknown"),
        "events": out.get("events", []),
        "summary": out.get("summary", {}),
        "limitari": [
            *out.get("limitari", []),
            "Cronologia este citită din trackerul local; nu este verdict juridic.",
        ],
    }


def get_evidence_bundle(stare: Stare, args: dict) -> dict:
    query = {
        "project_id": [_text_arg(args, "project_id", required=True)],
        "dossier_id": [_text_arg(args, "dossier_id")],
        "event_limit": [str(_int_arg(args, "event_limit", 100, 200))],
        "note_limit": [str(_int_arg(args, "note_limit", 25, 50))],
    }
    out = project_evidence_pack.build(stare, query)
    return {"tool": "get_evidence_bundle", **out}


def draft_from_evidence(stare: Stare, args: dict) -> dict:
    del stare
    out = ai_drafting.preview(args)
    return {"tool": "draft_from_evidence", **out}


TOOLS = {
    "search_laws": search_laws,
    "search_projects": search_projects,
    "get_source_status": get_source_status,
    "get_project_timeline": get_project_timeline,
    "get_evidence_bundle": get_evidence_bundle,
    "draft_from_evidence": draft_from_evidence,
}


def call_tool(stare: Stare, name: str, args: dict | None = None) -> dict:
    key = str(name or "").strip()
    if key in FORBIDDEN_TOOL_NAMES or "verdict" in key or "legality" in key:
        raise ValueError("Unealta MCP cerută ar emite un verdict juridic și nu este expusă.")
    if key not in TOOLS:
        raise ValueError("Unealtă MCP necunoscută.")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("Argumente MCP invalide.")
    return TOOLS[key](stare, args)


def _state_from_args(args: argparse.Namespace) -> Stare:
    return Stare(
        corpus=args.corpus,
        initiative=args.initiative,
        graf=args.graf,
        eu=args.eu,
        date_dir=args.date_dir,
        reports_dir=args.reports_dir,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded local MCP tool surface")
    parser.add_argument("--corpus", default="corpus.db")
    parser.add_argument("--initiative", default="initiative.db")
    parser.add_argument("--graf", default="graf.db")
    parser.add_argument("--eu", default="eu.db")
    parser.add_argument("--date-dir")
    parser.add_argument("--reports-dir")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    call = sub.add_parser("call")
    call.add_argument("tool")
    call.add_argument("args", nargs="?", default="{}")
    ns = parser.parse_args(argv)
    if ns.command == "list":
        print(json.dumps(tool_schemas(), ensure_ascii=False, indent=2))
        return 0
    payload: Any = json.loads(ns.args)
    print(
        json.dumps(call_tool(_state_from_args(ns), ns.tool, payload), ensure_ascii=False, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
