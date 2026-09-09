"""Static checks for the browser AI boundary."""

from scripts.construieste_web import ROOT, _csp


def test_online_rewrite_is_byok_not_project_default():
    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")

    assert "online (BYOK)" in html
    assert 'id="ai-provider"' in html
    assert 'id="ai-key"' in html
    assert 'sessionStorage.setItem(aiStore("key")' in html
    assert "legislativ-rescrieri.cn-webify.workers.dev" not in html


def test_static_csp_allows_only_named_byok_destinations():
    csp = _csp()

    assert "https://api.openai.com" in csp
    assert "https://api.anthropic.com" in csp
    assert "https://*.workers.dev" in csp
    assert "connect-src 'self'" in csp
