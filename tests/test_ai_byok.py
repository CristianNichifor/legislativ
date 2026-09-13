"""Static checks for the browser AI boundary."""

from urllib.parse import urlparse

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
    assert 'id="ai-contract"' in html
    assert "ai-byok-settings-v1" in html
    assert "fără furnizor plătit al platformei" in html
    assert 'sessionStorage.setItem(aiStore("key")' in html
    assert "legislativ-rescrieri.cn-webify.workers.dev" not in html


def test_static_csp_allows_only_named_byok_destinations():
    surse = _csp_directive("connect-src")
    origini = set()
    for sursa in surse:
        parsed = urlparse(sursa)
        if parsed.scheme:
            origini.add((parsed.scheme, parsed.netloc, parsed.path))

    assert ("https", "api.openai.com", "") in origini
    assert ("https", "api.anthropic.com", "") in origini
    assert ("https", "*.workers.dev", "") in origini
    assert "'self'" in surse


def test_browser_byok_settings_contract_persists_no_secret():
    import shutil
    import subprocess

    if not shutil.which("node"):
        return

    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    source = html.split("const MODELE_ONLINE=", 1)[1].split("let _onlineOk=", 1)[0]
    program = (
        "const assert=require('node:assert/strict');"
        "const localStore=new Map([['ai_mode','online'],['ai_provider','openai'],"
        "['ai_model','Qwen-test'],['ai_model_online_openai','gpt-test'],"
        "['ai_endpoint_openai','https://api.openai.test/v1/chat/completions']]);"
        "const sessionStore=new Map([['ai_key_openai','SECRET-KEY']]);"
        "const localStorage={getItem:k=>localStore.has(k)?localStore.get(k):null,"
        "setItem:(k,v)=>localStore.set(k,String(v))};"
        "const sessionStorage={getItem:k=>sessionStore.has(k)?sessionStore.get(k):null,"
        "setItem:(k,v)=>sessionStore.set(k,String(v))};"
        "const MODELE=[{id:'Qwen-test'}];"
        "function esc(s){return String(s).replace(/[&<>\"']/g,c=>"
        "({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}"
        "const MODELE_ONLINE=" + source + "const s=aiSettings();"
        "assert.equal(s.contract,'ai-byok-settings-v1');"
        "assert.equal(s.mode,'online');"
        "assert.equal(s.default_ai,'off');"
        "assert.equal(s.platform_paid_default,false);"
        "assert.equal(s.app_paid_provider,false);"
        "assert.equal(s.stores_api_key,false);"
        "assert.equal(s.online_byok.provider,'openai');"
        "assert.equal(s.online_byok.model,'gpt-test');"
        "assert.equal(s.online_byok.api_key_present,true);"
        "assert.equal(s.key_storage,'sessionStorage_only');"
        "assert.equal(s.cost_warning.server_cost,'none');"
        "assert.equal(s.cost_warning.token_estimate_required_before_send,true);"
        "assert.equal(s.drafting_guardrail.state,'evidence_only_draft_unreviewed');"
        "assert.equal(s.drafting_guardrail.evidence_required,true);"
        "assert.equal(s.drafting_guardrail.may_invent_sources,false);"
        "const persisted=aiSettingsPersist();"
        "const raw=localStore.get(AI_SETTINGS_KEY);"
        "assert.equal(persisted.contract,'ai-byok-settings-v1');"
        "assert.equal(persisted.stores_api_key,false);"
        "assert.ok(!raw.includes('SECRET-KEY'));"
        "assert.ok(!JSON.stringify(persisted).includes('SECRET-KEY'));"
        "assert.ok(aiSettingsStatusHtml(s).includes('fără furnizor plătit al platformei'));"
        "const note=aiNoteSettings();"
        "assert.equal(note.platform_paid_default,false);"
        "assert.equal(note.stores_api_key,false);"
        "const summary=aiNoteSettingsSummaryHtml({...note,boundary:'online_byok'});"
        "assert.ok(summary.includes('Cost: server zero'));"
        "assert.ok(summary.includes('Ciornă AI nerevizuită'));"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True, timeout=10)
