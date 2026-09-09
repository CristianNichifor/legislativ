"""Disposable dossier backup for browser transport tests, using existing EU fixtures."""

import contextlib
import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from scripts import dosare, legaturi_ue_store
from tests import eu_link_fixture
from tests.test_legaturi_ue_store import request


def main():
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        eu_link_fixture.main()
    seed = json.loads(captured.getvalue())
    root = Path(__file__).resolve().parents[1] / ".eu-link-fixture"
    state = SimpleNamespace(
        initiative=root / "initiative.db",
        corpus=root / "corpus.db",
        eu=root / "eu.db",
        date_dir=None,
    )
    selection = dict(
        dosar_id=seed["id"],
        rulare_id=seed["run"],
        constatare_id=seed["finding"],
        revizie=1,
        celex="32018R1805",
        instantanee=seed["snapshot"],
        locator="art1",
    )
    link = legaturi_ue_store.salveaza(
        state,
        {**request(state, selection), "id": uuid.uuid4().hex, "obligatie": "Obligatie UE de test."},
    )
    print(json.dumps({**seed, "link": link["id"], "bytes": list(dosare.cale(state).read_bytes())}))


if __name__ == "__main__":
    main()
