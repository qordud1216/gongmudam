/* Synthetic, browser-only toolbox checks. Never writes application business APIs. */
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {PDFDocument}=require('../static/toolbox/vendor/pdf-lib.min.js');
const JSZip=require('../static/toolbox/vendor/jszip.min.js');
const [base,out,heicFixture]=process.argv.slice(2);
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||'')||!out)throw Error('Usage: loopback-url evidence-directory');
fs.mkdirSync(out,{recursive:true});
const report={base,synthetic_only:true,business_api_writes:[],external_requests:[],errors:[],warnings:[],checks:[],rendered:[]};
if(heicFixture){report.synthetic_only=false;report.inputs='Synthetic data plus HEIC library publisher demo fixture';}
async function main(){
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 await context.route('**/*',route=>{
  const r=route.request(),url=r.url();
  if(/^https?:/.test(url)&&new URL(url).origin!==base){report.external_requests.push(url);return route.abort();}
  if(!['GET','HEAD'].includes(r.method())){report.business_api_writes.push({url,method:r.method()});return route.abort();}
  return route.continue();
 });
 const page=await context.newPage();
 page.on('pageerror',e=>report.errors.push(`${page.url()} after ${report.checks.at(-1)}: ${e.stack||e.message}`));
 page.on('console',m=>{
  const t=m.text();
  const disabledDemo=m.location().url===base+'/api/public-demo/status'&&t.includes('404');
  if(disabledDemo||/\[W:onnxruntime:.*CleanUnusedInitializersAndNodeArgs\]/.test(t))report.warnings.push(t);
  else if(m.type()==='error'||t.includes('정밀 엔진을 쓸 수 없어'))report.errors.push(t);
 });
 page.on('response',r=>{
  if(r.status()===404&&r.url()===base+'/api/public-demo/status')report.warnings.push('Existing private-runtime folder UI: public demo endpoint disabled (404)');
  else if(r.status()>=400)report.errors.push(`HTTP ${r.status()} ${r.url()}`);
 });
 const check=n=>report.checks.push(n);
 const tool=async id=>{await page.goto(base+'/toolbox.html?v=56');await page.locator('#toolSearch').waitFor();await page.goto(base+'/toolbox.html?v=56#'+id);};
 const root=()=>page.locator('#toolbox-app');
 async function download(name,action){await action();const dialog=page.locator('#toolbox-output-dialog');await dialog.waitFor({state:'visible'});const format=page.locator('#toolbox-output-file');if(name.endsWith('.zip')&&await format.locator('option[value="zip"]').count())await format.selectOption('zip');const pending=page.waitForEvent('download',{timeout:90000});await page.locator('#toolbox-output-download').click();const d=await pending;assert.equal(await d.failure(),null);const dest=path.join(out,name);await d.saveAs(dest);assert.ok(fs.statSync(dest).size>0);await page.locator('#toolbox-output-close').click();return fs.readFileSync(dest);}
 try{
  await page.goto(base+'/toolbox.html?v=56');
  const tools=await page.evaluate(()=>App.tools().map(t=>({id:t.id,name:t.name})));
  assert.equal(tools.length,28);assert.equal(await page.locator('#count').innerText(),'도구 28개');
  for(const t of tools){
   await tool(t.id);await root().getByRole('heading',{name:t.name,exact:true}).waitFor();
   assert.doesNotMatch(await root().innerText(),/도구를 여는 중 오류/);
   if(t.id==='qr')await page.waitForFunction(()=>document.querySelector('.toolbox-surface .status')?.textContent.startsWith('QR '));
   report.rendered.push(t.id);
  }
  check('All 28 tool screens render without script errors');
  await tool('img2pdf');await root().getByRole('button',{name:'← 전체 도구',exact:true}).click();
  await page.locator('#toolSearch').waitFor();assert.equal(new URL(page.url()).hash,'');
  await page.locator('#toolSearch').fill('PDF 합치기');assert.equal(await root().locator('.tile').count(),1);
  await root().locator('.tile').click();assert.equal(new URL(page.url()).hash,'#pdfmerge');
  await page.goBack();await page.locator('#toolSearch').waitFor();
  await page.goto(base+'/toolbox.html#invalid-tool');await page.locator('#toolSearch').waitFor();
  check('Deep-link back, catalog/browser back, search, unknown tool fallback');
  const docs=[];
  for(const widths of [[300,310],[400]]){const p=await PDFDocument.create();widths.forEach(w=>p.addPage([w,500]));docs.push(Buffer.from(await p.save()));}
  await tool('pdfmerge');await root().locator('input[type=file]').setInputFiles(docs.map((buffer,i)=>({name:`synthetic-${i}.pdf`,mimeType:'application/pdf',buffer})));
  await page.waitForFunction(()=>document.querySelectorAll('.pg').length===3);
  const merged=await download('merged.pdf',()=>root().getByRole('button',{name:'합쳐서 저장',exact:true}).click());
  const mergedDoc=await PDFDocument.load(merged);assert.deepEqual(mergedDoc.getPages().map(p=>p.getWidth()),[300,310,400]);
  check('PDF merge: two files / three pages preserve page order and dimensions');
  await tool('pdfsplit');await root().locator('input[type=file]').setInputFiles({name:'synthetic.pdf',mimeType:'application/pdf',buffer:merged});
  await root().locator('.pg').nth(1).click();
  const split=await PDFDocument.load(await download('split.pdf',()=>root().getByRole('button',{name:'선택한 쪽만 새 PDF로',exact:true}).click()));
  assert.equal(split.getPageCount(),1);assert.equal(split.getPage(0).getWidth(),310);
  check('PDF split: selected second page only');
  const image=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=1600;c.height=1000;const x=c.getContext('2d');x.fillStyle='white';x.fillRect(0,0,c.width,c.height);x.fillStyle='black';x.font='80px Arial';x.fillText('OFFICE TEST 12345',90,180);return c.toDataURL('image/png').split(',')[1];}),'base64');
  const imageFile={name:'synthetic.png',mimeType:'image/png',buffer:image};
  await tool('img2pdf');await root().locator('input[type=file]').setInputFiles(imageFile);
  await root().getByRole('button',{name:'PDF 만들기',exact:true}).waitFor({state:'visible'});
  const imgPdf=await PDFDocument.load(await download('image.pdf',()=>root().getByRole('button',{name:'PDF 만들기',exact:true}).click()));
  assert.equal(imgPdf.getPageCount(),1);assert.ok(Math.abs(imgPdf.getPage(0).getWidth()-841.89)<0.1);
  check('Image → PDF: actual image converted into a landscape A4 PDF');
  await tool('photos');await root().locator('input[type=file]').setInputFiles(imageFile);
  await root().getByLabel('긴 변 최대 (px)',{exact:true}).selectOption('800');
  const resized=await download('resized.jpg',()=>root().getByRole('button',{name:'줄여서 저장',exact:true}).click());
  const dimensions=await page.evaluate(async b=>{const bitmap=await createImageBitmap(new Blob([new Uint8Array(b)],{type:'image/jpeg'}));return [bitmap.width,bitmap.height];},[...resized]);
  assert.deepEqual(dimensions,[800,500]);check('Photo resize: 1600×1000 → 800×500 JPEG');
  await tool('clean');await root().getByLabel('원문',{exact:true}).fill('합성 010-1234-5678 office@example.com\n합성 010-1234-5678 office@example.com');
  await root().getByRole('button',{name:'적용',exact:true}).click();
  assert.equal(await root().getByLabel('결과',{exact:true}).inputValue(),'합성 010-****-5678 of***@example.com');check('Text masking and duplicate-line removal');
  await tool('zip');await root().locator('input[type=file]').first().setInputFiles([{name:'first.txt',mimeType:'text/plain',buffer:Buffer.from('first synthetic')},{name:'second.txt',mimeType:'text/plain',buffer:Buffer.from('second synthetic')}]);
  const zipBytes=await download('bundle.zip',()=>root().getByRole('button',{name:'ZIP으로 묶기',exact:true}).click());
  const zip=await JSZip.loadAsync(zipBytes);assert.equal(await zip.file('first.txt').async('string'),'first synthetic');assert.equal(await zip.file('second.txt').async('string'),'second synthetic');
  await root().locator('input[type=file]').nth(1).setInputFiles({name:'bundle.zip',mimeType:'application/zip',buffer:zipBytes});
  await root().getByText('first.txt',{exact:true}).last().waitFor();check('ZIP creation and reading with two synthetic file contents');
  await tool('qr');await page.waitForFunction(()=>document.querySelector('.toolbox-surface .status')?.textContent.startsWith('QR '));
  const qr=await download('qr.png',()=>root().getByRole('button',{name:'PNG 저장',exact:true}).click());
  assert.equal(qr.subarray(1,4).toString(),'PNG');check('QR code renders and downloads PNG using local library');
  await tool('ocr');await root().locator('input[type=file]').setInputFiles(imageFile);
  await root().getByLabel('인식 엔진',{exact:true}).selectOption('kor+eng');
  await root().getByRole('button',{name:'글자 인식',exact:true}).click();
  await page.waitForFunction(()=>{const x=document.querySelector('.toolbox-surface textarea');return x?.value.includes('12345');},{},{timeout:120000});
  report.ocr_text=await root().locator('textarea').inputValue();
  await root().getByLabel('저장 형식',{exact:true}).selectOption('hwpx');
  const hwpx=await JSZip.loadAsync(await download('ocr.hwpx',()=>root().getByRole('button',{name:'저장',exact:true}).click()));
  assert.ok(hwpx.file('Contents/section0.xml'));assert.match(await hwpx.file('Contents/section0.xml').async('string'),/12345/);
  check('Local lightweight OCR recognizes synthetic image and exports HWPX with recognized text');
  await tool('ocr');await root().locator('input[type=file]').setInputFiles(imageFile);
  assert.equal(await root().getByLabel('인식 엔진',{exact:true}).inputValue(),'pp');
  const ppModels=[];const ppResponse=r=>{if(r.url().endsWith('.onnx'))ppModels.push(r.url());};page.on('response',ppResponse);
  await root().getByRole('button',{name:'글자 인식',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.toolbox-surface textarea')?.value.includes('12345'),{},{timeout:120000});
  page.off('response',ppResponse);assert.equal(ppModels.length,2);report.precision_models=ppModels;
  check('Local precision OCR engine recognizes synthetic image without external network');
  if(heicFixture){
   await tool('heic');await root().locator('input[type=file]').setInputFiles({name:'publisher-demo.heic',mimeType:'image/heic',buffer:fs.readFileSync(heicFixture)});
   await root().getByRole('button',{name:'JPG로 변환',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('.toolbox-surface .status')?.textContent.startsWith('1장 변환 완료'),{},{timeout:45000});
   const jpg=await download('heic-converted.jpg',()=>root().getByRole('button',{name:'저장',exact:true}).click());
   assert.equal(jpg.subarray(0,2).toString('hex'),'ffd8');
   check('HEIC publisher demo converts and downloads JPEG with actual worker under toolbox CSP');
  }
  await page.goto(base+'/travel.html');
  const toolboxLinks=page.locator('a[href^="toolbox.html"]');assert.equal(await toolboxLinks.count(),4);
  for(const a of await toolboxLinks.all()){assert.equal(await a.getAttribute('target'),'_blank');assert.match(await a.getAttribute('rel'),/noopener/);}
  check('All four toolbox entries from travel open separately to preserve in-progress inputs');
  for(const name of ['start','index','travel','adhoc','folders','change-inbox','local-ai','public-demo']){
   // Public demo APIs are deliberately disabled in the private installed runtime.
   if(name==='public-demo'){
    const response=await page.request.get(base+'/public-demo.html');assert.equal(response.status(),200);
    const html=await response.text();
    assert.equal(await page.evaluate(s=>new DOMParser().parseFromString(s,'text/html').querySelectorAll('.common-navigation a[href="toolbox.html"]').length,html),1);continue;
   }
   await page.goto(base+'/'+name+'.html');assert.equal(await page.locator('.common-navigation a[href="toolbox.html"]').count(),1,name);
  }
  check('Seven existing page UIs and disabled public-demo markup each contain exactly one sidebar toolbox entry');
  await page.goto(base+'/toolbox.html?v=56');await page.screenshot({path:path.join(out,'toolbox-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(out,'toolbox-mobile.png'),fullPage:true});
  await tool('img2pdf');assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  check('Catalog and image-to-PDF tool fit 390px mobile viewport');
  const nav=await page.locator('.sidebar a[href="toolbox.html"]').count();assert.equal(nav,1);
  assert.deepEqual(report.business_api_writes,[]);assert.deepEqual(report.external_requests,[]);assert.deepEqual(report.errors,[]);
  check('No external requests, business API writes, HTTP failures or browser script errors');
  report.passed=true;
 }catch(e){report.passed=false;report.failure=e.stack;await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});throw e;}
 finally{fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
