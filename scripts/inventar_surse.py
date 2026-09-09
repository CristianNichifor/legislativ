"""Read-only inventory of available local evidence, not a completeness verdict."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

MAX_PROGRESS_CALLBACKS = 20_000

# Fixed queries only: neither HTTP query parameters nor database contents become SQL.
METRICE = {
    "corpus": {
        "acte": "SELECT count(*) FROM acte",
        "documente": "SELECT count(*) FROM documente",
        "prevederi": "SELECT count(*) FROM provizii",
        "acte_cu_prevederi": (
            "SELECT count(*) FROM acte WHERE EXISTS "
            "(SELECT 1 FROM provizii WHERE act_id=acte.id AND trim(text) <> '')"
        ),
        "acte_cu_structura": (
            "SELECT count(*) FROM acte WHERE EXISTS (SELECT 1 FROM provizii "
            "WHERE act_id=acte.id AND locator <> 'text' AND trim(text) <> '')"
        ),
        "surse_incercate": "SELECT count(*) FROM surse",
        "surse_reusite": "SELECT count(*) FROM surse WHERE stare='ok' AND html IS NOT NULL",
        "surse_esuate": "SELECT count(*) FROM surse WHERE stare<>'ok' OR html IS NULL",
        "documente_fara_sursa_reusita": (
            "SELECT count(*) FROM documente WHERE NOT EXISTS (SELECT 1 FROM surse "
            "WHERE surse.id_portal=documente.id_portal AND stare='ok' AND html IS NOT NULL)"
        ),
        "ultima_incercare_sursa": "SELECT datetime(max(julianday(incercat_la))) FROM surse",
        "ultima_reusita_sursa": (
            "SELECT datetime(max(julianday(incercat_la))) FROM surse "
            "WHERE stare='ok' AND html IS NOT NULL"
        ),
        "ultima_pagina_colectata": "SELECT datetime(max(julianday(terminat_la))) FROM progres",
        "ultimul_document_stocat": "SELECT datetime(max(julianday(adus_la))) FROM documente",
    },
    "initiative": {
        "initiative": "SELECT count(*) FROM initiative",
        "initiative_cu_tinte": (
            "SELECT count(*) FROM initiative WHERE EXISTS "
            "(SELECT 1 FROM initiative_tinta WHERE plx_id=initiative.plx_id)"
        ),
        "ultima_inregistrare_stocata": "SELECT datetime(max(julianday(citit_la))) FROM initiative",
    },
    "ue": {
        "acte": "SELECT count(*) FROM eu_acte",
        "prevederi": "SELECT count(*) FROM eu_provizii",
        "acte_cu_prevederi": (
            "SELECT count(*) FROM eu_acte WHERE EXISTS "
            "(SELECT 1 FROM eu_provizii WHERE celex=eu_acte.celex AND trim(text) <> '')"
        ),
        "acte_romana": "SELECT count(*) FROM eu_acte WHERE limba='RON'",
        "acte_engleza": "SELECT count(*) FROM eu_acte WHERE limba='ENG'",
        "ultima_inregistrare_stocata": "SELECT datetime(max(julianday(citit_la))) FROM eu_acte",
    },
    "importuri": {
        "versiuni": "SELECT count(*) FROM documente",
        "extrase": "SELECT count(*) FROM documente WHERE status='extras'",
        "ocr_necesar": "SELECT count(*) FROM documente WHERE status='ocr_necesar'",
        "fara_text": "SELECT count(*) FROM documente WHERE status='fara_text'",
        "status_necunoscut": (
            "SELECT count(*) FROM documente WHERE status IS NULL "
            "OR status NOT IN ('extras', 'ocr_necesar', 'fara_text')"
        ),
        "ultima_inregistrare_stocata": "SELECT datetime(max(julianday(preluat_la))) FROM documente",
    },
}


def _sursa(cale: Path, fel: str) -> dict:
    out = {
        "stare": "lipsa",
        "actualitate": "necunoscuta",
        "ultima_sincronizare_completa": None,
        "sqlite_user_version": None,
        "metrici": {k: {"stare": "indisponibil", "valoare": None} for k in METRICE[fel]},
    }
    try:
        if not cale.exists():
            return out
        # URI escaping matters for ordinary filenames containing '?' or '#'. No migrations.
        with closing(
            sqlite3.connect(cale.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        ) as con:
            con.execute("PRAGMA query_only=ON")
            # Bound work on unexpectedly large/expensive databases; partial metrics stay explicit.
            budget = 0

            def stop():
                nonlocal budget
                budget += 1
                return budget > MAX_PROGRESS_CALLBACKS

            con.set_progress_handler(stop, 10_000)
            con.execute("BEGIN")
            out["sqlite_user_version"] = con.execute("PRAGMA user_version").fetchone()[0]
            out["stare"] = "disponibil"
            for key, query in METRICE[fel].items():
                try:
                    value = con.execute(query).fetchone()[0]
                    out["metrici"][key] = {
                        "stare": "masurat" if value is not None else "necunoscut",
                        "valoare": value,
                    }
                except sqlite3.Error:
                    out["stare"] = "partial"
    except (OSError, sqlite3.Error):
        out["stare"] = "inaccesibil"
    return out


def raport(corpus="corpus.db", initiative="initiative.db", eu="eu.db") -> dict:
    return {
        "schema_version": 1,
        "generat_la": datetime.now(UTC).isoformat(),
        "mod": "local_readonly",
        "acoperire_juridica": "necunoscuta",
        "surse": {
            fel: _sursa(Path(cale), fel)
            for fel, cale in {
                "corpus": corpus,
                "initiative": initiative,
                "ue": eu,
                "importuri": Path(initiative).with_suffix(".documente.db"),
            }.items()
        },
        "limitari": [
            "Inventar local, nu verdict de completitudine sau compatibilitate juridică.",
            "Zero măsurat diferă de o metrică indisponibilă sau o dată necunoscută.",
            "Datele stocării nu dovedesc o sincronizare completă sau actualitatea sursei oficiale.",
            "Sursele HTML păstrează ultima încercare per document, nu istoricul complet.",
            "Numărătorile actelor, documentelor și prevederilor au populații distincte.",
            "Structura înseamnă locator diferit de 'text', nu extragere verificată juridic.",
            "Schema SQLite user_version=0 nu certifică versiunea migrărilor aplicației.",
            "Nu se verifică integritatea indexului FTS sau întregul corpus oficial.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="corpus.db")
    parser.add_argument("--initiative", default="initiative.db")
    parser.add_argument("--eu", default="eu.db")
    args = parser.parse_args()
    print(json.dumps(raport(args.corpus, args.initiative, args.eu), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
