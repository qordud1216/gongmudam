/* Live preview verification. Creates only clearly labelled synthetic work via the UI. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process'),crypto=require('node:crypto');
const JSZip=require('../static/toolbox/vendor/jszip.min.js');
const [base,out,python]=process.argv.slice(2);
if(base!=='http://127.0.0.1:8781'||!out||!python)throw Error('Usage: http://127.0.0.1:8781 evidence-dir python.exe');
fs.mkdirSync(out,{recursive:true});
const stateFile=path.join(out,'created-synthetic-work.json');
let saved=fs.existsSync(stateFile)?JSON.parse(fs.readFileSync(stateFile,'utf8')):{base,tag:'[합성검증 v57 '+new Date().toISOString().replace(/[:.]/g,'-')+']'};
assert.equal(saved.base,base);
const report={base,synthetic_tag:saved.tag,checks:[],downloads:0,page_errors:[],writes:[],existing_work_unchanged:false};
const hash=x=>crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
async function main(){
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 const persist=()=>fs.writeFileSync(stateFile,JSON.stringify(saved,null,2));
 async function get(route){const r=await context.request.get(base+route);assert.equal(r.status(),200,route);return r.json();}
 const check=n=>{report.checks.push(n);fs.writeFileSync(path.join(out,'progress.json'),JSON.stringify(report,null,2));};
 function digestLists(cases,jobs){return {travel:Object.fromEntries(cases.map(c=>[c.id,hash({version:c.version,trip:c.trip,organization:c.organization,updated_at:c.updated_at})])),adhoc:Object.fromEntries(jobs.map(j=>[j.id,hash(j)]))};}
 const targets=await context.request.get(base+'/api/toolbox/targets');
 if(targets.status()!==200){await browser.close();throw Error('New attachment API not ready; no synthetic work was created. HTTP '+targets.status());}
 if(!saved.baseline){saved.baseline=digestLists(await get('/api/travel/cases'),await get('/api/adhoc/jobs'));persist();}
 await context.route('**/*',async route=>{
  const r=route.request(),url=new URL(r.url());
  if(url.origin!==base)return route.abort();
  if(!['GET','HEAD'].includes(r.method())){
   const create=r.method()==='POST'&&((url.pathname==='/api/travel/cases'&&!saved.trip)||(url.pathname==='/api/adhoc/jobs'&&!saved.job));
   const scoped=[saved.trip,saved.job].filter(Boolean).some(id=>url.pathname.includes('/'+id+'/'));
   if(!create&&!scoped){report.page_errors.push('Blocked unexpected write '+url.pathname);return route.abort();}
   report.writes.push({method:r.method(),path:url.pathname});
  }
  await route.continue();
 });
 context.on('page',p=>{p.on('pageerror',e=>report.page_errors.push(e.message));p.on('download',()=>report.downloads++);});
 const tripPage=await context.newPage(),jobPage=await context.newPage();let toolbox;
 try{
  if(!saved.trip){
   await tripPage.goto(base+'/travel.html?v=57');await tripPage.locator('#organization').selectOption('demo-city');
   for(const [id,value] of Object.entries({destination:'세종',purpose:saved.tag+' 도구함 증빙 첨부','start-date':'2026-10-23','end-date':'2026-10-23'}))await tripPage.locator('#'+id).fill(value);
   await tripPage.locator('#overnight').selectOption('false');
   const pending=tripPage.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/travel/cases');
   await tripPage.locator('#trip-form button[type=submit]').click();const r=await pending;assert.equal(r.status(),201);saved.trip=(await r.json()).id;persist();
  }else await tripPage.goto(base+'/travel.html?case='+saved.trip+'#settle');
  await tripPage.locator('#case-workspace').waitFor({state:'visible'});await tripPage.locator('#journey-step-evidence').click();
  if(!saved.job){
   await jobPage.goto(base+'/adhoc.html#new');
   for(const [id,value] of Object.entries({situation:saved.tag+' 교육 참석 희망자 취합 검증','job-title':saved.tag+' 자료 취합',course:'도구함 첨부 검증교육','event-date':'2026-11-06',deadline:'2026-10-30',departments:'검증부서'}))await jobPage.locator('#'+id).fill(value);
   const pending=jobPage.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/adhoc/jobs');
   await jobPage.locator('#job-form button[type=submit]').click();const r=await pending;assert.equal(r.status(),201);saved.job=(await r.json()).id;persist();
  }else await jobPage.goto(base+'/adhoc.html#job-'+saved.job);
  await jobPage.locator('#job-detail').waitFor({state:'visible'});
  const tripBefore=await get('/api/travel/cases/'+saved.trip),jobBefore=await get('/api/adhoc/jobs/'+saved.job);
  assert.ok(tripBefore.trip_json.purpose.startsWith(saved.tag));assert.ok(jobBefore.settings.title.startsWith(saved.tag));
  check('Created/reopened exactly two labelled synthetic work records; existing work not selected for writes');
  const popup=context.waitForEvent('page');await tripPage.locator('#travel-work-attachments a').first().click();toolbox=await popup;
  await toolbox.waitForLoadState();await toolbox.goto(base+`/toolbox.html?v=57&work=travel&target=${saved.trip}#img2pdf`);
  const png=Buffer.from(await toolbox.evaluate(()=>{const c=document.createElement('canvas');c.width=1200;c.height=700;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,c.width,c.height);x.fillStyle='#123';x.font='52px Arial';x.fillText('SYNTHETIC LIVE ATTACHMENT 12345',30,130);return c.toDataURL('image/png').split(',')[1];}),'base64');
  await toolbox.locator('#toolbox-app input[type=file]').setInputFiles({name:'합성검증_영수증.png',mimeType:'image/png',buffer:png});
  await toolbox.getByRole('button',{name:'PDF 만들기',exact:true}).click();
  await toolbox.locator('#toolbox-output-dialog').waitFor({state:'visible'});await toolbox.waitForFunction(()=>!document.getElementById('toolbox-output-refresh').disabled);
  assert.equal(await toolbox.locator('#toolbox-output-work').inputValue(),'travel:'+saved.trip);assert.equal(await toolbox.locator('#toolbox-output-mode').inputValue(),'receipt');
  async function attach(expectedPath){const pending=toolbox.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname===expectedPath);await toolbox.locator('#toolbox-output-attach').click();const r=await pending;assert.equal(r.status(),201);await toolbox.waitForFunction(()=>!document.getElementById('toolbox-output-attach').disabled);return r.json();}
  const receipt=await attach('/api/travel/cases/'+saved.trip+'/documents');
  const doc=receipt.documents.find(d=>d.id===receipt.upload_result.document_id);assert.ok(doc);assert.deepEqual(receipt.review.transactions,tripBefore.review.transactions);
  const original=await context.request.get(base+doc.original_url);assert.equal(original.status(),200);const bytes=await original.body();assert.ok(bytes.subarray(0,5).equals(Buffer.from('%PDF-')));
  fs.writeFileSync(path.join(out,'attached-live-receipt.pdf'),bytes);assert.equal(report.downloads,0);
  check('Actual photo→PDF output POSTed to live travel receipt API, original preserved, no automatic transaction approval and no browser download');
  await tripPage.reload();await tripPage.locator('#journey-step-evidence').click();await tripPage.locator('#document-'+doc.id).waitFor({state:'visible'});
  await tripPage.locator('#receipt-documents').screenshot({path:path.join(out,'travel-receipt-attached.png')});
  check('Saved travel attachment remains visible after reloading the real app');
  const beforeRefs=await get(`/api/toolbox/adhoc/${saved.job}/attachments`);
  await toolbox.locator('#toolbox-output-work').selectOption('adhoc:'+saved.job);assert.equal(await toolbox.locator('#toolbox-output-mode').inputValue(),'reference');
  const ref=await attach(`/api/toolbox/adhoc/${saved.job}/attachments`),item=ref.items.find(i=>i.id===ref.attachment_id);
  const refBytes=await context.request.get(base+item.original_url);assert.equal(refBytes.status(),200);assert.ok((await refBytes.body()).equals(bytes));
  const jobRef=await get('/api/adhoc/jobs/'+saved.job);assert.equal(jobRef.version,jobBefore.version);assert.deepEqual(jobRef.rows,jobBefore.rows);
  await jobPage.locator('#adhoc-work-attachments .work-attachment-item').waitFor();await jobPage.reload();await jobPage.locator('#adhoc-work-attachments .work-attachment-item').waitFor();
  await jobPage.locator('#adhoc-work-attachments').screenshot({path:path.join(out,'collection-reference-attached.png')});
  check('Same in-memory PDF POSTed to live collection references, bytes match travel original, refresh preserves it and roster/version stay unchanged');
  const duplicate=await attach(`/api/toolbox/adhoc/${saved.job}/attachments`);assert.equal(duplicate.duplicate,true);
  assert.equal((await get(`/api/toolbox/adhoc/${saved.job}/attachments`)).items.length,beforeRefs.items.length+Number(!ref.duplicate));
  check('Live duplicate retry does not create a second reference file');
  const fixture=spawnSync(python,['-c',"import sys; from app import adhoc; s={'course':'도구함 첨부 검증교육','event_date':'2026-11-06','departments':['검증부서']}; sys.stdout.buffer.write(adhoc.workbook(s,[['검증부서','합성검증자','주무관','도구함 첨부 검증교육','2026-11-06','희망']]))"],{cwd:path.resolve(__dirname,'..'),windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  assert.equal(fixture.status,0,fixture.stderr?.toString());const archive=new JSZip();archive.file('합성검증_회신.xlsx',fixture.stdout);const zip=await archive.generateAsync({type:'nodebuffer'});
  await toolbox.locator('#toolbox-output-close').click();await toolbox.goto(base+'/toolbox.html?v=57');await toolbox.goto(base+'/toolbox.html?v=57#zip');
  await toolbox.locator('#toolbox-app input[type=file]').nth(1).setInputFiles({name:'합성검증_회신.zip',mimeType:'application/zip',buffer:zip});
  await toolbox.locator('#toolbox-app .fitem').getByRole('button',{name:'저장',exact:true}).click();await toolbox.locator('#toolbox-output-dialog').waitFor({state:'visible'});await toolbox.waitForFunction(()=>!document.getElementById('toolbox-output-refresh').disabled);
  await toolbox.locator('#toolbox-output-work').selectOption('adhoc:'+saved.job);assert.equal(await toolbox.locator('#toolbox-output-mode').inputValue(),'reply');
  const reply=await attach('/api/adhoc/jobs/'+saved.job+'/files');
  assert.ok(reply.rows.some(r=>r.values.includes('합성검증자')&&r.decision==='pending'));
  await jobPage.reload();await jobPage.locator('#detail-title').waitFor();
  assert.equal((await get('/api/adhoc/jobs/'+saved.job)).rows.length,reply.rows.length);
  check('XLSX extracted by toolbox POSTed directly to live collection API, validated and preserved as pending rows after reload');
  const after=digestLists(await get('/api/travel/cases'),await get('/api/adhoc/jobs'));
  for(const kind of ['travel','adhoc'])for(const [id,digest] of Object.entries(saved.baseline[kind]))assert.equal(after[kind][id],digest,'Existing work changed: '+kind+'/'+id);
  report.existing_work_unchanged=true;assert.equal(report.downloads,0);assert.deepEqual(report.page_errors,[]);
  report.travel_url=base+'/travel.html?case='+saved.trip+'#settle';report.collection_url=base+'/adhoc.html#job-'+saved.job;
  check('All direct attachments required zero browser downloads; original work hashes unchanged and no uncaught browser errors');
  report.passed=true;
 }catch(e){report.passed=false;report.failure=e.stack;await (toolbox||tripPage).screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e;}
 finally{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
