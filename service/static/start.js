"use strict";
const startById=id=>document.getElementById(id),startEscape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function recentHref(item){
 const id=String(item.id??'');
 if(item.kind==='travel'&&/^[a-f0-9]{32}$/i.test(id))return `travel.html?case=${id}#settle`;
 if(item.kind==='education'&&/^[a-f0-9]{32}$/i.test(id))return `adhoc.html#job-${id}`;
 if(item.kind==='collection'&&/^[a-f0-9]{32}$/i.test(id))return `adhoc.html#job-${id}`;
 if(item.kind==='folder'&&/^[a-f0-9]{32}$/i.test(id))return `folders.html#${id}`;
 if(item.kind==='folder'&&id==='esaram-manuals-v68')return 'folders.html?view=references#esaram-manuals-v68';
 return '';
}
let startModelSnapshot=null,startKnowledgeCount='등록 근거 자료 확인 중',startRecentRequest=0;
async function loadRecentWork(){
 const request=++startRecentRequest,box=startById('recent-work'),moreOpen=!!startById('recent-more')?.open;
 box.innerHTML='<p class="recent-state">최근 업무를 불러오는 중입니다.</p>';
 try{
  const response=await fetch('/api/workspace/recent');if(!response.ok)throw Error('최근 업무를 불러오지 못했습니다.');
  const data=await response.json();if(request!==startRecentRequest)return;
  if(!data||!Array.isArray(data.items)||data.items.some(item=>!item||typeof item!=='object'||Array.isArray(item)))throw Error('최근 업무 응답을 읽지 못했습니다. 다시 시도해 주세요.');
  const items=data.items.slice(0,6);
  if(!items.length){box.innerHTML='<p class="recent-state">저장된 업무가 없습니다. 새로 질문하거나 업무별 바로가기에서 시작하세요.</p><button type="button" class="secondary" id="recent-new-question">질문 입력으로 이동</button>';startById('recent-new-question').onclick=()=>{startById('start-question').focus();startById('start-question').scrollIntoView({block:'center'});};return;}
  const labels={travel:'출장정산',education:'교육 취합',collection:'자료 취합',folder:'업무자료 정리'};
  const rows=list=>`<ul class="recent-list">${list.map(item=>{
   const manual=item.kind==='folder'&&item.id==='esaram-manuals-v68',href=recentHref(item),label=manual?'등록 매뉴얼':labels[item.kind]||'업무',status=manual?'등록 자료':item.status,next=manual?'등록 매뉴얼과 원문 PDF를 확인하세요.':item.next_action;
   return `<li class="recent-row"><span class="recent-main"><span class="recent-type">${startEscape(label)}</span><span class="recent-status">${startEscape(status)}</span></span><span class="recent-title">${startEscape(item.title)}</span><span class="recent-next"><span class="recent-next-label">다음 할 일</span> ${startEscape(next)}</span>${href?`<a class="recent-open" aria-label="${startEscape(manual?'등록 매뉴얼 자료 보기':label+' '+String(item.title||'')+' 이어서 하기')}" href="${startEscape(href)}">${manual?'자료 보기':'이어서 하기 →'}</a>`:'<span class="recent-open unavailable">열 수 없음</span>'}</li>`;
  }).join('')}</ul>`;
  box.innerHTML=rows(items.slice(0,3))+(items.length>3?`<details id="recent-more"${moreOpen?' open':''}><summary>최근 업무 더 보기 (${items.length-3})</summary>${rows(items.slice(3))}</details>`:'');
 }catch(e){if(request!==startRecentRequest)return;box.innerHTML=`<div class="recent-error"><p class="recent-state">${startEscape(e.message||'최근 업무를 읽지 못했습니다.')}</p><button type="button" class="secondary" id="retry-recent">다시 시도</button></div>`;startById('retry-recent').onclick=loadRecentWork;}
}
async function loadWorkspaceStatus(){
 const box=startById('workspace-status');
 try{
  const response=await fetch('/api/workspace/status');if(!response.ok)throw Error('서버 상태를 읽지 못했습니다.');const d=await response.json(),r=d.resources;
  startKnowledgeCount=`등록 근거 자료 ${Number(r.knowledge_sources||0)}개`;
  startById('knowledge-count').textContent=startKnowledgeCount;
  renderStartModelStatus({detail:startModelSnapshot});
  box.innerHTML=`<div class="status-grid"><article><strong>기본 Ollama 참고</strong>${d.local_server_available?'기본 서버 응답 확인':'기본 서버 응답 미확인'}<br>Gemma ${d.local_pair_installed.gemma?'설치됨':'미확인'} · Llama ${d.local_pair_installed.llama?'설치됨':'미확인'}<br>기본 설치 참고 정보이며 선택 모델의 연결 상태와는 별도입니다.</article></div><p class="help">${startEscape(d.notice)}</p>`;
 }catch(e){startKnowledgeCount='등록 자료 수를 읽지 못했습니다.';startById('knowledge-count').textContent=startKnowledgeCount;renderStartModelStatus({detail:startModelSnapshot});box.textContent=e.message;}
}
function renderStartModelStatus(event){
 const s=event.detail;
 startModelSnapshot=s||null;
 if(!s){startById('start-quick-status').textContent=`선택 모델 상태 확인 불가 · ${startKnowledgeCount}`;return;}
 const connection={ready:'서버 연결됨 · 모델 확인',offline:'오프라인 안내',external:'외부 모델',invalid:'설정 확인 필요',unreachable:'서버 연결 실패',unauthorized:'인증 확인 필요',server_error:'서버 오류',unsupported:'목록 확인 미지원',invalid_response:'서버 응답 확인 필요',model_missing:'선택 모델 없음'}[s.connection?.state]||'연결 상태 확인 불가';
 const response={verified:'최근 시험 응답 확인',unverified:'시험 응답 미확인',checking:'시험 응답 확인 중',model_mismatch:'응답 모델 다름',model_unverified:'응답 모델 확인 불가',empty:'시험 응답 없음',failed:'최근 시험 실패',expired:'최근 시험 만료'}[s.response?.state]||'시험 응답 미확인';
 startById('start-quick-status').textContent=`선택 모델 ${s.profile||''} · ${s.model||'모델 미확인'} · ${connection} · ${response} · ${startKnowledgeCount}`;
}
window.addEventListener('seomu:model-status',renderStartModelStatus);
window.SeomuModelStatus?.init();
startById('refresh-start').onclick=()=>Promise.all([loadWorkspaceStatus(),loadRecentWork(),window.SeomuModelStatus?.refresh()]);
document.querySelectorAll('[data-start-example]').forEach(button=>{
 button.onclick=()=>{const input=startById('start-question');input.value=button.dataset.startExample;input.focus();startById('start-message').textContent='예시를 입력했습니다. 상황에 맞게 고친 뒤 바로 물어보세요.';};
});
let startNavigating=false;
startById('start-question-form').onsubmit=e=>{
 e.preventDefault();const text=startById('start-question').value.trim();if(!text||startNavigating)return;
 if(!SeomuFlow.write('question',{text,auto_submit:true,use_ai:startById('use-local-ai')?.checked===true})){startById('start-message').textContent='브라우저 임시 저장을 사용할 수 없습니다. 서무 안내 화면에 문장을 직접 입력하세요.';return;}
 startNavigating=true;startById('start-ask').disabled=true;startById('start-message').textContent='서무 안내로 이동해 답변을 찾습니다…';location.href='index.html?v=52#chat';
};
startById('start-question').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();startById('start-question-form').requestSubmit();}});
Promise.all([loadWorkspaceStatus(),loadRecentWork()]);
