import hashlib
import io
import json
import sqlite3
from contextlib import closing

import pytest

from scripts import date_locale as local
from scripts import depozit


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


class Transport:
    def __init__(self, tmp_path):
        db = tmp_path / "source.db"
        with closing(sqlite3.connect(db)) as con:
            con.executescript(depozit.SCHEMA)
            con.execute("PRAGMA journal_mode=DELETE")
        self.payload = db.read_bytes()
        self.requests = []
        self.bad_hash = False
        self.short = False
        self.range_header = None
        self.ignore_range = False
        self.publish("2026-09-10")

    def publish(self, version):
        self.manifest = {
            "schema_version": 1,
            "app_contract": 1,
            "release": version,
            "created_at": "2026-09-10T00:00:00Z",
            "files": [
                {
                    "name": "corpus.db",
                    "bytes": len(self.payload),
                    "sha256": hashlib.sha256(self.payload).hexdigest(),
                }
            ],
        }
        self.raw = json.dumps(self.manifest).encode()
        self.channel = {
            "schema_version": 1,
            "manifest": f"https://date.cristian-nichifor.com/{version}/dataset-release.json",
            "sha256": hashlib.sha256(self.raw).hexdigest(),
        }

    def small(self, url):
        self.requests.append((url, 0))
        return json.dumps(self.channel).encode() if url.endswith("channel.json") else self.raw

    def open(self, url, offset=0):
        self.requests.append((url, offset))
        data = self.payload
        if self.bad_hash:
            data = b"x" * len(data)
        if self.ignore_range:
            offset = 0
        headers = {}
        if offset:
            headers["Content-Range"] = (
                self.range_header or f"bytes {offset}-{len(data) - 1}/{len(data)}"
            )
        data = data[offset:]
        if self.short:
            data = data[:100]
        return Response(data, 206 if offset else 200, headers)


@pytest.fixture
def setup(tmp_path):
    transport = Transport(tmp_path)
    manager = local.DatasetManager(tmp_path / "home", transport=transport)
    return manager, transport


def download(manager):
    manager.check()
    fingerprint = manager.offer["sha256"]
    manager.start(fingerprint)
    manager.thread.join(5)
    assert not manager.thread.is_alive()
    return fingerprint


def test_first_run_offline_and_explicit_activation(setup):
    manager, transport = setup
    assert manager.active() is None
    assert transport.requests == []
    private = manager.home / "private" / "dosare.db"
    private.write_bytes(b"personal research")
    fingerprint = download(manager)
    assert manager.status()["progress"]["state"] == "ready"
    assert manager.active() is None
    assert "manifest_text" not in manager.status()["offer"]
    state = object()
    manager.activate(fingerprint, lambda record: state)
    assert manager.current_state is state
    assert manager.active()["generation"] == fingerprint
    assert private.read_bytes() == b"personal research"
    assert manager.status()["private_data_uploaded"] is False


def test_restart_retains_ready_and_resume(setup):
    manager, transport = setup
    fingerprint = download(manager)
    restarted = local.DatasetManager(manager.home, transport=transport)
    assert restarted.progress["state"] == "ready"
    restarted.activate(fingerprint, lambda record: record)
    assert restarted.active()["generation"] == fingerprint


def test_failed_activation_keeps_active_pointer_and_runtime(setup):
    manager, transport = setup
    fingerprint = download(manager)
    manager.activate(fingerprint, lambda record: "old")
    old = manager.active()
    transport.publish("2026-09-11")
    fingerprint = download(manager)

    def fail(record):
        raise ValueError("private migration rejected")

    with pytest.raises(ValueError, match="migration rejected"):
        manager.activate(fingerprint, fail)
    assert manager.active() == old
    assert manager.current_state == "old"


def test_rollback_creates_new_private_generation_without_losing_files(setup):
    manager, transport = setup
    first = download(manager)
    manager.activate(first, lambda record: record)
    original = manager.active()
    transport.publish("2026-09-11")
    second = download(manager)
    manager.activate(second, lambda record: record)
    manager.rollback(lambda record: record)
    active = manager.active()
    assert active["generation"] == first
    assert active["private_generation"] != original["private_generation"]
    assert active["previous"] == {"generation": second, "release": "2026-09-11"}


def test_bad_download_never_activates_and_deletes_corrupt_partial(setup):
    manager, transport = setup
    transport.bad_hash = True
    fingerprint = download(manager)
    assert manager.progress["state"] == "error"
    assert manager.active() is None
    assert not (manager.home / "staging" / fingerprint / "corpus.db.part").exists()
    with pytest.raises(ValueError, match="pregatit"):
        manager.activate(fingerprint, lambda record: record)


@pytest.mark.parametrize("ignore_range", [False, True])
def test_interrupted_download_resumes_or_restarts_if_range_ignored(setup, ignore_range):
    manager, transport = setup
    transport.short = True
    fingerprint = download(manager)
    assert manager.progress["state"] == "error"
    partial = manager.home / "staging" / fingerprint / "corpus.db.part"
    assert partial.stat().st_size == 100
    transport.short = False
    transport.ignore_range = ignore_range
    restarted = local.DatasetManager(manager.home, transport=transport)
    restarted.start(fingerprint)
    restarted.thread.join(5)
    assert not restarted.thread.is_alive()
    assert restarted.progress["state"] == "ready"
    assert transport.requests[-1][1] == 100


def test_invalid_range_is_rejected(setup):
    manager, transport = setup
    transport.short = True
    fingerprint = download(manager)
    transport.short = False
    transport.range_header = "bytes 0-10/11"
    manager.start(fingerprint)
    manager.thread.join(5)
    assert manager.progress["state"] == "error"
    assert "Intervalul" in manager.progress["error"]


def test_manifest_tampering_fails_before_payload_request(setup):
    manager, transport = setup
    transport.raw += b" "
    with pytest.raises(ValueError, match="Amprenta"):
        manager.check()
    assert len(transport.requests) == 2
    assert manager.active() is None


def test_remote_channel_cannot_select_another_origin(setup):
    manager, transport = setup
    transport.channel["manifest"] = "https://evil.example/2026-09-10/dataset-release.json"
    with pytest.raises(ValueError):
        manager.check()
    assert len(transport.requests) == 1


def test_tampered_pending_cannot_escape_private_root(setup):
    manager, transport = setup
    manager.check()
    record = dict(manager.offer, sha256="../private")
    local.atomic_json(manager.home / "pending.json", record)
    restarted = local.DatasetManager(manager.home, transport=transport)
    assert restarted.offer is None
    assert restarted.progress["state"] == "error"


@pytest.mark.parametrize("value", [None, [], 12, {}])
def test_malformed_pending_offer_does_not_prevent_startup(setup, value):
    manager, transport = setup
    local.atomic_json(manager.home / "pending.json", {"manifest_text": value})
    restarted = local.DatasetManager(manager.home, transport=transport)
    assert restarted.offer is None
    assert restarted.progress["state"] == "error"


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_unlisted_sqlite_sidecars_prevent_activation(setup, suffix):
    manager, _ = setup
    fingerprint = download(manager)
    folder = manager.home / "datasets" / fingerprint
    (folder / ("corpus.db" + suffix)).write_bytes(b"unverified")
    with pytest.raises(ValueError, match="auxiliare"):
        manager.activate(fingerprint, lambda record: record)
    assert manager.active() is None


def test_wal_header_cannot_pass_even_without_sidecars(setup):
    manager, transport = setup
    payload = bytearray(transport.payload)
    payload[18:20] = b"\x02\x02"
    transport.payload = bytes(payload)
    transport.publish("2026-09-11")
    download(manager)
    assert manager.progress["state"] == "error"
    assert "autonom" in manager.progress["error"]


def test_generation_flush_failure_keeps_old_pointer(setup, monkeypatch):
    manager, _ = setup
    fingerprint = download(manager)
    manager.current_state = "old"

    def fail(path):
        raise OSError("flush failed")

    monkeypatch.setattr(local, "sync_directory", fail)
    with pytest.raises(OSError, match="flush"):
        manager.activate(fingerprint, lambda record: "new")
    assert manager.active() is None
    assert manager.current_state == "old"


def test_post_replace_flush_failure_keeps_runtime_consistent_with_pointer(setup, monkeypatch):
    manager, _ = setup
    fingerprint = download(manager)
    original = local.atomic_json

    def uncertain(path, data):
        original(path, data)
        raise local.CommittedWriteError("flush uncertain")

    monkeypatch.setattr(local, "atomic_json", uncertain)
    with pytest.raises(local.CommittedWriteError, match="uncertain"):
        manager.activate(fingerprint, lambda record: "new")
    assert manager.active()["generation"] == fingerprint
    assert manager.current_state == "new"
    assert manager.progress["state"] == "active"
    assert manager.progress["error"] == "flush uncertain"


def test_activation_rechecks_completed_file(setup):
    manager, _ = setup
    fingerprint = download(manager)
    (manager.home / "datasets" / fingerprint / "corpus.db").write_bytes(b"bad")
    with pytest.raises(ValueError, match="Integritatea"):
        manager.activate(fingerprint, lambda record: record)
    assert manager.active() is None


def test_no_previous_rollback(setup):
    manager, _ = setup
    with pytest.raises(ValueError, match="anterioara"):
        manager.rollback(lambda record: record)


def test_rechecking_active_release_does_not_replace_previous_generation(setup):
    manager, transport = setup
    first = download(manager)
    manager.activate(first, lambda record: record)
    transport.publish("2026-09-11")
    second = download(manager)
    manager.activate(second, lambda record: record)
    old = manager.active()
    manager.check()
    assert manager.progress["state"] == "active"
    with pytest.raises(ValueError, match="deja activa"):
        manager.start(second)
    assert manager.active() == old
    restarted = local.DatasetManager(manager.home, transport=transport)
    assert restarted.progress["state"] == "active"


def test_lock_blocks_another_manager(setup):
    manager, _ = setup
    with local.update_lock(manager.home), pytest.raises(OSError), local.update_lock(manager.home):
        pytest.fail("second writer acquired lock")


def test_low_disk_does_not_start_payload_transfer(setup, monkeypatch):
    manager, transport = setup
    monkeypatch.setattr(local.shutil, "disk_usage", lambda path: type("Usage", (), {"free": 0})())
    download(manager)
    assert manager.progress["state"] == "error"
    assert "Spatiu" in manager.progress["error"]
    assert len(transport.requests) == 2
    assert manager.active() is None


def test_cancel_keeps_partial_and_active_dataset(setup):
    manager, transport = setup
    fingerprint = download(manager)
    manager.activate(fingerprint, lambda record: "old")
    old = manager.active()
    transport.publish("2026-09-11")
    manager.check()
    manager.cancelled.set()
    manager._download(manager.offer)
    assert manager.progress["state"] == "cancelled"
    assert manager.active() == old
    assert manager.current_state == "old"


def test_valid_hash_but_wrong_sqlite_schema_never_becomes_ready(setup):
    manager, transport = setup
    path = manager.home / "bad.db"
    with closing(sqlite3.connect(path)) as con:
        con.execute("CREATE TABLE wrong(id TEXT)")
    transport.payload = path.read_bytes()
    transport.publish("2026-09-11")
    download(manager)
    assert manager.progress["state"] == "error"
    assert "structura" in manager.progress["error"]
    assert manager.active() is None


@pytest.mark.parametrize("pointer", [[], {}, {"generation": "../private"}, {"generation": []}])
def test_invalid_local_pointer_never_selects_path(setup, pointer):
    manager, _ = setup
    local.atomic_json(manager.home / "active.json", pointer)
    with pytest.raises(ValueError):
        manager.active()


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example/channel.json",
        "https://a:b@example.org/channel.json",
        "https://example.org/../channel.json",
        "https://example.org/%2e%2e/channel.json",
        "https://example.org/x?token=secret",
        "https://example.org/x#fragment",
        "https://example.org/\nchannel.json",
    ],
)
def test_transport_rejects_unsafe_configured_url(url):
    with pytest.raises(ValueError):
        local.PublicTransport(url)


def test_transport_refuses_redirect_and_origin_change():
    transport = local.PublicTransport("https://example.org/channel.json")
    with pytest.raises(ValueError, match="originea"):
        transport.open("https://evil.example/corpus.db")
    with pytest.raises(ValueError, match="Redirectarea"):
        local.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.example")
