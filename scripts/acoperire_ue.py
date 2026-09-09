"""Coverage report for explicit EU legal references.

The CELEX importer can only help when we know which EU acts Romanian law and pending initiatives
actually cite. This module scans local text for deterministic EU references, checks which CELEX ids
are already imported in `eu.db`, and reports the missing queue. It is source coverage, not a
compatibility opinion.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterable
from itertools import chain
from pathlib import Path

from scripts import cellar, depozit
from scripts.referinte_ue import referinte_dict

SEMNAL_UE = (
    "celex",
    "regulament",
    "regulation",
    "directiv",
    "directive",
    "decizi",
    "decision",
    "euratom",
    " u.e.",
    " ue ",
    "/ue",
    " ce ",
    "cee",
)
LIMITARE = (
    "Acoperirea UE numără numai citările explicite CELEX/regulament/directivă/decizie "
    "pe care parserul determinist le poate normaliza; nu este analiză de conformitate."
)


def _are_tabel(con: sqlite3.Connection, tabel: str) -> bool:
    return (
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabel,)
        ).fetchone()
        is not None
    )


def _limita(valoare) -> int:
    try:
        return max(1, min(int(valoare), 500))
    except (TypeError, ValueError):
        return 50


def _posibil_text_ue(text: str) -> bool:
    t = f" {(text or '').casefold()} "
    return any(s in t for s in SEMNAL_UE)


def _snippet(text: str, start: int, end: int, raza: int = 110) -> str:
    text = text or ""
    if not text.strip():
        return ""
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    a = max(0, start - raza)
    b = min(len(text), end + raza)
    fragment = " ".join(text[a:b].split())
    return ("…" if a else "") + fragment.strip() + ("…" if b < len(text) else "")


def _randuri_corpus(cale: str | Path, limitari: list[str]) -> Iterable[dict]:
    cale = Path(cale)
    if not cale.is_file():
        limitari.append(f"{cale.name} lipsește; nu am scanat legile publicate.")
        return
    try:
        with depozit.deschide(cale, readonly=True) as con:
            if not (_are_tabel(con, "acte") and _are_tabel(con, "provizii")):
                limitari.append(f"{cale.name} nu are tabelele acte/provizii.")
                return
            for r in con.execute(
                "SELECT p.act_id, p.locator, p.text, a.titlu, a.sursa_url, a.id_act_portal"
                " FROM provizii p JOIN acte a ON a.id = p.act_id"
                " WHERE p.text LIKE '%CELEX%'"
                " OR p.text LIKE '%UE%'"
                " OR p.text LIKE '%U.E.%'"
                " OR p.text LIKE '%CEE%'"
                " OR p.text LIKE '%Euratom%'"
                " OR p.text LIKE '%Regulament%'"
                " OR p.text LIKE '%Directiv%'"
                " OR p.text LIKE '%Decizi%'"
                " OR p.text LIKE '%Regulation%'"
                " OR p.text LIKE '%Directive%'"
                " OR p.text LIKE '%Decision%'"
            ):
                if _posibil_text_ue(r["text"]):
                    yield {
                        "sursa": "corpus",
                        "id": r["act_id"],
                        "locator": r["locator"] or "",
                        "titlu": r["titlu"] or "",
                        "url": depozit.url_document(r["sursa_url"], r["id_act_portal"]),
                        "text": r["text"] or "",
                    }
            for r in con.execute(
                "SELECT id, titlu, sursa_url, id_act_portal FROM acte"
                " WHERE titlu LIKE '%CELEX%'"
                " OR titlu LIKE '%UE%'"
                " OR titlu LIKE '%U.E.%'"
                " OR titlu LIKE '%CEE%'"
                " OR titlu LIKE '%Euratom%'"
                " OR titlu LIKE '%Regulament%'"
                " OR titlu LIKE '%Directiv%'"
                " OR titlu LIKE '%Decizi%'"
                " OR titlu LIKE '%Regulation%'"
                " OR titlu LIKE '%Directive%'"
                " OR titlu LIKE '%Decision%'"
            ):
                if _posibil_text_ue(r["titlu"]):
                    yield {
                        "sursa": "corpus",
                        "id": r["id"],
                        "locator": "titlu",
                        "titlu": r["titlu"] or "",
                        "url": depozit.url_document(r["sursa_url"], r["id_act_portal"]),
                        "text": r["titlu"] or "",
                    }
    except sqlite3.Error as e:
        limitari.append(f"{cale.name} nu a putut fi citit: {e}")


def _randuri_initiative(cale: str | Path, limitari: list[str]) -> Iterable[dict]:
    cale = Path(cale)
    if not cale.is_file():
        limitari.append(f"{cale.name} lipsește; nu am scanat inițiativele parlamentare.")
        return
    try:
        with depozit.deschide(cale, readonly=True) as con:
            if not _are_tabel(con, "initiative"):
                limitari.append(f"{cale.name} nu are tabela initiative.")
                return
            for r in con.execute(
                "SELECT plx_id, senat_id, titlu, obiect, stadiu, sursa_url FROM initiative"
                " WHERE titlu LIKE '%CELEX%'"
                " OR obiect LIKE '%CELEX%'"
                " OR titlu LIKE '%UE%'"
                " OR obiect LIKE '%UE%'"
                " OR titlu LIKE '%U.E.%'"
                " OR obiect LIKE '%U.E.%'"
                " OR titlu LIKE '%CEE%'"
                " OR obiect LIKE '%CEE%'"
                " OR titlu LIKE '%Euratom%'"
                " OR obiect LIKE '%Euratom%'"
                " OR titlu LIKE '%Regulament%'"
                " OR obiect LIKE '%Regulament%'"
                " OR titlu LIKE '%Directiv%'"
                " OR obiect LIKE '%Directiv%'"
                " OR titlu LIKE '%Decizi%'"
                " OR obiect LIKE '%Decizi%'"
                " OR titlu LIKE '%Regulation%'"
                " OR obiect LIKE '%Regulation%'"
                " OR titlu LIKE '%Directive%'"
                " OR obiect LIKE '%Directive%'"
                " OR titlu LIKE '%Decision%'"
                " OR obiect LIKE '%Decision%'"
            ):
                text = "\n".join(x for x in (r["titlu"], r["obiect"]) if x)
                if _posibil_text_ue(text):
                    yield {
                        "sursa": "initiative",
                        "id": r["plx_id"],
                        "locator": r["senat_id"] or "",
                        "titlu": r["titlu"] or "",
                        "url": r["sursa_url"] or "",
                        "text": text,
                        "stadiu": r["stadiu"] or "",
                    }
    except sqlite3.Error as e:
        limitari.append(f"{cale.name} nu a putut fi citit: {e}")


def celex_importate(cale: str | Path, limitari: list[str] | None = None) -> set[str]:
    limitari = limitari if limitari is not None else []
    cale = Path(cale)
    if not cale.is_file():
        limitari.append(f"{cale.name} lipsește; toate referințele UE apar ca neimportate.")
        return set()
    try:
        with cellar.deschide(str(cale), readonly=True) as con:
            if not _are_tabel(con, "eu_acte"):
                limitari.append(f"{cale.name} nu are tabela eu_acte.")
                return set()
            return {r["celex"] for r in con.execute("SELECT celex FROM eu_acte")}
    except sqlite3.Error as e:
        limitari.append(f"{cale.name} nu a putut fi citit: {e}")
        return set()


def _adauga(
    agregate: dict[str, dict],
    ref: dict,
    rand: dict,
    importate: set[str],
    surse: dict[str, dict],
) -> None:
    celex = ref["celex"]
    sursa = rand["sursa"]
    surse[sursa]["mentionari"] += 1
    surse[sursa]["documente"].add(rand["id"])
    item = agregate.setdefault(
        celex,
        {
            "celex": celex,
            "fel": ref.get("fel") or "",
            "an": ref.get("an"),
            "numar": ref.get("numar") or "",
            "mentionari": 0,
            "surse": {},
            "importat": celex in importate,
            "exemple": [],
            "comanda_import": f"uv run python -m scripts.cellar {celex} --db eu.db",
        },
    )
    item["mentionari"] += 1
    item["surse"][sursa] = item["surse"].get(sursa, 0) + 1
    if len(item["exemple"]) < 3:
        item["exemple"].append(
            {
                "sursa": sursa,
                "id": rand["id"],
                "locator": rand.get("locator") or "",
                "titlu": rand.get("titlu") or "",
                "url": rand.get("url") or "",
                "text": ref.get("text") or "",
                "fragment": _snippet(
                    rand.get("text") or "", ref.get("start") or 0, ref.get("end") or 0
                ),
            }
        )


def raport(
    corpus: str | Path = "corpus.db",
    initiative: str | Path = "initiative.db",
    eu: str | Path = "eu.db",
    *,
    limita: int = 50,
) -> dict:
    limitari = [LIMITARE]
    importate = celex_importate(eu, limitari)
    agregate: dict[str, dict] = {}
    surse: dict[str, dict] = {
        "corpus": {"mentionari": 0, "documente": set()},
        "initiative": {"mentionari": 0, "documente": set()},
    }

    for rand in chain(_randuri_corpus(corpus, limitari), _randuri_initiative(initiative, limitari)):
        for ref in referinte_dict(rand["text"]):
            _adauga(agregate, ref, rand, importate, surse)

    randuri = sorted(
        agregate.values(),
        key=lambda r: (r["importat"], -r["mentionari"], r["celex"]),
    )
    total_importate = sum(1 for r in randuri if r["importat"])
    total_neimportate = len(randuri) - total_importate
    return {
        "sursa": "calculat",
        "total": len(randuri),
        "mentionari": sum(r["mentionari"] for r in randuri),
        "importate": total_importate,
        "neimportate": total_neimportate,
        "surse": {
            k: {"mentionari": v["mentionari"], "documente": len(v["documente"])}
            for k, v in surse.items()
        },
        "referinte": randuri[: _limita(limita)],
        "limitari": limitari,
    }


def _text(out: dict) -> str:
    linii = [
        f"CELEX citate: {out['total']} ({out['importate']} importate, {out['neimportate']} lipsă)",
        f"Menționări: {out['mentionari']}",
        "",
    ]
    for r in out["referinte"]:
        stare = "importat" if r["importat"] else "lipsește"
        linii.append(f"{r['celex']}  {stare}  {r['mentionari']} menționări")
        if not r["importat"]:
            linii.append(f"  {r['comanda_import']}")
    return "\n".join(linii)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="corpus.db")
    ap.add_argument("--initiative", default="initiative.db")
    ap.add_argument("--eu", default="eu.db")
    ap.add_argument("--limita", type=int, default=50)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = raport(a.corpus, a.initiative, a.eu, limita=a.limita)
    print(json.dumps(out, ensure_ascii=False, indent=2) if a.json else _text(out))


if __name__ == "__main__":
    main()
