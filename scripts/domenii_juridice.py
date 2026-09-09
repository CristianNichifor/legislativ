"""Conservative legal-domain hints for matrix filtering.

The portal does not publish a subject taxonomy. These labels are therefore not a hidden truth from
the source, and they must never be presented as one. A domain exists here only when the act's title
or its issuing body contains a visible signal from this file; otherwise the act stays
``necunoscut``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class RegulaDomeniu:
    cheie: str
    eticheta: str
    termeni_titlu: tuple[str, ...]
    termeni_emitent: tuple[str, ...] = ()


REGULI: tuple[RegulaDomeniu, ...] = (
    RegulaDomeniu(
        "achizitii-publice",
        "achiziții publice",
        (
            "achiziție publică",
            "achiziții publice",
            "achizițiile publice",
            "achizițiilor publice",
            "contracte de achiziție",
            "concesiune de lucrări",
            "concesiune de servicii",
            "Sistemul Electronic de Achiziții Publice",
            "SEAP",
        ),
    ),
    RegulaDomeniu(
        "fiscal-bugetar",
        "fiscal / bugetar",
        (
            "Codul fiscal",
            "Codul de procedură fiscală",
            "impozit",
            "taxă",
            "TVA",
            "accize",
            "bugetul de stat",
            "bugetar",
            "creanțe fiscale",
        ),
        ("Ministerul Finanțelor", "Agenția Națională de Administrare Fiscală"),
    ),
    RegulaDomeniu(
        "sanatate",
        "sănătate",
        (
            "sănătate",
            "sănătății",
            "sanitar",
            "spital",
            "medicament",
            "asigurări sociale de sănătate",
            "pacient",
            "farmaceutic",
        ),
        ("Ministerul Sănătății", "Casa Națională de Asigurări de Sănătate"),
    ),
    RegulaDomeniu(
        "educatie",
        "educație",
        (
            "educație",
            "educația",
            "educației",
            "învățământ",
            "învățământului",
            "universitar",
            "elev",
            "student",
            "școală",
        ),
        ("Ministerul Educației",),
    ),
    RegulaDomeniu(
        "munca-protectie-sociala",
        "muncă / protecție socială",
        (
            "codul muncii",
            "salarii",
            "pensie",
            "pensiilor",
            "asigurări sociale",
            "șomaj",
            "protecție socială",
            "prestații sociale",
            "dialog social",
        ),
        ("Ministerul Muncii", "Casa Națională de Pensii"),
    ),
    RegulaDomeniu(
        "justitie-penal-civil",
        "justiție / penal / civil",
        (
            "Codul penal",
            "Codul civil",
            "Codul de procedură penală",
            "Codul de procedură civilă",
            "instanțe",
            "justiției",
            "procurori",
            "magistrați",
            "executarea pedepselor",
        ),
        ("Ministerul Justiției", "Consiliul Superior al Magistraturii"),
    ),
    RegulaDomeniu(
        "administratie-publica",
        "administrație publică",
        (
            "administrație publică",
            "funcționari publici",
            "prefect",
            "autorități publice locale",
            "consiliul local",
            "servicii publice comunitare",
        ),
    ),
    RegulaDomeniu(
        "mediu",
        "mediu",
        ("protecția mediului", "deșeuri", "ape", "păduri", "biodiversitate", "emisii", "poluare"),
        ("Ministerul Mediului", "Agenția Națională pentru Protecția Mediului"),
    ),
    RegulaDomeniu(
        "transporturi",
        "transporturi",
        ("transport", "drumuri", "feroviar", "rutier", "aerian", "naval"),
        ("Ministerul Transporturilor",),
    ),
    RegulaDomeniu(
        "energie",
        "energie",
        ("energie", "gaze naturale", "energie electrică", "petrol", "regenerabile"),
        ("Ministerul Energiei", "Autoritatea Națională de Reglementare în Domeniul Energiei"),
    ),
    RegulaDomeniu(
        "constructii-urbanism",
        "construcții / urbanism",
        (
            "construcții",
            "construcțiilor",
            "urbanism",
            "autorizarea executării",
            "locuințe",
            "cadastru",
        ),
    ),
    RegulaDomeniu(
        "agricultura",
        "agricultură",
        ("agricultură", "agriculturii", "silvicultură", "zootehnie", "pescuit"),
        ("Ministerul Agriculturii",),
    ),
)

NECUNOSCUT = {
    "cheie": "necunoscut",
    "eticheta": "domeniu necunoscut",
    "dovezi": [],
}


def _fold(text: str) -> str:
    fara_diacritice = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", fara_diacritice).strip()


def _potriviri(text: str, termeni: tuple[str, ...], sursa: str) -> list[str]:
    hay = _fold(text)
    out = []
    for termen in termeni:
        cautat = _fold(termen)
        if cautat and re.search(rf"(?<![a-z0-9]){re.escape(cautat)}(?![a-z0-9])", hay):
            out.append(f"{sursa}: {termen}")
    return out


def optiuni() -> list[dict]:
    """Filter options exposed by the API."""
    return [{"cheie": r.cheie, "eticheta": r.eticheta} for r in REGULI] + [NECUNOSCUT.copy()]


def chei_valide() -> set[str]:
    return {r.cheie for r in REGULI} | {"necunoscut"}


def clasifica(*, titlu: str = "", emitent: str = "") -> dict:
    """Classify only when the evidence is visible in metadata the corpus already stores."""
    candidati = []
    for regula in REGULI:
        titlu_hits = _potriviri(titlu or "", regula.termeni_titlu, "titlu")
        emitent_hits = _potriviri(emitent or "", regula.termeni_emitent, "emitent")
        if titlu_hits or emitent_hits:
            candidati.append(
                (len(titlu_hits) * 2 + len(emitent_hits), regula, titlu_hits + emitent_hits)
            )
    if not candidati:
        return NECUNOSCUT.copy()
    _, regula, dovezi = max(candidati, key=lambda x: (x[0], -REGULI.index(x[1])))
    return {"cheie": regula.cheie, "eticheta": regula.eticheta, "dovezi": dovezi[:4]}
