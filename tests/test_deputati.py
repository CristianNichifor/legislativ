"""Tests for reading a deputy's record off the collected signatures.

The identity is the whole story here, and it took three attempts to get right against real data:

- keyed on `idm` alone, 349 ids covered 1 044 people;
- adding the legislature, 282 pairs still covered more than one person;
- with the chamber as well, no key covers two names.

`idm=56, leg=2020` is Buzoianu Diana-Anda in the Chamber and Ghica Cristian in the Senate. The
first profile built on the id alone reported one deputy sitting in AUR, PNL and USR at once.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import depozit, deputati


def _magazin(tmp_path: Path) -> sqlite3.Connection:
    """Two people who share an id in one legislature, and a bill each, plus one they co-signed."""
    cale = tmp_path / "initiative.db"
    with depozit.deschide(cale) as con:
        for plx, titlu, stadiu, data in (
            ("plx-1-2021", "Lege despre A", "adoptată", "2021-01-01"),
            ("plx-2-2021", "Lege despre B", "respinsă", "2021-02-01"),
            ("plx-3-2021", "Lege despre C", "în comisie", "2021-03-01"),
        ):
            con.execute(
                "INSERT INTO initiative (plx_id, cam, idp, tip, titlu, obiect, urgenta, stadiu,"
                " data_inreg, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (plx, 2, "0", "propunere", titlu, "", 0, stadiu, data, "2021-01-01"),
            )
        semnaturi = [
            # same idm, same legislature, different chamber — two different people
            ("plx-1-2021", "56", "2020", "Camera Deputaților", "Buzoianu Diana-Anda", "USR"),
            ("plx-1-2021", "77", "2020", "Camera Deputaților", "Altcineva Ion", "PNL"),
            ("plx-2-2021", "56", "2020", "Senat", "Ghica Cristian", "USR"),
            ("plx-3-2021", "56", "2020", "Camera Deputaților", "Buzoianu Diana-Anda", "USR"),
        ]
        for plx, idm, leg, camera, nume, grup in semnaturi:
            con.execute(
                "INSERT INTO initiativa_initiator (plx_id, idm, leg, nume, grup, camera)"
                " VALUES (?,?,?,?,?,?)",
                (plx, idm, leg, nume, grup, camera),
            )
        for plx, rezultat in (("plx-1-2021", "adoptat"), ("plx-2-2021", "respins")):
            con.execute(
                "INSERT INTO initiativa_vot (plx_id, data, camera, intrebare, pentru, contra,"
                " abtineri, rezultat) VALUES (?,?,?,?,?,?,?,?)",
                (plx, "2021-06-01", "Camera Deputaților", None, 200, 10, 0, rezultat),
            )
        con.commit()
    return sqlite3.connect(f"file:{cale}?mode=ro", uri=True)


def test_two_people_sharing_an_id_in_one_legislature_stay_apart(tmp_path):
    """The bug that shipped in #61 and was caught by a profile looking wrong, not by a test.
    `idm=56, leg=2020` is a deputy and a senator, and merging them put one person in two parties."""
    con = _magazin(tmp_path)
    try:
        gasiti = deputati.cauta(con, "a")
        chei = {(s.idm, s.leg, s.camera): s.nume for s in gasiti}
    finally:
        con.close()
    assert chei[("56", "2020", "Camera Deputaților")] == "Buzoianu Diana-Anda"
    assert chei[("56", "2020", "Senat")] == "Ghica Cristian"
    for s in gasiti:
        assert len(s.grupuri) <= 1, f"{s.nume} apare în mai multe grupuri: {s.grupuri}"


def test_a_search_finds_by_name_folded(tmp_path):
    """The Fișe spell the same person `Şovăială` and `Șovăială`, and a reader types neither."""
    con = _magazin(tmp_path)
    try:
        assert [s.nume for s in deputati.cauta(con, "BUZOIANU")] == ["Buzoianu Diana-Anda"]
        assert deputati.cauta(con, "") == []
    finally:
        con.close()


def test_a_pending_bill_is_not_a_defeat(tmp_path):
    """Only 1 729 of 4 052 collected initiatives have a division on their Fișa. A success rate over
    "adopted / everything" would quietly convert every bill still moving into a loss."""
    con = _magazin(tmp_path)
    try:
        s = deputati.soarta(con, "56", "2020", "Camera Deputaților")
    finally:
        con.close()
    assert (s.adoptate, s.respinse, s.nedecise) == (1, 0, 1)
    assert s.cu_vot == 1


def test_the_other_persons_bill_is_not_counted(tmp_path):
    con = _magazin(tmp_path)
    try:
        senator = deputati.soarta(con, "56", "2020", "Senat")
    finally:
        con.close()
    assert (senator.adoptate, senator.respinse, senator.nedecise) == (0, 1, 0)


def test_every_bill_says_how_many_signed_it(tmp_path):
    """A bill carrying sixty signatures says something different from one carrying two, and a list
    without the count invites reading every row as this person's own initiative."""
    con = _magazin(tmp_path)
    try:
        lista = deputati.initiative(con, "56", "2020", "Camera Deputaților")
    finally:
        con.close()
    pe_id = {x["plx_id"]: x for x in lista}
    assert pe_id["plx-1-2021"]["semnatari"] == 2
    assert pe_id["plx-3-2021"]["semnatari"] == 1
    assert pe_id["plx-1-2021"]["rezultat"] == "adoptat"


def test_groups_count_people_not_ids(tmp_path):
    """Counting distinct ids reports one member where a group has had several sit under the same
    number — across legislatures, or a deputy and a senator in the same one."""
    con = _magazin(tmp_path)
    try:
        pe_grup = {g["grup"]: g for g in deputati.grupuri(con)}
    finally:
        con.close()
    assert pe_grup["USR"]["membri"] == 2, "deputatul și senatorul cu același idm au fost contopiți"
    assert pe_grup["USR"]["semnaturi"] == 3
    assert pe_grup["USR"]["initiative"] == 3


def test_signatures_and_initiatives_are_different_numbers(tmp_path):
    """Twenty members of one group signing one bill is twenty signatures and one initiative.
    Reporting only the first makes a group look busy for co-signing."""
    con = _magazin(tmp_path)
    try:
        pnl = next(g for g in deputati.grupuri(con) if g["grup"] == "PNL")
    finally:
        con.close()
    assert pnl["semnaturi"] == 1 and pnl["initiative"] == 1
