"""Managed-server integration, using real SQLite files and an in-memory HTTPS source."""

import hashlib
import http.client
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import chdir, closing, contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from scripts import cellar, depozit, documente_proiecte, dosare, instantanee_ue, server
from scripts.local_runtime import open_runtime
from scripts.servicii import Stare, rezumat

ROOT = Path(__file__).resolve().parents[1]
CHANNEL = "https://datasets.example/channel.json"


class Response(io.BytesIO):
    status = 200
    headers = {}


class Transport:
    def __init__(self):
        self.payloads = {}
        self.calls = []

    def small(self, url):
        self.calls.append(url)
        return self.payloads[url]

    def open(self, url, offset=0):
        self.calls.append(url)
        return Response(self.payloads[url])


def fixture_release(folder, transport, release, title, *, include_eu=True):
    folder.mkdir(parents=True)
    with depozit.deschide(folder / "corpus.db") as con:
        con.execute(
            "INSERT INTO acte(id,tip,titlu,citit_la) VALUES (?,?,?,?)",
            ("lege-1-2026", "LEGE", title, "2026-01-01"),
        )
    with cellar.deschide(folder / "eu.db"):
        pass
    (folder / "termeni.json").write_text(json.dumps([{"termen": title, "definitie": title}]))
    (folder / "vid.json").write_text(json.dumps([{"id": title}]))
    for name in ("corpus.db", "eu.db"):
        with closing(sqlite3.connect(folder / name)) as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.execute("PRAGMA journal_mode=DELETE")
    entries = []
    for name in ("corpus.db", "eu.db", "termeni.json", "vid.json"):
        if name == "eu.db" and not include_eu:
            continue
        payload = (folder / name).read_bytes()
        entries.append(
            {"name": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
        transport.payloads[f"https://datasets.example/{release}/{name}"] = payload
    raw = json.dumps(
        {
            "schema_version": 1,
            "app_contract": 1,
            "release": release,
            "created_at": "2026-09-10T00:00:00Z",
            "files": entries,
        },
        indent=2,
    ).encode()
    fingerprint = hashlib.sha256(raw).hexdigest()
    url = f"https://datasets.example/{release}/dataset-release.json"
    transport.payloads[url] = raw
    transport.payloads[CHANNEL] = json.dumps(
        {"schema_version": 1, "manifest": url, "sha256": fingerprint}
    ).encode()
    return fingerprint


@contextmanager
def running(runtime):
    with ThreadingHTTPServer(
        ("127.0.0.1", 0), server.face_handler(runtime.manager.current_state, runtime=runtime)
    ) as httpd:
        httpd.daemon_threads = False
        thread = threading.Thread(target=httpd.serve_forever)
        thread.start()
        try:
            yield httpd
        finally:
            httpd.shutdown()
            thread.join(timeout=5)


def request(httpd, path="/api/date", body=None, *, method=None, headers=None):
    method = method or ("POST" if body is not None else "GET")
    payload = json.dumps(body) if body is not None else None
    headers = {"Content-Type": "application/json", **(headers or {})}
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    try:
        connection.request(method, path, payload, headers)
        response = connection.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), data
    finally:
        connection.close()


class LocalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="local runtime ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "user data"
        self.transport = Transport()

    def open(self):
        return open_runtime(self.home, CHANNEL, transport=self.transport)

    def offer(self, name, title):
        return fixture_release(self.base / name, self.transport, name, title)

    def ready(self, runtime, httpd, name, title):
        fingerprint = self.offer(name, title)
        self.assertEqual(request(httpd, body={"action": "check"})[0], 200)
        self.assertEqual(request(httpd, body={"action": "download", "sha256": fingerprint})[0], 200)
        runtime.manager.thread.join(timeout=5)
        status = runtime.manager.status()
        self.assertEqual(status["progress"]["state"], "ready", status)
        return fingerprint

    def activate(self, runtime, httpd, name, title):
        fingerprint = self.ready(runtime, httpd, name, title)
        result = request(httpd, body={"action": "activate", "sha256": fingerprint})
        self.assertEqual(result[0], 200, result[2])
        return runtime.manager.current_state

    def test_first_run_is_offline_and_missing_corpus_is_explicit(self):
        with self.open() as runtime, running(runtime) as httpd:
            self.assertEqual(request(httpd, "/")[0], 200)
            code, headers, data = request(httpd)
            self.assertEqual(code, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIsNone(json.loads(data)["active"])
            summary = request(httpd, "/api/rezumat")
            self.assertEqual(summary[0], 200)
            self.assertFalse(json.loads(summary[2])["dataset_available"])
            self.assertEqual(request(httpd, "/api/cauta?q=test")[0], 503)
            self.assertEqual(self.transport.calls, [])
            self.assertFalse(list(self.home.rglob("corpus.db")))

    def test_local_origin_body_bounds_and_fixed_channel(self):
        with self.open() as runtime, running(runtime) as httpd:
            for headers in (
                {"Host": "attacker.example"},
                {"Origin": "https://attacker.example"},
                {"Origin": "null"},
                {"Origin": ""},
                {"Host": "localhost"},
            ):
                self.assertEqual(request(httpd, headers=headers)[0], 403)
                self.assertEqual(request(httpd, body={"action": "check"}, headers=headers)[0], 403)
            for body in (
                [],
                None,
                {"action": []},
                {"action": "check", "url": "https://evil.example"},
                {"action": "activate", "sha256": "../outside"},
            ):
                self.assertEqual(request(httpd, body=body, method="POST")[0], 400)
            self.assertEqual(request(httpd, body={"action": "x" * 5000})[0], 413)
            self.assertEqual(
                request(httpd, body={}, headers={"Content-Type": "text/plain"})[0], 415
            )
            self.assertEqual(self.transport.calls, [])

    def test_manager_failures_have_non_success_status(self):
        with self.open() as runtime, running(runtime) as httpd:
            self.assertEqual(request(httpd, body={"action": "rollback"})[0], 409)
            self.assertEqual(
                request(httpd, body={"action": "activate", "sha256": "a" * 64})[0], 409
            )
            with patch.object(runtime.manager, "check", side_effect=OSError("offline")):
                self.assertEqual(request(httpd, body={"action": "check"})[0], 503)
            with patch.object(runtime.manager, "check", side_effect=RuntimeError("broken")):
                self.assertEqual(request(httpd, body={"action": "check"})[0], 500)

    def test_fixed_assets_and_fonts(self):
        app = self.base / "app"
        app.mkdir()
        for name in ("dataset-updates.js", "browser-workspace.js"):
            (app / name).write_text("export const loaded = true;")
        (app / "secret.txt").write_text("private")
        with self.open() as runtime, running(runtime) as httpd:
            self.assertEqual(request(httpd, "/fonts/aileron-400.woff2")[0], 200)
            with patch.object(server, "APP", app):
                for name in ("dataset-updates.js", "browser-workspace.js"):
                    self.assertEqual(request(httpd, "/" + name)[0], 200)
                for path in ("/secret.txt", "/../secret.txt", "/%2e%2e/secret.txt"):
                    self.assertEqual(request(httpd, path)[0], 404)

    def test_activation_fresh_state_rollback_and_restart(self):
        with self.open() as runtime, running(runtime) as httpd:
            first = self.activate(runtime, httpd, "2026-09-09", "First")
            self.assertEqual(first.titlu("lege-1-2026"), "First")
            self.assertEqual(first.termeni[0].termen, "First")
            self.assertIsNone(first.date_dir)
            self.assertFalse(first.pe_shard)
            self.assertEqual(rezumat(first)["acte"], 1)
            self.assertEqual(first._dosare_db, self.home / "private/dosare.db")
            self.assertEqual(
                documente_proiecte.cale_store(first), self.home / "private/initiative.documente.db"
            )
            second = self.activate(runtime, httpd, "2026-09-10", "Second")
            self.assertIsNot(first, second)
            self.assertEqual(second.titlu("lege-1-2026"), "Second")
            self.assertEqual(second.vid, [{"id": "Second"}])
            self.assertNotEqual(first.eu, second.eu)
            self.assertEqual(request(httpd, body={"action": "rollback"})[0], 200)
            rolled = runtime.manager.current_state
            self.assertEqual(rolled.titlu("lege-1-2026"), "First")
            self.assertNotIn(rolled.eu, (first.eu, second.eu))
            record = runtime.manager.active()
            old_bytes = Path(rolled.eu).read_bytes()
        with (
            patch("scripts.local_runtime.prepare_eu", side_effect=AssertionError("reprepared")),
            self.open() as reopened,
        ):
            self.assertEqual(reopened.manager.current_state.eu, rolled.eu)
            self.assertEqual(reopened.manager.active(), record)
            self.assertEqual(Path(rolled.eu).read_bytes(), old_bytes)
        Path(rolled.eu).unlink()
        with self.assertRaisesRegex(ValueError, "privata activa lipseste"), self.open():
            pass

    def test_private_import_survives_rollback(self):
        with self.open() as runtime, running(runtime) as httpd:
            self.activate(runtime, httpd, "2026-09-09", "First")
            state = self.activate(runtime, httpd, "2026-09-10", "Second")
            from scripts.achizitii_ue import ATTEMPT_SCHEMA

            manifest = cellar.ManifestareUE(
                celex="32018R1805",
                work_uri="https://example.test/work",
                expression_uri="https://example.test/expression",
                manifestation_uri="https://example.test/manifestation",
                limba="RON",
                format="xhtml",
                item_url="https://example.test/document",
                titlu="Import",
                data_document="2018-11-14",
                tip_uri="regulation",
                in_vigoare=True,
            )
            with cellar.deschide(state.eu) as con:
                cellar.scrie_celex(
                    con,
                    manifest.celex,
                    [manifest],
                    manifest,
                    "Articolul 1\nObservatie privata pentru cercetare.",
                )
                con.execute(ATTEMPT_SCHEMA)
                con.execute(
                    "INSERT INTO eu_achizitii VALUES (?,?,?,?,?)",
                    (manifest.celex, "2026-09-10", "2026-09-10", "ok", None),
                )
                snapshot = instantanee_ue.citeste_curenta(con, manifest.celex)
            self.assertEqual(request(httpd, body={"action": "rollback"})[0], 200)
            rolled = runtime.manager.current_state
            with cellar.deschide(rolled.eu, readonly=True) as con:
                self.assertEqual(instantanee_ue.citeste_curenta(con, manifest.celex), snapshot)
            for path in (self.home / "datasets").glob("*/eu.db"):
                with cellar.deschide(path, readonly=True) as con:
                    self.assertEqual(con.execute("SELECT count(*) FROM eu_acte").fetchone()[0], 0)

    def test_failed_activation_keeps_pointer_and_state(self):
        with self.open() as runtime, running(runtime) as httpd:
            state = self.activate(runtime, httpd, "2026-09-09", "First")
            fingerprint = self.ready(runtime, httpd, "2026-09-10", "Second")
            record = (self.home / "active.json").read_bytes()
            with patch("scripts.local_runtime.prepare_eu", side_effect=OSError("disk full")):
                result = request(httpd, body={"action": "activate", "sha256": fingerprint})
                self.assertEqual(result[0], 503)
            self.assertIs(runtime.manager.current_state, state)
            self.assertEqual((self.home / "active.json").read_bytes(), record)

    def test_request_blocks_state_switch_until_response_finishes(self):
        with self.open() as runtime, running(runtime) as httpd:
            old = runtime.manager.current_state
            entered, release, switched = (threading.Event() for _ in range(3))
            result = []

            def slow_summary(state):
                entered.set()
                self.assertTrue(release.wait(timeout=5))
                self.assertIs(state, old)
                self.assertIs(runtime.manager.current_state, old)
                return {"generation": "old"}

            def swap():
                with runtime.manager.runtime_lock:
                    runtime.manager.current_state = runtime.state_factory(None)
                    switched.set()

            with patch.object(server, "rezumat", slow_summary):
                reader = threading.Thread(
                    target=lambda: result.append(request(httpd, "/api/rezumat"))
                )
                reader.start()
                self.assertTrue(entered.wait(timeout=5))
                writer = threading.Thread(target=swap)
                writer.start()
                try:
                    self.assertFalse(switched.wait(timeout=0.1))
                finally:
                    release.set()
                    reader.join(timeout=5)
                    writer.join(timeout=5)
            self.assertTrue(switched.is_set())
            self.assertEqual(json.loads(result[0][2]), {"generation": "old"})

    def test_lifetime_lock_rejects_second_server_process(self):
        command = [
            sys.executable,
            "-B",
            "-m",
            "scripts.server",
            "--data-home",
            str(self.home),
            "--port",
            "0",
            "--fara-browser",
        ]
        with self.open():
            result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
        with self.open():
            pass

    def test_explicit_reports_never_fall_back_to_cwd_or_shards(self):
        explicit = self.base / "reports"
        explicit.mkdir()
        shards = self.base / "shards"
        shards.mkdir()
        (shards / "termeni.json").write_text('[{"termen":"wrong","definitie":"wrong"}]')
        (self.base / "web/data").mkdir(parents=True)
        (self.base / "web/data/vid.json").write_text('[{"wrong":true}]')
        (self.base / "vid.json").write_text('[{"wrong":true}]')
        with chdir(self.base):
            state = Stare(date_dir=str(shards), reports_dir=str(explicit))
        self.assertEqual(state.vid, [])
        self.assertEqual(state.report_root, explicit)
        self.assertEqual(state.termeni, [])
        self.assertTrue(state.pe_shard)
        (explicit / "termeni.json").write_text('[{"termen":"right","definitie":"right"}]')
        state = Stare(reports_dir=str(explicit))
        self.assertFalse(state.pe_shard)
        self.assertEqual(state.termeni[0].termen, "right")

    def test_private_dossier_helper_contract(self):
        with self.open() as runtime:
            self.assertEqual(
                dosare.cale(runtime.manager.current_state), self.home / "private/dosare.db"
            )

    def test_dossier_write_stays_private_before_and_after_activation(self):
        with self.open() as runtime, running(runtime) as httpd:
            body = {"id": "a" * 32, "titlu": "Research"}
            self.assertEqual(request(httpd, "/api/dosare", body)[0], 200)
            private_db = self.home / "private/dosare.db"
            self.assertTrue(private_db.is_file())
            self.activate(runtime, httpd, "2026-09-10", "First")
            code, _, data = request(httpd, "/api/dosare?id=" + body["id"])
            self.assertEqual(code, 200)
            self.assertIn(b"Research", data)
            self.assertFalse(list((self.home / "datasets").rglob("*dosare.db")))

    def test_corpus_only_release_rejects_already_active_download(self):
        with self.open() as runtime, running(runtime) as httpd:
            fingerprint = fixture_release(
                self.base / "corpus-only", self.transport, "2026-09-10", "First", include_eu=False
            )
            self.assertEqual(request(httpd, body={"action": "check"})[0], 200)
            result = request(httpd, body={"action": "download", "sha256": fingerprint})
            self.assertEqual(result[0], 200)
            runtime.manager.thread.join(timeout=5)
            code, _, data = request(httpd, body={"action": "activate", "sha256": fingerprint})
            self.assertEqual(code, 200, data)
            self.assertTrue(Path(runtime.manager.current_state.eu).is_file())
            record = runtime.manager.active()
            self.assertEqual(request(httpd, body={"action": "check"})[0], 200)
            self.assertEqual(runtime.manager.status()["progress"]["state"], "active")
            self.assertEqual(
                request(httpd, body={"action": "download", "sha256": fingerprint})[0], 409
            )
            self.assertEqual(
                request(httpd, body={"action": "activate", "sha256": fingerprint})[0], 409
            )
            self.assertEqual(runtime.manager.active(), record)
            with self.assertRaises(FileExistsError):
                runtime.state_factory(record)

    def test_post_replace_error_reports_committed_pointer_and_matching_runtime(self):
        from scripts import date_locale

        with self.open() as runtime, running(runtime) as httpd:
            first = self.activate(runtime, httpd, "2026-09-09", "First")
            fingerprint = self.ready(runtime, httpd, "2026-09-10", "Second")
            real_write = date_locale.atomic_json

            def uncertain_write(path, value):
                real_write(path, value)
                raise date_locale.CommittedWriteError("Pointer changed; flush failed")

            with patch.object(date_locale, "atomic_json", uncertain_write):
                code, _, data = request(httpd, body={"action": "activate", "sha256": fingerprint})
            self.assertEqual(code, 503)
            self.assertTrue(json.loads(data)["committed"])
            self.assertIsNot(runtime.manager.current_state, first)
            self.assertEqual(runtime.manager.current_state.dataset_record, runtime.manager.active())
            self.assertEqual(runtime.manager.current_state.titlu("lege-1-2026"), "Second")

    def test_shutdown_joins_worker_before_releasing_lifetime_lock(self):
        cancelling, finish, closed = (threading.Event() for _ in range(3))
        errors = []

        def owner():
            try:
                with self.open() as runtime:

                    def worker():
                        runtime.manager.cancelled.wait(timeout=5)
                        cancelling.set()
                        finish.wait(timeout=5)

                    runtime.manager.thread = threading.Thread(target=worker)
                    runtime.manager.thread.start()
                closed.set()
            except Exception as exc:
                errors.append(exc)

        owner_thread = threading.Thread(target=owner)
        owner_thread.start()
        try:
            self.assertTrue(cancelling.wait(timeout=5))
            self.assertFalse(closed.is_set())
            with self.assertRaises(OSError), self.open():
                pass
        finally:
            finish.set()
            owner_thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertTrue(closed.is_set())
