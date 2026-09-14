"""Bounded MCP executor boundary for one approved local workflow.

The v1 executor intentionally supports only a deterministic local mock adapter.
It proves the configure/test/run/audit shape without adding a hidden network
path, credential storage or app-paid model calls.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from scripts import dosare, mcp_ai_draft, mcp_export

CONTRACT = "mcp-executor-boundary-v1"
SUPPORTED_SERVER = "local-mock"
SUPPORTED_TOOL = "ai.draft"
SUPPORTED_EXPORT_TOOL = "document.export"
MAX_RESULT = 8000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _selected_evidence_ids(plan: dict) -> list[str]:
    ids = []
    for item in plan.get("evidence_manifest", []):
        if not isinstance(item, dict):
            continue
        act_id = str(item.get("act_id") or "").strip()
        locator = str(item.get("locator") or "").strip()
        label = str(item.get("label") or "").strip()
        ids.append(":".join(part for part in (act_id, locator) if part) or label)
    return [item for item in ids if item]


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS mcp_audit_events ("
        "id TEXT PRIMARY KEY, dosar_id TEXT NOT NULL REFERENCES dosare(id), "
        "event_type TEXT NOT NULL, server TEXT NOT NULL, tool TEXT NOT NULL, "
        "data_sha256 TEXT NOT NULL, request_sha256 TEXT NOT NULL, "
        "result_sha256 TEXT NOT NULL, status TEXT NOT NULL, "
        "audit_json TEXT NOT NULL, creat_la TEXT NOT NULL)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS mcp_audit_events_dosar "
        "ON mcp_audit_events(dosar_id,creat_la DESC,id)"
    )
    for operation in ("UPDATE", "DELETE"):
        con.execute(
            f"CREATE TRIGGER IF NOT EXISTS mcp_audit_events_no_{operation.lower()} "
            f"BEFORE {operation} ON mcp_audit_events BEGIN "
            "SELECT RAISE(ABORT,'MCP audit events are append-only'); END"
        )


def test_config(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"server", "tool"}:
        raise ValueError("Configurație MCP invalidă.")
    server = dosare._text(request["server"], 120, True)
    tool = dosare._text(request["tool"], 160, True)
    supported = server == SUPPORTED_SERVER and tool in {SUPPORTED_TOOL, SUPPORTED_EXPORT_TOOL}
    workflows = {
        SUPPORTED_TOOL: ["ai_draft"],
        SUPPORTED_EXPORT_TOOL: ["document_export"],
    }.get(tool, [])
    return {
        "contract": "mcp-executor-config-test-v1",
        "server": server,
        "tool": tool,
        "available": supported,
        "mode": "local_mock_only" if supported else "unsupported",
        "external_calls": False,
        "credentials_stored": False,
        "app_paid_ai": False,
        "supported_workflows": workflows if supported else [],
        "limitari": [
            "V1 rulează doar adaptoare local-mock în teste.",
            "Nu există apeluri de rețea, credentiale salvate sau cost AI al aplicației.",
        ],
    }


def _mock_ai_draft(plan: dict) -> str:
    evidence = plan.get("evidence_manifest", [])
    labels = [
        f"{item.get('index')}. {item.get('label')}" for item in evidence if isinstance(item, dict)
    ]
    cited = "\n".join(f"- {label}" for label in labels) or "- dovezi selectate"
    return (
        "[Ciornă MCP locală · nerevizuită]\n"
        "Nu verdict juridic. Verifică manual fiecare afirmație înainte de folosire.\n\n"
        "Ipoteză de lucru:\n"
        "Dovezile selectate pot susține redactarea unei note, dar nu stabilesc singure "
        "efectul juridic.\n\n"
        "Dovezi folosite:\n"
        f"{cited}\n\n"
        "Pași de verificare:\n"
        "- confirmă textul oficial și versiunea sursei;\n"
        "- confirmă dacă există excepții sau acte subsecvente;\n"
        "- marchează rezultatul ca revizuit doar după control uman."
    )


def _mock_document_export(plan: dict) -> str:
    digest = plan["mcp"]["approval"]["data_sha256"][:12]
    return (
        "[Export MCP local · nerevizuit]\n"
        f"document_id: local-mock-export-{digest}\n"
        "status: pregătit local, fără transfer extern\n"
        "Nu verdict juridic. Verifică manual înainte de publicare."
    )


def execute(path: Path | str, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {
        "id",
        "dosar_id",
        "server",
        "tool",
        "draft",
        "approved",
        "approved_data_sha256",
    }:
        raise ValueError("Cerere de execuție MCP invalidă.")
    audit_id = dosare._id(request["id"])
    dossier_id = dosare._id(request["dosar_id"])
    if request["approved"] is not True:
        raise ValueError("Execuția MCP cere aprobare explicită.")
    approved_hash = dosare._text(request["approved_data_sha256"], 64, True)
    if len(approved_hash) != 64 or any(c not in "0123456789abcdef" for c in approved_hash):
        raise ValueError("Hash aprobare MCP invalid.")
    config = test_config({"server": request["server"], "tool": request["tool"]})
    if not config["available"]:
        raise ValueError("Executorul MCP local acceptă doar local-mock/ai.draft în v1.")
    plan = mcp_ai_draft.preview(
        {
            "server": config["server"],
            "tool": config["tool"],
            "draft": request["draft"],
        }
    )
    actual_hash = plan["mcp"]["approval"]["data_sha256"]
    if approved_hash != actual_hash:
        raise ValueError("Payloadul MCP aprobat nu mai corespunde cererii curente.")
    result_text = dosare._text(_mock_ai_draft(plan), MAX_RESULT, True)
    result_sha = hashlib.sha256(result_text.encode()).hexdigest()
    selected_evidence_ids = _selected_evidence_ids(plan)
    payload = {
        "contract": CONTRACT,
        "workflow": "ai_draft",
        "server": config["server"],
        "tool": config["tool"],
        "approved_data_sha256": approved_hash,
        "request_sha256": _hash_json(request["draft"]),
        "result_sha256": result_sha,
        "selected_evidence_ids": selected_evidence_ids,
        "user_action": "approved_and_executed",
        "output_status": "draft_unreviewed",
        "external_calls": False,
        "credentials_stored": False,
        "app_paid_ai": False,
        "legal_text_sent_externally": False,
        "hidden_external_calls": False,
    }
    created_at = _now()
    with dosare._open(path, write=True) as con:
        if not con.execute("SELECT 1 FROM dosare WHERE id=?", (dossier_id,)).fetchone():
            raise ValueError("Dosar inexistent.")
        _ensure_schema(con)
        old = con.execute(
            "SELECT audit_json FROM mcp_audit_events WHERE id=?", (audit_id,)
        ).fetchone()
        if old:
            return json.loads(old["audit_json"])
        con.execute(
            "INSERT INTO mcp_audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                audit_id,
                dossier_id,
                "mcp_ai_draft_executed",
                config["server"],
                config["tool"],
                approved_hash,
                payload["request_sha256"],
                result_sha,
                "draft_unreviewed",
                dosare._json(
                    {
                        **payload,
                        "id": audit_id,
                        "dosar_id": dossier_id,
                        "created_at": created_at,
                        "draft_text": result_text,
                        "insert_header": (
                            "[Ciornă MCP · nerevizuită · "
                            f"{config['server']}/{config['tool']} · {approved_hash}]"
                        ),
                        "audit_event": {
                            "contract": "mcp-audit-event-v1",
                            "event": "mcp_ai_draft_executed",
                            "approved": True,
                            "created_at": created_at,
                            "timestamp": created_at,
                            "data_sha256": approved_hash,
                            "payload_hash": approved_hash,
                            "selected_evidence_ids": selected_evidence_ids,
                            "result_sha256": result_sha,
                            "result_hash": result_sha,
                            "user_action": "approved_and_executed",
                            "requires_user_approval": True,
                            "cost_owner": "user_account_or_user_key",
                            "external_calls": False,
                            "credentials_stored": False,
                        },
                        "limitari": [
                            "Adaptor local-mock; nu s-a apelat niciun server MCP extern.",
                            "Rezultatul este ciornă nerevizuită și nu verdict juridic.",
                            "Credentialele nu sunt acceptate, salvate sau incluse în audit.",
                        ],
                    }
                ),
                created_at,
            ),
        )
    return read(path, dossier_id, audit_id)


def execute_export(path: Path | str, request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {
        "id",
        "dosar_id",
        "server",
        "tool",
        "export",
        "approved",
        "approved_data_sha256",
    }:
        raise ValueError("Cerere de export MCP invalidă.")
    audit_id = dosare._id(request["id"])
    dossier_id = dosare._id(request["dosar_id"])
    if request["approved"] is not True:
        raise ValueError("Exportul MCP cere aprobare explicită.")
    approved_hash = dosare._text(request["approved_data_sha256"], 64, True)
    if len(approved_hash) != 64 or any(c not in "0123456789abcdef" for c in approved_hash):
        raise ValueError("Hash aprobare MCP invalid.")
    config = test_config({"server": request["server"], "tool": request["tool"]})
    if not config["available"] or config["tool"] != SUPPORTED_EXPORT_TOOL:
        raise ValueError(
            "Executorul MCP local acceptă doar local-mock/document.export pentru export."
        )
    plan = mcp_export.preview(
        {
            "server": config["server"],
            "tool": config["tool"],
            "export": request["export"],
        }
    )
    actual_hash = plan["mcp"]["approval"]["data_sha256"]
    if approved_hash != actual_hash:
        raise ValueError("Payloadul MCP aprobat nu mai corespunde cererii curente.")
    result_text = dosare._text(_mock_document_export(plan), MAX_RESULT, True)
    result_sha = hashlib.sha256(result_text.encode()).hexdigest()
    selected_evidence_ids = plan["selected_evidence_ids"]
    payload = {
        "contract": CONTRACT,
        "workflow": "document_export",
        "server": config["server"],
        "tool": config["tool"],
        "approved_data_sha256": approved_hash,
        "request_sha256": _hash_json(request["export"]),
        "result_sha256": result_sha,
        "selected_evidence_ids": selected_evidence_ids,
        "user_action": "approved_and_executed",
        "output_status": "export_unreviewed",
        "external_calls": False,
        "credentials_stored": False,
        "app_paid_ai": False,
        "legal_text_sent_externally": False,
        "hidden_external_calls": False,
    }
    created_at = _now()
    with dosare._open(path, write=True) as con:
        if not con.execute("SELECT 1 FROM dosare WHERE id=?", (dossier_id,)).fetchone():
            raise ValueError("Dosar inexistent.")
        _ensure_schema(con)
        old = con.execute(
            "SELECT audit_json FROM mcp_audit_events WHERE id=?", (audit_id,)
        ).fetchone()
        if old:
            return json.loads(old["audit_json"])
        con.execute(
            "INSERT INTO mcp_audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                audit_id,
                dossier_id,
                "mcp_document_export_executed",
                config["server"],
                config["tool"],
                approved_hash,
                payload["request_sha256"],
                result_sha,
                "export_unreviewed",
                dosare._json(
                    {
                        **payload,
                        "id": audit_id,
                        "dosar_id": dossier_id,
                        "created_at": created_at,
                        "export_markdown": plan["markdown"],
                        "result_text": result_text,
                        "audit_event": {
                            "contract": "mcp-audit-event-v1",
                            "event": "mcp_document_export_executed",
                            "approved": True,
                            "created_at": created_at,
                            "timestamp": created_at,
                            "data_sha256": approved_hash,
                            "payload_hash": approved_hash,
                            "selected_evidence_ids": selected_evidence_ids,
                            "result_sha256": result_sha,
                            "result_hash": result_sha,
                            "user_action": "approved_and_executed",
                            "requires_user_approval": True,
                            "cost_owner": "user_account_or_user_key",
                            "external_calls": False,
                            "credentials_stored": False,
                        },
                        "limitari": [
                            "Adaptor local-mock; nu s-a apelat niciun server MCP extern.",
                            "Exportul este rezultat local nerevizuit.",
                            "Credentialele nu sunt acceptate, salvate sau incluse în audit.",
                        ],
                    }
                ),
                created_at,
            ),
        )
    return read(path, dossier_id, audit_id)


def read(path: Path | str, dossier_id: str, audit_id: str) -> dict:
    dossier_id = dosare._id(dossier_id)
    audit_id = dosare._id(audit_id)
    if not Path(path).exists():
        raise ValueError("Dosar inexistent.")
    with dosare._open(path) as con:
        row = con.execute(
            "SELECT audit_json FROM mcp_audit_events WHERE dosar_id=? AND id=?",
            (dossier_id, audit_id),
        ).fetchone()
        if not row:
            raise ValueError("Eveniment MCP inexistent.")
        return json.loads(row["audit_json"])
