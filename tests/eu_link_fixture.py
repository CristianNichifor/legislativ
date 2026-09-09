"""Disposable, local-only EU-link preview data; no external source acquisition."""

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import achizitii_ue, depozit, dosare, interventii_propuneri, propuneri, revizuiri
from tests.test_instantanee_ue import write


def main():
    root = Path(__file__).resolve().parents[1] / ".eu-link-fixture"
    root.mkdir(exist_ok=True)
    state = SimpleNamespace(
        initiative=Path(os.environ.get("EU_LINK_INITIATIVE_DB", root / "initiative.db")),
        corpus=root / "corpus.db",
        eu=root / "eu.db",
        date_dir=None,
    )
    # Explicit preview initiative data stays untouched; source fixtures stay in this worktree.
    for p in [state.corpus, *([] if "EU_LINK_INITIATIVE_DB" in os.environ else [state.initiative])]:
        with depozit.deschide(p):
            pass
    with depozit.deschide(state.corpus) as con:
        con.execute(
            "INSERT OR IGNORE INTO acte(id,sursa_url,citit_la,tip,titlu) "
            "VALUES (?,?,?,'lege','Fixture')",
            ("lege-98-2016", "https://legislatie.just.ro/fixture", "2026-01-01"),
        )
        if not con.execute("SELECT 1 FROM provizii WHERE act_id='lege-98-2016'").fetchone():
            con.execute(
                "INSERT INTO provizii(act_id,locator,ord,text) VALUES (?,?,?,?)",
                ("lege-98-2016", "art1", 1, "National fixture text."),
            )
    write(state, "Articolul 1\nObligatii\nObligatie UE de test.\nArticolul 2\nExceptii de test.")
    ident = uuid.uuid4().hex
    path = dosare.cale(state)
    dosare.creeaza(path, {"id": ident, "titlu": "FIXTURE EU linkage"})
    report = {
        "gasit": True,
        "contradictii": {
            "candidati": [
                {
                    "tip": "definitie",
                    "termen": "Fixture",
                    "domeniu": {"eticheta": "Fixture only"},
                    "a": {"act_id": "lege-98-2016", "locator": "art1", "text": "Fixture A"},
                    "b": {"act_id": "fixture-b", "locator": "art2", "text": "Fixture B"},
                }
            ]
        },
        "markdown": "Fixture, not a legal assessment",
    }
    with patch("scripts.servicii._matrice_dosar", return_value=report):
        run = dosare.salveaza_rulare(state, {"dosar_id": ident, "filtre": {"emitent": "P"}})
    finding = revizuiri.constatari(run)[0]["id"]
    intent = interventii_propuneri.pregateste(
        state,
        {
            "act_id": "lege-98-2016",
            "locator": "art1",
            "operatie": "modifica",
            "text_nou": "Text nou de test.",
            "articol_nou": "",
        },
    )
    propuneri.salveaza(
        path,
        {
            "id": uuid.uuid4().hex,
            "dosar_id": ident,
            "rulare_id": run["id"],
            "constatare_id": finding,
            "revizie": 0,
            "titlu": "Fixture proposal",
            "text": intent["text_compus"],
            "motiv": "Fixture",
            "interventie": intent["cerere"],
        },
        state,
    )
    snapshot = achizitii_ue.detaliu(state, "32018R1805")["curenta"]["id"]
    print(json.dumps({"id": ident, "run": run["id"], "finding": finding, "snapshot": snapshot}))


if __name__ == "__main__":
    main()
