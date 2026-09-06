"""Tests for extracting a decision's strikes once and keeping them.

The register spent 177 of its 178 seconds re-parsing all 20 006 decisions to find the ~530 that
strike anything, every run. The text does not change once collected, so neither does the answer.

The load-bearing test is `test_a_decision_that_strikes_nothing_is_not_re_read`: 97% of the case
law strikes nothing, so "has no rows" is the normal case and cannot be allowed to mean "not yet
examined" — that is the whole corpus re-read on every pass, which is the mistake `publicat IS
NULL` already made once.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.lovituri import extrage, incarca


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "corpus.db"


LOVESTE = (
    "DECIZIE nr. 9 din 25 noiembrie 1994 EMITENT CURTEA CONSTITUȚIONALĂ "
    "Publicat în MONITORUL OFICIAL nr. 326 din 25 noiembrie 1994 "
    "CURTEA În numele legii DECIDE: "
    "Admite excepția și constată că art. 5 alin. (7) din Legea nr. 59/1993 este "
    "neconstituțional. Definitivă și general obligatorie."
)
RESPINGE = (
    "DECIZIE nr. 10 din 25 noiembrie 1994 EMITENT CURTEA CONSTITUȚIONALĂ "
    "Publicat în MONITORUL OFICIAL nr. 327 din 26 noiembrie 1994 "
    "CURTEA În numele legii DECIDE: "
    "Respinge excepția de neconstituționalitate a art. 7 din Legea nr. 60/1993. "
    "Definitivă și general obligatorie."
)


def _decizie(numar: str, text: str, portal: str) -> Inregistrare:
    return Inregistrare(
        titlu=f"DECIZIE nr. {numar}/1994",
        tip_act="DECIZIE",
        numar=numar,
        an=1994,
        data_vigoare=date(1994, 11, 25),
        emitent="Curtea Constituțională",
        publicatie="MO",
        link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{portal}",
        text=text,
    )


def _scrie(db, *inregistrari):
    with depozit.deschide(db) as con:
        for r in inregistrari:
            depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))


def test_a_strike_is_extracted_once_and_read_back(db):
    _scrie(db, _decizie("9", LOVESTE, "900"))
    r = extrage(db, log=lambda *_: None)
    assert r["examinate"] == 1 and r["lovituri"] == 1

    lovituri = incarca(db)
    assert len(lovituri) == 1
    lov = lovituri[0]
    assert lov.decizie == "decizie-9-1994"
    assert lov.proviziune.act == "lege-59-1993"
    assert lov.proviziune.locator == "art5.alin7"
    assert lov.proviziune.fel == "neconstitutional"
    assert lov.definitiva is True
    assert lov.publicat == date(1994, 11, 25)


def test_a_decision_that_strikes_nothing_is_not_re_read(db):
    """97% of decisions strike nothing. If absence of rows meant "not yet examined", every pass
    would re-read the whole corpus — which is exactly what `publicat IS NULL` did before."""
    _scrie(db, _decizie("10", RESPINGE, "1000"))
    assert extrage(db, log=lambda *_: None)["examinate"] == 1
    assert extrage(db, log=lambda *_: None)["examinate"] == 0, "re-read a decision already examined"
    assert incarca(db) == []


def test_only_newly_arrived_decisions_are_examined(db):
    """The daily refresh must cost the decisions that arrived, not the corpus."""
    _scrie(db, _decizie("9", LOVESTE, "900"))
    extrage(db, log=lambda *_: None)
    _scrie(db, _decizie("10", RESPINGE, "1000"))
    r = extrage(db, log=lambda *_: None)
    assert r["examinate"] == 1, f"examined {r['examinate']} decisions instead of the new one"


def test_re_collecting_a_decision_replaces_its_strikes(db):
    """A document rewritten in place must not leave its old strikes behind."""
    _scrie(db, _decizie("9", LOVESTE, "900"))
    extrage(db, log=lambda *_: None)
    assert len(incarca(db)) == 1

    # same portal id, now a rejection
    _scrie(db, _decizie("9", RESPINGE.replace("nr. 10", "nr. 9"), "900"))
    extrage(db, log=lambda *_: None)
    assert incarca(db) == [], "stale strikes survived a re-collection"


def test_only_the_court_is_examined(db):
    """An ordinary law is not a decision, and reading one for a dispozitiv is wasted work."""
    lege = Inregistrare(
        titlu="LEGE nr. 1/1994",
        tip_act="LEGE",
        numar="1",
        an=1994,
        data_vigoare=None,
        emitent="Parlamentul",
        publicatie="MO",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/1",
        text="LEGE nr. 1 din 1994. Art. 1 se aplică de la publicare.",
    )
    _scrie(db, lege)
    assert extrage(db, log=lambda *_: None)["examinate"] == 0


def test_the_quotable_span_survives_the_round_trip(db):
    """Every finding carries the text it was read from; storing the strike must not lose it."""
    _scrie(db, _decizie("9", LOVESTE, "900"))
    extrage(db, log=lambda *_: None)
    (lov,) = incarca(db)
    assert "art. 5 alin. (7)" in lov.proviziune.text
