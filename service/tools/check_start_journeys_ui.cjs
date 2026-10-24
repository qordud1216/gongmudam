/* Run only against a separate synthetic installation, never a shared demo. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const assert = require('node:assert/strict');
const [base, output, python] = process.argv.slice(2);
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base || '') || !output || !python) throw Error('Usage: isolated-loopback-url output-dir python.exe');
if (['8766','8767'].includes(new URL(base).port)) throw Error('Use a separate synthetic installation');
fs.mkdirSync(output,{recursive:true});
const result={base,synthetic_only:true,model_inference_tested:false,checks:[]};
const check=name=>result.checks.push(name);
async function main(){
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1050},acceptDownloads:true});
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 let askCount=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/ask'))askCount++;});
 async function ask(text){
   await page.goto(base+'/start.html?v=45');
   await page.locator('#start-question').fill(text);
   const before=askCount;
   await page.locator('#start-question').press('Enter');
   await page.waitForURL('**/index.html?v=52#chat');
   await page.locator('.task-followup button').waitFor({timeout:30000});
   assert.equal(askCount,before+1);
   await page.locator('.task-followup button').click();
 }
 async function download(selector, filename){
   const ready=page.waitForEvent('download');await page.locator(selector).click();
   const d=await ready;await d.saveAs(path.join(output,filename));return path.join(output,filename);
 }
 try{
   const status=await (await page.request.get(base+'/api/workspace/status')).json();
   assert.equal(status.resources.knowledge_sources,25);
   await page.goto(base+'/start.html?v=45');
   assert.equal(await page.locator('.workspace-grid > a').count(),3);
   assert.equal(await page.locator('.hero-flow').count(),0);
   assert.equal(await page.locator('.first-run').getAttribute('open'),null);
   assert.equal(await page.locator('#start-shortcuts').getAttribute('open'),null);
   assert.ok(await page.locator('.recent-section').evaluate(el=>el.compareDocumentPosition(document.getElementById('start-shortcuts'))&Node.DOCUMENT_POSITION_FOLLOWING));
   check('question and resume before optional shortcuts; environment collapsed; 25 registered sources');

   const travelQuestion='2026-10-21 세종 당일 출장 정산을 준비해줘';
   await ask(travelQuestion);await page.waitForURL('**/travel.html?v=45#from-guidance');
   await page.locator('#organization option[value="national-general"]').waitFor({state:'attached'});
   assert.equal(await page.locator('#situation').inputValue(),travelQuestion);
   await page.locator('#organization').selectOption('national-general');
   await page.locator('#destination').fill('세종');await page.locator('#purpose').fill('[합성 v45] 화면 흐름 검증');
   await page.locator('#start-date').fill('2026-10-21');await page.locator('#end-date').fill('2026-10-21');
   await page.locator('#overnight').selectOption('false');
   await page.locator('#trip-form button[type="submit"]').click();
   await page.locator('#case-workspace').waitFor({state:'visible'});
   await page.locator('#journey-step-calculate').click();
   await page.locator('#calc-grade').selectOption('group2');await page.locator('#calc-scope').selectOption('inside');
   await page.locator('#calc-minutes').fill('240');await page.locator('#calc-km').fill('3');await page.locator('#calc-confirm').check();
   await page.locator('#calculate').click();
   await page.locator('#calculation-result').getByText('20,000원',{exact:false}).first().waitFor();
   await page.locator('#journey-step-draft').click();
   await page.locator('#draft').click();await page.locator('#draft-result a[href$="/csv"]').waitFor();
   await download('#draft-result a[href$="/csv"]','travel-preparation.csv');
   await page.screenshot({path:path.join(output,'travel-draft.png'),fullPage:true});
   check('question → travel handoff → save → 20,000 KRW calculation → draft CSV download');

   const educationQuestion='각 부서의 교육 참석 희망자를 취합하고 누락과 중복을 확인해줘';
   await ask(educationQuestion);await page.waitForURL('**/adhoc.html?v=45#new');
   await page.waitForFunction(text=>document.getElementById('situation').value===text,educationQuestion);
   assert.equal(await page.locator('#situation').inputValue(),educationQuestion);
   await page.locator('#job-title').fill('[합성 시연 v36] v45 대화에서 이어진 교육 취합');
   await page.locator('#course').fill('공공 AI 실무교육');await page.locator('#event-date').fill('2026-11-06');
   await page.locator('#deadline').fill('2026-10-30');await page.locator('#departments').fill('총무팀\n행정팀\n안전팀');
   await page.locator('#job-form button[type="submit"]').click();await page.waitForURL(/#job-[a-f0-9]{32}$/);
   const jobId=new URL(page.url()).hash.slice(5),port=Number(new URL(base).port);
   const run=spawnSync(python,['-c',`import sys,json;from tools.check_education_workflow import check;r=check(${port},${JSON.stringify(jobId)});print(json.dumps({'passed':r['passed'],'completed':r['final']['workflow']['completed_count']},ensure_ascii=False))`],{cwd:path.resolve(__dirname,'..'),encoding:'utf8',timeout:120000});
   if(run.status!==0)throw Error(run.stdout+'\n'+run.stderr);
   result.education=JSON.parse(run.stdout.trim());assert.equal(result.education.completed,6);
   await page.reload();await page.locator('#job-detail').waitFor({state:'visible'});
   const job=await (await page.request.get(base+'/api/adhoc/jobs/'+jobId)).json();
   const current=job.exports.find(e=>e.is_current);assert.ok(current);
   const exportResponse=await page.request.get(base+`/api/adhoc/jobs/${jobId}/exports/${current.id}`);
   assert.ok(exportResponse.ok());fs.writeFileSync(path.join(output,'education-result.xlsx'),await exportResponse.body());
   check('question → education creation → replies/errors/duplicate review → six stages → current XLSX export');

   const folderQuestion='11월 교육 관련 업무 폴더를 정리하고 자료를 분류하고 싶어요.';
   await ask(folderQuestion);await page.waitForURL('**/folders.html?v=45#from-guidance');
   await page.waitForFunction(text=>document.getElementById('folder-situation').value===text,folderQuestion);
   assert.equal(await page.locator('#folder-situation').inputValue(),folderQuestion);
   const fixtures=path.join(output,'synthetic-materials');fs.mkdirSync(fixtures,{recursive:true});
   fs.writeFileSync(path.join(fixtures,'교육안내.txt'),'업무명: 공공 AI 실무교육\n연도: 2026\n교육일: 2026-11-06\n주관부서: 총무팀\n교육 안내와 회신 자료를 정리합니다.','utf8');
   await page.locator('#upload-library-name').fill('[합성 v45] 교육 자료 정리');
   await page.locator('#folder-upload-input').setInputFiles(fixtures);
   await page.locator('#folder-upload-submit').waitFor({state:'visible'});
   await page.locator('#folder-upload-submit').click();
   await page.waitForURL(/folders\.html\?v=45#[a-f0-9]{32}$/);
   await page.locator('.select-project').first().click();await page.locator('#confirm-project').click();
   await page.locator('#project-context .tag').getByText('사용자 분류 확인').waitFor();
   await page.locator('#folder-step-result').click();
   const reportPath=await download('#report-link','folder-analysis.json');
   const report=JSON.parse(fs.readFileSync(reportPath,'utf8'));assert.equal(report.situation,folderQuestion);assert.equal(report.summary.review,0);
   check('question → folder purpose → directory upload → classification confirmation → JSON report');

   await page.goto(base+'/start.html?v=45');await page.locator('.recent-row').first().waitFor();
   await page.waitForFunction(()=>document.getElementById('start-quick-status').textContent.includes('25개'));
   const names=await page.locator('.recent-type').allTextContents();
   for(const name of ['출장정산','교육 취합','업무자료 정리'])assert.ok(names.includes(name));
   await page.screenshot({path:path.join(output,'start-desktop.png'),fullPage:true});
   const recent=await (await page.request.get(base+'/api/workspace/recent')).json();result.recent=recent;
   for(const kind of ['travel','education','folder']){
     const item=recent.items.find(i=>i.kind===kind);assert.ok(item);
     const link=page.locator(`a.recent-open[href="${item.href}"]`);if(!await link.isVisible())await page.locator('#recent-more>summary').click();
     await page.locator(`a.recent-open[href="${item.href}"]`).click();
     await page.waitForURL(base+'/'+item.href);await page.goto(base+'/start.html?v=45');await page.locator('.recent-row').first().waitFor();
   }
   const count=askCount;await page.reload();await page.waitForTimeout(500);assert.equal(askCount,count);
   for(const width of [390,760,1024]){
     await page.setViewportSize({width,height:900});
     const size=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));
     assert.ok(size.scroll<=size.width,JSON.stringify(size));
     if(width===390){
       const nav=await page.locator('.common-navigation').boundingBox();assert.ok(nav.height<=64,JSON.stringify(nav));
       await page.screenshot({path:path.join(output,'start-mobile.png'),fullPage:true});
     }
   }
   check('saved items resume exact records; refresh does not repeat question; 390/760/1024px no page overflow');
   await page.route('**/api/workspace/recent',r=>r.fulfill({json:{items:[],totals:{}}}));
   await page.goto(base+'/start.html');await page.getByText('저장된 업무가 없습니다.',{exact:false}).waitFor();
   await page.unroute('**/api/workspace/recent');
   await page.route('**/api/workspace/recent',r=>r.fulfill({status:503,json:{detail:'test'}}));
   await page.reload();await page.locator('#retry-recent').waitFor();
   await page.unroute('**/api/workspace/recent');await page.locator('#retry-recent').click();await page.locator('.recent-row').first().waitFor();
   await page.route('**/api/workspace/recent',r=>r.fulfill({json:{items:[{kind:'travel',id:'invalid',title:'<img src=x onerror=alert(1)>',status:'<b>unsafe</b>',next_action:'literal',href:'javascript:alert(1)'}]}}));
   await page.reload();await page.getByText('열 수 없음').waitFor();assert.equal(await page.locator('#recent-work img, #recent-work b, #recent-work a').count(),0);
   check('recent list empty/error/retry states; stored text and invalid links stay inert');
   assert.deepEqual(errors,[]);result.passed=true;
 }catch(error){
   result.failure={message:error.message,url:page.url(),inputs:await page.locator('input:invalid,select:invalid').evaluateAll(es=>es.map(e=>({id:e.id,value:e.value,reason:e.validationMessage}))),notice:await page.locator('#message').textContent().catch(()=>null)};
   await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;
 }finally{
   result.page_errors=errors;fs.writeFileSync(path.join(output,'ui-results.json'),JSON.stringify(result,null,2));await browser.close();
 }
 console.log(JSON.stringify({passed:result.passed,checks:result.checks,education:result.education},null,2));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
