import json
from pathlib import Path

from scripts import release_smoke

ROOT = Path(__file__).resolve().parents[1]


def test_release_smoke_contract_passes_for_repo():
    report = release_smoke.run(ROOT)

    assert report["contract"] == "release-smoke-v1"
    assert report["status"] == "ok"
    assert {check["key"] for check in report["checks"]} >= {
        "file:app/index.html",
        "file:ruleaza.sh",
        "local_launch:private_data_home",
        "public_app:workspace_and_updates",
        "browser_checks:npm_scripts",
        "pages:workflow",
    }


def test_release_smoke_json_cli(capsys):
    assert release_smoke.main(["--root", str(ROOT), "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["contract"] == "release-smoke-v1"
    assert out["status"] == "ok"
