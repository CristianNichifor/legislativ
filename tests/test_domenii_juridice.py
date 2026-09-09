"""Tests for conservative legal-domain hints."""

from __future__ import annotations

from scripts import domenii_juridice


def test_domain_is_read_from_title_evidence_not_inferred():
    out = domenii_juridice.clasifica(
        titlu="Lege privind achizițiile publice și contractele de concesiune",
        emitent="Parlamentul",
    )

    assert out["cheie"] == "achizitii-publice"
    assert "titlu: achizițiile publice" in out["dovezi"]


def test_domain_can_be_read_from_specific_issuer():
    out = domenii_juridice.clasifica(
        titlu="Ordin pentru aprobarea normelor metodologice",
        emitent="Ministerul Sănătății",
    )

    assert out["cheie"] == "sanatate"
    assert out["dovezi"] == ["emitent: Ministerul Sănătății"]


def test_domain_stays_unknown_without_visible_signal():
    out = domenii_juridice.clasifica(titlu="Lege pentru modificarea unor acte normative")

    assert out == {"cheie": "necunoscut", "eticheta": "domeniu necunoscut", "dovezi": []}
