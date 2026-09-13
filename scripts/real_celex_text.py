"""Validate and seed the bounded official CELEX text used by the real pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from scripts import articole_ue, cellar

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "real_celex_text_32014L0024.json"
CONTRACT = "real-celex-text-fixture-v1"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load(path: Path = FIXTURE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def manifestare(fixture: dict) -> cellar.ManifestareUE:
    return cellar.ManifestareUE(
        celex=fixture["celex"],
        work_uri=fixture["work_uri"],
        expression_uri=fixture["expression_uri"],
        manifestation_uri=fixture["manifestation_uri"],
        limba=fixture["language"],
        format=fixture["format"],
        item_url=fixture["item_url"],
        titlu=fixture["title"],
        data_document=fixture["document_date"],
        tip_uri=fixture["legal_type_uri"],
        in_vigoare=None,
    )


def validate(path: Path = FIXTURE) -> dict:
    fixture = load(path)
    problems: list[dict[str, str]] = []
    text = fixture.get("text") or ""
    text_sha256 = _sha(text)
    if fixture.get("contract") != CONTRACT:
        problems.append({"key": "contract", "message": "Unexpected CELEX fixture contract."})
    if fixture.get("text_sha256") != text_sha256:
        problems.append({"key": "text_sha256", "message": "CELEX fixture text hash mismatch."})
    if fixture.get("language") == "ENG" and fixture.get("language_state") != "official_en_fallback":
        problems.append(
            {"key": "language_state", "message": "English CELEX text must be explicit fallback."}
        )
    if fixture.get("language") == "RON" and fixture.get("fallback"):
        problems.append(
            {"key": "fallback", "message": "Romanian CELEX text cannot be marked fallback."}
        )

    snapshot = {
        "id": "fixture",
        "stare": "capturat",
        "sursa": {
            "celex": fixture.get("celex"),
            "limba": fixture.get("language"),
            "text": text,
            "text_sha256": text_sha256,
        },
    }
    article_summary = articole_ue.summary(snapshot)
    found = {row["locator"] for row in article_summary.get("randuri") or []}
    required = set((fixture.get("article_boundaries") or {}).get("required_locators") or [])
    missing = sorted(required - found)
    if missing:
        problems.append(
            {
                "key": "article_boundaries",
                "message": "Missing CELEX locators: " + ", ".join(missing),
            }
        )
    minimum = int((fixture.get("article_boundaries") or {}).get("minimum_articles") or 0)
    if article_summary.get("total", 0) < minimum:
        problems.append({"key": "article_boundaries", "message": "Too few parsed CELEX articles."})

    return {
        "contract": CONTRACT,
        "status": "blocked" if problems else "ready",
        "celex": fixture.get("celex"),
        "source_url": fixture.get("source_url"),
        "language": fixture.get("language"),
        "language_state": fixture.get("language_state"),
        "fallback": fixture.get("fallback"),
        "text_sha256": text_sha256,
        "articles": article_summary,
        "problems": problems,
        "limitations": [
            "Bounded retained official text fixture, not a bulk EUR-Lex import.",
            "Article boundaries are citation provenance, not a legal verdict.",
        ],
    }


def seed_database(stare, path: Path = FIXTURE) -> dict:
    fixture = load(path)
    m = manifestare(fixture)
    citit_la = datetime.now(UTC).isoformat()
    with cellar.deschide(str(stare.eu)) as con:
        cellar.scrie_celex(
            con, fixture["celex"], [m], replace(m, item_url=fixture["item_url"]), fixture["text"]
        )
        con.execute(
            "UPDATE eu_acte SET citit_la=?, sursa_url=?, text_sha256=? WHERE celex=?",
            (citit_la, fixture["source_url"], fixture["text_sha256"], fixture["celex"]),
        )
    return validate(path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    args = parser.parse_args(argv)
    print(json.dumps(validate(args.fixture), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
