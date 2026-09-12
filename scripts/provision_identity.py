"""Stable provision identities for the law-as-code layer.

This module does not recover text and does not guess missing structure. It turns
an act id plus an explicit locator into one durable unit key, with the source
snapshot that backs the current local row.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Final

from scripts.text import normalizeaza

_CANON_PART: Final[re.Pattern[str]] = re.compile(
    r"^(?:(anx(?P<anx>[0-9]+(?:\^[0-9]+)?))|"
    r"(art(?P<art>[0-9]+(?:\^[0-9]+)?|[IVXLCDM]+))|"
    r"(alin(?P<alin>[0-9]+(?:\^[0-9]+)?))|"
    r"(lit(?P<lit>[a-zș](?:\^[0-9]+)?))|"
    r"(pct(?P<pct>[0-9]+(?:\^[0-9]+)?)))$",
    re.IGNORECASE,
)
_ANEXA: Final[re.Pattern[str]] = re.compile(
    r"\banex[ăa]\s*(?:nr\.?\s*)?(?P<value>[0-9]+(?:\^[0-9]+)?)?", re.IGNORECASE
)
_ARTICOL: Final[re.Pattern[str]] = re.compile(
    r"\b(?:articol(?:ul|ului)?|art\.?)\s*(?P<value>[0-9]+(?:\^[0-9]+)?|[IVXLCDM]+)\b",
    re.IGNORECASE,
)
_ALINEAT: Final[re.Pattern[str]] = re.compile(
    r"\b(?:alineat(?:ul|ului)?|alin\.?)\s*\(?(?P<value>[0-9]+(?:\^[0-9]+)?)\)?",
    re.IGNORECASE,
)
_LITERA: Final[re.Pattern[str]] = re.compile(
    r"\b(?:liter(?:a|ei)|lit\.?)\s*(?P<value>[a-zș](?:\^[0-9]+)?)\s*\)",
    re.IGNORECASE,
)
_PUNCT: Final[re.Pattern[str]] = re.compile(
    r"\b(?:punct(?:ul|ului)?|pct\.?)\s*(?P<value>[0-9]+(?:\^[0-9]+)?)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class LocatorIdentity:
    canonical: str
    kind: str
    parts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvisionIdentity:
    contract: str
    status: str
    provision_id: str
    act_id: str
    locator: str
    kind: str
    parts: dict[str, str]
    source_url: str
    captured_at: str
    source_hash: str
    source_version: str
    rows: int
    exact: bool
    unavailable_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _clean(value: str | None) -> str:
    return normalizeaza(value or "").strip()


def _norm_num(value: str) -> str:
    value = value.strip()
    if value.isascii() and value.isalpha() and len(value) > 1:
        return value.upper()
    return value.lower()


def _canonical_parts(parts: dict[str, str]) -> LocatorIdentity:
    if not parts:
        raise ValueError("Locatorul nu conține o unitate citabilă.")
    if any(parts.get(k) for k in ("alineat", "litera", "punct")) and not parts.get("articol"):
        raise ValueError("Locator ambiguu: alineatul/litera/punctul trebuie legat de un articol.")
    if parts.get("punct") and not parts.get("litera"):
        raise ValueError("Locator ambiguu: punctul trebuie legat de o literă.")
    ordered = [
        f"anx{parts['anexa']}" if parts.get("anexa") else "",
        f"art{parts['articol']}" if parts.get("articol") else "",
        f"alin{parts['alineat']}" if parts.get("alineat") else "",
        f"lit{parts['litera']}" if parts.get("litera") else "",
        f"pct{parts['punct']}" if parts.get("punct") else "",
    ]
    canonical = ".".join(p for p in ordered if p)
    kind = next(
        name for name in ("punct", "litera", "alineat", "articol", "anexa") if parts.get(name)
    )
    return LocatorIdentity(canonical=canonical, kind=kind, parts=parts)


def _from_canonical(value: str) -> LocatorIdentity | None:
    if value == "text":
        return LocatorIdentity(canonical="text", kind="document", parts={"document": "text"})
    parts: dict[str, str] = {}
    for raw in value.split("."):
        m = _CANON_PART.match(raw)
        if not m:
            return None
        if m.group("anx"):
            parts["anexa"] = _norm_num(m.group("anx"))
        elif m.group("art"):
            parts["articol"] = _norm_num(m.group("art"))
        elif m.group("alin"):
            parts["alineat"] = _norm_num(m.group("alin"))
        elif m.group("lit"):
            parts["litera"] = _norm_num(m.group("lit"))
        elif m.group("pct"):
            parts["punct"] = _norm_num(m.group("pct"))
    return _canonical_parts(parts)


def normalize_locator(value: str | None) -> LocatorIdentity:
    """Return one canonical locator, or raise when the locator is ambiguous."""
    text = _clean(value)
    if not text:
        raise ValueError("Locator lipsă.")
    compact = re.sub(r"\s+", "", text).replace(")", "")
    direct = _from_canonical(compact)
    if direct:
        return direct

    parts: dict[str, str] = {}
    if m := _ANEXA.search(text):
        parts["anexa"] = _norm_num(m.group("value") or "1")
    if m := _ARTICOL.search(text):
        parts["articol"] = _norm_num(m.group("value"))
    if m := _ALINEAT.search(text):
        parts["alineat"] = _norm_num(m.group("value"))
    if m := _LITERA.search(text):
        parts["litera"] = _norm_num(m.group("value"))
    if m := _PUNCT.search(text):
        parts["punct"] = _norm_num(m.group("value"))
    return _canonical_parts(parts)


def provision_key(act_id: str, locator: str) -> str:
    act = _clean(act_id)
    loc = normalize_locator(locator).canonical
    if not act:
        raise ValueError("Act lipsă.")
    return f"ro:{act}#{loc}"


def resolve(con: sqlite3.Connection, act_id: str, locator: str) -> ProvisionIdentity:
    """Resolve a local corpus row into the law-as-code identity contract.

    Missing rows remain unavailable. The identity still carries the canonical unit
    key so a review queue can point to the same place once a better source arrives.
    """
    act = _clean(act_id)
    if not act:
        raise ValueError("Act lipsă.")
    loc = normalize_locator(locator)
    rows = con.execute(
        "SELECT p.text, a.sursa_url, a.citit_la FROM provizii p "
        "JOIN acte a ON a.id = p.act_id WHERE p.act_id = ? AND p.locator = ? ORDER BY p.ord",
        (act, loc.canonical),
    ).fetchall()
    if not rows:
        act_row = con.execute(
            "SELECT sursa_url, citit_la FROM acte WHERE id = ?", (act,)
        ).fetchone()
        return ProvisionIdentity(
            contract="provision-identity-v1",
            status="unavailable",
            provision_id=f"ro:{act}#{loc.canonical}",
            act_id=act,
            locator=loc.canonical,
            kind=loc.kind,
            parts=loc.parts,
            source_url=(act_row[0] if act_row else "") or "",
            captured_at=(act_row[1] if act_row else "") or "",
            source_hash="",
            source_version=(act_row[1] if act_row else "") or "",
            rows=0,
            exact=False,
            unavailable_reason="provision-not-found" if act_row else "act-not-found",
        )
    text = "\n".join(row[0] for row in rows)
    source_url = rows[0][1] or ""
    captured_at = rows[0][2] or ""
    return ProvisionIdentity(
        contract="provision-identity-v1",
        status="available",
        provision_id=f"ro:{act}#{loc.canonical}",
        act_id=act,
        locator=loc.canonical,
        kind=loc.kind,
        parts=loc.parts,
        source_url=source_url,
        captured_at=captured_at,
        source_hash=_sha(text),
        source_version=captured_at,
        rows=len(rows),
        exact=True,
    )
