"use strict";
window.AdHocWorkflow = (() => {
  let jobId=null,selected=null,editing=null,editorContext=null,editorEpoch=0,chosen=[],refsDirty=false,searchSequence=0;
  const byId=id=>document.getElementById(id);
  const stateLabels={add:'단계 추가',edit:'내용 수정',move:'순서 변경',archive:'추가 단계 삭제',restore:'단계 복원',complete:'완료 확인',reopen:'완료 취소'};
  const panelIds=['request-panel','upload-panel','review-panel','export-panel'];
  const panelFor={request:'request-panel',collect:'upload-panel',review:'review-panel',report:'export-panel'};
  const refKey=r=>[r.origin,r.id,r.unit||0].join(':');
  const safeLink=url=>typeof url==='string'&&(/^(https?:\/\/|\/api\/|folders\.html#)/.test(url))?url:null;
  function link(url,label){const href=safeLink(url);return href?`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`:'';}
  function historyDetail(h){
    const before=h.detail.before.steps.find(s=>s.id===h.detail.step_id),after=h.detail.after.steps.find(s=>s.id===h.detail.step_id);
    const text=(s,key)=>key==='references'?(s?.references||[]).map(r=>`${r.title} · ${r.loc} · 원문 버전 ${r.sha256.slice(0,8)}`).join('\n'):Array.isArray(s?.[key])?s[key].join('\n'):s?.[key]||'';
    if(h.action==='move')return `<p class="workflow-detail">이전 순서: ${h.detail.before.steps.filter(s=>!s.archived).map(s=>esc(s.title)).join(' → ')}<br>변경 순서: ${h.detail.after.steps.filter(s=>!s.archived).map(s=>esc(s.title)).join(' → ')}</p>`;
    if(h.action==='complete')return `<p>담당자가 완료 확인사항을 확인했어요. · ${esc(new Date(after.completed_at).toLocaleString('ko-KR'))}</p>`;
    if(h.action==='reopen')return '<p>담당자가 이 단계를 미완료로 돌렸어요.</p>';
    if(h.action==='archive'||h.action==='restore')return `<p>${h.action==='archive'?'추가 단계를 삭제 기록에 보관했어요. 복원할 수 있어요.':'추가 단계를 복원했어요. 이전에 완료한 단계라면 다시 확인해요.'}</p>`;
    return [['title','단계 이름'],['detail','할 일'],['checks','완료 확인사항'],['caution','주의점'],['references','연결 자료']].filter(([key])=>text(before,key)!==text(after,key)).map(([key,label])=>`<p class="workflow-detail"><strong>${label}</strong><br>이전: ${esc(text(before,key)||'(없음)')}<br>변경: ${esc(text(after,key)||'(없음)')}</p>`).join('');
  }
  function root(){let el=byId('education-workflow');if(!el){el=document.createElement('section');el.id='education-workflow';el.className='panel education-workflow flow-overview';(byId('adhoc-overview')||byId('adhoc-metrics')).before(el);}return el;}
  function init(){
    const input=window.SeomuFlow?.take('education');
    if(input){byId('situation').value=input.text;byId('job-title').value='교육 참석 희망자 취합';message('대화에서 입력한 내용을 가져왔어요. 교육명·일정·대상 부서를 확인해 주세요.');}
  }
  async function command(action,extra={},expected=null){
    const start=current;
    if(!start || expected && expected.id!==start.id){message('다른 업무가 열렸어요. 수정할 업무에서 단계를 다시 열어 주세요.',true);return false;}
    try{
      const updated=await api(`/jobs/${start.id}/workflow`,'PATCH',{action,revision:expected?.revision??start.workflow.revision,data_version:expected?.data_version??start.version,...extra});
      if(current?.id===start.id){if(action==='add'){const added=updated.workflow.steps.find(s=>!start.workflow.steps.some(old=>old.id===s.id));if(added)selected=added.id;}refresh(start,updated);}
      if(current?.id===start.id)message(`${stateLabels[action]} 내용을 저장했어요.`);return true;
    }catch(error){
      if(current?.id===start.id)message(error.message,true);
      if(error.message.includes('바뀌었습니다')){try{const latest=await api(`/jobs/${start.id}`);refresh(start,latest);}catch{}}
      return false;
    }
  }
  function stageFooter(){
    let el=byId('workflow-stage-detail');
    if(!el){el=document.createElement('section');el.id='workflow-stage-detail';el.className='panel flow-stage-footer';byId('export-panel').after(el);}
    return el;
  }
  function wireRail(box,steps,selectStep){
    const rail=box.querySelector('.workflow-rail');
    box.querySelectorAll('[data-step]').forEach(b=>b.onclick=()=>{selectStep(b.dataset.step);byId(b.id)?.focus({preventScroll:true});});
    rail.onkeydown=e=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
      const buttons=[...rail.querySelectorAll('[data-step]')],at=buttons.findIndex(b=>b.getAttribute('aria-selected')==='true');
      const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(at+(e.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
      e.preventDefault();selectStep(buttons[next].dataset.step);box.querySelectorAll('[data-step]')[next].focus();
    };
    const active=box.querySelector('.workflow-step.selected');
    if(active)rail.scrollLeft=Math.max(0,active.offsetLeft-rail.offsetLeft-(rail.clientWidth-active.offsetWidth)/2);
  }
  function renderGeneric(v,box,footer){
    const conflict=v.departments.filter(d=>d.conflict).length,hasCurrent=v.exports.some(e=>e.is_current);
    const next=v.summary.missing||conflict?'collect':v.summary.pending?'review':'report';
    const rows=[
      {id:'request',title:'요청·서식',status:'요청문 준비됨',instruction:'요청문과 회신 서식을 확인하고 대상 부서에 전달하세요.'},
      {id:'collect',title:'회신 취합',status:`미회신 ${v.summary.missing} · 충돌 ${conflict}`,instruction:'같은 양식의 회신 파일을 올리고, 자료 없음 회신도 기록하세요.'},
      {id:'review',title:'누락·중복 검토',status:`보류 ${v.summary.pending}건`,instruction:'취합한 행의 누락·중복을 확인하고 포함·제외 사유를 남기세요.'},
      {id:'report',title:'취합본 저장',status:hasCurrent?'현재 취합본 있음':v.can_finalize?'저장 가능':'확인 필요',instruction:'회신과 행 검토를 확인한 뒤 현재 버전의 취합본을 저장하세요.'}
    ];
    if(!rows.some(s=>s.id===selected))selected=next;
    const s=rows.find(s=>s.id===selected);
    panelIds.forEach(id=>byId(id).hidden=id!==panelFor[s.id]);footer.hidden=true;
    box.innerHTML=`<div class="flow-topline"><span>자료 취합 진행 순서</span><button type="button" class="secondary" data-next>다음 할 일: ${esc(rows.find(s=>s.id===next).title)} →</button></div>
      <nav class="workflow-rail" role="tablist" aria-label="자료 취합 단계">${rows.map((r,i)=>`<button type="button" id="workflow-step-${r.id}" class="workflow-step ${r.id===selected?'selected':''}" data-step="${r.id}" role="tab" aria-selected="${r.id===selected}" tabindex="${r.id===selected?'0':'-1'}" aria-controls="${panelFor[r.id]}"><span>${i+1}. ${r.title}</span><small>${esc(r.status)}</small></button>`).join('')}</nav>
      <div class="workflow-selected flow-current"><h2>${rows.indexOf(s)+1}. ${s.title}</h2><p class="flow-instruction">${s.instruction}</p><p class="flow-reason">${esc(s.status)}</p></div>
      <p class="flow-note">회신·검토·저장 기록을 보여줍니다. 화면 이동은 완료·제출을 뜻하지 않습니다.</p>`;
    const move=id=>{selected=id;render(current);};wireRail(box,rows,move);
    box.querySelector('[data-next]').onclick=()=>{move(next);box.querySelector('.flow-current h2').setAttribute('tabindex','-1');box.querySelector('.flow-current h2').focus();};
  }
  function render(v){
    const box=root(),rail=document.querySelector('.adhoc-rail'),footer=stageFooter();
    box.hidden=false;if(rail)rail.hidden=true;
    if(jobId!==v.id){leave();jobId=v.id;const requested=new URLSearchParams(location.search).get('step');selected=requested&&v.workflow?.steps?.some(s=>s.id===requested)?requested:(v.workflow?.next_step_id||v.workflow?.steps[0]?.id||null);}
    if(!v.workflow){renderGeneric(v,box,footer);return;}
    const w=v.workflow,steps=w.steps;
    if(!steps.some(s=>s.id===selected))selected=w.next_step_id||steps[0]?.id;
    const s=steps.find(item=>item.id===selected);
    if(!s){box.textContent='표시할 단계가 없습니다. 진행표를 다시 확인해 주세요.';footer.hidden=true;panelIds.forEach(id=>byId(id).hidden=true);return;}
    panelIds.forEach(id=>byId(id).hidden=id!==panelFor[s.kind]);footer.hidden=false;
    const next=steps.find(item=>item.id===w.next_step_id);
    const checks=s.automatic_checks.map(c=>`<li class="${c.ok?'check-ok':'check-missing'}">${c.ok?'✓':'○'} ${esc(c.text)} <small>자동 점검</small></li>`).join('');
    box.innerHTML=`<div class="flow-topline"><span>교육 취합 진행 순서 · ${w.completed_count} / ${steps.length}단계 확인</span><button type="button" class="secondary" data-next ${next?'':'disabled'}>${next?'다음 할 일: '+esc(next.title)+' →':'모든 단계 확인됨'}</button></div>
      <nav class="workflow-rail" role="tablist" aria-label="교육 취합 업무 단계">${steps.map((item,i)=>`<button type="button" id="workflow-step-${esc(item.id)}" class="workflow-step ${esc(item.status)} ${item.id===selected?'selected':''}" data-step="${esc(item.id)}" role="tab" aria-selected="${item.id===selected}" tabindex="${item.id===selected?'0':'-1'}" aria-controls="${panelFor[item.kind]||'workflow-stage-detail'}" ${item.id===selected?'aria-current="step"':''}><span>${i+1}. ${esc(item.title)}</span><small>${esc(item.status_label)}</small></button>`).join('')}</nav>
      <div class="workflow-selected flow-current"><div class="section-heading"><div><h3>${steps.indexOf(s)+1}. ${esc(s.title)}</h3><span class="workflow-status ${esc(s.status)}">${esc(s.status_label)}</span></div><details class="flow-edit-tools"><summary>단계 수정·순서</summary><div class="toolbar"><button class="secondary" data-chat-edit>대화로 수정</button><button class="secondary" data-wf="add">＋ 단계 추가</button><button class="secondary" data-wf="edit">단계 수정</button><button class="secondary" data-wf="up" ${steps[0].id===s.id?'disabled':''}>앞으로</button><button class="secondary" data-wf="down" ${steps.at(-1).id===s.id?'disabled':''}>뒤로</button>${s.kind==='custom'?'<button class="secondary" data-wf="archive">추가 단계 삭제</button>':''}</div></details></div>
      <p class="workflow-detail flow-instruction">${esc(s.detail)}</p>${s.review_reason?`<p class="workflow-warning">${esc(s.review_reason)}</p>`:''}
      ${s.blockers.length?`<div class="workflow-warning">먼저 확인해 주세요: ${s.blockers.map(esc).join(' · ')}</div>`:''}
      <button type="button" class="text-button flow-reference" data-stage-checks>완료 확인사항·근거·메모 보기 ↓</button></div>
      <p class="flow-note">단계 선택은 화면 이동입니다. 완료 확인은 아래 작업을 처리한 뒤 담당자가 직접 합니다.</p>`;
    footer.innerHTML=`<h2>${esc(s.title)} · 완료 전 확인</h2>
      ${s.kind==='intake'?`<dl class="workflow-intake"><dt>교육</dt><dd>${esc(v.settings.course)}</dd><dt>교육일 / 마감일</dt><dd>${esc(v.settings.event_date)} / ${esc(v.settings.deadline)}</dd><dt>대상 부서</dt><dd>${v.settings.departments.map(esc).join(' · ')}</dd></dl><details><summary>처음 받은 업무 요청</summary><p class="workflow-detail">${esc(v.settings.situation)}</p></details>`:''}
      <details class="workflow-annotation" ${s.kind==='intake'||s.kind==='custom'?'open':''}><summary>완료 전에 챙길 것</summary><ul class="workflow-checks">${checks}${s.checks.map(text=>`<li>□ ${esc(text)} <small>담당자 확인</small></li>`).join('')}</ul></details>
      <div class="workflow-annotations">${s.caution?`<details class="workflow-annotation"><summary>주의점 · 실무 점검 제안</summary><p class="workflow-detail">${esc(s.caution)}</p></details>`:''}<details class="workflow-annotation"><summary>서식·근거·경험 ${s.references.length}개</summary>${s.references.map(r=>`<article class="workflow-reference"><b>${esc(r.title)}</b><p class="help">${esc(r.kind)} · ${esc(r.loc)}${r.effective_date?' · 시행일 '+esc(r.effective_date):''}${r.official?' · 공식 출처 확인':''}${r.current?'':' · 원문 변경·삭제 확인 필요'}</p>${r.note?`<p class="help">${esc(r.note)}</p>`:''}<p class="workflow-detail">${esc(r.text)}</p><p>${link(r.href,'등록 원문·서식 확인')} ${link(r.source_url,'공식 원문')}</p><small>등록 시 해시: ${esc(r.sha256)}</small></article>`).join('')||'<p class="help">이 단계에 맞는 근거는 아직 연결하지 않았어요. 단계 수정에서 등록 자료를 선택할 수 있어요.</p><a href="folders.html" target="_blank">자료 등록 화면 열기 ↗</a>'}${s.kind==='request'?`<p><a href="/api/adhoc/jobs/${v.id}/template.xlsx">이 업무의 회신 서식 XLSX 받기</a></p>`:''}</details></div>
      <div class="workflow-complete">${s.status==='done'?`<p class="help">담당자 확인: ${esc(new Date(s.completed_at).toLocaleString('ko-KR'))}</p>${next&&next.id!==s.id?`<button class="secondary" data-wf-next>다음 단계: ${esc(next.title)} →</button>`:''}<button class="secondary" data-wf="reopen">완료 취소</button>`:`<label class="checkbox"><input id="workflow-confirm" type="checkbox" ${s.can_complete?'':'disabled'}> 완료 확인사항을 직접 확인했어요.</label><button class="primary" data-wf="complete" disabled>${s.status==='needs_review'?'다시 확인하고 완료':'이 단계 확인 완료'}</button>${s.completed_at?'<button class="secondary" data-wf="reopen">미완료로 돌리기</button>':''}`}</div>
      ${w.archived.length?`<details class="workflow-annotation"><summary>삭제한 추가 단계 ${w.archived.length}개</summary>${w.archived.map(item=>`<p>${esc(item.title)} <button class="secondary" data-restore="${esc(item.id)}">복원</button></p>`).join('')}</details>`:''}
      <details class="workflow-annotation"><summary>진행표 수정 이력 · ${w.revision}회</summary>${w.history.map(h=>{const before=h.detail.before.steps.find(i=>i.id===h.detail.step_id),after=h.detail.after.steps.find(i=>i.id===h.detail.step_id);return `<details class="workflow-history"><summary>${esc(stateLabels[h.action]||h.action)} · ${esc(after?.title||before?.title||'')} · ${esc(new Date(h.created_at).toLocaleString('ko-KR'))}</summary>${h.detail.source==='chat'&&h.detail.request_text?`<p class="workflow-detail">대화 요청: ${esc(h.detail.request_text)}</p>`:''}${historyDetail(h)}</details>`;}).join('')||'<p class="help">아직 수정 기록이 없어요.</p>'}</details>`;
    const move=id=>{selected=id;render(current);};wireRail(box,steps,move);
    const goToNext=()=>{if(!next)return;move(next.id);const title=box.querySelector('.flow-current h3');title.setAttribute('tabindex','-1');title.focus();title.scrollIntoView({block:'start'});};
    box.querySelector('[data-next]').onclick=goToNext;
    footer.querySelector('[data-wf-next]')?.addEventListener('click',goToNext);
    box.querySelector('[data-stage-checks]').onclick=()=>{footer.querySelector('details').open=true;footer.setAttribute('tabindex','-1');footer.focus();footer.scrollIntoView({block:'start'});};
    box.querySelector('[data-chat-edit]').onclick=()=>window.SeomuWorkflowChat?.openFromWorkflow(current);
    const confirm=byId('workflow-confirm'),complete=footer.querySelector('[data-wf="complete"]');
    if(confirm)confirm.onchange=()=>complete.disabled=!confirm.checked||!s.can_complete;
    for(const region of [box,footer]){
      region.querySelectorAll('[data-wf]').forEach(button=>guarded(button,async()=>{
        const action=button.dataset.wf;
        if(action==='edit'||action==='add'){openEditor(action==='edit'?s:null);return;}
        if(action==='up'||action==='down'){const index=steps.indexOf(s);await command('move',{step_id:s.id,before_id:action==='up'?steps[index-1].id:steps[index+2]?.id||null});return;}
        await command(action,{step_id:s.id,confirmed:action==='complete'&&confirm.checked});
      }));
    }
    footer.querySelectorAll('[data-restore]').forEach(button=>guarded(button,()=>command('restore',{step_id:button.dataset.restore})));
  }
  function openEditor(s){
    const epoch=++editorEpoch;
    editing=s;editorContext={id:current.id,revision:current.workflow.revision,data_version:current.version};chosen=(s?.references||[]).map(r=>({...r}));refsDirty=false;searchSequence++;
    let dialog=byId('workflow-editor');if(!dialog){dialog=document.createElement('dialog');dialog.id='workflow-editor';dialog.addEventListener('cancel',()=>{editorEpoch++;searchSequence++;editorContext=null;});document.body.append(dialog);}
    dialog.innerHTML=`<form id="workflow-editor-form"><div class="section-heading"><h2>${s?'단계 수정':'단계 추가'}</h2><button type="button" class="secondary" id="workflow-editor-close">닫기</button></div><p class="help">이번 업무의 진행표에 적용해요. 기본 단계의 자동 점검 조건은 유지돼요.</p><label>단계 이름<input id="wf-title" required maxlength="100" value="${esc(s?.title||'')}"></label><label>할 일<textarea id="wf-detail" maxlength="2000" rows="3">${esc(s?.detail||'')}</textarea></label><label>완료 확인사항 · 한 줄에 하나<textarea id="wf-checks" rows="3">${esc((s?.checks||[]).join('\n'))}</textarea></label><label>주의점<textarea id="wf-caution" maxlength="1500" rows="2">${esc(s?.caution||'')}</textarea></label><h3>연결 자료</h3><div id="wf-chosen"></div><div class="toolbar"><input id="wf-search" placeholder="등록 자료 제목·본문 검색" aria-label="연결할 등록 자료 검색"><button id="wf-search-button" type="button" class="secondary">자료 찾기</button></div><div id="wf-results" aria-live="polite"></div><p id="wf-editor-error" class="workflow-warning" hidden></p><button type="submit" class="primary">이번 업무에 저장</button></form>`;
    byId('workflow-editor-close').onclick=leave;paintChosen();
    byId('wf-search-button').onclick=searchReferences;
    byId('wf-search').onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing){e.preventDefault();searchReferences();}};
    guarded(byId('workflow-editor-form'),async()=>{
      const data={title:byId('wf-title').value.trim(),detail:byId('wf-detail').value,checks:byId('wf-checks').value.split('\n').map(x=>x.trim()).filter(Boolean),caution:byId('wf-caution').value};
      if(refsDirty)data.references=chosen.map(r=>({origin:r.origin,id:r.id,unit:r.unit||0,sha256:r.sha256}));
      if(editing)data.step_id=editing.id;
      const saved=await command(editing?'edit':'add',data,editorContext);
      if(epoch!==editorEpoch)return;
      if(saved)leave();else{byId('wf-editor-error').hidden=false;byId('wf-editor-error').textContent=byId('adhoc-message').textContent;}
    },'submit');dialog.showModal();
  }
  function paintChosen(){byId('wf-chosen').innerHTML=chosen.map((r,i)=>`<p>${esc(r.title)} · ${esc(r.loc)} <button type="button" class="secondary" data-remove-ref="${i}">연결 해제</button></p>`).join('')||'<p class="help">연결한 자료가 없어요. 관련 자료만 직접 선택해 주세요.</p>';
    byId('wf-chosen').querySelectorAll('[data-remove-ref]').forEach(b=>b.onclick=()=>{chosen.splice(Number(b.dataset.removeRef),1);refsDirty=true;paintChosen();});}
  async function searchReferences(){
    const seq=++searchSequence,start=editorContext?.id;if(!start||current?.id!==start)return;byId('wf-results').textContent='등록 자료를 찾고 있어요…';
    try{const options=await api(`/jobs/${start}/workflow/references?q=${encodeURIComponent(byId('wf-search').value)}`);if(seq!==searchSequence||current?.id!==start)return;
      byId('wf-results').innerHTML=options.map((r,i)=>`<article class="workflow-reference"><b>${esc(r.title)}</b><p class="help">${esc(r.kind)} · ${esc(r.loc)}</p><p>${esc(r.text.slice(0,180))}</p><button type="button" class="secondary" data-pick-ref="${i}">이 자료 연결</button></article>`).join('')||'<p class="help">맞는 등록 자료가 없어요. 자료를 등록한 뒤 다시 찾아주세요.</p>';
      byId('wf-results').querySelectorAll('[data-pick-ref]').forEach(b=>b.onclick=()=>{const r=options[Number(b.dataset.pickRef)];if(!chosen.some(old=>refKey(old)===refKey(r)))chosen.push(r);refsDirty=true;paintChosen();b.disabled=true;});
    }catch(error){if(seq===searchSequence)byId('wf-results').textContent=error.message;}
  }
  function leave(){editorEpoch++;searchSequence++;editorContext=null;const dialog=byId('workflow-editor');if(dialog?.open)dialog.close();}
  return {init,render,leave};
})();
