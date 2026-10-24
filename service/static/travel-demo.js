"use strict";
Object.assign(eventNames,{DEMO_PREPARED:"합성 시연자료·자동 검토 상태 준비"});

async function loadDemoCenter(){
  const data=await api("/demo-scenarios");
  $("demo-scenarios").innerHTML=data.scenarios.map(s=>`<article class="demo-scenario"><div class="tx-top"><strong>${escapeHtml(s.title)}</strong><span class="tag">${s.expected.total===null?"계산 보류 기대":money(s.expected.total)}</span></div><p>${escapeHtml(s.description)}</p><ol>${s.steps.map(t=>`<li>${escapeHtml(t)}</li>`).join("")}</ol><div class="toolbar"><button class="primary prepare-demo" data-scenario="${s.id}">${s.existing_case_id?"준비한 시연 다시 열기":"합성 시연 준비·열기"}</button><button class="text-button copy-demo" data-scenario="${s.id}">새 시연 복사본 만들기</button></div></article>`).join("");
  document.querySelectorAll(".prepare-demo,.copy-demo").forEach(b=>guarded(b,async()=>{
    const c=await api(`/demo-scenarios/${b.dataset.scenario}/prepare`,"POST",{new_copy:b.classList.contains("copy-demo")});
    renderCase(c);showPage("settle");
    if(c.prepared_draft_id){
      const id=c.prepared_draft_id;
      $("draft-result").innerHTML=`<b>저장한 합성 시연 초안 · 실제 청구용 아님</b><br><a href="/api/travel/drafts/${id}/print" target="_blank" rel="noopener">시연 정산서 보기·인쇄</a><a href="/api/travel/drafts/${id}/csv">시연 거래표 CSV</a><div class="package-result demo-saved-package">묶음 확인 중</div>`;
      try{$("draft-result").querySelector(".demo-saved-package").innerHTML=savedPackageHtml(await api(`/drafts/${id}/package-check`));}
      catch(e){$("draft-result").querySelector(".demo-saved-package").textContent="묶음 확인 필요: "+e.message;}
    }
    notify(c.scenario_reused?"기존 합성 시연을 다시 열었습니다. 변경한 내용은 그대로 유지됩니다.":"합성 시연을 준비했습니다. 기대값 비교·계산 근거·초안·묶음을 확인하세요.");
  }));
}

function demoValue(key,value){
  if(value===null||value===undefined)return "보류·미산정";
  if(typeof value==="boolean")return value?"예":"아니오";
  if(key==="status")return ({calculated_for_review:"검토용 산정",blocked:"계산 보류"})[value]||value;
  if(["total","transport","daily","meal","lodging"].includes(key))return money(value);
  return String(value);
}

function renderDemo(c){
  const synthetic=c.data_origin==="synthetic_demo";
  $("synthetic-notice").hidden=!synthetic;$("demo-check-panel").hidden=!synthetic;
  if(!synthetic){$("demo-check-result").replaceChildren();return;}
  const r=c.demo_report;
  $("demo-check-result").innerHTML=`<p><strong>${r.passed?"기대 결과와 일치합니다.":"기대 결과와 다른 항목이 있습니다. 변경 사항을 확인하세요."}</strong></p><table class="demo-comparison"><thead><tr><th>확인 항목</th><th>기대값</th><th>실제 결과</th><th>비교</th></tr></thead><tbody>${r.checks.map(v=>`<tr><td>${escapeHtml(v.title)}</td><td>${escapeHtml(demoValue(v.key,v.expected))}</td><td>${escapeHtml(demoValue(v.key,v.actual))}</td><td>${v.passed?"일치":"확인 필요"}</td></tr>`).join("")}</tbody></table><p class="help">${escapeHtml(r.notice)}</p>`;
  $("data-mode").textContent="합성 시연자료 · 실제 청구용 아님";
}
