import sqlite3

import pytest

from scripts import dosare, propuneri
from tests import test_propuneri
from tests.test_dosare import request as http

ID = test_propuneri.ID
case = test_propuneri.case


def test_dossier_list_only_latest_with_pagination_and_ownership(case):
    state, path, run, req = case
    assert propuneri.lista(path, ID)["total"] == 0
    first = propuneri.salveaza(path, req)
    for revision in range(1, 23):
        propuneri.salveaza(
            path,
            {**req, "id": f"{revision:032x}", "revizie": revision, "titlu": f"Title {revision}"},
        )
    page = propuneri.lista(path, ID)
    assert page["total"] == 1 and page["propuneri"][0]["revizie"] == 23
    assert page["propuneri"][0]["constatare_id"] == req["constatare_id"]
    assert "text" not in page["propuneri"][0]
    assert propuneri.lista(path, ID, 1)["propuneri"] == []
    new = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": "Other"}})
    propuneri.salveaza(path, {**req, "id": "c" * 32, "rulare_id": new["id"]})
    assert propuneri.lista(path, ID)["total"] == 2
    dosare.creeaza(path, {"id": "f" * 32, "titlu": "Other dossier"})
    assert propuneri.lista(path, "f" * 32)["total"] == 0
    history = propuneri.istoric(path, ID, run["id"], req["constatare_id"])
    assert history["total"] == 23
    assert [p["revizie"] for p in history["revizii"]] == list(range(23, 3, -1))
    assert "text" not in history["revizii"][0]
    tail = propuneri.istoric(path, ID, run["id"], req["constatare_id"], 20)
    assert [p["revizie"] for p in tail["revizii"]] == [3, 2, 1]
    assert propuneri.citeste(path, ID, run["id"], req["constatare_id"], 1)["propunere"] == first


def test_list_more_than_one_page(case):
    state, path, _, req = case
    for n in range(52):
        run = dosare.salveaza_rulare(state, {"dosar_id": ID, "filtre": {"emitent": str(n)}})
        propuneri.salveaza(path, {**req, "id": f"{n:032x}", "rulare_id": run["id"]})
    first, last = propuneri.lista(path, ID), propuneri.lista(path, ID, 50)
    assert first["total"] == last["total"] == 52
    assert len(first["propuneri"]) == 50 and len(last["propuneri"]) == 2
    assert len({p["id"] for p in first["propuneri"] + last["propuneri"]}) == 52


def test_export_selected_revision_complete_original_basis_and_safe_markdown(case):
    _, path, run, req = case
    malicious = "```\n<script>alert(1)</script>\n# Not a real heading\n````"
    first = propuneri.salveaza(path, {**req, "text": malicious, "motiv": "Original rationale"})
    propuneri.salveaza(path, {**req, "id": "c" * 32, "revizie": 1, "text": "Later draft"})
    before = path.read_bytes()
    data = propuneri.exporta(path, ID, run["id"], req["constatare_id"], 1)
    assert data["propunere"] == first
    assert data["rulare"] == run and data["baza"]["raport_sha256"] == run["sha256"]
    assert "Later draft" not in data["markdown"]
    assert "`````\n" + malicious + "\n`````" in data["markdown"]
    assert "Retained A" in data["markdown"] and "Retained B" in data["markdown"]
    assert "nu text legal in vigoare" in data["markdown"]
    assert "nu modificarile nesalvate" in data["markdown"]
    assert data["schema_version"] == 1 and data["limitari"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("revision", [0, -1, True, "1", 1000002, 99])
def test_invalid_or_missing_revision(case, revision):
    _, path, run, req = case
    propuneri.salveaza(path, req)
    with pytest.raises(ValueError):
        propuneri.citeste(path, ID, run["id"], req["constatare_id"], revision)
    with pytest.raises(ValueError):
        propuneri.exporta(path, ID, run["id"], req["constatare_id"], revision)


def test_read_modes_on_old_schema_do_not_migrate(case):
    _, path, run, req = case
    with sqlite3.connect(path) as con:
        con.execute("DROP TABLE interventii_propuneri")
        con.execute("DROP TABLE propuneri")
        con.execute("PRAGMA user_version=4")
    before = path.read_bytes()
    assert propuneri.lista(path, ID)["total"] == 0
    assert propuneri.istoric(path, ID, run["id"], req["constatare_id"])["revizii"] == []
    with pytest.raises(ValueError, match="nu exista"):
        propuneri.exporta(path, ID, run["id"], req["constatare_id"], 1)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "suffix", ["&mod=lista", "&mod=istoric", "&revizie=1", "&mod=export&revizie=1"]
)
def test_http_read_modes_and_local_security(case, suffix):
    state, path, run, req = case
    propuneri.salveaza(path, req)
    url = (
        f"/api/dosare/propuneri?id={ID}&rulare_id={run['id']}&constatare_id={req['constatare_id']}"
    )
    assert http(state, "GET", url + suffix)[0] == 200
    assert http(state, "GET", url + suffix, origin="https://evil.test")[0] == 403
    assert http(state, "GET", url + suffix, host="evil:8123")[0] == 403
    dosare.creeaza(path, {"id": "f" * 32, "titlu": "Other"})
    if suffix != "&mod=lista":
        assert http(state, "GET", url.replace(ID, "f" * 32) + suffix)[0] == 400
    state.date_dir = "static"
    assert http(state, "GET", url + suffix)[0] == 400


@pytest.mark.parametrize(
    "suffix",
    [
        "&mod=unknown",
        "&mod=lista&offset=-1",
        "&mod=istoric&offset=x",
        "&mod=export",
        "&revizie=0",
        "&revizie=1.5",
    ],
)
def test_invalid_http_read_modes(case, suffix):
    state, _, run, req = case
    url = (
        f"/api/dosare/propuneri?id={ID}&rulare_id={run['id']}&constatare_id={req['constatare_id']}"
    )
    assert http(state, "GET", url + suffix)[0] == 400
