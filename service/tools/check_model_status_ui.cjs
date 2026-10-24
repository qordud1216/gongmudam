/* Use only an isolated installation. Actual model checks use synthetic text. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const [base,out]=process.argv.slice(2);
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||'')||['8766','8767'].includes(new URL(base).port)||!out)throw Error('Use isolated-loopback-url output-dir');
const output=path.resolve(out);fs.mkdirSync(output,{recursive:true});
const report={base,synthetic_only:true,checks:[],actual_response_checks:[]};
function gate(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
async function main(){
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
 context.on('page',p=>p.on('pageerror',e=>errors.push(e.message)));page.on('pageerror',e=>errors.push(e.message));
 let posts=0;context.on('request',r=>{if(r.method()==='POST'&&(r.url().endsWith('/api/workspace/model-check')||r.url().endsWith('/api/settings/llm/test')))posts++});
 const full=page.locator('#view-settings [data-model-status=full]');
 const record=name=>report.checks.push({name,passed:true});
 async function api(method,url,data){const r=await page.request.fetch(base+url,{method,data});assert.ok(r.ok(),await r.text());return r.json()}
 const original=(await api('GET','/api/settings')).llm.active;
 async function switchTo(profile){
  const card=page.locator('.profileCard').filter({has:page.locator('b',{hasText:new RegExp('^'+profile+'$')})});
  const use=card.locator('.pUse');if(await use.count())await use.click();
  await full.locator('.ms-head').filter({hasText:profile+' · '}).waitFor();
  await page.waitForFunction(name=>[...document.querySelectorAll('.profileCard.active')].some(c=>c.dataset.name===name),profile);
 }
 async function actualCheck(model,selector=full.locator('.ms-check')){
  const [r]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST'&&r.url()===base+'/api/workspace/model-check',{timeout:75000}),selector.click()]);
  assert.equal(r.status(),200);const result=await r.json();assert.equal(result.response.state,'verified');assert.equal(result.response.response_model,model);
  await full.getByText('최근 시험 응답 확인',{exact:true}).waitFor({timeout:75000});
  await full.getByText('서버가 보고한 응답 모델: '+model,{exact:true}).waitFor();
  report.actual_response_checks.push({model,...result.response});
 }
 let start;
 try{
  await api('PUT','/api/settings/llm',{active:'offline'});
  await page.goto(base+'/index.html?v=48#settings');await page.locator('.profileCard[data-name=local_gemma] .pUse').waitFor();
  assert.equal(await page.locator('.profileCard[data-name=offline] .pTest').count(),0);await full.getByText('오프라인 안내',{exact:true}).waitFor();assert.ok(await full.locator('.ms-check').isDisabled());
  let before=posts;await switchTo('local_gemma');await full.getByText('서버 연결됨 · 모델 확인',{exact:true}).waitFor();assert.equal(posts,before);await full.getByText('시험 응답 미확인',{exact:true}).waitFor();
  await actualCheck('gemma3:4b');await full.screenshot({path:path.join(output,'gemma-verified.png')});
  record('offline settings render; switch Gemma only discovers until explicit real check');

  const workspaceStatus=await api('GET','/api/workspace/status');
  const expectedSourceCount=workspaceStatus?.resources?.knowledge_sources;
  assert.ok(Number.isInteger(expectedSourceCount)&&expectedSourceCount>=25,`Expected at least 25 knowledge sources, received ${expectedSourceCount}`);
  report.source_count=expectedSourceCount;
  start=await context.newPage();await start.goto(base+'/start.html?v=48');await start.locator('#start-quick-status').filter({hasText:'local_gemma'}).waitFor();await start.locator('#start-quick-status').filter({hasText:`${expectedSourceCount}개`}).waitFor();
  before=posts;const old=await api('GET','/api/workspace/model-status'),hold=gate(),entered=gate(),delivered=gate();let first=true;
  await start.route('**/api/workspace/model-status',async route=>{if(first){first=false;entered.resolve();await hold.promise;await route.fulfill({json:old});delivered.resolve()}else await route.continue()});
  await start.evaluate(()=>void window.SeomuModelStatus.refresh());await entered.promise;
  await switchTo('local_llama');await start.locator('#start-quick-status').filter({hasText:'local_llama'}).waitFor();await start.locator('#start-quick-status').filter({hasText:'시험 응답 미확인'}).waitFor();hold.resolve();
  await delivered.promise;await start.unroute('**/api/workspace/model-status');assert.equal(posts,before);assert.ok(!(await start.locator('#start-quick-status').textContent()).includes('local_gemma'));
  const activeTest=page.locator('.profileCard[data-name=local_llama] .pTest');await actualCheck('llama3.2:3b',activeTest);await page.locator('.profileCard[data-name=local_llama] .pMsg').filter({hasText:'최근 시험 응답 확인'}).waitFor();
  await start.locator('#start-environment>summary').click();await start.locator('#refresh-start').click();await start.locator('#start-quick-status').filter({hasText:'최근 시험 응답 확인'}).waitFor();await full.screenshot({path:path.join(output,'llama-verified.png')});
  record('switch Llama updates another tab; late Gemma metadata discarded; active-card real test is shared');

  await switchTo('local_gemma');await full.getByText('시험 응답 미확인',{exact:true}).waitFor();
  const held=gate(),committed=gate();let once=true;
  await page.route('**/api/workspace/model-check',async route=>{if(once){once=false;const response=await route.fetch({timeout:75000});committed.resolve();await held.promise;await route.fulfill({response})}else await route.continue()});
  await full.locator('.ms-check').click();await committed.promise;await switchTo('local_llama');await full.getByText('시험 응답 미확인',{exact:true}).waitFor();held.resolve();
  await page.waitForFunction(()=>!document.querySelector('#view-settings .ms-check').disabled);await page.unroute('**/api/workspace/model-check');
  assert.ok((await full.locator('.ms-head').textContent()).includes('local_llama'));assert.equal(await full.getByText('최근 시험 응답 확인',{exact:true}).count(),0);
  record('old real completion delivered after model switch cannot mark the new model verified');

  // Selected metadata and unavailable states are real API outcomes, not UI fixtures.
  await switchTo('status-v48-missing');await full.getByText('선택 모델 없음',{exact:true}).waitFor();assert.equal(await full.getByText('최근 시험 응답 확인',{exact:true}).count(),0);
  await switchTo('status-v48-unavailable');await full.getByText('서버 연결 실패',{exact:true}).waitFor();
  await switchTo('status-v48-external');await full.getByText('외부 모델',{exact:true}).waitFor();assert.ok(await full.locator('.ms-check').isDisabled());
  await switchTo('offline');await full.getByText('오프라인 안내',{exact:true}).waitFor();
  record('missing selected model, unavailable local server, external profile and offline are distinct');

  // The old card must never initiate a test of a different, newly active model.
  await switchTo('local_gemma');const oldClick=await page.locator('.profileCard[data-name=local_gemma] .pTest').evaluateHandle(button=>button.onclick);
  before=posts;await api('PUT','/api/settings/llm',{active:'local_llama'});await page.evaluate(()=>window.SeomuModelStatus.changed());
  await page.waitForFunction(()=>document.querySelector('.profileCard.active')?.dataset.name==='local_llama');await oldClick.evaluate(fn=>fn());assert.equal(posts,before);
  record('stale active-card handler does not test the newly selected model');

  // Fail then recover: a successful display must not remain during a status outage.
  await start.route('**/api/workspace/model-status',route=>route.fulfill({status:503,json:{detail:'synthetic outage'}}));await start.evaluate(()=>window.SeomuModelStatus.refresh());
  await start.locator('#start-quick-status').filter({hasText:'선택 모델 상태 확인 불가'}).waitFor();assert.ok(!(await start.locator('#start-quick-status').textContent()).includes('최근 시험 응답 확인'));
  await start.unroute('**/api/workspace/model-status');await start.evaluate(()=>window.SeomuModelStatus.refresh());await start.locator('#start-quick-status').filter({hasText:'local_llama'}).waitFor();
  record('status outage clears old success; recovered fetch restores selected identity');

  before=posts;let attempts=0;const valid=await api('GET','/api/workspace/model-status');
  await page.route('**/api/workspace/model-status',route=>{attempts++;return route.fulfill(attempts===1?{status:409,json:{detail:{code:'selection_changed',message:'changed'}}}:{json:valid})});
  await page.evaluate(()=>window.SeomuModelStatus.refresh());assert.equal(attempts,2);assert.equal(posts,before);await page.unroute('**/api/workspace/model-status');
  record('selection-changed discovery retries once without generating text');

  // A late settings payload must not repaint the former active profile.
  await switchTo('local_gemma');const oldSettings=await api('GET','/api/settings'),settingsHold=gate(),settingsEntered=gate(),settingsDelivered=gate();let oldFirst=true;
  await page.route('**/api/settings',async route=>{if(oldFirst){oldFirst=false;settingsEntered.resolve();await settingsHold.promise;await route.fulfill({json:oldSettings});settingsDelivered.resolve()}else await route.continue()});
  await page.evaluate(()=>void renderSettings());await settingsEntered.promise;
  await api('PUT','/api/settings/llm',{active:'local_llama'});await page.evaluate(()=>window.SeomuModelStatus.changed());
  await page.waitForFunction(()=>document.querySelector('.profileCard.active')?.dataset.name==='local_llama');settingsHold.resolve();await settingsDelivered.promise;await page.unroute('**/api/settings');
  assert.equal(await page.evaluate(()=>S.settings.llm.active),'local_llama');assert.equal(await page.locator('.profileCard.active').getAttribute('data-name'),'local_llama');
  record('late settings response cannot restore a former active card');

  let testedProfile;await page.route('**/api/settings/llm/test',route=>{testedProfile=route.request().postDataJSON().profile;return route.fulfill({json:{ok:true,message:'synthetic profile response'}})});
  await page.locator('.profileCard[data-name=local_gemma] .pTest').click();await page.locator('.profileCard[data-name=local_gemma] .pMsg').filter({hasText:'이 프로필 시험 결과: synthetic profile response'}).waitFor();
  assert.equal(testedProfile,'local_gemma');assert.ok((await full.locator('.ms-head').textContent()).includes('local_llama'));await page.unroute('**/api/settings/llm/test');
  record('unselected profile test keeps its result separate from selected model evidence');

  before=posts;const preparingHold=gate(),preparingEntered=gate(),preparingDone=gate(),preparingOld=await api('GET','/api/workspace/model-status');let preparingFirst=true;
  await page.route('**/api/workspace/model-status',async route=>{if(preparingFirst){preparingFirst=false;preparingEntered.resolve();await preparingHold.promise;await route.fulfill({json:preparingOld});preparingDone.resolve()}else await route.continue()});
  await full.locator('.ms-check').click();await preparingEntered.promise;
  await api('PUT','/api/settings/llm',{active:'local_gemma'});await page.evaluate(()=>window.SeomuModelStatus.changed());await full.locator('.ms-head').filter({hasText:'local_gemma'}).waitFor();
  preparingHold.resolve();await preparingDone.promise;await page.waitForFunction(()=>!document.querySelector('#view-settings .ms-check').disabled);await page.unroute('**/api/workspace/model-status');assert.equal(posts,before);
  record('switch during check preparation does not generate with the new selection automatically');

  await page.evaluate(()=>Object.defineProperty(window,'localStorage',{configurable:true,get(){throw Error('Synthetic storage denial')}}));
  await switchTo('offline');await full.getByText('오프라인 안내',{exact:true}).waitFor();await start.evaluate(()=>window.dispatchEvent(new Event('focus')));await start.locator('#start-quick-status').filter({hasText:'offline'}).waitFor();
  record('storage denial still updates local display and other tab on focus');
  for(const width of [390,760]){
   await page.setViewportSize({width,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await start.setViewportSize({width,height:900});assert.ok(await start.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  }
  await page.setViewportSize({width:390,height:900});await full.screenshot({path:path.join(output,'mobile-model-status.png')});
  assert.deepEqual(errors,[]);record('390/760px settings/start layout; no browser script errors');report.passed=true;
 }catch(error){report.failure={message:error.message,url:page.url()};await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error}
 finally{
  await api('PUT','/api/settings/llm',{active:original});report.restored_profile=original;report.page_errors=errors;
  fs.writeFileSync(path.join(output,'model-status-ui.json'),JSON.stringify(report,null,2));await browser.close();
 }
 console.log(JSON.stringify({passed:report.passed,checks:report.checks,actual_response_checks:report.actual_response_checks},null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1});


