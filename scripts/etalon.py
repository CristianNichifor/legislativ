"""What the extractors actually catch, measured rather than asserted.

Every regular expression in this package looked right when it was written and several of them
were wrong. `articolului` did not match a pattern built for `articolul`; the jargon check flagged
correct usage and missed the error it exists for; the order instrument matched citations of
orders as though they were requirements to issue one. All three were found by a labelled example,
none by reading the pattern.

So the deterministic layer ships with a number. `raporteaza()` prints precision and recall per
extractor over `data/etalon.json`, and prints the misses by case id, because an aggregate that
does not say *which* cases fail cannot be acted on.

**The gold set keeps its failures.** Two cases are marked `cunoscut_ratat` — article enumerations
(`la articolele 7 și 8`) which are not expanded, and the vacatio legis sentence which is read as
an obligation with no instrument. Removing them would raise the printed score and lower the
information in it to zero. A linter that reports 100% on a set curated to make it report 100% is
the failure mode this whole repository is built against, and it is worse here than elsewhere
because the number is what a research team would use to decide how far to trust the tool.

Run it directly: `python -m scripts.etalon`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.amendamente import amendamente
from scripts.referinte import Act, acte, referinte
from scripts.termene import obligatii

ETALON = Path(__file__).resolve().parent.parent / "data" / "etalon.json"


@dataclass(frozen=True)
class Scor:
    """One extractor's tally. Counts are kept so several groups can be summed honestly."""

    grup: str
    adevarat_pozitive: int
    fals_pozitive: int
    fals_negative: int

    @property
    def precizie(self) -> float:
        numitor = self.adevarat_pozitive + self.fals_pozitive
        return self.adevarat_pozitive / numitor if numitor else 1.0

    @property
    def acoperire(self) -> float:
        numitor = self.adevarat_pozitive + self.fals_negative
        return self.adevarat_pozitive / numitor if numitor else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precizie, self.acoperire
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def plus(self, alt: Scor) -> Scor:
        return Scor(
            self.grup,
            self.adevarat_pozitive + alt.adevarat_pozitive,
            self.fals_pozitive + alt.fals_pozitive,
            self.fals_negative + alt.fals_negative,
        )


def _act_din_id(identificator: str | None) -> Act | None:
    if not identificator:
        return None
    parti = identificator.split("-")
    if len(parti) >= 3 and parti[-1].isdigit():
        return Act("-".join(parti[:-2]), parti[-2], int(parti[-1]))
    return Act(identificator)


def _observat(caz: dict[str, Any]) -> dict[str, set[tuple[Any, ...]]]:
    """Run every extractor the case has an expectation for, and shape the output for comparison."""
    text = caz["text"]
    gazda = _act_din_id(caz.get("act_gazda"))
    iesire: dict[str, set[tuple[Any, ...]]] = {}

    if "acte" in caz["asteptat"]:
        iesire["acte"] = {(r.act.id,) for r in acte(text) if r.act}
    if "referinte" in caz["asteptat"]:
        iesire["referinte"] = {
            (r.act.id if r.act else None, r.locator.id) for r in referinte(text) if r.locator
        }
    if "amendamente" in caz["asteptat"]:
        iesire["amendamente"] = {
            (a.fel, a.act_tinta.id if a.act_tinta else None, a.locator.id)
            for a in amendamente(text, act_gazda=gazda)
        }
    if "articole_noi" in caz["asteptat"]:
        iesire["articole_noi"] = {
            (n,) for a in amendamente(text, act_gazda=gazda) for n in a.articole_noi
        }
    if "obligatii" in caz["asteptat"]:
        iesire["obligatii"] = {
            (o.instrument, o.termen_zile, o.ancora, o.institutie) for o in obligatii(text)
        }
    return iesire


def _asteptat(caz: dict[str, Any]) -> dict[str, set[tuple[Any, ...]]]:
    return {
        camp: {tuple(v) if isinstance(v, list) else (v,) for v in valori}
        for camp, valori in caz["asteptat"].items()
    }


def evalueaza(cale: Path = ETALON) -> tuple[dict[str, Scor], list[str]]:
    """Score every case, and collect a line per discrepancy."""
    cazuri = json.loads(cale.read_text(encoding="utf-8"))["cazuri"]
    scoruri: dict[str, Scor] = {}
    abateri: list[str] = []

    for caz in cazuri:
        asteptat, observat = _asteptat(caz), _observat(caz)
        for camp, vrut in asteptat.items():
            gasit = observat.get(camp, set())
            tp, fp, fn = len(vrut & gasit), len(gasit - vrut), len(vrut - gasit)
            scoruri[camp] = scoruri.get(camp, Scor(camp, 0, 0, 0)).plus(Scor(camp, tp, fp, fn))
            marcaj = " (cunoscut-ratat)" if caz.get("cunoscut_ratat") else ""
            for lipsa in sorted(vrut - gasit, key=str):
                abateri.append(f"  {caz['id']:8} {camp:13} lipsă     {lipsa}{marcaj}")
            for inventat in sorted(gasit - vrut, key=str):
                abateri.append(f"  {caz['id']:8} {camp:13} în plus   {inventat}{marcaj}")
    return scoruri, abateri


def raporteaza(cale: Path = ETALON) -> str:
    scoruri, abateri = evalueaza(cale)
    total = Scor("total", 0, 0, 0)
    for s in scoruri.values():
        total = total.plus(s)

    linii = [f"{'extractor':14} {'precizie':>9} {'acoperire':>10} {'F1':>7}   tp/fp/fn", "-" * 62]
    for nume in sorted(scoruri):
        s = scoruri[nume]
        linii.append(
            f"{nume:14} {s.precizie:>8.1%} {s.acoperire:>10.1%} {s.f1:>7.2f}   "
            f"{s.adevarat_pozitive}/{s.fals_pozitive}/{s.fals_negative}"
        )
    linii += [
        "-" * 62,
        f"{'TOTAL':14} {total.precizie:>8.1%} {total.acoperire:>10.1%} {total.f1:>7.2f}   "
        f"{total.adevarat_pozitive}/{total.fals_pozitive}/{total.fals_negative}",
    ]
    if abateri:
        linii += ["", f"{len(abateri)} abateri:", *abateri]
    return "\n".join(linii)


if __name__ == "__main__":
    print(raporteaza())
