"""Tests for the consolidation surface — the layer the product sits on.

It reads committed local pages (the fixtures), so these run offline and are deterministic. What is
checked is the honest behaviour: touched provisions come back consolidated where the engine could
apply the change and refused where it could not, and the as-of date correctly hides a later change.
"""

from __future__ import annotations

from datetime import date

from scripts.consolidat import acte_disponibile, consolideaza_local, modificari_pentru
from scripts.server import _consolidare_semnale


def test_only_locally_available_acts_are_offered():
    ids = {a["act_id"] for a in acte_disponibile()}
    assert "lege-98-2016" in ids
    assert all(a["amendatoare"] >= 1 for a in acte_disponibile())


def test_a_touched_provision_comes_back_consolidated_with_attribution():
    _, rez = consolideaza_local("lege-98-2016", la_data=date(2023, 1, 1))
    r = rez["art187.alin8.lita"]
    assert r.complet and not r.abrogat
    assert [(s.act, s.fel) for s in r.schimbari] == [("lege-208-2022", "modifica")]
    # the change is dated by the amending act's own entry into force, not the viewing date
    assert r.schimbari[0].data == date(2022, 7, 12)


def test_an_unsupported_change_is_refused_not_spliced():
    """208/2022 introduces new provisions too; `introduce` is out of this slice, so those come back
    neconsolidate with a named reason rather than silently applied."""
    _, rez = consolideaza_local("lege-98-2016", la_data=date(2023, 1, 1))
    refuzate = [r for r in rez.values() if not r.complet]
    assert refuzate
    assert any("introduce" in lim for r in refuzate for lim in r.limitari)


def test_the_as_of_date_hides_a_later_change():
    """Consolidated as of before Legea 208/2022, the same provision carries none of its changes and
    is itself consolidated — the date is not decoration, it decides the answer."""
    _, rez = consolideaza_local("lege-98-2016", la_data=date(2020, 1, 1))
    r = rez["art187.alin8.lita"]
    assert r.complet and r.schimbari == ()


def test_the_summary_counts_add_up():
    _, rez = consolideaza_local("lege-98-2016", la_data=date(2023, 1, 1))
    complet = sum(1 for r in rez.values() if r.complet)
    refuzat = sum(1 for r in rez.values() if not r.complet)
    assert complet + refuzat == len(rez)
    assert complet >= 1 and refuzat >= 1


def test_modificari_pentru_maps_touched_provisions_and_is_empty_off_catalog():
    m = modificari_pentru("lege-98-2016", date(2023, 1, 1))
    assert "art187.alin8.lita" in m and m["art187.alin8.lita"].schimbari
    assert modificari_pentru("lege-999-9999") == {}


def test_lint_flags_a_citation_to_a_since_amended_provision():
    """The linter's consolidated-text pass: citing art. 187, whose alineate 208/2022 rewrote, is
    told so and pointed at the current text."""
    sig = _consolidare_semnale(
        "La articolul 187 din Legea nr. 98/2016 privind achizițiile publice, "
        "alineatul (8) se aplică."
    )
    assert sig and sig[0]["act_id"] == "lege-98-2016" and sig[0]["locator"] == "art187"
    assert "lege-208-2022" in sig[0]["prin"]
    assert any(u.startswith("art187") for u in sig[0]["unitati"])


def test_lint_is_silent_on_an_unchanged_provision():
    assert _consolidare_semnale("Articolul 200 din Legea nr. 98/2016 rămâne aplicabil.") == []


def test_lint_is_silent_when_the_act_cannot_be_consolidated_locally():
    assert _consolidare_semnale("Articolul 5 din Legea nr. 227/2015 se aplică.") == []
