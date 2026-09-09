"""Conservative deadline comparisons: identical obligation wording except its duration."""

from __future__ import annotations

import re

from scripts.termene import NUMERALE
from scripts.text import cheie, normalizeaza

_DURATA = re.compile(
    r"\b(?:în|in)\s+termen\s+de\s+(?P<numar>\d{1,4}|[a-zăâîșț]+)\s+"
    r"(?:de\s+)?(?P<unitate>zile|zi|luni|lună|luna|ani|an)\b"
    r"(?:\s+(?P<baza>lucrătoare|lucratoare|calendaristice))?",
    re.IGNORECASE,
)
_OBLIGATIE = re.compile(
    r"(?P<responsabil>(?:guvernul|ministerul|ministrul|autoritatea|agentia|oficiul|"
    r"consiliul|solicitantul|angajatorul|operatorul)\b[^.;:!?]{0,100}?)\s+"
    r"(?P<actiune>(?:(?:va|vor)\s+)?(?:comunica|solutioneaza|transmite|adopta|emite|"
    r"aproba|elibereaza|depune|publica|raspunde))\s+(?P<obiect>[^.;:!?]+)",
)
_ANTET = re.compile(r"^(?:art\.?\s*\d+(?:\^\d+)?\.?\s*[-–]?\s*)?(?:\(\d+\)\s*)?")
# An act's own publication/entry date is not a shared event across different acts.
_AMBIGUU = re.compile(
    r"\b(?:vigoare|publicarii|prezent\w*|acest\w*|respectiv\w*|sus|art\.?|alin\.?|"
    r"except\w*|derog\w*|daca|cazul|nu|poate|pot)\b"
)
_UNITATI = {"zi": "zile", "zile": "zile", "luna": "luni", "luni": "luni", "an": "ani", "ani": "ani"}


def termen_comparabil(text: str) -> dict | None:
    """Accept one explicit subject/action/object/duration/event provision, preserving wording.

    Matching the entire remaining wording keeps different objects, conditions and events
    apart. No unit conversion, inferred legal scope or inferred entry-into-force anchor.
    """
    original = " ".join(normalizeaza(text).split())
    durate = list(_DURATA.finditer(original))
    if len(durate) != 1:
        return None
    durata = durate[0]
    numar_text = cheie(durata["numar"])
    numar = int(numar_text) if numar_text.isdigit() else NUMERALE.get(numar_text)
    if not numar:
        return None
    prefix = _ANTET.sub("", cheie(original[: durata.start()])).strip()
    obligatie = _OBLIGATIE.fullmatch(prefix)
    suffix = cheie(original[durata.end() :]).strip().rstrip(".")
    ancora = re.fullmatch(r"de la (?:data )?(?P<eveniment>[^.;:!?]{5,250})", suffix)
    if not obligatie or not ancora or _AMBIGUU.search(prefix + " " + suffix):
        return None
    unitate = _UNITATI[cheie(durata["unitate"])]
    baza = cheie(durata["baza"] or "neprecizata")
    if unitate != "zile" and baza != "neprecizata":
        return None
    return {
        "cheie": (prefix, ancora["eveniment"], unitate),
        "responsabil": obligatie["responsabil"],
        "actiune": obligatie["actiune"] + " " + obligatie["obiect"],
        "eveniment": ancora["eveniment"],
        "cantitate": numar,
        "unitate": unitate,
        "baza": baza,
        "termen_text": durata.group(0),
        "text": original,
    }


def termene_diferite(a: dict, b: dict) -> bool:
    """Unknown versus explicit day basis alone is not evidence of a difference."""
    return a["cantitate"] != b["cantitate"] or (
        a["baza"] != b["baza"] and "neprecizata" not in (a["baza"], b["baza"])
    )
