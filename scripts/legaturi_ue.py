"""Explicit saved-proposal/EU article links; no acquisition or legal verdicts."""

import hashlib
import re
import sqlite3
from dataclasses import asdict

from scripts import achizitii_ue, cellar, dosare, interventii_propuneri, propuneri, revizuiri
from scripts.verificari_ue import _valid as valid_snapshot

CONTRACT = "ro-eu-link-v1"
MAX_TEXT_BYTES = 1_000_000
MAX_ARTICLE_CHARS = 12_000
MAX_BLOCKS = 1000
SELECTORS = {"dosar_id", "rulare_id", "constatare_id", "revizie", "celex", "instantanee", "locator"}
HYPOTHESES = {"potential_coverage", "potential_conflict", "potential_gap"}
LIMITATIONS = [
    "Ipoteza declarata de autor neautentificat, nu verdict juridic sau aviz.",
    "Prezenta textului nu confirma aplicabilitatea, transpunerea sau actualitatea sursei.",
    "Articolul este extras cu parserul local; obligatia este identificata explicit de autor.",
    "Contextul cunoscut declarat, necunoscut si euristic nu este verificat automat.",
    "Fara AI, descarcari sau actualizare a propunerii ori a deciziilor constatarilor.",
]


def sha(value):
    return hashlib.sha256(dosare._json(value).encode()).hexdigest()


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Amprenta sau identificator de instantanee invalid.")
    return value


def selection(request):
    if not isinstance(request, dict) or set(request) != SELECTORS:
        raise ValueError("Selectie de legatura UE invalida.")
    result = {k: dosare._id(request[k]) for k in ("dosar_id", "rulare_id", "constatare_id")}
    result["revizie"] = propuneri._number(request["revizie"], 1)
    result["celex"] = achizitii_ue.celex_valid(request["celex"])
    if not isinstance(request["instantanee"], str):
        raise ValueError("Instantanee invalida.")
    result["instantanee"] = digest(request["instantanee"]) if request["instantanee"] else ""
    result["locator"] = dosare._text(request["locator"], 80)
    return result


def _block(side, code):
    return {"side": side, "code": code}


def _eu(stare, celex, snapshot_id):
    if not snapshot_id:
        try:
            detail = achizitii_ue.detaliu(stare, celex)
        except (OSError, sqlite3.Error):
            return None, [_block("eu", "source_unavailable")]
        code = "missing_snapshot" if detail["stare"] == "text_disponibil" else "missing_text"
        return None, [_block("eu", code)]
    digest(snapshot_id)
    try:
        snapshot = achizitii_ue.detaliu(stare, celex, snapshot_id=snapshot_id)
    except ValueError:
        # An invalid or unavailable observation cannot serve as trusted evidence.
        return None, [_block("eu", "snapshot_unavailable_or_invalid_hash")]
    except (OSError, sqlite3.Error, KeyError, TypeError):
        return None, [_block("eu", "source_unavailable")]
    if not valid_snapshot(snapshot):
        return None, [_block("eu", "unverified_hash")]
    text = snapshot["sursa"]["text"]
    if not text.strip():
        return None, [_block("eu", "missing_text")]
    if len(text.encode()) > MAX_TEXT_BYTES:
        return None, [_block("eu", "capture_limit")]
    if snapshot["sursa"]["limba"] not in ("RON", "ENG"):
        return None, [_block("eu", "unsupported_language")]
    return snapshot, []


def _articles(snapshot):
    source = snapshot["sursa"]
    blocks = cellar.provizii_din_text(source["celex"], source["text"], source["limba"])
    if len(blocks) > MAX_BLOCKS:
        return [], [_block("eu", "capture_limit")]
    articles = []
    for block in blocks:
        if block.fel != "articol":
            continue
        base = re.sub(r"-\d+$", "", block.locator)
        ambiguous = any(b.locator.startswith(base + "-") for b in blocks)
        articles.append({**asdict(block), "selectabil": not ambiguous})
    return articles, []


def obligatii(stare, celex, snapshot_id, offset=0):
    """Read-only article selectors derived from the exact retained snapshot."""
    celex = achizitii_ue.celex_valid(celex)
    propuneri._number(offset)
    snapshot, blockers = _eu(stare, celex, snapshot_id)
    articles = []
    if snapshot:
        articles, blockers = _articles(snapshot)
    return {
        "celex": celex,
        "instantanee": snapshot_id,
        "blockers": blockers,
        "articole": [
            {k: v for k, v in a.items() if k != "text"} for a in articles[offset : offset + 50]
        ],
        "total": len(articles),
        "offset": offset,
        "mai_multe": offset + 50 < len(articles),
        "sursa": {k: v for k, v in snapshot["sursa"].items() if k != "text"} if snapshot else None,
    }


def _national(proposal):
    if not (proposal.get("text") or "").strip():
        return [_block("national", "missing_text")]
    intervention = proposal.get("interventie")
    if not intervention:
        return [_block("national", "unresolved_national_target")]
    try:
        target = intervention["tinta"]
        intent = intervention["cerere"]
        if not target["text"].strip():
            return [_block("national", "missing_text")]
        if sha(target) != intent["sha256_tinta"]:
            return [_block("national", "unverified_hash")]
        if (
            target["act"]["id"] != intent["act_id"]
            or not target["prevederi"]
            or any(p["locator"] != intent["locator"] for p in target["prevederi"])
        ):
            return [_block("national", "ambiguous_locator")]
        reconstructed = interventii_propuneri.pregateste(
            None, intent, snapshot=target, require_hash=True
        )
        if reconstructed != intervention or reconstructed["text_compus"] != proposal["text"]:
            return [_block("national", "unverified_hash")]
    except (KeyError, TypeError, ValueError, AttributeError):
        return [_block("national", "invalid_saved_target")]
    return []


def preview(stare, request):
    selected = selection(request)
    path = dosare.cale(stare)
    data = propuneri.citeste(
        path,
        selected["dosar_id"],
        selected["rulare_id"],
        selected["constatare_id"],
        selected["revizie"],
    )
    proposal = data["propunere"]
    blockers = _national(proposal)
    snapshot, eu_blockers = _eu(stare, selected["celex"], selected["instantanee"])
    blockers += eu_blockers
    article = None
    if snapshot:
        articles, parse_blockers = _articles(snapshot)
        blockers += parse_blockers
        candidates = [a for a in articles if a["locator"] == selected["locator"]]
        if len(candidates) != 1 or not candidates[0]["selectabil"]:
            blockers.append(_block("eu", "ambiguous_or_missing_locator"))
        elif len(candidates[0]["text"]) > MAX_ARTICLE_CHARS:
            blockers.append(_block("eu", "capture_limit"))
        else:
            article = candidates[0]
    contexts = revizuiri.lista(path, selected["dosar_id"], selected["rulare_id"])
    finding = next(f for f in contexts["constatari"] if f["id"] == selected["constatare_id"])
    basis = {
        "contract": CONTRACT,
        "selection": selected,
        "proposal": proposal,
        "proposal_sha256": sha(proposal),
        "eu_snapshot": snapshot,
        "eu_article": article,
        "article_sha256": sha(article) if article else None,
        "context": {k: v["curent"] for k, v in finding["context_juridic"].items()},
        "context_applicability": "unknown",
        "blockers": blockers,
    }
    if len(dosare._json(basis).encode()) > dosare.MAX_REPORT_BYTES:
        raise ValueError("Baza legaturii depaseste limita de 4 MB.")
    return {
        "contract": CONTRACT,
        "scope": "contextual",
        "state": "blocked_missing_text"
        if any(b["code"] == "missing_text" for b in blockers)
        else "blocked_evidence"
        if blockers
        else "ready_for_explicit_link",
        "blockers": blockers,
        "baza": basis,
        "baza_sha256": sha(basis),
        "substantive_candidate": None,
        "limitari": LIMITATIONS,
    }
