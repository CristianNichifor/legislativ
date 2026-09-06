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
