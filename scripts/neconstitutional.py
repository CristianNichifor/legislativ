"""Provisions the Court put out of force that nobody ever repaired.

This is the register the whole CCR layer exists to produce. `decizii.py` reads what a decision
struck; the amendment graph knows what was touched afterwards and when; this joins the two and
reports the rows where the second never happened. The output is the same shape as `vid.py`'s and
for the same reason — it is arithmetic over dates and edges, checkable line by line, and it says
on each row what it could not check.

**Article 147 (1) is the clock, and it is short.** A provision found unconstitutional is
suspended for 45 days from publication of the decision, and if Parliament or the Government has
not brought it into line by then it ceases to have legal effect. The text stays in the official
consolidated version regardless — that is the point. A row here says: this text is still printed,
it has had no legal effect since a date in the 1990s, and nothing in the corpus shows anyone
touched it. Before the 2003 revision the same rule sat in article 145 (1) with the same 45 days,
so the arithmetic is unchanged across the whole corpus.

**Article 150 (1) has no clock at all.** A pre-1991 provision contrary to the Constitution was
abrogated by the Constitution itself, and the Court only records that it happened. There was
never a 45-day window for anyone to miss, so `termen` is `None` and stays `None` rather than
being counted from the decision that noticed it.

**An amendment that predates the decision is not a repair, and this is the mistake that would
make the register look like it worked.** Nearly every struck provision had been amended before —
frequently that is how it came to be challenged. Accepting any amending edge would clear almost
every row and produce a short, clean, entirely wrong report.

**An instrument that cannot amend the struck act does not repair it either.** An ordin of a
minister modifying a law is either a parse error or an illegality; in both cases clearing the row
on it would be wrong. Those edges are kept and shown as near misses, because a reader will ask
about them first, and the row says why they were not counted.

**Absence is only evidence if the corpus is complete.** The same rule `vid.py` runs on, and here
it bites harder: this corpus holds a fraction of the national one and stops in 2008, so a repair
enacted in 2011 is invisible. `complet_pentru` names the act types the caller claims to have
collected exhaustively, and every row outside it comes back `blocking` and says so on its face.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from scripts.decizii import Proviziune, citeste

# Article 147 (1) of the Constitution, and article 145 (1) before the 2003 revision.
ZILE_SUSPENDARE: Final[int] = 45

# Edges that can put a struck text right. A `refera` cannot: pointing at a provision is not
# changing it, and 12 310 of the 14 345 edges in this graph are references.
FELURI_REPARATOARE: Final[frozenset[str]] = frozenset(
    {"modifica", "inlocuieste", "abroga", "completeaza", "introduce"}
)

# What may amend what. A law is amended by a law or by an ordonanță; a hotărâre or an ordin
# cannot reach it. Ranks are compared, not matched, so an oug amending an hg is fine.
RANG: Final[dict[str, int]] = {
    "constitutie": 0,
    "lege": 1,
    "decret-lege": 1,
    "oug": 1,
    "og": 1,
    "decret": 2,
    "hg": 3,
    "ordin": 4,
    "norma": 4,
    "instructiuni": 4,
}


@dataclass(frozen=True)
class Muchie:
    """One amendment edge, as `graf.db` holds it."""

    din_act: str
    catre_act: str
    locator: str
    fel: str
    de_la: date | None


@dataclass(frozen=True)
class Lovitura:
    """One provision put out of force by one decision."""

    decizie: str
    publicat: date | None
    proviziune: Proviziune
    definitiva: bool | None

    @property
    def termen(self) -> date | None:
        """When the suspension ran out. `None` where no suspension was ever running."""
        if self.proviziune.fel != "neconstitutional" or self.publicat is None:
            return None
        return self.publicat + timedelta(days=ZILE_SUSPENDARE)


@dataclass(frozen=True)
class Nereparat:
    """A struck provision with nothing in the corpus that brought it into line."""

    lovitura: Lovitura
    termen: date | None
    zile_de_la_termen: int | None
    reparatii: tuple[Muchie, ...]
    atingeri: tuple[Muchie, ...]
    severitate: str
    limitari: tuple[str, ...]

    @property
    def increderea(self) -> str:
        """The strike is quoted from the decision; the *absence* of a repair is always derived
        from what happens to have been collected."""
        return "derived"


def _atinge(muchie: Muchie, prov: Proviziune) -> bool:
    """Whether an edge lands on the struck provision, at any depth either way.

    Deliberately generous in both directions: an amendment to the whole article covers a struck
    paragraph, and an amendment to one paragraph of a struck article is treated as touching it.
    A quiet register costs a missed row; a loud one costs a researcher defending a finding that
    dissolves when someone opens the law.
    """
    if muchie.catre_act != prov.act:
        return False
    if not muchie.locator or not prov.locator:
        return True
    return (
        muchie.locator == prov.locator
        or muchie.locator.startswith(prov.locator + ".")
        or prov.locator.startswith(muchie.locator + ".")
    )


def _poate_repara(din_tip: str | None, catre_tip: str | None) -> bool:
    """Whether an act of the first type can lawfully amend one of the second."""
    if din_tip is None or catre_tip is None:
        return True
    return RANG.get(din_tip, 9) <= RANG.get(catre_tip, 9)


def registru(
    lovituri: list[Lovitura],
    muchii: list[Muchie],
    tipuri: dict[str, str],
    la_data: date,
    complet_pentru: frozenset[str],
) -> list[Nereparat]:
    """Which struck provisions the corpus cannot show were ever brought into line.

    Provisions whose act could not be keyed are not in the register at all: there is nothing to
    look them up against, and a row that named an article without a law would be unusable. They
    are counted in `decizii.py`'s limitations, where they belong.
    """
    gasite: list[Nereparat] = []
    for lov in lovituri:
        prov = lov.proviziune
        if prov.act is None:
            continue
        catre_tip = tipuri.get(prov.act)
        candidate = [m for m in muchii if _atinge(m, prov)]

        reparatii = [
            m
            for m in candidate
            if m.fel in FELURI_REPARATOARE
            and m.de_la is not None
            and lov.publicat is not None
            and m.de_la >= lov.publicat
            and _poate_repara(tipuri.get(m.din_act), catre_tip)
        ]
        if reparatii:
            continue

        atingeri = [m for m in candidate if m.fel in FELURI_REPARATOARE and m not in reparatii]
        termen = lov.termen
        limitari, severitate = _limitari(lov, catre_tip, complet_pentru, atingeri, tipuri)
        gasite.append(
            Nereparat(
                lovitura=lov,
                termen=termen,
                zile_de_la_termen=(la_data - termen).days if termen and la_data > termen else None,
                reparatii=(),
                atingeri=tuple(atingeri),
                severitate=severitate,
                limitari=tuple(limitari),
            )
        )
    return sorted(
        gasite,
        key=lambda n: (-(n.zile_de_la_termen or 0), n.lovitura.proviziune.id),
    )


def _limitari(
    lov: Lovitura,
    catre_tip: str | None,
    complet_pentru: frozenset[str],
    atingeri: list[Muchie],
    tipuri: dict[str, str],
) -> tuple[list[str], str]:
    limitari: list[str] = []
    severitate = "material"

    if catre_tip is None or catre_tip not in complet_pentru:
        limitari.append(
            f"Corpusul nu se declară complet pentru actele de tip «{catre_tip or 'necunoscut'}». "
            "Lipsa unei reparații nu distinge un text rămas neconstituțional de o lipsă a "
            "colectării."
        )
        severitate = "blocking"

    if lov.definitiva is not True:
        limitari.append(
            "Decizia nu se declară definitivă în textul ei "
            f"(definitivă: {lov.definitiva!r}). În anii '90 deciziile erau supuse recursului la "
            "plen, iar un recurs admis ar răsturna această lovitură. Recursul nu a fost căutat."
        )
        severitate = "blocking"

    if lov.proviziune.fel == "abrogat_constitutional":
        limitari.append(
            "Prevederea a fost abrogată prin art. 150 alin. (1) din Constituție, nu lovită de "
            "Curte, deci nu a existat niciodată un termen de 45 de zile de aliniere. Nu se "
            "calculează întârziere."
        )
    elif lov.publicat is None:
        limitari.append(
            "Decizia nu are dată de publicare cunoscută, deci termenul de 45 de zile nu poate "
            "fi calculat."
        )

    rang_gresit = [m for m in atingeri if not _poate_repara(tipuri.get(m.din_act), catre_tip)]
    if rang_gresit:
        limitari.append(
            "Există modificări de rang inferior actului lovit "
            f"({', '.join(m.din_act for m in rang_gresit)}), care nu îl pot modifica. Nu au fost "
            "socotite reparații; sunt fie erori de parsare a grafului, fie nelegalități."
        )
    return limitari, severitate


def sumar(rows: list[Nereparat]) -> str:
    """One line per provision, worst overdue first — the list, rather than the evidence for it.

    A provision reaches the register once per decision that struck it, and several are struck
    repeatedly: `art. 224 din Codul penal` is recorded by four separate decisions. That is the
    right shape for `raport`, which has to show the reasoning behind each row, and the wrong
    shape for the question actually being asked — *which provisions are still unconstitutional* —
    where it inflates the count and buries how many distinct texts there are.

    The clock runs from the earliest strike, so that is the decision named. `raport` remains the
    place to look for why any single row is there.
    """
    if not rows:
        return "Nicio prevedere lovită rămasă nereparată în corpusul încărcat."

    grupe: dict[tuple[str | None, str], list[Nereparat]] = {}
    for n in rows:
        p = n.lovitura.proviziune
        grupe.setdefault((p.act, p.locator), []).append(n)

    def cheie(pereche):
        _, membri = pereche
        return -max((m.zile_de_la_termen or 0) for m in membri)

    linii = [f"{len(grupe)} prevederi distincte, din {len(rows)} lovituri înregistrate.", ""]
    for (act, locator), membri in sorted(grupe.items(), key=cheie):
        prima = min(membri, key=lambda m: (m.lovitura.publicat or date.max, m.lovitura.decizie))
        zile = max((m.zile_de_la_termen or 0) for m in membri)
        feluri = sorted({m.lovitura.proviziune.fel for m in membri})
        blocante = sum(1 for m in membri if m.severitate == "blocking")
        linii.append(
            f"{(act or '?') + ' ' + locator:38s} {'/'.join(feluri):24s} "
            f"{prima.lovitura.decizie:20s} {prima.lovitura.publicat or 'dată necunoscută'}  "
            f"{(str(zile) + ' zile') if zile else 'fără termen':>12s}  "
            f"{len(membri)} decizii{'  [blocking]' if blocante else ''}"
        )
    return "\n".join(linii)


def raport(rows: list[Nereparat]) -> str:
    """The table as it goes in front of a room, with every caveat attached to its own row."""
    if not rows:
        return "Nicio prevedere lovită rămasă nereparată în corpusul încărcat."
    linii = []
    for n in rows:
        lov = n.lovitura
        cand = f"{n.termen:%d.%m.%Y}" if n.termen else "fără termen"
        de_atunci = (
            f"{n.zile_de_la_termen} zile" if n.zile_de_la_termen is not None else "necalculabil"
        )
        linii.append(
            f"{lov.proviziune.id} — {lov.proviziune.fel}, prin {lov.decizie} "
            f"({lov.publicat or 'dată necunoscută'}); termen {cand}, de atunci {de_atunci} "
            f"[{n.severitate}]"
        )
        linii.append(f'    „{lov.proviziune.text[:120]}"')
        if n.atingeri:
            linii.append(
                "    atingeri necontabilizate: "
                + ", ".join(
                    f"{m.din_act} {m.fel} {m.locator or '(tot actul)'} {m.de_la}"
                    for m in n.atingeri
                )
            )
        for lim in n.limitari:
            linii.append(f"    ⚠ {lim}")
    return "\n".join(linii)


def _data(brut: str | None) -> date | None:
    try:
        return date.fromisoformat(brut) if brut else None
    except ValueError:
        return None


def din_baze(corpus: str, graf: str) -> tuple[list[Lovitura], list[Muchie], dict[str, str]]:
    """Read the decisions, the graph and the act types straight out of the databases."""
    cx = sqlite3.connect(f"file:{corpus}?mode=ro", uri=True)
    tipuri = {i: t for i, t in cx.execute("select id, tip from acte")}
    # Decisions come from `documente`, not from `acte`, for two reasons that both bite here.
    # `acte` is keyed on the citation key, and `decizie-5-1996` names a Curtea Constituțională
    # decision no better than an agency's — a collision there puts the wrong issuer on a strike.
    # And `documente.publicat` is the date read from the act's own Monitorul Oficial line, which
    # is what article 147 (1) counts its 45 days from; `acte.publicat` was a copy of the in-force
    # date. For the Court the two coincide, because article 147 (4) makes a decision binding on
    # publication — but coinciding by luck is not the same as being right.
    decizii = cx.execute(
        """select cheie_act, publicat, vigoare, text from documente
           where emitent like 'Curtea Constitu%' and tip = 'decizie' order by cheie_act"""
    ).fetchall()
    lovituri: list[Lovitura] = []
    for cheie_act, publicat, vigoare, text in decizii:
        dec = citeste(cheie_act, text)
        for prov in dec.neconstitutionale:
            # `vigoare` is the fallback and only that: for a decision the two are the same event,
            # so it costs nothing when the line is unreadable and never invents a date.
            lovituri.append(
                Lovitura(cheie_act, _data(publicat) or _data(vigoare), prov, dec.definitiva)
            )
    cx.close()

    gx = sqlite3.connect(f"file:{graf}?mode=ro", uri=True)
    muchii = [
        Muchie(d, c, loc or "", fel, _data(de_la))
        for d, c, loc, fel, de_la in gx.execute(
            "select din_act, catre_act, locator, fel, de_la from muchii where fel != 'refera'"
        )
    ]
    gx.close()
    return lovituri, muchii, tipuri


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="corpus.db")
    ap.add_argument("--graf", default="graf.db")
    ap.add_argument(
        "--complet-pentru",
        default="",
        help="tipurile de act colectate exhaustiv, separate prin virgulă. Gol = niciunul, "
        "ceea ce marchează fiecare rând «blocking» — care este starea reală a acestui corpus.",
    )
    ap.add_argument("--la-data", default=date.today().isoformat())
    ap.add_argument(
        "--sumar",
        action="store_true",
        help="o linie per prevedere, nu per lovitură — lista, nu dovezile pentru ea",
    )
    args = ap.parse_args()

    lovituri, muchii, tipuri = din_baze(args.db, args.graf)
    rows = registru(
        lovituri,
        muchii,
        tipuri,
        la_data=date.fromisoformat(args.la_data),
        complet_pentru=frozenset(t for t in args.complet_pentru.split(",") if t),
    )
    print(f"{len(lovituri)} prevederi lovite citite, {len(rows)} fără reparație în corpus.\n")
    print(sumar(rows) if args.sumar else raport(rows))


if __name__ == "__main__":
    main()
