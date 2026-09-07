"""Tests for the roll of a division: who voted which way.

The markup is trimmed from `evot2015.Nominal?idv=25475` — the final vote on PL-x 1/2021, where the
Fișa's tally reads `pentru=275, contra=34, abtineri=0, nu au votat=3` and the roll lists 312 names.
The three shapes that matter are all in the fixture: a member who voted, a member listed with `-`
who was in the room and did not, and the fact that the roll is shorter than the chamber.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import depozit, nominal

PAGINA = """
<html><body>
<table>
<tr valign="top"><td align="right" bgcolor="#fffef2" nowrap>Sedinta:</td>
  <td>Camerei Deputatilor</td></tr>
<tr valign="top"><td align="right" bgcolor="#fffef2" nowrap>Subiect vot:</td>
  <td><b> Vot final </b> <br> Adoptare
  <a href="/ords/pls/proiecte/upl_pck2015.proiect?idp=19122" target="PROIECTE">PL 1/2021</a>
  pentru aprobarea Ordonan&#355;ei de urgen&#355;&#259; a Guvernului nr.212/2020</td></tr>
</table>
<table>
<tr valign="top"><td nowrap align="right">1.</td>
  <td><a href="/ords/pls/parlam/structura2015.mp?idm=1&cam=2&leg=2020">Acatrinei
  Dorel-Gheorghe</a></td>
  <td align="center">AUR</td><td align="center" nowrap> NU </td></tr>
<tr valign="top"><td nowrap align="right">2.</td>
  <td><a href="/ords/pls/parlam/structura2015.mp?idm=2&cam=2&leg=2020">Achima&#351;-Cadariu
  Patriciu-Andrei</a></td>
  <td align="center">PSD</td><td align="center" nowrap> DA </td></tr>
<tr valign="top"><td nowrap align="right">3.</td>
  <td><a href="/ords/pls/parlam/structura2015.mp?idm=3&cam=2&leg=2020">Adomnic&#259;i
  Mirela</a></td>
  <td align="center">PSD</td><td align="center" nowrap> - </td></tr>
<tr valign="top"><td nowrap align="right">4.</td>
  <td><a href="/ords/pls/parlam/structura2015.mp?idm=4&cam=1&leg=2020">Un Senator</a></td>
  <td align="center">USR</td><td align="center" nowrap> AB </td></tr>
</table>
</body></html>
"""


def _rol():
    return nominal.parseaza_nominal(PAGINA, "25475")


def test_every_member_on_the_roll_is_read_with_the_key_their_profile_uses():
    """A vote is only useful if it reaches the right person, and the only thing that reaches the
    right person is (legislature, chamber, id) — the same triple the signatures and the speeches
    hang off. `idm=4` here sits in the Senate, and the chamber is what keeps them apart."""
    r = _rol()
    chei = {(o.idm, o.leg, o.camera) for o in r.optiuni}
    assert ("1", "2020", "Camera Deputaților") in chei
    assert ("4", "2020", "Senat") in chei
    assert len(r.optiuni) == 4


def test_the_options_are_folded_and_the_page_is_still_quotable():
    """`optiune` is what the app groups on; `brut` is what the page printed, so any reading can be
    checked against the source without refetching it."""
    pe_id = {o.idm: o for o in _rol().optiuni}
    assert (pe_id["1"].optiune, pe_id["1"].brut) == ("nu", "NU")
    assert (pe_id["2"].optiune, pe_id["2"].brut) == ("da", "DA")
    assert (pe_id["4"].optiune, pe_id["4"].brut) == ("abtinere", "AB")


def test_present_and_not_voting_is_not_the_same_as_absent():
    """A member listed with `-` was in the room and did not vote. A member not listed was not
    there. The page states the first and is silent about the second, so only the first is a row —
    inventing rows for the absent would be inventing an attendance record."""
    pe_id = {o.idm: o for o in _rol().optiuni}
    assert pe_id["3"].optiune == "nu_a_votat"
    assert "5" not in pe_id, "rândul unui absent a fost inventat"


def test_the_subject_is_one_line_and_names_the_bill():
    """The roll writes it across four lines — `Vot final`, `Adoptare`, `PL 1/2021`, the title — and
    a stored newline renders as a broken heading everywhere it is shown."""
    r = _rol()
    assert r.subiect is not None and "\n" not in r.subiect
    assert r.subiect.startswith("Vot final Adoptare PL 1/2021")
    assert r.idp == "19122"
    assert r.camera == "Camera Deputaților"


def _magazin(tmp_path: Path) -> Path:
    cale = tmp_path / "initiative.db"
    with depozit.deschide(cale) as con:
        con.execute(
            "INSERT INTO initiative (plx_id, cam, idp, tip, titlu, obiect, urgenta, stadiu,"
            " data_inreg, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("plx-1-2021", 2, "19122", "proiect", "Lege", "", 0, "adoptată", "2021-01-01", "x"),
        )
        con.execute(
            "INSERT INTO initiativa_vot (plx_id, data, camera, intrebare, pentru, contra,"
            " abtineri, rezultat, idv) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "plx-1-2021",
                "2021-02-24",
                "Camera Deputaților",
                None,
                275,
                34,
                0,
                "adoptat",
                "25475",
            ),
        )
        con.commit()
    return cale


def test_only_the_rolls_not_yet_read_are_asked_for(tmp_path):
    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        assert nominal.de_adus(con) == ["25475"]
        nominal.scrie_nominal(con, _rol())
        con.commit()
        assert nominal.de_adus(con) == []


def test_a_members_record_carries_what_the_division_was_about(tmp_path):
    """A list of `da`/`nu` with no subject is unreadable. The vote's own row supplies the date and
    the bill; the roll supplies what was put."""
    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        nominal.scrie_nominal(con, _rol())
        con.commit()
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        (v,) = nominal.cum_a_votat(con, "1", "2020", "Camera Deputaților")
    finally:
        con.close()
    assert v["optiune"] == "nu"
    assert v["plx_id"] == "plx-1-2021" and v["data"] == "2021-02-24"
    assert v["subiect"].startswith("Vot final")


def test_the_roll_is_grouped_the_way_the_chamber_sits(tmp_path):
    """How a party voted is the question after how one member did, and a flat list of 312 names
    does not answer it."""
    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        nominal.scrie_nominal(con, _rol())
        con.commit()
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        r = nominal.rolul(con, "25475")
    finally:
        con.close()
    assert r["gasit"] is True
    psd = next(g for g in r["grupuri"] if g["grup"] == "PSD")
    assert (psd["da"], psd["nu"], psd["nu_au_votat"]) == (1, 0, 1)
    aur = next(g for g in r["grupuri"] if g["grup"] == "AUR")
    assert aur["nu"] == 1


def test_a_roll_that_was_never_fetched_says_so_rather_than_reading_unanimous(tmp_path):
    """An unread roll and a division nobody voted in are different facts, and an empty list for
    both would report a silence that did not happen."""
    cale = _magazin(tmp_path)
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        assert nominal.rolul(con, "25475") == {"gasit": False, "idv": "25475", "grupuri": []}
    finally:
        con.close()


def test_rereading_a_division_replaces_rather_than_duplicates(tmp_path):
    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        nominal.scrie_nominal(con, _rol())
        nominal.scrie_nominal(con, _rol())
        con.commit()
        assert con.execute("SELECT count(*) FROM vot_nominal").fetchone()[0] == 4


# --- ce servește pagina ---------------------------------------------------------------------


def _stare(cale: Path):
    from scripts.servicii import Stare

    return Stare(corpus=str(cale), initiative=str(cale), graf=str(cale))


def test_the_vote_row_carries_its_roll_and_a_division_without_one_does_not(tmp_path):
    """A division with no roll linked must not offer one; `idv` is absent rather than empty."""
    from scripts.servicii import _parcurs

    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        con.execute(
            "INSERT INTO initiativa_vot (plx_id, data, camera, intrebare, pentru, contra,"
            " abtineri, rezultat) VALUES (?,?,?,?,?,?,?,?)",
            ("plx-1-2021", "2021-03-01", "Senat", None, 90, 2, 0, "adoptat"),
        )
        con.commit()
    voturi = _parcurs({"plx": ["plx-1-2021"]}, _stare(cale))["voturi"]
    pe_data = {v["data"]: v for v in voturi}
    assert pe_data["2021-02-24"]["idv"] == "25475"
    assert pe_data["2021-03-01"]["idv"] is None


def test_the_served_roll_can_open_the_person_who_cast_the_vote(tmp_path):
    """A name on the roll is only useful if clicking it reaches the right person, and the only
    thing that does is (legislature, chamber, id)."""
    from scripts.servicii import _rol

    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        nominal.scrie_nominal(con, _rol_pagina())
        con.commit()
    r = _rol({"idv": ["25475"]}, _stare(cale))
    assert r["gasit"] is True
    membru = next(m for g in r["grupuri"] for m in g["membri"] if m["nume"].startswith("Acatrinei"))
    assert (membru["idm"], membru["leg"], membru["camera"]) == ("1", "2020", "Camera Deputaților")
    assert membru["optiune"] == "nu"


def test_a_members_profile_answers_how_they_voted(tmp_path):
    """The profile already says what they proposed and what they said. This is the third question
    and the one a voter actually asks — on the same key, so it is the same person."""
    from scripts.servicii import _deputati

    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        nominal.scrie_nominal(con, _rol_pagina())
        con.commit()
    d = _deputati({"idm": ["1"], "leg": ["2020"], "camera": ["Camera Deputaților"]}, _stare(cale))
    assert [v["optiune"] for v in d["voturi"]] == ["nu"]
    assert d["voturi"][0]["plx_id"] == "plx-1-2021"


def _rol_pagina():
    return nominal.parseaza_nominal(PAGINA, "25475")
