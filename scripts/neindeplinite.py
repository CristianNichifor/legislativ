"""The authority's own list of unfulfilled implementing norms — ground truth for the gap report.

`vid.py` derives, from the corpus alone, that a law required an implementing act within a
deadline and that no such act was ever collected. That is arithmetic, and it is honest about its
one weakness: an absent norm and an uncollected norm look identical from inside the graph. The
Consiliul Legislativ / SGG publish the answer key — *Situația normelor neîndeplinite*, the list of
delegated norms that were mandated and never issued. Comparing our derived report against that list
is what turns "derived, hedged" into "independently reproduces N of the authority's M outstanding
norms; here are the ones we miss and the extras we raise".

**The tool stays offline.** The list is a public document the user downloads; this reads it from a
file rather than fetching it, so a draft — and the machine — never has to reach out. The format is
a small delimited table (CSV/TSV, ';' or ',' or tab), documented in the committed sample
`data/neindeplinite_exemplu.csv`: one row per outstanding norm, columns
`act, instrument, scadenta, stadiu, sursa`. Column names are
matched diacritic-folded and a handful of aliases are accepted, because the export is retyped by
hand as often as not.

**The denominator is only what the corpus can vouch for.** An authority entry whose host act is not
in the corpus cannot be judged — its absence would be a scrape gap, not a disagreement — so those
rows are reported separately (`necunoscute`) and kept out of the coverage fraction. The number that
goes in front of a room is coverage over acts we actually hold, and the acts we cannot check are
named rather than folded into it.

Comparison is at the level of the host act, which is the key both sides share cleanly. The
authority lists norms; we flag host acts with an undischarged obligation; the join is on the act.
Instrument-level matching is noisier and is left for later — act-level agreement is the defensible
headline, and the misses it names are the work list. Standard library only.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from scripts.referinte import acte as extrage_acte
from scripts.termene import INSTRUMENTE
from scripts.text import cheie

# Header aliases, all compared diacritic-folded via `cheie`. The left of each pair is a folded
# spelling the export might use; the right is the canonical field.
_ALIASE: dict[str, str] = {
    "act": "act",
    "lege": "act",
    "act de baza": "act",
    "actul de baza": "act",
    "temei": "act",
    "temei legal": "act",
    "baza legala": "act",
    "instrument": "instrument",
    "norma": "instrument",
    "norme": "instrument",
    "act de aplicare": "instrument",
    "norma de aplicare": "instrument",
    "scadenta": "scadenta",
    "termen": "scadenta",
    "termen limita": "scadenta",
    "data limita": "scadenta",
    "stadiu": "stadiu",
    "status": "stadiu",
    "stare": "stadiu",
    "sursa": "sursa",
    "referinta": "sursa",
}


@dataclass(frozen=True)
class NormaNeindeplinita:
    """One implementing norm the authority records as mandated and not issued."""

    act_id: str | None  # None when the citation could not be resolved to an act key
    act_citat: str
    instrument: str
    tip_asteptat: str | None
    scadenta: date | None
    stadiu: str
    sursa: str


@dataclass(frozen=True)
class Comparatie:
    """How the derived gap report lines up with the authority's list, at the host-act level."""

    acord: tuple[str, ...]  # acts both the tool and the authority flag
    doar_autoritate: tuple[str, ...]  # authority lists outstanding, tool did not flag — misses
    doar_tool: tuple[str, ...]  # tool flags a gap the authority does not list — extras / FPs
    necunoscute: tuple[str, ...]  # authority acts absent from the corpus — cannot be judged

    @property
    def acoperire(self) -> float:
        """Coverage over acts the corpus can actually vouch for: of the authority's outstanding
        norms whose host act we hold, the fraction the tool independently flags as a gap."""
        verificabile = len(self.acord) + len(self.doar_autoritate)
        return len(self.acord) / verificabile if verificabile else 1.0


def _tip_instrument(text: str) -> str | None:
    """Map an instrument named in prose to the expected act type, using the same table the
    deadline extractor uses, so the two agree on what 'norme metodologice' should be issued as."""
    for _nume, tip, sablon in INSTRUMENTE:
        if re.search(sablon, text, re.IGNORECASE):
            return tip
    return None


def _data(brut: str) -> date | None:
    """Parse a deadline written ISO (2018-01-01) or Romanian-dotted (01.01.2018). Anything else
    is left as no date rather than guessed — an invented deadline is exactly the failure the gap
    report is built to avoid."""
    brut = brut.strip()
    if not brut:
        return None
    try:
        return date.fromisoformat(brut)
    except ValueError:
        pass
    parti = brut.replace("/", ".").split(".")
    if len(parti) == 3 and all(p.strip().isdigit() for p in parti):
        zi, luna, an = (int(p) for p in parti)
        if an < 100:  # a two-digit year is too ambiguous to place; refuse it
            return None
        try:
            return date(an, luna, zi)
        except ValueError:
            return None
    return None


def _act_id(citat: str) -> str | None:
    """The corpus key for an act as the list cites it, or None if it cannot be resolved.

    Reuses the reference extractor so the key is derived exactly as everywhere else — the same
    citation produces the same node id here as in the graph, which is what lets the join land."""
    for ref in extrage_acte(citat):
        if ref.act is not None:
            return ref.act.id
    return None


def citeste(cale: Path | str, *, sursa: str | None = None) -> list[NormaNeindeplinita]:
    """Read the authority's list from a delimited file into rows keyed to corpus acts.

    Lines beginning with '#' are comments (the sample file documents its own format that way).
    The delimiter is sniffed and falls back to comma; headers are matched diacritic-folded through
    a small alias table. A row with no resolvable act keeps `act_id=None` and is surfaced as
    `necunoscute` by `compara`, never silently dropped.
    """
    cale = Path(cale)
    implicit_sursa = sursa or cale.stem
    linii = [ln for ln in cale.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    if not linii:
        return []
    try:
        dialect = csv.Sniffer().sniff(linii[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.get_dialect("excel")
    cititor = csv.DictReader(linii, dialect=dialect)
    camp = {
        (c or "").strip(): _ALIASE.get(cheie((c or "").strip()), "")
        for c in cititor.fieldnames or []
    }

    norme: list[NormaNeindeplinita] = []
    for rand in cititor:
        val = {camp[k]: (v or "").strip() for k, v in rand.items() if camp.get(k)}
        citat = val.get("act", "").strip()
        instrument = val.get("instrument", "").strip()
        if not citat or not instrument:
            continue
        norme.append(
            NormaNeindeplinita(
                act_id=_act_id(citat),
                act_citat=citat,
                instrument=instrument,
                tip_asteptat=_tip_instrument(instrument),
                scadenta=_data(val.get("scadenta", "")),
                stadiu=val.get("stadiu", "").strip() or "neîndeplinită",
                sursa=val.get("sursa", "").strip() or implicit_sursa,
            )
        )
    return norme


def compara(vids, norme: list[NormaNeindeplinita], *, acte_in_corpus: set[str]) -> Comparatie:
    """Line the derived gap report up against the authority's list, at the host-act level.

    `vids` is a list of `vid.Vid`; only each finding's host act is used. `acte_in_corpus` is the
    set of act ids the corpus holds — the authority's rows for acts outside it cannot be judged
    and become `necunoscute`, kept out of the coverage fraction.
    """
    autoritate = {n.act_id for n in norme if n.act_id}
    tool = {v.obligatie.act.id for v in vids if v.obligatie.act}

    verificabile = autoritate & acte_in_corpus
    necunoscute = autoritate - acte_in_corpus
    return Comparatie(
        acord=tuple(sorted(verificabile & tool)),
        doar_autoritate=tuple(sorted(verificabile - tool)),
        doar_tool=tuple(sorted(tool - autoritate)),
        necunoscute=tuple(sorted(necunoscute)),
    )


def importa(
    cale: Path | str, cale_db: Path | str = "corpus.db", *, sursa: str | None = None
) -> int:
    """Read the list and store it beside the corpus it validates. Returns rows written."""
    from scripts import depozit

    norme = citeste(cale, sursa=sursa)
    scrise = 0
    with depozit.deschide(cale_db) as con:
        for n in norme:
            if n.act_id is None:
                continue
            depozit.scrie_norma(con, n)
            scrise += 1
    return scrise


def raport(cmp: Comparatie) -> str:
    """The comparison as it goes in front of a room: the number, then both work lists named."""
    linii = [
        f"acoperire vs lista autorității: {len(cmp.acord)}/"
        f"{len(cmp.acord) + len(cmp.doar_autoritate)} acte = {cmp.acoperire:.1%}",
        "",
        f"  în acord (ambele semnalează vid):        {len(cmp.acord)}",
        f"  doar autoritatea (ratări ale tool-ului):  {len(cmp.doar_autoritate)}",
        f"  doar tool-ul (în plus / fals-pozitive):   {len(cmp.doar_tool)}",
        f"  neverificabile (act lipsă din corpus):    {len(cmp.necunoscute)}",
    ]
    if cmp.doar_autoritate:
        linii += ["", "  ratări (autoritatea le listează, noi nu):"]
        linii += [f"    {a}" for a in cmp.doar_autoritate[:25]]
    if cmp.necunoscute:
        linii += ["", "  neverificabile (nu sunt în corpus — lipsă de colectare, nu dezacord):"]
        linii += [f"    {a}" for a in cmp.necunoscute[:25]]
    return "\n".join(linii)


def _main() -> int:
    import argparse

    from scripts import depozit
    from scripts.vid_corpus import raport_vid

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lista", required=True, help="fișierul cu lista oficială (CSV/TSV)")
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--graf", default="graf.db")
    ap.add_argument("--importa", action="store_true", help="stochează lista în corpus.db")
    ap.add_argument(
        "--complet", default="", help="tipuri complete, separate prin virgulă (ex: hg,ordin)"
    )
    ap.add_argument("--limita", type=int, default=None)
    a = ap.parse_args()

    norme = citeste(a.lista)
    print(f"{len(norme)} norme citite din {a.lista}", end="")
    nerezolvate = sum(1 for n in norme if n.act_id is None)
    if nerezolvate:
        print(f" ({nerezolvate} fără act rezolvabil)", end="")
    print()

    if a.importa:
        scrise = importa(a.lista, a.corpus)
        print(f"{scrise} norme stocate în {a.corpus}")

    complet = frozenset(t.strip() for t in a.complet.split(",") if t.strip())
    vids = raport_vid(a.corpus, a.graf, complet_pentru=complet, limita=a.limita)
    with depozit.deschide(a.corpus, readonly=True) as con:
        acte = {r[0] for r in con.execute("SELECT id FROM acte")}
    print()
    print(raport(compara(vids, norme, acte_in_corpus=acte)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
