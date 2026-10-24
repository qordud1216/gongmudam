"use strict";
// 선택을 바꾸지 않고, 접힌 설정 밖에도 현재 질문 조건과 조회 문제를 표시한다.
window.SeomuChatOptions=(()=>{
 const byId=id=>document.getElementById(id),options=byId('chat-options');
 if(!options)return {refresh(){}};
 const body=options.querySelector('.chat-options-body'),summary=byId('chat-options-summary'),alert=byId('chat-options-alert');
 const canonicalDate=byId('today'),date=byId('chat-reference-date');
 let scheduled=false;
 function setText(node,value){if(node.textContent!==value)node.textContent=value;}
 function refresh(){
  const library=byId('knowledge-library'),catalog=byId('knowledge-catalog'),count=byId('knowledge-count');
  const layers=[...options.querySelectorAll('.layer:checked')].map(el=>el.value);
  const workflow=options.querySelector('.workflow-chat-context select');
  const libraryLabel=library?.selectedOptions[0]?.textContent||'전체 등록 자료';
  const parts=[libraryLabel,layers.length?layers.join('·'):'적용 범위 선택 없음',canonicalDate.value||'기준 날짜 확인 중'];
  if(workflow?.value)parts.push('진행표: '+(workflow.selectedOptions[0]?.textContent||'교육 취합 업무'));
  if(count?.dataset.loaded!=='true'&&catalog?.dataset.loading==='true')parts.unshift('자료 확인 중');
  const text=parts.join(' · ');setText(summary,text);if(summary.title!==text)summary.title=text;
  if(date.value!==canonicalDate.value)date.value=canonicalDate.value;
  const messages=[...catalog.querySelectorAll('.knowledge-catalog-status')].map(el=>{const copy=el.cloneNode(true);copy.querySelectorAll('button').forEach(button=>button.remove());return copy.textContent.trim();}).filter(Boolean);
  const workflowMessage=options.querySelector('.workflow-chat-status')?.textContent.trim();
  if(workflowMessage)messages.push(workflowMessage);
  if(!layers.length)messages.push('선택한 규정 적용 범위가 없습니다. 자료·업무 설정에서 확인하세요.');
  const message=[...new Set(messages)].join(' · ');setText(alert,message);alert.hidden=!message;
  options.dataset.ready='true';
 }
 function schedule(){if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;refresh();});}
 function updateDate(){
  if(canonicalDate.value!==date.value){canonicalDate.value=date.value;canonicalDate.dispatchEvent(new Event('change',{bubbles:true}));}
  refresh();
 }
 date.addEventListener('input',updateDate);date.addEventListener('change',updateDate);
 canonicalDate.addEventListener('input',schedule);canonicalDate.addEventListener('change',schedule);
 body.addEventListener('input',schedule);body.addEventListener('change',schedule);
 new MutationObserver(schedule).observe(body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['hidden','href','data-loading','data-loaded','value','selected']});
 window.addEventListener('pageshow',schedule);
 refresh();
 return {refresh};
})();
