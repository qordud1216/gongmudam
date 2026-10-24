/* Actual browser conversions → actual ASGI upload APIs, isolated temporary DBs, no server. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process'),readline=require('node:readline');
const JSZip=require('../static/toolbox/vendor/jszip.min.js');
const [python,out]=process.argv.slice(2);if(!python||!out)throw Error('Usage: python.exe evidence-directory');
fs.mkdirSync(out,{recursive:true});
const base='http://127.0.0.1:8799',report={transport:'ASGI TestClient / browser route bridge; no listening server',temporary_databases:true,downloads:0,checks:[],page_errors:[],requests:[]};
const child=spawn(python,[path.join(__dirname,'toolbox_ui_bridge.py')],{cwd:path.resolve(__dirname,'..'),windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'},stdio:['pipe','pipe','pipe']});
let serial=0,pending=new Map(),readyResolve,readyReject,targetGate=null;
const ready=new Promise((a,b)=>{readyResolve=a;readyReject=b;});
child.stderr.on('data',b=>fs.appendFileSync(path.join(out,'bridge-stderr.txt'),b));
readline.createInterface({input:child.stdout}).on('line',line=>{try{const r=JSON.parse(line);if(r.ready)readyResolve(r);else if(pending.has(r.id)){const p=pending.get(r.id);pending.delete(r.id);r.error?p.reject(Error(r.error)):p.resolve(r);}}catch(e){readyReject(e);}});
child.on('exit',code=>{if(code){const e=Error('ASGI bridge exited '+code);readyReject(e);for(const p of pending.values())p.reject(e);}});
function rpc(request){return new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});child.stdin.write(JSON.stringify({id,...request})+'\n');});}
async function data(url,method='GET',body){const r=await rpc({path:url,method,headers:body?{'content-type':'application/json'}:{},body:body?Buffer.from(JSON.stringify(body)).toString('base64'):''});assert.ok(r.status<300,`${r.status} ${url}`);return JSON.parse(Buffer.from(r.body,'base64').toString());}
async function main(){
 const fixture=await ready;
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 await context.route('**/*',async route=>{const r=route.request(),u=new URL(r.url());if(u.origin!==base)return route.abort();try{
  if(u.pathname==='/api/toolbox/targets'&&targetGate){targetGate.arrived();await targetGate.wait;}
  const headers=r.headers();delete headers['content-length'];delete headers.host;
  const response=await rpc({path:u.pathname+u.search,method:r.method(),headers,body:r.postDataBuffer()?.toString('base64')||''});
  if(r.method()!=='GET')report.requests.push({path:u.pathname,method:r.method(),status:response.status});
  await route.fulfill({status:response.status,headers:response.headers,body:Buffer.from(response.body,'base64')});
 }catch(e){report.page_errors.push(e.stack);await route.abort().catch(()=>{});}});
 context.on('page',p=>{p.on('pageerror',e=>report.page_errors.push(e.stack||e.message));p.on('download',()=>report.downloads++);});
 const page=await context.newPage();const check=n=>report.checks.push(n);
 const tool=async id=>{await page.goto(base+`/toolbox.html?v=57&work=travel&target=${fixture.trip}`);await page.locator('#toolSearch').waitFor();await page.goto(base+`/toolbox.html?v=57&work=travel&target=${fixture.trip}#${id}`);};
 async function dialog(){await page.locator('#toolbox-output-dialog').waitFor({state:'visible'});await page.waitForFunction(()=>!document.getElementById('toolbox-output-refresh').disabled);}
 async function attach(status=201){const response=page.waitForResponse(r=>r.request().method()==='POST'&&(/\/attachments$|\/documents$|\/files$/.test(new URL(r.url()).pathname)));await page.locator('#toolbox-output-attach').click();assert.equal((await response).status(),status);await page.waitForFunction(()=>!document.getElementById('toolbox-output-attach').disabled);}
 try{
  const jobPage=await context.newPage();await jobPage.goto(base+'/adhoc.html#job-'+fixture.job);await jobPage.locator('#adhoc-work-attachments .work-attachments-list').waitFor();
  await tool('img2pdf');
  const png=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=1200;c.height=700;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,c.width,c.height);x.fillStyle='black';x.font='56px Arial';x.fillText('SYNTHETIC RECEIPT 12345',50,140);return c.toDataURL('image/png').split(',')[1];}),'base64');
  await page.locator('#toolbox-app input[type=file]').setInputFiles({name:'receipt.png',mimeType:'image/png',buffer:png});
  await page.getByRole('button',{name:'PDF 만들기',exact:true}).click();await dialog();
  assert.equal(await page.locator('#toolbox-output-work').inputValue(),'travel:'+fixture.trip);
  assert.equal(await page.locator('#toolbox-output-mode').inputValue(),'receipt');assert.equal(report.downloads,0);
  await attach();assert.match(await page.locator('#toolbox-output-status').innerText(),/원본과 거래 후보/);
  const trip=await data('/api/travel/cases/'+fixture.trip);assert.equal(trip.documents.length,1);assert.equal(trip.review.transactions.length,0);assert.equal(trip.version,2);
  const original=await rpc({path:trip.documents[0].original_url});fs.writeFileSync(path.join(out,'attached-receipt.pdf'),Buffer.from(original.body,'base64'));
  check('Real image→PDF output attaches as travel receipt without download; review remains required');
  const tripPage=await context.newPage();await tripPage.goto(base+'/travel.html?case='+fixture.trip+'#settle');
  await tripPage.locator('.receipt-document').waitFor({state:'attached'});
  await tripPage.locator('#journey-step-evidence').click();
  await tripPage.locator('.receipt-reason').fill('아직 저장하지 않은 대조 메모');
  await page.locator('#toolbox-output-work').selectOption('adhoc:'+fixture.job);
  assert.equal(await page.locator('#toolbox-output-mode').inputValue(),'reference');await attach();
  await jobPage.locator('#adhoc-work-attachments .work-attachment-item').waitFor();
  const refs=await data(`/api/toolbox/adhoc/${fixture.job}/attachments`),refOriginal=await rpc({path:refs.items[0].original_url});
  assert.equal(refOriginal.body,original.body);const job=await data('/api/adhoc/jobs/'+fixture.job);assert.equal(job.version,1);assert.equal(job.rows.length,0);
  check('Same in-memory PDF attaches to collection references; original bytes identical, roster/version unchanged, open tab updates');
  await attach();assert.match(await page.locator('#toolbox-output-status').innerText(),/이미 첨부/);
  assert.equal((await data(`/api/toolbox/adhoc/${fixture.job}/attachments`)).items.length,1);
  check('Duplicate click/retry keeps one attachment');
  await page.locator('#toolbox-output-work').selectOption('travel:'+fixture.trip);await page.locator('#toolbox-output-mode').selectOption('reference');await attach();
  await tripPage.locator('#travel-work-attachments .work-attachment-item').waitFor();assert.equal(await tripPage.locator('.receipt-reason').inputValue(),'아직 저장하지 않은 대조 메모');
  check('Reference notification refreshes only attachment list and preserves unsaved receipt memo');
  await page.screenshot({path:path.join(out,'direct-attach-desktop.png'),fullPage:true});
  await page.locator('#toolbox-output-close').click();await page.locator('#toolbox-output-reopen').click();assert.equal(await page.locator('#toolbox-output-file option').count(),1);
  check('Close and reopen preserves generated Blob');
  await page.locator('#toolbox-output-close').click();await tool('photos');
  await page.locator('#toolbox-app input[type=file]').setInputFiles([{name:'same.png',mimeType:'image/png',buffer:png},{name:'same.png',mimeType:'image/png',buffer:png}]);
  await page.getByRole('button',{name:'줄여서 저장',exact:true}).click();await dialog();
  const names=await page.locator('#toolbox-output-file option').allTextContents();assert.equal(names.length,3);assert.match(names[1],/same_1\.jpg/);
  await page.locator('#toolbox-output-work').selectOption('adhoc:'+fixture.job);await page.locator('#toolbox-output-file').selectOption('zip');await attach();
  const all=await data(`/api/toolbox/adhoc/${fixture.job}/attachments`),archive=all.items.find(i=>i.filename.endsWith('.zip'));const z=await rpc({path:archive.original_url});
  const zip=await JSZip.loadAsync(Buffer.from(z.body,'base64'));assert.deepEqual(Object.keys(zip.files).sort(),['same.jpg','same_1.jpg']);
  check('Multiple converted photos offer individual files and full ZIP with collision-safe names');
  await page.locator('#toolbox-output-close').click();await tool('zip');
  const replyZip=new JSZip();replyZip.file('reply.xlsx',Buffer.from(fixture.reply,'base64'));const zipBytes=await replyZip.generateAsync({type:'nodebuffer'});
  await page.locator('#toolbox-app input[type=file]').nth(1).setInputFiles({name:'reply.zip',mimeType:'application/zip',buffer:zipBytes});
  await page.locator('#toolbox-app .fitem').getByRole('button',{name:'저장',exact:true}).click();await dialog();
  await page.locator('#toolbox-output-work').selectOption('adhoc:'+fixture.job);assert.equal(await page.locator('#toolbox-output-mode').inputValue(),'reply');await attach();
  const merged=await data('/api/adhoc/jobs/'+fixture.job);assert.equal(merged.rows.length,1);assert.equal(merged.rows[0].decision,'pending');assert.equal(merged.version,2);
  await jobPage.locator('.work-attachments-latest').waitFor();
  check('XLSX extracted in ZIP tool goes straight to existing collection validator and pending-row review');
  await page.locator('#toolbox-output-close').click();await tool('qr');await page.waitForFunction(()=>document.querySelector('.toolbox-surface .status')?.textContent.startsWith('QR '));
  await page.getByRole('button',{name:'PNG 저장',exact:true}).click();await dialog();await page.locator('#toolbox-output-work').selectOption('adhoc:'+fixture.job);
  await data(`/api/adhoc/jobs/${fixture.job}/empty-replies`,'POST',{version:2,department:'총무팀',reason:'다른 창에서 변경한 합성 회신'});
  await attach(409);assert.match(await page.locator('#toolbox-output-status').innerText(),/바뀌었습니다|유지|보관/);
  await page.locator('#toolbox-output-refresh').click();await page.waitForFunction(()=>!document.getElementById('toolbox-output-refresh').disabled);await attach();
  assert.equal((await data('/api/adhoc/jobs/'+fixture.job)).version,3);
  check('Concurrent business change rejects stale attachment; refresh/retry retains exact generated file');
  let release,arrived;const reached=new Promise(r=>arrived=r);targetGate={wait:new Promise(r=>release=r),arrived};
  const writes=report.requests.length;await page.locator('#toolbox-output-refresh').click();await reached;
  for(const id of ['work','file','mode','attach'])assert.equal(await page.locator('#toolbox-output-'+id).isDisabled(),true,id);
  await page.evaluate(id=>{const s=document.getElementById('toolbox-output-work');s.value='travel:'+id;s.dispatchEvent(new Event('change'));},fixture.trip);
  assert.equal(await page.locator('#toolbox-output-attach').isDisabled(),true);
  release();targetGate=null;await page.waitForFunction(()=>!document.getElementById('toolbox-output-refresh').disabled);
  assert.equal(await page.locator('#toolbox-output-work').inputValue(),'adhoc:'+fixture.job);assert.equal(report.requests.length,writes);
  check('Delayed target refresh locks work/purpose/attach, preventing displayed and actual target races');
  assert.equal(report.downloads,0);
  const pending=page.waitForEvent('download');await page.locator('#toolbox-output-download').click();const download=await pending;await download.saveAs(path.join(out,'optional-download.png'));
  assert.equal(report.downloads,1);check('All direct attachments need zero downloads; optional download remains available');
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  const box=await page.locator('#toolbox-output-dialog').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=391);
  await page.screenshot({path:path.join(out,'direct-attach-mobile.png'),fullPage:true});check('Attachment dialog fits 390px mobile viewport');
  await tripPage.locator('#new-case').click();
  const oldContext=await tripPage.locator('a[data-toolbox-href]').evaluateAll(links=>links.some(a=>new URL(a.href).searchParams.has('target')||new URL(a.href).searchParams.has('work')));
  assert.equal(oldContext,false);check('Starting a new trip clears prior toolbox target while preserving converter links');
  assert.deepEqual(report.page_errors,[]);report.passed=true;
 }catch(e){report.passed=false;report.failure=e.stack;await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e;}
 finally{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));await browser.close();child.stdin.end();}
}
main().catch(e=>{console.error(e);child.stdin.end();process.exitCode=1;});
