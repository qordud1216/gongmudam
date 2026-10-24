"use strict";
let knowledgeSourcesSnapshot=null,knowledgeSourcesRequest=0,knowledgeLibraryListenerBound=false,knowledgeSelectionReset=false,knowledgeCatalogError='',knowledgeCatalogOpen=false,knowledgeCatalogSearch='',knowledgeCatalogEventsBound=false;
const knowledgeEsc=v=>typeof esc==='function'?esc(v??''):String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function knowledgeHttpUrl(value){if(typeof value!=='string'||!value.trim())return '';try{const url=new URL(value);return /^https?:$/.test(url.protocol)&&!url.username&&!url.password?url.href:''}catch{return ''}}
function knowledgeFileUrl(entry){const fileId=entry.file_id,sourceId=entry.source_id||entry.id,libraryId=entry.library_id;if(!libraryId)return '';let url='folders.html';if(fileId){url+=`?file=${encodeURIComponent(fileId)}`;if(sourceId)url+=`&source=${encodeURIComponent(sourceId)}`}return `${url}#${encodeURIComponent(libraryId)}`}
function knowledgeManualPage(value){const page=Number(value);return Number.isSafeInteger(page)&&page>0?page:null}
function knowledgeManualUrl(entry){const sourceId=entry.source_id||entry.id,page=knowledgeManualPage(entry.page);return sourceId&&page?`/api/knowledge/sources/${encodeURIComponent(sourceId)}/original#page=${page}`:''}
function knowledgeAnswerHtml(k){
 if(!k)return '';
 let h='';
 if(k.evidence?.length)h+=`<section class="refs"><h3>내 자료에서 확인한 원문</h3><p class="muted">${knowledgeEsc(k.scope)}</p>${k.evidence.map((e,i)=>{const manual=e.reference_kind==='system_manual',officialUrl=knowledgeHttpUrl(e.official?.source_url),downloadUrl=knowledgeHttpUrl(e.official?.download_url),fileUrl=knowledgeFileUrl(e),manualUrl=manual?knowledgeManualUrl(e):'';return `<details class="ref knowledge-ref" data-evidence-index="${i+1}"><summary>[${i+1}] ${knowledgeEsc(e.title)} · ${knowledgeEsc(e.loc)}</summary>${manual?`<p>e-사람 사용법 · PDF ${knowledgeEsc(knowledgeManualPage(e.page))}/${knowledgeEsc(knowledgeManualPage(e.page_count)||'미확인')}쪽 · 전체 ${knowledgeEsc(knowledgeManualPage(e.indexed_pages)||'미확인')}쪽 색인</p><p class="muted">화면 조작 안내이며 법정 지급 기준은 별도 확인합니다.</p>${manualUrl?`<p><a href="${knowledgeEsc(manualUrl)}" target="_blank" rel="noopener noreferrer">등록 매뉴얼 원문 PDF 열기 ↗</a></p>`:''}`:`<p>${knowledgeEsc(e.kind)} · 적용 기관: ${knowledgeEsc(e.institution||'미확인')} · 시행일: ${knowledgeEsc(e.effective_date||'미확인')}${e.limited?' · 추출 본문 일부만 검색':''}</p>${e.official?`<p>${officialUrl?`<a href="${knowledgeEsc(officialUrl)}" target="_blank" rel="noopener noreferrer">공식 출처 열기 ↗</a>`:''}${downloadUrl&&downloadUrl!==officialUrl&&e.official.pdf_pages?.length?`${officialUrl?' · ':''}<a href="${knowledgeEsc(downloadUrl)}" target="_blank" rel="noopener noreferrer">원문 PDF 해당 쪽 열기 ↗</a>`:''}</p><p class="muted">${knowledgeEsc(e.official.publication)} · 발행: ${knowledgeEsc(e.official.issuer)} · 수집 ${knowledgeEsc(e.official.retrieved_at?String(e.official.retrieved_at).slice(0,10):'미확인')}<br>${knowledgeEsc(e.official.scope)}</p>`:''}`}${e.model_selected_quote?`<p class="muted">AI가 선택한 구절: ${knowledgeEsc(e.model_selected_quote)}</p>`:''}${e.quote_basis==='original_context'?'<p class="muted">조건 누락을 막기 위해 검색한 조항의 원문 문맥을 함께 표시합니다.</p>':''}<blockquote>${knowledgeEsc(e.quote)}</blockquote><details><summary>검색에 사용한 원문 범위</summary><p>${knowledgeEsc(e.text)}</p></details>${fileUrl?`<p><a href="${fileUrl}">자료함에서 이 파일 확인</a></p>`:''}<small>SHA-256: ${knowledgeEsc(e.sha256)}</small></details>`}).join('')}</section>`;
 if(k.experiences?.length)h+=`<section class="refs"><h3>지난번 처리 경험 · 공식 근거 아님</h3>${k.experiences.map(n=>`<details><summary>${knowledgeEsc(n.title)} · ${knowledgeEsc(n.project_name)}</summary><p>${knowledgeEsc(n.author)} · ${knowledgeEsc(n.created_at?String(n.created_at).slice(0,10):'미확인')}</p><p>상황: ${knowledgeEsc(n.situation)}</p><p>처리 방법: ${knowledgeEsc(n.handling)}</p><p>주의점: ${knowledgeEsc(n.caution)}</p></details>`).join('')}</section>`;
 if(k.excluded?.length)h+=`<details><summary>답변 근거에서 제외한 자료 ${k.excluded.length}개</summary>${k.excluded.map(d=>`<p>${knowledgeEsc(d.title)}: ${knowledgeEsc(d.reason)}</p>`).join('')}</details>`;
 return h;
}
function knowledgeValue(value){return String(value??'')}
function knowledgeCatalogItem(entry){
 const changed=entry.current===false;
 const manual=entry.reference_kind==='system_manual';
 const officialUrl=knowledgeHttpUrl(entry.official?.source_url);
 const fileUrl=knowledgeFileUrl(entry);
 const states=[];
 if(entry.enabled&&entry.current)states.push('<span class="knowledge-catalog-state is-available">사용 설정 · 원문 일치</span>');
 if(changed)states.push('<span class="knowledge-catalog-state needs-review">원문 재확인 필요</span>');
 if(!entry.enabled)states.push('<span class="knowledge-catalog-state is-excluded">답변 제외</span>');
 if(!states.length)states.push('<span class="knowledge-catalog-state is-excluded">답변 제외</span>');
 const links=[fileUrl?`<a href="${fileUrl}">자료함에서 이 파일 확인</a>`:'',officialUrl?`<a href="${knowledgeEsc(officialUrl)}" target="_blank" rel="noopener noreferrer">공식 원문</a>`:''].filter(Boolean).join(' · ');
 const description=manual?`e-사람 사용법 · 전체 ${knowledgeEsc(knowledgeManualPage(entry.indexed_pages)||'미확인')}/${knowledgeEsc(knowledgeManualPage(entry.page_count)||'미확인')}쪽 색인 · ${knowledgeEsc(entry.institution||'기관 미확인')}`:`${knowledgeEsc(entry.library_name||'자료함 미확인')} · ${knowledgeEsc(entry.kind||'종류 미확인')} · ${knowledgeEsc(entry.institution||'기관 미확인')}`;
 const manualUrl=manual?knowledgeManualUrl({...entry,page:1}):'';
 return `<article class="knowledge-catalog-item"><strong>${knowledgeEsc(entry.title||'제목 미확인')}</strong><span>${description}</span>${states.join('')}${links?`<span class="knowledge-catalog-links">${links}</span>`:''}${manualUrl?`<span class="knowledge-catalog-links"><a href="${knowledgeEsc(manualUrl)}" target="_blank" rel="noopener noreferrer">등록 매뉴얼 원문 PDF 열기 ↗</a></span>`:''}</article>`;
}
function bindKnowledgeRefresh(root){
 if(knowledgeCatalogEventsBound)return;
 knowledgeCatalogEventsBound=true;
 root.addEventListener('click',event=>{if(event.target.closest('[data-knowledge-refresh]'))refreshKnowledgeSources()});
 root.addEventListener('input',event=>{
  if(!event.target.matches('[data-knowledge-search]'))return;
  const search=event.target,start=search.selectionStart,end=search.selectionEnd;
  knowledgeCatalogSearch=search.value;knowledgeCatalogOpen=!!root.querySelector('.knowledge-catalog-details')?.open;
  renderKnowledgeCatalog();
  const next=root.querySelector('[data-knowledge-search]');
  if(next){next.focus();next.setSelectionRange(start,end)}
 });
 root.addEventListener('toggle',event=>{if(event.target.matches('.knowledge-catalog-details'))knowledgeCatalogOpen=event.target.open},true);
}
function renderKnowledgeCatalog(){
 const root=document.getElementById('knowledge-catalog');if(!root)return;
 bindKnowledgeRefresh(root);
 const docs=knowledgeSourcesSnapshot;
 const previousDetails=root.querySelector('.knowledge-catalog-details');
 if(previousDetails)knowledgeCatalogOpen=previousDetails.open;
 const search=root.querySelector('[data-knowledge-search]');
 if(search)knowledgeCatalogSearch=search.value;
 const library=document.getElementById('knowledge-library'),selected=library?.value||'',query=knowledgeCatalogSearch;
 const usable=docs?docs.filter(d=>d.enabled&&d.current).length:0;
 const excluded=docs?docs.filter(d=>!d.enabled||!d.current).length:0;
 const count=document.getElementById('knowledge-count');
 if(count)count.textContent=docs?`답변 근거로 등록한 자료 ${usable}개 · PC 폴더 전체를 임의로 검색하지 않습니다.${excluded?` ${excluded}개는 답변에서 제외됩니다.`:''}`:'등록 자료 상태를 읽지 못했습니다.';
 if(!docs){root.innerHTML=`<p class="knowledge-catalog-status" role="status">${knowledgeEsc(knowledgeCatalogError||'등록 자료 목록을 아직 불러오지 못했습니다.')} <button type="button" data-knowledge-refresh>다시 시도</button></p>`;return}
 const matching=docs.filter(entry=>{
  const text=[entry.title,entry.library_name,entry.kind,entry.institution].map(knowledgeValue).join(' ').toLocaleLowerCase();
  return text.includes(query.toLocaleLowerCase())&&(!selected||String(entry.library_id||'')===selected);
 });
 const listHtml=matching.length?matching.map(knowledgeCatalogItem).join(''):docs.length?'<p class="knowledge-catalog-empty">조건에 맞는 자료가 없습니다.</p>':'<p class="knowledge-catalog-empty">등록된 자료가 없습니다.</p>';
 const status=knowledgeCatalogError?`<p class="knowledge-catalog-status" role="status">${knowledgeEsc(knowledgeCatalogError)}</p>`:'';
 root.innerHTML=`<details class="knowledge-catalog-details"${knowledgeCatalogOpen?' open':''}><summary>답변에 쓰는 자료 보기</summary>${status}${knowledgeSelectionReset?'<p class="knowledge-catalog-status" role="status">선택한 자료함이 사라져 전체 자료로 돌아왔습니다.</p>':''}<p class="knowledge-catalog-note">실제 인용은 질문 기준일과 적용 대상에 따라 달라집니다.</p><div class="knowledge-catalog-head"><button type="button" data-knowledge-refresh>새로고침</button></div><div class="knowledge-catalog-controls"><label>검색 <input type="search" data-knowledge-search value="${knowledgeEsc(query)}" placeholder="제목, 자료함, 종류, 기관"></label></div><div class="knowledge-catalog-list">${listHtml}</div></details>`;
}
async function refreshKnowledgeSources(){
 const seq=++knowledgeSourcesRequest,root=document.getElementById('knowledge-catalog');
 if(root){const details=root.querySelector('.knowledge-catalog-details');if(details)knowledgeCatalogOpen=details.open;root.dataset.loading='true'}
 try{
  const response=await fetch('/api/knowledge/sources');
  if(!response.ok)throw new Error(`HTTP ${response.status}`);
  const data=await response.json();
  if(!Array.isArray(data)||data.some(item=>!item||typeof item!=='object'||Array.isArray(item)))throw new Error('invalid response');
  if(seq!==knowledgeSourcesRequest)return;
  const library=document.getElementById('knowledge-library'),oldSelection=library?.value||'';
  knowledgeSourcesSnapshot=data;knowledgeCatalogError='';knowledgeSelectionReset=false;
  if(library){
   const libraries=new Map();
   for(const item of data)if(item.enabled&&item.library_id)libraries.set(String(item.library_id),item.library_name||'자료함 미확인');
   library.innerHTML='<option value="">전체 등록 자료</option>'+[...libraries].map(([id,name])=>`<option value="${knowledgeEsc(id)}">${knowledgeEsc(name)}</option>`).join('');
   if([...library.options].some(option=>option.value===oldSelection))library.value=oldSelection;
   else if(oldSelection){library.value='';knowledgeSelectionReset=true}
   if(!knowledgeLibraryListenerBound){library.addEventListener('change',()=>renderKnowledgeCatalog());knowledgeLibraryListenerBound=true}
  }
  renderKnowledgeCatalog();
  const count=document.getElementById('knowledge-count');if(count)count.dataset.loaded='true';
  if(root)delete root.dataset.loading;
 }catch(error){
  if(seq!==knowledgeSourcesRequest)return;
  knowledgeCatalogError=knowledgeSourcesSnapshot?'새 목록을 불러오지 못했습니다. 아래는 마지막으로 불러온 목록입니다.':'자료 목록을 불러오지 못했습니다.';
  if(root){delete root.dataset.loading;renderKnowledgeCatalog()}
  const count=document.getElementById('knowledge-count');if(count)count.textContent=knowledgeSourcesSnapshot?'마지막으로 불러온 등록 자료 목록을 표시합니다.':'등록 자료 상태를 읽지 못했습니다.';
 }
}
async function loadKnowledgeScope(){
 const target=document.getElementById('knowledge-library');if(!target)return;
 if(knowledgeSourcesSnapshot){renderKnowledgeCatalog();return}
 await refreshKnowledgeSources();
}
