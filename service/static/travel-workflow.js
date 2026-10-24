"use strict";
Object.assign(eventNames,{TASK_CREATED:"보완 작업·메모 등록",TASK_CHANGED:"보완 작업 처리·사유 기록"});
guarded($("search-history"),loadHistory);
$("history-query").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();loadHistory().catch(err=>notify(err.message,true));}});
guarded($("add-task"),async()=>{
  const c=state.current;
  renderCase(await api(`/cases/${c.id}/tasks`,"POST",{version:c.version,workflow_revision:c.workflow_revision,title:$("task-title").value,note:$("task-note").value}));
  $("task-title").value="";$("task-note").value="";notify("보완 작업과 메모를 저장했습니다. 새 초안을 만들면 현재 보완 상태도 보존됩니다.");
});

function renderTasks(c,caseChanged){
  if(caseChanged){$("task-title").value="";$("task-note").value="";}
  $("task-list").innerHTML=(c.tasks||[]).map(t=>`<article class="manual-task" data-task="${t.id}"><div class="tx-top"><strong>${escapeHtml(t.title)}</strong><span class="tag">${t.status==="open"?"미완료":"완료 기록"}</span></div><p class="task-note">${escapeHtml(t.note)}</p>${t.resolution?`<p class="help">최근 처리 사유: ${escapeHtml(t.resolution)}</p>`:""}<label>처리 사유<input class="task-reason" maxlength="500" placeholder="완료 근거 또는 다시 열 사유 · 5자 이상"></label><button class="secondary task-change" data-action="${t.status==="open"?"done":"reopen"}">${t.status==="open"?"완료로 기록":"다시 열기"}</button></article>`).join("")||'<p class="empty">등록한 보완 작업이 없습니다.</p>';
  document.querySelectorAll(".manual-task").forEach(el=>guarded(el.querySelector(".task-change"),async()=>{
    const c=state.current;
    renderCase(await api(`/cases/${c.id}/tasks/${el.dataset.task}`,"PATCH",{version:c.version,workflow_revision:c.workflow_revision,action:el.querySelector(".task-change").dataset.action,reason:el.querySelector(".task-reason").value}));
    notify("보완 작업의 처리 사유를 기록했습니다. 원본 확인·계산 상태는 자료에 따라 별도로 판단합니다.");
  }));
  const count=(c.tasks||[]).filter(t=>t.status==="open").length;
  if(count)$("next-actions").insertAdjacentHTML("afterbegin",`<li>보완 작업 ${count}개가 남아 있습니다. <a href="#case-tasks">작업·메모 확인</a></li>`);
}

function savedPackageHtml(check){
  return formPreviewLinks(check.form_previews||[])+`<div class="tx-top"><strong>저장한 제출 준비 묶음</strong><span class="tag">${escapeHtml(check.status)}</span></div><p>출장 버전 ${check.case_version} · ${check.file_count}개 파일 · 원본 ${check.documents.length}건</p><ul>${check.checklist.map(i=>`<li class="${i.level==="required"?"package-required":""}">${escapeHtml(i.message)}</li>`).join("")}</ul><a class="package-download" href="${escapeHtml(check.package_url)}">저장한 ZIP 내려받기</a><p class="help">저장 당시의 자료입니다. 현재 출장과 다를 수 있으며, 수정 후에는 새 초안을 만드세요.</p>`;
}

async function renderHistory(){
  const params=new URLSearchParams({q:$("history-query").value,stage:$("history-stage").value});
  const rows=await api("/cases?"+params);
  $("history-summary").textContent=`검색 결과 ${rows.length}건 · 확인 항목 ${rows.reduce((n,c)=>n+c.required_count,0)}개 · 미완료 보완 작업 ${rows.reduce((n,c)=>n+c.open_tasks,0)}개 · 상태는 실제 자료에서 자동 판단합니다.`;
  $("case-list").innerHTML=rows.map(c=>`<article class="work-case"><div class="tx-top"><div><strong>${escapeHtml(c.trip.destination)} · ${escapeHtml(c.trip.purpose)}</strong><p>${escapeHtml(c.organization)} · ${c.trip.start_date} ~ ${c.trip.end_date} · 출장 버전 ${c.version}</p></div><span class="pill ${c.stage==="handoff"?"green":"amber"}">${escapeHtml(c.stage_label)}</span></div><p class="help">보류 거래 ${c.pending_transactions}건 · 미확인 원본 ${c.unconfirmed_documents}건 · 보완 작업 ${c.open_tasks}개 · 저장 초안 ${c.draft_count}건</p><p class="queue-next">다음: ${escapeHtml(c.next_action)}</p><div class="toolbar"><button class="secondary open-case" data-id="${c.id}">이어서 검토</button><button class="text-button show-drafts" data-id="${c.id}">저장한 초안·묶음 ${c.draft_count}건</button></div><div class="saved-drafts" hidden></div></article>`).join("")||'<p class="empty">조건에 맞는 출장이 없습니다.</p>';
  document.querySelectorAll(".work-case").forEach((el,i)=>{if(rows[i].data_origin==="synthetic_demo")el.insertAdjacentHTML("afterbegin",'<p class="help"><b>합성 시연자료 · 실제 청구용 아님</b></p>');});
  document.querySelectorAll(".open-case").forEach(b=>guarded(b,async()=>{renderCase(await api(`/cases/${b.dataset.id}`));showPage("settle");notify("저장한 출장과 보완 작업을 불러왔습니다.");}));
  document.querySelectorAll(".show-drafts").forEach(b=>guarded(b,async()=>{
    const box=b.closest(".work-case").querySelector(".saved-drafts");
    if(!box.hidden){box.hidden=true;return;}
    const data=await api(`/cases/${b.dataset.id}/drafts`);box.hidden=false;
    box.innerHTML=data.drafts.map(d=>`<article class="saved-draft"><div class="tx-top"><strong>출장 ${d.case_version} · 보완 ${d.workflow_revision} 사본</strong><span class="tag">${d.is_current?"현재 내용":"이전 내용"}</span></div><p class="help">${escapeHtml(new Date(d.created_at).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"}))} · 산정액 ${d.estimated_total===null?"미산정·보류":money(d.estimated_total)}</p><div class="toolbar"><a href="${d.print_url}" target="_blank" rel="noopener">정산서 보기·인쇄</a><a href="${d.csv_url}">거래표 CSV</a><button class="secondary open-saved-package" data-draft="${d.id}">검토 목록·ZIP 열기</button></div><div class="saved-package" hidden></div></article>`).join("")||'<p class="empty">저장한 초안이 없습니다.</p>';
    box.querySelectorAll(".open-saved-package").forEach(button=>guarded(button,async()=>{
      const target=button.closest(".saved-draft").querySelector(".saved-package");target.hidden=false;
      try{target.innerHTML=savedPackageHtml(await api(`/drafts/${button.dataset.draft}/package-check`));}
      catch(e){target.textContent="묶음 확인 필요: "+e.message;}
    }));
  }));
}
