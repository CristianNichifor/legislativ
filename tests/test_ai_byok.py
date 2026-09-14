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


def test_browser_byok_requests_are_timeout_bound_and_secret_safe():
    import shutil
    import subprocess

    if not shutil.which("node"):
        return

    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    source = (
        "let _onlineOk=false;"
        + html.split("let _onlineOk=false;", 1)[1].split(
            "// the single door every rewrite goes through", 1
        )[0]
    )
    program = (
        "const assert=require('node:assert/strict');"
        "let timerMs=null,clearCalled=false;"
        "globalThis.setTimeout=(fn,ms)=>{timerMs=ms;return 1;};"
        "globalThis.clearTimeout=(id)=>{clearCalled=id===1;};"
        "class AbortController{constructor(){this.signal={aborted:false};}"
        "abort(reason){this.signal.aborted=true;this.signal.reason=reason;}}"
        "globalThis.AbortController=AbortController;"
        "globalThis.fetch=async(ep,init)=>{assert.equal(timerMs,9000);"
        "assert.ok(init.signal);throw Object.assign(new Error('SECRET fetch failed'),"
        "{name:'AbortError'});};"
        + source
        + "(async()=>{try{await aiJson('https://api.openai.test',{method:'POST'},"
        "{timeout_ms:9000});assert.fail('expected timeout');}catch(err){"
        "assert.equal(err.code,'AI_BYOK_TIMEOUT');"
        "assert.equal(err.name,'AbortError');"
        "assert.equal(err.timeout_ms,9000);"
        "assert.ok(!err.message.includes('SECRET'));"
        "assert.equal(clearCalled,true);}})().catch(e=>{console.error(e);process.exit(1);});"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True, timeout=10)


def test_browser_byok_provider_calls_use_user_key_and_timeout_signal():
    import shutil
    import subprocess

    if not shutil.which("node"):
        return

    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    source = (
        "let _onlineOk=false;"
        + html.split("let _onlineOk=false;", 1)[1].split(
            "// the single door every rewrite goes through", 1
        )[0]
    )
    program = (
        "const assert=require('node:assert/strict');"
        "const calls=[];"
        "globalThis.setTimeout=()=>1;globalThis.clearTimeout=()=>{};"
        "class AbortController{constructor(){this.signal={aborted:false};}"
        "abort(){this.signal.aborted=true;}}"
        "globalThis.AbortController=AbortController;"
        "globalThis.fetch=async(ep,init)=>{calls.push({ep,init});"
        "return {ok:true,status:200,text:async()=>JSON.stringify({choices:[{message:"
        "{content:'ok'}}],"
        "content:[{type:'text',text:'ok'}]})};};"
        "let provider='openai';"
        "function aiProvider(){return provider;}"
        "function aiProv(p){return {openai:{et:'OpenAI',cheie:true},"
        "anthropic:{et:'Anthropic',cheie:true}}[p||provider];}"
        "function aiEndpoint(p){return p==='anthropic'?'https://api.anthropic.test/v1/messages':"
        "'https://api.openai.test/v1/chat/completions';}"
        "function aiModelOnline(p){return p==='anthropic'?'claude-test':'gpt-test';}"
        "function aiKey(){return 'SECRET-USER-KEY';}"
        + source
        + "(async()=>{await aiRescrieOnline('text','system','nou',{timeout_ms:12000});"
        "provider='anthropic';await aiRescrieOnline('text','system','nou',{timeout_ms:12000});"
        "const openai=calls[0],anthropic=calls[1];"
        "assert.equal(openai.ep,'https://api.openai.test/v1/chat/completions');"
        "assert.equal(openai.init.headers.Authorization,'Bearer SECRET-USER-KEY');"
        "assert.ok(openai.init.signal);"
        "assert.deepEqual(JSON.parse(openai.init.body).messages.map(m=>m.role),['system','user']);"
        "assert.equal(anthropic.ep,'https://api.anthropic.test/v1/messages');"
        "assert.equal(anthropic.init.headers['x-api-key'],'SECRET-USER-KEY');"
        "assert.equal(anthropic.init.headers['anthropic-version'],'2023-06-01');"
        "assert.ok(anthropic.init.signal);"
        "assert.equal(JSON.parse(anthropic.init.body).model,'claude-test');"
        "})().catch(e=>{console.error(e);process.exit(1);});"
    )
    subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True, timeout=10)
