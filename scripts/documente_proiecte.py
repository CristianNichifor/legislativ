"""User-triggered official document discovery and immutable local import snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from scripts.cdep import BASE, USER_AGENT

MAX_BYTES = 10 * 1024 * 1024
HOSTS = {"www.cdep.ro", "cdep.ro", "www.senat.ro", "senat.ro"}


def url_oficial(url: str) -> str:
    if not isinstance(url, str) or any(ord(c) < 33 for c in url) or "\\" in url:
        raise ValueError("Adresă oficială invalidă.")
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or p.hostname not in HOSTS or p.username or p.password:
        raise ValueError("Sunt permise doar surse parlamentare oficiale.")
    if p.port not in (None, 80 if p.scheme == "http" else 443):
        raise ValueError("Port nepermis.")
    return urlunsplit(("https", p.hostname, p.path, p.query, ""))


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, url_oficial(newurl))


def descarca(url: str, limita: int = MAX_BYTES) -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirect())
    req = urllib.request.Request(url_oficial(url), headers={"User-Agent": USER_AGENT})
    with opener.open(req, timeout=20) as response:
        url_oficial(response.geturl())
        data = response.read(limita + 1)
    if len(data) > limita:
        raise ValueError("Documentul depășește limita de descărcare.")
    return data


class _Linkuri(HTMLParser):
    def __init__(self, baza):
        super().__init__(convert_charrefs=True)
        self.baza, self.curent, self.linkuri = baza, None, {}
        self.randuri = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.randuri.append({"text": "", "docs": []})
        if tag == "a":
            self.curent = None
            try:
                url = url_oficial(urljoin(self.baza, attrs.get("href", "")))
            except ValueError:
                return
            if urlsplit(url).path.lower().endswith((".pdf", ".docx")):
                self.curent = {"url": url, "label": attrs.get("title", "")}
        if tag == "img" and self.curent:
            self.curent["label"] += " " + attrs.get("alt", "")

    def handle_data(self, data):
        if self.randuri:
            row = self.randuri[-1]
            row["text"] = (row["text"] + " " + data)[:1000]
        if self.curent:
            self.curent["label"] += data

    def handle_endtag(self, tag):
        if tag == "tr" and self.randuri:
            row = self.randuri.pop()
            context = " ".join(row["text"].split())[:240]
            for doc in row["docs"]:
                if context and context != doc["label"]:
                    doc["label"] = context + " · " + doc["label"]
        if tag == "a" and self.curent:
            d = self.curent
            d["label"] = " ".join(d["label"].split())[:300] or Path(urlsplit(d["url"]).path).name
            self.linkuri.setdefault(d["url"], d)
            if self.randuri:
                self.randuri[-1]["docs"].append(d)
            self.curent = None


def descopera(html: str, baza: str) -> list[dict]:
    parser = _Linkuri(url_oficial(baza))
    parser.feed(html)
    return list(parser.linkuri.values())


def cale_store(stare) -> Path:
    if hasattr(stare, "documente_db"):
        return Path(stare.documente_db)
    return Path(stare.initiative).with_suffix(".documente.db")


def versiuni(stare, plx: str) -> list[dict]:
    path = cale_store(stare)
    if not path.exists():
        return []
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documente'"
        ).fetchone():
            return []
        return [
            dict(r)
            for r in con.execute(
                "SELECT id, plx_id, url, label, sha256, preluat_la, status FROM documente "
                "WHERE plx_id=? ORDER BY preluat_la DESC, id LIMIT 100",
                (plx,),
            )
        ]


def lista(stare, plx: str) -> dict:
    with closing(
        sqlite3.connect(Path(stare.initiative).resolve().as_uri() + "?mode=ro", uri=True)
    ) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT idp, cam FROM initiative WHERE plx_id=?", (plx,)).fetchone()
    if not row or not re.fullmatch(r"\d{1,10}", row["idp"]) or row["cam"] not in (1, 2):
        raise ValueError("Inițiativa nu are o fișă parlamentară adresabilă.")
    url = f"{BASE}.proiect?cam={row['cam']}&idp={row['idp']}"
    history = versiuni(stare, plx)
    try:
        html = descarca(url, 2 * 1024 * 1024).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        if not history:
            raise
        return {
            "documente": [],
            "versiuni": history,
            "fisa_url": url,
            "avertisment": "Sursa nu este disponibilă; sunt afișate importurile locale.",
        }
    docs = descopera(html, url)
    return {
        "documente": docs[:100],
        "trunchiat": len(docs) > 100,
        "fisa_url": url,
        "versiuni": history,
    }


def extrage(data: bytes) -> dict:
    import subprocess
    import tempfile

    if len(data) > MAX_BYTES or not data.startswith((b"%PDF-", b"PK\x03\x04")):
        raise ValueError("Format necunoscut sau document prea mare; sunt acceptate PDF și DOCX.")
    with tempfile.TemporaryDirectory() as tmp:
        source, result = Path(tmp) / "document", Path(tmp) / "result.json"
        source.write_bytes(data)
        try:
            run = subprocess.run(
                [sys.executable, "-m", "scripts.documente_proiecte", str(source), str(result)],
                timeout=25,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Extragerea a depășit timpul permis.") from exc
        if run.returncode or not result.exists() or result.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Documentul nu a putut fi extras în limitele disponibile.")
        out = json.loads(result.read_text(encoding="utf-8"))
        if "error" in out:
            raise ValueError(out["error"])
        return out


def importa(stare, plx: str, url: str) -> dict:
    url = url_oficial(url)
    discovered = lista(stare, plx)
    if discovered.get("avertisment"):
        raise OSError("Sursa oficiala nu este disponibila.")
    doc = next((d for d in discovered["documente"] if d["url"] == url), None)
    if not doc:
        raise ValueError("Documentul nu apare între linkurile fișei inițiativei.")
    data = descarca(url)
    parsed = extrage(data)
    sha = hashlib.sha256(data).hexdigest()
    id = hashlib.sha256(json.dumps([plx, url, sha]).encode()).hexdigest()
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(cale_store(stare)) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS documente (id TEXT PRIMARY KEY, plx_id TEXT, "
            "url TEXT, label TEXT, sha256 TEXT, preluat_la TEXT, status TEXT, "
            "text TEXT, octeti BLOB)"
        )
        con.execute(
            "INSERT OR IGNORE INTO documente VALUES (?,?,?,?,?,?,?,?,?)",
            (id, plx, url, doc["label"], sha, now, parsed["status"], parsed["text"], data),
        )
    return citeste(stare, plx, id)


def citeste(stare, plx: str, id: str) -> dict:
    path = cale_store(stare)
    if not path.exists():
        raise ValueError("Versiunea importată nu există.")
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT id, plx_id, url, label, sha256, preluat_la, status, text "
            "FROM documente WHERE id=? AND plx_id=?",
            (id, plx),
        ).fetchone()
    if not row:
        raise ValueError("Versiunea nu aparține inițiativei selectate.")
    return dict(row)


def diferente(stare, plx: str, inainte: str, dupa: str) -> dict:
    from scripts.diferente_versiuni import compara

    return compara(citeste(stare, plx, inainte), citeste(stare, plx, dupa))


def verifica_actualizari(stare, plx: str, id: str) -> dict:
    original = citeste(stare, plx, id)
    current = importa(stare, plx, original["url"])
    return {
        "schimbat": original["sha256"] != current["sha256"],
        "verificat_la": datetime.now(UTC).isoformat(),
        "versiune": current,
    }


def _worker(source: Path, result: Path):
    # Limits are set in a fresh child, never via preexec_fn in the threaded HTTP server.
    import resource
    import shutil
    import subprocess

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024,) * 2)
    try:
        data = source.read_bytes()
        if data.startswith(b"%PDF-"):
            executable = shutil.which("pdftotext")
            if not executable:
                raise ValueError("Importul PDF necesită Poppler (pdftotext) în aplicația locală.")
            target = source.with_suffix(".txt")
            run = subprocess.run(
                [executable, "-enc", "UTF-8", str(source), str(target)],
                timeout=15,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if run.returncode:
                raise ValueError("PDF ilizibil, protejat sau prea complex.")
            text = target.read_text(encoding="utf-8")
            pages = text.split("\f")
            if pages and not pages[-1].strip():
                pages.pop()
            ocr = not pages or any(len(re.findall(r"\w", p)) < 20 for p in pages)
        else:
            from scripts.fisiere import din_docx

            text, ocr = din_docx(data), False
        out = {"text": text, "status": "ocr_necesar" if ocr else "extras"}
        if not text.strip() and not ocr:
            out["status"] = "fara_text"
        result.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        result.write_text(json.dumps({"error": str(exc)[:300]}), encoding="utf-8")


if __name__ == "__main__":
    _worker(Path(sys.argv[1]), Path(sys.argv[2]))
