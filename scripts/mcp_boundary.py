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
        "execution": {
            "implemented": True,
            "runtime_contract": "mcp-runtime-surface-v1",
            "executor_contract": "mcp-executor-boundary-v1",
            "supported_executor": "local-mock/ai.draft",
            "requires_user_approval": True,
            "approval_event_contract": "mcp-audit-event-v1",
            "cost_owner": "user_account_or_user_key",
            "credentials_stored": False,
            "hidden_external_calls": False,
            "external_calls": False,
        },
        "runtime": {
            "servers_endpoint": "/api/mcp/runtime",
            "test_endpoint": "/api/mcp/test",
            "preview_endpoint": "/api/mcp/preview",
            "execution_endpoint": "/api/dosare/ai-draft/mcp-execute",
            "payload_preview_required": True,
            "failure_contract": "mcp-runtime-failure-v1",
        },
        "limits": {
            "contract": "mcp-boundary-limits-v1",
            "max_data_chars": MAX_TEXT,
            "max_preview_chars": MAX_PREVIEW,
            "max_server_id_chars": 120,
            "max_tool_id_chars": 160,
        },
        "private_data_excluded": [
            "chei API sau tokenuri",
            "configurări BYOK salvate în browser",
            "baze de date locale/private",
            "date neselectate explicit de utilizator pentru payload",
        ],
        "limitari": [
            "Acest contract nu execută apeluri MCP.",
            "Executorul v1 rulează doar adaptorul local-mock/ai.draft și păstrează audit local.",
            "Textul juridic poate fi trimis extern numai după aprobare explicită.",
            "Aplicația rămâne utilizabilă fără MCP.",
            "Nu se stochează credentiale și nu există apeluri externe ascunse.",
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
    data_sha256 = hashlib.sha256(data.encode()).hexdigest()
    created_at = datetime.now(UTC).isoformat()
    payload = {
        "server": server,
        "tool": tool,
        "capability": capability,
        "purpose": purpose,
        "data_preview": data[:MAX_PREVIEW],
        "data_truncated": len(data) > MAX_PREVIEW,
        "data_sha256": data_sha256,
        "data_chars": len(data),
        "estimated_input_tokens": max(0, len(data) // 4),
        "data_classification": (
            "legal_text_or_evidence"
            if CAPABILITIES[capability]["requires_external_text"]
            else "metadata"
        ),
        "max_data_chars": MAX_TEXT,
    }
    approval = {
        **payload,
        "capability_label": CAPABILITIES[capability]["label"],
        "expected_output": CAPABILITIES[capability]["expected_output"],
        "external_text": bool(data),
        "requires_user_approval": True,
        "approved": False,
        "cost_owner": "user_account_or_user_key",
        "retention_policy": "executor_must_disclose_destination_retention",
        "private_data_excluded": [
            "chei API sau tokenuri",
            "configurări BYOK salvate în browser",
            "baze de date locale/private",
            "date neselectate explicit de utilizator pentru payload",
        ],
        "credentials_stored": False,
        "hidden_external_calls": False,
    }
    return {
        "contract": "mcp-boundary-v1",
        "status": "requires_user_approval",
        "approval_state": "preview_created",
        "approval": approval,
        "audit_event": {
            **payload,
            "contract": "mcp-audit-event-v1",
            "event": "mcp_preview_created",
            "timestamp": created_at,
            "payload_hash": data_sha256,
            "selected_evidence_ids": [],
            "result_hash": None,
            "user_action": "previewed",
            "approval_state": "preview_created",
            "approved": False,
            "requires_user_approval": True,
            "cost_owner": "user_account_or_user_key",
            "created_at": created_at,
        },
        "cost_estimate": {
            "contract": "mcp-cost-estimate-v1",
            "estimated_input_tokens": payload["estimated_input_tokens"],
            "estimated_output_tokens": None,
            "server_cost": "none",
            "cost_owner": "user_account_or_user_key",
            "price_unknown_until_user_selects_mcp_server": True,
        },
        "limitari": [
            "Previzualizare locală; nu s-a apelat niciun server MCP.",
            "Un executor MCP viitor trebuie să păstreze acest eveniment înainte de apel.",
            "Utilizatorul trebuie să vadă serverul, unealta și datele trimise.",
        ],
    }
