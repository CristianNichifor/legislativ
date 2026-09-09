import copy
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts import dataset_release as release

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def manifest():
    return {
        "schema_version": 1,
        "release": "2026-09-10-rc.1",
        "app_contract": 1,
        "created_at": "2026-09-10T12:00:00Z",
        "files": [{"name": "corpus.db", "bytes": 4096, "sha256": "a" * 64}],
    }


def database(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE acte (id INTEGER)")
    con.execute("INSERT INTO acte VALUES (1)")
    con.commit()
    con.close()
    return path


def test_valid_contract_and_schema(manifest):
    assert release.validate(manifest) == manifest
    assert release.load_manifest(json.dumps(manifest).encode()) == manifest
    schema = json.loads((ROOT / "schema/dataset_release.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", 2),
        ("app_contract", False),
        ("app_contract", 2),
        ("app_contract", "1"),
        ("release", "2026-02-30"),
        ("release", "../2026-09-10"),
        ("release", "2026-09-10/evil"),
        ("release", "2026-09-10-"),
        ("release", "2026-09-10-" + "x" * 65),
        ("release", "2026-09-10\n"),
        ("created_at", "2026-09-10T12:00:00+00:00"),
        ("created_at", "2026-09-10T25:00:00Z"),
        ("created_at", 42),
        ("files", []),
        ("files", {}),
        ("extra", 1),
    ],
)
def test_invalid_manifest(manifest, key, value):
    manifest[key] = value
    with pytest.raises(release.ReleaseError):
        release.validate(manifest)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("bytes", 0),
        ("bytes", -1),
        ("bytes", True),
        ("bytes", 1.0),
        ("bytes", release.MAX_DB_BYTES + 1),
        ("sha256", "A" * 64),
        ("sha256", "a" * 63),
        ("name", "documente.db"),
        ("name", "dossier.db"),
        ("name", "private.db"),
        ("name", "../corpus.db"),
        ("name", "corpus.db.gz"),
        ("name", "https://other/corpus.db"),
        ("url", "https://other/corpus.db"),
    ],
)
def test_invalid_file(manifest, key, value):
    manifest["files"][0][key] = value
    with pytest.raises(release.ReleaseError):
        release.validate(manifest)


def test_duplicates_missing_corpus_and_report_limit(manifest):
    entry = copy.deepcopy(manifest["files"][0])
    manifest["files"].append(entry)
    with pytest.raises(release.ReleaseError):
        release.validate(manifest)
    entry["name"] = "vid.json"
    entry["bytes"] = release.MAX_REPORT_BYTES
    release.validate(manifest)
    entry["bytes"] += 1
    with pytest.raises(release.ReleaseError):
        release.validate(manifest)
    manifest["files"] = [entry | {"bytes": 1}]
    with pytest.raises(release.ReleaseError):
        release.validate(manifest)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema_version":1,"schema_version":1}',
        b"\xff",
        b"[]",
        b"NaN",
        b" " * (release.MAX_MANIFEST_BYTES + 1),
        b"[" * 2000,
    ],
)
def test_bad_json(raw):
    with pytest.raises(release.ReleaseError):
        release.load_manifest(raw)


def test_nested_duplicate_keys(manifest):
    raw = json.dumps(manifest).replace('"bytes": 4096', '"bytes": 4096, "bytes": 4096')
    with pytest.raises(release.ReleaseError, match="duplicate"):
        release.load_manifest(raw)


def test_build_copy_verify_and_channel(tmp_path):
    source = database(tmp_path / "publicat.db")
    original = source.read_bytes()
    folder = tmp_path / "release"
    release.main(
        ["build", str(folder), "--release", "2026-09-10", "--published-corpus", str(source)]
    )
    manifest = release.verify_release(folder)
    assert source.read_bytes() == original == (folder / "corpus.db").read_bytes()
    assert manifest["files"][0]["sha256"] == hashlib.sha256(original).hexdigest()
    output = tmp_path / "channel.json"
    release.main(
        [
            "channel",
            str(folder),
            "--manifest-url",
            "https://date.cnwebify.dev/2026-09-10/dataset-release.json",
            "--output",
            str(output),
        ]
    )
    pointer = release.load_channel(output.read_bytes())
    assert (
        pointer["sha256"]
        == hashlib.sha256((folder / release.MANIFEST_NAME).read_bytes()).hexdigest()
    )
    with pytest.raises(SystemExit):
        release.main(["build", str(folder), "--release", "2026-09-10"])
    with (folder / "corpus.db").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(release.ReleaseError):
        release.verify_release(folder)


@pytest.mark.parametrize(
    "name",
    [
        "private.db",
        "dossier.db",
        "documente.db",
        "other.json",
        "corpus.db-wal",
        "corpus.db-shm",
        "corpus.db-journal",
    ],
)
def test_reject_unknown_files_and_sidecars(tmp_path, name):
    database(tmp_path / "corpus.db")
    (tmp_path / name).write_bytes(b"x")
    with pytest.raises(release.ReleaseError):
        release.build_manifest(tmp_path, "2026-09-10")


def test_reject_wal_header_without_sidecar(tmp_path):
    path = database(tmp_path / "corpus.db")
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.close()
    assert not path.with_name("corpus.db-wal").exists()
    with pytest.raises(release.ReleaseError, match="DELETE-journal"):
        release.build_manifest(tmp_path, "2026-09-10")


def test_reject_live_uncheckpointed_source_without_mutating(tmp_path):
    path = database(tmp_path / "publicat.db")
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("INSERT INTO acte VALUES (2)")
        con.commit()
        before = path.read_bytes()
        wal = path.with_name("publicat.db-wal")
        before_wal = wal.read_bytes()
        with pytest.raises(SystemExit):
            release.main(
                [
                    "build",
                    str(tmp_path / "release"),
                    "--release",
                    "2026-09-10",
                    "--published-corpus",
                    str(path),
                ]
            )
        assert path.read_bytes() == before and wal.read_bytes() == before_wal
    finally:
        con.close()


def test_reject_private_table_and_symlink(tmp_path):
    path = database(tmp_path / "corpus.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE documente (secret TEXT)")
    con.close()
    with pytest.raises(release.ReleaseError, match="private"):
        release.build_manifest(tmp_path, "2026-09-10")
    path.unlink()
    source = database(tmp_path / "publicat.db")
    path.symlink_to(source)
    with pytest.raises(release.ReleaseError):
        release.build_manifest(tmp_path, "2026-09-10")


@pytest.mark.parametrize(
    "url",
    [
        "http://date.cnwebify.dev/2026-09-10/dataset-release.json",
        "https://evil.test/2026-09-10/dataset-release.json",
        "https://user@date.cnwebify.dev/2026-09-10/dataset-release.json",
        "https://date.cnwebify.dev/latest/dataset-release.json",
        "https://date.cnwebify.dev/../2026-09-10/dataset-release.json",
        "https://date.cnwebify.dev/%2e%2e/dataset-release.json",
        "https://date.cnwebify.dev/2026-09-10/dataset-release.json?x=1",
        "https://date.cnwebify.dev/2026-09-10/dataset-release.json#x",
    ],
)
def test_bad_channel(url):
    with pytest.raises(release.ReleaseError):
        release.validate_channel({"schema_version": 1, "manifest": url, "sha256": "a" * 64})


@pytest.mark.parametrize(
    ("latest", "failure"),
    [
        (0, ""),
        (1, ""),
        (1, "occupied"),
        (1, "check"),
        (1, "copyto"),
        (1, "lsf"),
        (1, "manifest-check"),
    ],
)
def test_publication_order_offline(tmp_path, latest, failure):
    stage = tmp_path / "payload"
    stage.mkdir()
    (stage / "corpus.db").write_bytes(b"payload")
    (stage / release.MANIFEST_NAME).write_bytes(b"manifest")
    # Execute the publication tail with shell functions replacing every external operation.
    tail = (ROOT / "infra/republica.sh").read_text().split("r2()", 1)[1]
    script = (
        """set -euo pipefail
rclone() {
  echo "$*" >> "$LUCRU/calls"
  if [ "$FAILURE" = "$1" ]; then return 1; fi
  if [ "$FAILURE" = manifest-check ] && [ "$1" = check ]; then
    case "$*" in *--include*) return 1 ;; esac
  fi
  if [ "$1" = lsf ] && [ "$FAILURE" = occupied ]; then echo existing; fi
  return 0
}
uv() { return 0; }
r2()"""
        + tail
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "LUCRU": str(tmp_path),
            "STAGE": str(stage),
            "IDX": str(tmp_path / "idx"),
            "BUCKET": "fixture",
            "PREFIX": "2026-09-10",
            "LATEST": str(latest),
            "FAILURE": failure,
        },
    )
    calls = (tmp_path / "calls").read_text().splitlines()
    manifest_upload = [
        i
        for i, line in enumerate(calls)
        if line.startswith("copyto") and "dataset-release.json" in line
    ]
    channel_upload = [
        i for i, line in enumerate(calls) if line.startswith("copyto") and "channel.json" in line
    ]
    if failure:
        assert result.returncode != 0
        assert bool(manifest_upload) == (failure == "manifest-check")
        assert not channel_upload
    else:
        assert result.returncode == 0, result.stderr
        first_check = next(i for i, line in enumerate(calls) if line.startswith("check"))
        assert first_check < manifest_upload[0]
        assert bool(channel_upload) == bool(latest)
        if latest:
            assert channel_upload[0] > manifest_upload[0] + 1
