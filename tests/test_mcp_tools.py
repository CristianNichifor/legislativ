from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import depozit, mcp_tools, tracker_events
from scripts.parsare import ActParsat, Provizie
from scripts.referinte import Act


def state(tmp_path):
    corpus = tmp_path / "corpus.db"
    initiative = tmp_path / "initiative.db"
    depozit.importa(
        corpus,
        [
            ActParsat(
                act=Act("lege", "10", 2026),
                titlu="LEGE nr. 10 din 2026",
                provizii=(Provizie("art1", "achiziții publice și praguri valorice"),),
            )
        ],
    )
    with depozit.deschide(initiative) as con:
        con.execute(
            "INSERT INTO initiative(plx_id,cam,idp,titlu,stadiu,citit_la,data_inreg,sursa_url) "
            "VALUES ('plx-10-2026',2,'10','Proiect achiziții','Raport depus',"
            "'2026-09-12T10:00:00+00:00','2026-09-01','https://www.cdep.ro/proiect10')"
        )
        con.commit()
    stare = SimpleNamespace(corpus=corpus, initiative=initiative, eu=tmp_path / "eu.db")
    tracker_events.adauga(
        stare,
        {
            "event_type": "report_filed",
            "project_id": "plx-10-2026",
            "source_family": "camera",
            "source_url": "https://www.cdep.ro/proiect10",
            "occurred_at": "2026-09-12T10:00:00+00:00",
            "title": "Raport depus",
            "payload": {"affected_act": "lege-10-2026"},
            "content_hash": "a" * 64,
        },
    )
    return stare


def test_tool_schemas_are_bounded_and_exclude_verdict_tools():
    out = mcp_tools.tool_schemas()
    names = {tool["name"] for tool in out["tools"]}

    assert out["contract"] == "bounded-mcp-tools-v1"
    assert names == {
        "search_laws",
        "search_projects",
        "get_source_status",
        "get_project_timeline",
        "get_evidence_bundle",
        "draft_from_evidence",
    }
    assert not any("verdict" in name or "legality" in name for name in names)
    assert "ai_legal_verdict" in out["forbidden_tools"]
    assert out["execution"]["external_calls"] is False
    assert out["execution"]["model_calls"] is False


def test_local_tools_search_laws_projects_and_report_source_status(tmp_path):
    stare = state(tmp_path)

    laws = mcp_tools.call_tool(stare, "search_laws", {"q": "achizitii", "limit": 5})
    projects = mcp_tools.call_tool(stare, "search_projects", {"q": "achiziții"})
    status = mcp_tools.call_tool(stare, "get_source_status")

    assert laws["contract"] == "bounded-mcp-search-laws-v1"
    assert laws["results"][0]["act_id"] == "lege-10-2026"
    assert projects["contract"] == "bounded-mcp-search-projects-v1"
    assert projects["projects"][0]["project_id"] == "plx-10-2026"
    assert status["contract"] == "bounded-mcp-source-status-v1"
    assert status["mode"] == "local_first"
    assert status["external_calls"] is False
    assert status["stores"]["corpus"]["available"] is True


def test_timeline_and_evidence_bundle_read_selected_local_project(tmp_path):
    stare = state(tmp_path)

    timeline = mcp_tools.call_tool(
        stare, "get_project_timeline", {"project_id": "plx-10-2026"}
    )
    bundle = mcp_tools.call_tool(
        stare, "get_evidence_bundle", {"project_id": "plx-10-2026", "event_limit": 10}
    )

    assert timeline["contract"] == "bounded-mcp-project-timeline-v1"
    assert timeline["events"][0]["event_type"] == "report_filed"
    assert any("nu este verdict juridic" in item for item in timeline["limitari"])
    assert bundle["contract"] == "project-evidence-pack-v1"
    assert bundle["tool"] == "get_evidence_bundle"
    assert bundle["summary"]["events"] == 1
    assert bundle["evidence"][0]["source_url"] == "https://www.cdep.ro/proiect10"


def test_draft_from_evidence_builds_prompt_without_calling_model(tmp_path):
    stare = state(tmp_path)

    out = mcp_tools.call_tool(
        stare,
        "draft_from_evidence",
        {
            "task": "issue_note",
            "type": "lacuna",
            "title": "Verificare achiziții",
            "context": "Folosește numai dovada selectată.",
            "evidence": [
                {
                    "label": "Legea 10/2026 art. 1",
                    "act_id": "lege-10-2026",
                    "locator": "art1",
                    "source_url": "https://example.test/lege10",
                    "quote": "achiziții publice și praguri valorice",
                }
            ],
        },
    )

    assert out["tool"] == "draft_from_evidence"
    assert out["contract"] == "ai-evidence-draft-v1"
    assert out["approval"]["server_calls_model"] is False
    assert out["audit"]["approved_external_send"] is False
    assert "nu verdict juridic" in out["export_manifest"]["non_verdict_notice"]


@pytest.mark.parametrize("name", ["legal_verdict", "ai_legal_verdict", "decide_legality"])
def test_verdict_tools_are_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="verdict juridic"):
        mcp_tools.call_tool(state(tmp_path), name, {})
