"""Tests for grouping the corpus by who issued it.

By issuer and not by subject, and the reason is worth keeping in front of whoever reads this next:
a portal page carries its type, number, year, issuer and text, and no classification of any kind.
A subject grouping would have to be invented and then shown as though it had been read. The issuer
is on every one of the 205 321 documents.
"""

from __future__ import annotations

from pathlib import Path

from scripts import curatare, depozit, domenii


def _act(con, id_portal, tip, numar, an, emitent, titlu="T", publicat=None):
    con.execute(
        "INSERT INTO acte (id, cheie_citare, tip, numar, an, titlu, emitent, publicat,"
        " id_portal, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            f"{tip}-{numar}-{an}-{id_portal}",
            f"{tip}-{numar}-{an}",
            tip,
            numar,
            an,
            titlu,
            emitent,
            publicat,
            id_portal,
            "x",
        ),
    )


def _magazin(tmp_path: Path) -> Path:
    cale = tmp_path / "corpus.db"
    with depozit.deschide(cale) as con:
        _act(con, "1", "ordin", "1", 2020, "Ministerul Sănătății", publicat="2020-01-01")
        _act(con, "2", "ordin", "2", 2021, "Ministerul Sănătății", publicat="2021-01-01")
        _act(con, "3", "hg", "5", 2019, "Ministerul Sănătății", publicat="2019-01-01")
        _act(con, "4", "lege", "9", 2022, "Parlamentul", publicat="2022-01-01")
        con.commit()
    return cale


def test_a_body_is_listed_with_what_it_issues_and_the_years_it_spans(tmp_path):
    """The instrument matters as much as the count: a ministry issuing `ordin` is administering,
    Parliament issuing `lege` is legislating, and both are read rather than inferred."""
    with depozit.deschide(_magazin(tmp_path), readonly=True) as con:
        lista = domenii.emitenti(con)
    sanatate = next(e for e in lista if e.nume == "Ministerul Sănătății")
    assert sanatate.acte == 3
    assert sanatate.tipuri == (("ordin", 2), ("hg", 1))
    assert (sanatate.de_la, sanatate.pana_la) == ("2019", "2021")


def test_the_busiest_body_comes_first(tmp_path):
    with depozit.deschide(_magazin(tmp_path), readonly=True) as con:
        assert [e.nume for e in domenii.emitenti(con)][0] == "Ministerul Sănătății"


def test_one_bodys_acts_come_back_newest_first_and_can_be_narrowed_by_instrument(tmp_path):
    with depozit.deschide(_magazin(tmp_path), readonly=True) as con:
        toate = domenii.acte_ale(con, "Ministerul Sănătății")
        assert [a["an"] for a in toate] == [2021, 2020, 2019]
        doar_ordine = domenii.acte_ale(con, "Ministerul Sănătății", tip="ordin")
        assert [a["numar"] for a in doar_ordine] == ["2", "1"]


def test_every_listed_act_says_what_a_reader_would_have_to_cite(tmp_path):
    """An act that took a qualified id because a namesake holds the bare key is still cited by the
    bare one, and a list that showed only the id would show something nobody can look up."""
    with depozit.deschide(_magazin(tmp_path), readonly=True) as con:
        (unul,) = domenii.acte_ale(con, "Parlamentul")
    assert unul["act_id"] == "lege-9-2022-4"
    assert unul["cheie_citare"] == "lege-9-2022"


def test_a_store_with_nothing_collected_says_so_rather_than_failing(tmp_path):
    from scripts.servicii import Stare, _domenii

    cale = tmp_path / "gol.db"
    with depozit.deschide(cale):
        pass
    stare = Stare(corpus=str(cale), initiative=str(cale), graf=str(cale))
    assert _domenii({}, stare) == {"emitenti": []}


# --- numele emitentului, pe care serviciul nu-l poate scrie -----------------------------------


def test_the_lost_letters_are_taken_from_the_page_not_guessed():
    """The API encodes its responses in a charset with no comma-below letters and emits a literal
    `?` for each. 113 910 documents — 55% of the corpus — carry an issuer damaged that way."""
    assert (
        curatare.repara_emitent("Ministerul Sănătă?ii", "MINISTERUL SĂNĂTĂȚII")
        == "Ministerul Sănătății"
    )
    assert (
        curatare.repara_emitent("Pre?edintele României", "PREȘEDINTELE ROMÂNIEI")
        == "Președintele României"
    )


def test_the_page_may_spell_the_rest_of_the_name_differently_and_it_is_not_rewritten():
    """`AGENŢIA NAŢIONALA DE PRIVATIZARE` on the page, `Agenția Națională de Privatizare` from the
    service: upper case, and missing a diacritic of its own. Only the `?` positions are taken."""
    assert (
        curatare.repara_emitent(
            "Agen?ia Na?ională de Privatizare", "AGENȚIA NAȚIONALA DE PRIVATIZARE"
        )
        == "Agenția Națională de Privatizare"
    )


def test_a_page_that_names_a_different_body_repairs_nothing():
    """Half a repair is worse than none. `Agenția Națională a Funcționarilor Publici` publishes on
    a page headed `MINISTERUL ADMINISTRAȚIEI ȘI INTERNELOR-...`."""
    assert (
        curatare.repara_emitent(
            "Agen?ia Na?ională a Func?ionarilor Publici", "MINISTERUL ADMINISTRAȚIEI ȘI INTERNELOR"
        )
        is None
    )


def test_a_name_with_no_damage_is_returned_untouched():
    assert curatare.repara_emitent("Parlamentul", "PARLAMENTUL") == "Parlamentul"
