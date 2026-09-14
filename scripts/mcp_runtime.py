"""User-visible MCP runtime registry.

This does not open an MCP transport. It exposes the product surface the UI can
show before any future external connector is added: servers, tools, preview
requirements, approval requirements and retryable failure states.
"""

from __future__ import annotations

from datetime import UTC, datetime

from scripts import dosare, mcp_boundary, mcp_executor

CONTRACT = "mcp-runtime-surface-v1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def failure(code: str, message: str, *, retryable: bool = False) -> dict:
    return {
        "contract": "mcp-runtime-failure-v1",
        "code": code,
        "message": message,
        "retryable": retryable,
        "hidden_external_calls": False,
        "external_calls": False,
        "created_at": _now(),
    }


def registry() -> dict:
    capabilities = mcp_boundary.capabilities()
    return {
        "contract": CONTRACT,
        "status": "available_local_mock_only",
        "servers": [
            {
                "id": mcp_executor.SUPPORTED_SERVER,
                "label": "Adaptor local de probă",
                "available": True,
                "transport": "local-module",
                "external_calls": False,
                "credentials_stored": False,
                "app_paid_ai": False,
                "tools": [
                    {
                        "id": mcp_executor.SUPPORTED_TOOL,
                        "label": "Ciornă AI locală simulată",
                        "capability": "ai_draft",
                        "requires_preview": True,
                        "requires_user_approval": True,
                        "result_status": "draft_unreviewed",
                    },
                    {
                        "id": mcp_executor.SUPPORTED_EXPORT_TOOL,
                        "label": "Export document local simulat",
                        "capability": "document_export",
                        "requires_preview": True,
                        "requires_user_approval": True,
                        "result_status": "export_unreviewed",
                    },
                ],
            }
        ],
        "capabilities": capabilities["capabilities"],
        "approval": {
            "required_for_every_external_call": True,
            "payload_preview_required": True,
            "audit_event_contract": "mcp-audit-event-v1",
            "audit_schema": {
                "server": "string",
                "tool": "string",
                "timestamp": "iso8601",
                "payload_hash": "sha256",
                "selected_evidence_ids": "array",
                "result_hash": "sha256_or_null",
                "user_action": "previewed|approved|executed|copied|cancelled",
            },
        },
        "failure_states": [
            failure("mcp_unavailable", "Executorul MCP local nu este disponibil.", retryable=True),
            failure("unknown_server", "Server MCP necunoscut."),
            failure("unknown_tool", "Unealtă MCP necunoscută."),
            failure("approval_required", "Aprobarea explicită lipsește."),
            failure("payload_mismatch", "Payloadul aprobat nu mai corespunde cererii curente."),
            failure("executor_failed", "Executorul MCP a eșuat.", retryable=True),
        ],
        "limitari": [
            "V1 listează și testează doar adaptoare local-mock.",
            "Nu se trimit date către servere MCP externe din acest runtime.",
            "Fiecare apel extern viitor trebuie să afișeze payloadul și să ceară aprobare.",
        ],
    }


def test_connection(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"server", "tool"}:
        raise ValueError("Cerere test MCP invalidă.")
    server = dosare._text(request["server"], 120, True)
    tool = dosare._text(request["tool"], 160, True)
    config = mcp_executor.test_config({"server": server, "tool": tool})
    return {
        "contract": "mcp-runtime-test-v1",
        "server": server,
        "tool": tool,
        "available": config["available"],
        "status": "available" if config["available"] else "unsupported",
        "mode": config["mode"],
        "supported_workflows": config["supported_workflows"],
        "requires_user_approval": True,
        "preview_required_before_execute": True,
        "hidden_external_calls": False,
        "external_calls": False,
        "credentials_stored": False,
        "failure": None
        if config["available"]
        else failure("unknown_server", "V1 acceptă doar local-mock cu unelte aprobate."),
        "created_at": _now(),
    }
