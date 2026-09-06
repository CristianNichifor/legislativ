"""Tests for the corpus store.

The one that matters is `test_nothing_is_silently_dropped`. It exists because the first schema
keyed provisions on (act_id, locator), Legea 98/2016 went in with 1 435 provisions and came out
with 1 404, and nothing said so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import depozit
from scripts.parsare import ActParsat, Provizie, din_fisier
from scripts.referinte import Act

SURSE = Path(__file__).resolve().parent.parent / "sources"


@pytest.fixture(scope="module")
def lege():
    return din_fisier(
        SURSE / "lege-98-2016.html.gz",
        url="https://legislatie.just.ro/Public/DetaliiDocument/178667",
    )


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "corpus.db"


def test_an_act_round_trips(db, lege):
    (r,) = depozit.importa(db, [lege])
    assert r.act_id == "lege-98-2016" and r.provizii == len(lege.provizii)
    with depozit.deschide(db) as con:
        assert [a.id for a in depozit.acte(con)] == ["lege-98-2016"]
        row = con.execute("SELECT * FROM acte WHERE id='lege-98-2016'").fetchone()
        assert row["id_portal"] == "178667" and row["id_act_portal"] == "290673"


def test_nothing_is_silently_dropped(db, lege):
    """A locator is not unique — an article and an unnumbered block inside it produce the same
    one — so `ord` carries the identity and the writer counts the rows back."""
    depozit.importa(db, [lege])
    with depozit.deschide(db) as con:
        assert depozit.rezumat(con)["provizii"] == len(lege.provizii)


def test_the_writer_refuses_rather_than_lose_a_row(db):
    """If the count ever disagrees again, the import fails instead of returning a short corpus."""
    dublu = ActParsat(
        act=Act("lege", "1", 2020),
        titlu="LEGE nr. 1 din 1 ianuarie 2020",
        provizii=(Provizie("art1", "unu"), Provizie("art1", "doi")),
    )
    (r,) = depozit.importa(db, [dublu])
    assert r.provizii == 2
    with depozit.deschide(db) as con:
        assert depozit.rezumat(con)["provizii"] == 2


def test_reimporting_replaces_rather_than_merges(db, lege):
    depozit.importa(db, [lege])
    depozit.importa(db, [lege])
    with depozit.deschide(db) as con:
        assert depozit.rezumat(con)["provizii"] == len(lege.provizii)
        assert depozit.rezumat(con)["acte"] == 1


def test_search_ignores_diacritics_in_both_directions(db, lege):
    """Half the corpus predates the comma-below letters. A search for `hotarare` that misses
    `hotărâre` is a search nobody can use."""
    depozit.importa(db, [lege])
    with depozit.deschide(db) as con:
        fara = depozit.cauta(con, "achizitie publica", 5)
        cu = depozit.cauta(con, "achiziție publică", 5)
        assert fara and cu
        assert {r["locator"] for r in fara} & {r["locator"] for r in cu}


def test_the_portals_relation_flags_are_stored_as_assumed(db, lege):
    """A flag says a relation exists, not what it points at. Stored as anything firmer, it
    would look like a fact somebody could act on."""
    depozit.importa(db, [lege])
    with depozit.deschide(db) as con:
        rows = con.execute("SELECT * FROM relatii WHERE din_act='lege-98-2016'").fetchall()
        assert len(rows) == 4
        assert {r["sursa"] for r in rows} == {"portal"}
        assert {r["incredere"] for r in rows} == {"assumed"}


def test_a_page_is_fetched_once_ever(db):
    """The cache is the collector's most important property: this reads a ministry's server on
    behalf of a political party, and it should ask for a document once."""
    url = "https://legislatie.just.ro/Public/DetaliiDocument/1"
    with depozit.deschide(db) as con:
        assert depozit.din_cache(con, url) is None
        depozit.pune_in_cache(con, url, b"<html>x</html>", 200)
    with depozit.deschide(db) as con:
        assert depozit.din_cache(con, url) == b"<html>x</html>"
        assert depozit.rezumat(con)["pagini_in_cache"] == 1


def test_a_failed_fetch_is_not_served_from_cache(db):
    url = "https://legislatie.just.ro/Public/DetaliiDocument/2"
    with depozit.deschide(db) as con:
        depozit.pune_in_cache(con, url, b"Error", 403)
        assert depozit.din_cache(con, url) is None


def test_two_documents_sharing_a_citation_key_both_survive(db):
    """A citation key is not a document identity, and conflating them cost a quarter of a corpus.

    Ministries number their ordine from 1 each year and `decizie-5-1996` names a Curtea
    Constituțională decision as readily as an agency's, so `tip-numar-an` collides constantly.
    `acte` is the citation view and keeps the last writer — resolution needs exactly one answer
    for `Legea nr. 98/2016`. `documente` keeps both, because the one thing this package may not
    do is delete a document it fetched.
    """
    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    def rec(id_portal: str, emitent: str, text: str) -> Inregistrare:
        return Inregistrare(
            titlu="ORDIN nr. 1/1995",
            tip_act="ORDIN",
            numar="1",
            an=1995,
            data_vigoare=None,
            emitent=emitent,
            publicatie="MO",
            link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{id_portal}",
            text=text,
        )

    finante = rec("111", "Ministerul Finanțelor", "text finanțe")
    sanatate = rec("222", "Ministerul Sănătății", "text sănătate")
    assert act_din_inregistrare(finante).id == act_din_inregistrare(sanatate).id

    with depozit.deschide(db) as con:
        for r in (finante, sanatate):
            depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))

        assert con.execute("SELECT count(*) FROM acte").fetchone()[0] == 1
        pastrate = con.execute("SELECT emitent, text FROM documente ORDER BY id_portal").fetchall()
        assert [r["emitent"] for r in pastrate] == [
            "Ministerul Finanțelor",
            "Ministerul Sănătății",
        ]
        assert [r["text"] for r in pastrate] == ["text finanțe", "text sănătate"]
        assert {r["cheie_act"] for r in con.execute("SELECT cheie_act FROM documente")} == {
            "ordin-1-1995"
        }


def test_refetching_the_same_document_updates_it_in_place(db):
    """Re-collecting a page must not duplicate the documents on it."""
    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    r = Inregistrare(
        titlu="LEGE nr. 98/2016",
        tip_act="LEGE",
        numar="98",
        an=2016,
        data_vigoare=None,
        emitent="Parlamentul",
        publicatie="MO",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/900",
        text="corp",
    )
    with depozit.deschide(db) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        assert con.execute("SELECT count(*) FROM documente").fetchone()[0] == 1


def test_rewriting_an_act_leaves_no_stale_full_text_rows(db):
    """Replacing an act must remove its old search rows, or it matches twice with stale text.

    This was previously done with `DELETE FROM provizii_fts WHERE act_id = ?`, which is a full
    scan of the fts5 table because `act_id` is UNINDEXED there. Correct, and it made collection
    cost grow with the corpus: 65 ms per record at 18 000 rows, ten records to a page, projecting
    to 9.1 s per page at the full 251 460 documents. The rowid map replaces the scan; this test
    is what stops the replacement from quietly losing the delete.
    """
    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    def rec(text: str) -> Inregistrare:
        return Inregistrare(
            titlu="LEGE nr. 7/2001",
            tip_act="LEGE",
            numar="7",
            an=2001,
            data_vigoare=None,
            emitent="Parlamentul",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/700",
            text=text,
        )

    with depozit.deschide(db) as con:
        vechi = rec("cadastru si publicitate imobiliara")
        depozit.scrie_inregistrare(con, vechi, act_din_inregistrare(vechi))
        nou = rec("text inlocuit complet")
        depozit.scrie_inregistrare(con, nou, act_din_inregistrare(nou))

        assert con.execute("SELECT count(*) FROM provizii_fts").fetchone()[0] == 1
        assert (
            con.execute(
                "SELECT count(*) FROM provizii_fts WHERE provizii_fts MATCH 'cadastru'"
            ).fetchone()[0]
            == 0
        )
        assert (
            con.execute(
                "SELECT count(*) FROM provizii_fts WHERE provizii_fts MATCH 'inlocuit'"
            ).fetchone()[0]
            == 1
        )
        # The map must not leak rows either, or it grows without bound.
        assert con.execute("SELECT count(*) FROM provizii_fts_rand").fetchone()[0] == 1


def test_a_corpus_written_before_the_map_existed_is_backfilled(db):
    """An older corpus has full-text rows and no map; the first write-open must reconcile them."""
    from scripts.api import Inregistrare
    from scripts.colector import act_din_inregistrare

    r = Inregistrare(
        titlu="LEGE nr. 8/2001",
        tip_act="LEGE",
        numar="8",
        an=2001,
        data_vigoare=None,
        emitent="Parlamentul",
        publicatie="MO",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/800",
        text="text vechi de dinainte de harta",
    )
    with depozit.deschide(db) as con:
        depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        # Simulate the pre-migration state: index populated, map absent.
        con.execute("DELETE FROM provizii_fts_rand")

    with depozit.deschide(db) as con:
        assert con.execute("SELECT count(*) FROM provizii_fts_rand").fetchone()[0] == 1
        nou = Inregistrare(**{**r.__dict__, "text": "text nou"})
        depozit.scrie_inregistrare(con, nou, act_din_inregistrare(nou))
        assert con.execute("SELECT count(*) FROM provizii_fts").fetchone()[0] == 1


def _rec_mo(text: str, vigoare=None):
    from datetime import date as _d

    from scripts.api import Inregistrare

    return Inregistrare(
        titlu="LEGE nr. 3/1962",
        tip_act="LEGE",
        numar="3",
        an=1962,
        data_vigoare=vigoare or _d(1963, 1, 29),
        emitent="Marea Adunare Națională",
        publicatie="Monitorul Oficial",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/1962",
        text=text,
    )


def test_publication_date_is_read_from_the_act_not_copied_from_in_force(db):
    """`publicat` used to be a second copy of `vigoare` — identical in all 63 933 rows.

    Codul silvic is the real case: published 30 December 1962, in force 29 January 1963. Every
    art. 78 and art. 147 deadline anchors on the first date, and the corpus held only the second.
    """
    from datetime import date as _d

    from scripts.colector import act_din_inregistrare

    rec = _rec_mo(
        "LEGE nr. 3 din 28 decembrie 1962 privind CODUL SILVIC EMITENT MAREA ADUNARE NAȚIONALA "
        "Publicat în MONITORUL OFICIAL nr. 28 din 30 decembrie 1962 + Capitolul 1"
    )
    with depozit.deschide(db) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
        a = con.execute("SELECT publicat, vigoare FROM acte").fetchone()
        assert a["publicat"] == _d(1962, 12, 30).isoformat()
        assert a["vigoare"] == _d(1963, 1, 29).isoformat()
        assert a["publicat"] != a["vigoare"], "publicat is a copy of vigoare again"

        d = con.execute("SELECT publicat, monitor, republicare FROM documente").fetchone()
        assert d["publicat"] == _d(1962, 12, 30).isoformat()
        assert d["monitor"] == 28
        assert not d["republicare"]


def test_an_act_with_no_readable_monitor_line_stores_null_not_a_substitute(db):
    """22% of documents carry no readable line. NULL is the honest answer; a substitute is how
    this went wrong the first time."""
    from scripts.colector import act_din_inregistrare

    rec = _rec_mo("LEGE nr. 3 din 28 decembrie 1962 privind ceva, fără linie de publicare.")
    with depozit.deschide(db) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
        assert con.execute("SELECT publicat FROM acte").fetchone()["publicat"] is None
        assert con.execute("SELECT publicat FROM documente").fetchone()["publicat"] is None


def test_columns_are_added_to_a_corpus_collected_under_an_older_schema(db):
    """CREATE TABLE IF NOT EXISTS never adds a column to a table that already exists, so a new
    field would silently never reach a corpus that took hours to collect."""
    from scripts.colector import act_din_inregistrare

    rec = _rec_mo(
        "LEGE nr. 3 din 28 decembrie 1962 "
        "Publicat în MONITORUL OFICIAL nr. 28 din 30 decembrie 1962"
    )
    with depozit.deschide(db) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    # Simulate the pre-migration shape by dropping the column back off.
    import sqlite3 as _s

    raw = _s.connect(db)
    raw.execute("ALTER TABLE documente DROP COLUMN monitor")
    raw.commit()
    raw.close()

    with depozit.deschide(db) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(documente)")}
        assert "monitor" in cols, "the migration did not re-add the column"


def test_backfill_clears_a_date_it_cannot_source(db):
    """Half a backfill is worse than none: an act whose document carries no Monitorul Oficial
    line must end up NULL, not holding whatever `publicat` contained before — which was a copy
    of the in-force date. On the finished corpus that was 11 116 of 152 079 rows."""
    from scripts.colector import act_din_inregistrare
    from scripts.publicare import reciteste

    rec = _rec_mo("LEGE nr. 3 din 28 decembrie 1962, fără linie de publicare.")
    with depozit.deschide(db) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
        # Simulate the old write path, which put the in-force date in `publicat`.
        con.execute("UPDATE acte SET publicat = vigoare")
        assert con.execute("SELECT publicat FROM acte").fetchone()["publicat"] is not None

    reciteste(db, log=lambda *_: None)

    with depozit.deschide(db) as con:
        assert con.execute("SELECT publicat FROM acte").fetchone()["publicat"] is None
