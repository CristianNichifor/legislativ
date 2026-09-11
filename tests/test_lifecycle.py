import io
from datetime import UTC, datetime
from types import SimpleNamespace

from scripts import depozit, source_registry
from scripts.lifecycle import (
    ACTIVE_STAGE_KEYS,
    STAGES,
    TERMINAL_STAGE_KEYS,
    is_active_stage,
    normalize_stage_label,
    project_lifecycle_item,
    project_lifecycle_summary,
    watchlist_lifecycle,
)
from scripts.server import face_handler


def test_lifecycle_model_covers_public_consultation_and_parliamentary_stages():
    keys = {stage.key for stage in STAGES}
    assert {
        "consultation_announced",
        "consultation_open",
        "consultation_closed",
        "drafting",
        "government_adopted",
        "sent_to_parliament",
        "registered",
        "committee",
        "report",
        "plenary_scheduled",
        "adopted",
        "rejected",
        "promulgated",
        "published",
        "withdrawn_archived",
        "unknown",
        "unavailable",
    } <= keys
    assert "report" in ACTIVE_STAGE_KEYS
    assert {"rejected", "promulgated", "published", "withdrawn_archived"} <= TERMINAL_STAGE_KEYS


def test_known_stage_labels_normalize_to_bounded_states():
    examples = {
        "Anunț dezbatere publică publicat pe site": "consultation_announced",
        "Proiect supus consultării publice": "consultation_open",
        "Termen consultare expirat": "consultation_closed",
        "În avizare interministerială": "drafting",
        "Adoptat de Guvern": "government_adopted",
        "Trimis Parlamentului pentru dezbatere": "sent_to_parliament",
        "Înregistrat la Camera Deputaților": "registered",
        "Trimis pentru raport la comisii": "committee",
        "Raport depus de comisia sesizată în fond": "report",
        "Pe ordinea de zi a plenului": "plenary_scheduled",
        "Vot final adoptat": "adopted",
        "Respins definitiv de Camera Deputaților": "rejected",
        "Decret de promulgare emis": "promulgated",
        "Publicat în Monitorul Oficial": "published",
        "Retras de inițiator": "withdrawn_archived",
    }
    for raw, key in examples.items():
        assert normalize_stage_label(raw)["key"] == key


def test_unknown_and_unavailable_are_not_guessed():
    unavailable = normalize_stage_label("")
    assert unavailable["key"] == "unavailable"
    assert unavailable["available"] is False
    assert unavailable["known"] is False

    unknown = normalize_stage_label("Etapă nouă pe portal")
    assert unknown["key"] == "unknown"
    assert unknown["available"] is True
    assert unknown["known"] is False
    assert unknown["raw"] == "Etapă nouă pe portal"


def test_active_stage_helper_does_not_treat_terminal_or_missing_as_live():
    assert is_active_stage("Raport depus")
    assert not is_active_stage("Respins definitiv")
    assert not is_active_stage("")
    assert not is_active_stage("Etapă nouă pe portal")
    assert normalize_stage_label("Adoptat de Senat")["key"] == "unknown"


def test_watchlist_lifecycle_marks_rows_that_need_parser_attention():
    row = {
        "plx_id": "plx-1-2026",
        "titlu": "Proiect",
        "stadiu": "Etapă nouă pe portal",
        "sursa_url": "https://www.cdep.ro/proiect",
        "citit_la": "2026-09-11T10:00:00+00:00",
    }
    out = watchlist_lifecycle(row)
    assert out["plx_id"] == "plx-1-2026"
    assert out["lifecycle"]["key"] == "unknown"
    assert out["needs_attention"] is True


def test_project_lifecycle_item_exposes_stale_unknown_and_unavailable_states():
    now = datetime(2026, 9, 11, tzinfo=UTC)
    row = {
        "plx_id": "plx-1-2026",
        "titlu": "Proiect",
        "stadiu": "Raport depus",
        "citit_la": "2026-09-10T10:00:00+00:00",
        "data_inreg": "2026-09-01",
        "sursa_url": "https://www.cdep.ro/proiect",
    }
    ok = project_lifecycle_item(row, now=now)
    assert ok["project_id"] == "plx-1-2026"
    assert ok["source_name"] == "Camera Deputaților"
    assert ok["stage"]["key"] == "report"
    assert ok["source_state"] == "ok"
    assert ok["needs_attention"] is False
    stale = project_lifecycle_item({**row, "citit_la": "2026-07-01T00:00:00+00:00"}, now=now)
    assert stale["source_state"] == "stale" and stale["needs_attention"]
    unknown = project_lifecycle_item({**row, "stadiu": "Etapă nouă"}, now=now)
    assert unknown["source_state"] == "unknown"
    unavailable = project_lifecycle_item({**row, "stadiu": "", "sursa_url": ""}, now=now)
    assert unavailable["source_state"] == "unavailable"


def test_project_lifecycle_summary_reads_local_store_and_bounds_results(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db")
    with depozit.deschide(state.initiative) as con:
        con.executemany(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES (?,2,?, ?, ?, ?, ?, ?)",
            [
                (
                    "plx-1-2026",
                    "101",
                    "Lege fiscală",
                    "Raport depus",
                    "2026-09-10T10:00:00+00:00",
                    "2026-09-01",
                    "https://www.cdep.ro/proiect1",
                ),
                (
                    "plx-2-2026",
                    "102",
                    "Lege muncă",
                    "Etapă nouă",
                    "2026-08-01T10:00:00+00:00",
                    "2026-08-01",
                    "https://www.cdep.ro/proiect2",
                ),
            ],
        )
        con.commit()
    now = datetime(2026, 9, 11, tzinfo=UTC)
    out = project_lifecycle_summary(state, query="Lege", limit=1, stale_days=20, now=now)
    assert out["source_status"] == "ok"
    assert out["total"] == 2
    assert out["returned"] == 1
    assert out["mai_multe"] is True
    assert out["projects"][0]["project_id"] == "plx-1-2026"
    second = project_lifecycle_summary(state, query="muncă", limit=10, stale_days=20, now=now)
    assert second["source_status"] == "needs_review"
    assert second["unknown_stage"] == 1
    assert second["projects"][0]["source_state"] == "unknown"


def test_project_lifecycle_summary_includes_registry_attention(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db")
    with depozit.deschide(state.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 10/2026',2,'10','Lege urmărită','Raport depus',"
            "'2026-09-10T10:00:00+00:00','2026-09-01','https://www.cdep.ro/proiect10')"
        )
        con.commit()
    row = source_registry.executa(state, {"family": "parlament", "identifier": "PL-x 10/2026"})
    source_registry.executa(state, {"action": "queue", "id": row["id"]})
    source_registry.executa(
        state,
        {
            "action": "record",
            "id": row["id"],
            "state": "fetched",
            "content_hash": "d" * 64,
            "parser_version": "test",
        },
    )
    changed = source_registry.executa(
        state,
        {
            "action": "record",
            "id": row["id"],
            "state": "changed",
            "content_hash": "e" * 64,
            "parser_version": "test",
        },
    )

    out = project_lifecycle_summary(
        state, query="PL-x 10/2026", now=datetime(2026, 9, 11, tzinfo=UTC)
    )

    project = out["projects"][0]
    assert project["source_state"] == "ok"
    assert project["needs_attention"] is True
    assert project["registry_needs_attention"] is True
    assert project["registry_source_id"] == changed["id"]
    assert project["registry_source_state"] == "changed"
    assert project["registry_can_sync"] is True


def test_project_lifecycle_summary_reports_unavailable_source_without_leaking_paths(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "missing.db")
    out = project_lifecycle_summary(state)
    assert out["source_status"] == "unavailable"
    assert out["projects"] == []
    assert "missing.db" not in " ".join(out["limitari"])


def _request(state, query=""):
    handler = object.__new__(face_handler(state))
    handler.path = "/api/lifecycle-proiecte" + query
    handler.rfile = io.BytesIO()
    handler.headers = {"Host": "localhost:8123", "Content-Length": "0"}
    handler.server = SimpleNamespace(server_port=8123)
    result = []
    handler._json = lambda data, code=200: result.append((code, data))
    handler.do_GET()
    return result[0]


def test_http_project_lifecycle_endpoint_validates_query(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db")
    with depozit.deschide(state.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la) "
            "VALUES ('plx-1',2,'1','Proiect','Raport depus','2026-09-10')"
        )
        con.commit()
    code, data = _request(state, "?q=Proiect&limit=10&offset=0")
    assert code == 200
    assert data["projects"][0]["stage"]["key"] == "report"
    assert _request(state, "?limit=bad")[0] == 400
