"""User-visible MCP runtime registry.

This does not open an MCP transport. It exposes the product surface the UI can
show before any future external connector is added: servers, tools, preview
requirements, approval requirements and retryable failure states.
"""

from __future__ import annotations

from datetime import UTC, datetime

from scripts import dosare, mcp_boundary, mcp_executor

CONTRACT = "mcp-runtime-surface-v1"
DISCOVERY_CONTRACT = "mcp-runtime-discovery-v1"
AUDIT_SCHEMA_CONTRACT = "mcp-audit-log-schema-v1"

APPROVAL_STATES = [
    "not_previewed",
    "preview_created",
    "approved_pending_execution",
    "approved_and_executed",
    "cancelled",
    "failed_retryable",
    "failed_terminal",
]

AUDIT_REQUIRED_FIELDS = [
    "server",
    "tool",
    "timestamp",
    "payload_hash",
    "selected_evidence_ids",
    "result_hash",
    "user_action",
]


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


def audit_schema() -> dict:
    return {
        "contract": AUDIT_SCHEMA_CONTRACT,
        "required_fields": AUDIT_REQUIRED_FIELDS,
        "fields": {
            "server": "MCP server id shown to the user before approval.",
            "tool": "MCP tool id shown to the user before approval.",
            "timestamp": "ISO-8601 timestamp for the user action.",
            "payload_hash": "SHA-256 of the exact previewed payload.",
            "selected_evidence_ids": "Evidence ids explicitly selected for the payload.",
            "result_hash": "SHA-256 of the stored result, or null before execution.",
            "user_action": "previewed|approved|approved_and_executed|copied|cancelled|failed",
        },
        "append_only": True,
        "hidden_external_calls": False,
        "credentials_stored": False,
    }


def registry() -> dict:
    capabilities = mcp_boundary.capabilities()
    schema = audit_schema()
    return {
        "contract": CONTRACT,
        "status": "available_local_mock_only",
        "discovery": {
            "contract": DISCOVERY_CONTRACT,
            "server_count": 1,
            "tool_count": 2,
            "runtime_available": True,
            "runtime_mode": "local_mock_only",
            "external_transport_configured": False,
            "hidden_external_calls": False,
            "credentials_required": False,
            "refresh_action": "retry_runtime_discovery",
            "created_at": _now(),
        },
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
                        "approval_states": APPROVAL_STATES,
                        "preview_endpoint": "/api/dosare/ai-draft/mcp-preview",
                        "execution_endpoint": "/api/dosare/ai-draft/mcp-execute",
                        "result_status": "draft_unreviewed",
                    },
                    {
                        "id": mcp_executor.SUPPORTED_EXPORT_TOOL,
                        "label": "Export document local simulat",
                        "capability": "document_export",
                        "requires_preview": True,
                        "requires_user_approval": True,
                        "approval_states": APPROVAL_STATES,
                        "preview_endpoint": "/api/dosare/mcp-export-preview",
                        "execution_endpoint": "/api/dosare/mcp-export-execute",
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
            "approval_states": APPROVAL_STATES,
            "audit_schema": {
                "server": "string",
                "tool": "string",
                "timestamp": "iso8601",
                "payload_hash": "sha256",
                "selected_evidence_ids": "array",
                "result_hash": "sha256_or_null",
                "user_action": "previewed|approved|executed|copied|cancelled",
            },
            "audit_log_schema": schema,
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
