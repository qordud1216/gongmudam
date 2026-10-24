"use strict";
// 읽기 전용 진행 안내. 단계 선택은 분류·AI 분석·저장을 실행하지 않는다.
window.FolderFlow=(()=>{
 const steps=[['connect','폴더 연결'],['classify','분류 확인'],['assist','AI 도움','선택'],['result','정리 결과']];
 let view=null,libraryId=null,selectedStep='connect',root=null,panes={},loading=false;
 const byId=id=>document.getElementById(id);
 function ensure(){
  if(root)return;
  const workspace=byId('workspace-detail'),bar=byId('folder-case-bar');
  root=document.createElement('section');root.id='folder-flow';root.className='panel flow-overview';bar.after(root);
  const host=document.createElement('div');host.id='folder-stage-body';host.className='flow-stage-body';workspace.append(host);
  for(const [key] of steps){const pane=document.createElement('section');pane.id='folder-pane-'+key;pane.setAttribute('role','tabpanel');pane.setAttribute('aria-labelledby','folder-step-'+key);panes[key]=pane;host.append(pane);}
  const groups={connect:['folder-connect-panel','folder-libraries-panel','folder-scan-panel'],classify:['folder-classify-panel'],assist:['ai-panel','watch-panel'],result:['folder-knowledge-panel','folder-history-panel']};
  for(const [key,ids] of Object.entries(groups))for(const id of ids)panes[key].append(byId(id));
  const result=document.createElement('section');result.className='panel';result.id='folder-result';
  result.innerHTML='<h2>현재 분류 결과</h2><p id="folder-result-summary"></p><p class="help">파일 분류와 연결 기록을 JSON으로 저장합니다. 실제 업무의 완료·제출 기록과는 구분합니다.</p><div id="folder-result-download"></div>';
  panes.result.prepend(result);
  byId('folder-result-download').append(byId('report-link'));
  byId('report-link').classList.add('primary');byId('report-link').textContent='현재 정리 결과 JSON 저장';
  const obsolete=[...workspace.children].find(el=>el.tagName==='P'&&el.textContent.startsWith('흐름:'));if(obsolete)obsolete.hidden=true;
 }
 function facts(){
  if(!view)return {recommended:'connect',filter:null,reason:loading?'자료함을 불러오고 있습니다.':'업무 폴더를 선택하거나 저장한 자료함을 여세요.'};
  const review=Number(view.summary.review)||0,missing=Number(view.summary.missing)||0,files=Number(view.summary.files)||0;
  if(!files&&!missing)return {recommended:'connect',filter:null,reason:'확인한 파일이 없습니다. 폴더와 읽을 수 있는 자료를 확인하세요.'};
  if(missing)return {recommended:'classify',filter:'missing',reason:`이번에 확인하지 못한 파일 ${missing}개가 있습니다. 원래 폴더와 파일 상태를 확인하세요.`};
  if(review)return {recommended:'classify',filter:'review',reason:`분류를 확인하지 않은 파일 ${review}개가 있습니다. 제안 근거를 보고 분류를 확인하세요.`};
  return {recommended:'result',filter:null,reason:'현재 발견한 파일의 분류 확인이 기록되었습니다. 결과를 살펴보고 저장하세요.'};
 }
 function select(key,{focus=false}={}){
  if(!steps.some(([id])=>id===key)||(!view&&key!=='connect'))return;
  selectedStep=key;paint();
  if(focus){const title=byId('folder-current-title');title.focus();root.scrollIntoView({block:'start'});}
 }
 function paint(){
  const f=facts(),labels={connect:view?'연결됨':'자료함 선택',classify:!view?'연결 후 확인':`${view.summary.review}개 확인 필요${view.summary.missing?' · 미확인 '+view.summary.missing+'개':''}`,assist:'선택 기능',result:view?'현재 기록 보기':'연결 후 확인'};
  if(view&&!view.summary.review&&!view.summary.missing&&view.summary.files)labels.classify='현재 파일 확인됨';
  const instructions={connect:'업무 폴더를 선택해 연결하거나, 저장한 자료함을 열어 이어서 정리하세요.',classify:'파일을 열어 제안 근거를 확인하고, 맞는 업무 분류를 저장하세요.',assist:'필요하면 로컬 AI에 분류·요약·다음 할 일 제안을 요청하세요.',result:'현재 분류 결과를 저장하세요. 필요한 자료는 답변 근거로 등록할 수 있습니다.'};
  root.innerHTML=`<div class="flow-topline"><span>업무자료 정리 순서</span><button id="folder-next" type="button" class="secondary" ${loading?'disabled':''}>다음 할 일: ${esc(steps.find(([key])=>key===f.recommended)[1])} →</button></div>
   <nav class="flow-rail" role="tablist" aria-label="업무자료 정리 단계">${steps.map(([key,title,optional],i)=>`<button type="button" id="folder-step-${key}" class="flow-step ${selectedStep===key?'selected':''}" data-folder-step="${key}" role="tab" aria-selected="${selectedStep===key}" tabindex="${selectedStep===key?'0':'-1'}" aria-controls="folder-pane-${key}" ${!view&&key!=='connect'?'disabled':''}><span class="flow-number">${i+1}</span><span class="flow-label">${title}${optional?' · 선택':''}</span><span class="flow-state">${esc(labels[key])}</span></button>`).join('')}</nav>
   <div class="flow-current"><h2 id="folder-current-title" tabindex="-1">${steps.findIndex(([key])=>key===selectedStep)+1}. ${steps.find(([key])=>key===selectedStep)[1]}</h2><p class="flow-instruction">${instructions[selectedStep]}</p><p class="flow-reason" role="status">${esc(f.reason)}</p></div>
   <p class="flow-note">단계 선택은 화면 이동입니다. AI 분석은 분석 버튼을 누를 때만 요청하며, 분류 확인은 업무 완료를 뜻하지 않습니다.</p>`;
  for(const [key,pane] of Object.entries(panes))pane.hidden=key!==selectedStep;
  byId('folder-scan-panel').hidden=!view;
  byId('folder-case-bar').hidden=!view;
  byId('folder-overview').hidden=!view;
  byId('situation-display').hidden=!view;
  byId('warnings').hidden=!view;
  byId('workspace-detail').hidden=false;
  if(view)byId('folder-result-summary').textContent=`확인한 파일 ${view.summary.files}개 · 자료가 있는 업무 ${view.summary.projects}개 · 분류 확인 필요 ${view.summary.review}개 · 이번에 미확인 ${view.summary.missing||0}개`;
  for(const b of root.querySelectorAll('[data-folder-step]'))b.onclick=()=>{select(b.dataset.folderStep);byId(b.id).focus({preventScroll:true});};
  byId('folder-next').onclick=()=>{select(f.recommended,{focus:true});if(!view){byId('connect-details').open=true;const local=byId('local-folder-options');if(!local.hidden){local.open=true;byId('library-name').focus();}else{byId('folder-upload-options').open=true;byId('upload-library-name').focus();}}};
  root.querySelector('.flow-rail').onkeydown=e=>{
   if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
   const buttons=[...root.querySelectorAll('[data-folder-step]:not([disabled])')],at=buttons.findIndex(b=>b.getAttribute('aria-selected')==='true');
   const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(at+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
   e.preventDefault();select(buttons[next].dataset.folderStep);byId(buttons[next].id).focus();
  };
 }
 function render(value,{pending=false}={}){
  ensure();view=value;loading=pending;
  const id=value?.id||null;
  if(id!==libraryId){libraryId=id;selectedStep=facts().recommended;}
  if(!view)selectedStep='connect';
  paint();
 }
 render(typeof current!=='undefined'?current:null);
 return {render,select};
})();
