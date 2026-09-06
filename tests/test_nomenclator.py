"""The named acts: from what a citation calls them to what the corpus stored.

`referinte` resolves the Constitution and the codes to a bare name; the collector keys them from
their own titles. The two wrote different ids for the same law, so a quarter of everything the
corpus cites looked absent — the Constitution among it, with 95 768 citations and eleven stored
versions, none reachable.
"""

from __future__ import annotations

from datetime import date

from scripts.nomenclator import este_nume, rezolva, versiuni

CORPUS = {
    "constitutie-0-1866",
    "constitutie-0-1991",
    "constitutie-0-2003",
    "codul-penal-0-1969",
    "codul-penal-0-2014",
    "codul-de-procedura-civila-0-2015",
    "lege-98-2016",  # an ordinary act: never a name
}


def test_a_name_resolves_to_the_most_recent_version_by_default():
    """What a citation written today means."""
    assert rezolva("constitutie", CORPUS) == "constitutie-0-2003"
    assert rezolva("cod-penal", CORPUS) == "codul-penal-0-2014"


def test_a_date_selects_the_version_in_force_then():
    assert rezolva("constitutie", CORPUS, date(1995, 1, 1)) == "constitutie-0-1991"
    assert rezolva("constitutie", CORPUS, date(2010, 1, 1)) == "constitutie-0-2003"
    assert rezolva("cod-penal", CORPUS, date(2000, 1, 1)) == "codul-penal-0-1969"


def test_a_date_before_every_version_resolves_to_nothing():
    """A draft from 1850 did not cite the 1866 Constitution, and saying it did is an invention."""
    assert rezolva("constitutie", CORPUS, date(1850, 1, 1)) is None


def test_a_name_the_corpus_does_not_hold_resolves_to_nothing():
    assert rezolva("cod-administrativ", CORPUS) is None
    assert rezolva("cod-fiscal", set()) is None


def test_the_prefixes_are_not_guessable_from_each_other():
    """The portal says COD PENAL but CODUL DE PROCEDURĂ PENALĂ — a rule deriving one from the
    other would be wrong for half of them, which is why both halves are written out."""
    assert versiuni("cod-penal", CORPUS) == [
        (1969, "codul-penal-0-1969"),
        (2014, "codul-penal-0-2014"),
    ]
    assert versiuni("cod-procedura-civila", CORPUS) == [(2015, "codul-de-procedura-civila-0-2015")]


def test_only_named_acts_are_names():
    assert este_nume("constitutie") and este_nume("cod-penal")
    assert not este_nume("lege-98-2016")
    assert not este_nume("constitutie-0-2003")  # already resolved


# --- acts filed under the year they were republished -------------------------------------------


def _corpus_cu(tmp_path, acte, documente):
    from scripts import depozit

    cale = tmp_path / "c.db"
    with depozit.deschide(str(cale)) as con:
        con.executemany(
            "INSERT INTO acte (id, tip, numar, an, titlu, citit_la)"
            " VALUES (?,?,?,?,?, '2020-01-01')",
            acte,
        )
        con.executemany(
            "INSERT INTO documente (id_portal, cheie_act, tip, numar, an, titlu, text, adus_la)"
            " VALUES (?,?,?,?,?,?, 'x', '2020-01-01')",
            documente,
        )
        con.commit()
    return cale


def test_an_act_filed_under_its_republication_year_gets_an_alias(tmp_path):
    """`LEGE nr. 500 din 11 iulie 2002` filed as 2003: every citation says 500/2002."""
    from scripts import depozit
    from scripts.nomenclator import alias_an

    cale = _corpus_cu(
        tmp_path,
        acte=[("lege-500-2003", "lege", "500", 2003, "LEGE nr. 500 din 11 iulie 2002 privind X")],
        documente=[
            ("p1", "lege-500-2003", "lege", "500", 2003, "LEGE nr. 500 din 11 iulie 2002 privind X")
        ],
    )
    with depozit.deschide(str(cale), readonly=True) as con:
        assert alias_an(con) == {"lege-500-2002": "lege-500-2003"}


def test_an_alias_is_dropped_when_the_stored_act_does_not_confirm_the_year(tmp_path):
    """`acte` is a citation view where the last writer wins, and 53 242 documents share a key.

    So one `cheie_act` is not one act: the row that survived may be an unrelated law. Before this
    check, 2 566 of 10 669 aliases pointed at an act from a different year — `lege-303-2004`
    landing on a 2005 ratification law rather than the statute of judges.
    """
    from scripts import depozit
    from scripts.nomenclator import alias_an

    cale = _corpus_cu(
        tmp_path,
        # the surviving row is the 2005 law, not the 2004 one the document claimed
        acte=[
            ("lege-303-2005", "lege", "303", 2005, "LEGE nr. 303 din 25 octombrie 2005 pentru Y")
        ],
        documente=[
            ("p1", "lege-303-2005", "lege", "303", 2005, "LEGE nr. 303 din 28 iunie 2004 privind X")
        ],
    )
    with depozit.deschide(str(cale), readonly=True) as con:
        assert alias_an(con) == {}  # refuses rather than pointing at the wrong act


def test_no_alias_when_the_corpus_already_holds_that_year(tmp_path):
    from scripts import depozit
    from scripts.nomenclator import alias_an

    cale = _corpus_cu(
        tmp_path,
        acte=[
            ("lege-7-2001", "lege", "7", 2001, "LEGE nr. 7 din 3 mai 2000 privind X"),
            ("lege-7-2000", "lege", "7", 2000, "LEGE nr. 7 din 3 mai 2000 privind X"),
        ],
        documente=[("p1", "lege-7-2001", "lege", "7", 2001, "LEGE nr. 7 din 3 mai 2000 privind X")],
    )
    with depozit.deschide(str(cale), readonly=True) as con:
        assert "lege-7-2000" not in alias_an(con)
