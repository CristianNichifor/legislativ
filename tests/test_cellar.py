"""Tests for the Cellar CELEX source reader.

These tests pin the contract without touching the network: SPARQL results are Cellar-shaped JSON,
and document streams are small XHTML/plain fixtures.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

from scripts import cellar

RON_XHTML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b"<html><head><title>x</title><script>drop()</script></head><body>"
    b"<p>REGULAMENTUL (UE) 2018/1805</p>"
    b"<p>Articolul 1</p><p>Prezenta reglementare se aplic\xc4\x83.</p>"
    b"</body></html>"
)
RON_XHTML_2 = b"<html><body><p>Articolul 2</p><p>Anexa se aplic\xc4\x83.</p></body></html>"


class _Raspuns:
    def __init__(self, body: bytes, *, content_type: str = "application/json"):
        self._body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return self._body

    def geturl(self):
        return "mock://cellar"


def _binding(
    *,
    lang: str,
    fmt: str,
    item: str,
    title: str,
    in_force: str = "true",
    date: str = "2018-11-14",
) -> dict:
    expr_suffix = {"ENG": "0006", "RON": "0020"}.get(lang, "9999")
    return {
        "work": {"type": "uri", "value": "http://publications.europa.eu/resource/cellar/work"},
        "expr": {
            "type": "uri",
            "value": f"http://publications.europa.eu/resource/cellar/work.{expr_suffix}",
        },
        "manif": {
            "type": "uri",
            "value": f"http://publications.europa.eu/resource/cellar/work.{expr_suffix}.{fmt}",
        },
        "langCode": {"type": "literal", "value": lang},
        "format": {"type": "literal", "value": fmt},
        "item": {"type": "uri", "value": item},
        "title": {"type": "literal", "value": title},
        "date_document": {"type": "literal", "value": date},
        "legal_type": {"type": "uri", "value": "http://publications.europa.eu/type/regulation"},
        "in_force": {"type": "literal", "value": in_force},
    }


def _sparql(*bindings: dict) -> bytes:
    return json.dumps({"head": {"vars": []}, "results": {"bindings": list(bindings)}}).encode()


def _opener(bindings: bytes, docs: dict[str, bytes], calls: list | None = None):
    def deschide(req, timeout=0):
        if calls is not None:
            calls.append(req)
        if req.full_url == cellar.SPARQL_ENDPOINT:
            return _Raspuns(bindings, content_type="application/sparql-results+json")
        return _Raspuns(docs[req.full_url], content_type="application/xhtml+xml;charset=UTF-8")

    return deschide


def test_celex_is_normalized_from_plain_ids_and_urls():
    assert cellar.normalizeaza_celex("32018r1805") == "32018R1805"
    assert (
        cellar.normalizeaza_celex("https://publications.europa.eu/resource/celex/32018R1805")
        == "32018R1805"
    )
    assert (
        cellar.normalizeaza_celex(
            "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32018R1805"
        )
        == "32018R1805"
    )
    with pytest.raises(ValueError):
        cellar.normalizeaza_celex("32018R1805> . ?x ?y ?z")


def test_manifestations_are_sorted_by_language_then_readable_format():
    calls: list = []
    ron_pdf = "https://cellar/ron.pdf"
    ron_xhtml = "https://cellar/ron.xhtml"
    eng_xhtml = "https://cellar/eng.xhtml"
    manifestari = cellar.manifestari_celex(
        "32018r1805",
        opener=_opener(
            _sparql(
                _binding(lang="ENG", fmt="xhtml", item=eng_xhtml, title="English title"),
                _binding(lang="RON", fmt="pdfa1a", item=ron_pdf, title="Titlu română"),
                _binding(lang="RON", fmt="xhtml", item=ron_xhtml, title="Titlu română"),
            ),
            {},
            calls,
        ),
    )

    aleasa = cellar.alege_manifestare_text(manifestari)
    assert (aleasa.limba, aleasa.format, aleasa.item_url) == ("RON", "xhtml", ron_xhtml)

    query = urllib.parse.parse_qs(calls[0].data.decode())["query"][0]
    assert "http://publications.europa.eu/resource/celex/32018R1805" in query
    assert 'str(?langCode)="RON"' in query
    assert 'str(?langCode)="ENG"' in query


def test_english_is_the_fallback_when_romanian_is_absent():
    item = "https://cellar/eng.xhtml"
    manifestari = cellar.manifestari_celex(
        "32018R1805",
        opener=_opener(_sparql(_binding(lang="ENG", fmt="xhtml", item=item, title="Title")), {}),
    )

    assert cellar.alege_manifestare_text(manifestari).limba == "ENG"


def test_xhtml_text_is_extracted_without_scripts_and_with_block_breaks():
    text = cellar.extrage_text(RON_XHTML, content_type="application/xhtml+xml", format="xhtml")

    assert "drop" not in text
    assert "REGULAMENTUL (UE) 2018/1805" in text
    assert "Articolul 1\nPrezenta reglementare se aplică." in text


def test_pdf_is_not_silently_stored_as_text():
    with pytest.raises(cellar.TextIndisponibil):
        cellar.extrage_text(b"%PDF-1.7 binary", content_type="application/pdf", format="pdfa1a")


def test_importing_celex_writes_selected_text_and_all_manifestations(tmp_path: Path):
    db = tmp_path / "eu.db"
    ron_xhtml = "https://cellar/ron.xhtml"
    opener = _opener(
        _sparql(
            _binding(lang="ENG", fmt="xhtml", item="https://cellar/eng.xhtml", title="English"),
            _binding(lang="RON", fmt="pdfa1a", item="https://cellar/ron.pdf", title="Română"),
            _binding(lang="RON", fmt="xhtml", item=ron_xhtml, title="Română"),
        ),
        {ron_xhtml: RON_XHTML},
    )

    out = cellar.importa_celex("32018R1805", db=str(db), opener=opener)

    assert out["limba"] == "RON"
    assert out["format"] == "xhtml"
    assert out["manifestari"] == 3
    with cellar.deschide(str(db), readonly=True) as con:
        act = con.execute("SELECT * FROM eu_acte WHERE celex = ?", ("32018R1805",)).fetchone()
        assert act["limba"] == "RON"
        assert act["format"] == "xhtml"
        assert "Articolul 1" in act["text"]
        assert len(act["text_sha256"]) == 64
        manifestari = con.execute("SELECT count(*) FROM eu_manifestari").fetchone()[0]
        assert manifestari == 3


def test_importing_fetches_all_items_of_the_selected_manifestation(tmp_path: Path):
    db = tmp_path / "eu.db"
    doc1 = "https://cellar/ron.xhtml/DOC_1"
    doc2 = "https://cellar/ron.xhtml/DOC_2"
    opener = _opener(
        _sparql(
            _binding(lang="RON", fmt="xhtml", item=doc2, title="Română"),
            _binding(lang="RON", fmt="xhtml", item=doc1, title="Română"),
        ),
        {doc1: RON_XHTML, doc2: RON_XHTML_2},
    )

    cellar.importa_celex("32018R1805", db=str(db), opener=opener)

    with cellar.deschide(str(db), readonly=True) as con:
        text = con.execute("SELECT text FROM eu_acte WHERE celex = ?", ("32018R1805",)).fetchone()[
            0
        ]
    assert text.index("Articolul 1") < text.index("Articolul 2")
    assert "Anexa se aplică." in text


def test_no_manifestation_for_requested_languages_is_explicit():
    opener = _opener(
        _sparql(_binding(lang="FRA", fmt="xhtml", item="https://cellar/fr", title="FR")), {}
    )

    with pytest.raises(cellar.CelexNegasit):
        cellar.manifestari_celex("32018R1805", opener=opener)
