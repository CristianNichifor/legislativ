from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from scripts import achizitii_ue, real_celex_text

ROOT = Path(__file__).resolve().parents[1]


def test_real_celex_text_schema_validates_fixture():
    schema = json.loads((ROOT / "schema/real_celex_text.schema.json").read_text())
    fixture = json.loads((ROOT / "data/real_celex_text_32014L0024.json").read_text())

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(fixture)


def test_real_celex_text_fixture_is_hash_checked_and_article_bounded():
    result = real_celex_text.validate()

    assert result["status"] == "ready"
    assert result["celex"] == "32014L0024"
    assert result["language"] == "RON"
    assert result["language_state"] == "official_ro"
    assert result["fallback"] is False
    assert len(result["text_sha256"]) == 64
    assert result["articles"]["contract"] == "celex-article-boundary-v1"
    assert result["articles"]["total"] >= 1
    assert result["articles"]["randuri"][0]["locator"] == "art1"
    assert result["articles"]["randuri"][0]["boundary"]["language"] == "RON"
    assert result["problems"] == []
    assert "not a bulk EUR-Lex import" in result["limitations"][0]


def test_real_celex_text_can_seed_existing_celex_detail_contract(tmp_path):
    state = SimpleNamespace(eu=tmp_path / "eu.db")

    real_celex_text.seed_database(state)
    detail = achizitii_ue.detaliu(state, "32014L0024")

    assert detail["stare"] == "text_disponibil"
    assert detail["curenta"]["sursa"]["limba"] == "RON"
    assert detail["curenta"]["source_metadata"]["celex"] == "32014L0024"
    assert detail["curenta"]["source_metadata"]["celex_url"].startswith(
        "https://eur-lex.europa.eu/"
    )
    assert detail["curenta"]["articole"]["randuri"][0]["locator"] == "art1"
    assert (
        detail["curenta"]["articole"]["randuri"][0]["boundary"]["contract"]
        == "celex-article-boundary-v1"
    )


def test_real_celex_text_detects_tampered_hash(tmp_path):
    fixture = json.loads((ROOT / "data/real_celex_text_32014L0024.json").read_text())
    fixture["text_sha256"] = "0" * 64
    path = tmp_path / "celex.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    result = real_celex_text.validate(path)

    assert result["status"] == "blocked"
    assert result["problems"] == [
        {"key": "text_sha256", "message": "CELEX fixture text hash mismatch."}
    ]
