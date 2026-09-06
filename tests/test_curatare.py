"""Tests for removing the SOAP service's block separator from collected text.

The service marks a boundary with a lone `+` on its own line. It is the only single-character line
it emits, and the HTML the portal serves for the same document has none — which is what identified
it as an artifact of the transport rather than something the Monitorul Oficial printed. 83% of
collected documents carry at least one.

Two properties carry this.

**Real plus signs survive.** `a + b`, a sum inside a provision, a `+` used as a bullet mid-line —
stripping those would edit the law to tidy up the pipe it came down.

**The archive is not touched.** `documente.text` keeps exactly what the service returned. A marker
deleted from the archive could not be recovered, and the archive is the one thing here that has to
stay re-readable; the cleaned copy is the derived one in `provizii`, which is what gets quoted,
searched, and put in front of a model.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.curatare import separatoare, titluri
from scripts.text import fara_separatoare

MURDAR = (
    "LEGE nr. 7 din 1995 EMITENT PARLAMENTUL Publicat în\nMONITORUL OFICIAL nr. 3\n"
    "+\n"
    "Articolul UNIC Sarcinile prevăzute în anexă se majorează cu 2 + 3 unități.\n"
    "+"
)


def _rec(text: str) -> Inregistrare:
    return Inregistrare(
        titlu="LEGE nr. 7/1995",
        tip_act="LEGE",
        numar="7",
        an=1995,
        data_vigoare=date(1995, 1, 1),
        emitent="PARLAMENTUL",
        publicatie="MO",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/7",
        text=text,
    )


def test_a_separator_on_its_own_line_goes_and_a_sum_stays():
    curatat = fara_separatoare(MURDAR)
    assert "\n+\n" not in curatat
    assert not curatat.endswith("+")
    assert "2 + 3 unități" in curatat, "edited the law to tidy up the transport"
    assert "MONITORUL OFICIAL nr. 3\nArticolul UNIC" in curatat


def test_it_is_stable_under_a_second_application():
    o = fara_separatoare(MURDAR)
    assert fara_separatoare(o) == o


def test_new_collection_stores_the_derived_copy_already_clean(tmp_path: Path):
    cale = tmp_path / "corpus.db"
    r = _rec(MURDAR)
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))

    cx = sqlite3.connect(str(cale))
    try:
        (prov,) = cx.execute("SELECT text FROM provizii WHERE locator='text'").fetchone()
        (arhiva,) = cx.execute("SELECT text FROM documente").fetchone()
    finally:
        cx.close()
    assert "\n+\n" not in prov
    assert "2 + 3" in prov
    # The archive keeps what the service said, marker and all.
    assert arhiva == MURDAR, "the archive was edited; the original could not be recovered"


def test_the_migration_cleans_a_corpus_collected_before_the_fix(tmp_path: Path):
    """Rows written by an older collector. The fix at the write site does nothing for them."""
    cale = tmp_path / "corpus.db"
    r = _rec(MURDAR)
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        # put the marker back, as an older build would have stored it
        con.execute("UPDATE provizii SET text = ? WHERE locator = 'text'", (MURDAR,))

    rez = separatoare(str(cale), log=lambda *_: None)
    assert (rez.examinate, rez.schimbate) == (1, 1)

    cx = sqlite3.connect(str(cale))
    try:
        (prov,) = cx.execute("SELECT text FROM provizii WHERE locator='text'").fetchone()
    finally:
        cx.close()
    assert "\n+\n" not in prov and "2 + 3" in prov


def test_search_still_finds_the_act_after_the_index_is_rebuilt(tmp_path: Path):
    """`provizii_fts` is external content, so a rewritten row leaves the index holding the old
    values unless it is rebuilt. An act that stopped being findable would be a worse corpus."""
    cale = tmp_path / "corpus.db"
    r = _rec(MURDAR)
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        con.execute("UPDATE provizii SET text = ? WHERE locator = 'text'", (MURDAR,))
    separatoare(str(cale), log=lambda *_: None)

    with depozit.deschide(cale, readonly=True) as con:
        assert depozit.cauta(con, "sarcinile", 5), "the act stopped being findable"


def test_a_corpus_with_nothing_to_clean_is_left_alone(tmp_path: Path):
    cale = tmp_path / "corpus.db"
    r = _rec("Articolul 1 Text curat, fără marcaje de separator.")
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
    rez = separatoare(str(cale), log=lambda *_: None)
    assert rez.schimbate == 0


def test_provisions_parsed_from_html_are_not_rewritten(tmp_path: Path):
    """0 of 44 059 carried the marker, so touching them would be a rewrite with nothing to fix —
    and every rewrite of a provision is a chance to lose one."""
    cale = tmp_path / "corpus.db"
    r = _rec("orice")
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        con.execute(
            "INSERT INTO provizii (act_id, locator, ord, text) VALUES ('lege-7-1995','art1',2,?)",
            ("Un articol venit din HTML.\n+\ncu marcaj inventat",),
        )
    separatoare(str(cale), log=lambda *_: None)

    cx = sqlite3.connect(str(cale))
    try:
        (t,) = cx.execute("SELECT text FROM provizii WHERE locator='art1'").fetchone()
    finally:
        cx.close()
    assert "\n+\n" in t, "rewrote a provision the service never touched"


# --- titluri: marca de ordine a octeților și entitățile HTML -----------------------------------


def _rec_titlu(titlu: str) -> Inregistrare:
    return Inregistrare(
        titlu=titlu,
        tip_act="LEGE",
        numar="7",
        an=1995,
        data_vigoare=date(1995, 1, 1),
        emitent="PARLAMENTUL",
        publicatie="MO",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/7",
        text="Articolul UNIC Se aprobă.",
    )


def test_the_service_record_yields_a_title_without_its_byte_order_mark():
    """The ingest half, at the boundary that actually normalises: `_inregistrare` runs the title
    through `normalizeaza`, which now drops U+FEFF. Nothing collected from here on needs the
    migration below — the 91 650 dirty titles were written while `normalizeaza` let the mark
    through.
    """
    from scripts.api import _inregistrare

    rec = (
        "<a:Titlu>\ufeff &#9675;LEGE nr. 7 din 1995 privind ceva</a:Titlu>"
        "<a:TipAct>LEGE</a:TipAct><a:Numar>7</a:Numar><a:An>1995</a:An>"
    )
    assert _inregistrare(rec).titlu == "○LEGE nr. 7 din 1995 privind ceva"


def test_the_migration_cleans_titles_already_written(tmp_path: Path):
    """The corpus half: 91 650 titles were written before the ingest fix existed. Written straight
    past `scrie_inregistrare` so the row is dirty the way the stored ones are."""
    cale = tmp_path / "corpus.db"
    r = _rec_titlu("LEGE nr. 7 din 1995")
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        con.execute("UPDATE acte SET titlu = ?", ("﻿ &#9675;LEGE nr. 7 din 1995 privind ceva",))
        con.commit()

    raport = titluri(str(cale), log=lambda *_: None)
    assert raport.schimbate == 1

    cx = sqlite3.connect(str(cale))
    try:
        (titlu,) = cx.execute("SELECT titlu FROM acte").fetchone()
    finally:
        cx.close()
    assert titlu == "○LEGE nr. 7 din 1995 privind ceva"


def test_the_migration_leaves_a_clean_title_alone(tmp_path: Path):
    """It must be safe to run twice — the count is what tells a person whether it did anything."""
    cale = tmp_path / "corpus.db"
    r = _rec_titlu("LEGE nr. 7 din 1995 privind ceva")
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
    assert titluri(str(cale), log=lambda *_: None).schimbate == 0


def test_an_ampersand_in_a_title_survives_one_decode(tmp_path: Path):
    """`&amp;` becomes `&`, and running the migration again must not then eat the bare `&`. This is
    why the decode lives here and not in `normalizeaza`, which is documented as safe to run twice
    and is applied on the way in *and* on the way into a matcher."""
    cale = tmp_path / "corpus.db"
    r = _rec_titlu("LEGE nr. 7 din 1995")
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        con.execute("UPDATE acte SET titlu = ?", ("LEGE nr. 7 privind A &amp; B",))
        con.commit()

    titluri(str(cale), log=lambda *_: None)
    titluri(str(cale), log=lambda *_: None)
    cx = sqlite3.connect(str(cale))
    try:
        (titlu,) = cx.execute("SELECT titlu FROM acte").fetchone()
    finally:
        cx.close()
    assert titlu == "LEGE nr. 7 privind A & B"
