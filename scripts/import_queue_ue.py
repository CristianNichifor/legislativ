"""Read-only queue for CELEX acts that should be imported from Cellar.

The queue is deliberately derived from already-local evidence: the EU coverage report says which
CELEX ids Romanian acts cite, and `eu.db` says which of those ids are already imported. This module
does not call Cellar or EUR-Lex; it only returns official URLs and the local import command a
maintainer can run.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from scripts import cellar

LIMBI_IMPLICITE = ("RON", "ENG")
LIMITARE_COADA = (
    "Coada de import listează numai CELEX-urile lipsă din citările explicite detectate local; "
    "nu interoghează Cellar live și nu este analiză de conformitate."
)
STATUS_NEIMPORTAT = "neimportat"
STATUS_METADATA = "metadata_locala_fara_text"
EURLEX_LIMBI = {
    "RON": "RO",
    "ENG": "EN",
    "FRA": "FR",
    "DEU": "DE",
    "ITA": "IT",
    "SPA": "ES",
}


def _limita(valoare: int | str | None) -> int:
    try:
        return max(1, min(int(valoare), 200))
    except (TypeError, ValueError):
        return 50


def normalizeaza_limbi(limbi: Sequence[str] | str | None = None) -> tuple[str, ...]:
    """Language preference for a future Cellar import, validated without touching the network."""
    valori = limbi.split(",") if isinstance(limbi, str) else limbi or LIMBI_IMPLICITE
    out = tuple(dict.fromkeys(v.strip().upper() for v in valori if v and v.strip()))
    return out if out and all(re.fullmatch(r"[A-Z]{3}", v) for v in out) else LIMBI_IMPLICITE


def _are_tabel(con: sqlite3.Connection, tabel: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (tabel,)
        ).fetchone()
        is not None
    )


def _bucati(valori: set[str], marime: int = 400):
    lista = sorted(v for v in valori if v)
    for i in range(0, len(lista), marime):
        yield lista[i : i + marime]


def _stare_eu(
    cale: str | Path, celexuri: set[str], limitari: list[str]
) -> tuple[set[str], dict[str, list[dict]]]:
    cale = Path(cale)
    if not cale.is_file():
        limitari.append(f"{cale.name} lipsește; niciun CELEX din acoperire nu poate fi confirmat.")
        return set(), {}
    try:
        with cellar.deschide(str(cale), readonly=True) as con:
            importate: set[str] = set()
            manifestari: dict[str, list[dict]] = {}
            if _are_tabel(con, "eu_acte"):
                importate = {r["celex"] for r in con.execute("SELECT celex FROM eu_acte")}
            else:
                limitari.append(f"{cale.name} nu are tabela eu_acte.")
            if _are_tabel(con, "eu_manifestari") and celexuri:
                for bucata in _bucati(celexuri):
                    marci = ",".join("?" * len(bucata))
                    for r in con.execute(
                        "SELECT celex, limba, format, titlu, data_document, tip_uri,"
                        " in_vigoare, item_url"
                        f" FROM eu_manifestari WHERE celex IN ({marci})"
                        " ORDER BY celex, limba, format, item_url",
                        bucata,
                    ):
                        manifestari.setdefault(r["celex"], []).append(
                            {
                                "limba": r["limba"] or "",
                                "format": r["format"] or "",
                                "titlu": r["titlu"] or "",
                                "data_document": r["data_document"],
                                "tip_uri": r["tip_uri"] or "",
                                "in_vigoare": (
                                    None if r["in_vigoare"] is None else bool(r["in_vigoare"])
                                ),
                                "item_url": r["item_url"] or "",
                            }
                        )
            return importate, manifestari
    except sqlite3.Error as e:
        limitari.append(f"{cale.name} nu a putut fi citit: {e}")
        return set(), {}


def _celex(rand: dict, limitari: list[str]) -> str:
    brut = rand.get("celex") or ""
    try:
        return cellar.normalizeaza_celex(brut)
    except ValueError:
        if brut:
            limitari.append(f"CELEX invalid ignorat în acoperire: {brut}")
        return ""


def _referinte_locale(rand: dict) -> list[dict]:
    referinte = rand.get("referinte_locale") or rand.get("exemple") or []
    out: list[dict] = []
    for ref in referinte:
        if not isinstance(ref, dict):
            continue
        out.append(
            {
                "sursa": ref.get("sursa") or "",
                "id": ref.get("id") or "",
                "locator": ref.get("locator") or "",
                "titlu": ref.get("titlu") or "",
                "url": ref.get("url") or "",
                "text": ref.get("text") or "",
                "fragment": ref.get("fragment") or "",
            }
        )
    return out


def _surse_oficiale(celex: str, limbi: tuple[str, ...]) -> list[dict]:
    surse = [
        {
            "tip": "publications_office_celex",
            "eticheta": "Publications Office CELEX",
            "url": cellar.CELEX_URI.format(celex=celex),
        }
    ]
    for limba in limbi:
        cod = EURLEX_LIMBI.get(limba)
        if not cod:
            continue
        surse.append(
            {
                "tip": "eurlex_text",
                "eticheta": f"EUR-Lex {cod}",
                "limba": limba,
                "url": f"https://eur-lex.europa.eu/legal-content/{cod}/TXT/?uri=CELEX:{celex}",
            }
        )
    return surse


def _status_limba(manifestari: list[dict], limbi: tuple[str, ...]) -> str:
    if not manifestari:
        return (
            f"{limbi[0]} este preferată la import; disponibilitatea nu este verificată "
            "fără interogare Cellar."
        )
    disponibile = {m.get("limba") for m in manifestari}
    if limbi[0] in disponibile:
        return f"{limbi[0]} apare în metadata Cellar stocată local."
    fallback = next((limba for limba in limbi[1:] if limba in disponibile), "")
    if fallback:
        return f"{limbi[0]} nu apare în metadata locală; {fallback} apare ca fallback."
    return "Metadata locală există, dar nu pentru limbile preferate."


def _ghid_import(celex: str, limbi: tuple[str, ...]) -> dict:
    limbi_csv = ",".join(limbi)
    return {
        "comanda": f"uv run python -m scripts.cellar {celex} --db eu.db --limbi {limbi_csv}",
        "limbi": list(limbi),
        "dupa_import": "Refă acoperirea UE sau build-ul static ca CELEX-ul să dispară din coadă.",
    }


def _rand_coada(rand: dict, celex: str, manifestari: list[dict], limbi: tuple[str, ...]) -> dict:
    referinte = _referinte_locale(rand)
    return {
        "celex": celex,
        "status": STATUS_METADATA if manifestari else STATUS_NEIMPORTAT,
        "limba_preferata": limbi[0],
        "limbi_import": list(limbi),
        "limba_status": _status_limba(manifestari, limbi),
        "mentionari": int(rand.get("mentionari") or len(referinte)),
        "surse_locale": dict(rand.get("surse") or {}),
        "referinte_locale": referinte,
        "manifestari_locale": manifestari,
        "surse_oficiale": _surse_oficiale(celex, limbi),
        "ghid_import": _ghid_import(celex, limbi),
    }


def coada_import(
    acoperire: dict,
    eu: str | Path = "eu.db",
    *,
    limita: int | str | None = 50,
    limbi: Sequence[str] | str | None = None,
    sursa: str = "calculat",
) -> dict:
    """Return CELEX ids from coverage that are still absent from `eu_acte`."""
    limita_i = _limita(limita)
    limbi_i = normalizeaza_limbi(limbi)
    limitari = [LIMITARE_COADA]
    if isinstance(acoperire, dict):
        referinte = [r for r in acoperire.get("referinte", []) if isinstance(r, dict)]
        for limita_text in acoperire.get("limitari") or []:
            if limita_text not in limitari:
                limitari.append(limita_text)
    else:
        referinte = []
        limitari.append("Raportul de acoperire UE lipsește sau are format invalid.")

    referinte_normalizate: list[tuple[dict, str]] = []
    celexuri: set[str] = set()
    for rand in referinte:
        celex = _celex(rand, limitari)
        referinte_normalizate.append((rand, celex))
        celexuri.add(celex)
    celexuri.discard("")
    importate, manifestari = _stare_eu(eu, celexuri, limitari)

    vazute: set[str] = set()
    randuri: list[dict] = []
    for rand, celex in referinte_normalizate:
        if not celex or celex in vazute:
            continue
        vazute.add(celex)
        if celex in importate:
            continue
        randuri.append(_rand_coada(rand, celex, manifestari.get(celex, []), limbi_i))

    randuri.sort(key=lambda r: (-r["mentionari"], r["celex"]))
    total = len(randuri)
    return {
        "sursa": sursa,
        "total": total,
        "afisate": min(total, limita_i),
        "limba_preferata": limbi_i[0],
        "limbi_import": list(limbi_i),
        "randuri": randuri[:limita_i],
        "acoperire": {
            "total": acoperire.get("total", 0) if isinstance(acoperire, dict) else 0,
            "importate": acoperire.get("importate", 0) if isinstance(acoperire, dict) else 0,
            "neimportate": acoperire.get("neimportate", 0) if isinstance(acoperire, dict) else 0,
        },
        "limitari": limitari,
    }
