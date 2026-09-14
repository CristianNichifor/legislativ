import json
from pathlib import Path

from scripts import public_local_acceptance

ROOT = Path(__file__).resolve().parents[1]


def test_public_local_acceptance_gate_passes_for_repo():
    report = public_local_acceptance.run(ROOT)

    assert report["contract"] == "public-local-acceptance-v1"
    assert report["status"] == "ok"
    assert {check["key"] for check in report["checks"]} >= {
        "pages:public_deploy",
        "local:downloadable_package",
        "local:cold_start_smoke",
        "data:channel_manifest_contract",
        "data:update_private_boundary",
        "public:optional_source_states",
        "public:server_unavailable_states",
    }
    assert all(report["acceptance"].values())


def test_public_local_acceptance_json_cli(capsys):
    assert public_local_acceptance.main(["--root", str(ROOT), "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["contract"] == "public-local-acceptance-v1"
    assert out["status"] == "ok"
    assert "npm run test:browser:static" in out["commands"]
