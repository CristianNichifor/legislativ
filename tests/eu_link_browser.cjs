const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),base=process.env.EU_LINK_BASE_URL||'http://127.0.0.1:8043';
(async()=>{
  const browser=await chromium.launch({headless:true});
  try{for(const width of [1280,390]){
    const seed=JSON.parse(execFileSync('uv',['run','python','-m','tests.eu_link_fixture'],{cwd:root,encoding:'utf8'}));
    const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base);await page.click('#tab-matrice');
    await page.locator('#dossier-library > summary').click();
    await page.selectOption('#dossier-select',seed.id);await page.selectOption('#dossier-run-select',seed.run);
    await page.locator('[data-proposal] > summary').click().catch(async err=>{
      console.error(errors,await page.locator('#dossier-saved').innerText());throw err;
    });
    const section=page.locator('[data-eu-proposal-links]');await section.locator('summary').first().click();
    const field=k=>section.locator(`[data-eu-link-field=${k}]`),button=k=>section.locator(`[data-eu-link-${k}]`);
    await field('celex').fill('32014L0024');await button('sources').click();
    await button('preview').click();await button('preview-result').filter({hasText:'missing_text'}).waitFor();
    assert.ok(await button('confirm').isDisabled());
    assert.ok((await button('preview-result').innerText()).includes('missing_text'));
    await field('celex').fill('32018R1805');await button('sources').click();
    await field('instantanee').selectOption(seed.snapshot);await field('locator').selectOption('art1');
    await field('celex').fill('32014L0024');
    assert.equal(await field('instantanee').locator('option').count(),1);
    assert.equal(await field('locator').locator('option').count(),1);
    await field('celex').fill('32018R1805');await button('sources').click();
    await field('instantanee').selectOption(seed.snapshot);await field('locator').selectOption('art1');
    await button('preview').click();await page.waitForFunction(()=>!document.querySelector('[data-eu-link-confirm]').disabled);
    await field('autor').fill('Fixture author <img>');await field('obligatie').fill('Obligatie UE de test.');
    await field('motiv').fill('Potential coverage, fixture only');
    assert.equal(await page.evaluate(()=>{const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented;}),true);
    let lost=false;const ids=[];
    await page.route('**/api/dosare/propuneri/legaturi-ue',async route=>{
      if(route.request().method()!=='POST')return route.continue();
      ids.push(route.request().postDataJSON().id);
      if(!lost){lost=true;const response=await route.fetch();assert.ok(response.ok());await route.abort();}
      else await route.continue();
    });
    await button('confirm').click();await button('status').filter({hasText:/fetch|Failed|Network/i}).waitFor();
    await button('confirm').click();await button('saved-result').filter({hasText:'Ipoteză salvată'}).waitFor();
    assert.equal(ids.length,2);assert.equal(ids[0],ids[1]);assert.equal(await section.locator('img').count(),0);
    assert.ok(await button('confirm').isDisabled());
    const download=page.waitForEvent('download');await section.locator('[data-eu-link-export=json]').click();
    const result=JSON.parse(fs.readFileSync(await(await download).path(),'utf8'));
    assert.equal(result.baza.selection.revizie,1);assert.equal(result.baza.eu_snapshot.id,seed.snapshot);
    assert.equal(result.substantive_candidate.autor,'Fixture author <img>');
    assert.ok(result.baza.proposal.interventie.tinta.text.includes('National fixture'));
    // Add another immutable link and select the older one explicitly.
    await field('motiv').fill('Second hypothesis');await button('confirm').click();
    await page.waitForFunction(()=>document.querySelectorAll('[data-eu-link-history] option').length===3);
    await button('history').selectOption(ids[0]);
    await page.waitForFunction(id=>document.querySelector('[data-eu-link-history]').value===id,ids[0]);
    await button('saved-result').filter({hasText:'Potential coverage, fixture only'}).waitFor();
    // Remounting the same host and ordinary review reloads must leave exactly one EU panel.
    await page.evaluate(identity=>{
      const state=EU_LINK_VIEWS.get(JSON.stringify(identity));
      bindEuProposalLinks(document.querySelector('[data-proposal-editor]'),{},state.saved.baza.proposal,identity,()=>true);
    },{dosar_id:seed.id,rulare_id:seed.run,constatare_id:seed.finding});
    assert.equal(await page.locator('[data-eu-proposal-links]').count(),1);
    const previousSection=await section.elementHandle();
    await page.click('[data-review-refresh]');
    await page.waitForFunction(el=>!el.isConnected,previousSection);
    await page.waitForLoadState('networkidle');await section.waitFor();
    assert.equal(await page.locator('[data-eu-proposal-links]').count(),1);
    const proposalForm=page.locator('[data-proposal-editor] > form');
    await proposalForm.locator('[name=titlu]').fill('Fixture revised title');
    await proposalForm.locator('[type=submit]').click();
    await page.waitForLoadState('networkidle');
    await section.locator('[data-eu-link-revision-label]').filter({hasText:'disponibilă: 2'}).waitFor();
    assert.equal(await page.locator('[data-eu-proposal-links]').count(),1);
    assert.equal(await field('revizie').inputValue(),'1');
    await field('revizie').fill('2');await field('revizie').press('Tab');
    await button('saved-result').filter({hasText:'Nicio bază'}).waitFor();
    assert.ok(await section.locator('[data-eu-link-export=json]').isDisabled());
    await button('cancel').click();
    await section.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,`.eu-link-fixture/eu-link-${width}.png`)});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    assert.deepEqual(errors,[]);
    console.log(`${width}: blockers, selectors, save/retry, history/export, remount/reload/save isolation, unload warning and layout passed`);
    await page.close();
  }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
