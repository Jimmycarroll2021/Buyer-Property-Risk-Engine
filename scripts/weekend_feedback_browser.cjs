// Run against a disposable sample preview; saves one fictional worksheet for replay/print checks.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base=process.env.UAT_URL || 'http://127.0.0.1:8145';
const out=process.env.UAT_OUTPUT || 'runtime/final-feedback-browser';
fs.mkdirSync(out,{recursive:true});
const receipts=[], errors=[];
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const p=await browser.newPage({locale:'en-AU',viewport:{width:1360,height:1000}});
  p.on('pageerror',e=>errors.push(e.message));
  const ready=()=>p.waitForFunction(()=>!document.querySelector('#inputs').disabled);
  async function record(label){
   receipts.push({label,status:await p.locator('#status-pill').innerText(),action:await p.locator('#action').innerText(),metrics:await p.locator('#metrics').innerText(),bid:await p.locator('#bid').innerText(),works:await p.locator('#works-status').innerText()});
   fs.writeFileSync(path.join(out,'receipts.json'),JSON.stringify(receipts,null,2));
  }
  async function select(id){await ready();await p.locator('#example').selectOption(id);await ready();await p.locator('#outcome').waitFor({state:'visible'});}
  async function calc(values={}){
   for(const [k,v] of Object.entries(values))await p.locator('#'+k).fill(String(v));
   await p.locator('#calculate').click();await ready();await p.locator('#outcome').waitFor({state:'visible'});
  }
  await p.goto(base+'/weekend');await ready();
  assert.equal(await p.locator('#example option').count(),5);
  await record('Ngunnawal original');
  assert.match(await p.locator('#bid-head').innerText(),/Search stopped at AUD\s*1,100,000\.00; higher offers untested/);
  assert.match(await p.locator('#bid').innerText(),/Green and Amber both qualify/);
  await p.locator('#first_year_works').fill('');
  assert.match(await p.locator('#works-status').innerText(),/unknown.*does not mean zero/);
  await calc();assert.equal(await p.locator('#status-pill').innerText(),'Unresolved');await record('Ngunnawal unknown works');
  await calc({purchase_price:740000,cash_before_settlement:310000,first_year_works:40000});
  assert.equal(await p.locator('#status-pill').innerText(),'Red');
  assert.match(await p.locator('#metrics').innerText(),/-AUD\s*11,000\.00/);
  assert.match(await p.locator('#bid-reason').innerText(),/600,000\.00.*AUD -7,500\.00 available.*11,157\.30 required/);
  await record('Ngunnawal revised');
  await select('weston-family');
  assert.match(await p.locator('#action').innerText(),/Disability cover shortfall AUD\s*15,000\.00.*insurer/);
  await record('Weston original');await p.screenshot({path:path.join(out,'weston.png')});
  await calc({purchase_price:740000});assert.equal(await p.locator('#status-pill').innerText(),'Green');await record('Weston offer only');
  await calc({cash_before_settlement:342000,first_year_works:6500});assert.equal(await p.locator('#status-pill').innerText(),'Green');await record('Weston final');
  await select('kambah-repairs');await record('Kambah original');
  await calc({purchase_price:580000});assert.equal(await p.locator('#status-pill').innerText(),'Amber');await record('Kambah 580000');
  await calc({purchase_price:585000});assert.equal(await p.locator('#status-pill').innerText(),'Red');await record('Kambah 585000');
  await calc({purchase_price:550000,cash_before_settlement:210000,first_year_works:48000});
  assert.equal(await p.locator('#status-pill').innerText(),'Amber');assert.match(await p.locator('#works-status').innerText(),/38,000\.00.*10,000\.00/);
  assert.match(await p.locator('#bid').innerText(),/720,000\.00.*725,000\.00/s);await record('Kambah revised');await p.screenshot({path:path.join(out,'kambah.png')});
  await p.locator('#first_year_works').fill('37000');
  assert.equal(await p.locator('#first_year_works').evaluate(x=>x.checkValidity()),false);
  assert.match(await p.locator('#works-status').innerText(),/at least AUD\s*38,000\.00/);
  await calc({first_year_works:48000});
  await select('belconnen-single');assert.equal(await p.locator('#status-pill').innerText(),'Red');await record('Belconnen original');
  await p.locator('#evidence-inputs summary').click();
  assert.match(await p.locator('#illiquid-help').innerText(),/15%.*10%.*not sourced market predictions/);
  assert.match(await p.locator('#storms').innerText(),/Cash immediately before sale/);
  assert.match(await p.locator('#storms').innerText(),/cash after sale already funds that shortfall; do not subtract it again/);
  await p.locator('#illiquid').selectOption('false');await calc();
  assert.equal(await p.locator('#status-pill').innerText(),'Red');
  assert.match(await p.locator('#storms').innerText(),/66,309\.33/);await record('Belconnen resale No');
  await p.locator('#illiquid').selectOption('true');
  await calc({purchase_price:450000,cash_before_settlement:160000,first_year_works:9000});
  assert.equal(await p.locator('#status-pill').innerText(),'Amber');
  assert.match(await p.locator('#storms').innerText(),/142,269\.50/);await record('Belconnen revised');
  await p.screenshot({path:path.join(out,'belconnen.png')});
  await select('braddon-downsizers');assert.equal(await p.locator('#status-pill').innerText(),'Unresolved');await record('Braddon sibling');
  assert.match(await p.locator('#vetoes').innerText(),/Cash and income calculations can be known while a property check is unresolved/);
  await calc({purchase_price:635000,cash_before_settlement:411000,first_year_works:7000});
  assert.equal(await p.locator('#status-pill').innerText(),'Unresolved');
  assert.match(await p.locator('#metrics').innerText(),/112,625\.00/);await record('Braddon revised unresolved');
  await p.locator('#structural_clear').selectOption('false');await calc();
  assert.equal(await p.locator('#status-pill').innerText(),'Red');
  assert.match(await p.locator('#bid-reason').innerText(),/V1 is red at every price/);await record('Braddon structural No');
  await p.locator('#structural_clear').selectOption('true');await calc({purchase_price:640000,cash_before_settlement:400000,first_year_works:10000});
  assert.equal(await p.locator('#status-pill').innerText(),'Green');await record('Braddon evidence cleared');
  assert.match(await p.locator('#bid-head').innerText(),/Search stopped at AUD\s*820,000\.00; higher offers untested/);
  await p.screenshot({path:path.join(out,'braddon.png')});
  await p.locator('#save').click();await p.waitForFunction(()=>document.querySelector('#save-notice').textContent.includes('Saved version 1.'));await ready();
  await p.locator('#replay').click();await p.waitForFunction(()=>document.querySelector('#save-notice').textContent.includes('Exact replay.'));await ready();
  const popup=p.waitForEvent('popup');await p.locator('#print').click();const report=await popup;
  await report.waitForFunction(()=>document.body.innerText.includes('Total first-year works, including urgent works:'));
  const printText=await report.locator('body').innerText();
  assert.match(printText,/Green and Amber both qualify/);
  assert.match(printText,/Search stopped at AUD 820,000.00; higher offers untested/);
  assert.match(printText,/Cash immediately before sale:/);
  assert.match(printText,/do not subtract it again/);
  assert.match(printText,/Cash and income calculations can be known/);await report.close();await ready();
  // Delay a real response: old output must disappear and the picker must be disabled.
  await select('weston-family');let release, started;
  const gate=new Promise(r=>release=r), entered=new Promise(r=>started=r);
  await p.route('**/v1/weekend/preview',async route=>{started();await gate;await route.continue();},{times:1});
  await p.locator('#purchase_price').fill('740000');await p.locator('#calculate').click();await entered;
  assert.equal(await p.locator('#outcome').isVisible(),false);
  assert.equal(await p.locator('#example').isDisabled(),true);
  assert.match(await p.locator('#notice').innerText(),/Testing Sam and Asha at AUD\s*740,000\.00/);
  release();await ready();assert.match(await p.locator('#metrics').innerText(),/740,000\.00/);
  // Even an input event injected while controls are disabled invalidates the in-flight result.
  let releaseStale,startedStale;const staleGate=new Promise(r=>releaseStale=r),staleEntered=new Promise(r=>startedStale=r);
  await p.route('**/v1/weekend/preview',async route=>{startedStale();await staleGate;await route.continue();},{times:1});
  await p.locator('#calculate').click();await staleEntered;
  await p.locator('#purchase_price').evaluate(x=>{x.value='735000';x.dispatchEvent(new Event('input',{bubbles:true}));});
  releaseStale();await ready();assert.equal(await p.locator('#outcome').isVisible(),false);
  assert.match(await p.locator('#notice').innerText(),/Inputs changed while testing/);await calc();assert.match(await p.locator('#metrics').innerText(),/735,000\.00/);
  await p.route('**/v1/weekend/preview',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Synthetic preview unavailable'})}),{times:1});
  await p.locator('#calculate').click();await ready();assert.equal(await p.locator('#outcome').isVisible(),false);
  assert.match(await p.locator('#notice').innerText(),/Synthetic preview unavailable/);
  await calc();await record('Recovered after delayed stale and failed responses');
  await p.setViewportSize({width:390,height:844});assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth),390);
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'summary.json'),JSON.stringify({status:'pass',recorded_runs:receipts.length,errors,checks:['five persona journeys','five household picker paths','Belconnen resale assumption and sale cash','Braddon unknown No Yes','explicit untested endpoint heading','total subset validation','unknown inline','Amber eligibility','specific disability headline','grid reason price context','save replay print','delayed response hides output','disabled picker during request','stale response rejected','503 recovery','mobile width']},null,2));
  console.log('PASS: '+receipts.length+' recorded runs; delayed/stale/error/recovery, save/replay/print, mobile');
 }finally{await browser.close();}
})().catch(error=>{fs.writeFileSync(path.join(out,'failure.txt'),error.stack);console.error(error);process.exitCode=1;});
