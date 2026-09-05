"""Tests for the initiative target index.

The index answers one question — which pending bills touch a given act — and that is what the
tests assert: an initiative's targets are extracted and indexed, the reverse lookup finds it, and
a dead bill is left out of the live answer.
"""

from __future__ import annotations

from pathlib import Path

from scripts import depozit
from scripts.cdep import Initiativa
from scripts.imbogateste import imbogateste, initiative_pe_act


def _db(tmp_path: Path, *inis) -> Path:
    db = tmp_path / "initiative.db"
    with depozit.deschide(db) as con:
        for i in inis:
            depozit.scrie_initiativa(con, i)
    return db


def _ini(plx, titlu, obiect, stadiu="pe ordinea de zi"):
    return Initiativa(
        plx_id=plx,
        cam=2,
        idp=plx,
        senat_id=None,
        tip="propunere legislativa",
        titlu=titlu,
        obiect=obiect,
        urgenta=False,
        stadiu=stadiu,
        camera_decizionala="Camera Deputaților",
        data_inreg="2024-01-01",
        sursa_url="",
    )


def test_targets_are_extracted_and_reverse_looked_up(tmp_path):
    db = _db(
        tmp_path,
        _ini(
            "plx-1-2024",
            "Lege pentru modificarea Legii nr. 227/2015",
            "modificarea Codului fiscal, Legea nr. 227/2015",
        ),
        _ini("plx-2-2024", "Lege despre altceva", "nimic legat"),
    )
    n = imbogateste(str(db))
    assert n >= 1
    with depozit.deschide(db, readonly=True) as con:
        hits = initiative_pe_act(con, "lege-227-2015")
    assert [h["plx_id"] for h in hits] == ["plx-1-2024"]


def test_a_dead_bill_is_left_out_of_the_live_answer(tmp_path):
    db = _db(
        tmp_path,
        _ini(
            "plx-dead-2024",
            "Lege pentru modificarea Legii nr. 227/2015",
            "modificarea Legii nr. 227/2015",
            stadiu="respins definitiv",
        ),
    )
    imbogateste(str(db))
    with depozit.deschide(db, readonly=True) as con:
        assert initiative_pe_act(con, "lege-227-2015") == []
        assert initiative_pe_act(con, "lege-227-2015", doar_vii=False)  # visible when asked


def test_rerunning_replaces_rather_than_doubles(tmp_path):
    db = _db(
        tmp_path,
        _ini("plx-1-2024", "modificarea Legii nr. 227/2015", "modificarea Legii nr. 227/2015"),
    )
    n1 = imbogateste(str(db))
    n2 = imbogateste(str(db))
    assert n1 == n2
