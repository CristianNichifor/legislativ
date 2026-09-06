"""The linter's unmet-obligations pass: the prebuilt gap report, filtered to the draft's acts."""

from __future__ import annotations

from types import SimpleNamespace

from scripts.servicii import _obligatii_neindeplinite

_VID = [
    {"act_id": "lege-98-2016", "instrument": "hg", "text": "ANAP elaborează norme metodologice."},
    {"act_id": "lege-1-2011", "instrument": "hg", "text": "Guvernul aprobă normele."},
]


def test_filters_the_report_to_the_acts_the_draft_touches():
    draft = "La articolul 233 din Legea nr. 98/2016 privind achizițiile, alineatul (1) se modifică."
    r = _obligatii_neindeplinite(draft, SimpleNamespace(vid=_VID))
    assert [v["act_id"] for v in r] == ["lege-98-2016"]


def test_a_draft_touching_nothing_in_the_report_is_silent():
    draft = "La articolul 5 din Legea nr. 500/2002 privind finanțele publice, se modifică."
    assert _obligatii_neindeplinite(draft, SimpleNamespace(vid=_VID)) == []


def test_no_report_shipped_is_silent():
    draft = "La articolul 233 din Legea nr. 98/2016, alineatul (1) se modifică."
    assert _obligatii_neindeplinite(draft, SimpleNamespace(vid=[])) == []
