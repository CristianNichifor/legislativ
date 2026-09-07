"""Tests for reading a sitting's transcript, against the shapes a real page actually has.

The markup below is trimmed from `steno2015.stenograma?ids=8235&idm=8` and `?ids=8236&idm=15.02`,
and every awkward thing in it is there because the Chamber's pages do it:

- a speaker announced in one row and speaking in the next, so the block carries no name of its own;
- a speaker announced *inside* the block, which is the more common shape;
- a minister with no profile to link to, whose office is only stated in the parenthetical;
- `Voci din sală` — an interjection from the floor — carrying the chairing deputy's own id;
- four links to the same sitting summary, of which only the breadcrumb spells out the date;
- two highlighted cells, one holding the item's number and one its subject.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts import depozit
from scripts.stenograme import de_adus, parseaza_stenograma, scrie_stenograma

PAGINA = """
<html><body>
<a href="/ords/pls/steno/steno2015.sumar?ids=8235&idl=2">EN</a>
<a href="/ords/pls/steno/steno2015.sumar?ids=8235">Sumarul &#351;edin&#355;ei</a>
<td class="cale-right"><a href="/ords/pls/steno/steno2015.sumar?ids=8235">&#350;edin&#355;a
Camerei Deputa&#355;ilor din 22 februarie  2021</a></td>
<table>
<tr valign="top">
  <td nowrap bgcolor="#fef9c2"><b>8.</td>
  <td width="100%" colspan=3 bgcolor="#fef9c2"><b>Dezbaterea Proiectului de Lege pentru aprobarea
  Ordonan&#355;ei de urgen&#355;&#259; a Guvernului nr. 212/2020 (PL-x 1/2021).</b></td>
</tr>
<tr><td colspan=4><div id="MaiMulte">consulta fisa PL nr.
  <a href="/ords/pls/proiecte/upl_pck2015.proiect?idp=19122&cam=2">1/2021</a></div></td></tr>
</table>
<table>
<tr valign="top"><td>&nbsp;</td>
<td><P><B><a href="/ords/pls/parlam/structura2015.mp?idm=165&cam=2&leg=2020"
   target="PARLAMENTARI"><font color="#0000FF">Domnul Lauren&#355;iu-Dan Leoreanu</font></a></B>:
</td>
</tr>
<tr valign="top"><td width="100%">
<!-- START=2138112,813606,839016 -->
 <p align="justify">4. Proiectul de Lege pentru aprobarea Ordonan&#355;ei de urgen&#355;&#259;.
 <p align="justify">Are cuv&#226;ntul ini&#355;iatorul, Guvernul Rom&#226;niei.
<!-- END -->
</td></tr>
<tr valign="top"><td width="100%">
<!-- START=2138113,839017,876677 -->
<p align="justify"><B><font color="#0000FF">Domnul Nini S&#259;punaru</font></B>
<I>(secretar de stat, Departamentul pentru Rela&#355;ia cu Parlamentul)</I>:
<p align="justify">Bun&#259; ziua! Prin prezenta ordonan&#355;&#259; s-au operat modific&#259;ri.
<!-- END -->
</td></tr>
<tr valign="top"><td width="100%">
<!-- START=2138886,12716103,12722222 -->
 <p align="justify">Trecem la punctul III. Legi ordinare.
 <p align="justify"><B><a href="/ords/pls/parlam/structura2015.mp?idm=245&cam=2&leg=2020"
 target="PARLAMENTARI"><font color="#0000FF">Voci din sal&#259;</font></a></B>:
 <p align="justify">Organice!
<!-- END -->
</td></tr>
</table>
</body></html>
"""


def _steno():
    return parseaza_stenograma(PAGINA, "8235", "8")


def test_the_sitting_is_dated_from_the_breadcrumb_not_the_first_link():
    """Four links point at the same sitting summary and three of them say only `EN` or `Sumarul
    şedinţei`. Reading the first would leave every transcript in the corpus undated."""
    s = _steno()
    assert s.data == "2021-02-22"
    assert s.camera == "Camera Deputaților"


def test_the_item_is_titled_by_its_subject_and_not_its_number():
    """Both highlighted cells are the same colour; one holds `8.` and one holds the subject."""
    s = _steno()
    assert s.titlu is not None
    assert s.titlu.startswith("Dezbaterea Proiectului de Lege")


def test_the_bill_is_read_from_the_link_not_the_printed_number():
    s = _steno()
    assert s.idp == "19122"


def test_a_speaker_announced_in_the_row_above_still_owns_the_speech():
    """The Chamber prints the chair's name once and then the words, in two rows. A block with no
    announcement of its own is not an anonymous speech."""
    s = _steno()
    prima = s.interventii[0]
    assert prima.vorbitor == "Domnul Laurențiu-Dan Leoreanu"
    assert (prima.dep_idm, prima.dep_leg, prima.dep_camera) == ("165", "2020", "Camera Deputaților")
    assert prima.text.startswith("4. Proiectul de Lege")


def test_the_announcement_is_not_part_of_the_speech():
    """A speaker announced inside their own block must not have their own name read back as the
    first words they said."""
    s = _steno()
    ministru = s.interventii[1]
    assert not ministru.text.startswith("Domnul Nini")
    assert ministru.text.startswith("Bună ziua!")


def test_someone_with_no_profile_keeps_their_office_and_gains_no_id():
    """A secretary of state has no `structura2015.mp` link; the parenthetical is the only place
    the transcript says who they were, and inventing a deputy id for them would be worse."""
    s = _steno()
    ministru = s.interventii[1]
    assert ministru.vorbitor == "Domnul Nini Săpunaru"
    assert ministru.dep_idm is None
    assert ministru.rol is not None and "secretar de stat" in ministru.rol


def test_an_interjection_from_the_floor_is_not_attributed_to_the_chair():
    """The Chamber's own markup links `Voci din sală` to idm=245, who is Prună. Storing that would
    put crowd noise on a named person's record; the words stay, the attribution goes."""
    s = _steno()
    voci = s.interventii[2]
    assert voci.vorbitor == "Voci din sală"
    assert (voci.dep_idm, voci.dep_leg, voci.dep_camera) == (None, None, None)
    assert "Organice!" in voci.text


def test_the_speaker_key_is_the_one_deputy_profiles_are_built_on():
    """`(leg, camera, idm)` and nothing else — the same triple `deputati.py` groups signatures by,
    so a speech joins to the person through the Chamber's id and never through the name."""
    s = _steno()
    chei = {(i.dep_leg, i.dep_camera, i.dep_idm) for i in s.interventii if i.dep_idm}
    assert chei == {("2020", "Camera Deputaților", "165")}


def _magazin(tmp_path: Path) -> Path:
    cale = tmp_path / "initiative.db"
    with depozit.deschide(cale) as con:
        con.execute(
            "INSERT INTO initiative (plx_id, cam, idp, tip, titlu, obiect, urgenta, stadiu,"
            " data_inreg, citit_la) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("plx-1-2021", 2, "19122", "proiect", "Lege", "", 0, "adoptată", "2021-01-01", "x"),
        )
        con.execute(
            "INSERT INTO initiativa_etapa (plx_id, ord, data, camera, actiune, steno_ids,"
            " steno_idm) VALUES (?,?,?,?,?,?,?)",
            ("plx-1-2021", 0, "2021-02-22", "Camera Deputaților", "dezbatere", "8235", "8"),
        )
        con.commit()
    return cale


def test_only_the_transcripts_not_yet_read_are_asked_for(tmp_path):
    """A run interrupted at 3 000 pages must not start again at 1, and several steps of one bill
    routinely point at the same sitting item."""
    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        assert de_adus(con) == [("8235", "8")]
        scrie_stenograma(con, _steno())
        con.commit()
        assert de_adus(con) == []


def test_the_stored_transcript_carries_the_bill_under_the_id_bills_are_keyed_on(tmp_path):
    """The transcript links a Fișa by `idp`; everything else here is keyed on `plx_id`."""
    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        scrie_stenograma(con, _steno())
        con.commit()
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        assert con.execute("SELECT plx_id FROM stenograma").fetchone()[0] == "plx-1-2021"
        assert con.execute("SELECT count(*) FROM interventie").fetchone()[0] == 3
    finally:
        con.close()


def test_rereading_a_sitting_replaces_rather_than_duplicates(tmp_path):
    """The page is the authority on its own sitting, and a speech has no identity to merge on
    beyond its place in the order — so a refetch must supersede, including in the search index."""
    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        scrie_stenograma(con, _steno())
        scrie_stenograma(con, _steno())
        con.commit()
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        assert con.execute("SELECT count(*) FROM interventie").fetchone()[0] == 3
        assert con.execute("SELECT count(*) FROM interventie_fts").fetchone()[0] == 3
    finally:
        con.close()


def test_the_debate_is_searchable_by_what_was_said(tmp_path):
    """A corpus of speeches nobody can search is an archive, not an answer."""
    cale = _magazin(tmp_path)
    with depozit.deschide(cale) as con:
        scrie_stenograma(con, _steno())
        con.commit()
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        gasit = con.execute(
            "SELECT vorbitor FROM interventie_fts WHERE interventie_fts MATCH ?", ("ordonanta",)
        ).fetchall()
    finally:
        con.close()
    assert [r[0] for r in gasit] == ["Domnul Nini Săpunaru"]
