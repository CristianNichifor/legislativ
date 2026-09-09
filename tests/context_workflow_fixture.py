"""Seed only this worktree's disposable context browser database."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import dosare, revizuiri


def main():
    root = Path(__file__).resolve().parents[1] / ".context-fixture"
    root.mkdir(exist_ok=True)
    state = SimpleNamespace(initiative=root / "initiative.db", date_dir=None)
    ident = uuid.uuid4().hex
    path = dosare.cale(state)
    dosare.creeaza(path, {"id": ident, "titlu": "FIXTURE context comparison"})
    report = {
        "gasit": True,
        "contradictii": {
            "candidati": [
                {
                    "tip": "definitie",
                    "termen": "FIXTURE scope",
                    "domeniu": {"cheie": "mediu", "eticheta": "Mediu", "dovezi": ["titlu: ape"]},
                    "a": {"act_id": "fixture-a", "locator": "art1", "text": "Fixture A"},
                    "b": {"act_id": "fixture-b", "locator": "art2", "text": "Fixture B"},
                }
            ]
        },
        "markdown": "Fixture only, no legal assessment",
    }
    with patch("scripts.servicii._matrice_dosar", return_value=report):
        run = dosare.salveaza_rulare(state, {"dosar_id": ident, "filtre": {"emitent": "P"}})
    finding = revizuiri.constatari(run)[0]["id"]
    for revision in range(22):
        context = {k: {"valoare": "", "citare": ""} for k in revizuiri.CONTEXT_FIELDS}
        context["teritoriu"] = {"valoare": "Fixture <img> territory", "citare": "A art.1"}
        context["aplicabil_de_la"] = {"valoare": "2026-01-01", "citare": "A art.3"}
        revizuiri.context_salveaza(
            path,
            {
                "id": uuid.uuid4().hex,
                "dosar_id": ident,
                "rulare_id": run["id"],
                "constatare_id": finding,
                "tinta": "a",
                "revizie": revision,
                "evaluator": "Fixture author",
                "motiv": "Fixture revision",
                "context": context,
            },
        )
    print(json.dumps({"id": ident, "run": run["id"], "finding": finding}))


if __name__ == "__main__":
    main()
