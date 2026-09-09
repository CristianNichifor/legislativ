"""Static checks for the browser AI boundary."""

from scripts.construieste_web import ROOT, _csp


def _csp_directive(name: str) -> set[str]:
    for directive in _csp().split(";"):
        tokens = directive.strip().split()
        if tokens and tokens[0] == name:
            return set(tokens[1:])
    return set()


def test_online_rewrite_is_byok_not_project_default():
    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")

    assert "online (BYOK)" in html
    assert 'id="ai-provider"' in html
    assert 'id="ai-key"' in html
    assert 'sessionStorage.setItem(aiStore("key")' in html
    assert "legislativ-rescrieri.cn-webify.workers.dev" not in html


def test_static_csp_allows_only_named_byok_destinations():
    surse = _csp_directive("connect-src")

    assert "https://api.openai.com" in surse
    assert "https://api.anthropic.com" in surse
    assert "https://*.workers.dev" in surse
    assert "'self'" in surse
