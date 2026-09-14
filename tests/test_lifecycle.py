import io
from datetime import UTC, datetime
from types import SimpleNamespace

from scripts import depozit, dosare, source_registry, tracker_events
from scripts.lifecycle import (
    ACTIVE_STAGE_KEYS,
    CANONICAL_PROJECT_STATUSES,
    STAGES,
    TERMINAL_STAGE_KEYS,
    canonical_project_status,
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


def test_canonical_project_status_contract_groups_portal_specific_stages():
    keys = {status.key for status in CANONICAL_PROJECT_STATUSES}
    assert {
        "consultation",
        "drafting",
        "parliamentary",
        "committee",
        "plenary",
        "promulgation",
        "published",
        "closed",
        "unknown",
        "unavailable",
    } <= keys
    assert canonical_project_status({"key": "consultation_open"}) == {
        "key": "consultation",
        "label": "consultation",
        "order": 10,
        "terminal": False,
        "available": True,
        "known": True,
        "stage_key": "consultation_open",
        "contract": "canonical-project-status-v1",
    }
    assert canonical_project_status("report")["key"] == "committee"
    assert canonical_project_status("adopted")["key"] == "plenary"
    assert canonical_project_status("published")["terminal"] is True
    assert canonical_project_status("withdrawn_archived")["key"] == "closed"
    assert canonical_project_status(None)["key"] == "unknown"


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
    assert ok["canonical_status"]["key"] == "committee"
    assert ok["canonical_status"]["contract"] == "canonical-project-status-v1"
    assert ok["stage_date"] == "2026-09-01"
    assert ok["latest_event"]["source_url"] == "https://www.cdep.ro/proiect"
    assert ok["latest_event"]["from_timeline"] is False
    assert ok["uncertainty"] == {
        "level": "low",
        "reasons": [],
        "message": "Stadiu citit din sursa locală.",
    }
    assert ok["source_state"] == "ok"
    assert ok["source_freshness_state"] == "partial"
    assert ok["source_freshness_status"]["label"] == "Parțială"
    assert {"stage": "consultation", "source_family": "consultare_econsultare"} in [
        {"stage": row["stage"], "source_family": row["source_family"]}
        for row in ok["missing_source_states"]
    ]
    assert ok["needs_attention"] is False
    stale = project_lifecycle_item({**row, "citit_la": "2026-07-01T00:00:00+00:00"}, now=now)
    assert stale["source_state"] == "stale" and stale["needs_attention"]
    assert stale["source_freshness_state"] == "stale"
    assert stale["uncertainty"]["level"] == "medium"
    assert stale["uncertainty"]["reasons"] == ["stale_source_read"]
    unknown = project_lifecycle_item({**row, "stadiu": "Etapă nouă"}, now=now)
    assert unknown["source_state"] == "unknown"
    assert unknown["source_freshness_state"] == "needs_review"
    assert unknown["uncertainty"]["level"] == "high"
    assert "unrecognized_stage_label" in unknown["uncertainty"]["reasons"]
    unavailable = project_lifecycle_item({**row, "stadiu": "", "sursa_url": ""}, now=now)
    assert unavailable["source_state"] == "unavailable"
    assert unavailable["source_freshness_state"] == "unavailable"
    assert unavailable["uncertainty"]["level"] == "high"


def test_project_lifecycle_item_marks_deadline_soon_and_recent_stage_change():
    now = datetime(2026, 9, 11, tzinfo=UTC)
    row = {
        "plx_id": "PL-x 30/2026",
        "titlu": "Proiect cu termen",
        "stadiu": "Raport depus",
        "citit_la": "2026-09-11T10:00:00+00:00",
        "data_inreg": "2026-09-01",
        "sursa_url": "https://www.cdep.ro/proiect30",
        "consultation_deadline": "2026-09-20",
    }

    out = project_lifecycle_item(
        row,
        latest_event={
            "data": "2026-09-10",
            "camera": "Camera Deputaților",
            "actiune": "Raport depus",
        },
        now=now,
    )

    assert out["needs_attention"] is True
    assert out["deadline_attention"]["state"] == "deadline_soon"
    assert out["deadline_attention"]["days_until"] == 9
    assert out["stage_change_attention"]["state"] == "recent_stage_change"
    assert out["stage_change_attention"]["days_since"] == 1
    assert out["attention_reasons"] == ["deadline_soon", "recent_stage_change"]


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
    assert second["source_freshness_states"]["needs_review"] == 1
    assert second["unknown_stage"] == 1
    assert second["projects"][0]["source_state"] == "unknown"
    assert second["unknown_stage_review_queue"] == [
        {
            "raw_label": "Etapă nouă",
            "count": 1,
            "projects": [
                {
                    "project_id": "plx-2-2026",
                    "title": "Lege muncă",
                    "source_url": "https://www.cdep.ro/proiect2",
                    "last_seen": "2026-08-01T10:00:00+00:00",
                }
            ],
            "next_action": "Mapează eticheta în lifecycle.py sau marchează sursa ca nesuportată.",
        }
    ]


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
    assert project["affected_dossiers"] == 0
    assert project["uncertainty"]["level"] == "medium"
    assert "tracked_source_needs_review" in project["uncertainty"]["reasons"]


def test_project_lifecycle_summary_exposes_latest_timeline_event(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db")
    with depozit.deschide(state.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 20/2026',2,'20','Lege parcurs','Pe ordinea de zi',"
            "'2026-09-10T10:00:00+00:00','2026-09-01','https://www.cdep.ro/proiect20')"
        )
        con.executemany(
            "INSERT INTO initiativa_etapa(plx_id,ord,data,camera,actiune) VALUES (?,?,?,?,?)",
            [
                ("PL-x 20/2026", 0, "2026-09-01", "Camera Deputaților", "Înregistrat"),
                ("PL-x 20/2026", 1, "2026-09-08", "Camera Deputaților", "Pe ordinea de zi"),
            ],
        )
        con.commit()

    out = project_lifecycle_summary(
        state, query="PL-x 20/2026", now=datetime(2026, 9, 11, tzinfo=UTC)
    )

    project = out["projects"][0]
    assert project["stage"]["key"] == "plenary_scheduled"
    assert project["stage_date"] == "2026-09-08"
    assert project["latest_event"] == {
        "date": "2026-09-08",
        "source_name": "Camera Deputaților",
        "source_url": "https://www.cdep.ro/proiect20",
        "source_state": "ok",
        "stage_key": "plenary_scheduled",
        "stage_label": "plenary scheduled",
        "raw_status": "Pe ordinea de zi",
        "action": "Pe ordinea de zi",
        "camera": "Camera Deputaților",
        "from_timeline": True,
    }
    assert project["uncertainty"]["level"] == "low"


def test_project_lifecycle_summary_reads_optional_deadline_column(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db")
    with depozit.deschide(state.initiative) as con:
        con.execute("ALTER TABLE initiative ADD COLUMN consultation_deadline TEXT")
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url,"
            "consultation_deadline) VALUES ('PL-x 21/2026',2,'21','Lege termen',"
            "'În consultare publică','2026-09-10T10:00:00+00:00','2026-09-01',"
            "'https://www.cdep.ro/proiect21','15.09.2026')"
        )
        con.commit()

    out = project_lifecycle_summary(
        state, query="PL-x 21/2026", now=datetime(2026, 9, 11, tzinfo=UTC)
    )

    project = out["projects"][0]
    assert project["consultation_deadline"] == "15.09.2026"
    assert project["deadline_attention"]["date"] == "2026-09-15"
    assert project["deadline_attention"]["state"] == "deadline_soon"
    assert "deadline_soon" in project["attention_reasons"]
    assert "deadline" in project["filter_buckets"]


def test_project_lifecycle_summary_counts_user_work_buckets(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db")
    with depozit.deschide(state.initiative) as con:
        con.execute("ALTER TABLE initiative ADD COLUMN consultation_deadline TEXT")
        con.executemany(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url,"
            "consultation_deadline) VALUES (?,2,?,?,?,?,?,?,?)",
            [
                (
                    "PL-x 31/2026",
                    "31",
                    "Lege termen",
                    "În consultare publică",
                    "2026-09-10T10:00:00+00:00",
                    "2026-09-01",
                    "https://www.cdep.ro/proiect31",
                    "15.09.2026",
                ),
                (
                    "PL-x 32/2026",
                    "32",
                    "Lege comisie",
                    "Raport depus",
                    "2026-09-10T10:00:00+00:00",
                    "2026-09-01",
                    "https://www.cdep.ro/proiect32",
                    "",
                ),
                (
                    "PL-x 33/2026",
                    "33",
                    "Lege plen",
                    "Pe ordinea de zi",
                    "2026-09-10T10:00:00+00:00",
                    "2026-09-01",
                    "https://www.cdep.ro/proiect33",
                    "",
                ),
                (
                    "PL-x 34/2026",
                    "34",
                    "Lege publicată",
                    "Publicat în Monitorul Oficial",
                    "2026-09-10T10:00:00+00:00",
                    "2026-09-01",
                    "https://www.cdep.ro/proiect34",
                    "",
                ),
            ],
        )
        con.commit()

    out = project_lifecycle_summary(state, limit=10, now=datetime(2026, 9, 11, tzinfo=UTC))
    by_id = {project["project_id"]: project for project in out["projects"]}

    assert by_id["PL-x 31/2026"]["filter_buckets"] == ["deadline"]
    assert by_id["PL-x 32/2026"]["filter_buckets"] == ["committee"]
    assert by_id["PL-x 33/2026"]["filter_buckets"] == ["vote"]
    assert by_id["PL-x 34/2026"]["filter_buckets"] == ["published"]
    assert out["filter_buckets"]["deadline"] == 1
    assert out["filter_buckets"]["committee"] == 1
    assert out["filter_buckets"]["vote"] == 1
    assert out["filter_buckets"]["published"] == 1


def test_project_lifecycle_summary_exposes_event_backed_timeline_coverage(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db")
    with depozit.deschide(state.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 40/2026',2,'40','Lege dovezi','Raport depus',"
            "'2026-09-10T10:00:00+00:00','2026-09-01','https://www.cdep.ro/proiect40')"
        )
        con.commit()
    for event in (
        {
            "event_type": "committee_assignment",
            "project_id": "PL-x 40/2026",
            "source_family": "camera",
            "source_url": "https://www.cdep.ro/comisie",
            "occurred_at": "2026-09-02T10:00:00+00:00",
            "title": "Comisie sesizată",
        },
        {
            "event_type": "report_filed",
            "project_id": "PL-x 40/2026",
            "source_family": "camera",
            "source_url": "https://www.cdep.ro/raport",
            "occurred_at": "2026-09-08T10:00:00+00:00",
            "title": "Raport depus",
            "payload": {
                "documents": [
                    {
                        "url": "https://www.cdep.ro/proiecte/raport.pdf",
                        "label": "Raport favorabil",
                    }
                ]
            },
        },
        {
            "event_type": "vote_recorded",
            "project_id": "PL-x 40/2026",
            "source_family": "camera",
            "source_url": "https://www.cdep.ro/vot",
            "occurred_at": "2026-09-09T10:00:00+00:00",
            "title": "Vot final",
        },
    ):
        tracker_events.adauga(state, event)

    out = project_lifecycle_summary(
        state, query="PL-x 40/2026", now=datetime(2026, 9, 11, tzinfo=UTC)
    )

    coverage = out["projects"][0]["timeline_coverage"]
    by_key = {stage["key"]: stage for stage in coverage["stages"]}
    assert coverage["contract"] == "project-timeline-coverage-v1"
    assert coverage["project_id"] == "PL-x 40/2026"
    assert coverage["total_events"] == 3
    assert by_key["committee"]["state"] == "present"
    assert by_key["committee"]["event_types"] == ["committee_assignment"]
    assert by_key["committee"]["suggested_source_family"] == "camera"
    assert by_key["report"]["count"] == 1
    assert by_key["vote"]["latest_at"] == "2026-09-09T10:00:00+00:00"
    assert by_key["publication"]["state"] == "missing"
    assert by_key["publication"]["suggested_source_family"] == "monitorul_oficial_pi"
    assert coverage["evidence_counts"]["documents"] == 1
    assert coverage["evidence_counts"]["reports"] == 1
    assert coverage["evidence_counts"]["votes"] == 1
    assert coverage["document_urls"] == ["https://www.cdep.ro/proiecte/raport.pdf"]
    assert "publication" in coverage["missing"]
    assert coverage["next_missing_stage"]["key"] == "consultation"
    assert coverage["next_source_hint"].startswith("Verifică e-consultare")
    assert coverage["complete"] is False
    assert coverage["next_action"] == "Completează următoarea dovadă: Consultare."
    assert out["projects"][0]["source_freshness_state"] == "partial"
    assert out["projects"][0]["missing_source_states"][0]["source_family"] == (
        "consultare_econsultare"
    )
    assert "evidence" in out["projects"][0]["filter_buckets"]
    assert out["filter_buckets"]["evidence"] == 1


def test_project_lifecycle_summary_counts_affected_dossiers(tmp_path):
    state = SimpleNamespace(initiative=tmp_path / "initiative.db", date_dir=None)
    with depozit.deschide(state.initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('PL-x 10/2026',2,'10','Lege urmărită','Raport depus',"
            "'2026-09-10T10:00:00+00:00','2026-09-01','https://www.cdep.ro/proiect10')"
        )
        con.commit()
    path = dosare.cale(state)
    dosare.creeaza(path, {"id": "a" * 32, "titlu": "Dosar proiect"})
    with dosare._open(path, write=True) as con:
        con.execute(
            "INSERT INTO rulari VALUES (?,?,?,?,?,?,?,?)",
            (
                "b" * 32,
                "a" * 32,
                "2026-09-11T10:00:00+00:00",
                "matrice-proiecte-v1",
                "c" * 64,
                "{}",
                '{"gasit":true,"selectie_proiecte":{"a":{"plx_id":"PL-x 10/2026","versiune_id":"'
                + "d" * 64
                + '"}}}',
                '{"manifest":{"dependente":[]}}',
            ),
        )

    out = project_lifecycle_summary(
        state, query="PL-x 10/2026", now=datetime(2026, 9, 11, tzinfo=UTC)
    )

    assert out["projects"][0]["affected_dossiers"] == 1


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
