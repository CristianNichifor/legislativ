"""Tests for in-force awareness.

The point is narrow and the whole reason it exists: a draft must not be allowed to build on law
that is gone. So the tests assert exactly that — a citation to a repealed act, and to a repealed
article, is caught; a citation to living law is not; and an article repeal reaches the paragraphs
under it. Built on a constructed corpus + graph so the assertions are exact.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.graf import _deschide_graf, construieste
from scripts.vigoare import (
    _peste_republicare,
    citari_calificate,
    citari_moarte,
    este_abrogat,
    locatori_abrogati,
)


def _graf(tmp_path: Path, acts: list[tuple[str, str, str]]):
    corpus = tmp_path / "corpus.db"
    with depozit.deschide(corpus) as con:
        for tip, numar, text in acts:
            rec = Inregistrare(
                titlu=f"{tip} nr. {numar}",
                tip_act=tip,
                numar=numar,
                an=None,
                data_vigoare=date(2020, 1, 1),
                emitent="X",
                publicatie="MO",
                link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{numar}0",
                text=text,
            )
            depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    graf_db = tmp_path / "graf.db"
    construieste(str(corpus), str(graf_db))
    return _deschide_graf(str(graf_db), readonly=True)


def test_a_whole_act_repeal_is_seen(tmp_path):
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Se abrogă Legea nr. 50/1991 privind autorizarea construcțiilor."),
        ],
    )
    ab = este_abrogat(graf, "lege-50-1991")
    assert ab is not None and ab.este_intregul_act and ab.de_catre == "lege-200-2020"


def test_an_article_repeal_is_seen(tmp_path):
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Articolul 15 din Legea nr. 98/2016 se abrogă."),
        ],
    )
    abrogati = locatori_abrogati(graf, "lege-98-2016")
    assert "art15" in abrogati


def test_a_draft_citing_a_repealed_article_is_flagged(tmp_path):
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Articolul 15 din Legea nr. 98/2016 se abrogă."),
        ],
    )
    dead = citari_moarte("Se aplică prevederile articolului 15 din Legea nr. 98/2016.", graf)
    assert dead and dead[0].act_id == "lege-98-2016" and dead[0].locator == "art15"
    assert "abrogat" in dead[0].motiv


def test_a_draft_citing_living_law_is_not_flagged(tmp_path):
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Articolul 15 din Legea nr. 98/2016 se abrogă."),
        ],
    )
    # art. 7 is not the repealed article
    assert citari_moarte("Se aplică art. 7 din Legea nr. 98/2016.", graf) == []


def test_an_article_repeal_reaches_the_paragraphs_under_it(tmp_path):
    """If art. 7 is repealed, a citation to art. 7 para (2) is just as dead."""
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Articolul 7 din Legea nr. 98/2016 se abrogă."),
        ],
    )
    dead = citari_moarte("în condițiile art. 7 alin. (2) din Legea nr. 98/2016", graf)
    assert dead and dead[0].locator.startswith("art7")


def test_a_whole_act_repeal_condemns_any_citation_into_it(tmp_path):
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Se abrogă Legea nr. 50/1991."),
        ],
    )
    dead = citari_moarte("potrivit art. 3 din Legea nr. 50/1991", graf)
    assert dead and dead[0].abrogare.este_intregul_act


# --- qualified status short of repeal: suspended, derogated, prorogated ---


def test_a_draft_citing_a_suspended_article_is_flagged(tmp_path):
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Aplicarea articolului 7 din Legea nr. 98/2016 se suspendă."),
        ],
    )
    cal = citari_calificate("Se aplică art. 7 din Legea nr. 98/2016.", graf)
    assert cal and cal[0].act_id == "lege-98-2016" and cal[0].locator == "art7"
    assert cal[0].eticheta == "suspendat" and "suspendat" in cal[0].motiv


def test_a_derogation_is_surfaced(tmp_path):
    graf = _graf(
        tmp_path,
        [
            (
                "LEGE",
                "200",
                "Prin derogare de la articolul 5 din Legea nr. 98/2016, taxa nu se ia.",
            ),
        ],
    )
    cal = citari_calificate("în temeiul art. 5 din Legea nr. 98/2016", graf)
    assert cal and cal[0].eticheta == "derogare" and "derogă" in cal[0].motiv


def test_a_repealed_provision_is_not_repeated_as_qualified(tmp_path):
    # death subsumes qualification: a repealed article is reported dead, not merely qualified
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Articolul 7 din Legea nr. 98/2016 se abrogă."),
            ("LEGE", "201", "Aplicarea articolului 7 din Legea nr. 98/2016 se suspendă."),
        ],
    )
    draft = "Se aplică art. 7 din Legea nr. 98/2016."
    assert citari_moarte(draft, graf)  # caught as dead
    assert citari_calificate(draft, graf) == []  # and not repeated as qualified


def test_unqualified_living_law_is_not_flagged(tmp_path):
    graf = _graf(
        tmp_path,
        [
            ("LEGE", "200", "Aplicarea articolului 7 din Legea nr. 98/2016 se suspendă."),
        ],
    )
    # art. 9 carries no qualification
    assert citari_calificate("Se aplică art. 9 din Legea nr. 98/2016.", graf) == []


# --- republication: a renumbering boundary the package will not assert across ------------------
#
# The acts in `_graf` are dated 2020-01-01, so every edge carries that date. Moving the
# republication date either side of it is what puts a repeal before or after the boundary.

def _dateaza(tmp_path: Path, cand: date) -> None:
    """Put a date on the repeal edges. `_graf`'s acts produce undated ones, and the after-the-
    boundary case needs a dated edge to be about anything."""
    import sqlite3

    con = sqlite3.connect(tmp_path / "graf.db")
    con.execute("UPDATE muchii SET de_la = ? WHERE fel = 'abroga'", (cand.isoformat(),))
    con.commit()
    con.close()


CITARE = "Se aplică prevederile articolului 15 din Legea nr. 98/2016."
ABROGA_15 = ("LEGE", "200", "Articolul 15 din Legea nr. 98/2016 se abrogă.")


def test_a_repeal_older_than_the_republication_is_qualified_not_asserted(tmp_path):
    """The repealed art. 15 and today's art. 15 need not be the same provision."""
    graf = _graf(tmp_path, [ABROGA_15])
    dead = citari_moarte(CITARE, graf, {"lege-98-2016": date(2021, 6, 1)})
    assert len(dead) == 1
    assert dead[0].peste_republicare == date(2021, 6, 1)
    assert dead[0].severitate == "material"       # not blocking: the match may not hold
    assert "republicării" in dead[0].motiv and "01.06.2021" in dead[0].motiv


def test_the_boundary_rule_itself(tmp_path):
    """`_peste_republicare` is the whole decision, so it is worth pinning exactly.

    Returns the date a locator match must cross, or None when it crosses none.
    """
    R, INAINTE, DUPA = date(2021, 6, 1), date(2020, 1, 1), date(2022, 1, 1)
    # a repeal older than the republication: its locator is in the old numbering
    assert _peste_republicare("art15", INAINTE, R) == R
    # on or after it: already current numbering, nothing to cross
    assert _peste_republicare("art15", R, R) is None
    assert _peste_republicare("art15", DUPA, R) is None
    # undated, with a republication on record: cannot be placed, so it counts as crossing —
    # the same call consolidare.py makes for an operation it cannot date
    assert _peste_republicare("art15", None, R) == R
    # no republication on record: an absent date is not evidence of a boundary
    assert _peste_republicare("art15", INAINTE, None) is None
    # whole-act edge: no locator to renumber
    assert _peste_republicare("", INAINTE, R) is None


def test_a_repeal_after_the_republication_is_asserted_normally(tmp_path):
    """Past the boundary the locator is already in current numbering, so nothing is qualified."""
    _graf(tmp_path, [ABROGA_15]).close()   # builds corpus + graph
    _dateaza(tmp_path, date(2022, 1, 1))
    graf = _deschide_graf(str(tmp_path / "graf.db"), readonly=True)
    dead = citari_moarte(CITARE, graf, {"lege-98-2016": date(2021, 6, 1)})
    assert len(dead) == 1
    assert dead[0].abrogare.de_la == date(2022, 1, 1)   # the edge really is dated
    assert dead[0].peste_republicare is None
    assert dead[0].severitate == "blocking"
    assert "republicării" not in dead[0].motiv


def test_without_a_republication_date_nothing_changes(tmp_path):
    """An absent date is not evidence of a boundary — the finding stands as it always did."""
    graf = _graf(tmp_path, [ABROGA_15])
    fara = citari_moarte(CITARE, graf)
    cu_none = citari_moarte(CITARE, graf, {"lege-98-2016": None})
    assert [d.severitate for d in fara] == ["blocking"]
    assert [d.motiv for d in cu_none] == [d.motiv for d in fara]


def test_a_whole_act_repeal_is_never_qualified_by_a_republication(tmp_path):
    """Renumbering cannot save an act that is gone, so this stays blocking."""
    graf = _graf(
        tmp_path,
        [("LEGE", "200", "Se abrogă Legea nr. 50/1991 privind autorizarea construcțiilor.")],
    )
    dead = citari_moarte(
        "Se aplică art. 15 din Legea nr. 50/1991.", graf, {"lege-50-1991": date(2021, 6, 1)}
    )
    assert len(dead) == 1
    assert dead[0].peste_republicare is None
    assert dead[0].severitate == "blocking"


def test_a_qualification_older_than_the_republication_is_qualified_too(tmp_path):
    """Suspension and derogation edges carry locators, so the same boundary applies."""
    graf = _graf(
        tmp_path,
        [("LEGE", "200", "Aplicarea articolului 7 din Legea nr. 98/2016 se suspendă.")],
    )
    cal = citari_calificate(
        "Se aplică art. 7 din Legea nr. 98/2016.", graf, {"lege-98-2016": date(2021, 6, 1)}
    )
    assert len(cal) == 1
    assert cal[0].peste_republicare == date(2021, 6, 1)
    assert "republicării" in cal[0].motiv
