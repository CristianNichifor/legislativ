"""Run release acceptance against a prepared public dataset folder.

The runner uses the production local-runtime update path, but a file-backed
transport, so it can validate multi-GB release payloads before R2 publication.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import sqlite3
import tempfile
import threading
import time
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from urllib.parse import quote, urlencode

from scripts import depozit, server
from scripts.dataset_release import MANIFEST_NAME, verify_release
from scripts.dosare import LAW_WORKBENCH_ENGINE_VERSION
from scripts.local_runtime import open_runtime

CHANNEL = "https://datasets.example/channel.json"


class FileResponse:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, path: Path, offset: int = 0):
        self.stream = path.open("rb")
        self.stream.seek(offset)

    def read(self, size=-1):
        return self.stream.read(size)

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class BytesResponse(io.BytesIO):
    status = 200
    headers: dict[str, str] = {}


class Transport:
    def __init__(self):
        self.small_payloads: dict[str, bytes] = {}
        self.files: dict[str, Path] = {}

    def small(self, url):
        return self.small_payloads[url]

    def open(self, url, offset=0):
        if url in self.files:
            return FileResponse(self.files[url], offset)
        return BytesResponse(self.small_payloads[url][offset:])


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def point_channel(transport: Transport, manifest_url: str, manifest_raw: bytes) -> str:
    fingerprint = sha256(manifest_raw)
    transport.small_payloads[manifest_url] = manifest_raw
    transport.small_payloads[CHANNEL] = json.dumps(
        {"schema_version": 1, "manifest": manifest_url, "sha256": fingerprint}
    ).encode("utf-8")
    return fingerprint


def baseline_release(folder: Path, transport: Transport) -> str:
    folder.mkdir(parents=True)
    with depozit.deschide(folder / "corpus.db") as con:
        con.execute(
            "INSERT INTO acte(id,tip,titlu,citit_la) VALUES (?,?,?,?)",
            ("lege-setup-2026", "LEGE", "Setup acceptance", "2026-01-01"),
        )
    with closing(sqlite3.connect(folder / "corpus.db")) as con:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("PRAGMA journal_mode=DELETE")
    payload = (folder / "corpus.db").read_bytes()
    manifest = {
        "schema_version": 1,
        "app_contract": 1,
        "release": "2026-09-09-test",
        "created_at": "2026-09-10T00:00:00Z",
        "files": [{"name": "corpus.db", "bytes": len(payload), "sha256": sha256(payload)}],
    }
    raw = json.dumps(manifest, indent=2).encode("utf-8")
    base = "https://datasets.example/2026-09-09-test"
    transport.small_payloads[f"{base}/corpus.db"] = payload
    return point_channel(transport, f"{base}/{MANIFEST_NAME}", raw)


def release_from_folder(folder: Path, transport: Transport) -> tuple[str, str]:
    manifest = verify_release(folder)
    raw = (folder / MANIFEST_NAME).read_bytes()
    base = f"https://datasets.example/{manifest['release']}"
    for entry in manifest["files"]:
        transport.files[f"{base}/{entry['name']}"] = folder / entry["name"]
    return manifest["release"], point_channel(transport, f"{base}/{MANIFEST_NAME}", raw)


@contextmanager
def running(runtime):
    with server.LoopbackHTTPServer(
        ("127.0.0.1", 0), server.face_handler(runtime.manager.current_state, runtime=runtime)
    ) as httpd:
        thread = threading.Thread(target=httpd.serve_forever)
        thread.start()
        try:
            yield httpd
        finally:
            httpd.shutdown()
            thread.join(timeout=5)


def request(httpd, path="/api/date", body=None, *, timeout=1800):
    payload = json.dumps(body) if body is not None else None
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=timeout)
    try:
        connection.request(
            "POST" if body is not None else "GET",
            path,
            payload,
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read()
        data = json.loads(raw) if raw else None
        if response.status != 200:
            raise AssertionError(f"{response.status} {data}")
        return data
    finally:
        connection.close()


def wait_ready(runtime, *, interval=5):
    while runtime.manager.thread and runtime.manager.thread.is_alive():
        status = runtime.manager.status()
        progress = status["progress"]
        total = progress.get("total") or 0
        copied = progress.get("bytes") or 0
        percent = f" {copied / total:.1%}" if total else ""
        print(
            f"download: {progress.get('state')} {progress.get('file', '')} "
            f"{copied}/{total}{percent}",
            flush=True,
        )
        runtime.manager.thread.join(timeout=interval)
    status = runtime.manager.status()
    if status["progress"]["state"] != "ready":
        raise AssertionError(status)


def activate(runtime, httpd, fingerprint: str):
    request(httpd, body={"action": "check"})
    request(httpd, body={"action": "download", "sha256": fingerprint})
    wait_ready(runtime)
    print("activate: starting", flush=True)
    request(httpd, body={"action": "activate", "sha256": fingerprint})
    print("activate: complete", flush=True)


def _first_act_id(results: dict) -> str:
    for row in results.get("results") or []:
        act_id = row.get("act_id") or row.get("id")
        if isinstance(act_id, str) and act_id.strip():
            return act_id.strip()
    return ""


def _proposal_candidate(findings: list[dict]) -> dict | None:
    for finding in findings:
        if finding.get("tip") not in {"lacuna", "ccr"}:
            continue
        evidence = finding.get("dovada") or {}
        act_id = evidence.get("act_tinta") or evidence.get("act_id")
        if act_id and evidence.get("locator"):
            return finding
    return None


def pilot_workbench(httpd, dossier_id: str, *, search_results: dict, act_id: str = "") -> dict:
    """Exercise the real law-workbench-to-dossier path without a synthetic finding."""
    selected = act_id.strip() or _first_act_id(search_results)
    if not selected:
        return {
            "status": "skipped_no_search_act",
            "finding_to_proposal": "not_exercised_no_act",
        }
    workbench = request(httpd, "/api/fisa-act?act=" + quote(selected, safe=""))
    if not workbench.get("gasit"):
        raise AssertionError(workbench)
    run = request(
        httpd,
        "/api/dosare/rulari",
        {"dosar_id": dossier_id, "filtre": {"act": selected}},
    )
    if run["engine_version"] != LAW_WORKBENCH_ENGINE_VERSION:
        raise AssertionError(run)
    query = urlencode({"id": dossier_id, "rulare_id": run["id"]})
    review = request(httpd, "/api/dosare/revizuiri?" + query)
    findings = review.get("constatari") or []
    candidate = _proposal_candidate(findings)
    signals = ((run.get("raport") or {}).get("rand") or {}).get("semnale") or {}
    return {
        "status": "passed",
        "act_id": selected,
        "engine_version": run["engine_version"],
        "signals": {
            "viduri": int(signals.get("viduri") or 0),
            "neconstitutionale": int(signals.get("neconstitutionale") or 0),
            "initiative_in_lucru": int(signals.get("initiative_in_lucru") or 0),
            "amendamente_primite": int(signals.get("amendamente_primite") or 0),
            "referinte_ue": len(run.get("raport", {}).get("referinte_ue") or []),
        },
        "reviewable_findings": len(findings),
        "finding_to_proposal": (
            "eligible_real_finding_available"
            if candidate
            else "not_exercised_no_authentic_gap_or_ccr_finding"
        ),
        "proposal_candidate_id": candidate["id"] if candidate else None,
        "limitations": [
            "No synthetic bridge is used by this acceptance runner.",
            "Proposal save is not automated until a real reviewer-approved finding/wording exists.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_dir", type=Path)
    parser.add_argument(
        "--data-home",
        type=Path,
        help="fresh local-runtime data directory; defaults to a temp dir beside release_dir",
    )
    parser.add_argument("--keep", action="store_true", help="keep the generated data home")
    parser.add_argument("--min-acts", type=int, default=1000)
    parser.add_argument("--skip-search", action="store_true", help="only for tiny smoke fixtures")
    parser.add_argument(
        "--pilot-act",
        default="",
        help="act id to open in the real-data law workbench; defaults to the first search result",
    )
    args = parser.parse_args(argv)

    release_dir = args.release_dir.resolve()
    parent = release_dir.parent
    if args.keep:
        base_context = nullcontext(tempfile.mkdtemp(prefix="acceptare-date-reale-", dir=parent))
    else:
        base_context = tempfile.TemporaryDirectory(prefix="acceptare-date-reale-", dir=parent)
    with base_context as temp:
        base = Path(temp)
        home = (args.data_home or base / "home").resolve()
        transport = Transport()
        with open_runtime(home, CHANNEL, transport=transport) as runtime, running(runtime) as httpd:
            activate(runtime, httpd, baseline_release(base / "baseline", transport))
            release, fingerprint = release_from_folder(release_dir, transport)
            started = time.monotonic()
            activate(runtime, httpd, fingerprint)
            summary = request(httpd, "/api/rezumat")
            if summary["acte"] < args.min_acts:
                raise AssertionError(summary)
            results = {"results": []}
            if not args.skip_search:
                results = request(httpd, "/api/cauta?q=achizitii&limita=3")
                if not results["results"]:
                    raise AssertionError(results)
            dossier_id = "b" * 32
            request(httpd, "/api/dosare", {"id": dossier_id, "titlu": "Acceptare date reale"})
            request(
                httpd,
                "/api/dosare/metadate",
                {
                    "id": dossier_id,
                    "titlu": "Acceptare date reale actualizata",
                    "arhivat": False,
                    "revizie": 0,
                },
            )
            workbench = pilot_workbench(
                httpd, dossier_id, search_results=results, act_id=args.pilot_act
            )
            before = request(httpd, "/api/dosare?id=" + dossier_id)
            request(httpd, body={"action": "rollback"})
            after = request(httpd, "/api/dosare?id=" + dossier_id)
            if before["titlu"] != after["titlu"]:
                raise AssertionError((before, after))
            print(
                json.dumps(
                    {
                        "release": release,
                        "acte": summary["acte"],
                        "search_results": len(results["results"]),
                        "workbench": workbench,
                        "dossier_survived_rollback": True,
                        "seconds": round(time.monotonic() - started, 2),
                        "data_home": str(home),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        if args.keep and args.data_home is None:
            print(f"kept data under {base}", flush=True)


if __name__ == "__main__":
    main()
