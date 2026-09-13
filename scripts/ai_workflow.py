"""One bounded AI assistant workflow over selected dossier evidence.

The server still does not call a paid model. It validates the same evidence
prompt used by BYOK/local UI, can produce a deterministic local draft for CI,
and stores the browser/provider result with an append-only audit event.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from scripts import ai_drafting, dosare

CONTRACT = "ai-dossier-assistant-workflow-v1"
AUDIT_CONTRACT = "ai-draft-storage-audit-v1"
MAX_PROVIDER = 120
MAX_RESULT = 8000
BOUNDARIES = {"local_ai", "online_byok", "mcp_handoff"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _provider(value: object, boundary: str) -> str:
    fallback = {
        "local_ai": "deterministic-local-mock",
        "online_byok": "browser-byok-provider",
        "mcp_handoff": "mcp-executor",
    }[boundary]
    return dosare._text(value or fallback, MAX_PROVIDER) or fallback


def _ensure_schema(con) -> None:
    con.execute(
        "CREATE TABLE IF NOT EXISTS ai_draft_audit_events ("
        "id TEXT PRIMARY KEY, dosar_id TEXT NOT NULL REFERENCES dosare(id), "
        "event_type TEXT NOT NULL, boundary TEXT NOT NULL, provider TEXT NOT NULL, "
        "input_sha256 TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, "
        "result_sha256 TEXT NOT NULL, status TEXT NOT NULL, "
        "audit_json TEXT NOT NULL, creat_la TEXT NOT NULL)"
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS ai_draft_audit_events_dosar "
        "ON ai_draft_audit_events(dosar_id,creat_la DESC,id)"
    )
    for operation in ("UPDATE", "DELETE"):
        con.execute(
            f"CREATE TRIGGER IF NOT EXISTS ai_draft_audit_events_no_{operation.lower()} "
            f"BEFORE {operation} ON ai_draft_audit_events BEGIN "
            "SELECT RAISE(ABORT,'AI draft audit events are append-only'); END"
        )


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]


def claim_support(plan: dict, text: str) -> dict:
    """Label claims that cite evidence outside the approved manifest.

    This intentionally uses a narrow deterministic rule. It blocks invalid
    numeric citations and labels legal-looking sentences that carry no evidence
    citation, without pretending to prove semantic faithfulness.
    """

    allowed = {int(item["index"]) for item in plan.get("evidence_manifest", [])}
    claims: list[dict] = []
    unsupported = 0
    for sentence in _sentences(text):
        cited = {int(match) for match in re.findall(r"\[(\d{1,2})\]", sentence)}
        invalid = sorted(cited - allowed)
        legalish = bool(
            re.search(
                r"\b(legea|ordonanța|ordonanta|hotărârea|hotararea|art\.?|alin\.?|"
                r"directiva|regulamentul|celex|conform|obligă|interzice)\b",
                sentence,
                re.I,
            )
        )
        if invalid:
            status = "unsupported_blocked"
            reason = "citation_outside_selected_evidence"
        elif legalish and not cited:
            status = "unsupported_labeled"
            reason = "legal_claim_without_selected_evidence_citation"
        else:
            status = "supported_by_selected_evidence" if cited else "draft_context"
            reason = ""
        unsupported += int(status.startswith("unsupported"))
        claims.append(
            {"text": sentence, "citations": sorted(cited), "status": status, "reason": reason}
        )
    return {
        "contract": "ai-claim-support-check-v1",
        "selected_evidence_indexes": sorted(allowed),
        "claims": claims,
        "unsupported_claims": unsupported,
        "blocks_insertion": any(item["status"] == "unsupported_blocked" for item in claims),
        "label_required": unsupported > 0,
        "method": "deterministic_citation_boundary",
    }


def _mock_gap_draft(plan: dict) -> str:
    evidence = plan.get("evidence", [])
    first = evidence[0] if evidence else {}
    source = " ".join(
        str(first.get(key, "")).strip() for key in ("act_id", "locator") if first.get(key)
    )
    source = source or "dovada selectată"
    return (
        "[Ciornă AI locală · nerevizuită]\n"
        "Nu verdict juridic. Textul de mai jos folosește numai dovezile selectate.\n\n"
        "Explicație gap:\n"
        f"- {source} indică o problemă de completat sau verificat manual [1].\n"
        "- Dovezile nu sunt suficiente pentru concluzie juridică finală [1].\n\n"
        "Propunere de lucru:\n"
        "- formulează intervenția ca ipoteză și păstrează trimiterea la sursa selectată [1].\n"
        "- cere verificarea versiunii oficiale, a excepțiilor și a actelor subsecvente [1].\n\n"
        "Checklist reviewer:\n"
        "- confirmă URL-ul oficial sau hash-ul sursei [1];\n"
        "- verifică dacă există norme, derogări sau jurisprudență relevantă;\n"
        "- marchează nota ca revizuită numai după control uman."
    )


def preview(request: dict) -> dict:
    if not isinstance(request, dict) or set(request) != {"boundary", "draft", "provider"}:
        raise ValueError("Cerere workflow AI invalidă.")
    boundary = dosare._text(request["boundary"], 40, True)
    if boundary not in BOUNDARIES:
        raise ValueError("Limită workflow AI invalidă.")
    plan = ai_drafting.preview(request["draft"])
    return {
        "contract": CONTRACT,
        "status": "requires_user_action",
        "boundary": boundary,
        "provider": _provider(request.get("provider"), boundary),
        "plan": plan,
        "cost_estimate": plan["cost_estimate"],
        "privacy": {
            "server_calls_model": False,
            "stores_api_key": False,
            "prompt_scope": "selected_evidence_only",
            "private_data_excluded": plan["export_manifest"]["private_data_excluded"],
        },
        "approval": {
            "required": True,
            "external_send_required": boundary in {"online_byok", "mcp_handoff"},
            "approved_external_send": False,
            "output_status": "draft_unreviewed",
            "unsupported_claims_block_or_label": True,
        },
    }


def execute(path: Path | str, request: dict) -> dict:
    required = {"id", "dosar_id", "boundary", "draft", "provider", "approved", "result_text"}
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError("Cerere de finalizare AI invalidă.")
    audit_id = dosare._id(request["id"])
    dossier_id = dosare._id(request["dosar_id"])
    boundary = dosare._text(request["boundary"], 40, True)
    if boundary not in {"local_ai", "online_byok"}:
        raise ValueError("Finalizează aici doar AI local sau BYOK; MCP folosește executorul MCP.")
    if request["approved"] is not True:
        raise ValueError("Workflow-ul AI cere aprobare explicită.")
    provider = _provider(request.get("provider"), boundary)
    plan = ai_drafting.preview(request["draft"])
    result_text = dosare._text(request["result_text"], MAX_RESULT)
    if not result_text and boundary == "local_ai":
        result_text = _mock_gap_draft(plan)
    if not result_text:
        raise ValueError("Rezultat AI lipsă.")
    support = claim_support(plan, result_text)
    output_status = (
        "blocked_unsupported_claims"
        if support["blocks_insertion"]
        else "draft_labeled_unsupported_claims"
        if support["label_required"]
        else "draft_unreviewed"
    )
    result_sha = _hash_text(result_text)
    created_at = _now()
    payload = {
        "contract": AUDIT_CONTRACT,
        "workflow_contract": CONTRACT,
        "id": audit_id,
        "dosar_id": dossier_id,
        "boundary": boundary,
        "provider": provider,
        "approved": True,
        "approved_external_send": boundary == "online_byok",
        "server_calls_model": False,
        "stores_api_key": False,
        "app_paid_provider": False,
        "input_sha256": plan["input_sha256"],
        "evidence_sha256": plan["evidence_sha256"],
        "result_sha256": result_sha,
        "request_sha256": _hash_json(request["draft"]),
        "output_status": output_status,
        "insert_allowed": output_status != "blocked_unsupported_claims",
        "draft_text": result_text,
        "claim_support": support,
        "cost_estimate": plan["cost_estimate"],
        "evidence_manifest": plan["evidence_manifest"],
        "created_at": created_at,
        "insert_header": (
            f"[Ciornă AI · {boundary} · {provider} · {plan['input_sha256']} · {output_status}]"
        ),
    }
    with dosare._open(path, write=True) as con:
        if not con.execute("SELECT 1 FROM dosare WHERE id=?", (dossier_id,)).fetchone():
            raise ValueError("Dosar inexistent.")
        _ensure_schema(con)
        old = con.execute(
            "SELECT audit_json FROM ai_draft_audit_events WHERE id=?", (audit_id,)
        ).fetchone()
        if old:
            return json.loads(old["audit_json"])
        con.execute(
            "INSERT INTO ai_draft_audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                audit_id,
                dossier_id,
                "ai_draft_completed",
                boundary,
                provider,
                plan["input_sha256"],
                plan["evidence_sha256"],
                result_sha,
                output_status,
                dosare._json(payload),
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
            "SELECT audit_json FROM ai_draft_audit_events WHERE dosar_id=? AND id=?",
            (dossier_id, audit_id),
        ).fetchone()
        if not row:
            raise ValueError("Eveniment AI inexistent.")
        return json.loads(row["audit_json"])
