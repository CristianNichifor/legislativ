"""Browser transport for the existing dossier services; no network acquisition."""

import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from scripts import dosare


def validate(path):
    """Reject foreign/corrupt databases before replacing a workspace."""

    def shape(con):
        return {
            row[0]: tuple(row[1:])
            for row in con.execute("SELECT name,type,tbl_name,sql FROM sqlite_master ORDER BY name")
        }

    with (
        tempfile.TemporaryDirectory() as folder,
        dosare._open(Path(folder) / "canonical.db", write=True) as canonical,
    ):
        expected = shape(canonical)
    with dosare._open(path) as con:
        con.execute("PRAGMA trusted_schema=OFF")
        actual = shape(con)
        if not {"dosare", "rulari"} <= actual.keys() or any(
            name not in expected or definition != expected[name]
            for name, definition in actual.items()
        ):
            raise ValueError("Schema backupului nu corespunde contractului de dosare.")
        if [row[0] for row in con.execute("PRAGMA quick_check")] != ["ok"]:
            raise ValueError("Backup SQLite corupt.")
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Backup cu referinte invalide.")
    # Migrate only the isolated candidate, using the same schema as localhost.
    with dosare._open(path, write=True) as con:
        if shape(con) != expected:
            raise ValueError("Schema backupului de dosare este incompleta.")
    # Imported desktop backups may retain WAL mode. Checkpoint into the standalone file.
    with closing(sqlite3.connect(path)) as con:
        con.execute("PRAGMA journal_mode=DELETE")


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with dosare._open(path, write=True):
        pass


def public_contract(kind, raw, channel, allow_loopback=False):
    """Use the publisher's contract, including duplicate-key and optional-file rules."""
    from scripts import dataset_release as release

    configured = urlsplit(channel)
    origin = f"{configured.scheme}://{configured.netloc}"
    if kind == "channel":
        if configured.scheme == "http":
            if not allow_loopback or configured.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Canalul necesita HTTPS.")
            value = release._parse(raw)
            url = value.get("manifest", "") if isinstance(value, dict) else ""
            if not url.startswith(origin + "/"):
                raise ValueError("Origine nepermisa.")
            release.validate_channel(
                {**value, "manifest": "https" + url[4:]},
                trusted_origin="https" + origin[4:],
            )
        else:
            value = release.load_channel(raw, trusted_origin=origin)
    elif kind == "manifest":
        value = release.load_manifest(raw)
    else:
        raise ValueError("Contract necunoscut.")
    return json.dumps(value)


def route(stare, route, qs, body, method="GET"):
    from scripts import (
        analize_propuneri,
        coada_ue,
        dependente_dovezi,
        legaturi_ue,
        legaturi_ue_store,
        note_manuale,
        propuneri,
        revizuiri,
        surse_propuneri,
        verificari_dovezi,
    )

    path = dosare.cale(stare)
    part = route.removeprefix("/api/dosare")

    def get(key, default=None):
        return qs.get(key, [default])[0]

    ident, run = get("id"), get("rulare_id")
    offset = int(get("offset", "0"))
    if method == "POST":
        handlers = {
            "": lambda: dosare.creeaza(path, body),
            "/metadate": lambda: dosare.modifica(path, body),
            "/ciorne": lambda: dosare.salveaza_ciorna(path, body),
            "/rulari": lambda: dosare.salveaza_rulare(stare, body),
            "/revizuiri": lambda: revizuiri.salveaza(path, body),
            "/verificari": lambda: verificari_dovezi.salveaza(stare, body),
            "/context": lambda: revizuiri.context_salveaza(path, body),
            "/note": lambda: note_manuale.salveaza(path, body),
            "/propuneri": lambda: propuneri.salveaza(path, body, stare),
            "/propuneri/previzualizare": lambda: propuneri.previzualizeaza(stare, body),
            "/propuneri/analize": lambda: analize_propuneri.salveaza(stare, body),
            "/propuneri/legaturi-ue": lambda: legaturi_ue_store.salveaza(stare, body),
            "/propuneri/legaturi-ue/previzualizare": lambda: legaturi_ue.preview(stare, body),
        }
    elif method == "GET":
        handlers = {
            "": lambda: (
                dosare.citeste(path, ident)
                if ident
                else dosare.lista(path, offset, get("stare", "active"))
            ),
            "/metadate": lambda: dosare.metadata(path, ident),
            "/ciorne": lambda: (
                dosare.citeste_ciorna(path, ident) if ident else dosare.lista_ciorne(path, offset)
            ),
            "/rulari": lambda: dosare.rulari(path, ident, run),
            "/revizuiri": lambda: (
                revizuiri.istoric(path, ident, run, get("constatare_id"), offset)
                if "constatare_id" in qs
                else revizuiri.lista(path, ident, run)
            ),
            "/context": lambda: revizuiri.context_istoric(
                path, ident, run, get("constatare_id"), get("tinta"), offset
            ),
            "/verificari": lambda: verificari_dovezi.istoric(
                path, ident, run, offset, get("verificare_id")
            ),
            "/coada": lambda: verificari_dovezi.coada(path, offset, get("stare", "toate")),
            "/coada-ue": lambda: coada_ue.lista(path, offset, get("stare", "toate")),
            "/note": lambda: (
                note_manuale.citeste(path, ident, get("note_id"))
                if "note_id" in qs
                else note_manuale.lista(path, ident, offset, get("status"))
            ),
            "/dovezi": lambda: dependente_dovezi.verifica(stare, ident, run),
            "/propuneri": lambda: propuneri.citeste_cerere(path, qs),
            "/propuneri/analize": lambda: analize_propuneri.citeste_cerere(path, qs),
            "/propuneri/surse": lambda: surse_propuneri.citeste_cerere(stare, qs),
            "/propuneri/legaturi-ue": lambda: legaturi_ue_store.citeste_cerere(path, qs),
            "/propuneri/legaturi-ue/obligatii": lambda: legaturi_ue.obligatii(
                stare, get("celex"), get("instantanee", ""), offset
            ),
        }
    else:
        raise ValueError("Metoda nesuportata.")
    if part not in handlers:
        raise ValueError("Ruta de dosare nesuportata in browser.")
    try:
        return handlers[part]()
    except sqlite3.DatabaseError as exc:
        raise ValueError("Depozitul de dosare nu este disponibil.") from exc
