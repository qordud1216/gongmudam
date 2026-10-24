/* Browser checks use an isolated installation and synthetic mutations only. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const [base,outputPath,runtimePath]=process.argv.slice(2);
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||'')||['8766','8767'].includes(new URL(base).port)||!outputPath||!runtimePath)throw Error('Use isolated-loopback-url output-dir isolated-runtime-dir');
const output=path.resolve(outputPath),runtime=path.resolve(runtimePath);
fs.mkdirSync(output,{recursive:true});
const result={base,synthetic_only:true,model_inference_tested:false,checks:[]};
const record=(name,details={})=>result.checks.push({name,...details,passed:true});
const wait=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
async function main(){
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 let asks=0,sourceReads=0;
 page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/ask'))asks++;if(r.url()===base+'/api/knowledge/sources')sourceReads++});
 let navigation=0;
 async function open(){await page.goto(base+'/index.html?v=51&check='+(++navigation)+'#chat');await page.waitForFunction(()=>document.getElementById('today').value&&document.getElementById('knowledge-count').dataset.loaded==='true');await page.locator('#chat-options>summary').click()}
 async function send(query){await page.locator('#query').fill(query);await page.locator('#askBtn').click()}
 async function settled(){await page.waitForFunction(()=>!document.getElementById('askBtn').disabled)}
 async function ask(query){const response=page.waitForResponse(r=>r.url()===base+'/api/ask'&&r.request().method()==='POST');await send(query);const r=await response;assert.equal(r.status(),200);const data=await r.json();await settled();return {data,box:page.locator('.msg.bot .bubble').last()}}
 async function request(method,url,body){const response=await page.request.fetch(base+url,{method,data:body});assert.ok(response.ok(),await response.text());return response.json()}
 try{
  await open();const bundledIds=new Set(JSON.parse(fs.readFileSync(path.join(runtime,'submission-data/knowledge.json'),'utf8')).sources.map(s=>s.id));
  const sources=(await request('GET','/api/knowledge/sources')).filter(s=>bundledIds.has(s.id)),libs=[...new Set(sources.filter(s=>s.enabled).map(s=>s.library_id))];assert.equal(sources.length,25);
  let count=sourceReads;await page.locator('.knowledge-catalog-details summary').click();
  assert.ok(await page.locator('#chatLog').evaluate(el=>el.getBoundingClientRect().height>=260));
  await page.locator('[data-knowledge-search]').fill('공무원');assert.equal(await page.locator('.knowledge-catalog-details').getAttribute('open'),'');
  assert.ok(await page.locator('.knowledge-catalog-item').count());assert.equal(sourceReads,count);
  await page.locator('[data-knowledge-search]').fill('');await page.locator('#knowledge-library').selectOption(libs[0]);
  await page.locator('[data-knowledge-refresh]').click();await page.waitForFunction(()=>!document.getElementById('knowledge-catalog').dataset.loading);
  assert.equal(await page.locator('#knowledge-library').inputValue(),libs[0]);assert.equal(await page.locator('.knowledge-catalog-details').getAttribute('open'),'');
  assert.ok((await page.locator('.knowledge-catalog-item a').first().getAttribute('href')).includes('?file='));
  record('catalog shares source fetch; search stays open; refresh preserves selected scope');

  await page.route('**/api/knowledge/sources',route=>route.fulfill({status:503,json:{detail:'synthetic outage'}}));
  await page.locator('[data-knowledge-refresh]').click();await page.locator('#knowledge-catalog').getByText('새 목록을 불러오지 못했습니다.',{exact:false}).waitFor();
  await page.locator('[data-knowledge-search]').fill('출장');await page.locator('#knowledge-catalog').getByText('마지막으로 불러온 목록입니다.',{exact:false}).waitFor();
  await page.unroute('**/api/knowledge/sources');await page.locator('[data-knowledge-refresh]').click();await page.waitForFunction(()=>!document.getElementById('knowledge-catalog').dataset.loading);
  assert.equal(await page.getByText('마지막으로 불러온 목록입니다.',{exact:false}).count(),0);
  await page.locator('[data-knowledge-search]').fill('');await page.locator('#knowledge-library').selectOption('');
  await page.locator('.knowledge-catalog-details summary').click();
  record('catalog outage retains marked snapshot through search and recovers');

  const realCases=new Map(['question_checks_v39.json','question_checks_v40.json'].flatMap(n=>JSON.parse(fs.readFileSync(path.join(runtime,'reference_data',n),'utf8'))).map(c=>[c.id,c]));
  let actualEvidenceTarget;
  for(const id of ['domestic-daily','지방공무원-marriage','inspection-deadline']){
   const {data,box}=await ask(realCases.get(id).question);assert.equal(data.mode,'source_search');assert.ok(data.knowledge.evidence.length);
   await box.locator('.answer-record-button').waitFor();const download=page.waitForEvent('download');await box.locator('.answer-record-button').click();const file=await download;const filename=path.join(output,id+'.txt');await file.saveAs(filename);const text=fs.readFileSync(filename,'utf8');
   for(const evidence of data.knowledge.evidence){assert.ok(text.includes(evidence.quote));assert.ok(text.includes(evidence.sha256));assert.ok(text.includes(evidence.source_id))}
   await box.locator('.answer-original summary').first().click();await box.locator('.knowledge-ref summary').first().click();
  const link=box.getByRole('link',{name:'자료함에서 이 파일 확인'}).first(),target=new URL(await link.getAttribute('href'),base);assert.equal(target.searchParams.get('source'),data.knowledge.evidence[0].source_id);actualEvidenceTarget=target;
   record('actual registered-source answer and exact-quote record: '+id,{evidence:data.knowledge.evidence.length});
  }
  const originalPage=await context.newPage();await originalPage.goto(actualEvidenceTarget.href);await originalPage.waitForFunction(file=>document.activeElement?.dataset.file===file,actualEvidenceTarget.searchParams.get('file'));assert.equal(await originalPage.locator('.knowledge-source.source-focus').getAttribute('data-id'),actualEvidenceTarget.searchParams.get('source'));assert.equal(await originalPage.getByText('요청한 등록 자료를 찾지 못했습니다.',{exact:false}).count(),0);await originalPage.close();
  await page.screenshot({path:path.join(output,'guidance-desktop.png'),fullPage:true});

  const gate=wait();let received;
  await page.route('**/api/ask',async route=>{received=route.request().postDataJSON();await gate.promise;await route.fulfill({json:{query:received.query,mode:'source_search',summary:'합성 응답',answer:'합성 응답',alternatives:[],cited:[],related:[],personal_notes:[],knowledge:{evidence:[]}}})});
  count=asks;await send('합성 대기 질문');await page.waitForFunction(()=>document.getElementById('askBtn').disabled);
  await page.locator('#query').fill('다음 질문 초안');await page.locator('#query').press('Enter');await page.locator('#chat-examples-options>summary').click();await page.locator('.ex').first().click();
  assert.equal(await page.locator('#query').inputValue(),'다음 질문 초안');assert.equal(asks,count+1);
  const sentDate=received.today;await page.locator('#chat-reference-date').fill('2026-10-18');await page.locator('#knowledge-library').selectOption(libs[0]);
  gate.resolve();await settled();const scopeBox=page.locator('.msg.bot .bubble').last();assert.ok((await scopeBox.locator('.chat-request-context').textContent()).includes(sentDate));assert.ok((await scopeBox.locator('.chat-request-context').textContent()).includes('전체 등록 자료'));
  const scopeDownload=page.waitForEvent('download');await scopeBox.locator('.answer-record-button').click();const scopeFile=await scopeDownload;await scopeFile.saveAs(path.join(output,'sent-context.txt'));assert.ok(fs.readFileSync(path.join(output,'sent-context.txt'),'utf8').includes('안내 기준일: '+sentDate));
  await page.unroute('**/api/ask');record('single flight; rejected repeat keeps draft; reply and saved record retain sent scope/date');

  const clearGate=wait();await page.route('**/api/ask',async route=>{await clearGate.promise;await route.fulfill({json:{query:'합성 늦은 응답',mode:'offline',summary:'지운 뒤 표시되면 안 되는 응답',alternatives:[],cited:[],related:[],personal_notes:[]}})});
  await send('합성 늦은 응답');await page.locator('#chatClear').click();await page.locator('#query').fill('지운 뒤 작성한 초안');await page.locator('#query').press('Enter');
  assert.ok(await page.locator('#askBtn').isDisabled());clearGate.resolve();await settled();assert.equal(await page.locator('.msg.bot').count(),1);assert.equal(await page.locator('#query').inputValue(),'지운 뒤 작성한 초안');assert.equal(await page.getByText('지운 뒤 표시되면 안 되는 응답',{exact:true}).count(),0);
  await page.unroute('**/api/ask');record('clear invalidates late display; in-flight request stays locked; next draft preserved');

  // Let the server commit a synthetic workflow edit, then lose the HTTP response.
  const job=await request('POST','/api/adhoc/jobs',{title:'[합성 v47] 재시도 검증',situation:'교육 참석 희망자 취합',course:'합성 교육',event_date:'2026-11-06',deadline:'2026-10-30',departments:['합성총무팀']});
  await open();await Promise.all([page.waitForResponse(r=>r.url()===base+'/api/adhoc/jobs/'+job.id),page.locator('.workflow-chat-context select').selectOption(job.id)]);
  await page.waitForFunction(id=>window.SeomuWorkflowChat.getAskFields().education_job_id===id,job.id);
  const bodies=[],workflowResponses=[];
  await page.route('**/api/ask',async route=>{bodies.push(route.request().postDataJSON());const response=await route.fetch();workflowResponses.push(await response.json());if(bodies.length===1)await route.abort('failed');else await route.fulfill({response})});
  await send('검토 다음에 부서장 확인 단계를 넣어줘');await page.locator('.chat-retry').waitFor();assert.equal(workflowResponses[0].workflow_chat.status,'applied');
  await page.locator('.chat-retry').click();await settled();assert.equal(bodies.length,2);assert.deepEqual(bodies[1],bodies[0]);assert.equal(workflowResponses[1].workflow_chat.replayed,true);
  const edited=await request('GET','/api/adhoc/jobs/'+job.id);assert.equal(edited.workflow.steps.filter(s=>s.title==='부서장 확인').length,1);assert.equal(edited.version,job.version);
  await page.unroute('**/api/ask');record('lost response after actual workflow commit retries exact request once; no duplicate step');

  // Create synthetic local files only inside the isolated test installation.
  const documents=path.join(runtime,'synthetic-v47',String(Date.now()));fs.mkdirSync(documents,{recursive:true});
  fs.writeFileSync(path.join(documents,'같은제목A.txt'),'업무명: 합성 교육\n연도: 2026\n교육 참석 희망자는 부서별로 회신합니다.');
  const library=await request('POST','/api/folders/libraries',{name:'[합성 v47] 근거 이동',roots:[documents]}),fid=library.files[0].id;
  const registered=await request('POST','/api/knowledge/libraries/'+library.id+'/sources',{version:library.version,file_ids:[fid],kind:'기관 지침',institution:'합성 기관'}),sid=registered.sources[0].id;
  await page.goto(base+`/folders.html?file=${fid}&source=${sid}#${library.id}`);
  await page.waitForFunction(file=>document.activeElement?.dataset.file===file,fid);
  const card=page.locator('#files details[data-file]').filter({has:page.locator('summary strong',{hasText:'같은제목A.txt'})});assert.equal(await card.getAttribute('open'),'');
  assert.ok((await page.locator('.knowledge-source').textContent()).includes('등록 원문과 일치'));
  fs.writeFileSync(path.join(documents,'같은제목A.txt'),'업무명: 합성 교육\n연도: 2026\n교육 참석 회신 마감이 수정되었습니다.');
  fs.writeFileSync(path.join(documents,'같은제목B.txt'),'업무명: 합성 교육\n연도: 2026\n추가 회신 안내문입니다.');
  await page.locator('#folder-step-connect').click();await page.locator('#scan-form').evaluate(form=>form.closest('details').open=true);await page.locator('#scan-form button[type=submit]').click();
  await page.waitForFunction(()=>document.querySelectorAll('#knowledge-files option').length===2&&document.getElementById('knowledge-sources').textContent.includes('원문 변경'));
  await page.locator('#folder-step-result').click();await page.locator('.source-file-link').click();await page.waitForFunction(file=>document.activeElement?.dataset.file===file,fid);assert.ok((await page.locator('.knowledge-source').textContent()).includes('원문 변경'));
  await page.screenshot({path:path.join(output,'source-file-and-rescan.png'),fullPage:true});
  await page.locator('#folder-step-connect').click();const other=page.locator('.open-library').filter({hasNotText:'[합성 v47] 근거 이동'}).first();await other.click();await page.waitForFunction(()=>!new URL(location.href).searchParams.has('file'));assert.ok(!page.url().includes('source='));
  await page.goto(base+`/folders.html?file=missing&source=${sid}#${library.id}`);await page.getByText('요청한 파일을 이 자료함에서 찾지 못했습니다.',{exact:false}).waitFor();assert.equal(await page.locator('#files details[open][data-file]').count(),0);
  record('exact source/file navigation and focus; rescan updates candidates/stale status; unknown IDs have no fallback');

  // Stale catalog, unsafe links and out-of-order refreshes are controlled browser cases.
  await open();const synthetic=[{id:'s1',file_id:'f1',library_id:'l1',library_name:'합성 자료함',title:'<img src=x onerror=window.bad=1>',enabled:true,current:false,path:'PRIVATE-PATH',official:{source_url:'javascript:alert(1)'}},{id:'s2',library_id:'l2',title:'제외 자료',enabled:false,current:false}];
  await page.route('**/api/knowledge/sources',route=>route.fulfill({json:synthetic}));await page.evaluate(()=>refreshKnowledgeSources());
  await page.locator('.knowledge-catalog-details summary').click();assert.equal(await page.locator('.knowledge-catalog-item').count(),2);assert.equal(await page.locator('#knowledge-catalog img').count(),0);assert.equal(await page.locator('#knowledge-catalog a[href^="javascript:"]').count(),0);assert.ok(!(await page.locator('#knowledge-catalog').textContent()).includes('PRIVATE-PATH'));assert.equal(await page.getByText('원문 재확인 필요',{exact:true}).count(),2);
  await page.unroute('**/api/knowledge/sources');const pending=[];
  await page.route('**/api/knowledge/sources',route=>{pending.push(route)});
  await page.evaluate(()=>{void refreshKnowledgeSources();void refreshKnowledgeSources()});await page.waitForFunction(()=>document.getElementById('knowledge-catalog').dataset.loading==='true');
  while(pending.length<2)await new Promise(r=>setTimeout(r,10));
  await pending[1].fulfill({json:[{...synthetic[0],title:'최신 응답'}]});await page.getByText('최신 응답',{exact:true}).waitFor();await pending[0].fulfill({json:[{...synthetic[0],title:'늦은 응답'}]});
  assert.equal(await page.getByText('늦은 응답',{exact:true}).count(),0);await page.unroute('**/api/knowledge/sources');
  record('source status remains explicit; literal HTML and private fields inert; newest refresh wins');
  await page.route('**/api/knowledge/sources',route=>route.fulfill({json:[[]]}));await page.reload();await page.locator('#chat-options-alert').filter({hasText:'자료 목록을 불러오지 못했습니다.'}).waitFor();await page.unroute('**/api/knowledge/sources');await page.locator('#chat-options>summary').click();await page.locator('[data-knowledge-refresh]').click();await page.waitForFunction(()=>document.getElementById('knowledge-count').dataset.loaded==='true');
  for(const width of [390,760]){await page.setViewportSize({width,height:900});const sizes=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,height:document.getElementById('chatLog').getBoundingClientRect().height}));assert.ok(sizes.scroll<=sizes.width,JSON.stringify(sizes));assert.ok(sizes.height>=260,JSON.stringify(sizes))}
  await page.locator('.knowledge-catalog-details summary').click();await page.screenshot({path:path.join(output,'guidance-mobile.png'),fullPage:true});
  record('malformed initial source response recovers; 390/760px layout has no horizontal overflow');
  assert.deepEqual(errors,[]);result.passed=true;
 }catch(error){result.failure={message:error.message,url:page.url()};await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error}
 finally{result.page_errors=errors;fs.writeFileSync(path.join(output,'guidance-ui-result.json'),JSON.stringify(result,null,2));await browser.close()}
 console.log(JSON.stringify(result,null,2));
}
main().catch(error=>{console.error(error);process.exitCode=1});
