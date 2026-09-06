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
