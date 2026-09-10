"""The shell cache identifies both the runtime and its public catalogs."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import construieste_web as cw


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "WEB", tmp_path)
    monkeypatch.setattr(cw, "DATA", tmp_path / "data")
    cw.DATA.mkdir()
    (cw.DATA / "manifest.json").write_text('{"acte":4}', encoding="utf-8")
    return tmp_path


def test_unchanged_rebuild_and_manifest_key_order_are_stable(web):
    first = cw._versiune_si_sw()
    sw = (web / "sw.js").read_bytes()
    assert cw._versiune_si_sw() == first
    (cw.DATA / "manifest.json").write_text(
        '{"versiune":"previous-generated-value", "acte":4}', encoding="utf-8"
    )
    assert cw._versiune_si_sw() == first
    assert (web / "sw.js").read_bytes() == sw
    assert json.loads((cw.DATA / "manifest.json").read_text())["versiune"] == first


def test_initially_missing_manifest_is_stable(web):
    (cw.DATA / "manifest.json").unlink()
    assert cw._versiune_si_sw() == cw._versiune_si_sw()


def test_worker_and_precache_share_content_qualified_bundle_url(web):
    urls = []
    for content in (b"python version one", b"python version two"):
        (web / "bundle.zip").write_bytes(content)
        cw._worker()
        cw._versiune_si_sw()
        url = "bundle.zip?v=" + hashlib.sha256(content).hexdigest()
        worker = (web / "worker.js").read_text(encoding="utf-8")
        sw = (web / "sw.js").read_text(encoding="utf-8")
        assert f'fetch("{url}")' in worker
        assert f'"./{url}"' in sw
        assert 'fetch("bundle.zip")' not in worker
        assert '"./bundle.zip"' not in sw
        urls.append(url)
    assert urls[0] != urls[1]


def test_missing_unit_fixture_bundle_uses_same_empty_tag_without_fallback(web):
    cw._worker()
    cw._versiune_si_sw()
    worker = (web / "worker.js").read_text(encoding="utf-8")
    assert 'fetch("bundle.zip?v=")' in worker
    assert '"./bundle.zip?v="' in (web / "sw.js").read_text(encoding="utf-8")
    assert 'fetch("bundle.zip")' not in worker


@pytest.mark.parametrize(
    "name",
    [
        "bundle.zip",
        "worker.js",
        "index.html",
        "browser-workspace.js",
        "browser-generation.js",
        "dataset-updates.js",
        "fonts/test.woff2",
        *["pagefind/" + name for name in cw.CLIENT_CAUTARE],
        "data/termeni.json",
        "data/initiative.db",
        "data/graf.db",
        "data/eu.db",
        "data/vid.json",
        "data/neconstitutional.json",
        "data/norme_lovite.json",
        "data/considerente.json",
        "data/parlament.json",
        "data/ue_acoperire.json",
    ],
)
def test_runtime_or_catalog_change_rotates_cache(web, name):
    path = web / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(b"first")
    first = cw._versiune_si_sw()
    path.write_bytes(b"other")
    assert cw._versiune_si_sw() != first
    path.unlink()
    assert cw._versiune_si_sw() != first


def test_streaming_excludes_corpus_shards_and_private_files(web, monkeypatch):
    ignored = [
        web / name
        for name in (
            "data/corpus.db",
            "data/dosare.db",
            "workspace/dosare.db",
            "data/acte/large.json",
        )
    ]
    for path in ignored:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"never read")
    (web / "bundle.zip").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    original = Path.open
    reads = []

    class Stream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024
            reads.append(size)
            return self.stream.read(size)

    def bounded(path, mode="r", *args, **kwargs):
        assert path not in ignored
        stream = original(path, mode, *args, **kwargs)
        return Stream(stream) if mode == "rb" else stream

    monkeypatch.setattr(Path, "open", bounded)
    first = cw._versiune_si_sw()
    assert len(reads) >= 4
    assert cw._versiune_si_sw() == first


def test_activation_only_deletes_old_shell_caches(web):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute the generated service worker")
    version = cw._versiune_si_sw()
    script = """
const vm = require('node:vm'), assert = require('node:assert/strict');
const handlers = {}, deleted = [];
const sandbox = {
  self: {addEventListener: (type, handler) => handlers[type] = handler,
         clients: {claim: async () => {}}},
  caches: {keys: async () => ['legislativ-shell-old', CURRENT, 'public-generation',
      'legislativ-private-workspace-v1', 'unrelated-app'],
    delete: async key => {deleted.push(key);}},
};
Object.defineProperty(sandbox, 'indexedDB', {get() {throw Error('Private IDB touched');}});
vm.runInNewContext(SOURCE, sandbox);
handlers.activate({waitUntil: promise => promise.then(() => {
  assert.deepEqual(deleted, ['legislativ-shell-old']);
}).catch(error => {console.error(error); process.exitCode = 1;})});
"""
    script = script.replace("CURRENT", json.dumps("legislativ-shell-" + version))
    script = script.replace("SOURCE", json.dumps((web / "sw.js").read_text(encoding="utf-8")))
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=20)


def test_active_cache_cannot_match_old_bundle_to_new_qualified_request(web):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute the generated service worker")
    (web / "bundle.zip").write_bytes(b"new Python runtime")
    cw._versiune_si_sw()
    source = (web / "sw.js").read_text(encoding="utf-8")
    script = """
const vm = require('node:vm'), assert = require('node:assert/strict');
const handlers = {}, origin = 'https://example.invalid', fetched = [];
const oldEntries = new Map([
  [origin + '/bundle.zip', {old: true}],
  [origin + '/bundle.zip?v=old', {old: true}],
]);
const sandbox = {
  URL, location: {origin},
  self: {addEventListener: (type, handler) => handlers[type] = handler},
  caches: {open: async () => ({match: async req => oldEntries.get(req.url), put: () => {}})},
  fetch: async req => {fetched.push(req.url); return {fresh: true, ok: false};},
};
vm.runInNewContext(SOURCE, sandbox);
handlers.fetch({request: {method:'GET', url:origin + '/' + BUNDLE}, respondWith: promise =>
  promise.then(result => {
    assert.equal(result.fresh, true);
    assert.deepEqual(fetched, [origin + '/' + BUNDLE]);
  }).catch(error => {console.error(error); process.exitCode = 1;})});
"""
    script = script.replace("SOURCE", json.dumps(source)).replace(
        "BUNDLE", json.dumps(cw._bundle_url())
    )
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True, timeout=20)
