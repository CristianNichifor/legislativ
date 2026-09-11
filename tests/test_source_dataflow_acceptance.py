import hashlib
import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from scripts import date_locale as local
from scripts import depozit, source_sync

ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


class PublicDatasetFixture:
    def __init__(self, tmp_path):
        self.requests = []
        self.payload = self._corpus(tmp_path / "corpus.db")
        self.publish("2026-09-10")

    @staticmethod
    def _corpus(path):
        with closing(sqlite3.connect(path)) as con:
            con.executescript(depozit.SCHEMA)
            con.execute("PRAGMA journal_mode=DELETE")
        return path.read_bytes()

    def publish(self, release_id):
        self.manifest = {
            "schema_version": 1,
            "release": release_id,
            "app_contract": 1,
            "created_at": "2026-09-10T00:00:00Z",
            "files": [
                {
                    "name": "corpus.db",
                    "bytes": len(self.payload),
                    "sha256": hashlib.sha256(self.payload).hexdigest(),
                }
            ],
        }
        self.manifest_raw = json.dumps(self.manifest).encode()
        self.channel = {
            "schema_version": 1,
            "manifest": f"https://date.cristian-nichifor.com/{release_id}/dataset-release.json",
            "sha256": hashlib.sha256(self.manifest_raw).hexdigest(),
        }

    def small(self, url):
        self.requests.append((url, 0))
        return (
            json.dumps(self.channel).encode() if url.endswith("channel.json") else self.manifest_raw
        )

    def open(self, url, offset=0):
        self.requests.append((url, offset))
        return Response(self.payload[offset:], 206 if offset else 200)


def _download(manager):
    checked = manager.check()
    fingerprint = checked["offer"]["sha256"]
    manager.start(fingerprint)
    manager.thread.join(5)
    assert not manager.thread.is_alive()
    assert manager.status()["progress"]["state"] == "ready"
    return fingerprint


def test_public_local_source_dataflow_acceptance(tmp_path):
    transport = PublicDatasetFixture(tmp_path)
    manager = local.DatasetManager(tmp_path / "home", transport=transport)
    private_note = manager.home / "private" / "dosare.db"
    private_note.write_bytes(b"private legislative gap workspace")

    first = _download(manager)
    status = manager.status()
    assert status["mode"] == "local"
    assert status["channel"] == local.DEFAULT_CHANNEL
    assert status["private_data_uploaded"] is False
    assert status["active"] is None
    assert status["offer"]["manifest"] == transport.manifest
    assert status["offer"]["url"].endswith("/2026-09-10/dataset-release.json")
    assert "manifest_text" not in status["offer"]
    assert transport.requests[:2] == [
        (local.DEFAULT_CHANNEL, 0),
        ("https://date.cristian-nichifor.com/2026-09-10/dataset-release.json", 0),
    ]

    manager.activate(first, lambda record: record)
    active_first = manager.active()
    assert active_first["release"] == "2026-09-10"
    assert private_note.read_bytes() == b"private legislative gap workspace"

    transport.publish("2026-09-11")
    second = _download(manager)
    manager.activate(second, lambda record: record)
    assert manager.active()["release"] == "2026-09-11"
    assert private_note.read_bytes() == b"private legislative gap workspace"

    manager.rollback(lambda record: record)
    rolled_back = manager.active()
    assert rolled_back["generation"] == first
    assert rolled_back["release"] == "2026-09-10"
    assert rolled_back["previous"] == {"generation": second, "release": "2026-09-11"}
    assert private_note.read_bytes() == b"private legislative gap workspace"
    assert manager.status()["private_data_uploaded"] is False


def test_source_status_contract_is_explicit_and_docs_backed():
    docs = (ROOT / "docs/SOURCE_DATAFLOW_ACCEPTANCE.md").read_text(encoding="utf-8")
    boundaries = source_sync.one_source_acceptance_boundaries()
    states = set(boundaries["states"])
    assert {"unavailable", "failed", "rate_limited", "needs_review"} <= states
    assert "hide_missing_or_unavailable_source" in boundaries["must_not_do"]
    for state in ("unavailable", "failed", "rate_limited", "needs_review"):
        assert f"`{state}`" in docs

    assert source_sync.classify_one_source_sync(http_status=404).state == "unavailable"
    assert source_sync.classify_one_source_sync(error="timeout").state == "failed"
    assert source_sync.classify_one_source_sync(http_status=429).state == "rate_limited"
    assert (
        source_sync.classify_one_source_sync(fetched_hash="a" * 64, needs_review=True).state
        == "needs_review"
    )
