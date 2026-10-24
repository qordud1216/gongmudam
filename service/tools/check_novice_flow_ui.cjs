/* All business mutations go through the UI in an isolated synthetic installation. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const [base,output,python]=process.argv.slice(2);
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||'')||['8766','8767'].includes(new URL(base).port)||!output||!python)throw Error('Usage: isolated-loopback-url output-dir python.exe');
fs.mkdirSync(output,{recursive:true});
const result={base,synthetic_only:true,business_mutations:'UI only',model_inference_tested:false,checks:[]};
const check=name=>result.checks.push(name);
async function main(){
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 let asks=0,workflowWrites=0;
 page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/ask'))asks++;if(r.method()==='PATCH'&&r.url().endsWith('/workflow'))workflowWrites++;});
 async function ask(text){
  await page.goto(base+'/start.html');await page.locator('#start-question').fill(text);
  const before=asks;await page.locator('#start-ask').click();
  await page.locator('.task-followup button').waitFor();await page.waitForFunction(()=>!document.getElementById('askBtn').disabled);
  assert.equal(asks,before+1);assert.equal(await page.locator('.task-followup').count(),1);
  const geometry=await page.evaluate(()=>{const a=document.querySelector('.task-followup button').getBoundingClientRect(),b=document.getElementById('chatLog').getBoundingClientRect();return {visible:a.top>=b.top&&a.bottom<=b.bottom,top:a.top,bottom:a.bottom};});
  assert.ok(geometry.visible,JSON.stringify(geometry));return geometry;
 }
 async function download(selector,name){const pending=page.waitForEvent('download');await page.locator(selector).click();const d=await pending,target=path.join(output,name);await d.saveAs(target);assert.ok(fs.statSync(target).size>0);return target;}
 async function complete(){await page.locator('#workflow-confirm').check();const saved=page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().endsWith('/workflow'));await page.locator('[data-wf=complete]').click();assert.equal((await saved).status(),200);await page.locator('.flow-current .workflow-status.done').waitFor();}
 async function next(){const before=workflowWrites;await page.locator('[data-wf-next]').click();assert.equal(workflowWrites,before);assert.ok(await page.locator('.flow-current h3').evaluate(el=>document.activeElement===el));}
 async function jobData(id){return await (await page.request.get(base+'/api/adhoc/jobs/'+id)).json();}
 async function selectKind(id,kind){const data=await jobData(id),step=data.workflow.steps.find(s=>s.kind===kind);await page.locator(`[data-step="${step.id}"]`).click();return step;}
 try{
  const q='2026-10-21 세종에서 회의 참석 후 당일 복귀했어. 출장정산을 준비해줘.';
  result.cta=await ask(q);await page.screenshot({path:path.join(output,'chat-work-action.png')});
  await page.locator('.task-followup button').click();await page.waitForFunction(q=>document.getElementById('situation')?.value===q,q);
  await page.waitForFunction(()=>!document.getElementById('extract').disabled&&document.getElementById('extract-result').textContent.length>0);
  await page.locator('#organization').selectOption('national-general');
  for(const [id,value] of Object.entries({destination:'세종',purpose:'[합성 v53] 처음 사용 회의', 'start-date':'2026-10-21','end-date':'2026-10-21'}))await page.locator('#'+id).fill(value);
  await page.locator('#overnight').selectOption('false');
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/travel/cases')&&r.request().method()==='POST');
  await page.locator('#trip-form button[type=submit]').click();const trip=await (await saved).json();result.travel_id=trip.id;
  await page.locator('#case-workspace').waitFor({state:'visible'});assert.equal(new URL(page.url()).searchParams.get('case'),trip.id);assert.equal(new URL(page.url()).hash,'#settle');
  await page.reload();await page.locator('#case-workspace').waitFor({state:'visible'});assert.equal(await page.locator('#setup').isVisible(),false);assert.match(await page.locator('#case-title').innerText(),/처음 사용 회의/);assert.doesNotMatch(await page.locator('#message').innerText(),/30분|가져올 입력/);
  await page.screenshot({path:path.join(output,'saved-travel-refresh.png'),fullPage:true});
  check('one question → visible work action → exact handoff → saved case URL → refresh resumes same record');
  await page.locator('#journey-step-calculate').click();await page.locator('#calc-grade').selectOption('group2');await page.locator('#calc-scope').selectOption('inside');
  await page.locator('#calc-minutes').fill('240');await page.locator('#calc-km').fill('3');await page.locator('#calc-confirm').check();await page.locator('#calculate').click();
  await page.locator('#calculation-result').getByText('20,000원',{exact:false}).first().waitFor();
  assert.equal(new URL(page.url()).searchParams.get('case'),trip.id);
  await page.locator('#journey-step-draft').click();await page.locator('#draft').click();await page.locator('#draft-result a[href$="/csv"]').waitFor();await download('#draft-result a[href$="/csv"]','travel-preparation.csv');
  check('saved record → actual 20,000 KRW calculation → draft CSV through existing UI');
  const tabOpened=context.waitForEvent('page');await page.locator('#travel-tools [data-page=history]').click({modifiers:['Control']});const historyTab=await tabOpened;
  await historyTab.waitForLoadState('domcontentloaded');assert.equal(new URL(historyTab.url()).hash,'#history');assert.equal(new URL(page.url()).hash,'#settle');await historyTab.close();
  let historyReads=0;const countHistory=r=>{if(r.method()==='GET'&&new URL(r.url()).pathname==='/api/travel/cases')historyReads++;};page.on('request',countHistory);
  await page.locator('#travel-tools [data-page=history]').click();await page.locator(`.open-case[data-id="${trip.id}"]`).waitFor();assert.equal(historyReads,1);
  await page.goBack();assert.equal(new URL(page.url()).hash,'#settle');assert.ok(await page.locator('#page-settle').isVisible());page.off('request',countHistory);
  check('travel links preserve Ctrl-click and browser Back; normal history navigation makes one list request');
  await page.locator('#travel-tools [data-page=history]').click();await page.locator(`.open-case[data-id="${trip.id}"]`).click();
  await page.waitForURL(url=>url.hash==='#settle');
  assert.equal(new URL(page.url()).hash,'#settle');assert.equal(new URL(page.url()).searchParams.get('case'),trip.id);
  // Create the second case in the UI so this check does not depend on pre-existing records.
  await page.locator('#new-case').click();
  for(const [id,value] of Object.entries({destination:'부산',purpose:'[합성 v53] 이력 이동 확인','start-date':'2026-10-21','end-date':'2026-10-21'}))await page.locator('#'+id).fill(value);
  await page.locator('#overnight').selectOption('false');
  const savedOther=page.waitForResponse(r=>r.url().endsWith('/api/travel/cases')&&r.request().method()==='POST');await page.locator('#trip-form button[type=submit]').click();const otherResponse=await savedOther;assert.ok(otherResponse.ok());const otherId=(await otherResponse.json()).id;
  await page.waitForURL(url=>url.searchParams.get('case')===otherId);
  await page.locator('#travel-tools [data-page=history]').click();await page.locator(`.open-case[data-id="${trip.id}"]`).click();await page.waitForURL(url=>url.searchParams.get('case')===trip.id&&url.hash==='#settle');
  await page.locator('#travel-tools [data-page=history]').click();await page.locator(`.open-case[data-id="${otherId}"]`).click();
  await page.waitForURL(url=>url.searchParams.get('case')===otherId&&url.hash==='#settle');
  await page.goBack();await page.waitForFunction(id=>new URL(location.href).searchParams.get('case')===id&&state.current?.id===id,trip.id);assert.match(await page.locator('#case-title').innerText(),/처음 사용 회의/);
  await page.goForward();await page.waitForFunction(id=>new URL(location.href).searchParams.get('case')===id&&state.current?.id===id,otherId);
  await page.goBack();await page.waitForFunction(id=>new URL(location.href).searchParams.get('case')===id&&state.current?.id===id,trip.id);
  await page.reload();await page.locator('#case-workspace').waitFor({state:'visible'});
  await page.locator('#new-case').click();assert.equal(new URL(page.url()).searchParams.has('case'),false);
  for(const id of ['situation','destination','purpose','start-date','end-date'])assert.equal(await page.locator('#'+id).inputValue(),'');
  await page.reload();await page.locator('#organization option[value=national-general]').waitFor({state:'attached'});assert.ok(await page.locator('#setup').isVisible());assert.equal(await page.locator('#case-workspace').isVisible(),false);
  check('history and cross-case Back/Forward restore the matching record; explicit new clears ID/inputs without deleting saved work');

  const eq='각 부서 교육 희망자를 취합해줘. 교육명: 공공 AI 실무교육, 교육일: 2026-11-06, 회신 마감: 2026-10-30, 대상 부서: 총무팀, 안전팀.';
  await ask(eq);await page.locator('.task-followup button').click();await page.waitForFunction(q=>document.getElementById('situation')?.value===q,eq);
  for(const [id,value] of Object.entries({'job-title':'[합성 v53] 처음 사용 교육 취합',course:'공공 AI 실무교육','event-date':'2026-11-06',deadline:'2026-10-30',departments:'총무팀\n안전팀'}))await page.locator('#'+id).fill(value);
  await page.locator('#job-form button[type=submit]').click();await page.waitForURL(/#job-[a-f0-9]{32}$/);const job=new URL(page.url()).hash.slice(5);result.education_id=job;
  await page.locator('#workflow-confirm').waitFor();await complete();await page.locator('[data-wf-next]').waitFor();await page.screenshot({path:path.join(output,'education-next-at-completion.png'),fullPage:true});await next();assert.ok(await page.locator('#request-panel').isVisible());
  const template=await download('#template-link','education-template.xlsx');assert.match(await page.locator('#request-draft').inputValue(),/공공 AI 실무교육/);
  // The UI confirmation simulates a responsible person's review; no request is sent externally.
  await complete();await next();assert.ok(await page.locator('#upload-panel').isVisible());assert.equal(await page.locator('#workflow-confirm').isDisabled(),true);
  const reply=path.join(output,'synthetic-reply.xlsx');
  const fixture=spawnSync(python,['-c',"import sys;from openpyxl import load_workbook;w=load_workbook(sys.argv[1]);s=w['참석희망자'];s.delete_rows(2,s.max_row);s.append(['총무팀','가상참석자A','주무관','공공 AI 실무교육','2026-11-06','희망']);s.append(['총무팀','','주무관','공공 AI 실무교육','2026-11-06','희망']);w.save(sys.argv[2])",template,reply],{encoding:'utf8'});
  if(fixture.status!==0)throw Error(fixture.stderr);
  await page.locator('#reply-files').setInputFiles(reply);await page.locator('#upload-files').click();await page.locator('#upload-results').getByText('등록 완료',{exact:false}).waitFor();assert.equal(await page.locator('#workflow-confirm').isDisabled(),true);
  await page.locator('#empty-form').evaluate(el=>el.closest('details').open=true);await page.locator('#empty-department').selectOption('안전팀');await page.locator('#empty-reason').fill('[합성 검증] 희망자 없음 회신을 대조했습니다.');await page.locator('#empty-form button').click();
  await page.waitForFunction(()=>!document.getElementById('workflow-confirm').disabled);await complete();await next();assert.ok(await page.locator('#review-panel').isVisible());assert.equal(await page.locator('#workflow-confirm').isDisabled(),true);
  await page.locator('#clean-reason').fill('[합성 검증] 정상 행을 회신 원본과 대조했습니다.');await page.locator('#clean-button').click();await page.waitForFunction(()=>document.getElementById('clean-button').textContent.includes('0행'));
  const missing=page.locator('.adhoc-row').filter({has:page.locator('summary').getByText('성명 누락',{exact:false})});await missing.locator('summary').click();
  await missing.locator('[data-col="1"]').fill('가상참석자B');await missing.locator('.row-reason').fill('[합성 검증] 회신 담당자 확인 후 누락 성명 보완');await missing.locator('button[type=submit]').click();
  await page.waitForFunction(()=>!document.getElementById('workflow-confirm').disabled);await complete();
  let data=await jobData(job);assert.equal(data.workflow.steps.find(s=>s.kind==='collect').status,'needs_review');
  await next();assert.ok(await page.locator('#upload-panel').isVisible());await complete();await next();assert.ok(await page.locator('#export-panel').isVisible());assert.equal(await page.locator('#workflow-confirm').isDisabled(),true);
  await page.locator('#finalize').click();await page.locator('#export-list a').waitFor();await download('#export-list a','education-result.xlsx');await complete();
  assert.equal(await page.locator('[data-wf-next]').count(),0);assert.equal(await page.locator('[data-next]').isDisabled(),true);
  data=await jobData(job);assert.equal(data.workflow.completed_count,5);assert.equal(data.summary.pending,0);assert.equal(data.summary.missing,0);assert.equal(data.summary.attendees,2);assert.ok(data.exports.some(e=>e.is_current));
  await page.screenshot({path:path.join(output,'education-completed.png'),fullPage:true});
  check('education entirely through UI: request/template → XLSX reply → absence → missing-name correction → required recheck → current export → five confirmations');
  const version=data.version,revision=data.workflow.revision;
  await page.reload();await page.locator('#job-detail').waitFor({state:'visible'});await selectKind(job,'request');
  const writesBefore=workflowWrites;assert.equal(await page.locator('[data-wf-next]').count(),0);data=await jobData(job);assert.equal(data.version,version);assert.equal(data.workflow.revision,revision);assert.equal(workflowWrites,writesBefore);
  check('completed education reload retains record, checklist, export version; navigation has no workflow writes');

  await page.goto(base+'/start.html');await page.locator('.recent-open').first().waitFor();
  if(await page.locator('#recent-more').count())await page.locator('#recent-more').evaluate(el=>el.open=true);
  const t=page.locator(`.recent-open[href*="case=${trip.id}"]`),e=page.locator(`.recent-open[href$="job-${job}"]`);
  assert.equal(await t.count(),1);assert.equal(await e.count(),1);result.recent_links=await page.locator('.recent-open').evaluateAll(a=>a.map(x=>x.getAttribute('href')));
  await e.click();await page.locator('#detail-title').getByText('[합성 v53] 처음 사용 교육 취합',{exact:true}).waitFor();assert.equal((await jobData(job)).workflow.completed_count,5);
  await page.goto(base+'/start.html');if(await page.locator('#recent-more').count())await page.locator('#recent-more').evaluate(el=>el.open=true);await page.locator(`.recent-open[href*="case=${trip.id}"]`).click();await page.locator('#case-workspace').waitFor({state:'visible'});assert.match(await page.locator('#case-title').innerText(),/처음 사용 회의/);
  check('start page resumes the exact saved education and travel IDs without re-entering the question');
  for(const width of [390,760,1440]){
   await page.setViewportSize({width,height:900});await page.goto(base+'/start.html');await page.locator('#recent-work .recent-row').first().waitFor();
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.equal(await page.locator('#start-shortcuts').getAttribute('open'),null);
   await page.screenshot({path:path.join(output,`start-${width}.png`),fullPage:true});
  }
  check('390/760/1440px start layout has no horizontal overflow and keeps optional shortcuts closed');
  assert.deepEqual(errors,[]);result.page_errors=errors;result.passed=true;
 }catch(e){result.passed=false;result.failure=e.stack;await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw e;}
 finally{fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2));await browser.close();}
 console.log(JSON.stringify(result,null,2));
}
main().catch(e=>{console.error(e);process.exitCode=1});
