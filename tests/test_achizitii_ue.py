import io
import json
import sqlite3
import urllib.request
from types import SimpleNamespace

import pytest

from scripts import achizitii_ue as au
from scripts import cellar
from scripts import transport_cellar as tc
from scripts.server import face_handler

CELEX = "32014L0024"
ITEM = "https://publications.europa.eu/resource/cellar/test/DOC_1"
TEXT = b"<html><body><p>Articolul 1</p><p>Text oficial de test pentru achizitii.</p></body></html>"


def binding(lang="RON", fmt="xhtml", item=ITEM):
    values = {
        "work": "http://publications.europa.eu/resource/cellar/test",
        "expr": "http://publications.europa.eu/resource/cellar/test." + lang,
        "manif": "http://publications.europa.eu/resource/cellar/test." + lang + "." + fmt,
        "langCode": lang,
        "format": fmt,
        "item": item,
        "title": "Test " + lang,
    }
    return {k: {"value": v} for k, v in values.items()}


class Response(io.BytesIO):
    headers = {"Content-Type": "application/xhtml+xml"}

    def __init__(self, data, url=ITEM):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    state = SimpleNamespace(eu=tmp_path / "eu?#.db")
    source = {"manifestations": [binding()], "text": TEXT, "calls": []}

    def open_request(req, **kwargs):
        source["calls"].append(req.full_url)
        if source.get("offline"):
            raise OSError("private credentials and /local/path")
        data = (
            json.dumps({"results": {"bindings": source["manifestations"]}}).encode()
            if req.data
            else source["text"]
        )
        return Response(data, req.full_url)

    monkeypatch.setattr(
        tc.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=open_request)
    )
    return state, source


def test_local_reads_do_not_create_fetch_or_migrate(fixture):
    state, source = fixture
    assert au.detaliu(state, CELEX)["stare"] == "neimportat"
    assert not state.eu.exists() and not source["calls"]
    with cellar.deschide(state.eu):
        pass
    before = state.eu.read_bytes()
    au.detaliu(state, CELEX)
    assert state.eu.read_bytes() == before and not source["calls"]
    with cellar.deschide(state.eu, readonly=True) as con:
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='eu_achizitii'").fetchone()


def test_romanian_preferred_unchanged_import_keeps_snapshot(fixture):
    state, source = fixture
    source["manifestations"] = [binding("ENG", item=ITEM + "ENG"), binding()]
    first = au.importa(state, {"celex": CELEX})
    assert first["limba"] == "RON" and first["schimbat"]
    assert first["limba_import"] == {
        "preferinta": ["RON", "ENG"],
        "aleasa": "RON",
        "eticheta": "romana oficiala",
        "fallback": False,
    }
    assert first["contract"] == "celex-on-demand-source-v1"
    assert first["source_identifier"] == CELEX
    assert first["language_preference"] == ["RON", "ENG"]
    assert first["selected_language"] == "RON"
    assert first["selected_language_label"] == "romana oficiala"
    assert first["language_fallback"] is False
    assert first["instantanee"] and len(first["text_sha256"]) == 64
    assert first["source_hash"] == first["text_sha256"]
    assert first["snapshot"] == {
        "id": first["instantanee"],
        "text_sha256": first["text_sha256"],
        "source_hash": first["text_sha256"],
    }
    assert first["articole"]["total"] == 1
    assert first["articole"]["randuri"][0]["locator"] == "art1"
    assert len(first["articole"]["randuri"][0]["sha256"]) == 64
    detail = au.detaliu(state, CELEX)
    snapshot_id = detail["curenta"]["id"]
    assert detail["incercare"]["stare"] == "ok"
    assert "text" not in detail["curenta"]["sursa"]
    assert detail["curenta"]["limba_import"]["aleasa"] == "RON"
    assert detail["curenta"]["articole"]["total"] == 1
    assert "achizitii" in au.detaliu(state, CELEX, snapshot_id=snapshot_id)["sursa"]["text"]
    second = au.importa(state, {"celex": CELEX})
    assert not second["schimbat"]
    assert au.detaliu(state, CELEX)["curenta"]["id"] == snapshot_id
    assert len(au.detaliu(state, CELEX)["instantanee"]) == 1
    assert not any(u.endswith("ENG") for u in source["calls"])


def test_english_fallback_and_later_romanian_preserve_history(fixture):
    state, source = fixture
    source["manifestations"] = [binding("ENG")]
    first = au.importa(state, {"celex": CELEX})
    assert first["limba"] == "ENG"
    assert first["limba_import"]["fallback"] is True
    assert first["selected_language"] == "ENG"
    assert first["language_fallback"] is True
    assert "fallback explicit" in first["selected_language_label"]
    old = au.detaliu(state, CELEX)["curenta"]["id"]
    source["manifestations"] = [binding()]
    au.importa(state, {"celex": CELEX})
    detail = au.detaliu(state, CELEX)
    assert detail["curenta"]["sursa"]["limba"] == "RON"
    assert len(detail["instantanee"]) == 2
    assert au.detaliu(state, CELEX, snapshot_id=old)["sursa"]["limba"] == "ENG"
    with pytest.raises(ValueError):
        au.detaliu(state, "32018R1805", snapshot_id=old)


def test_identifier_import_contract_normalizes_celex_url(fixture):
    state, _ = fixture

    result = au.importa(
        state,
        {
            "identifier": "https://eur-lex.europa.eu/legal-content/RO/TXT/?uri=CELEX:32014L0024",
            "limbi": ["RON", "ENG"],
        },
    )

    assert result["contract"] == "celex-on-demand-source-v1"
    assert result["source_identifier"].startswith("https://eur-lex.europa.eu/")
    assert result["celex"] == CELEX
    assert result["language_preference"] == ["RON", "ENG"]
    assert result["snapshot"]["id"]
    assert len(result["snapshot"]["source_hash"]) == 64


def test_metadata_only_import_has_contract_without_snapshot(fixture):
    state, source = fixture
    source["manifestations"] = [binding(fmt="pdf")]

    result = au.importa(state, {"identifier": CELEX})

    assert result["contract"] == "celex-on-demand-source-v1"
    assert result["stare"] == "metadate"
    assert result["source_hash"] == ""
    assert result["snapshot"] is None


def test_pdf_only_retains_metadata_and_last_good_text(fixture):
    state, source = fixture
    source["manifestations"] = [binding(fmt="pdf")]
    result = au.importa(state, {"celex": CELEX})
    assert result["stare"] == "metadate"
    assert result["limba_import"]["aleasa"] is None
    detail = au.detaliu(state, CELEX)
    assert detail["stare"] == "metadate" and detail["incercare"]["reusit_la"] is None
    assert len(source["calls"]) == 1
    source["manifestations"] = [binding()]
    au.importa(state, {"celex": CELEX})
    previous = au.detaliu(state, CELEX)
    source["manifestations"] = [binding(fmt="pdf")]
    au.importa(state, {"celex": CELEX})
    now = au.detaliu(state, CELEX)
    assert now["curenta"] == previous["curenta"]
    assert now["incercare"]["reusit_la"] == previous["incercare"]["reusit_la"]
    assert now["incercare"]["stare"] == "metadate"


def test_failed_update_keeps_previous_success_and_retry(fixture):
    state, source = fixture
    au.importa(state, {"celex": CELEX})
    before = au.detaliu(state, CELEX)
    source["offline"] = True
    with pytest.raises(ValueError) as err:
        au.importa(state, {"celex": CELEX})
    assert "private" not in str(err.value)
    failed = au.detaliu(state, CELEX)
    assert failed["curenta"] == before["curenta"]
    assert failed["incercare"]["reusit_la"] == before["incercare"]["reusit_la"]
    assert failed["incercare"]["stare"] == "eroare"
    source["offline"] = False
    source["text"] = TEXT.replace(b"achizitii", b"contracte")
    au.importa(state, {"celex": CELEX})
    assert len(au.detaliu(state, CELEX)["instantanee"]) == 2


def test_unreadable_multipart_and_bad_romanian_do_not_fallback_or_replace(fixture, monkeypatch):
    state, source = fixture
    au.importa(state, {"celex": CELEX})
    before = au.detaliu(state, CELEX)["curenta"]
    source["manifestations"] = [binding(), binding(item=ITEM[:-1] + "2"), binding("ENG")]
    original = cellar.descarca_text

    def read(part, **kwargs):
        if part.item_url.endswith("DOC_2"):
            raise cellar.TextIndisponibil("Bad part")
        assert part.limba == "RON"
        return original(part, **kwargs)

    monkeypatch.setattr(cellar, "descarca_text", read)
    with pytest.raises(ValueError):
        au.importa(state, {"celex": CELEX})
    assert au.detaliu(state, CELEX)["curenta"] == before


def test_archive_and_search_updates_roll_back_together(fixture, monkeypatch):
    state, source = fixture
    au.importa(state, {"celex": CELEX})
    before = au.detaliu(state, CELEX)["curenta"]
    source["text"] = TEXT.replace(b"achizitii", b"contracte")
    monkeypatch.setattr(
        cellar,
        "scrie_provizii_celex",
        lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError()),
    )
    with pytest.raises(ValueError):
        au.importa(state, {"celex": CELEX})
    assert au.detaliu(state, CELEX)["curenta"] == before
    assert len(au.detaliu(state, CELEX)["instantanee"]) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/x",
        "http://127.0.0.1/x",
        "file:///tmp/x",
        "https://user@publications.europa.eu/x",
        "https://publications.europa.eu:8443/x",
        "https://publications.europa.eu.evil.test/x",
        "https://publications.europa.eu/\nx",
        None,
    ],
)
def test_transport_rejects_untrusted_urls(url):
    with pytest.raises(ValueError):
        tc.url_oficial(url)


def test_redirects_are_validated_before_following():
    transport = tc.TransportCellar()
    redirect = next(
        h for h in transport.opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)
    )
    with pytest.raises(ValueError):
        redirect.redirect_request(
            urllib.request.Request(ITEM), None, 302, "", {}, "http://127.0.0.1/x"
        )


def test_manifestation_url_rejected_without_fetch(fixture):
    state, source = fixture
    source["manifestations"] = [binding(item="http://127.0.0.1/private")]
    with pytest.raises(ValueError):
        au.importa(state, {"celex": CELEX})
    assert len(source["calls"]) == 1
    assert au.detaliu(state, CELEX)["incercare"]["stare"] == "eroare"


def test_transport_bounds_response_total_requests_and_deadline(fixture, monkeypatch):
    _, source = fixture
    source["text"] = b"x" * 11
    monkeypatch.setattr(tc, "MAX_RESPONSE", 10)
    with pytest.raises(ValueError), tc.TransportCellar()(urllib.request.Request(ITEM)) as response:
        response.read()
    source["text"] = b"123456"
    transport = tc.TransportCellar()
    transport.remaining = 10
    with transport(urllib.request.Request(ITEM)) as response:
        assert response.read() == b"123456"
    with pytest.raises(ValueError), transport(urllib.request.Request(ITEM)) as response:
        response.read()
    transport = tc.TransportCellar()
    transport.requests = tc.MAX_REQUESTS
    with pytest.raises(ValueError):
        transport.check_request()
    transport.deadline = 0
    with pytest.raises(ValueError):
        transport.check_time()


def test_readonly_history_integrity_and_pagination(fixture, monkeypatch):
    state, source = fixture
    for i in range(3):
        source["text"] = TEXT.replace(b"achizitii", f"achizitii {i}".encode())
        au.importa(state, {"celex": CELEX})
    monkeypatch.setattr(au, "PAGE_SIZE", 2)
    first = au.detaliu(state, CELEX)
    assert len(first["instantanee"]) == 2 and first["mai_multe"]
    second = au.detaliu(state, CELEX, offset=2)
    assert len(second["instantanee"]) == 1 and not second["mai_multe"]
    old = next(
        s for s in first["instantanee"] + second["instantanee"] if s["id"] != first["curenta"]["id"]
    )
    assert au.detaliu(state, CELEX, snapshot_id=old["id"])["sursa"]["text"]
    with cellar.deschide(state.eu) as con:
        con.execute("DROP TRIGGER eu_instantanee_no_update")
        con.execute("UPDATE eu_instantanee SET snapshot_json='{}' WHERE id=?", (old["id"],))
    with pytest.raises((ValueError, KeyError)):
        au.detaliu(state, CELEX, snapshot_id=old["id"])


def request(
    state,
    method,
    query="",
    body=None,
    host="localhost:8123",
    origin=None,
    length=None,
    path="/api/ue/surse",
):
    handler = object.__new__(face_handler(state))
    handler.path = path + query
    raw = json.dumps(body).encode() if body is not None else b""
    handler.rfile = io.BytesIO(raw)
    handler.headers = {
        "Host": host,
        "Content-Length": str(length if length is not None else len(raw)),
    }
    if origin:
        handler.headers["Origin"] = origin
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    getattr(handler, "do_" + method)()
    return result[0]


def test_http_boundaries_and_no_cache(fixture):
    state, source = fixture
    for method in ("GET", "POST"):
        assert request(state, method, origin="https://evil.test")[0] == 403
        assert request(state, method, host="evil.test:8123")[0] == 403
    assert request(state, "POST", length=16001)[0] == 413
    for body in (
        [],
        {"celex": []},
        {"celex": CELEX, "url": ITEM},
        {"celex": "X> }"},
        {"identifier": CELEX, "limbi": [1]},
    ):
        assert request(state, "POST", body=body)[0] == 400
    assert not source["calls"] and not state.eu.exists()
    assert request(state, "POST", body={"celex": CELEX})[0] == 200
    alias = request(state, "POST", body={"identifier": CELEX}, path="/api/ue/import")
    assert alias[0] == 200
    assert alias[1]["contract"] == "celex-on-demand-source-v1"
    assert request(state, "GET", "?celex=" + CELEX)[1]["stare"] == "text_disponibil"
    assert request(state, "GET", "?celex=" + CELEX + "&offset=-1")[0] == 400
    handler = object.__new__(face_handler(state))
    handler.path = "/api/ue/surse"
    headers = {}
    handler.send_header = lambda k, v: headers.update({k: v})
    handler.send_response = lambda *args: None
    handler.end_headers = lambda: None
    handler.wfile = io.BytesIO()
    handler._json({})
    assert headers["Cache-Control"] == "no-store"


def test_parallel_import_is_rejected_without_network(fixture):
    state, source = fixture
    with au.IMPORT_LOCK, pytest.raises(ValueError, match="deja in curs"):
        au.importa(state, {"celex": CELEX})
    assert not source["calls"]


def test_part_limit_malformed_response_and_unknown_charset(fixture, monkeypatch):
    state, source = fixture
    source["manifestations"] = [binding(item=ITEM + str(i)) for i in range(11)]
    with pytest.raises(ValueError):
        au.importa(state, {"celex": CELEX})
    assert len(source["calls"]) == 1
    source["manifestations"] = [None]
    with pytest.raises(ValueError):
        au.importa(state, {"celex": CELEX})
    source["manifestations"] = [binding()]
    monkeypatch.setattr(Response, "headers", {"Content-Type": "text/html; charset=not-an-encoding"})
    with pytest.raises(ValueError):
        au.importa(state, {"celex": CELEX})
    assert au.detaliu(state, CELEX)["incercare"]["stare"] == "eroare"


def test_nonidentity_encoding_rejected(fixture, monkeypatch):
    state, _ = fixture
    monkeypatch.setattr(Response, "headers", {"Content-Encoding": "gzip"})
    with pytest.raises(ValueError):
        au.importa(state, {"celex": CELEX})
    assert au.detaliu(state, CELEX)["stare"] == "neimportat"


def test_import_updates_live_retrieval(fixture):
    state, source = fixture
    au.importa(state, {"celex": CELEX})
    with cellar.deschide(state.eu, readonly=True) as con:
        assert cellar.cauta_ue(con, "achizitii")[0]["celex"] == CELEX
    source["text"] = TEXT.replace(b"achizitii", b"contracte")
    au.importa(state, {"celex": CELEX})
    with cellar.deschide(state.eu, readonly=True) as con:
        assert not cellar.cauta_ue(con, "achizitii")
        assert cellar.cauta_ue(con, "contracte")[0]["celex"] == CELEX
