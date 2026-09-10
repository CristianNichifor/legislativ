"""The honest number: locator extraction measured against the publisher's own marks.

`etalon.py` scores the extractors on thirty-six sentences written by the same hand that wrote the
patterns. That measures whether they do what they were designed to do; it cannot measure how much
of real law they catch, because there is no independent truth in it. This module supplies an
independent truth over real acts: the portal wraps positions inside the text in an `S_LGI` span,
so those spans are the Ministry's own answer key for *where a provision is*.

**Locator recall against `S_LGI`, on committed fixtures.** For every span the publisher marked,
did `referinte.py` find a reference overlapping it. The acts are the ones already saved in
`sources/` that carry marks; two of them hold over eight hundred marks between them, which is a
larger and more real sample than the hand-written set. Fixtures rather than a live fetch, so the
number is reproducible and CI can hold it.

**`S_LGI` marks locators, not citations of other acts.** This said the opposite until 2026-09-10
— "the portal wraps every legislative reference it recognises" — and the number was read as
reference recall on that basis. Counted over the same fixtures the harness scores:

    lege-310-2021    242 marks     0 carry an act number    (100% locators)
    lege-98-2016     580 marks    14 carry an act number    (97,6% locators)

All fourteen name the host act. Not one of the 822 marks points at a *different* act — they are
`lit. e)`, `anexa nr. 1`, `art. 107 alin. (1)-(3)`. So this measures locator extraction, which is
real and worth guarding, and says nothing about whether `Legea nr. 171/1998` is found in a
sentence that cites it. The parser and the regex below were compared span for span to be sure
this is not a truncation artefact: 242/242 and 580/580, identical.

**What this is not.** It is not reference recall, per the above. It is not precision either:
an answer key says where something *is*, not where it *is not*, so nothing here can catch an
invention — see `etalon_precizie.py`, which asks a person instead, because for act citations
there is no key to ask. And a short act that cites nothing carries no marks and contributes
nothing. The synthetic set still guards precision on thirty-six sentences and guards the
amendment and deadline extractors; this guards locator recall against the real world; the
adjudicated sample guards reference precision. No one of the three is the measurement.

Run: `python -m scripts.etalon_real`.
"""

from __future__ import annotations

import gzip
import html
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.referinte import referinte
from scripts.text import cheie, normalizeaza

SURSE = Path(__file__).resolve().parent.parent / "sources"
_LGI = re.compile(r'class="S_LGI"[^>]*>(.*?)</', re.S)


@dataclass(frozen=True)
class Masura:
    act: str
    marcaje: int
    gasite: int

    @property
    def recall(self) -> float:
        return self.gasite / self.marcaje if self.marcaje else 1.0


def _text_curat(fragment: str) -> str:
    return normalizeaza(html.unescape(re.sub(r"<[^>]+>", " ", fragment)))


def masoara_fisier(cale: Path) -> Masura:
    """Recall over one act: publisher marks found by the extractor."""
    s = gzip.decompress(cale.read_bytes()).decode("utf-8", errors="replace")
    marcaje = [m for m in (_text_curat(x) for x in _LGI.findall(s)) if len(m) > 3]
    body = _text_curat(s)
    chei_ref = [cheie(r.text) for r in referinte(body) if r.text]
    gasite = 0
    for mk in marcaje:
        k = cheie(mk)
        if k and any(k in rk or rk in k for rk in chei_ref):
            gasite += 1
    return Masura(cale.stem, len(marcaje), gasite)


def masoara(surse: Path = SURSE) -> list[Masura]:
    """Every fixture that carries publisher marks. Acts without marks contribute nothing."""
    masuri = [masoara_fisier(f) for f in sorted(surse.glob("*.html.gz"))]
    return [m for m in masuri if m.marcaje]


def recall_global(masuri: list[Masura]) -> float:
    total = sum(m.marcaje for m in masuri)
    gasit = sum(m.gasite for m in masuri)
    return gasit / total if total else 1.0


def raport(surse: Path = SURSE) -> str:
    masuri = masoara(surse)
    linii = ["recall localizatori vs marcajele S_LGI ale portalului:", ""]
    for m in masuri:
        linii.append(f"  {m.act:22} {m.gasite:>4}/{m.marcaje:<4} {m.recall:.1%}")
    total = sum(m.marcaje for m in masuri)
    gasit = sum(m.gasite for m in masuri)
    linii += ["", f"  TOTAL {gasit}/{total} = {recall_global(masuri):.1%}"]
    return "\n".join(linii)


if __name__ == "__main__":
    print(raport())
