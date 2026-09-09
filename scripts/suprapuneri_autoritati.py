"""Candidate shared competences from matching wording with different named authorities."""

import re

from scripts.text import cheie, normalizeaza

_ANTET = re.compile(r"^(?:art\.?\s*\d+(?:\^\d+)?\.?\s*[-–]?\s*)?(?:\(\d+\)\s*)?")
_ATRIBUTIE = re.compile(
    r"(?P<autoritate>(?:ministerul|agentia|autoritatea|oficiul|institutul) "
    r"[a-z -]{2,100}?) "
    r"(?P<actiune>aproba|emite|elibereaza|autorizeaza|avizeaza|controleaza|verifica|"
    r"solutioneaza|stabileste|supravegheaza) (?P<obiect>[^.;:!?]{5,500})"
)
_AMBIGUU = re.compile(
    r"\b(?:si|sau|impreuna|comun\w*|colabor\w*|aviz(?:ul|ului|e|elor)?|propun\w*|deleg\w*|"
    r"coordon\w*|sprijin\w*|consult\w*|subordin\w*|except\w*|derog\w*|daca|"
    r"poate|pot|nu|prezent\w*|acest\w*|respectiv\w*|art|alin)\b"
)
_TERITORIAL = re.compile(
    r"\b(?:local\w*|judet\w*|municip\w*|oras\w*|comun\w*|regional\w*|teritorial\w*|din)\b"
)
_GENERIC = {"autoritatea competenta", "autoritatea contractanta", "autoritatea responsabila"}
_NUME_AMBIGUU = re.compile(r"\b(?:va|vor|are|trebuie|este|competent\w*|responsabil\w*|resort)\b")


def atributie_comparabila(text: str) -> dict | None:
    """Only a single unconditional competence with its complete object and scope wording."""
    original = " ".join(normalizeaza(text).split())
    formulare = _ANTET.sub("", cheie(original)).rstrip(".")
    m = _ATRIBUTIE.fullmatch(formulare)
    if not m or _AMBIGUU.search(formulare):
        return None
    autoritate = m["autoritate"]
    if autoritate in _GENERIC or _TERITORIAL.search(autoritate) or _NUME_AMBIGUU.search(autoritate):
        return None
    return {
        "cheie": (m["actiune"], m["obiect"]),
        "autoritate": autoritate,
        "actiune": m["actiune"],
        "obiect": m["obiect"],
        "text": original,
    }
