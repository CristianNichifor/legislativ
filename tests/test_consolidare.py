"""Tests for the consolidation engine.

The engine's whole value is in the refusal, so the rail is tested as hard as the happy path: an
operation the slice cannot apply must leave the provision original and blocking, never splice
partial. The happy path checks date ordering and the as-of-date cutoff, because a consolidated text
is only meaningful for a stated date.
"""

from __future__ import annotations

from datetime import date

from scripts.consolidare import Operatie, Rezultat, consolideaza


def test_a_clean_modification_replaces_the_text():
    r = consolideaza(
        "art7",
        "Art. 7. - Textul original.",
        [Operatie("modifica", "art7", date(2020, 1, 1), "lege-200-2020", "Art. 7. - Textul nou.")],
        la_data=date(2021, 1, 1),
    )
    assert r.complet and r.text == "Art. 7. - Textul nou."
    assert r.increderea == "derived"
    assert [s.act for s in r.schimbari] == ["lege-200-2020"]


def test_the_latest_dated_modification_wins():
    ops = [
        Operatie("modifica", "art7", date(2022, 1, 1), "lege-3-2022", "a treia"),
        Operatie("modifica", "art7", date(2020, 1, 1), "lege-1-2020", "prima"),
    ]
    r = consolideaza("art7", "original", ops, la_data=date(2023, 1, 1))
    assert r.text == "a treia"  # applied in date order, latest wins
    assert [s.act for s in r.schimbari] == ["lege-1-2020", "lege-3-2022"]


def test_a_change_after_the_as_of_date_is_not_applied():
    ops = [
        Operatie("modifica", "art7", date(2020, 1, 1), "lege-1-2020", "de la 2020"),
        Operatie("modifica", "art7", date(2025, 1, 1), "lege-9-2025", "de la 2025"),
    ]
    r = consolideaza("art7", "original", ops, la_data=date(2021, 1, 1))
    assert r.complet and r.text == "de la 2020"  # the 2025 change is future, correctly excluded
    assert [s.act for s in r.schimbari] == ["lege-1-2020"]


def test_an_abrogation_marks_the_provision_repealed():
    r = consolideaza(
        "art15",
        "Art. 15. - Textul.",
        [Operatie("abroga", "art15", date(2019, 6, 1), "lege-5-2019")],
        la_data=date(2020, 1, 1),
    )
    assert r.complet and r.abrogat
    assert r.schimbari[0].fel == "abroga"


def test_only_operations_for_this_locator_are_considered():
    ops = [
        Operatie("modifica", "art7", date(2020, 1, 1), "lege-1-2020", "pentru 7"),
        Operatie("modifica", "art8", date(2020, 1, 1), "lege-1-2020", "pentru 8"),
    ]
    r = consolideaza("art7", "original", ops, la_data=date(2021, 1, 1))
    assert r.text == "pentru 7"


def test_a_modification_without_a_payload_refuses_and_keeps_the_original():
    r = consolideaza(
        "art7",
        "Art. 7. - Textul original.",
        [Operatie("modifica", "art7", date(2020, 1, 1), "lege-200-2020", continut_nou=None)],
        la_data=date(2021, 1, 1),
    )
    assert not r.complet
    assert r.text == "Art. 7. - Textul original."  # untouched
    assert r.schimbari == ()
    assert any("nu citează textul nou" in lim for lim in r.limitari)
    assert any("lege-200-2020" in lim for lim in r.limitari)


def test_an_unsupported_operation_refuses_the_whole_provision():
    """Even mixed with a clean change: partial consolidation is not allowed."""
    ops = [
        Operatie("modifica", "art7", date(2020, 1, 1), "lege-1-2020", "text nou"),
        Operatie("suspenda", "art7", date(2021, 1, 1), "lege-2-2021", None),
    ]
    r = consolideaza("art7", "original", ops, la_data=date(2022, 1, 1))
    assert not r.complet and r.text == "original"
    assert any("suspenda" in lim and "lege-2-2021" in lim for lim in r.limitari)


def test_an_undated_change_cannot_be_placed_and_refuses():
    r = consolideaza(
        "art7",
        "original",
        [Operatie("modifica", "art7", None, "lege-1-2020", "text nou")],
        la_data=date(2022, 1, 1),
    )
    assert not r.complet
    assert any("nu are dată" in lim for lim in r.limitari)


def test_a_provision_with_no_operations_is_itself_consolidated():
    r = consolideaza("art7", "Art. 7. - Neatins.", [], la_data=date(2022, 1, 1))
    assert isinstance(r, Rezultat)
    assert r.complet and r.text == "Art. 7. - Neatins." and not r.abrogat and r.schimbari == ()


def test_completeaza_appends_the_payload():
    r = consolideaza(
        "art7",
        "Art. 7. - Textul original.",
        [Operatie("completeaza", "art7", date(2020, 1, 1), "lege-2-2020", "Se adaugă o teză.")],
        la_data=date(2022, 1, 1),
    )
    assert r.complet
    assert r.text == "Art. 7. - Textul original.\nSe adaugă o teză."
    assert r.schimbari[0].fel == "completeaza"


def test_completeaza_without_a_payload_refuses():
    r = consolideaza(
        "art7",
        "original",
        [Operatie("completeaza", "art7", date(2020, 1, 1), "lege-2-2020", None)],
        la_data=date(2022, 1, 1),
    )
    assert not r.complet and any("nu citează textul nou" in lim for lim in r.limitari)


def test_introduce_does_not_refuse_the_anchor():
    # an insertion after art. 7 leaves art. 7 itself untouched — it must not block its consolidation
    r = consolideaza(
        "art7",
        "Art. 7. - Ancora.",
        [Operatie("introduce", "art7", date(2020, 1, 1), "lege-3-2020", "Art. 7^1. - Nou.")],
        la_data=date(2022, 1, 1),
    )
    assert r.complet and r.text == "Art. 7. - Ancora." and r.schimbari == ()


def test_consolideaza_in_materialises_an_inserted_provision():
    from scripts.consolidare import consolideaza_in
    from scripts.parsare import ActParsat, Provizie
    from scripts.referinte import Act

    act = ActParsat(
        act=Act("lege", "98", 2016),
        titlu="L",
        provizii=(Provizie("art7", "Art. 7. - Ancora."),),
    )
    ops = [Operatie("introduce", "art7", date(2020, 1, 1), "lege-3-2020", "Art. 7^1. - Nou.")]
    rez = consolideaza_in(act, ops, la_data=date(2022, 1, 1))
    inserate = [r for r in rez.values() if r.schimbari and r.schimbari[0].fel == "introduce"]
    assert len(inserate) == 1
    assert inserate[0].text == "Art. 7^1. - Nou." and inserate[0].complet
    assert any("renumerotarea" in lim for lim in inserate[0].limitari)


# --- republication: the numbering boundary. A pre-republication operation named a locator under
# the old numbering, so the engine refuses to apply it to the renumbered tree rather than guess. ---


def test_a_pre_republication_amendment_refuses_the_provision():
    r = consolideaza(
        "art7",
        "Art. 7. - Textul original.",
        [Operatie("modifica", "art7", date(2018, 3, 1), "lege-1-2018", "Art. 7. - Textul nou.")],
        la_data=date(2023, 1, 1),
        republicat_din=date(2020, 1, 1),
    )
    assert not r.complet
    assert r.text == "Art. 7. - Textul original."  # original kept, never the pre-republicare splice
    assert any("anterior republicării" in lim for lim in r.limitari)


def test_an_amendment_on_or_after_republication_applies_normally():
    r = consolideaza(
        "art7",
        "Art. 7. - Textul original.",
        [Operatie("modifica", "art7", date(2021, 6, 1), "lege-9-2021", "Art. 7. - Textul nou.")],
        la_data=date(2023, 1, 1),
        republicat_din=date(2020, 1, 1),
    )
    assert r.complet and r.text == "Art. 7. - Textul nou."  # post-republicare numbering, safe


def test_a_provision_with_ops_both_sides_of_republication_refuses_whole():
    ops = [
        Operatie("modifica", "art7", date(2018, 1, 1), "lege-1-2018", "vechi"),
        Operatie("modifica", "art7", date(2021, 1, 1), "lege-9-2021", "nou"),
    ]
    r = consolideaza(
        "art7", "original", ops, la_data=date(2023, 1, 1), republicat_din=date(2020, 1, 1)
    )
    assert not r.complet and r.text == "original"  # one unsafe op refuses the whole provision


def test_without_a_republication_date_nothing_changes():
    # the rail is inert unless the act is actually republished — old behaviour is preserved
    r = consolideaza(
        "art7",
        "original",
        [Operatie("modifica", "art7", date(2018, 1, 1), "lege-1-2018", "nou")],
        la_data=date(2023, 1, 1),
    )
    assert r.complet and r.text == "nou"


def test_consolideaza_in_threads_the_acts_republication_date():
    from scripts.consolidare import consolideaza_in
    from scripts.parsare import ActParsat, Provizie
    from scripts.referinte import Act

    act = ActParsat(
        act=Act("lege", "98", 2016),
        titlu="L",
        provizii=(Provizie("art7", "Art. 7. - Ancora."),),
        republicat_din=date(2020, 1, 1),
    )
    ops = [Operatie("modifica", "art7", date(2018, 5, 1), "lege-1-2018", "Art. 7. - Nou.")]
    rez = consolideaza_in(act, ops, la_data=date(2023, 1, 1))
    assert not rez["art7"].complet
    assert any("anterior republicării" in lim for lim in rez["art7"].limitari)
