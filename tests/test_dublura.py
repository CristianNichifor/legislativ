"""Tests for the duplicate-check.

The engine's promise is a specific one: a shared amendment target beats any amount of shared
prose, and a dead bill is never offered as a live duplicate. Both are asserted against a small
initiative database built in the test, so nothing depends on what the collector has reached.
"""

from __future__ import annotations

from pathlib import Path

from scripts import depozit
from scripts.cdep import Initiativa
from scripts.dublura import dubluri, tinte


def _ini(plx, titlu, obiect, stadiu="pe ordinea de zi", senat=None):
    return Initiativa(
        plx_id=plx,
        cam=2,
        idp=plx,
        senat_id=senat,
        tip="propunere legislativa",
        titlu=titlu,
        obiect=obiect,
        urgenta=False,
        stadiu=stadiu,
        camera_decizionala="Camera Deputaților",
        data_inreg="2024-01-01",
        sursa_url="",
    )


def _db(tmp_path: Path, *inis) -> Path:
    db = tmp_path / "i.db"
    with depozit.deschide(db) as con:
        for i in inis:
            depozit.scrie_initiativa(con, i)
    return db


def test_targets_are_read_from_a_draft():
    t = tinte("Lege pentru modificarea articolului 7 din Legea nr. 98/2016.")
    assert "lege-98-2016 art7" in t


def test_a_shared_target_is_found_and_explained(tmp_path):
    db = _db(
        tmp_path,
        _ini(
            "plx-1-2024",
            "Lege pentru modificarea Legii nr. 98/2016",
            "modificarea articolului 7 din Legea nr. 98/2016",
            senat="L10/2024",
        ),
        _ini("plx-2-2024", "Lege privind cizmele de cauciuc", "cu totul altceva despre pescuit"),
    )
    draft = "Propunere pentru modificarea art. 7 din Legea nr. 98/2016 privind achizițiile."
    with depozit.deschide(db, readonly=True) as con:
        hits = dubluri(draft, con)
    assert [h.plx_id for h in hits] == ["plx-1-2024"]
    assert "lege-98-2016 art7" in hits[0].tinte_comune
    assert hits[0].senat_id == "L10/2024"
    assert hits[0].increderea == "verbatim"


def test_a_shared_target_outranks_a_wording_match(tmp_path):
    db = _db(
        tmp_path,
        _ini(
            "plx-word-2024",
            "Lege privind achizițiile publice electronice transparente",
            "achiziții publice transparente electronice licitații",
        ),
        _ini(
            "plx-tgt-2024", "Lege de modificare", "modificarea articolului 7 din Legea nr. 98/2016"
        ),
    )
    draft = "modificarea art. 7 din Legea nr. 98/2016 privind achizițiile publice electronice"
    with depozit.deschide(db, readonly=True) as con:
        hits = dubluri(draft, con)
    assert hits[0].plx_id == "plx-tgt-2024"  # target match first, whatever the wording overlap


def test_a_dead_bill_is_not_offered_as_a_live_duplicate(tmp_path):
    db = _db(
        tmp_path,
        _ini(
            "plx-dead-2024",
            "Lege pentru modificarea Legii nr. 98/2016",
            "modificarea articolului 7 din Legea nr. 98/2016",
            stadiu="respins definitiv de Camera Deputaților",
        ),
    )
    draft = "modificarea art. 7 din Legea nr. 98/2016"
    with depozit.deschide(db, readonly=True) as con:
        assert dubluri(draft, con) == []  # filtered by default
        assert dubluri(draft, con, doar_vii=False)  # visible when asked


def test_nothing_matches_an_unrelated_draft(tmp_path):
    db = _db(
        tmp_path, _ini("plx-1-2024", "Lege despre apicultură", "sprijinul crescătorilor de albine")
    )
    with depozit.deschide(db, readonly=True) as con:
        assert dubluri("modificarea Codului fiscal privind TVA la software", con) == []
