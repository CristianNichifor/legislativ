"""One locked local runtime, with immutable public and durable private generations."""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

from scripts import cellar, depozit
from scripts.date_locale import DEFAULT_CHANNEL, DatasetManager, update_lock
from scripts.date_personale import prepare_eu
from scripts.servicii import Stare


class DatasetConflict(ValueError):
    """The manager cannot complete the requested transition from its current state."""


class LocalRuntime:
    def __init__(self, manager):
        self.manager = manager
        self.home = manager.home

    def _private(self, relative):
        path = self.home / "private" / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def _empty_eu(self):
        path = self._private("empty/eu.db")
        if not path.exists():
            with cellar.deschide(path):
                pass
        return path

    def state_factory(self, record, *, reopen=False):
        """Prepare under runtime_lock; only the manager publishes the resulting record."""
        private = self.home / "private"
        if record is None:
            folder = private / "empty"
            eu = self._private("eu-generations/initial/eu.db")
        else:
            generation = record.get("generation")
            private_generation = record.get("private_generation")
            if not isinstance(generation, str) or not re.fullmatch(r"[a-f0-9]{64}", generation):
                raise ValueError("Generatia publica este invalida.")
            if not isinstance(private_generation, str) or not re.fullmatch(
                r"[a-f0-9]{32}", private_generation
            ):
                raise ValueError("Generatia privata este invalida.")
            folder = self.home / "datasets" / generation
            if not (folder / "corpus.db").is_file():
                raise ValueError("Corpusul activ nu este disponibil; recuperarea este necesara.")
            eu = self._private(f"eu-generations/{private_generation}/eu.db")
            if reopen:
                if not eu.is_file():
                    raise ValueError("Baza UE privata activa lipseste; recuperarea este necesara.")
            else:
                current = self.manager.current_state
                previous = Path(current.eu) if current is not None else None
                if previous is not None and not previous.exists():
                    if getattr(current, "dataset_available", False):
                        raise ValueError("Baza UE privata curenta lipseste.")
                    previous = None
                public = folder / "eu.db"
                prepare_eu(public if public.is_file() else self._empty_eu(), previous, eu)
        initiative = folder / "initiative.db"
        # Initiative data is optional in a public release. An empty local schema lets
        # corpus-only releases work without ever creating a DB in a public generation.
        if record is not None and not initiative.is_file():
            initiative = self._private("empty/initiative.db")
            if not initiative.exists():
                with depozit.deschide(initiative):
                    pass
        state = Stare(
            str(folder / "corpus.db"),
            str(initiative),
            str(folder / "graf.db"),
            str(eu),
            reports_dir=str(folder),
        )
        state.dataset_available = record is not None
        state.dataset_record = record
        state._dosare_db = private / "dosare.db"
        state.dosare_db = state._dosare_db
        state._documente_db = private / "initiative.documente.db"
        state.documente_db = state._documente_db
        return state

    def command(self, body):
        if not isinstance(body, dict):
            raise ValueError("Cererea trebuie sa fie un obiect JSON.")
        action = body.get("action")
        if not isinstance(action, str) or action not in {
            "check",
            "download",
            "cancel",
            "activate",
            "rollback",
        }:
            raise ValueError("Actiune de actualizare necunoscuta.")
        fields = {"action", "sha256"} if action in {"download", "activate"} else {"action"}
        if set(body) != fields:
            raise ValueError("Campuri nepermise; sursa este configurata la pornire.")
        if "sha256" in fields:
            fingerprint = body["sha256"]
            if not isinstance(fingerprint, str) or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
                raise ValueError("Amprenta ofertei este invalida.")
        try:
            if action == "check":
                return self.manager.check()
            if action == "download":
                return self.manager.start(body["sha256"])
            if action == "cancel":
                return self.manager.cancel()
            if action == "activate":
                return self.manager.activate(body["sha256"], self.state_factory)
            return self.manager.rollback(self.state_factory)
        except ValueError as exc:
            raise DatasetConflict(str(exc)) from exc


@contextmanager
def open_runtime(home, channel=DEFAULT_CHANNEL, *, transport=None):
    home = Path(home).expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    if home == root or root in home.parents:
        raise ValueError("Directorul de date trebuie sa fie in afara aplicatiei.")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Keep this OS lock until all request threads finish, including EU imports.
    with update_lock(home, name="runtime.lock"):
        manager = DatasetManager(home, channel=channel, transport=transport)
        runtime = LocalRuntime(manager)
        with manager.runtime_lock, update_lock(home):
            manager.current_state = runtime.state_factory(manager.active(), reopen=True)
        try:
            yield runtime
        finally:
            try:
                manager.cancel()
            finally:
                if manager.thread is not None:
                    manager.thread.join()
