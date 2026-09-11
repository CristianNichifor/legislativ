from scripts import acceptare_date_reale as acceptance
from scripts.dosare import LAW_WORKBENCH_ENGINE_VERSION


def test_real_data_acceptance_runs_workbench_without_synthetic_bridge(monkeypatch):
    calls = []

    def fake_request(_httpd, path="/api/date", body=None, *, timeout=1800):
        calls.append((path, body, timeout))
        if path.startswith("/api/fisa-act?"):
            return {"gasit": True, "act_id": "lege-98-2016"}
        if path == "/api/dosare/rulari" and body:
            return {
                "id": "rulare-real",
                "engine_version": LAW_WORKBENCH_ENGINE_VERSION,
                "raport": {
                    "referinte_ue": [{"celex": "32014L0024"}],
                    "rand": {
                        "semnale": {
                            "viduri": 0,
                            "neconstitutionale": 0,
                            "initiative_in_lucru": 1,
                            "amendamente_primite": 2,
                        }
                    },
                },
            }
        if path.startswith("/api/dosare/revizuiri?"):
            return {"constatari": []}
        raise AssertionError((path, body))

    monkeypatch.setattr(acceptance, "request", fake_request)
    out = acceptance.pilot_workbench(
        object(),
        "b" * 32,
        search_results={"results": [{"act_id": "lege-98-2016"}]},
    )

    assert out["status"] == "passed"
    assert out["engine_version"] == LAW_WORKBENCH_ENGINE_VERSION
    assert out["signals"] == {
        "viduri": 0,
        "neconstitutionale": 0,
        "initiative_in_lucru": 1,
        "amendamente_primite": 2,
        "referinte_ue": 1,
    }
    assert out["reviewable_findings"] == 0
    assert out["finding_to_proposal"] == "not_exercised_no_authentic_gap_or_ccr_finding"
    assert calls[0][0] == "/api/fisa-act?act=lege-98-2016"
    assert calls[1][1] == {"dosar_id": "b" * 32, "filtre": {"act": "lege-98-2016"}}


def test_real_data_acceptance_reports_when_no_act_can_be_selected(monkeypatch):
    def fail_request(*_args, **_kwargs):
        raise AssertionError

    monkeypatch.setattr(acceptance, "request", fail_request)

    assert acceptance.pilot_workbench(object(), "b" * 32, search_results={"results": []}) == {
        "status": "skipped_no_search_act",
        "finding_to_proposal": "not_exercised_no_act",
    }
