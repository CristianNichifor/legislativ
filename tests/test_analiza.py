"""Tests for the corpus analysis.

Built on a small corpus assembled in the test, so the assertions do not drift with whatever the
collector has reached. What is checked is that the deterministic extractors reach the stored text
and that the pass reports its own scope rather than implying full coverage.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts import depozit
from scripts.analiza import obligatii_corpus, rezumat, termeni_corpus
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare


def _corpus(tmp_path: Path, *texts) -> Path:
    db = tmp_path / "c.db"
    with depozit.deschide(db) as con:
        for i, text in enumerate(texts, start=1):
            rec = Inregistrare(
                titlu=f"LEGE nr. {i} din 2024",
                tip_act="LEGE",
                numar=str(i),
                an=None,
                data_vigoare=date(2024, 1, 1),
                emitent="PARLAMENTUL",
                publicatie="MO",
                link_html=f"http://legislatie.just.ro/Public/DetaliiDocument/{i}00",
                text=text,
            )
            depozit.scrie_inregistrare(con, rec, act_din_inregistrare(rec))
    return db


def test_deadlines_are_read_from_the_stored_text(tmp_path):
    db = _corpus(
        tmp_path,
        "În termen de 30 de zile de la intrarea în vigoare, Guvernul aprobă normele metodologice.",
        "Prezenta lege reglementează cizmele de cauciuc și nimic altceva.",
    )
    with depozit.deschide(db, readonly=True) as con:
        found = list(obligatii_corpus(con))
    assert len(found) == 1
    assert found[0].obligatie.termen_zile == 30
    assert found[0].act.id == "lege-1-2024"


def test_definitions_across_the_corpus_form_the_dictionary(tmp_path):
    db = _corpus(
        tmp_path,
        "Art. 3. - În sensul prezentei legi, termenii de mai jos au următoarele semnificații:\n"
        "a) achiziție publică - achiziția de lucrări sau servicii;",
    )
    with depozit.deschide(db, readonly=True) as con:
        termeni = termeni_corpus(con)
    assert any(t.termen == "achiziție publică" for t in termeni)


def test_the_summary_states_its_own_scope(tmp_path):
    db = _corpus(
        tmp_path,
        "În termen de 60 de zile de la publicare, ministrul emite ordinul de aplicare.",
    )
    with depozit.deschide(db, readonly=True) as con:
        r = rezumat(con)
    assert r["obligatii"] == 1 and r["obligatii_cu_termen"] == 1
    assert r["obligatii_cu_instrument"] == 1  # 'ordinul' recognised


def test_analysis_reads_without_writing(tmp_path):
    """It must run against a corpus another process is writing, so it opens read-only and never
    creates or alters a row."""
    db = _corpus(tmp_path, "text oarecare fără obligații")
    with depozit.deschide(db, readonly=True) as con:
        list(obligatii_corpus(con))
        assert rezumat(con)["obligatii"] == 0
