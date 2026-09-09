import hashlib
import json
import sqlite3
from types import SimpleNamespace

from scripts import cellar, depozit
from scripts.inventar_surse import _sursa, main, raport
from scripts.servicii import _inventar_surse


def test_missing_is_not_measured_zero_and_creates_nothing(tmp_path):
    out = raport(tmp_path / "c.db", tmp_path / "i.db", tmp_path / "e.db")
    assert out["schema_version"] == 1
    assert out["acoperire_juridica"] == "necunoscuta"
    assert list(tmp_path.iterdir()) == []
    for source in out["surse"].values():
        assert source["stare"] == "lipsa"
        assert source["actualitate"] == "necunoscuta"
        assert all(
            m == {"stare": "indisponibil", "valoare": None} for m in source["metrici"].values()
        )


def test_empty_valid_database_is_measured_zero(tmp_path):
    path = tmp_path / "empty.db"
    with depozit.deschide(path):
        pass
    out = _sursa(path, "corpus")
    assert out["stare"] == "disponibil"
    assert out["metrici"]["acte"] == {"stare": "masurat", "valoare": 0}
    assert out["metrici"]["ultima_reusita_sursa"] == {"stare": "necunoscut", "valoare": None}


def test_inventory_is_readonly_and_uses_distinct_populations(tmp_path):
    path = tmp_path / "corpus?#.db"
    with depozit.deschide(path) as con:
        for i in (1, 2, 3):
            con.execute(
                "INSERT INTO acte(id,tip,titlu,citit_la) VALUES (?,'lege','A','today')", (str(i),)
            )
        con.execute("INSERT INTO provizii(act_id,locator,ord,text) VALUES ('1','art1',0,'Text')")
        con.execute("INSERT INTO provizii(act_id,locator,ord,text) VALUES ('2','text',0,'Flat')")
        con.execute("INSERT INTO provizii(act_id,locator,ord,text) VALUES ('3','art1',0,' ')")
        for i in (1, 2):
            con.execute(
                "INSERT INTO documente(id_portal,cheie_act,tip,titlu,text,adus_la) "
                "VALUES (?,?,'lege','A','Text','2026-09-01')",
                (str(i), str(i)),
            )
        con.execute(
            "INSERT INTO surse VALUES ('1','https://example.test',X'01',1,'ok',"
            "'2026-09-08T23:00:00+02:00')"
        )
        con.execute(
            "INSERT INTO surse VALUES ('2','https://example.test',NULL,NULL,'retea',"
            "'2026-09-08T22:00:00+00:00')"
        )
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    source = _sursa(path, "corpus")
    m = {k: v["valoare"] for k, v in source["metrici"].items()}
    assert m["acte"] == 3 and m["documente"] == 2
    assert m["acte_cu_prevederi"] == 2 and m["acte_cu_structura"] == 1
    assert m["surse_reusite"] == m["surse_esuate"] == 1
    assert m["documente_fara_sursa_reusita"] == 1
    assert m["ultima_incercare_sursa"] == "2026-09-08 22:00:00"
    assert m["ultima_reusita_sursa"] == "2026-09-08 21:00:00"
    assert source["ultima_sincronizare_completa"] is None
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_partial_schema_keeps_available_metrics_and_does_not_migrate(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE acte(id TEXT)")
        con.execute("INSERT INTO acte VALUES ('a')")
    out = _sursa(path, "corpus")
    assert out["stare"] == "partial"
    assert out["metrici"]["acte"]["valoare"] == 1
    assert out["metrici"]["prevederi"]["valoare"] is None
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT name FROM sqlite_master").fetchall() == [("acte",)]


def test_corrupt_and_directory_are_inaccessible(tmp_path):
    path = tmp_path / "bad.db"
    path.write_bytes(b"not sqlite")
    assert _sursa(path, "ue")["stare"] == "inaccesibil"
    assert _sursa(tmp_path, "ue")["stare"] == "inaccesibil"


def test_eu_and_import_statuses(tmp_path):
    eu = tmp_path / "eu.db"
    with cellar.deschide(str(eu)):
        pass
    assert _sursa(eu, "ue")["metrici"]["acte_romana"]["valoare"] == 0
    path = tmp_path / "i.documente.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE documente(status TEXT, preluat_la TEXT)")
        con.executemany(
            "INSERT INTO documente VALUES (?, 'invalid date')",
            [(s,) for s in ("extras", "ocr_necesar", "fara_text", "other", None)],
        )
    out = raport(tmp_path / "c.db", tmp_path / "i.db", eu)
    metrics = out["surse"]["importuri"]["metrici"]
    assert metrics["versiuni"]["valoare"] == 5
    assert metrics["status_necunoscut"]["valoare"] == 2
    assert metrics["ocr_necesar"]["valoare"] == 1
    assert metrics["ultima_inregistrare_stocata"]["stare"] == "necunoscut"


def test_service_static_does_not_scan_partial_or_remote_corpus(tmp_path):
    out = _inventar_surse(SimpleNamespace(date_dir=tmp_path))
    assert out["mod"] == "static" and out["surse"] == {}
    assert out["limitari"]
    state = SimpleNamespace(
        date_dir=None, corpus=tmp_path / "c", initiative=tmp_path / "i", eu=tmp_path / "e"
    )
    assert _inventar_surse(state)["mod"] == "local_readonly"


def test_cli_json_export(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["inventar_surse"])
    main()
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
    assert not list(tmp_path.iterdir())


def test_query_budget_returns_unavailable_not_zero(tmp_path, monkeypatch):
    path = tmp_path / "expensive.db"
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE VIEW acte AS WITH RECURSIVE rows(id) AS "
            "(SELECT 1 UNION ALL SELECT id+1 FROM rows WHERE id<1000000) SELECT id FROM rows"
        )
    monkeypatch.setattr("scripts.inventar_surse.MAX_PROGRESS_CALLBACKS", 0)
    out = _sursa(path, "corpus")
    assert out["stare"] == "partial"
    assert out["metrici"]["acte"] == {"stare": "indisponibil", "valoare": None}
