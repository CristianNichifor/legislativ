"""Dependency-free release checks: python -m unittest discover -s tests -p test_local_launch.py."""

import hashlib
import http.client
import io
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import launcher
from scripts.build_runtime import build

ROOT = Path(__file__).resolve().parents[1]
STUB_SERVER = """import argparse, json, pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer
p = argparse.ArgumentParser()
p.add_argument("--data-home", required=True)
p.add_argument("--port", required=True, type=int)
p.add_argument("--fara-browser", action="store_true")
a = p.parse_args()
root = pathlib.Path(__file__).resolve().parents[1]
assert a.fara_browser
assert pathlib.Path.cwd() == pathlib.Path(a.data_home)
assert (pathlib.Path(a.data_home) / "private").is_dir()
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        content = (root / "app/index.html").read_bytes()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(content)
    def log_message(self, *args): pass
server = HTTPServer(("127.0.0.1", a.port), Handler)
(pathlib.Path(a.data_home) / "started.json").write_text(json.dumps(vars(a)))
server.serve_forever()
"""


class LocalLaunchTests(unittest.TestCase):
    def test_platform_paths(self):
        cases = [
            ("linux", {}, "/home/person", "/home/person/.local/share/legislativ"),
            ("linux", {"XDG_DATA_HOME": "relative"}, "/home/p", "/home/p/.local/share/legislativ"),
            ("linux", {"XDG_DATA_HOME": "/data"}, "/home/p", "/data/legislativ"),
            ("darwin", {}, "/Users/p", "/Users/p/Library/Application Support/legislativ"),
            (
                "win32",
                {"LOCALAPPDATA": r"C:\Users\A B\AppData\Local"},
                r"C:\Users\A B",
                r"C:\Users\A B\AppData\Local\legislativ",
            ),
            ("win32", {}, r"D:\Users\A", r"D:\Users\A\AppData\Local\legislativ"),
            (
                "win32",
                {"LOCALAPPDATA": "relative"},
                r"D:\Users\A",
                r"D:\Users\A\AppData\Local\legislativ",
            ),
            (
                "win32",
                {"LOCALAPPDATA": r"\\host\share\Local"},
                r"C:\Users\A",
                r"\\host\share\Local\legislativ",
            ),
        ]
        for platform, env, home, expected in cases:
            with self.subTest(platform=platform, env=env):
                self.assertEqual(launcher.default_data_home(platform, env, home), expected)

    def test_private_data_rejects_checkout(self):
        with patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            launcher.main(["--data-home", str(ROOT / "private")])

    def test_server_contract_and_collision(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            with patch("scripts.launcher.subprocess.call", return_value=7) as call:
                self.assertEqual(
                    launcher.main(
                        [
                            "--data-home",
                            directory,
                            "--port",
                            str(port),
                            "--fara-browser",
                            "--data-channel",
                            "https://datasets.example/channel.json",
                        ]
                    ),
                    7,
                )
            command = call.call_args.args[0]
            self.assertNotEqual(int(command[command.index("--port") + 1]), port)
            self.assertEqual(
                command[command.index("--data-home") + 1], str(Path(directory).resolve())
            )
            self.assertIn("--fara-browser", command)
            self.assertEqual(
                command[command.index("--data-channel") + 1],
                "https://datasets.example/channel.json",
            )
            self.assertEqual(call.call_args.kwargs["cwd"], Path(directory).resolve())
            self.assertTrue((Path(directory) / "private").is_dir())

    def test_archive_assets_and_exclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = build(ROOT, Path(directory))
            expected = hashlib.sha256(bundle.read_bytes()).hexdigest()
            self.assertEqual((Path(directory) / "SHA256SUMS").read_text().split()[0], expected)
            with zipfile.ZipFile(bundle) as outer:
                self.assertEqual(
                    set(outer.namelist()),
                    {"legislativ.pyz", "ruleaza.sh", "ruleaza.cmd", "README.md"},
                )
                with zipfile.ZipFile(io.BytesIO(outer.read("legislativ.pyz"))) as archive:
                    names = set(archive.namelist())
                    self.assertIn("scripts/server.py", names)
                    self.assertIn("scripts/launcher.py", names)
                    for path in (ROOT / "app").rglob("*"):
                        if path.is_file() and path.suffix in {".woff2", ".js", ".mjs", ".html"}:
                            name = path.relative_to(ROOT).as_posix()
                            self.assertEqual(archive.read(name), path.read_bytes())
                    self.assertFalse(any(n.endswith(".db") or "private/" in n for n in names))

    def smoke(self, stub):
        with tempfile.TemporaryDirectory(prefix="launch test ") as directory:
            base = Path(directory).resolve()
            source = ROOT
            if stub:
                source = base / "source"
                shutil.copytree(
                    ROOT / "scripts",
                    source / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"),
                )
                shutil.copytree(ROOT / "app", source / "app")
                (source / "docs").mkdir()
                shutil.copy2(ROOT / "docs/local-launch.md", source / "docs/local-launch.md")
                for name in ("ruleaza.sh", "ruleaza.cmd"):
                    shutil.copy2(ROOT / name, source / name)
                (source / "scripts/server.py").write_text(STUB_SERVER)
            bundle = build(source, base / "dist")
            extracted = base / "extracted"
            with zipfile.ZipFile(bundle) as archive:
                archive.extractall(extracted)
            data = base / "user data"
            env = dict(
                os.environ,
                PYTHONPATH=str(ROOT / "tests/launch_network_guard"),
                LAUNCH_NETWORK_LOG=str(base / "network.log"),
                LEGISLATIV_PYTHON=sys.executable,
                PYTHONUNBUFFERED="1",
            )
            with socket.socket() as occupied:
                occupied.bind(("127.0.0.1", 0))
                occupied.listen()
                preferred = occupied.getsockname()[1]
                args = ["--data-home", str(data), "--port", str(preferred), "--fara-browser"]
                if os.name == "nt":
                    command = ["cmd", "/d", "/c", "ruleaza.cmd", *args]
                else:
                    command = ["bash", str(extracted / "ruleaza.sh"), *args]
                with (base / "output.log").open("w+") as output:
                    proc = subprocess.Popen(
                        command,
                        cwd=extracted,
                        env=env,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        start_new_session=os.name != "nt",
                    )
                    try:
                        deadline = time.monotonic() + 30
                        body = None
                        last_probe_error = None
                        while time.monotonic() < deadline and proc.poll() is None:
                            text = (base / "output.log").read_text()
                            if "Pornesc pe http://127.0.0.1:" in text:
                                port = int(text.split("Pornesc pe http://127.0.0.1:")[1].split()[0])
                                self.assertNotEqual(port, preferred)
                                connection = http.client.HTTPConnection(
                                    "127.0.0.1", port, timeout=1
                                )
                                try:
                                    connection.request("GET", "/")
                                    response = connection.getresponse()
                                    self.assertEqual(response.status, 200)
                                    body = response.read()
                                    break
                                except OSError as exc:
                                    last_probe_error = str(exc)
                                finally:
                                    connection.close()
                            time.sleep(0.1)
                        if body is None:
                            diagnostic = (
                                base / "output.log"
                            ).read_text() + f"\nLast HTTP probe error: {last_probe_error}"
                            print(diagnostic, file=sys.stderr, flush=True)
                            self.fail(diagnostic)
                        self.assertIn(b"<html", body.lower())
                        self.assertTrue((data / "private").is_dir())
                        self.assertFalse((base / "network.log").exists())
                        self.assertFalse(list(extracted.rglob("*.db")))
                    finally:
                        if os.name == "nt":
                            subprocess.run(
                                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                capture_output=True,
                                check=False,
                            )
                        else:
                            os.killpg(proc.pid, signal.SIGTERM)
                        proc.wait(timeout=10)

    def test_packaged_cold_start_contract(self):
        self.smoke(stub=True)

    def test_real_server_cold_start(self):
        if "--data-home" not in (ROOT / "scripts/server.py").read_text():
            if os.environ.get("LEGISLATIV_REQUIRE_INTEGRATION") == "1":
                self.fail("Server integration missing: --data-home and no-corpus UI required")
            self.skipTest("Parent server --data-home integration not present on this base")
        self.smoke(stub=False)
