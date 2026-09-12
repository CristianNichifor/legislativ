"""User-approved MCP call boundary.

This module does not connect to an MCP server. It validates one intended call and
returns the approval/audit payload the runtime must show before any future MCP
executor may send legal text outside the app.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from scripts import dosare

MAX_TEXT = 4000
MAX_PREVIEW = 1200
SERVER = re.compile(r"^[a-zA-Z0-9_.:-]{1,120}$")
TOOL = re.compile(r"^[a-zA-Z0-9_.:-]{1,160}$")

CAPABILITIES = {
    "ai_draft": {
        "label": "AI din abonamentul utilizatorului",
        "requires_external_text": True,
        "expected_output": "ciornă sau sumar nerevizuit",
    },
    "document_export": {
        "label": "Export document în spațiul utilizatorului",
        "requires_external_text": True,
        "expected_output": "document creat în contul conectat",
    },
    "consultation_reminder": {
        "label": "Reminder pentru termen de consultare",
        "requires_external_text": False,
        "expected_output": "eveniment sau task în contul conectat",
    },
    "source_ingest": {
        "label": "Import din folder local/conectat",
        "requires_external_text": False,
        "expected_output": "listă de fișiere/surse candidate",
    },
    "github_issue": {
        "label": "Issue GitHub pentru constatare revizuită",
        "requires_external_text": True,
        "expected_output": "issue sau draft de issue",
    },
}


def _text(value, limit: int, *, required: bool = False) -> str:
    try:
        return dosare._text(value, limit, required)
    except ValueError as exc:
        raise ValueError("Câmp MCP invalid.") from exc


def _token(value, pattern: re.Pattern[str], label: str) -> str:
    value = _text(value, 160, required=True)
    if not pattern.fullmatch(value):
        raise ValueError(f"{label} MCP invalid.")
    return value


def _capability(value) -> str:
    key = str(value or "").strip().lower().replace("-", "_")
    if key not in CAPABILITIES:
        raise ValueError("Capabilitate MCP necunoscută.")
    return key


def capabilities() -> dict:
    return {
        "contract": "mcp-boundary-v1",
        "capabilities": [{"key": key, **value} for key, value in CAPABILITIES.items()],
        "limitari": [
            "Acest contract nu execută apeluri MCP.",
            "Textul juridic poate fi trimis extern numai după aprobare explicită.",
            "Aplicația rămâne utilizabilă fără MCP.",
        ],
    }


def preview(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {
        "server",
        "tool",
        "capability",
        "purpose",
        "data",
    }:
        raise ValueError("Cerere MCP invalidă.")
    server = _token(request["server"], SERVER, "Server")
    tool = _token(request["tool"], TOOL, "Unealtă")
    capability = _capability(request["capability"])
    purpose = _text(request["purpose"], 500, required=True)
    data = _text(
        request["data"], MAX_TEXT, required=CAPABILITIES[capability]["requires_external_text"]
    )
    payload = {
        "server": server,
        "tool": tool,
        "capability": capability,
        "purpose": purpose,
        "data_preview": data[:MAX_PREVIEW],
        "data_truncated": len(data) > MAX_PREVIEW,
        "data_sha256": hashlib.sha256(data.encode()).hexdigest(),
    }
    return {
        "contract": "mcp-boundary-v1",
        "status": "requires_user_approval",
        "approval": {
            **payload,
            "capability_label": CAPABILITIES[capability]["label"],
            "expected_output": CAPABILITIES[capability]["expected_output"],
            "external_text": bool(data),
        },
        "audit_event": {
            **payload,
            "approved": False,
            "created_at": datetime.now(UTC).isoformat(),
        },
        "limitari": [
            "Previzualizare locală; nu s-a apelat niciun server MCP.",
            "Un executor MCP viitor trebuie să păstreze acest eveniment înainte de apel.",
            "Utilizatorul trebuie să vadă serverul, unealta și datele trimise.",
        ],
    }
