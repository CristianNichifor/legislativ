"""Parse the plain text of an act into the block tree the Redactează editor draws.

This is the counterpart to `parsare.py`, which reads the portal's HTML (its `S_ART`/`S_ALN`/`S_LIT`
markers are ground truth). Here the input is text a person pasted — from a Word document, a PDF, the
Monitorul Oficial — where the structure is only implied by the way Romanian legal drafting numbers
itself: `Articolul N` headings, `(N)` alineate, `a)`/`b)` litere. So the structure has to be
recovered from the numbering, not read off tags.

Two ideas keep the recovery honest against running text that also *mentions* those markers
(`…prevăzut la art. 7 alin. (2) lit. a)…`):

1. **Sequence.** Real alineate run 1, 2, 3, …; real litere run a, b, c, …. A marker is only taken
   when its token is the *next one expected*. A stray `(2)` cited inside alineat (1) is not the next
   expected token there, so it is passed over — the true `(2)` is still found later.
2. **Boundary.** A marker that opens a provision sits at a boundary — start of the segment, or right
   after `.`, `;`, `:` or a newline. One buried mid-sentence is a reference, not a heading.

Everything is a single `finditer` pass per level (precompiled patterns), so parsing a long act is
linear in its length. No dependencies, no model — same contract as the rest of the package.
"""

from __future__ import annotations

import re
from itertools import count

# Article heading at the start of a line: "Articolul 7", "Art. 7.", "ART. 154 -". The number may
# carry a bis index ("12^1"). A run of separators after it (". ", " - ", ". - ") is eaten; any title
# text that follows on the line is left in the body.
_HDR = re.compile(r"(?im)^[ \t]*art(?:icolul)?\.?[ \t]+(\d+(?:\^\d+)?)\b[ \t]*(?:[.–—-]+[ \t]*)*")

# An alineat marker "(N)"; a litera marker "a)" not glued to a word (so "achiziției)" and the ")"
# that closes an inline "(2)" do not read as litere).
_ALIN = re.compile(r"\((\d+(?:\^\d+)?)\)")
_LIT = re.compile(r"(?<![\w)])([a-zăâîșț])\)")

_GRANITA = set(".;:\n")


def parseaza_text(text: str) -> dict:
    """{'noduri': [ {nivel, numar, text, copii:[…]} ]} — the tree, articles at the top level."""
    if not text or not text.strip():
        return {"noduri": [], "nota": "text gol"}
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return {"noduri": [_nod_articol(num, corp) for num, corp in _articole(text)]}


def _articole(text: str) -> list[tuple[str, str]]:
    """Split into (numar, corp) by article heading. No heading → the whole text is one article."""
    capete = list(_HDR.finditer(text))
    if not capete:
        return [("", text.strip())]
    out: list[tuple[str, str]] = []
    for i, m in enumerate(capete):
        sfarsit = capete[i + 1].start() if i + 1 < len(capete) else len(text)
        out.append((m.group(1), text[m.end() : sfarsit].strip()))
    return out


def _nod_articol(numar: str, corp: str) -> dict:
    # alineate open a provision, so they must be followed by a capital — this is what tells a real
    # "(2)" from a cited "alin. (2)," where the abbreviation's dot mimics a sentence boundary.
    chapeau, alineate = _segmente(corp, _ALIN, (str(n) for n in count(1)), cere_majuscula=True)
    copii = [_nod_alineat(t, seg) for t, seg in alineate]
    return {"nivel": "art", "numar": numar, "text": chapeau, "copii": copii}


def _nod_alineat(numar: str, corp: str) -> dict:
    # litere start lowercase ("a) virament"), so no capital is required here
    chapeau, litere = _segmente(corp, _LIT, (chr(c) for c in range(ord("a"), ord("z") + 1)))
    copii = [{"nivel": "lit", "numar": t, "text": seg, "copii": []} for t, seg in litere]
    return {"nivel": "alin", "numar": numar, "text": chapeau, "copii": copii}


def _segmente(
    text: str, pat: re.Pattern, asteptate, cere_majuscula: bool = False
) -> tuple[str, list[tuple[str, str]]]:
    """Take the markers that match the expected sequence at a boundary; return the text before the
    first taken marker (the chapeau) and one (token, segment) per taken marker."""
    luate: list[tuple[str, int, int]] = []
    urmator = next(asteptate, None)
    for m in pat.finditer(text):
        if (
            urmator is not None
            and m.group(1).lower() == urmator
            and _la_granita(text, m.start())
            and (not cere_majuscula or _urmeaza_majuscula(text, m.end()))
        ):
            luate.append((m.group(1), m.start(), m.end()))
            urmator = next(asteptate, None)
    if not luate:
        return text.strip(), []
    chapeau = text[: luate[0][1]].strip()
    segmente: list[tuple[str, str]] = []
    for k, (tok, _s, e) in enumerate(luate):
        pana = luate[k + 1][1] if k + 1 < len(luate) else len(text)
        segmente.append((tok, text[e:pana].strip()))
    return chapeau, segmente


def _la_granita(text: str, i: int) -> bool:
    """True if the marker at index i opens a provision — at the start, or after . ; : or newline."""
    j = i - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j < 0 or text[j] in _GRANITA


def _urmeaza_majuscula(text: str, e: int) -> bool:
    """True if the first non-space character after index e is an uppercase letter (a provision's
    opening word). This is how a heading "(2) Termenul" is told from a citation "(2), decide"."""
    j = e
    while j < len(text) and text[j] in " \t":
        j += 1
    return j < len(text) and text[j].isupper()
