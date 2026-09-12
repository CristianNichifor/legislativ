"""MCP handoff packet for AI drafting from selected evidence.

This prepares an approved external-call payload. It does not execute MCP.
"""

from __future__ import annotations

from scripts import ai_drafting, dosare, mcp_boundary

MAX_SERVER_TEXT = 120
MAX_TOOL_TEXT = 160


def preview(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"server", "tool", "draft"}:
        raise ValueError("Cerere MCP AI invalidă.")
    server = dosare._text(request["server"], MAX_SERVER_TEXT, True)
    tool = dosare._text(request["tool"], MAX_TOOL_TEXT, True)
    plan = ai_drafting.preview(request["draft"])
    approval = mcp_boundary.preview(
        {
            "server": server,
            "tool": tool,
            "capability": "ai_draft",
            "purpose": "Redactare ciornă legislativă din dovezi selectate de utilizator.",
            "data": plan["prompt"],
        }
    )
    return {
        "contract": "mcp-ai-evidence-draft-v1",
        "status": "requires_user_approval",
        "ai_contract": plan["contract"],
        "system": plan["system"],
        "prompt": plan["prompt"],
        "input_sha256": plan["input_sha256"],
        "evidence_sha256": plan["evidence_sha256"],
        "evidence_manifest": plan["evidence_manifest"],
        "estimated_tokens": plan["estimated_tokens"],
        "cost_estimate": {
            "contract": "mcp-ai-cost-estimate-v1",
            "ai": plan["cost_estimate"],
            "mcp": approval["cost_estimate"],
            "server_cost": "none",
            "cost_owner": "user_if_sent_to_external_tool",
        },
        "approval": {
            "required": True,
            "reason": "legal evidence prompt leaves the local app only after user action",
            "server_calls_model": False,
            "mcp_executes_now": False,
            "output_status": "draft_unreviewed",
        },
        "audit": {
            "contract": "mcp-ai-draft-audit-v1",
            "ai_input_sha256": plan["input_sha256"],
            "evidence_sha256": plan["evidence_sha256"],
            "mcp_data_sha256": approval["approval"]["data_sha256"],
            "approved_external_send": False,
            "model_invoked_by_server": False,
        },
        "evidence_count": plan["evidence_count"],
        "mcp": approval,
        "insert_header": (
            "[Ciornă MCP AI · nerevizuită · "
            f"{server}/{tool} · {approval['approval']['data_sha256']}]"
        ),
        "limitari": [
            "Serverul nu a apelat niciun MCP și niciun model AI.",
            "Utilizatorul trebuie să copieze payload-ul sau să aprobe un executor local separat.",
            "Rezultatul MCP introdus în notă rămâne ciornă nerevizuită.",
        ],
    }
