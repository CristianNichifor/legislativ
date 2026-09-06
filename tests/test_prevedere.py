"""Tests for recovering the text of a struck provision.

The register says *which* provision the Court struck, as a citation. Checking whether a draft
**re-enacts** a struck norm — the question article 147 (4) actually poses, since the Court's
rulings bind identical provisions and not identical citations — needs the words instead.

Two properties carry this module, and both are refusals.

**It never returns text from a unit other than the one it names.** Pre-2000 drafting numbers
alineate implicitly and the collected text arrives with the paragraph breaks flattened out, so
`art. 81 alin. 4` cannot be cut. Guessing sentence boundaries there would publish a fabricated
quotation attributed to a ruling of the Constitutional Court. Instead the containing article comes
back labelled `articol`, and the label is load-bearing:
`test_a_flattened_alineat_falls_back_to_the_article_and_says_so`.

**A code citation resolves to the version in force when the strike happened.** A 1994 ruling on
`Codul penal` is about the 1968 code. Returning today's text would quote a norm the Court never
saw — plausible, well-formed, and about the wrong law.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.parsare_text import parseaza_text
from scripts.prevedere import Neregasita, Prevedere, acoperire, taie, textul, versiuni

# Modern drafting: alineate carry `(N)` markers, so they can be cut exactly. They run 1, 2, 3 —
# `parsare_text` only takes a marker that is the next one expected, which is what stops a cited
# `alin. (2)` inside running text from reading as a heading.
LEGE_MODERNA = (
    "Articolul 5\n"
    "(1) Cererea se depune la instanța competentă.\n"
    "(2) Cererea se judecă în ședință publică.\n"
    "(3) Cererea se soluționează fără citarea părților.\n"
    "Articolul 6\n"
    "(1) Hotărârea este definitivă.\n"
)

# Pre-2000 drafting as the corpus actually holds it: no `(N)` markers, no paragraph breaks. The
# second and third alineate begin mid-string with no signal of any kind.
COD_VECHI_1969 = (
    "Articolul 81 Instanța poate dispune suspendarea condiționată a executării pedepsei. "
    "Suspendarea poate fi acordată și în caz de concurs de infracțiuni. "
    "Suspendarea nu poate fi dispusă în cazul infracțiunilor intenționate."
)
COD_NOU_2014 = "Articolul 81 Textul nou, cu totul altă normă, din codul intrat în vigoare în 2014."


def _rec(titlu, tip, numar, an, text, portal, emitent="PARLAMENTUL") -> Inregistrare:
    return Inregistrare(
        titlu=titlu,
        tip_act=tip,
        numar=numar,
        an=an,
        data_vigoare=date(an, 1, 1),
        emitent=emitent,
        publicatie="MO",
        link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{portal}",
        text=text,
    )


@pytest.fixture
def con(tmp_path: Path):
    """A corpus holding one modern law and two versions of one code."""
    cale = tmp_path / "corpus.db"
    with depozit.deschide(cale) as c:
        for r in (
            _rec("LEGE nr. 59/1993", "LEGE", "59", 1993, LEGE_MODERNA, "59"),
            _rec("CODUL PENAL din 1968", "CODUL PENAL", "0", 1969, COD_VECHI_1969, "cp69"),
            _rec("CODUL PENAL din 2009", "CODUL PENAL", "0", 2014, COD_NOU_2014, "cp14"),
        ):
            depozit.scrie_inregistrare(c, r, act_din_inregistrare(r))
    cx = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    yield cx
    cx.close()


def test_the_corpus_keys_each_code_version_separately(con):
    """The premise everything else rests on: `codul-penal-0-1969` and `codul-penal-0-2014` are two
    acts, and a strike belongs to one of them."""
    assert versiuni(con)["codul-penal"] == [
        (1969, "codul-penal-0-1969"),
        (2014, "codul-penal-0-2014"),
    ]


def test_a_modern_alineat_is_cut_exactly(con):
    r = textul(con, "lege-59-1993", "art5.alin3", 1994)
    assert isinstance(r, Prevedere)
    assert r.granularitate == "exact"
    assert r.locator_gasit == "art5.alin3"
    assert r.text.strip() == "Cererea se soluționează fără citarea părților."
    assert r.nota == "", "an exact hit needs no caveat"


def test_a_code_strike_resolves_to_the_version_in_force_when_it_was_struck(con):
    """A 1994 ruling on the Penal Code is about the 1968 code. Quoting the 2014 text would be a
    well-formed quotation of a norm the Court never saw."""
    r = textul(con, "cod-penal", "art81", 1994)
    assert isinstance(r, Prevedere)
    assert r.act_gasit == "codul-penal-0-1969"
    assert "concurs de infracțiuni" in r.text
    assert "2014" not in r.text


def test_a_later_strike_on_the_same_code_resolves_to_the_later_version(con):
    r = textul(con, "cod-penal", "art81", 2016)
    assert isinstance(r, Prevedere)
    assert r.act_gasit == "codul-penal-0-2014"


def test_a_strike_predating_every_collected_version_takes_the_earliest(con):
    """The code existed; only its republications postdate the ruling. The earliest collected
    version is the closest thing to what the Court read, and `cum` says it was an alias."""
    r = textul(con, "cod-penal", "art81", 1960)
    assert isinstance(r, Prevedere)
    assert r.act_gasit == "codul-penal-0-1969"
    assert r.cum == "alias-datat"


def test_a_flattened_alineat_falls_back_to_the_article_and_says_so(con):
    """The load-bearing refusal. `art81.alin4` cannot be cut out of text whose paragraph breaks
    were flattened away, so the article comes back — labelled, with the reason attached."""
    r = textul(con, "cod-penal", "art81.alin4", 1994)
    assert isinstance(r, Prevedere)
    assert r.granularitate == "articol"
    assert r.locator_gasit == "art81", "claimed to have cut an alineat that is not in the text"
    assert r.este_exacta is False
    assert "nu se ghicesc" in r.nota
    assert "art81.alin4" in r.nota and "art81" in r.nota


def test_the_returned_text_is_never_from_a_different_unit(con):
    """Falling back must widen the quotation, never move it. The article's text has to contain the
    alineat's, or the fallback would be quoting somewhere else entirely."""
    exact = textul(con, "lege-59-1993", "art5.alin3", 1994)
    articol = textul(con, "lege-59-1993", "art5", 1994)
    assert isinstance(exact, Prevedere) and isinstance(articol, Prevedere)
    assert exact.text.strip() in LEGE_MODERNA
    assert articol.granularitate == "exact", "art5 itself is an exact hit, not a fallback"


def test_an_act_outside_the_corpus_is_reported_not_guessed(con):
    r = textul(con, "lege-999-1899", "art1", 1994)
    assert isinstance(r, Neregasita)
    assert r.motiv == "act-negasit"
    assert "nu este în corpus" in r.explicatie


def test_an_article_the_act_does_not_contain_is_reported(con):
    """Renumbering after republication is the usual cause, and the row must say so rather than
    return the nearest article."""
    r = textul(con, "lege-59-1993", "art404", 1994)
    assert isinstance(r, Neregasita)
    assert r.motiv == "articol-negasit"


def test_a_nonsense_locator_is_rejected_before_any_lookup(con):
    r = textul(con, "lege-59-1993", "capitolul-II", 1994)
    assert isinstance(r, Neregasita)
    assert r.motiv == "locator-nevalid"


def test_taie_stops_at_the_depth_the_text_actually_has():
    """The cutting rule on its own: descend while the tree goes, stop, and report where it got."""
    arbore = parseaza_text(LEGE_MODERNA)
    assert taie(arbore, "art5.alin3")[1:] == ("art5.alin3", "exact")
    assert taie(arbore, "art5.alin3.litz")[1:] == ("art5.alin3", "articol")
    assert taie(arbore, "art404")[0] is None


def test_coverage_is_recomputed_rather_than_quoted(con, tmp_path):
    """Every number in this module's docstring moves as the collection grows. A report that leans
    on this text has to be able to print what it could and could not quote."""
    cale = str(tmp_path / "corpus.db")
    with depozit.deschide(cale) as c:
        c.execute(
            "INSERT INTO lovituri (id_portal, ord, cheie_act, publicat, definitiva, act, locator,"
            " fel, text) VALUES (?,?,?,?,?,?,?,?,?)",
            ("d1", 1, "decizie-9-1994", "1994-11-25", 1, "lege-59-1993", "art5.alin3", "n", "x"),
        )
        c.execute(
            "INSERT INTO lovituri (id_portal, ord, cheie_act, publicat, definitiva, act, locator,"
            " fel, text) VALUES (?,?,?,?,?,?,?,?,?)",
            ("d2", 1, "decizie-9-1994", "1994-11-25", 1, "cod-penal", "art81.alin4", "n", "x"),
        )
    r = acoperire(cale, log=lambda *_: None)
    assert r["total"] == 2
    assert r["exact"] == 1
    assert r["articol"] == 1
    assert r["citabile"] == 2
    assert r["procent_citabile"] == 100
