"""Tests for keeping the portal's document pages instead of re-asking for them.

The property that carries this module is that **a document is asked for once, ever**. The corpus
already learned this twice — `publicare_incercata` and `lovituri_extrase` both exist because
resuming on "has no answer" re-read the whole corpus on every pass. Here it is not merely slow:
the thing being re-asked is a ministry's public server, and a job that re-requests every failure
on every run gets slower the longer it runs while hammering somebody else for an answer that will
not change.

The second property is that enrichment cannot make the corpus worse. An act whose page parses to
nothing keeps the flattened row it already had, and the act's own reconciled metadata — chiefly
`acte.publicat`, which cost a separate reconciliation pass — is never overwritten by a page parse.

No network: `_adu` is patched. What is being tested is the bookkeeping, which is where the
mistakes live.
"""

from __future__ import annotations

import gzip
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from scripts import depozit, surse
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare

PAGINA = """<html><body>
<div class="S_DEN">LEGE nr. 59/1993</div>
<div class="S_ART"><span class="S_ART_TTL">Articolul 5</span>
  <div class="S_ALN"><span class="S_ALN_TTL">(1)</span>
    <span class="S_ALN_BDY">Cererea se depune la instanța competentă.</span></div>
  <div class="S_ALN"><span class="S_ALN_TTL">(2)</span>
    <span class="S_ALN_BDY">Cererea se soluționează fără citarea părților.</span></div>
</div>
<div class="S_ART"><span class="S_ART_TTL">Articolul 6</span>
  <div class="S_ART_BDY">Hotărârea este definitivă.</div></div>
</body></html>"""


def _corpus(tmp_path: Path) -> Path:
    cale = tmp_path / "corpus.db"
    rec = Inregistrare(
        titlu="LEGE nr. 59/1993",
        tip_act="LEGE",
        numar="59",
        an=1993,
        data_vigoare=date(1993, 7, 1),
        emitent="PARLAMENTUL",
        publicatie="MO",
        link_html="http://legislatie.just.ro/Public/DetaliiDocument/591993",
        text="Art. 5 - text aplatizat, fără structură.",
    )
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
        con.execute(
            "INSERT INTO lovituri (id_portal, ord, cheie_act, publicat, definitiva, act,"
            " locator, fel, text) VALUES (?,?,?,?,?,?,?,?,?)",
            ("d1", 1, "decizie-9-1994", "1994-11-25", 1, "lege-59-1993", "art5.alin2", "n", "x"),
        )
    return cale


@pytest.fixture
def db(tmp_path):
    return _corpus(tmp_path)


@pytest.fixture
def adu(monkeypatch):
    """Count fetches, so 'asked once' is asserted rather than assumed."""
    apeluri: list[str] = []

    def fals(url: str):
        apeluri.append(url)
        return PAGINA.encode("utf-8"), "ok"

    monkeypatch.setattr(surse, "_adu", fals)
    return apeluri


def test_a_document_is_fetched_once_and_never_again(db, adu):
    """The load-bearing property. The second run must ask for nothing."""
    intai = surse.descarca(str(db), pauza=0, log=lambda *_: None)
    assert intai.cerute == 1 and intai.reusite == 1
    assert len(adu) == 1

    dupa = surse.descarca(str(db), pauza=0, log=lambda *_: None)
    assert dupa.cerute == 0, "re-asked for a document already stored"
    assert len(adu) == 1, "hit the ministry's server twice for the same page"


def test_a_failed_fetch_is_recorded_so_it_is_not_retried_every_run(db, monkeypatch):
    """A failure is an answer. Resuming on 'has no html' would re-ask for every refusal on every
    run — the mistake `publicare_incercata` and `lovituri_extrase` were each added to fix."""
    apeluri: list[str] = []

    def esueaza(url: str):
        apeluri.append(url)
        return None, "http-404"

    monkeypatch.setattr(surse, "_adu", esueaza)
    r = surse.descarca(str(db), pauza=0, log=lambda *_: None)
    assert (r.reusite, r.esuate) == (0, 1)

    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    assert len(apeluri) == 1, "retried a known failure"

    cx = sqlite3.connect(str(db))
    assert cx.execute("SELECT stare FROM surse").fetchone()[0] == "http-404"
    cx.close()


def test_a_network_failure_can_be_forgiven_but_a_404_cannot(db, monkeypatch):
    """Not every failure is an answer. A dropped connection is this end's problem and should not
    permanently cost a document; a 404 is the server's answer and re-asking changes nothing.
    Forgetting is a separate command on purpose — a run that silently re-asks is what the store
    exists to prevent."""
    monkeypatch.setattr(surse, "_adu", lambda url: (None, "retea"))
    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    assert surse.reincearca(str(db)) == 1

    monkeypatch.setattr(surse, "_adu", lambda url: (None, "http-404"))
    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    assert surse.reincearca(str(db)) == 0, "forgot a refusal the server had already given"


def test_only_the_acts_a_decision_struck_are_on_the_work_list(db, adu):
    """142 KB per act is 34 MB for the acts the register points at and 21 GB for all of them. The
    default work list is the one that pays for itself first."""
    with depozit.deschide(db) as con:
        rec = Inregistrare(
            titlu="LEGE nr. 200/2020",
            tip_act="LEGE",
            numar="200",
            an=2020,
            data_vigoare=date(2020, 1, 1),
            emitent="PARLAMENTUL",
            publicatie="MO",
            link_html="http://legislatie.just.ro/Public/DetaliiDocument/2002020",
            text="neatins de nicio decizie",
        )
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))

    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    assert len(adu) == 1
    assert "591993" in adu[0], "fetched an act no decision ever struck"


def test_the_stored_page_survives_the_round_trip(db, adu):
    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    cx = sqlite3.connect(str(db))
    try:
        brut = cx.execute("SELECT html, octeti, stare FROM surse").fetchone()
        assert brut[2] == "ok"
        assert brut[1] == len(PAGINA.encode("utf-8")), "stored size is not the uncompressed size"
        assert gzip.decompress(brut[0]).decode("utf-8") == PAGINA
        assert surse.html(cx, "591993") == PAGINA
    finally:
        cx.close()


def test_enrichment_turns_one_flattened_row_into_the_article_tree(db, adu):
    """The whole point: `provizii` goes from one `locator='text'` row to addressable units, so a
    struck `art5.alin2` can be quoted instead of guessed at."""
    cx = sqlite3.connect(str(db))
    inainte = cx.execute("SELECT locator FROM provizii WHERE act_id='lege-59-1993'").fetchall()
    cx.close()
    assert [r[0] for r in inainte] == ["text"]

    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    r = surse.imbogateste(str(db), log=lambda *_: None)
    assert r["imbunatatite"] == 1

    cx = sqlite3.connect(str(db))
    try:
        locatori = {
            x[0] for x in cx.execute("SELECT locator FROM provizii WHERE act_id='lege-59-1993'")
        }
        assert "text" not in locatori, "the flattened row survived alongside the tree"
        assert "art5.alin2" in locatori, f"got {sorted(locatori)}"
    finally:
        cx.close()


def test_enrichment_leaves_the_acts_own_metadata_alone(db, adu):
    """`acte.publicat` was reconciled against each document's Monitorul Oficial line in a separate
    pass. A page parse must not quietly overwrite it — that regression already happened once."""
    cx = sqlite3.connect(str(db))
    inainte = cx.execute("SELECT titlu, publicat, vigoare FROM acte").fetchone()
    cx.close()

    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    surse.imbogateste(str(db), log=lambda *_: None)

    cx = sqlite3.connect(str(db))
    try:
        assert cx.execute("SELECT titlu, publicat, vigoare FROM acte").fetchone() == inainte
    finally:
        cx.close()


def test_a_page_that_parses_to_nothing_leaves_the_act_as_it_was(db, monkeypatch):
    """A worse corpus is not an upgrade. Losing the flattened text to gain no structure would
    make the act unsearchable in exchange for nothing."""
    monkeypatch.setattr(surse, "_adu", lambda url: (b"<html><body>nimic</body></html>", "ok"))
    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    r = surse.imbogateste(str(db), log=lambda *_: None)
    assert r["imbunatatite"] == 0 and r["sarite"] == 1

    cx = sqlite3.connect(str(db))
    try:
        assert [x[0] for x in cx.execute("SELECT locator FROM provizii")] == ["text"]
    finally:
        cx.close()


def test_search_finds_the_new_units_and_not_the_withdrawn_one(db, adu):
    """`provizii_fts` is external-content: it keeps no copy, so a replaced row has to be handed
    back before it goes. An index still holding the flattened row would match an act for text it
    no longer contains — the quiet kind of wrong."""
    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    surse.imbogateste(str(db), log=lambda *_: None)

    with depozit.deschide(db, readonly=True) as con:
        gasite = depozit.cauta(con, "citarea", 5)
        assert gasite, "the new provisions were not indexed"
        assert any(g["locator"] == "art5.alin2" for g in gasite), gasite
        assert depozit.cauta(con, "aplatizat", 5) == [], "the withdrawn row still matches"


def test_the_summary_reports_what_is_held(db, adu):
    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    r = surse.rezumat(str(db))
    assert r == {"cerute": 1, "pastrate": 1, "octeti": r["octeti"]}
    assert 0 < r["octeti"] < len(PAGINA.encode("utf-8")), "not actually compressed"
