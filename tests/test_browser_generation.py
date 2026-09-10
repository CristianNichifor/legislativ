import json

import pytest

from scripts import browser_workspace, construieste_web


def test_corpus_only_contract_and_duplicate_keys():
    manifest = {
        "schema_version": 1,
        "app_contract": 1,
        "release": "2026-09-10",
        "created_at": "2026-09-10T00:00:00Z",
        "files": [{"name": "corpus.db", "bytes": 4096, "sha256": "a" * 64}],
    }
    raw = json.dumps(manifest)
    assert (
        json.loads(
            browser_workspace.public_contract("manifest", raw, construieste_web.PUBLIC_CHANNEL)
        )
        == manifest
    )
    with pytest.raises(ValueError, match="duplicate"):
        browser_workspace.public_contract(
            "manifest", raw[:-1] + ',"schema_version":1}', construieste_web.PUBLIC_CHANNEL
        )


def test_channel_origin_and_explicit_loopback():
    raw = json.dumps(
        {
            "schema_version": 1,
            "manifest": "http://127.0.0.1:8058/2026-09-10/dataset-release.json",
            "sha256": "a" * 64,
        }
    )
    with pytest.raises(ValueError):
        browser_workspace.public_contract("channel", raw, "http://127.0.0.1:8058/channel.json")
    assert (
        json.loads(
            browser_workspace.public_contract(
                "channel", raw, "http://127.0.0.1:8058/channel.json", True
            )
        )["schema_version"]
        == 1
    )
    with pytest.raises(ValueError):
        browser_workspace.public_contract(
            "channel",
            raw.replace("127.0.0.1:8058", "evil.test"),
            "http://127.0.0.1:8058/channel.json",
            True,
        )
    with pytest.raises(ValueError):
        construieste_web._public_config("http://127.0.0.1:8058/channel.json")
    assert construieste_web._public_config("http://127.0.0.1:8058/channel.json", True)[
        "allowLoopback"
    ]


def test_selected_generation_excludes_build_search_indexes_and_data():
    worker = construieste_web.WORKER
    assert 'path === "/api/cauta" && !generation' in worker
    assert "if (generation) {" in worker
    assert "Object.entries(generation.reports)" in worker
    assert "expectedTotal" in worker
    assert "if (!selectedGeneration)" in construieste_web.BOOT
