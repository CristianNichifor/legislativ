from types import SimpleNamespace

import pytest

from scripts import achizitii_econsultare as ec
from scripts import source_registry as registry

HTML = """
<html>
  <body>
    <h1>Proiect de hotărâre privind serviciile publice</h1>
    <dl>
      <dt>Autoritate inițiatoare</dt><dd>Ministerul Dezvoltării</dd>
      <dt>Termen limită</dt><dd>15.10.2026</dd>
    </dl>
    <p>Documentul este în consultare publică.</p>
    <a href="/upload/proiect.pdf">Proiect act normativ</a>
    <a href="https://e-consultare.gov.ro/upload/fundamentare.docx">Notă de fundamentare</a>
  </body>
</html>
""".encode()


def state(tmp_path):
    return SimpleNamespace(initiative=tmp_path / "initiative.db")


def test_econsultare_parser_extracts_bounded_snapshot():
    out = ec.parseaza(HTML, "https://e-consultare.gov.ro/consultare/123")

    assert out["contract"] == "econsultare-source-snapshot-v1"
    assert out["family"] == "consultare_econsultare"
    assert out["summary"] == {
        "title": "Proiect de hotărâre privind serviciile publice",
        "authority": "Ministerul Dezvoltării",
        "status": "open",
        "deadline": "15.10.2026",
        "documents": 2,
        "truncated": False,
    }
    assert out["documents"] == [
        {
            "url": "https://e-consultare.gov.ro/upload/fundamentare.docx",
            "label": "Notă de fundamentare",
        },
        {
            "url": "https://e-consultare.gov.ro/upload/proiect.pdf",
            "label": "Proiect act normativ",
        },
    ]
    assert len(ec.snapshot_hash(out)) == 64


def test_econsultare_rejects_non_official_urls():
    with pytest.raises(ValueError, match="e-consultare.gov.ro"):
        ec.url_oficial("https://example.com/consultare/123")


def test_registry_syncs_one_econsultare_source(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "consultare_econsultare",
            "url": "https://e-consultare.gov.ro/consultare/123",
            "label": "Consultare servicii publice",
        },
    )

    monkeypatch.setattr(ec, "descarca", lambda url: (HTML, 200))
    changed = registry.executa(stare, {"action": "sync", "id": row["id"]})

    assert changed["state"] == "changed"
    assert changed["last_hash"]
    assert changed["parser_version"] == ec.PARSER_VERSION
    selected = registry.lista(stare, {"id": [row["id"]]})["sources"][0]
    assert selected["sync_status"]["can_sync"] is True
    assert selected["snapshots"][0]["parser_version"] == ec.PARSER_VERSION
    assert selected["snapshots"][0]["summary"]["documents"] == 2

    unchanged = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert unchanged["state"] == "unchanged"


def test_registry_econsultare_changed_and_needs_review(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {
            "family": "consultare_econsultare",
            "identifier": "https://e-consultare.gov.ro/consultare/123",
        },
    )
    monkeypatch.setattr(ec, "descarca", lambda url: (HTML, 200))
    first = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert first["state"] == "changed"

    changed_html = HTML.replace(b"15.10.2026", b"20.10.2026")
    monkeypatch.setattr(ec, "descarca", lambda url: (changed_html, 200))
    changed = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert changed["state"] == "changed"
    assert changed["last_hash"] != first["last_hash"]

    bare = b"<html><body><p>Consultare publica fara documente.</p></body></html>"
    monkeypatch.setattr(ec, "descarca", lambda url: (bare, 200))
    review = registry.executa(stare, {"action": "sync", "id": row["id"]})
    assert review["state"] == "needs_review"
    assert review["last_error"] == ""


def test_registry_econsultare_records_bounded_failure(monkeypatch, tmp_path):
    stare = state(tmp_path)
    row = registry.executa(
        stare,
        {"family": "consultare_econsultare", "url": "https://e-consultare.gov.ro/consultare/404"},
    )

    def fail(url):
        raise ValueError("Pagina e-consultare nu este disponibilă.")

    monkeypatch.setattr(ec, "descarca", fail)
    failed = registry.executa(stare, {"action": "sync", "id": row["id"]})

    assert failed["state"] == "failed"
    assert failed["last_error"] == "fetch_failed"
