"""Loopback-only release server with explicit failure modes; no external publication."""

import hashlib
import json
import os
import shutil
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from scripts import dataset_release
from scripts.publica import DE_ARUNCAT

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("BROWSER_SOURCE_PORT", "8058"))


def fixtures():
    payloads = {}
    for label in ("a", "b", "minimal"):
        folder = ROOT / ".browser-generation-fixture" / label
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "web/data/corpus.db", folder / "corpus.db")
        with sqlite3.connect(folder / "corpus.db") as con:
            for table in DE_ARUNCAT:
                con.execute(f'DROP TABLE IF EXISTS "{table}"')
            con.execute("UPDATE acte SET titlu=?", ("GENERATION " + label.upper(),))
            con.commit()
            con.execute("VACUUM")
        release = "2026-09-10-" + label
        if label != "minimal":
            for name in ("manifest.json", "termeni.json"):
                raw = (ROOT / "web/data" / name).read_bytes()
                if name == "manifest.json":
                    raw = json.dumps(
                        {**json.loads(raw), "acte": 101 if label == "a" else 202}
                    ).encode()
                (folder / name).write_bytes(raw)
        manifest = dataset_release.build_manifest(folder, release)
        raw = json.dumps(manifest).encode()
        files = {f["name"]: (folder / f["name"]).read_bytes() for f in manifest["files"]}
        files["dataset-release.json"] = raw
        payloads[label] = {
            "files": files,
            "release": release,
            "channel": {
                "schema_version": 1,
                "manifest": f"http://127.0.0.1:{PORT}/{release}/dataset-release.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
        }
    return payloads


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/__fixture__/"):
            self.server.mode = path.rsplit("/", 1)[1]
            self.send_response(200)
            self.end_headers()
            return
        mode = self.server.mode
        fixture = self.server.payloads.get(
            mode, self.server.payloads["b" if mode in {"report", "no-range"} else "a"]
        )
        if path == "/channel.json":
            if mode == "unpublished":
                self.send_error(404)
                return
            channel = dict(fixture["channel"])
            if mode == "hash":
                channel["sha256"] = "0" * 64
            if mode == "origin":
                channel["manifest"] = "https://untrusted.invalid/2026-09-10/dataset-release.json"
            if mode == "duplicate":
                duplicate = fixture["files"]["dataset-release.json"][:-1] + b',"schema_version":1}'
                channel["sha256"] = hashlib.sha256(duplicate).hexdigest()
            raw = json.dumps(channel).encode()
        else:
            selected = next(
                (
                    f
                    for f in self.server.payloads.values()
                    if path.startswith("/" + f["release"] + "/")
                ),
                None,
            )
            if not selected or path.rsplit("/", 1)[-1] not in selected["files"]:
                self.send_error(404)
                return
            name = path.rsplit("/", 1)[-1]
            raw = selected["files"][name]
            if mode == "corpus-failure" and name == "corpus.db":
                self.send_error(404)
                return
            if mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "/untrusted")
                self.end_headers()
                return
            if mode == "report" and name == "termeni.json":
                raw = b"[]"
            if mode == "duplicate" and name == "dataset-release.json":
                raw = raw[:-1] + b',"schema_version":1}'
        start, end = 0, len(raw) - 1
        ranged = self.headers.get("Range") and mode != "no-range"
        if ranged:
            start, end = (int(n) for n in self.headers["Range"].removeprefix("bytes=").split("-"))
            end = min(end, len(raw) - 1)
        self.send_response(206 if ranged else 200)
        if mode != "cors":
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Expose-Headers", "Accept-Ranges, Content-Range, Content-Length"
            )
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if ranged:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(raw)}")
        content = raw[start : end + 1]
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    PORT = server.server_port
    server.payloads = fixtures()
    server.mode = "unpublished"
    server.serve_forever()
