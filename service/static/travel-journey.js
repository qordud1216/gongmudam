"use strict";
// 기존 작업 영역을 이동해 사용한다. 입력·원본·계산·초안 처리는 기존 기능을 유지한다.
const journeyState={caseId:null,selected:'trip',tab:'action',data:null,request:0};
const journeyNoteDrafts=new Map();
let journeyNoteRequest=0;
const journeySteps=[['trip','출장 확인'],['evidence','증빙 수집'],['review','거래 검토'],['calculate','여비 계산'],['draft','서식·초안'],['handoff','제출 준비']];
const journeyActions={trip:'저장한 기관과 실제 출장 일정을 확인하세요.',evidence:'카드문자를 붙여 넣거나 영수증 파일을 등록하세요.',review:'거래별로 포함·제외를 정하고 확인 사유를 남기세요.',calculate:'지급 구분과 실제 이용 조건을 확인하고 계산하세요.',draft:'검토한 내용으로 정산서 초안을 저장하세요.',handoff:'남은 보완사항을 확인하고 저장한 초안과 증빙을 검사하세요.'};
const journeyNotes={
 trip:['출장 목적과 실제 일정부터 맞추기','회의출장과 교육기관 입교는 확인할 조건이 다릅니다. 출장명령·실제 일정과 저장된 업무 유형을 먼저 대조하세요.'],
 evidence:['문자와 영수증이 같은 결제인지 확인하기','카드문자와 영수증을 각각 등록했다면 동일 거래 연결 여부를 확인하세요. 원본 파일 등록과 거래 포함 처리는 별도입니다.'],
 review:['유사 거래를 중복으로 단정하지 않기','날짜·금액·상호가 비슷해도 서로 다른 결제일 수 있습니다. 원본과 취소 여부를 대조하고 포함·제외 사유를 남기세요.'],
 calculate:['바뀐 자료로 다시 계산하기','출장 일정·거래·원본을 바꾸면 이전 계산이 재계산 대상으로 표시될 수 있습니다. 현재 입력 조건과 계산 근거를 다시 확인하세요.'],
 draft:['기관 서식 버전과 초안 버전을 함께 확인하기','현재 출장·보완 내용과 저장한 초안이 같은지 확인하세요. 초안 저장 뒤에 바꾼 내용은 이전 사본에 반영되지 않습니다.'],
 handoff:['다운로드 전에 저장 원본까지 검사하기','검토 목록과 저장된 ZIP의 기준 버전을 확인하세요. 원본 누락·해시 불일치는 묶음 검사를 통해 확인하고 담당자에게 보완사항을 전달하세요.']
};
const journeyRulePatterns={trip:/제3조|제5조|제7조|별표 1/,evidence:/제8조의2|제12조|제13조|제15조/,review:/제8조의2|제7조|제16조|비고/,calculate:/.*/,draft:/제8조의2|제16조|정산/,handoff:/제8조의2|제16조|정산/};

function ensureJourney(){
 if($('journey-work'))return;
 const workspace=$('case-workspace'),grid=workspace.querySelector('.work-grid');
 const shell=document.createElement('div');shell.id='journey-work';shell.className='journey-layout';
 shell.innerHTML='<div id="journey-panes"></div><details class="panel journey-context"><summary>이 단계의 근거·서식·메모 보기</summary><h2 id="journey-context-title"></h2><div class="journey-tabs" role="tablist" aria-label="단계 참고자료"><button id="journey-tab-action" role="tab" data-journey-tab="action" aria-controls="journey-context-body">할 일 안내</button><button id="journey-tab-basis" role="tab" data-journey-tab="basis" aria-controls="journey-context-body">법령·지침</button><button id="journey-tab-practice" role="tab" data-journey-tab="practice" aria-controls="journey-context-body">경험·주의</button><button id="journey-tab-forms" role="tab" data-journey-tab="forms" aria-controls="journey-context-body">서식·증빙</button></div><div id="journey-context-body" role="tabpanel"></div></details>';
 grid.before(shell);
 for(const [key,title] of journeySteps){
  const pane=document.createElement('section');pane.id='journey-pane-'+key;pane.className='journey-pane';pane.setAttribute('role','tabpanel');pane.setAttribute('aria-labelledby','journey-step-'+key);pane.hidden=true;
  $('journey-panes').append(pane);
 }
 $('journey-pane-trip').innerHTML='<section class="panel"><div class="section-heading"><div><span class="section-kicker">저장한 출장정보</span><h2>기관과 실제 일정을 대조하세요.</h2></div></div><div id="journey-trip"></div><button id="journey-edit" class="secondary">출장정보 수정 · 자료 재검토</button></section>';
 $('journey-edit').onclick=()=>{$('edit-trip').click();$('trip-editor').scrollIntoView({block:'start'});};
 const moves={evidence:[$('evidence-panel'),$('receipt-file').closest('section.panel')],review:[$('transactions-panel')],calculate:[$('calculation-panel')],draft:[$('draft-panel'),$('case-forms')],handoff:[$('case-tasks'),$('case-events').closest('section.panel'),$('next-actions').closest('section.panel')]};
 for(const [key,nodes] of Object.entries(moves))for(const node of nodes)$('journey-pane-'+key).append(node);
 const saved=document.createElement('section');saved.className='panel';saved.innerHTML='<h2>저장한 초안과 제출 준비 묶음</h2><p class="help">현재 내용과 과거 사본을 구분하고, 원본·규정 파일을 실제로 검사합니다. 묶음 검사는 기관 승인과 별도입니다.</p><div id="journey-saved-drafts"></div>';
 $('journey-pane-handoff').prepend(saved);
 const allRules=$('case-rules'),fold=document.createElement('details');fold.className='journey-all-rules';fold.innerHTML='<summary>저장 당시 전체 근거자료 보기</summary>';allRules.before(fold);fold.append(allRules);
 grid.hidden=true;workspace.querySelector('.case-section-links').hidden=true;
 for(const b of shell.querySelectorAll('[data-journey-tab]'))b.onclick=()=>{journeyState.tab=b.dataset.journeyTab;paintJourneyContext();};
}

function selectJourneyStep(key){
 if(!journeySteps.some(([id])=>id===key))return;
 journeyState.selected=key;
 for(const pane of document.querySelectorAll('.journey-pane'))pane.hidden=pane.id!=='journey-pane-'+key;
 for(const b of document.querySelectorAll('[data-journey-step]')){
  const selected=b.dataset.journeyStep===key;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;b.classList.toggle('selected',selected);
 }
 const step=journeyState.data?.steps.find(s=>s.id===key);
 $('journey-current-title').textContent=(journeySteps.findIndex(([id])=>id===key)+1)+'. '+journeySteps.find(([id])=>id===key)[1];
 $('journey-current-action').textContent=journeyActions[key];
 $('journey-reason').textContent=step?step.reason:'저장 상태를 확인하고 있습니다.';
 paintJourneyContext();
}

function paintJourneyContext(){
 const c=state.current;if(!c)return;
 const key=journeyState.selected,title=journeySteps.find(([id])=>id===key)[1],tab=journeyState.tab;
 $('journey-context-title').textContent=title+' · 참고자료';
 $('journey-work').dataset.tab=tab;
 for(const b of document.querySelectorAll('[data-journey-tab]'))b.setAttribute('aria-selected',String(b.dataset.journeyTab===tab));
 $('journey-context-body').setAttribute('aria-labelledby','journey-tab-'+tab);
 let html='';
 if(tab==='action'){
  const step=journeyState.data?.steps.find(s=>s.id===key);
  html=`<p class="journey-callout">${escapeHtml(step?.reason||'자료 상태를 확인하고 있습니다.')}</p><p>현재 단계의 작업 영역에서 입력·대조·저장을 진행하세요.</p><p class="help">법령·지침, 경험·주의, 서식·증빙 탭에서 같은 단계의 참고자료를 확인할 수 있습니다. 단계 이동은 처리 완료로 기록하지 않습니다.</p>`;
 }else if(tab==='basis'){
  const rules=c.rule_snapshot.filter(r=>journeyRulePatterns[key].test(r.article||''));
  html='<p class="help">저장 당시 조항 사본 중 이 단계에서 함께 확인할 자료입니다. 합성·미검증 표시와 적용 대상을 확인하세요.</p>';
  html+=rules.map(ruleHtml).join('')||'<p class="empty">이 단계에 연결된 조항이 없습니다. 기관 지침과 전체 근거자료를 확인하세요.</p>';
  if(key==='calculate'){
   const calc=c.calculation;
   if(calc&&!calc.stale){
    const refs=[...(calc.result.lines||[]),...(calc.result.blockers||[])].flatMap(line=>line.basis||[]),seen=new Set();
    const unique=refs.filter(ref=>{const id=[ref.document,ref.article,ref.source_version].join('|');if(seen.has(id))return false;seen.add(id);return true;});
    if(unique.length)html='<p class="help">현재 저장된 계산의 항목·보류 사유에 직접 연결된 근거입니다. 계산식과 입력은 위의 계산 작업 영역에서 확인하세요.</p>'+unique.map(basisHtml).join('');
   }
   html='<p class="journey-callout">'+(calc?.stale?'변경 전 계산입니다. 현재 입력으로 재계산한 뒤 적용 근거를 확인하세요.':'위의 계산 결과에서 항목별 산식과 직접 연결된 근거를 확인하세요.')+'</p>'+html;
  }
 }else if(tab==='practice'){
  const note=journeyNotes[key];
  html=`<span class="pill amber">합성 실무 점검 예시</span><h3>${escapeHtml(note[0])}</h3><p>${escapeHtml(note[1])}</p><p class="help">앱의 검토 흐름을 설명하는 예시입니다. 실제 기관 경험·공식 규정·승인 기준과 구분합니다. 작성 기준 2026-10-19.</p>
  <hr><h3>이 단계의 내 기록</h3><p class="help">이 출장에만 저장하는 사용자 기록입니다. 공식 근거·지급 승인으로 사용하지 않으며 정산서·제출 ZIP에는 포함하지 않습니다. 개인정보는 적지 마세요. 수정 사항은 새 기록으로 남깁니다. 아래 기록에서 보완 작업으로 연결할 수 있습니다.</p>
  <form id="journey-note-form"><label for="journey-note-title">기록 제목</label><input id="journey-note-title" minlength="2" maxlength="120" required><label for="journey-note-body">경험·확인할 사항</label><textarea id="journey-note-body" minlength="5" maxlength="2000" required rows="4"></textarea><button type="submit" class="primary">현재 단계에 기록 저장</button><p id="journey-note-status" role="status"></p></form><div id="journey-note-list" aria-live="polite">저장된 기록을 확인하고 있습니다.</div>`;
 }else{
  const forms=c.profile_snapshot.form_bindings||[],names=c.profile_snapshot.settings?.required_forms||[];
  html=`<h3>기관 준비서식</h3>${names.length?'<ul>'+names.map(n=>'<li>'+escapeHtml(n)+'</li>').join('')+'</ul>':'<p class="help">이 출장 사본에 기관 준비서식명이 없습니다.</p>'}`;
  html+=forms.map(f=>`<div class="journey-resource"><strong>${escapeHtml(f.name)}</strong><span class="tag">${escapeHtml(formStatusLabels[f.status]||f.status)}</span><p class="help">${f.template?'저장 서식 버전 '+escapeHtml(f.template.version):'사용할 원본 서식 확인 필요'}</p></div>`).join('');
  html+=`<h3>이 출장의 증빙 원본</h3>${c.documents.length?c.documents.map(d=>`<div class="journey-resource"><a href="${escapeHtml(d.original_url)}">${escapeHtml(d.filename)}</a><p class="help">${d.confirmed_at?'대조·처리 기록 있음':'원본 대조 필요'}</p></div>`).join(''):'<p class="help">등록된 증빙 원본이 없습니다.</p>'}<p class="help">원본 등록은 증빙 수집, TXT 기관 서식 채움과 출력은 서식·초안 단계에서 처리합니다.</p>`;
 }
 $('journey-context-body').innerHTML=html;
 if(tab==='practice')mountJourneyNotes(c,key);
}

function mountJourneyNotes(c,stage){
 const seq=++journeyNoteRequest,form=$('journey-note-form'),title=$('journey-note-title'),body=$('journey-note-body'),status=$('journey-note-status'),list=$('journey-note-list');
 const draftKey=c.id+':'+stage,draft=journeyNoteDrafts.get(draftKey)||{title:'',body:''};
 title.value=draft.title;body.value=draft.body;
 const remember=()=>journeyNoteDrafts.set(draftKey,{title:title.value,body:body.value});
 title.oninput=remember;body.oninput=remember;
 const active=()=>seq===journeyNoteRequest&&state.current?.id===c.id&&journeyState.tab==='practice'&&journeyState.selected===stage;
 const show=data=>{
  if(!active())return;
  const notes=data.notes.filter(n=>n.stage===stage);
  list.innerHTML=notes.map(n=>`<article class="journey-resource"><span class="pill amber">사용자 기록 · 미검증</span><h4>${escapeHtml(n.title)}</h4><p class="journey-note-text">${escapeHtml(n.body)}</p><p class="help">${escapeHtml(new Date(n.created_at).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"}))} · 출장 버전 ${n.case_version}</p>${n.context_changed?'<p class="journey-callout">기록 이후 출장·증빙 또는 저장 규정 정보가 변경되었습니다. 내용을 다시 확인하세요.</p>':'<p class="help">기록 당시와 같은 출장·증빙 버전입니다. 내용의 정확성을 인증하는 표시는 아닙니다.</p>'}${journeyNoteTaskHtml(n)}</article>`).join('')||'<p class="empty">이 단계에 저장한 사용자 기록이 없습니다.</p>';
  bindJourneyNoteTasks(c,list,active);
 };
 let saving=false,initialPending=true;
 api(`/cases/${c.id}/stage-notes`).then(data=>{if(initialPending)show(data);}).catch(e=>{if(active()&&initialPending)list.textContent='기록 조회 실패: '+e.message;});
 form.onsubmit=async e=>{
  e.preventDefault();if(saving||!form.reportValidity())return;saving=true;initialPending=false;
  const button=form.querySelector('button');button.disabled=true;status.textContent='저장 중입니다.';
  try{
   await api(`/cases/${c.id}/stage-notes`,'POST',{version:c.version,stage,title:title.value,body:body.value});
   journeyNoteDrafts.delete(draftKey);
   if(active()){title.value='';body.value='';status.textContent='사용자 기록을 저장했습니다.';show(await api(`/cases/${c.id}/stage-notes`));}
  }catch(error){if(active())status.textContent='저장 실패: '+error.message;}
  finally{saving=false;button.disabled=false;}
 };
}

function journeyNoteTaskHtml(n){
 if(n.task)return `<div class="journey-callout"><strong>연결된 보완 작업 · ${n.task.status==='open'?'미완료':'완료 기록'}</strong><p>${escapeHtml(n.task.title)}</p>${n.task.resolution?'<p>처리 사유: '+escapeHtml(n.task.resolution)+'</p>':''}<button type="button" class="secondary journey-open-tasks">제출 준비에서 처리</button><p class="help">작업 완료는 원본 검증·지급 승인과 별도입니다.</p></div>`;
 const id='note-task-'+n.id;
 return `<details><summary>이 기록을 보완 작업으로 연결</summary><form class="journey-note-task" data-note="${escapeHtml(n.id)}"><p class="help">보완 버전이 바뀌므로 기존 초안은 이전 내용으로 표시됩니다. 아래에 입력한 제목·메모는 새 정산서·제출 ZIP에 포함됩니다. 원래 기록 본문은 자동 복사하지 않습니다.</p><label for="${id}-title">보완할 일</label><input id="${id}-title" class="note-task-title" required minlength="3" maxlength="180" value="${escapeHtml('[확인] '+n.title)}"><label for="${id}-body">제출 자료에 남길 메모</label><textarea id="${id}-body" class="note-task-body" maxlength="1000" rows="3"></textarea>${n.context_changed?`<label><input type="checkbox" class="note-task-context" required> 변경된 현재 출장·증빙과 기록 내용을 대조했습니다.</label>`:''}<label><input type="checkbox" class="note-task-export" required> 위 제목·메모를 보완 작업과 새 초안·제출 묶음에 남깁니다.</label><button type="submit" class="primary">보완 작업 생성·연결</button><p class="note-task-status" role="status"></p></form></details>`;
}

function bindJourneyNoteTasks(c,list,active){
 for(const b of list.querySelectorAll('.journey-open-tasks'))b.onclick=()=>{
  journeyState.tab='action';selectJourneyStep('handoff');$('case-tasks').scrollIntoView({block:'start'});
 };
 for(const form of list.querySelectorAll('.journey-note-task')){
  let busy=false;
  form.onsubmit=async e=>{
   e.preventDefault();if(busy||!form.reportValidity())return;busy=true;
   const button=form.querySelector('button'),message=form.querySelector('.note-task-status');button.disabled=true;
   try{
    const updated=await api(`/cases/${c.id}/stage-notes/${form.dataset.note}/task`,'POST',{
     version:c.version,workflow_revision:c.workflow_revision,title:form.querySelector('.note-task-title').value,
     note:form.querySelector('.note-task-body').value,context_confirmed:!!form.querySelector('.note-task-context')?.checked,
     export_confirmed:form.querySelector('.note-task-export').checked
    });
    if(state.current?.id===c.id){renderCase(updated);notify('기록을 보완 작업으로 연결했습니다. 현재 내용으로 새 초안을 만드세요.');}
   }catch(error){if(active())message.textContent='연결 실패: '+error.message;}
   finally{busy=false;button.disabled=false;}
  };
 }
}

async function renderJourney(c){
 ensureJourney();const seq=++journeyState.request,changed=journeyState.caseId!==c.id;
 if(changed){journeyState.caseId=c.id;journeyState.selected='trip';journeyState.tab='action';}
 journeyState.data=null;
 $('step1').closest('ol').hidden=true;$('journey').hidden=false;
 $('journey').innerHTML='<div class="journey-next-line"><span>출장정산 진행 순서</span><button id="journey-next" type="button" class="secondary" disabled>다음 할 일 확인 중</button></div><div id="journey-rail" class="journey-rail" role="tablist" aria-label="출장정산 전체 흐름"></div><div class="journey-current" id="journey-current" tabindex="-1"><h2 id="journey-current-title"></h2><p id="journey-current-action"></p><p id="journey-reason" role="status"></p><button id="journey-reference" type="button" class="text-button" aria-controls="journey-context-body">이 단계의 근거·서식·메모 보기 ↓</button></div><p class="journey-navigation-note">단계 선택은 화면 이동이며, 완료·승인 처리는 아닙니다.</p>';
 $('journey-rail').innerHTML=journeySteps.map(([key,title],i)=>`<button type="button" id="journey-step-${key}" role="tab" aria-controls="journey-pane-${key}" data-journey-step="${key}"><span class="journey-number">${String(i+1).padStart(2,'0')}</span><b>${title}</b><span class="journey-state">확인 중</span></button>`).join('');
 const move=key=>{journeyState.tab='action';document.querySelector('.journey-context').open=false;selectJourneyStep(key);};
 for(const b of document.querySelectorAll('[data-journey-step]'))b.onclick=()=>move(b.dataset.journeyStep);
 $('journey-rail').onkeydown=e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  const index=journeySteps.findIndex(([key])=>key===journeyState.selected);
  const next=e.key==='Home'?0:e.key==='End'?journeySteps.length-1:(index+(e.key==='ArrowRight'?1:-1)+journeySteps.length)%journeySteps.length;
  e.preventDefault();move(journeySteps[next][0]);$('journey-step-'+journeySteps[next][0]).focus();
 };
 $('journey-next').onclick=()=>{const key=journeyState.data?.recommended_step;if(!key)return;move(key);$('journey-current').focus();$('journey-current').scrollIntoView({block:'nearest'});};
 $('journey-reference').onclick=()=>{if(journeyState.tab==='action')journeyState.tab='basis';paintJourneyContext();const context=document.querySelector('.journey-context');context.open=true;context.querySelector('summary').focus();context.scrollIntoView({block:'start'});};
 const t=c.trip_json;
 $('journey-trip').innerHTML=`<dl class="journey-trip-fields"><dt>기관</dt><dd>${escapeHtml(c.profile_snapshot.name)}</dd><dt>일정</dt><dd>${escapeHtml(t.start_date)} ~ ${escapeHtml(t.end_date)}</dd><dt>출장지 · 목적</dt><dd>${escapeHtml(t.destination)} · ${escapeHtml(t.purpose)}</dd><dt>근무형태</dt><dd>${escapeHtml(c.profile_snapshot.work_pattern)}</dd><dt>적용 기준</dt><dd>${escapeHtml(c.legal_profile?.title||'공식 계산 프로필 확인 필요')}</dd></dl><p class="help">기관·규정·서식은 저장 당시의 사본을 사용합니다. 변경하면 거래와 계산을 다시 검토합니다.</p>`;
 $('journey-saved-drafts').textContent='저장한 초안 상태를 확인하고 있습니다.';
 selectJourneyStep(journeyState.selected);
 try{
  const d=await api(`/cases/${c.id}/journey`);
  if(seq!==journeyState.request||state.current?.id!==c.id)return;
  if(d.case_version!==state.current.version||d.workflow_revision!==state.current.workflow_revision)throw Error('다른 창에서 자료가 변경되었습니다. 업무함에서 다시 열어 주세요.');
  journeyState.data=d;
  $('journey-next').disabled=false;$('journey-next').textContent='다음 할 일: '+journeySteps.find(([key])=>key===d.recommended_step)[1]+' →';
  for(const step of d.steps){const b=$('journey-step-'+step.id);b.dataset.status=step.status;b.querySelector('.journey-state').textContent=step.label;}
  $('journey-saved-drafts').innerHTML=d.drafts.map(row=>`<article class="saved-draft"><div class="tx-top"><strong>출장 ${row.case_version} · 보완 ${row.workflow_revision} 사본</strong><span class="tag">${row.is_current?'현재 내용':'이전 내용'}</span></div><div class="toolbar"><a href="${escapeHtml(row.print_url)}" target="_blank" rel="noopener">정산서 보기·인쇄</a><a href="${escapeHtml(row.csv_url)}">거래표 CSV</a><button class="secondary journey-package" data-draft="${escapeHtml(row.id)}">원본·묶음 검사</button></div><div class="journey-package-result" aria-live="polite"></div></article>`).join('')||'<p class="empty">저장한 초안이 없습니다. 서식·초안 단계에서 만들 수 있습니다.</p>';
  for(const b of document.querySelectorAll('.journey-package'))guarded(b,async()=>{
   const box=b.closest('.saved-draft').querySelector('.journey-package-result');box.textContent='저장된 원본과 파일 해시를 확인하고 있습니다.';
   try{const check=await api(`/drafts/${b.dataset.draft}/package-check`);box.innerHTML=savedPackageHtml(check);}catch(e){box.textContent='묶음 검사 실패: '+e.message;}
  });
  selectJourneyStep(changed?d.recommended_step:journeyState.selected);
 }catch(e){if(seq!==journeyState.request)return;$('journey-next').disabled=true;$('journey-next').textContent='다음 할 일 확인 필요';$('journey-reason').textContent='상태 확인 필요: '+e.message;$('journey-saved-drafts').textContent='초안 상태를 확인하지 못했습니다. 기존 업무함에서도 다시 확인할 수 있습니다.';}
}

window.addEventListener('hashchange',()=>{
 let id;try{id=decodeURIComponent(location.hash.slice(1));}catch{return;}const target=document.getElementById(id),pane=target?.closest('.journey-pane');
 if(pane&&state.current){journeyState.tab='action';selectJourneyStep(pane.id.replace('journey-pane-',''));target.scrollIntoView({block:'start'});}
});
