"""Explicit, download-only public dataset updates; private research is never uploaded."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import urllib.request
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from scripts.dataset_release import load_channel, load_manifest, validate_release_id

DEFAULT_CHANNEL = "https://date.cnwebify.dev/channel.json"
MAX_MANIFEST = 256 * 1024
CHUNK = 1024 * 1024
CORE_COLUMNS = {
    "corpus.db": {
        "acte": {
            "id",
            "cheie_citare",
            "tip",
            "numar",
            "an",
            "titlu",
            "emitent",
            "publicat",
            "vigoare",
            "sursa_url",
            "citit_la",
            "republicat_din",
            "id_portal",
            "id_act_portal",
        },
        "provizii": {"act_id", "locator", "ord", "text", "vigoare_de_la", "vigoare_pana_la"},
    },
    "initiative.db": {
        "initiative": {
            "plx_id",
            "cam",
            "idp",
            "senat_id",
            "tip",
            "titlu",
            "obiect",
            "urgenta",
            "stadiu",
            "camera_decizionala",
            "data_inreg",
            "sursa_url",
            "citit_la",
        }
    },
    "graf.db": {
        "muchii": {"din_act", "din_locator", "catre_act", "locator", "fel", "incredere", "de_la"}
    },
    "eu.db": {"eu_acte": {"celex", "text", "text_sha256", "limba", "citit_la"}},
}


class CommittedWriteError(OSError):
    """The pointer changed, but the final directory flush could not be confirmed."""


def sync_directory(path):
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_file(path):
    with Path(path).open("r+b") as stream:
        os.fsync(stream.fileno())


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            result.update(block)
    return result.hexdigest()


def atomic_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        sync_directory(path.parent)
        os.replace(temporary, path)
        try:
            sync_directory(path.parent)
        except OSError as exc:
            raise CommittedWriteError(
                "Pointer schimbat; persistenta pe disc nu poate fi confirmata."
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def update_lock(home, name="update.lock"):
    """OS-owned lock releases on process exit; no stale PID-file recovery guesses."""
    if name not in {"update.lock", "runtime.lock"}:
        raise ValueError("Invalid lock name")
    with (Path(home) / name).open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            stream.write(b"0")
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirectarea sursei de date nu este permisa.")


class PublicTransport:
    def __init__(self, channel, *, allow_loopback=False):
        self.channel = channel
        self.allow_loopback = allow_loopback
        self.origin = self._origin(channel)
        self.opener = urllib.request.build_opener(NoRedirect())

    def _origin(self, url):
        parsed = urlsplit(url)
        permitted = parsed.scheme == "https" or (
            self.allow_loopback
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        )
        if (
            not permitted
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or "\\" in url
            or any(ord(char) < 33 for char in url)
            or "\\" in unquote(parsed.path)
            or any(part in {".", ".."} for part in unquote(parsed.path).split("/"))
        ):
            raise ValueError("Sursa de actualizare trebuie sa fie o adresa HTTPS configurata.")
        return parsed.scheme, parsed.hostname, parsed.port

    def open(self, url, offset=0):
        if self._origin(url) != self.origin:
            raise ValueError("Actualizarea nu poate schimba originea configurata.")
        headers = {"Accept-Encoding": "identity", "User-Agent": "Legislativ-dataset/1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        return self.opener.open(urllib.request.Request(url, headers=headers), timeout=30)

    def small(self, url):
        with self.open(url) as response:
            if response.status != 200:
                raise ValueError("Raspuns de manifest invalid.")
            body = response.read(MAX_MANIFEST + 1)
        if len(body) > MAX_MANIFEST:
            raise ValueError("Manifest prea mare.")
        return body


class DatasetManager:
    def __init__(self, home, channel=DEFAULT_CHANNEL, *, transport=None):
        self.home = Path(home).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("datasets", "staging", "private"):
            (self.home / name).mkdir(exist_ok=True, mode=0o700)
        self.transport = transport or PublicTransport(channel)
        self.channel = channel
        self.lock = threading.RLock()
        self.runtime_lock = threading.RLock()
        self.current_state = None
        self.thread = None
        self.cancelled = threading.Event()
        self.offer = None
        self.progress = {"state": "idle", "bytes": 0, "total": 0, "error": ""}
        pending = self.home / "pending.json"
        if pending.is_file():
            try:
                if pending.stat().st_size > 4 * MAX_MANIFEST:
                    raise ValueError("Oferta locala prea mare.")
                offer = json.loads(pending.read_bytes())
                self._validate_offer(offer)
                self.offer = offer
                ready = (self.home / "datasets" / offer["sha256"]).is_dir()
                self.progress.update(
                    state="ready" if ready else "checked",
                    total=sum(f["bytes"] for f in offer["manifest"]["files"]),
                )
                active = self.active()
                if active and active["generation"] == offer["sha256"]:
                    self.progress["state"] = "active"
            except (OSError, ValueError, TypeError, KeyError):
                self.progress.update(
                    state="error", error="Oferta locala este invalida; verifica din nou sursa."
                )

    def _validate_offer(self, offer):
        if not isinstance(offer, dict) or not isinstance(offer.get("manifest_text"), str):
            raise ValueError("Oferta invalida.")
        raw = offer["manifest_text"].encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != offer["sha256"]:
            raise ValueError("Amprenta ofertei locale este invalida.")
        if load_manifest(raw) != offer["manifest"]:
            raise ValueError("Manifestul ofertei locale este invalid.")
        self._channel(
            json.dumps(
                {"schema_version": 1, "manifest": offer["url"], "sha256": offer["sha256"]}
            ).encode()
        )

    def _channel(self, raw):
        configured = urlsplit(self.channel)
        return load_channel(raw, trusted_origin=f"{configured.scheme}://{configured.netloc}")

    @staticmethod
    def _validate_record(data, *, previous=False):
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("generation"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", data["generation"])
        ):
            raise ValueError("Pointerul local de date este invalid.")
        validate_release_id(data.get("release"))
        if not previous:
            if not isinstance(data.get("private_generation"), str) or not re.fullmatch(
                r"[a-f0-9]{32}", data["private_generation"]
            ):
                raise ValueError("Pointerul privat este invalid.")
            if data.get("previous") is not None:
                DatasetManager._validate_record(data["previous"], previous=True)

    def active(self):
        path = self.home / "active.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        self._validate_record(data)
        return data

    def status(self):
        with self.lock:
            return {
                "mode": "local",
                "channel": self.channel,
                "active": self.active(),
                "offer": {k: v for k, v in self.offer.items() if k != "manifest_text"}
                if self.offer
                else None,
                "progress": dict(self.progress),
                "private_data_uploaded": False,
            }

    def check(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("O descarcare este deja in curs.")
            channel = self._channel(self.transport.small(self.channel))
            raw = self.transport.small(channel["manifest"])
            if hashlib.sha256(raw).hexdigest() != channel["sha256"]:
                raise ValueError("Amprenta manifestului nu corespunde canalului.")
            manifest = load_manifest(raw)
            self.offer = {
                "manifest": manifest,
                "url": channel["manifest"],
                "sha256": channel["sha256"],
                "manifest_text": raw.decode("utf-8"),
            }
            with update_lock(self.home):
                atomic_json(self.home / "pending.json", self.offer)
            self.progress = {
                "state": "checked",
                "bytes": 0,
                "total": sum(f["bytes"] for f in manifest["files"]),
                "error": "",
            }
            active = self.active()
            if active and active["generation"] == self.offer["sha256"]:
                self.progress["state"] = "active"
        return self.status()

    def start(self, fingerprint):
        with self.lock:
            if not self.offer or fingerprint != self.offer["sha256"]:
                raise ValueError("Verifica si confirma oferta curenta.")
            active = self.active()
            if active and active["generation"] == fingerprint:
                raise ValueError("Versiunea este deja activa.")
            if self.thread and self.thread.is_alive():
                return self.status()
            offer = json.loads(json.dumps(self.offer))
            self.cancelled.clear()
            self.progress.update(state="downloading", bytes=0, file="", file_bytes=0, error="")
            self.thread = threading.Thread(target=self._download, args=(offer,), daemon=True)
            self.thread.start()
        return self.status()

    def _set(self, **values):
        with self.lock:
            self.progress.update(values)

    def _file(self, offer, item, folder):
        target = folder / item["name"]
        if (
            target.exists()
            and target.stat().st_size == item["bytes"]
            and digest(target) == item["sha256"]
        ):
            return
        part = target.with_name(target.name + ".part")
        offset = part.stat().st_size if part.exists() else 0
        if offset >= item["bytes"]:
            part.unlink()
            offset = 0
        url = urljoin(offer["url"], item["name"])
        with self.transport.open(url, offset) as response:
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise ValueError("Compresia de transport nu este acceptata.")
            if offset and response.status == 206:
                expected = f"bytes {offset}-{item['bytes'] - 1}/{item['bytes']}"
                if response.headers.get("Content-Range") != expected:
                    raise ValueError("Intervalul descarcat nu corespunde pachetului.")
            elif response.status == 200:
                offset = 0
            else:
                raise ValueError("Raspuns de descarcare invalid.")
            with part.open("ab" if offset else "wb") as stream:
                count = offset
                while block := response.read(min(CHUNK, item["bytes"] - count + 1)):
                    if self.cancelled.is_set():
                        raise InterruptedError("Descarcare oprita; copia activa este pastrata.")
                    count += len(block)
                    if count > item["bytes"]:
                        raise ValueError("Pachetul depaseste dimensiunea declarata.")
                    stream.write(block)
                    self._set(file=item["name"], file_bytes=count)
                stream.flush()
                os.fsync(stream.fileno())
        if count != item["bytes"]:
            raise ValueError("Descarcare incompleta; poate fi reluata.")
        if digest(part) != item["sha256"]:
            part.unlink(missing_ok=True)
            raise ValueError("Amprenta pachetului este invalida; reia descarcarea.")
        os.replace(part, target)

    @staticmethod
    def verify(folder, manifest):
        for item in manifest["files"]:
            path = folder / item["name"]
            if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
                raise ValueError("Integritatea copiei locale nu poate fi confirmata.")
            if path.suffix == ".db":
                if any(
                    path.with_name(path.name + suffix).exists()
                    for suffix in ("-wal", "-shm", "-journal")
                ):
                    raise ValueError("Baza descarcata are fisiere SQLite auxiliare nepermise.")
                with path.open("rb") as stream:
                    header = stream.read(100)
                if (
                    len(header) != 100
                    or header[:16] != b"SQLite format 3\x00"
                    or header[18:20] != b"\x01\x01"
                ):
                    raise ValueError("Baza descarcata nu este un snapshot SQLite autonom.")
                with closing(
                    sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
                ) as con:
                    con.execute("PRAGMA trusted_schema=OFF")
                    if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
                        raise ValueError("Baza de date descarcata este deteriorata.")
                    for table, required in CORE_COLUMNS[path.name].items():
                        if not con.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                        ).fetchone():
                            raise ValueError("Baza descarcata nu are structura necesara.")
                        # Table identifiers come only from the app contract above.
                        columns = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                        if not required <= columns:
                            raise ValueError("Baza descarcata nu are coloanele necesare.")
            else:
                json.loads(path.read_text(encoding="utf-8"))

    def _download(self, offer):
        try:
            with update_lock(self.home):
                folder = self.home / "staging" / offer["sha256"]
                folder.mkdir(exist_ok=True)
                needed = 0
                for item in offer["manifest"]["files"]:
                    target = folder / item["name"]
                    if (
                        target.is_file()
                        and target.stat().st_size == item["bytes"]
                        and digest(target) == item["sha256"]
                    ):
                        continue
                    part = target.with_name(target.name + ".part")
                    present = part.stat().st_size if part.is_file() else 0
                    needed += item["bytes"] - (present if present < item["bytes"] else 0)
                if shutil.disk_usage(self.home).free < needed + 64 * CHUNK:
                    raise ValueError("Spatiu liber insuficient pentru descarcare si verificare.")
                done = 0
                for item in offer["manifest"]["files"]:
                    if self.cancelled.is_set():
                        raise InterruptedError("Descarcare oprita.")
                    self._file(offer, item, folder)
                    done += item["bytes"]
                    self._set(bytes=done)
                self._set(state="verifying")
                self.verify(folder, offer["manifest"])
                manifest_path = folder / "dataset-release.json"
                manifest_path.write_text(offer["manifest_text"], encoding="utf-8", newline="")
                sync_file(manifest_path)
                sync_directory(folder)
                destination = self.home / "datasets" / offer["sha256"]
                if not destination.exists():
                    os.replace(folder, destination)
                else:
                    self.verify(destination, offer["manifest"])
                sync_directory(destination.parent)
                sync_directory(folder.parent)
                self._set(state="ready", file="", file_bytes=0)
        except Exception as exc:
            self._set(
                state="cancelled" if isinstance(exc, InterruptedError) else "error", error=str(exc)
            )

    def activate(self, fingerprint, state_factory):
        with self.runtime_lock, self.lock, update_lock(self.home):
            if self.thread and self.thread.is_alive():
                raise ValueError("Asteapta finalizarea descarcarii.")
            if (
                not self.offer
                or fingerprint != self.offer["sha256"]
                or self.progress["state"] != "ready"
            ):
                raise ValueError("Pachetul nu este pregatit pentru activare.")
            folder = self.home / "datasets" / fingerprint
            if digest(folder / "dataset-release.json") != fingerprint:
                raise ValueError("Manifestul copiei locale este invalid.")
            self.verify(folder, self.offer["manifest"])
            old = self.active()
            record = self._record(fingerprint, self.offer["manifest"]["release"], old)
            # Build/validate a complete runtime before changing the only active pointer.
            state = state_factory(record)
            return self._publish(record, state)

    def _publish(self, record, state):
        folder = self.home / "datasets" / record["generation"]
        for path in folder.iterdir():
            if path.is_file():
                sync_file(path)
        sync_directory(folder)
        sync_directory(folder.parent)
        private = self.home / "private" / "eu-generations" / record["private_generation"]
        if private.is_dir():
            for path in private.iterdir():
                if path.is_file():
                    sync_file(path)
            sync_directory(private)
            sync_directory(private.parent)
            sync_directory(private.parent.parent)
        # Flush generation directory entries before making their pointer durable.
        try:
            atomic_json(self.home / "active.json", record)
        except CommittedWriteError as exc:
            self.current_state = state
            self.progress.update(state="active", error=str(exc))
            raise
        self.current_state = state
        self.progress.update(state="active", error="")
        return self.status()

    @staticmethod
    def _record(fingerprint, release, old):
        return {
            "generation": fingerprint,
            "release": release,
            "private_generation": uuid.uuid4().hex,
            "previous": {k: old[k] for k in ("generation", "release")} if old else None,
            "activated_at": datetime.now(UTC).isoformat(),
        }

    def rollback(self, state_factory):
        with self.runtime_lock, self.lock, update_lock(self.home):
            if self.thread and self.thread.is_alive():
                raise ValueError("Asteapta finalizarea descarcarii.")
            old = self.active()
            if not old or not old.get("previous"):
                raise ValueError("Nu exista o versiune anterioara.")
            previous = old["previous"]
            folder = self.home / "datasets" / previous["generation"]
            raw = (folder / "dataset-release.json").read_bytes()
            if hashlib.sha256(raw).hexdigest() != previous["generation"]:
                raise ValueError("Manifestul copiei anterioare este invalid.")
            manifest = load_manifest(raw)
            self.verify(folder, manifest)
            record = self._record(previous["generation"], manifest["release"], old)
            state = state_factory(record)
            return self._publish(record, state)

    def cancel(self):
        self.cancelled.set()
        return self.status()
