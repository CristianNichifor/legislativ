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


# --- o persoană, mai multe mandate ---------------------------------------------------------


def _mandate(tmp_path: Path) -> sqlite3.Connection:
    """The same person across two legislatures, under two different ids, plus a namesake risk."""
    cale = tmp_path / "initiative.db"
    with depozit.deschide(cale) as con:
        for plx, stadiu in (("plx-1-2021", "adoptată"), ("plx-2-2025", "adoptată")):
            con.execute(
                "INSERT INTO initiative (plx_id, cam, idp, tip, titlu, obiect, urgenta, stadiu,"
                " data_inreg, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (plx, 2, "0", "propunere", "T", "", 0, stadiu, "2021-01-01", "x"),
            )
        for plx, idm, leg, nume, grup in (
            # `idm` is not stable between legislatures: the same person is 56 then 48.
            ("plx-1-2021", "56", "2020", "Buzoianu Diana-Anda", "USR"),
            ("plx-2-2025", "48", "2024", "Buzoianu Diana-Anda", "USR"),
            ("plx-1-2021", "77", "2020", "Popescu Ion", "neafiliati"),
        ):
            con.execute(
                "INSERT INTO initiativa_initiator (plx_id, idm, leg, nume, grup, camera)"
                " VALUES (?,?,?,?,?,?)",
                (plx, idm, leg, nume, grup, "Camera Deputaților"),
            )
        # `soarta` counts recorded divisions, not the `stadiu` string — a bill without a vote is
        # not a bill that failed, which is the whole reason `nedecise` is its own column.
        for plx in ("plx-1-2021", "plx-2-2025"):
            con.execute(
                "INSERT INTO initiativa_vot (plx_id, data, camera, intrebare, pentru, contra,"
                " abtineri, rezultat) VALUES (?,?,?,?,?,?,?,?)",
                (plx, "2021-06-01", "Camera Deputaților", None, 200, 10, 0, "adoptat"),
            )
        con.commit()
    return sqlite3.connect(f"file:{cale}?mode=ro", uri=True)


def test_one_person_is_one_entry_with_a_term_each(tmp_path):
    """The search returned one row per *term*, so the same member appeared twice and neither row
    said so. `idm` cannot be the join: it is 56 in 2020 and 48 in 2024 for one person, and the
    Chamber publishes no id that is stable — the member page states the mandate history in prose
    and the photograph's filename is a name rendering written two different ways."""
    con = _mandate(tmp_path)
    try:
        (p,) = deputati.persoane(con, "buzoianu")
    finally:
        con.close()
    assert p.nume == "Buzoianu Diana-Anda"
    assert p.legislaturi == ("2024", "2020")
    assert [(m.leg, m.idm) for m in p.mandate] == [("2024", "48"), ("2020", "56")]


def test_no_number_is_summed_across_a_term(tmp_path):
    """The grouping is a name match and therefore a guess. Confining it to navigation is what makes
    it safe: every count stays attached to its own term, so two people wrongly merged would show
    two labelled terms rather than one wrong total."""
    con = _mandate(tmp_path)
    try:
        (p,) = deputati.persoane(con, "buzoianu")
        pe_leg = {m.leg: deputati.soarta(con, m.idm, m.leg, m.camera) for m in p.mandate}
    finally:
        con.close()
    assert pe_leg["2020"].adoptate == 1
    assert pe_leg["2024"].adoptate == 1
    assert all(m.initiative == 1 for m in p.mandate)


def test_a_group_can_be_read_for_one_parliament_at_a_time(tmp_path):
    """A group's record summed across parliaments it was differently composed in reads as one
    continuous record and is not."""
    con = _mandate(tmp_path)
    try:
        assert deputati.legislaturi(con) == ["2024", "2020"]
        toate = {g["grup"]: g for g in deputati.grupuri(con)}
        doar_2024 = {g["grup"]: g for g in deputati.grupuri(con, "2024")}
    finally:
        con.close()
    assert toate["USR"]["membri"] == 2, "cele două mandate sunt doi membri în total"
    assert doar_2024["USR"]["membri"] == 1
    assert "Neafiliați" not in doar_2024, "grupul din 2020 nu apare sub filtrul 2024"


def test_the_two_group_names_the_source_spells_badly_are_fixed(tmp_path):
    """`neafiliati` and `Minoritati` are written without capitals or diacritics at the source.
    Everything else in the column is an acronym — PSD, USR, UDMR, SOS RO — and must not be
    "corrected" into something the Chamber does not write, so this is a map of two names and not a
    title-casing rule applied to a column it would damage."""
    con = _mandate(tmp_path)
    try:
        nume = {g["grup"] for g in deputati.grupuri(con)}
    finally:
        con.close()
    assert "Neafiliați" in nume and "neafiliati" not in nume
    assert deputati.grup_afisat("Minoritati") == "Minorități"
    assert deputati.grup_afisat("SOS RO") == "SOS RO"
    assert deputati.grup_afisat("PSD") == "PSD"


def test_the_directory_lists_everyone_once_for_a_reader_with_no_name_to_type(tmp_path):
    """The search answers "how did this person vote"; the directory answers "who are they", which
    is the question of a reader who has not got a name — most readers. Grouped the same way as the
    search, so the two cannot describe the same person differently."""
    con = _mandate(tmp_path)
    try:
        toti = deputati.toti(con)
        doar_2024 = deputati.toti(con, leg="2024")
    finally:
        con.close()
    assert [p.nume for p in toti] == ["Buzoianu Diana-Anda", "Popescu Ion"]
    (buzoianu,) = [p for p in toti if p.nume.startswith("Buzoianu")]
    assert buzoianu.legislaturi == ("2024", "2020"), "cele două mandate sunt o singură persoană"
    assert [p.nume for p in doar_2024] == ["Buzoianu Diana-Anda"]


def test_the_directory_is_sorted_where_a_reader_looks(tmp_path):
    """`Șovăială` belongs under Ș. A byte comparison files it after Z, which is where nobody looks
    for it."""
    cale = tmp_path / "initiative.db"
    with depozit.deschide(cale) as con:
        for i, nume in enumerate(("Zamfir Ion", "Șovăială Petru", "Abrudean Mircea")):
            con.execute(
                "INSERT INTO initiativa_initiator (plx_id, idm, leg, nume, grup, camera)"
                " VALUES (?,?,?,?,?,?)",
                (f"plx-{i}-2021", str(i), "2020", nume, "PNL", "Camera Deputaților"),
            )
        con.commit()
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        assert [p.nume for p in deputati.toti(con)] == [
            "Abrudean Mircea",
            "Șovăială Petru",
            "Zamfir Ion",
        ]
    finally:
        con.close()


def test_a_groups_counts_can_be_opened_into_the_bills_behind_them(tmp_path):
    """A card that says 466 adopted and cannot show which 466 is a number a reader has to take on
    trust. Counted and listed off the same query, so the number and the list cannot drift."""
    con = _mandate(tmp_path)
    try:
        card = {g["grup"]: g for g in deputati.grupuri(con, "2020")}["USR"]
        adoptate = deputati.initiative_grup(con, "USR", leg="2020", rezultat="adoptat")
        respinse = deputati.initiative_grup(con, "USR", leg="2020", rezultat="respins")
        toate = deputati.initiative_grup(con, "USR", leg="2020")
    finally:
        con.close()
    assert len(adoptate) == card["adoptate"]
    assert len(respinse) == card["respinse"]
    assert len(toate) == card["initiative"]


def test_no_recorded_vote_is_its_own_outcome_and_not_a_defeat(tmp_path):
    """`nedecis` is a third value rather than the absence of the first two, because a bill still
    moving is not a bill that lost."""
    cale = tmp_path / "initiative.db"
    with depozit.deschide(cale) as con:
        con.execute(
            "INSERT INTO initiative (plx_id, cam, idp, tip, titlu, obiect, urgenta, stadiu,"
            " data_inreg, citit_la) VALUES ('plx-9-2021',2,'0','p','T','',0,'în comisie','2021',"
            " 'x')"
        )
        con.execute(
            "INSERT INTO initiativa_initiator (plx_id, idm, leg, nume, grup, camera)"
            " VALUES ('plx-9-2021','1','2020','X','PNL','Camera Deputaților')"
        )
        con.commit()
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        (x,) = deputati.initiative_grup(con, "PNL")
        assert x["rezultat"] == "nedecis"
        assert deputati.initiative_grup(con, "PNL", rezultat="respins") == []
    finally:
        con.close()
