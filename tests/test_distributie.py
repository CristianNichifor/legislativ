"""Tests for cutting a distribution from the archive.

`corpus.db` keeps every document the service returned, including the 53 242 whose citation key
collided and whose text survives nowhere else — 3 977 MB of 6 400. A reader needs the acts, the
provisions, the index, the strikes and the graph, and none of the archive.

The two that matter: a distribution must still *be* a corpus, so every tool works against it
unchanged; and it must not carry `progres`, or the collector would resume from page numbers
describing somebody else's run.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.distributie import construieste


@pytest.fixture
def arhiva(tmp_path: Path) -> Path:
    """An archive with two documents sharing one citation key — the case `documente` exists for."""
    cale = tmp_path / "corpus.db"

    def rec(portal: str, emitent: str, text: str) -> Inregistrare:
        return Inregistrare(
            titlu="ORDIN nr. 1/1995",
            tip_act="ORDIN",
            numar="1",
            an=1995,
            data_vigoare=date(1995, 1, 1),
            emitent=emitent,
            publicatie="MO",
            link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{portal}",
            text=text,
        )

    with depozit.deschide(cale) as con:
        for p, e, t in (
            ("111", "Ministerul Finanțelor", "ORDIN nr. 1 despre achiziție publică de bunuri"),
            ("222", "Ministerul Sănătății", "ORDIN nr. 1 despre altceva cu totul"),
        ):
            r = rec(p, e, t)
            depozit.scrie_inregistrare(con, r, act_din_inregistrare(r))
        depozit.pagina_terminata(con, 1, 2)
    return cale


def _numar(cale: Path, tabel: str) -> int:
    con = sqlite3.connect(f"file:{cale}?mode=ro", uri=True)
    try:
        return con.execute(f"SELECT count(*) FROM {tabel}").fetchone()[0]
    finally:
        con.close()


def test_the_archive_is_not_shipped_but_no_act_is_left_behind_with_it(arhiva, tmp_path):
    """Two documents sharing a citation key are now two acts, so a distribution carries both.

    This used to assert the opposite, and the opposite was the bug: `acte` kept the last writer, so
    the other document existed only in `documente` — which a distribution deliberately does not
    ship. 53 242 documents of the real corpus were unreachable that way. `documente` still stays
    behind, because it is the archive and a distribution is not one, but nothing is now *only*
    there."""
    assert _numar(arhiva, "documente") == 2
    assert _numar(arhiva, "acte") == 2

    tinta = tmp_path / "dist.db"
    r = construieste(str(arhiva), str(tinta), log=lambda *_: None)

    assert r.acte == 2
    assert _numar(tinta, "documente") == 0, "the archive was shipped"
    assert _numar(tinta, "provizii") == _numar(arhiva, "provizii")


def test_a_distribution_is_still_a_corpus(arhiva, tmp_path):
    """Same schema, so every tool works against it unchanged — search included."""
    tinta = tmp_path / "dist.db"
    construieste(str(arhiva), str(tinta), log=lambda *_: None)

    with depozit.deschide(tinta, readonly=True) as con:
        rezultate = depozit.cauta(con, "altceva", 5)
        assert rezultate, "the rebuilt index found nothing"
        assert any(r["fragment"] for r in rezultate), "no snippet"


def test_the_namesake_is_searchable_in_the_distribution_too(arhiva, tmp_path):
    """The text that used to survive only in the archive.

    When two documents shared a citation key, `acte` and `provizii` kept the last writer, so the
    other one's words lived only in `documente` — which a distribution does not ship. This asserted
    that loss as a documented cost. It is now a regression test for the other direction: the
    namesake has its own act row, so its text ships and a reader can find it.
    """
    tinta = tmp_path / "dist.db"
    construieste(str(arhiva), str(tinta), log=lambda *_: None)

    with depozit.deschide(arhiva, readonly=True) as con:
        omonim = con.execute(
            "SELECT count(*) FROM documente WHERE text LIKE '%achizi%'"
        ).fetchone()[0]
        assert omonim, "fixture no longer exercises a collision"

    with depozit.deschide(tinta, readonly=True) as con:
        assert depozit.cauta(con, "achizitie", 5), (
            "the namesake's text is still missing from the distribution"
        )


def test_collection_progress_is_not_shipped(arhiva, tmp_path):
    """`progres` describes somebody else's run. A collector resuming from it would ask the
    service for pages this corpus never fetched, and call the result an update."""
    assert _numar(arhiva, "progres") == 1
    tinta = tmp_path / "dist.db"
    construieste(str(arhiva), str(tinta), log=lambda *_: None)
    assert _numar(tinta, "progres") == 0


def test_the_strikes_travel_so_the_register_needs_no_reparse(arhiva, tmp_path):
    """Extraction costs six minutes over the full corpus; a reader should not pay it again."""
    from scripts.lovituri import extrage, incarca

    extrage(arhiva, log=lambda *_: None)
    tinta = tmp_path / "dist.db"
    construieste(str(arhiva), str(tinta), log=lambda *_: None)
    assert _numar(tinta, "lovituri") == _numar(arhiva, "lovituri")
    assert len(incarca(str(tinta))) == len(incarca(str(arhiva)))


def test_the_archive_is_not_touched(arhiva, tmp_path):
    """It is opened read-only; a build that damaged the archive would be unrecoverable."""
    inainte = (arhiva.stat().st_size, _numar(arhiva, "documente"), _numar(arhiva, "acte"))
    construieste(str(arhiva), str(tmp_path / "dist.db"), log=lambda *_: None)
    assert (arhiva.stat().st_size, _numar(arhiva, "documente"), _numar(arhiva, "acte")) == inainte


def test_rebuilding_replaces_rather_than_appends(arhiva, tmp_path):
    """Cutting a release twice must not double the rows in it."""
    tinta = tmp_path / "dist.db"
    a = construieste(str(arhiva), str(tinta), log=lambda *_: None)
    b = construieste(str(arhiva), str(tinta), log=lambda *_: None)
    assert (a.acte, a.provizii) == (b.acte, b.provizii)
