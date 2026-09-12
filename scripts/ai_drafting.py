"""Prompt contract for AI drafting from already selected evidence.

This module never calls a model. It validates the selected snippets and returns
the bounded prompt that the browser may send through local AI or BYOK.
"""

from __future__ import annotations

import hashlib

from scripts import constatari_manuale, dosare

MAX_EVIDENCE = 8
MAX_QUOTE = 1800
MAX_CONTEXT = 2000
MAX_PROMPT = 12000
ESTIMATED_OUTPUT_TOKENS = 900

TASKS = {
    "issue_note": "notă de constatare",
    "amendment_rationale": "motivare amendament",
    "review_checklist": "listă de verificare",
}

SYSTEM = (
    "Redactezi text de lucru pentru o analiză legislativă românească. "
    "Folosește numai dovezile primite. Nu inventa surse, articole, efecte juridice "
    "sau concluzii de conformitate. Marchează explicit incertitudinile și scrie că "
    "rezultatul este ciornă nerevizuită. Citează dovezile numai după indexul lor "
    "numeric din manifest. Dacă dovezile nu ajung, spune ce lipsește."
)


def _text(value, limit: int, *, required: bool = False) -> str:
    try:
        return dosare._text(value, limit, required)
    except ValueError as exc:
        raise ValueError("Câmp invalid pentru ciorna AI.") from exc


def _task(value) -> str:
    key = str(value or "issue_note").strip().lower().replace("-", "_")
    if key not in TASKS:
        raise ValueError("Tip de ciornă AI invalid.")
    return key


def _evidence(item: object, index: int) -> dict:
    if not isinstance(item, dict):
        raise ValueError("Dovadă AI invalidă.")
    quote = _text(item.get("quote"), MAX_QUOTE, required=True)
    source_url = _text(item.get("source_url", ""), 1000)
    source_hash = _text(item.get("source_hash", ""), 64)
    if not source_url and not source_hash:
        raise ValueError("Fiecare dovadă AI are nevoie de URL sau SHA-256.")
    return {
        "index": index,
        "label": _text(item.get("label", f"Dovada {index}"), 200) or f"Dovada {index}",
        "act_id": _text(item.get("act_id", ""), 200),
        "locator": _text(item.get("locator", ""), 120),
        "language": _text(item.get("language", "RON"), 20) or "RON",
        "source_url": source_url,
        "source_hash": source_hash,
        "quote": quote,
    }


def _evidence_manifest(evidence: list[dict]) -> list[dict]:
    return [
        {
            "index": item["index"],
            "label": item["label"],
            "act_id": item["act_id"],
            "locator": item["locator"],
            "language": item["language"],
            "source_url": item["source_url"],
            "source_hash": item["source_hash"],
            "quote_sha256": hashlib.sha256(item["quote"].encode()).hexdigest(),
        }
        for item in evidence
    ]


def _cost_estimate(prompt: str) -> dict:
    input_tokens = max(1, len(prompt) // 4)
    return {
        "contract": "ai-cost-estimate-v1",
        "input_chars": len(prompt),
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": ESTIMATED_OUTPUT_TOKENS,
        "estimated_total_tokens": input_tokens + ESTIMATED_OUTPUT_TOKENS,
        "server_cost": "none",
        "cost_owner": "user_if_byok_or_mcp",
        "price_unknown_until_user_selects_provider": True,
    }


def preview(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Cerere AI invalidă.")
    task = _task(data.get("task"))
    note_type = constatari_manuale.normalize_tip(data.get("type", "lacuna"))
    title = _text(data.get("title", ""), 200)
    user_context = _text(data.get("context", ""), MAX_CONTEXT)
    raw_evidence = data.get("evidence")
    if not isinstance(raw_evidence, list) or not 1 <= len(raw_evidence) <= MAX_EVIDENCE:
        raise ValueError("Selectează între 1 și 8 dovezi pentru ciorna AI.")
    evidence = [_evidence(item, index) for index, item in enumerate(raw_evidence, start=1)]
    type_label = next(
        (item["eticheta"] for item in constatari_manuale.tipuri() if item["cheie"] == note_type),
        note_type,
    )
    payload = {
        "contract": "ai-evidence-prompt-payload-v1",
        "task": task,
        "task_label": TASKS[task],
        "type": note_type,
        "type_label": type_label,
        "title": title,
        "context": user_context,
        "evidence_manifest": _evidence_manifest(evidence),
        "evidence": evidence,
        "required_output": [
            "titlu de lucru",
            "ipoteză și incertitudine",
            "dovezi citate după număr",
            "raționament limitat la dovezi",
            "ce trebuie verificat manual",
        ],
        "forbidden_output": [
            "verdict juridic final",
            "surse, articole sau citate neprimite",
            "marcare ca revizuit/acceptat",
            "afirmații de actualitate fără sursă",
        ],
        "approval_rules": [
            "ai_local: utilizatorul pornește explicit modelul local",
            "online_byok: utilizatorul confirmă trimiterea textului către furnizor",
            "mcp_handoff: utilizatorul aprobă payload-ul MCP înainte de trimitere",
        ],
    }
    prompt = "Construiește o ciornă, nu o concluzie. Răspunde în română.\n\n" + dosare._json(
        payload
    )
    if len(prompt.encode("utf-8")) > MAX_PROMPT:
        raise ValueError("Dovezile selectate depășesc limita pentru ciorna AI.")
    fingerprint = hashlib.sha256(prompt.encode()).hexdigest()
    cost = _cost_estimate(prompt)
    return {
        "contract": "ai-evidence-draft-v1",
        "mode": "client_local_or_byok",
        "system": SYSTEM,
        "prompt": prompt,
        "input_sha256": fingerprint,
        "evidence_manifest": payload["evidence_manifest"],
        "evidence_sha256": hashlib.sha256(
            dosare._json(payload["evidence_manifest"]).encode()
        ).hexdigest(),
        "estimated_chars": cost["input_chars"],
        "estimated_tokens": cost["estimated_input_tokens"],
        "cost_estimate": cost,
        "approval": {
            "required_for_external_ai": True,
            "server_calls_model": False,
            "allowed_modes": ["local_ai", "online_byok", "mcp_handoff"],
            "key_retention": "browser_session_only_for_byok",
            "output_status": "draft_unreviewed",
        },
        "audit": {
            "contract": "ai-draft-audit-v1",
            "event": "ai_draft_prompt_previewed",
            "input_sha256": fingerprint,
            "evidence_sha256": hashlib.sha256(
                dosare._json(payload["evidence_manifest"]).encode()
            ).hexdigest(),
            "model_invoked_by_server": False,
            "approved_external_send": False,
        },
        "task": task,
        "type": note_type,
        "evidence_count": len(evidence),
        "status": "draft_unreviewed",
        "limitari": [
            "Serverul nu a apelat niciun model AI.",
            (
                "Browserul poate trimite promptul doar prin AI local sau BYOK "
                "configurat de utilizator."
            ),
            "Ciorna nu poate marca o constatare drept revizuită sau acceptată.",
            "Modelul trebuie să folosească numai dovezile numerotate din prompt.",
        ],
    }
