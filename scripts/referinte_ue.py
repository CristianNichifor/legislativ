"""Deterministic references to EU legal acts in drafts.

This module only resolves explicit citations to stable CELEX ids. It does not infer compatibility
with EU law and it deliberately ignores broad law-looking patterns without an EU marker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.cellar import normalizeaza_celex

_SP = r"[ \t\r\n\f\v]{0,8}"
_SP1 = r"[ \t\r\n\f\v]{1,8}"
_MARKER = (
    r"(?:U\.?[ \t\r\n\f\v]{0,2}E\.?|E\.?[ \t\r\n\f\v]{0,2}U\.?|"
    r"C\.?[ \t\r\n\f\v]{0,2}E\.?[ \t\r\n\f\v]{0,2}E\.?|"
    r"C\.?[ \t\r\n\f\v]{0,2}E\.?|EURATOM)"
)
_CALIFICATOR = rf"(?:{_SP1}(?:delegat[aă]?|de punere{_SP1}[îi]n{_SP1}aplicare|de executare))?"
_TIP = (
    r"(?P<tip>Regulamentul|Regulamentului|Regulament|Directiva|Directivei|Directiv[aă]|"
    r"Decizia|Deciziei|Decizie|Regulation|Directive|Decision)"
)

_CELEX = re.compile(
    rf"\b(?:CELEX(?:{_SP}:{_SP}|{_SP1})|uri=CELEX:|/celex/)"
    r"(?P<celex>[0-9A-Z()._-]{5,50})",
    re.I,
)
_CITARE = re.compile(
    rf"\b{_TIP}{_CALIFICATOR}"
    rf"(?:{_SP}\((?P<marker1>[^)]{{0,40}}(?:{_MARKER})[^)]{{0,40}})\))?"
    rf"(?:{_SP1}(?P<marker2>{_MARKER}))?"
    rf"{_SP}(?:nr\.?{_SP})?"
    rf"(?P<a>\d{{1,5}}){_SP}/{_SP}(?P<b>\d{{1,5}})"
    rf"(?:{_SP}(?:/{_SP}(?P<marker3>{_MARKER})|"
    rf"\((?P<marker4>[^)]{{0,40}}(?:{_MARKER})[^)]{{0,40}})\)))?",
    re.I,
)

_CELEX_TIP = {
    "regulament": "R",
    "directiva": "L",
    "decizie": "D",
}


@dataclass(frozen=True)
class ReferintaUE:
    celex: str
    fel: str
    an: int | None
    numar: str
    text: str
    start: int
    end: int
    sursa: str

    def as_dict(self) -> dict:
        return {
            "celex": self.celex,
            "fel": self.fel,
            "an": self.an,
            "numar": self.numar,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "sursa": self.sursa,
        }


def _fel(tip: str) -> str:
    tip = tip.casefold()
    if tip.startswith(("regulament", "regulation")):
        return "regulament"
    if tip.startswith(("directiv", "directive")):
        return "directiva"
    return "decizie"


def _an(text: str) -> int | None:
    if not text.isdigit():
        return None
    valoare = int(text)
    if len(text) == 4 and 1900 <= valoare <= 2099:
        return valoare
    if len(text) == 2:
        return 2000 + valoare if valoare <= 29 else 1900 + valoare
    return None


def _an_numar(a: str, b: str) -> tuple[int, str] | None:
    an_a = _an(a)
    if an_a is not None:
        return an_a, str(int(b))
    an_b = _an(b)
    if an_b is not None:
        return an_b, str(int(a))
    return None


def _celex(fel: str, an: int, numar: str) -> str:
    nr = numar.zfill(4) if len(numar) < 4 else numar
    return f"3{an}{_CELEX_TIP[fel]}{nr}"


def referinte(text: str) -> list[ReferintaUE]:
    """Return explicit EU legal-act references found in `text`, in source order."""
    text = text or ""
    iesire: list[ReferintaUE] = []
    vazute: set[tuple[int, int, str]] = set()

    for m in _CELEX.finditer(text):
        brut = m.group("celex").rstrip(".,;:")
        try:
            celex = normalizeaza_celex(brut)
        except ValueError:
            continue
        start = m.start("celex")
        end = m.start("celex") + len(brut)
        cheie = (start, end, celex)
        if cheie in vazute:
            continue
        vazute.add(cheie)
        iesire.append(
            ReferintaUE(
                celex=celex,
                fel="celex",
                an=None,
                numar="",
                text=text[start:end],
                start=start,
                end=end,
                sursa="celex",
            )
        )

    for m in _CITARE.finditer(text):
        if not any(m.group(g) for g in ("marker1", "marker2", "marker3", "marker4")):
            continue
        fel = _fel(m.group("tip"))
        parti = _an_numar(m.group("a"), m.group("b"))
        if parti is None:
            continue
        an, numar = parti
        celex = _celex(fel, an, numar)
        try:
            celex = normalizeaza_celex(celex)
        except ValueError:
            continue
        cheie = (m.start(), m.end(), celex)
        if cheie in vazute:
            continue
        vazute.add(cheie)
        iesire.append(
            ReferintaUE(
                celex=celex,
                fel=fel,
                an=an,
                numar=numar,
                text=m.group(0),
                start=m.start(),
                end=m.end(),
                sursa="citare",
            )
        )

    iesire.sort(key=lambda r: (r.start, r.end, r.celex))
    return iesire


def referinte_dict(text: str) -> list[dict]:
    """JSON-ready explicit EU references."""
    return [r.as_dict() for r in referinte(text)]
