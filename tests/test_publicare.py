"""Tests for reading the Monitorul Oficial line out of an act's own text.

The date this yields is the one article 147 (1) counts from, and the one `acte.publicat` claimed
to hold while actually holding a copy of the in-force date — identical in all 63 933 rows.

The load-bearing test is `test_the_designation_line_is_not_mistaken_for_publication`. Every act
opens with `DECIZIE nr. 1 din 7 septembrie 1993`, which matches a bare `nr. N din DD month YYYY`
pattern perfectly and is the date the act was *pronounced*, not published. A parser that is not
anchored on `MONITORUL OFICIAL` reads that one, silently, and every deadline computed from it is
off by weeks.
"""

from __future__ import annotations

from datetime import date

from scripts.publicare import publicare

# decizie-101-1996, as the portal serves it: pronounced 1995, published 1996.
D101 = (
    "DECIZIE Nr. 101*) din 25 octombrie 1995 EMITENT CURTEA CONSTITUȚIONALĂ "
    "Publicat în MONITORUL OFICIAL NR. 9 din 17 ianuarie 1996 "
    "Notă ... Pe rol soluționarea excepției de neconstituționalitate"
)


def test_the_monitor_number_and_date_are_read():
    p = publicare(D101)
    assert p is not None
    assert p.monitor == 9
    assert p.data == date(1996, 1, 17)


def test_the_designation_line_is_not_mistaken_for_publication():
    # `nr. 101 din 25 octombrie 1995` appears first and matches an unanchored pattern.
    p = publicare(D101)
    assert p.data != date(1995, 10, 25), "read the pronouncement date instead of publication"


def test_the_partea_is_kept_when_the_text_gives_it():
    p = publicare(
        "LEGE nr. 98 din 19 mai 2016 Publicată în MONITORUL OFICIAL AL ROMÂNIEI, PARTEA I, "
        "nr. 390 din 23 mai 2016"
    )
    assert p.monitor == 390
    assert p.data == date(2016, 5, 23)
    assert p.partea == "I"


def test_lowercase_and_missing_diacritics_still_read():
    # 1990s portal records are frequently without diacritics and inconsistently cased.
    p = publicare(
        "DECIZIE nr. 1 din 7 septembrie 1993 "
        "Publicat in Monitorul Oficial nr. 232 din 27 septembrie 1993"
    )
    assert p.monitor == 232
    assert p.data == date(1993, 9, 27)


def test_an_act_with_no_monitor_line_returns_none():
    # 22% of collected documents have no readable line. None, so the caller stores NULL rather
    # than a plausible substitute — which is how `publicat` came to be a copy of `vigoare`.
    assert publicare("HOTĂRÎRE nr. 2 din 31 august 1992 privind o contestație electorală") is None


def test_a_citation_of_another_act_deep_in_the_body_is_not_read():
    # The reasoning of a decision quotes other acts and their monitors constantly. Only the
    # header is trusted, so a citation five paragraphs down cannot become this act's date.
    text = (
        "DECIZIE nr. 5 din 3 martie 1999 EMITENT CURTEA CONSTITUȚIONALĂ "
        + ("text de motivare. " * 80)
        + "Legea nr. 50/1991, publicată în Monitorul Oficial nr. 3 din 13 ianuarie 1991"
    )
    assert publicare(text) is None


def test_the_span_it_was_read_from_is_carried():
    p = publicare(D101)
    assert "MONITORUL OFICIAL" in p.text.upper()


def test_a_republication_is_flagged_not_flattened():
    """A republication is a different event from first publication, decades later at times."""
    p = publicare(
        "LEGE nr. 7 din 13 martie 1996 a cadastrului și a publicității imobiliare "
        "republicată în MONITORUL OFICIAL nr. 720 din 24 septembrie 2015"
    )
    assert p.data == date(2015, 9, 24)
    assert p.republicare is True


def test_an_ordinary_publication_is_not_flagged_as_republication():
    assert publicare(D101).republicare is False
