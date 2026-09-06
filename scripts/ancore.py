"""Where a citation sits in a passage, so the reader can follow it without leaving the sentence.

`referinte` answers *what* a text cites. This answers *where the words are*, which is the other
half of showing it: a chip drawn over `lit. a)-c)` needs the span those five characters occupy, and
the provisions they resolve to, and nothing else.

**The offsets are into the normalised text, not the text you passed in.** `normalizeaza` collapses
runs of whitespace and strips the ends, so a span read from it does not line up with the original
string. Handing back offsets measured against a string the caller does not have is the kind of bug
that shows a chip over the wrong three words and looks like a rendering problem for a week, so the
normalised text is returned *with* the anchors and the caller renders that.

**Overlapping spans become one anchor.** `extinde_serii` gives the middle and the last member of
`a)-c)` the same span — both are read off the `c)` that closes the range, because that is the only
place the text mentions them. Drawn literally that is two chips stacked on the same characters. So
spans that overlap, or that are separated only by the dash of a range, merge into a single anchor
carrying every provision they name: one chip over `lit. a)-c)`, three targets behind it.

An enumeration is left alone — `art. 7, 8 și 9` has each member written out separately, so each
gets its own chip and hovering `8` highlights only `art. 8`.

Nothing here formats a label. `locRo` in the page already turns `art7.litb` into `art. 7 · lit. b)`
and a second implementation in Python would be a second thing to keep true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from scripts.referinte import referinte
from scripts.text import normalizeaza

# What may sit between two spans and still be one citation. Only the dash of a range: `a)-c)` is
# one thing a reader points at. A comma or an `și` is an enumeration, whose members are written out
# individually and are worth pointing at individually.
_LIPICI: Final[re.Pattern[str]] = re.compile(r"^\s*-\s*$")


@dataclass(frozen=True)
class Tinta:
    """One provision an anchor points at. `act_id` is None where the sentence never named an act —
    an internal cross-reference, which is the common case inside an act's own text."""

    locator: str
    act_id: str | None


@dataclass(frozen=True)
class Ancora:
    """One chip: the characters it covers, and everything they cite."""

    start: int
    end: int
    text: str
    tinte: tuple[Tinta, ...]


def ancore(text: str, *, propriu: str | None = None) -> tuple[str, list[Ancora]]:
    """(normalised text, anchors in reading order). Anchors never overlap.

    Only citations that name a position are anchored. An act on its own — `Legea nr. 98/2016` with
    no article — has nothing to highlight, and a chip that points at a whole act would promise the
    reader a jump it cannot make.

    `propriu` is the locator of the provision the text belongs to, and its anchors are dropped. A
    provision's text opens with its own heading — `Articolul 154` at the top of `art154` — which
    reads as a citation because it is written like one. Left in, every provision on screen carries
    a chip on its first two words that highlights the row you are already reading.
    """
    curat = normalizeaza(text)
    # An act cited with no position carries an *empty* `Locator`, not `None`, so the test is on the
    # id rather than on the object — `is not None` lets every bare act through and draws a chip
    # over `Legea nr. 98/2016` that points nowhere.
    brute = [
        (r.start, r.end, Tinta(r.locator.id, r.act.id if r.act else None))
        for r in referinte(curat)
        if r.locator is not None and r.locator.id
    ]
    if not brute:
        return curat, []
    brute.sort(key=lambda x: (x[0], x[1]))

    grupuri: list[list[tuple[int, int, Tinta]]] = [[brute[0]]]
    for element in brute[1:]:
        capat = max(e[1] for e in grupuri[-1])
        gol = curat[capat : element[0]]
        if element[0] < capat or _LIPICI.match(gol) or not gol:
            grupuri[-1].append(element)
        else:
            grupuri.append([element])

    iesire: list[Ancora] = []
    for grup in grupuri:
        start = min(e[0] for e in grup)
        end = max(e[1] for e in grup)
        # Deduplicated, first mention first: `art. 7 lit. a)` read twice in one sentence is one
        # target, and a chip listing it twice would suggest two provisions.
        vazute: dict[tuple[str, str | None], Tinta] = {}
        for _, _, t in grup:
            vazute.setdefault((t.locator, t.act_id), t)
        tinte = tuple(vazute.values())
        # Dropped only when *every* target is the provision itself. `art. 154 și art. 187` inside
        # art154 keeps its chip, because the half that points elsewhere is still worth following.
        if propriu and all(t.act_id is None and t.locator == propriu for t in tinte):
            continue
        iesire.append(Ancora(start, end, curat[start:end], tinte))
    return curat, iesire


def ca_dict(text: str, *, propriu: str | None = None) -> dict:
    """The wire form: `{"text": ..., "ancore": [...]}`. Shared by the localhost server and the
    browser build, which is why it hands back plain types rather than the dataclasses above."""
    curat, gasite = ancore(text, propriu=propriu)
    return {
        "text": curat,
        "ancore": [
            {
                "start": a.start,
                "end": a.end,
                "text": a.text,
                "tinte": [{"locator": t.locator, "act_id": t.act_id} for t in a.tinte],
            }
            for a in gasite
        ],
    }
