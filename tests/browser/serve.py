"""Serve the real local backend with an isolated synthetic corpus, never user databases."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import depozit
from scripts.api import Inregistrare
from scripts.colector import act_din_inregistrare
from scripts.server import serveste

with TemporaryDirectory(prefix="legislativ-browser-") as directory:
    root = Path(directory)
    record = Inregistrare(
        titlu="LEGE nr. 999999 din 2024 - corpus sintetic pentru test",
        tip_act="LEGE",
        numar="999999",
        an=None,
        data_vigoare=date(2024, 1, 1),
        emitent="PARLAMENTUL",
        publicatie="TEST SINTETIC",
        link_html="https://example.invalid/fixture",
        text="Art. 1. - Registrul demonstrativ este o evidenta sintetica pentru test.",
    )
    with depozit.deschide(root / "corpus.db") as connection:
        depozit.scrie_inregistrare(connection, record, act_din_inregistrare(record))
    with depozit.deschide(root / "initiative.db"):
        pass
    serveste(
        5190,
        str(root / "corpus.db"),
        str(root / "initiative.db"),
        str(root / "graf.db"),
        deschide_browser=False,
        eu=str(root / "eu.db"),
    )
