from __future__ import annotations

import json
from datetime import UTC, datetime

from scripts import final_acceptance


def _completeness(*, complete: bool) -> dict:
    source_status = {
        "status": "ok" if complete else "blocked",
        "missing_required": 0,
        "unsynced_required": 0 if complete else 12,
        "attention_sources": 0,
    }
    return {
        "contract": "app-completeness-gate-v1",
        "completion_claim_allowed": complete,
        "summary": {"ready": 9 if complete else 7, "partial": 0 if complete else 2, "missing": 0},
        "source_status": source_status,
        "blocking_capabilities": []
        if complete
        else [
            {
                "key": "public_source_data_availability",
                "state": "partial",
                "blockers": ["12 source families unsynced"],
            }
        ],
        "capabilities": [
            {
                "key": "public_source_data_availability",
                "label": "Public source data availability",
                "state": "ready" if complete else "partial",
                "evidence": "source registry",
            }
        ],
        "vertical_acceptance": {
            "status": "passed",
            "contract": "final-v1-vertical-acceptance-flow-v1",
            "checks": {"search_finds_law": True},
            "summary": {"search_results": 2},
        },
        "limitari": ["No legal verdict."],
    }


def test_final_acceptance_report_records_blockers(monkeypatch):
    monkeypatch.setattr(
        final_acceptance,
        "_runtime_completeness",
        lambda *_args: (_completeness(complete=False), None),
    )
    monkeypatch.setattr(final_acceptance, "_git_commit", lambda: "abc123")

    report, summary = final_acceptance.build(generated_at=datetime(2026, 9, 15, tzinfo=UTC))

    assert summary["status"] == "blocked"
    assert summary["blocking_capabilities"] == ["public_source_data_availability"]
    assert "Status: **blocked**" in report
    assert "`public_source_data_availability`: partial" in report
    assert "Unsynced required source families: `12`" in report
    assert "uv run python -m scripts.app_completeness" in report


def test_final_acceptance_report_records_ready_anchor_sync(monkeypatch):
    anchor_sync = {
        "contract": "source-bootstrap-anchor-sync-v1",
        "total": 14,
        "counts": {"unchanged": 14},
    }
    monkeypatch.setattr(
        final_acceptance,
        "_runtime_completeness",
        lambda *_args: (_completeness(complete=True), anchor_sync),
    )
    monkeypatch.setattr(final_acceptance, "_git_commit", lambda: "def456")

    report, summary = final_acceptance.build(
        data_home="/tmp/legislativ-home",
        sync_source_anchors=True,
        generated_at=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert summary["status"] == "passed"
    assert summary["completion_claim_allowed"] is True
    assert summary["anchor_sync"] == anchor_sync
    assert "Status: **passed**" in report
    assert "source-bootstrap-anchor-sync-v1" in report
    assert '"unchanged": 14' in report


def test_final_acceptance_cli_writes_report_and_fails_closed(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        final_acceptance,
        "_runtime_completeness",
        lambda *_args: (_completeness(complete=False), None),
    )
    monkeypatch.setattr(final_acceptance, "_git_commit", lambda: "abc123")
    out = tmp_path / "FINAL_ACCEPTANCE.md"

    result = final_acceptance.main(["--output", str(out), "--require-complete"])
    summary = json.loads(capsys.readouterr().out)

    assert result == 2
    assert summary["status"] == "blocked"
    assert out.is_file()
    assert "Status: **blocked**" in out.read_text(encoding="utf-8")


def test_final_acceptance_refuses_passed_without_a_verified_runtime(monkeypatch):
    monkeypatch.setattr(
        final_acceptance,
        "_runtime_completeness",
        lambda *_args: (_completeness(complete=True), None),
    )
    monkeypatch.setattr(final_acceptance, "_git_commit", lambda: "abc123")

    report, summary = final_acceptance.build(generated_at=datetime(2026, 9, 15, tzinfo=UTC))

    assert summary["completion_claim_allowed"] is True
    assert summary["status"] == "blocked"
    assert summary["evidence_basis"] == "static_only"
    assert summary["data_home_used"] is False
    assert summary["anchors_verified"] is False
    assert "Status: **blocked**" in report
    assert "Evidence basis: `static_only`" in report
    assert "Data home: `not used`" in report
    assert "Completion claim allowed by the gate: `true`" in report


def test_final_acceptance_marks_runtime_without_anchors_as_unverified(monkeypatch):
    monkeypatch.setattr(
        final_acceptance,
        "_runtime_completeness",
        lambda *_args: (_completeness(complete=True), None),
    )
    monkeypatch.setattr(final_acceptance, "_git_commit", lambda: "abc123")

    report, summary = final_acceptance.build(
        data_home="/tmp/legislativ-home",
        generated_at=datetime(2026, 9, 15, tzinfo=UTC),
    )

    assert summary["status"] == "blocked"
    assert summary["evidence_basis"] == "runtime_no_anchors"
    assert "Official anchors verified in this run: `false`" in report


def test_final_acceptance_reports_coverage_by_sync_capability(monkeypatch):
    completeness = _completeness(complete=False)
    completeness["source_status"]["anchor_only_required"] = 3
    completeness["source_status"]["sync_capability_counts"] = {
        "automated": {"total": 5, "ok": 1, "families": ["camera", "senat"]},
        "anchor_only": {"total": 3, "ok": 0, "families": ["legislatie_ro", "ccr"]},
    }
    monkeypatch.setattr(
        final_acceptance,
        "_runtime_completeness",
        lambda *_args: (completeness, None),
    )
    monkeypatch.setattr(final_acceptance, "_git_commit", lambda: "abc123")

    report, _ = final_acceptance.build(generated_at=datetime(2026, 9, 15, tzinfo=UTC))

    assert "Anchor-only required source families: `3`" in report
    assert "### Coverage By Sync Capability" in report
    assert "| `anchor_only` | 0 | 3 | legislatie_ro, ccr |" in report
    assert "| `automated` | 1 | 5 | camera, senat |" in report


def test_final_acceptance_cli_fails_closed_on_an_unverified_basis(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        final_acceptance,
        "_runtime_completeness",
        lambda *_args: (_completeness(complete=True), None),
    )
    monkeypatch.setattr(final_acceptance, "_git_commit", lambda: "abc123")
    out = tmp_path / "FINAL_ACCEPTANCE.md"

    result = final_acceptance.main(["--output", str(out), "--require-complete"])
    summary = json.loads(capsys.readouterr().out)

    assert result == 2
    assert summary["completion_claim_allowed"] is True
    assert summary["evidence_basis"] == "static_only"
