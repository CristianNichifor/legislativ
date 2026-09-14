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
from urllib.parse import urlparse

from scripts import ai_drafting, dosare

CONTRACT = "ai-dossier-assistant-workflow-v1"
AUDIT_CONTRACT = "ai-draft-storage-audit-v1"
MAX_PROVIDER = 120
MAX_RESULT = 8000
BOUNDARIES = {"local_ai", "online_byok", "mcp_handoff"}
BYOK_REQUEST_CONTRACT = "ai-byok-execution-request-v1"
BYOK_RESULT_CONTRACT = "ai-byok-execution-result-v1"
BYOK_RETRYABLE_FAILURES = ["timeout", "quota", "provider_unavailable"]
BYOK_PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "default_endpoint": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        "auth_headers": ["Authorization"],
    },
    "anthropic": {
        "label": "Anthropic",
        "default_endpoint": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-3-5-haiku-latest",
        "auth_headers": ["x-api-key"],
    },
}
SECRET_FIELDS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "key",
    "password",
    "secret",
    "token",
    "x-api-key",
    "x_api_key",
}


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


def _contains_secret_field(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).strip().lower().replace("-", "_") in SECRET_FIELDS:
                return True
            if _contains_secret_field(item):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_field(item) for item in value)
    return False


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


def guardrail_summary(support: dict) -> dict:
    failed = []
    if support.get("blocks_insertion"):
        failed.append("cites_selected_evidence")
    if support.get("unsupported_claims", 0):
        failed.append("claim_requires_review")
    return {
        "contract": "ai-workflow-guardrail-summary-v1",
        "status": "blocked"
        if support.get("blocks_insertion")
        else "needs_review"
        if failed
        else "ok",
        "failed": failed,
        "insert_allowed": not support.get("blocks_insertion", False),
        "not_legal_verdict": True,
        "selected_evidence_only": True,
        "server_calls_model": False,
        "stores_api_key": False,
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
    if _contains_secret_field(request):
        raise ValueError("Credentialele BYOK nu se trimit serverului.")
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
    guardrails = guardrail_summary(support)
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
        "guardrail_summary": guardrails,
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


def _byok_provider(value: object) -> str:
    provider = str(value or "openai").strip().lower().replace("-", "_")
    if provider not in BYOK_PROVIDERS:
        raise ValueError("Furnizor BYOK neacceptat.")
    return provider


def _https_endpoint(value: object, provider: str) -> str:
    endpoint = dosare._text(value or BYOK_PROVIDERS[provider]["default_endpoint"], 500, True)
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Endpoint BYOK invalid.")
    host = parsed.hostname or ""
    if provider == "openai" and not (
        host in {"api.openai.com", "api.openai.test"}
        or host.endswith(".openai.com")
        or host.endswith(".openai.test")
    ):
        raise ValueError("Endpoint OpenAI BYOK invalid.")
    if provider == "anthropic" and not (
        host in {"api.anthropic.com", "api.anthropic.test"}
        or host.endswith(".anthropic.com")
        or host.endswith(".anthropic.test")
    ):
        raise ValueError("Endpoint Anthropic BYOK invalid.")
    return endpoint


def _int_range(value: object, default: int, minimum: int, maximum: int, label: str) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} BYOK invalid.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} BYOK invalid.")
    return number


def _byok_body(provider: str, model: str, plan: dict) -> dict:
    if provider == "anthropic":
        return {
            "model": model,
            "max_tokens": ai_drafting.ESTIMATED_OUTPUT_TOKENS,
            "temperature": 0.2,
            "system": plan["system"],
            "messages": [{"role": "user", "content": plan["prompt"]}],
        }
    return {
        "model": model,
        "max_tokens": ai_drafting.ESTIMATED_OUTPUT_TOKENS,
        "temperature": 0.2,
        "stream": False,
        "messages": [
            {"role": "system", "content": plan["system"]},
            {"role": "user", "content": plan["prompt"]},
        ],
    }


def byok_request(request: dict) -> dict:
    """Build the browser-executed BYOK call contract without accepting credentials."""

    required = {"draft", "provider", "model", "endpoint", "timeout_ms", "max_retries"}
    if _contains_secret_field(request):
        raise ValueError("Credentialele BYOK nu se trimit serverului.")
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError("Cerere BYOK invalidă.")
    provider = _byok_provider(request["provider"])
    model = dosare._text(
        request.get("model") or BYOK_PROVIDERS[provider]["default_model"], 120, True
    )
    endpoint = _https_endpoint(request.get("endpoint"), provider)
    timeout_ms = _int_range(request.get("timeout_ms"), 45000, 1000, 120000, "Timeout")
    max_retries = _int_range(request.get("max_retries"), 1, 0, 2, "Retry")
    plan = ai_drafting.preview(request["draft"])
    body = _byok_body(provider, model, plan)
    body_sha = _hash_json(body)
    created_at = _now()
    return {
        "contract": BYOK_REQUEST_CONTRACT,
        "status": "ready_for_browser_execution",
        "provider": provider,
        "provider_label": BYOK_PROVIDERS[provider]["label"],
        "model": model,
        "endpoint": endpoint,
        "method": "POST",
        "timeout_ms": timeout_ms,
        "retry_policy": {
            "contract": "ai-byok-retry-policy-v1",
            "max_retries": max_retries,
            "retryable_failures": BYOK_RETRYABLE_FAILURES,
            "creates_draft_on_failure": False,
            "result_imported_on_failure": False,
        },
        "headers": {
            "contract": "ai-byok-redacted-headers-v1",
            "content_type": "application/json",
            "auth_headers_required": BYOK_PROVIDERS[provider]["auth_headers"],
            "authorization_value": "browser_session_key_only",
            "redacted": True,
            "api_key_included": False,
        },
        "body": body,
        "body_sha256": body_sha,
        "input_sha256": plan["input_sha256"],
        "evidence_sha256": plan["evidence_sha256"],
        "request_sha256": _hash_json(
            {
                "provider": provider,
                "model": model,
                "endpoint": endpoint,
                "timeout_ms": timeout_ms,
                "max_retries": max_retries,
                "body_sha256": body_sha,
            }
        ),
        "external_approval_payload": plan["external_approval_payload"],
        "failure_contract": "ai-byok-provider-failure-v1",
        "failure_states": [
            ai_drafting.provider_failure_state(code) for code in ai_drafting.BYOK_FAILURE_STATES
        ],
        "audit": {
            "contract": "ai-byok-execution-audit-v1",
            "event": "ai_byok_request_prepared",
            "created_at": created_at,
            "server_calls_model": False,
            "stores_api_key": False,
            "api_key_uploaded": False,
            "app_paid_provider": False,
            "output_status": "draft_unreviewed",
            "result_review_state": "unreviewed",
        },
        "privacy": {
            "server_calls_model": False,
            "stores_api_key": False,
            "api_key_uploaded": False,
            "key_storage": "browser_session_only_for_byok",
            "private_data_excluded": plan["export_manifest"]["private_data_excluded"],
        },
        "limitari": [
            "Serverul pregătește contractul; browserul utilizatorului execută apelul BYOK.",
            "Cheia API nu este acceptată în payload și nu este inclusă în răspuns.",
            (
                "Eșecurile furnizorului nu creează ciorne, constatări acceptate "
                "sau rezultate importate."
            ),
            "Rezultatul valid trebuie salvat ulterior ca draft nerevizuit prin auditul dosarului.",
        ],
    }


def byok_failure_result(request: dict) -> dict:
    required = {"request", "failure_code", "provider_status"}
    if _contains_secret_field(request):
        raise ValueError("Credentialele BYOK nu se trimit serverului.")
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError("Rezultat BYOK invalid.")
    prepared = request["request"]
    if not isinstance(prepared, dict) or prepared.get("contract") != BYOK_REQUEST_CONTRACT:
        raise ValueError("Contract BYOK invalid.")
    failure = ai_drafting.provider_failure_state(request["failure_code"])
    provider_status = dosare._text(request.get("provider_status", ""), 120)
    return {
        "contract": BYOK_RESULT_CONTRACT,
        "status": "failed",
        "request_sha256": prepared["request_sha256"],
        "provider": prepared["provider"],
        "model": prepared["model"],
        "provider_status": provider_status,
        "failure": {
            **failure,
            "creates_draft": False,
            "result_imported": False,
            "accepted_findings_created": False,
            "review_state": "none",
        },
        "audit": {
            "contract": "ai-byok-execution-audit-v1",
            "event": "ai_byok_execution_failed",
            "created_at": _now(),
            "failure_code": failure["failure_code"],
            "server_calls_model": False,
            "stores_api_key": False,
            "api_key_uploaded": False,
            "output_status": "no_draft_created",
            "accepted_findings_created": False,
        },
    }


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
