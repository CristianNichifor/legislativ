"""Serve the real local backend with an isolated synthetic corpus, never user databases."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from scripts import depozit, tracker_events
from scripts.api import Inregistrare
from scripts.cdep import Initiativa
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
    with depozit.deschide(root / "initiative.db") as connection:
        depozit.scrie_initiativa(
            connection,
            Initiativa(
                plx_id="plx-999999-2026",
                cam=2,
                idp="999999",
                senat_id="L999/2026",
                tip="propunere legislativa",
                titlu="Lege pentru modificarea registrului demonstrativ",
                obiect="modificarea Legii nr. 999999/2024",
                urgenta=False,
                stadiu="raport depus",
                camera_decizionala="Camera Deputaților",
                data_inreg="2026-01-01",
                sursa_url="",
            ),
        )
        depozit.scrie_initiativa(
            connection,
            Initiativa(
                plx_id="plx-999998-2026",
                cam=2,
                idp="999998",
                senat_id="L998/2026",
                tip="propunere legislativa",
                titlu="Lege privind completarea registrului demonstrativ",
                obiect="completarea Legii nr. 999999/2024",
                urgenta=False,
                stadiu="pe ordinea de zi",
                camera_decizionala="Camera Deputaților",
                data_inreg="2026-01-02",
                sursa_url="",
            ),
        )
        connection.execute(
            "INSERT INTO initiative_tinta (plx_id, act_id, locator) VALUES (?,?,?)",
            ("plx-999999-2026", "lege-999999-2024", "art1"),
        )
        connection.execute(
            "INSERT INTO initiative_tinta (plx_id, act_id, locator) VALUES (?,?,?)",
            ("plx-999998-2026", "lege-999999-2024", "art2"),
        )
    for event in [
        {
            "event_type": "committee_assignment",
            "project_id": "plx-999999-2026",
            "source_family": "camera",
            "source_url": "https://www.cdep.ro/pls/proiecte/upl_pck.proiect?idp=999999",
            "occurred_at": "2026-01-03T10:00:00+00:00",
            "title": "Comisie sesizată pentru fond",
            "payload": {
                "committees": ["Comisia juridică"],
                "role": "fond",
                "raw_action": "trimis pentru raport",
            },
        },
        {
            "event_type": "report_filed",
            "project_id": "plx-999999-2026",
            "dossier_id": "11111111111111111111111111111111",
            "source_family": "camera",
            "source_url": "https://www.cdep.ro/pls/proiecte/upl_pck.proiect?idp=999999",
            "occurred_at": "2026-01-05T10:00:00+00:00",
            "title": "Raport depus",
            "payload": {
                "committee": "Comisia juridică",
                "position": "adoptare",
                "filed_at": "2026-01-05",
            },
        },
    ]:
        tracker_events.adauga(SimpleNamespace(initiative=root / "initiative.db"), event)
    serveste(
        5190,
        str(root / "corpus.db"),
        str(root / "initiative.db"),
        str(root / "graf.db"),
        deschide_browser=False,
        eu=str(root / "eu.db"),
    )
