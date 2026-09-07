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


# --- îmbogățirea nu are voie să piardă text ------------------------------------------------------

PAGINA_SARACA = """<html><body>
<div class="S_DEN">LEGE nr. 59/1993</div>
<div class="S_ART"><span class="S_ART_TTL">Articolul 1</span>
  <div class="S_ART_BDY">privind ceva</div></div>
<div class="S_ART"><span class="S_ART_TTL">Articolul 2</span>
  <div class="S_ART_BDY">(actualizată)</div></div>
</body></html>"""


def _corpus_cu_arhiva_lunga(tmp_path: Path) -> Path:
    """An act whose archived text is substantial — the case the count check could not see."""
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
        text="Articolul 1 " + "Dispoziții care se aplică tuturor situațiilor. " * 80,
    )
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    return cale


def test_a_parse_that_would_lose_text_is_refused(tmp_path, monkeypatch):
    """The bug this guard exists for. `len(provizii) <= 1` is a count, so a page yielding two
    header fragments passed it and replaced the act: measured over the corpus, the Codul vamal
    went from 79 865 characters to 95, and 54% of enriched acts held less than the archive."""
    db = _corpus_cu_arhiva_lunga(tmp_path)
    monkeypatch.setattr(surse, "_adu", lambda url: (PAGINA_SARACA.encode("utf-8"), "ok"))
    surse.descarca(str(db), candidati=["591993"], pauza=0, log=lambda *_: None)

    r = surse.imbogateste(str(db), log=lambda *_: None)
    assert r["imbunatatite"] == 0
    assert r["pierdute"] == 1

    cx = sqlite3.connect(str(db))
    try:
        randuri = cx.execute("SELECT locator, length(text) FROM provizii").fetchall()
    finally:
        cx.close()
    assert [x[0] for x in randuri] == ["text"], "actul a fost înlocuit cu fragmente"
    assert randuri[0][1] > 3000


def test_a_parse_that_keeps_the_text_is_still_accepted(db, adu):
    """The guard must not refuse a real article tree. A correct parse exceeds the flat text,
    because provisions are stored at every level and an article's words count again below it."""
    surse.descarca(str(db), pauza=0, log=lambda *_: None)
    r = surse.imbogateste(str(db), log=lambda *_: None)
    assert r["imbunatatite"] == 1 and r["pierdute"] == 0


def test_progress_is_reported_even_when_every_act_is_refused(tmp_path, monkeypatch):
    """The log used to sit after the `continue` of every rejection, so a run refusing most acts
    printed nothing: 100 754 acts to walk, four gigabytes read, one line of output. It read as a
    hang and was diagnosed as one. A run that is working must say so."""
    db = _corpus_cu_arhiva_lunga(tmp_path)
    monkeypatch.setattr(surse, "_adu", lambda url: (PAGINA_SARACA.encode("utf-8"), "ok"))
    surse.descarca(str(db), candidati=["591993"], pauza=0, log=lambda *_: None)

    linii: list[str] = []
    r = surse.imbogateste(str(db), log=linii.append)
    assert r["pierdute"] == 1 and r["imbunatatite"] == 0
    assert any("refuzate" in x for x in linii), "o rulare care refuză tot nu a raportat nimic"


def test_the_refusal_is_measured_against_the_archive_not_the_current_rows(tmp_path, monkeypatch):
    """Comparing against the act's current provisions would compare against the damage: a second
    run over an act already emptied finds the parse no worse than the fragments and accepts it."""
    db = _corpus_cu_arhiva_lunga(tmp_path)
    monkeypatch.setattr(surse, "_adu", lambda url: (PAGINA_SARACA.encode("utf-8"), "ok"))
    surse.descarca(str(db), candidati=["591993"], pauza=0, log=lambda *_: None)
    for _ in range(2):
        r = surse.imbogateste(str(db), reia=False, log=lambda *_: None)
        assert r["imbunatatite"] == 0, "a doua rulare a acceptat ce prima a refuzat"

    cx = sqlite3.connect(str(db))
    try:
        assert [x[0] for x in cx.execute("SELECT locator FROM provizii")] == ["text"]
    finally:
        cx.close()


PAGINA_FARA_PREAMBUL = """<html><body>
<div class="S_DEN">LEGE nr. 59/1993</div>
<div class="S_ART"><span class="S_ART_TTL">Articolul 1</span>
  <div class="S_ART_BDY">CORP_UNU</div></div>
<div class="S_ART"><span class="S_ART_TTL">Articolul 2</span>
  <div class="S_ART_BDY">CORP_DOI</div></div>
</body></html>"""


def test_a_parse_that_only_drops_the_preamble_is_accepted(tmp_path, monkeypatch):
    """The comparison used to be against the whole archive, preamble included — and the preamble is
    exactly what a correct parse leaves out. On a short act it is a quarter of the characters, so
    acts whose every article had been recovered were refused for losing their title. Measured over
    767 of them, body-against-body accepts 415 the old rule rejected."""
    corp_unu = "Se aplică tuturor situațiilor prevăzute mai jos. " * 12
    corp_doi = "Prezenta intră în vigoare la publicare. " * 12
    preambul = (
        "ACORD din 15 februarie 1974 de cooperare între guvernul României și guvernul Suediei "
        "BULETINUL OFICIAL nr. 169 din 30 decembrie 1974. Părțile contractante, dorind să "
        "dezvolte colaborarea, au convenit următoarele: "
    )
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
        text=preambul + "Articolul 1 " + corp_unu + "\nArticolul 2 " + corp_doi,
    )
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))

    pagina = PAGINA_FARA_PREAMBUL.replace("CORP_UNU", corp_unu).replace("CORP_DOI", corp_doi)
    monkeypatch.setattr(surse, "_adu", lambda url: (pagina.encode("utf-8"), "ok"))
    surse.descarca(str(cale), candidati=["591993"], pauza=0, log=lambda *_: None)

    r = surse.imbogateste(str(cale), log=lambda *_: None)
    assert r["imbunatatite"] == 1 and r["pierdute"] == 0

    cx = sqlite3.connect(str(cale))
    try:
        locatori = [x[0] for x in cx.execute("SELECT locator FROM provizii ORDER BY ord")]
    finally:
        cx.close()
    assert "art1" in locatori and "art2" in locatori


def test_an_archive_with_no_article_marker_is_compared_whole(tmp_path, monkeypatch):
    """The conservative reading: an act this cannot locate a body in is one to leave alone."""
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
        text="Preambul fără nicio structură de articole. " * 40,
    )
    with depozit.deschide(cale) as con:
        depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    monkeypatch.setattr(surse, "_adu", lambda url: (PAGINA_SARACA.encode("utf-8"), "ok"))
    surse.descarca(str(cale), candidati=["591993"], pauza=0, log=lambda *_: None)
    assert surse.imbogateste(str(cale), log=lambda *_: None)["pierdute"] == 1


def test_the_default_work_list_is_narrow_and_the_whole_corpus_is_a_choice(tmp_path):
    """`de_lovituri` is the list that pays for itself first — the acts a decision struck — and it
    is also the default, so a plain `descarca` never reached the rest. That is why 33 710 acts
    have no row in `surse` at all: not fetched and failed, never asked for. Every one of them is
    stored as a single flat provision, a 100% correlation and the diagnosis for half the corpus
    having no article tree."""
    from scripts import depozit
    from scripts.surse import de_lovituri, de_tot

    cale = tmp_path / "corpus.db"
    with depozit.deschide(cale) as con:
        for id_portal, act_id, an in (("1", "lege-1-1990", 1990), ("2", "lege-2-2024", 2024)):
            con.execute(
                "INSERT INTO acte (id, tip, numar, an, titlu, id_portal, sursa_url, citit_la)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (act_id, "lege", act_id.split("-")[1], an, "T", id_portal, "http://x", "x"),
            )
        con.execute(
            "INSERT INTO lovituri (id_portal, ord, cheie_act, act, locator, fel, text)"
            " VALUES ('9', 1, 'decizie-1-2020', 'lege-1-1990', 'art1', 'neconstitutional', 't')"
        )
        con.commit()
    with depozit.deschide(cale, readonly=True) as con:
        assert de_lovituri(con) == ["1"], "lista implicită nu mai e cea îngustă"
        # Struck first, then the rest newest-first: a run cut short should have done the law
        # people are reading rather than an alphabetical prefix.
        assert de_tot(con) == ["1", "2"]
