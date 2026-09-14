"""MCP preview packet for a bounded dossier export workflow."""

from __future__ import annotations

import hashlib

from scripts import dosare, mcp_boundary

MAX_SERVER_TEXT = 120
MAX_TOOL_TEXT = 160
MAX_TITLE = 200
MAX_BODY = 8000


def _field(data: dict, key: str, limit: int, required: bool = False) -> str:
    return dosare._text(data.get(key, ""), limit, required)


def _markdown(export: dict) -> str:
    title = _field(export, "title", MAX_TITLE, True)
    note_type = _field(export, "type", 80)
    act_id = _field(export, "act_id", 200)
    locator = _field(export, "locator", 120)
    source_url = _field(export, "source_url", 1000)
    source_hash = _field(export, "source_hash", 64)
    quote = _field(export, "evidence_quote", 4000)
    reasoning = _field(export, "reasoning", MAX_BODY)
    lines = [
        f"# {title}",
        "",
        "Export MCP local-mock. Ciornă nerevizuită; nu verdict juridic.",
        "",
        f"- Tip: {note_type or 'nespecificat'}",
        f"- Act/proiect: {act_id or 'neatasat'}",
        f"- Locator: {locator or 'neatasat'}",
        f"- URL sursa: {source_url or 'neatasat'}",
        f"- SHA-256 sursa: {source_hash or 'neatasat'}",
        "",
        "## Citat dovada",
        quote or "Nicio dovada selectata.",
        "",
        "## Rationament",
        reasoning or "Niciun rationament exportat.",
    ]
    return "\n".join(lines).strip()


def _selected_evidence_ids(export: dict) -> list[str]:
    act_id = _field(export, "act_id", 200)
    locator = _field(export, "locator", 120)
    source_hash = _field(export, "source_hash", 64)
    value = ":".join(part for part in (act_id, locator) if part) or source_hash
    return [value] if value else []


def preview(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"server", "tool", "export"}:
        raise ValueError("Cerere MCP export invalidă.")
    server = dosare._text(request["server"], MAX_SERVER_TEXT, True)
    tool = dosare._text(request["tool"], MAX_TOOL_TEXT, True)
    export = request["export"]
    if not isinstance(export, dict):
        raise ValueError("Export MCP invalid.")
    markdown = _markdown(export)
    approval = mcp_boundary.preview(
        {
            "server": server,
            "tool": tool,
            "capability": "document_export",
            "purpose": "Export dosar/notă legislativă în spațiul ales de utilizator.",
            "data": markdown,
        }
    )
    return {
        "contract": "mcp-dossier-export-v1",
        "status": "requires_user_approval",
        "markdown": markdown,
        "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
        "selected_evidence_ids": _selected_evidence_ids(export),
        "mcp": approval,
        "approval": {
            "required": True,
            "mcp_executes_now": False,
            "output_status": "export_preview",
            "server_calls_model": False,
            "private_data_excluded": approval["approval"]["private_data_excluded"],
        },
        "audit": {
            "contract": "mcp-export-audit-v1",
            "mcp_data_sha256": approval["approval"]["data_sha256"],
            "approved_external_send": False,
            "selected_evidence_ids": _selected_evidence_ids(export),
        },
        "cost_estimate": {
            "contract": "mcp-export-cost-estimate-v1",
            "server_cost": "none",
            "cost_owner": "user_if_sent_to_external_tool",
            "mcp": approval["cost_estimate"],
        },
        "limitari": [
            "Previzualizarea nu trimite documentul către niciun server MCP extern.",
            "Executorul v1 salvează doar un rezultat local-mock și audit local.",
            "Credentialele nu sunt cerute și nu sunt stocate.",
        ],
    }
