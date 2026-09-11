from scripts.lifecycle import (
    ACTIVE_STAGE_KEYS,
    STAGES,
    TERMINAL_STAGE_KEYS,
    is_active_stage,
    normalize_stage_label,
    watchlist_lifecycle,
)


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
