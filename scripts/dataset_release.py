"""Validate and build immutable, uncompressed public dataset releases (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

MANIFEST_NAME = "dataset-release.json"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_DB_BYTES = 1024**4
MAX_REPORT_BYTES = 4 * 1024**2
MAX_INDEX_BYTES = 256 * 1024**2
DATABASE_NAMES = frozenset({"corpus.db", "initiative.db", "graf.db", "eu.db"})
REPORT_NAMES = frozenset(
    {
        "index.json",
        "termeni.json",
        "manifest.json",
        "vid.json",
        "neconstitutional.json",
        "norme_lovite.json",
        "considerente.json",
        "parlament.json",
        "ue_acoperire.json",
    }
)
PUBLIC_NAMES = DATABASE_NAMES | REPORT_NAMES
RELEASE_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-[A-Za-z0-9][A-Za-z0-9._-]{0,63})?"
SHA256_PATTERN = r"[0-9a-f]{64}"


class ReleaseError(ValueError):
    """Invalid or unsafe public release."""


def _fields(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ReleaseError(f"expected exactly these fields: {sorted(expected)}")


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ReleaseError(f"expected integer in [{minimum}, {maximum}]")


def validate_release_id(value):
    if type(value) is not str or re.fullmatch(RELEASE_PATTERN, value) is None:
        raise ReleaseError("invalid release ID")
    try:
        date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ReleaseError("invalid release date") from exc
    return value


def _digest(value):
    if type(value) is not str or re.fullmatch(SHA256_PATTERN, value) is None:
        raise ReleaseError("expected lowercase SHA-256")


def file_size_limit(name):
    if name in DATABASE_NAMES:
        return MAX_DB_BYTES
    return MAX_INDEX_BYTES if name == "index.json" else MAX_REPORT_BYTES


def validate_manifest(value):
    """Validate an already parsed manifest; return it unchanged, or raise ReleaseError."""
    _fields(value, {"schema_version", "release", "created_at", "app_contract", "files"})
    _integer(value["schema_version"], 1, 1)
    _integer(value["app_contract"], 1, 1)
    validate_release_id(value["release"])
    timestamp = value["created_at"]
    if (
        type(timestamp) is not str
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z",
            timestamp,
        )
        is None
    ):
        raise ReleaseError("created_at must be an ISO8601 UTC timestamp ending in Z")
    try:
        datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise ReleaseError("invalid created_at") from exc
    files = value["files"]
    if type(files) is not list or not 1 <= len(files) <= len(PUBLIC_NAMES):
        raise ReleaseError("invalid files array")
    seen = set()
    for entry in files:
        _fields(entry, {"name", "bytes", "sha256"})
        name = entry["name"]
        if type(name) is not str or name not in PUBLIC_NAMES or name in seen:
            raise ReleaseError("unknown or duplicate public filename")
        seen.add(name)
        _integer(entry["bytes"], 1, file_size_limit(name))
        _digest(entry["sha256"])
    if "corpus.db" not in seen:
        raise ReleaseError("corpus.db is required")
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ReleaseError("JSON exceeds 256 KiB")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ReleaseError(f"invalid JSON: {exc}") from exc


def load_manifest(raw: bytes | str):
    """Parse bounded UTF-8 JSON bytes/text, rejecting duplicate keys, then validate."""
    return validate_manifest(_parse(raw))


def validate(manifest):
    """Consumer entry point: return the validated dictionary without coercing types."""
    return validate_manifest(manifest)


def validate_channel(value, *, trusted_origin="https://date.cnwebify.dev"):
    """Validate a separate channel pointer, restricted to the configured HTTPS origin."""
    _fields(value, {"schema_version", "manifest", "sha256"})
    _integer(value["schema_version"], 1, 1)
    _digest(value["sha256"])
    url = value["manifest"]
    if type(url) is not str:
        raise ReleaseError("manifest URL must be a string")
    origin = urlsplit(trusted_origin)
    if (
        origin.scheme != "https"
        or not origin.netloc
        or origin.username
        or origin.password
        or origin.path not in ("", "/")
        or origin.query
        or origin.fragment
    ):
        raise ReleaseError("trusted_origin must be an HTTPS origin")
    prefix = f"https://{origin.netloc}/"
    if not url.startswith(prefix) or not url.endswith("/" + MANIFEST_NAME):
        raise ReleaseError("manifest must use the trusted origin and immutable release path")
    validate_release_id(url[len(prefix) : -len("/" + MANIFEST_NAME)])
    return value


def load_channel(raw: bytes | str, *, trusted_origin="https://date.cnwebify.dev"):
    return validate_channel(_parse(raw), trusted_origin=trusted_origin)


def hash_file(path: Path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _check_sqlite(path):
    for suffix in ("-wal", "-shm", "-journal"):
        if path.with_name(path.name + suffix).exists():
            raise ReleaseError(f"SQLite sidecar present: {path.name}{suffix}")
    with path.open("rb") as stream:
        header = stream.read(100)
    if len(header) != 100 or header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
        raise ReleaseError(f"not a standalone DELETE-journal SQLite database: {path.name}")
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        names = [row[0].lower() for row in con.execute("SELECT name FROM sqlite_master")]
        if any(re.search(r"private|dossier|dosar|documente|eu_achizitii", name) for name in names):
            raise ReleaseError(f"private/build-time tables in {path.name}")
        if con.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ReleaseError(f"SQLite quick_check failed: {path.name}")
    except sqlite3.DatabaseError as exc:
        raise ReleaseError(f"invalid SQLite: {path.name}") from exc
    finally:
        con.close()


def _payloads(folder):
    paths = sorted(folder.iterdir())
    for path in paths:
        if path.name == MANIFEST_NAME and path.is_file() and not path.is_symlink():
            continue
        if path.name not in PUBLIC_NAMES or path.is_symlink() or not path.is_file():
            raise ReleaseError(f"not an allowed regular public payload: {path.name}")
        yield path


def build_manifest(folder: Path, release: str, *, created_at: str | None = None):
    validate_release_id(release)
    entries = []
    for path in _payloads(folder):
        _integer(path.stat().st_size, 1, file_size_limit(path.name))
        if path.name in DATABASE_NAMES:
            _check_sqlite(path)
        size, digest = hash_file(path)
        entries.append({"name": path.name, "bytes": size, "sha256": digest})
    return validate_manifest(
        {
            "schema_version": 1,
            "release": release,
            "created_at": created_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "app_contract": 1,
            "files": entries,
        }
    )


def verify_release(folder: Path):
    with (folder / MANIFEST_NAME).open("rb") as stream:
        manifest = load_manifest(stream.read(MAX_MANIFEST_BYTES + 1))
    actual = build_manifest(folder, manifest["release"], created_at=manifest["created_at"])
    if sorted(manifest["files"], key=lambda e: e["name"]) != actual["files"]:
        raise ReleaseError("payload names, lengths or hashes differ from the manifest")
    return manifest


def _write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=True) + "\n")


def _copy_public(source, target):
    if source.is_symlink() or not source.is_file():
        raise ReleaseError(f"expected a regular curated source: {source}")
    _integer(source.stat().st_size, 1, file_size_limit(target.name))
    if target.name in DATABASE_NAMES:
        _check_sqlite(source)
    with target.open("xb") as output, source.open("rb") as input_file:
        shutil.copyfileobj(input_file, output, 1024 * 1024)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("folder", type=Path)
    build.add_argument("--release", required=True)
    build.add_argument(
        "--published-corpus", type=Path, help="copy a standalone publicat.db into folder/corpus.db"
    )
    build.add_argument(
        "--published-eu",
        type=Path,
        help="copy an explicitly curated standalone public EU database to eu.db",
    )
    build.add_argument(
        "--public-reports",
        type=Path,
        help="copy only allowlisted reports from an explicitly curated directory",
    )
    verify = commands.add_parser("verify")
    verify.add_argument("folder", type=Path)
    channel = commands.add_parser("channel", help="write a local proposal after verifying payloads")
    channel.add_argument("folder", type=Path)
    channel.add_argument("--manifest-url", required=True)
    channel.add_argument("--trusted-origin", default="https://date.cnwebify.dev")
    channel.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            validate_release_id(args.release)
            args.folder.mkdir(parents=True, exist_ok=True)
            if (args.folder / MANIFEST_NAME).exists():
                raise ReleaseError("release manifest already exists; use a fresh release folder")
            if args.published_corpus:
                if (
                    args.published_corpus.name != "publicat.db"
                    or args.published_corpus.is_symlink()
                ):
                    raise ReleaseError("--published-corpus must name a regular publicat.db")
                _copy_public(args.published_corpus, args.folder / "corpus.db")
            if args.published_eu:
                _copy_public(args.published_eu, args.folder / "eu.db")
            if args.public_reports:
                for source in sorted(args.public_reports.iterdir()):
                    if source.name not in REPORT_NAMES:
                        raise ReleaseError(f"not an allowed public report: {source.name}")
                    _copy_public(source, args.folder / source.name)
            manifest = build_manifest(args.folder, args.release)
            _write_new(args.folder / MANIFEST_NAME, manifest)
        else:
            manifest = verify_release(args.folder)
            if args.command == "channel":
                pointer = validate_channel(
                    {
                        "schema_version": 1,
                        "manifest": args.manifest_url,
                        "sha256": hash_file(args.folder / MANIFEST_NAME)[1],
                    },
                    trusted_origin=args.trusted_origin,
                )
                if urlsplit(pointer["manifest"]).path != f"/{manifest['release']}/{MANIFEST_NAME}":
                    raise ReleaseError("channel URL release differs from local manifest")
                _write_new(args.output, pointer)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"dataset release: {exc}\n")


if __name__ == "__main__":
    main()
