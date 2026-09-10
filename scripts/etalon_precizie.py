"""The other half of the measurement: does the extractor invent references.

`etalon.py` scores thirty-six sentences written by the same hand as the patterns, and
`etalon_real.py` scores extraction against the portal's own `S_LGI` marks. Between them they
answer "does it find what is there". Neither answers "does it report things that are not
there", and that is the failure that costs a reader trust: a missed reference is a gap someone
may notice, while an invented one is a confident wrong answer someone acts on.

**Why `S_LGI` cannot answer it, and not for the reason previously written down.** The stated
reason was that an answer key lists what *is* there and so cannot catch an invention. True, but
secondary. Measured on the committed fixtures, `S_LGI` does not mark act citations at all:

    lege-310-2021    242 marks    0 carry an act number     (100% locators)
    lege-98-2016     580 marks   14 carry an act number     (97.6% locators)

All fourteen name the host act. Not one of the 822 marks points at a *different* act. `S_LGI`
marks positions inside the text — `lit. e)`, `anexa nr. 1`, `art. 107 alin. (1)-(3)` — so what
`etalon_real.py` measures is locator recall, which is a real number about a real extractor and
is not the same thing as reference recall. Building a precision check on "extracted but
unmarked" would therefore label `Legea nr. 171/1998` an invention because the publisher never
marked it, which is not a measurement, it is a sentence generator.

**So this one asks a person.** There is no answer key for act citations, so it builds one: it
samples what the extractor claims, writes each claim out with the surrounding text, and scores
whatever comes back labelled. The reviewer's question is narrow and answerable without reading
the whole act — *in this passage, is this a real citation of that act?* — which is what keeps
the work to an afternoon instead of a project.

**The sheet is pinned to the extractor.** Every candidate carries a key derived from the file
and the span it was read at, and the sheet records the fingerprint of the whole candidate set.
Change `referinte.py` and the fingerprint moves, the test fails, and the sheet has to be
regenerated and the new candidates reviewed. Verdicts cannot quietly come to describe an
extractor that no longer exists.

Regenerate the sheet:  `python -m scripts.etalon_precizie --scrie`
Report what is known:   `python -m scripts.etalon_precizie`
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from scripts.referinte import referinte
from scripts.text import normalizeaza

RADACINA = Path(__file__).resolve().parent.parent
SURSE = RADACINA / "sources"
FISA = RADACINA / "data" / "etalon-precizie.json"
VERDICTE = RADACINA / "data" / "etalon-precizie-verdicte.json"

# How much text the reviewer gets either side of the citation. Enough to see the sentence it
# sits in, because "is this a real citation" is a question about the sentence, not the span.
CONTEXT = 220

# The sample. The pool across the committed fixtures is a couple of hundred, so this is most of
# it rather than a thin slice; the cap exists so that adding a citation-dense fixture does not
# silently turn an afternoon of review into a week of it.
ESANTION = 120


@dataclass(frozen=True)
class Candidat:
    """One thing the extractor claims is a citation of another act."""

    cheie: str
    fisier: str
    act: str
    text: str
    inainte: str
    dupa: str


def _curat(fragment: str) -> str:
    return normalizeaza(html.unescape(re.sub(r"<[^>]+>", " ", fragment)))


def _cheie(fisier: str, start: int, act: str) -> str:
    """Stable across runs, and changes when the span or the act read from it changes.

    Position alone would collide across files; act alone would collapse the twenty places one
    law is cited into a single question. Both, so a verdict answers one passage.
    """
    return f"{fisier}:{start}:{act}"


def candidati(surse: Path = SURSE) -> list[Candidat]:
    """Every external act citation the extractor claims, over the committed fixtures.

    Internal references — `art. 7` meaning article 7 of the act being read — are excluded.
    They carry no act, they are the majority of what `referinte()` returns, and whether they
    resolve is a question about the caller that binds them, not about invention.
    """
    gasite: list[Candidat] = []
    for cale in sorted(surse.glob("*.html.gz")):
        brut = gzip.decompress(cale.read_bytes()).decode("utf-8", errors="replace")
        corp = _curat(brut)
        for r in referinte(corp):
            if r.act is None or not r.text:
                continue
            gasite.append(
                Candidat(
                    cheie=_cheie(cale.stem, r.start, r.act.id),
                    fisier=cale.stem,
                    act=r.act.id,
                    text=r.text,
                    inainte=corp[max(0, r.start - CONTEXT) : r.start],
                    dupa=corp[r.end : r.end + CONTEXT],
                )
            )
    return gasite


def amprenta(lot: list[Candidat]) -> str:
    """Fingerprint of the whole candidate set: what the verdicts below are answers about."""
    h = hashlib.blake2s(digest_size=16)
    for c in sorted(lot, key=lambda x: x.cheie):
        h.update(c.cheie.encode("utf-8"))
        h.update(b"\0")
        h.update(c.text.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def esantion(lot: list[Candidat], marime: int = ESANTION) -> list[Candidat]:
    """A deterministic sample, spread across files and acts.

    Sorted by a hash of the key rather than by position, because position order would hand the
    reviewer the first hundred citations of the first file — the same act, over and over, in
    the same section — and a sample that is all one act measures one pattern. A hash is not
    random, it is arbitrary and reproducible, which is what this needs: the same fixtures give
    the same sheet on every machine and in CI.
    """
    ordonat = sorted(lot, key=lambda c: hashlib.blake2s(c.cheie.encode("utf-8")).hexdigest())
    return sorted(ordonat[:marime], key=lambda c: (c.fisier, c.cheie))


def scrie_fisa(cale: Path = FISA, surse: Path = SURSE) -> dict:
    lot = candidati(surse)
    ales = esantion(lot)
    fisa = {
        # Emitted, not added by hand: tests/test_date.py requires every document under data/ to
        # declare a schema that exists and to validate against it, and a generated file that has
        # to be hand-edited afterwards to satisfy that is a file that will one day not be.
        "$schema": "../schema/etalon-precizie.schema.json",
        "_": (
            "Fișă de verificare pentru precizia extractorului de referințe. "
            "Vezi scripts/etalon_precizie.py."
        ),
        "amprenta": amprenta(lot),
        "candidati_total": len(lot),
        "in_esantion": len(ales),
        "intrebare": (
            "În pasajul de mai jos, `text` este o citare reală a actului `act`? "
            "Răspunsul intră în data/etalon-precizie-verdicte.json ca true / false / null."
        ),
        "elemente": [
            {
                "cheie": c.cheie,
                "fisier": c.fisier,
                "act": c.act,
                "text": c.text,
                "inainte": c.inainte,
                "dupa": c.dupa,
            }
            for c in ales
        ],
    }
    cale.write_text(json.dumps(fisa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return fisa


def citeste_fisa(cale: Path = FISA) -> dict:
    return json.loads(cale.read_text(encoding="utf-8"))


def citeste_verdicte(cale: Path = VERDICTE) -> dict:
    return json.loads(cale.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Scor:
    corecte: int
    gresite: int
    neclare: int
    nelabelate: int

    @property
    def judecate(self) -> int:
        return self.corecte + self.gresite

    @property
    def precizie(self) -> float | None:
        """None, not 1.0, when nothing has been judged. A precision of "no data" is not perfect
        precision, and every number this returns has to survive being read by someone in a
        hurry."""
        return self.corecte / self.judecate if self.judecate else None


def scor(fisa: dict | None = None, verdicte: dict | None = None) -> Scor:
    fisa = fisa if fisa is not None else citeste_fisa()
    verdicte = verdicte if verdicte is not None else citeste_verdicte()
    date = verdicte.get("verdicte", {})
    corecte = gresite = neclare = nelabelate = 0
    for element in fisa["elemente"]:
        v = date.get(element["cheie"])
        raspuns = v.get("corect") if isinstance(v, dict) else None
        if raspuns is True:
            corecte += 1
        elif raspuns is False:
            gresite += 1
        elif isinstance(v, dict):
            neclare += 1
        else:
            nelabelate += 1
    return Scor(corecte, gresite, neclare, nelabelate)


def raport(fisa: dict | None = None, verdicte: dict | None = None) -> str:
    fisa = fisa if fisa is not None else citeste_fisa()
    s = scor(fisa, verdicte)
    linii = [
        "precizia referințelor externe, față de verdicte omenești:",
        "",
        f"  candidați în corpus   {fisa['candidati_total']}",
        f"  în eșantion           {fisa['in_esantion']}",
        f"  judecate              {s.judecate}   (corecte {s.corecte}, greșite {s.gresite})",
        f"  neclare               {s.neclare}",
        f"  nelabelate            {s.nelabelate}",
        "",
    ]
    if s.precizie is None:
        linii.append("  PRECIZIE: nemăsurată — niciun verdict. Nu este 100%.")
    else:
        linii.append(f"  PRECIZIE: {s.precizie:.1%} pe {s.judecate} judecate")
    return "\n".join(linii)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scrie", action="store_true", help="regenerează fișa de verificare")
    argumente = parser.parse_args()
    if argumente.scrie:
        f = scrie_fisa()
        print(f"am scris {FISA} — {f['in_esantion']} din {f['candidati_total']} candidați")
    else:
        print(raport())
