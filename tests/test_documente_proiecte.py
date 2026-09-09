import hashlib
import shutil
from types import SimpleNamespace

import pytest

from scripts import depozit
from scripts import documente_proiecte as dp
from scripts.fisiere import catre_docx

URL = "https://www.cdep.ro/proiecte/2026/pl1.docx"
PAGE = "https://www.cdep.ro/ords/pls/proiecte/upl_pck2015.proiect?cam=2&idp=123"


@pytest.fixture
def stare(tmp_path):
    s = SimpleNamespace(initiative=str(tmp_path / "initiative.db"))
    with depozit.deschide(s.initiative) as con:
        con.execute(
            "INSERT INTO initiative (plx_id, cam, idp, titlu, citit_la) "
            "VALUES ('plx-1', 2, '123', 'Proiect', 'today')"
        )
        con.commit()
    return s


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/a.pdf",
        "file:///etc/passwd",
        "http://127.0.0.1/a.pdf",
        "https://www.cdep.ro.evil.test/a.pdf",
        "https://user@www.cdep.ro/a.pdf",
        "https://www.cdep.ro:444/a.pdf",
        "https://www.cdep.ro\\@evil.test/a.pdf",
        "https://www.cdep.ro/a\n.pdf",
        None,
    ],
)
def test_reject_untrusted_urls_and_redirects(url):
    with pytest.raises(ValueError):
        dp.url_oficial(url)
    with pytest.raises(ValueError):
        dp._Redirect().redirect_request(None, None, 302, "", {}, url)


def test_discovery_resolves_relative_urls_and_preserves_version_labels():
    html = '<a href="/proiecte/2026/pl1.docx">Forma inițială</a>'
    html += '<a href="http://www.senat.ro/a.pdf"><img alt="Forma adoptată"></a>'
    html += '<a href="https://evil.test/a.pdf">Bad</a><a href="/x.doc">Legacy</a>'
    html += '<a href="/proiecte/2026/pl1.docx">Duplicate</a>'
    docs = dp.descopera(html, PAGE)
    assert docs == [
        {"url": URL, "label": "Forma inițială"},
        {"url": "https://www.senat.ro/a.pdf", "label": "Forma adoptată"},
    ]


def test_import_hash_versions_ownership_and_offline_history(stare, monkeypatch):
    data = catre_docx("", "Articolul 7 se abrogă.")

    def download(url, limita=dp.MAX_BYTES):
        return f'<a href="{URL}">Proiect</a>'.encode() if "idp=" in url else data

    monkeypatch.setattr(dp, "descarca", download)
    first = dp.importa(stare, "plx-1", URL)
    assert first["sha256"] == hashlib.sha256(data).hexdigest()
    assert "Articolul 7 se abrogă." in first["text"]
    assert first["status"] == "extras"
    assert dp.importa(stare, "plx-1", URL) == first
    data = catre_docx("", "Articolul 8 se abrogă.")
    second = dp.importa(stare, "plx-1", URL)
    assert first["id"] != second["id"]
    assert len(dp.versiuni(stare, "plx-1")) == 2
    assert dp.citeste(stare, "plx-1", first["id"]) == first
    with pytest.raises(ValueError):
        dp.citeste(stare, "plx-2", first["id"])
    with pytest.raises(ValueError):
        dp.importa(stare, "plx-1", "https://www.cdep.ro/unlisted.pdf")

    def offline(*args):
        raise OSError("offline")

    monkeypatch.setattr(dp, "descarca", offline)
    assert len(dp.lista(stare, "plx-1")["versiuni"]) == 2
    assert dp.lista(stare, "plx-1")["avertisment"]


def test_download_is_bounded(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def geturl(self):
            return URL

        def read(self, size):
            assert size == 11
            return b"x" * size

    monkeypatch.setattr(
        dp.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *a, **k: Response()),
    )
    with pytest.raises(ValueError, match="limita"):
        dp.descarca(URL, 10)


def test_discovery_keeps_adjacent_official_document_description():
    html = '<table><tr><td><a href="/a.pdf"><img alt="PDF"></a></td>'
    html += "<td>Forma adoptată de Senat</td></tr></table>"
    assert "Forma adoptată de Senat" in dp.descopera(html, PAGE)[0]["label"]


def _pdf(text):
    # Small valid PDF fixture with a single text stream; extraction is still done by Poppler.
    stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] "
        + b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    data, offsets = b"%PDF-1.4\n", [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{n:010} 00000 n \n".encode() for n in offsets[1:])
    return data + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF".encode()


@pytest.mark.skipif(not shutil.which("pdftotext"), reason="Poppler unavailable")
def test_pdf_text_and_ocr_needed_page():
    out = dp.extrage(_pdf("Articolul 7 din Legea 98/2016 se abroga."))
    assert out["status"] == "extras" and "Articolul 7" in out["text"]
    assert dp.extrage(_pdf(""))["status"] == "ocr_necesar"


def test_reject_unknown_and_oversized_input():
    for data in [b"<html>Error</html>", b"%PDF-" + b"x" * dp.MAX_BYTES]:
        with pytest.raises(ValueError):
            dp.extrage(data)
