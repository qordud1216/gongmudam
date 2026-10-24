"use strict";
const $ = (id) => document.getElementById(id);
const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = n => new Intl.NumberFormat("ko-KR").format(n) + "원";
const state = { boot: null, current: null };
const categories = {transport:"교통",lodging:"숙박",meal:"식비",other:"기타"};
const decisions = {pending:"보류",include:"후보에 포함",exclude:"제외"};
const eventNames = {CASE_CREATED:"출장정보·프로필·규정 사본 저장",EVIDENCE_IMPORTED:"거래자료 분석·추가",TRANSACTION_REVIEWED:"거래 검토·사유 저장",DRAFT_CREATED:"정산서 초안 보존",PARSE_ISSUES_RESOLVED:"해석 실패 자료 확인",CALCULATION_SAVED:"규정 기준 계산·근거·입력 사본 저장"};
function notify(message, error=false) { $("message").hidden=false; $("message").className=error?"error":""; $("message").textContent=message; }
async function api(path, method="GET", body) {
  const r = await fetch("/api/travel" + path, {method,headers:body?{"Content-Type":"application/json"}:{},body:body?JSON.stringify(body):undefined});
  let data;
  try { data=await r.json(); } catch { throw Error("처리 결과를 읽지 못했습니다. 잠시 후 다시 시도해 주세요."); }
  if (!r.ok) throw Error(typeof data.detail === "string" ? data.detail : "입력값과 날짜를 확인하세요. " + (data.detail || []).map(x=>x.msg).join(" / "));
  return data;
}
function guarded(button, action) { button.addEventListener("click", async e => { e.preventDefault(); button.disabled=true; try {await action();} catch(e) {notify(e.message,true);} finally {button.disabled=false;} }); }
function showPage(page, remember=true) {
  if(remember){const url=new URL(location.href);url.hash=page;history.replaceState(null,'',url.pathname+url.search+url.hash);}
  for(const el of document.querySelectorAll(".page")) el.hidden=el.id!=="page-"+page;
  for(const el of document.querySelectorAll("[data-page]")) {
    const active=el.dataset.page===page;el.classList.toggle("active",active);
    if(active)el.setAttribute("aria-current","page");else el.removeAttribute("aria-current");
  }
  const headings={
    settle:["출장비를 확인하고 초안 만들기","출장정산","출장정보와 증빙을 모아 여비를 계산하고 정산서 초안을 만듭니다.","결과 · 정산서 초안·증빙 묶음"],
    history:["저장한 출장 이어하기","출장 업무함","처리하던 출장을 열어 남은 검토와 정산서 초안을 확인합니다.","저장한 출장·처리이력"],
    demo:["가상 자료로 사용해 보기","출장정산 연습","일반출장·교육출장·오류 탐지 사례로 정산 과정을 연습합니다.","합성 자료 · 실제 청구용 아님"],
    rules:["계산에 쓰는 기준 확인","여비 규정·근거","기관과 출장 기간에 맞는 조항을 찾고 공식 원문을 확인합니다.","원문·조항·적용 기간"],
    organizations:["소속 기관에 맞는 기준 준비","기관 설정","기관 정보와 규정 원문, 준비서식을 관리합니다.","기관별 업무환경·서식"]
  };
  const heading=headings[page],header=document.querySelector("main > header");
  if(heading&&header){header.querySelector(".eyebrow").textContent=heading[0];header.querySelector("h1").textContent=heading[1];header.querySelector("p").textContent=heading[2];header.querySelector(".purpose-output").textContent=heading[3];document.title=heading[1]+" | 서무비서";}
  document.querySelector('.travel-scope').hidden=page!=='settle';
  window.scrollTo({top:0,left:0,behavior:"instant"});
  if(page==="history") loadHistory().catch(e=>notify(e.message,true));
  if(page==="rules") loadRules().catch(e=>notify(e.message,true));
  if(page==="demo") loadDemoCenter().catch(e=>notify(e.message,true));
  if(page==="organizations") loadOrganizations().catch(e=>notify(e.message,true));
}
document.querySelectorAll("[data-page]").forEach(el=>el.onclick=e=>{
  if(e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
  e.preventDefault();
  if(location.hash==='#'+el.dataset.page)showPage(el.dataset.page,false);else location.hash=el.dataset.page;
});
function profileInfo() {
  const p=state.boot.organizations.find(x=>x.id===$("organization").value);
  $("profile-info").innerHTML=`<strong>${escapeHtml(p.personnel_type)}</strong> · ${escapeHtml(p.region)}<br>`+p.rule_packs.map(k=>`<span class="tag">${escapeHtml(state.boot.packs.find(x=>x.id===k)?.name||k)}</span>`).join("");
  $("data-mode").textContent=p.calculation_available?"공식 규정 계산 · 검토용":p.profile_kind==="registered"?"등록 기관 · 계산팩 검수 필요":"모의 기관 · 계산 미지원";
  $("work-pattern").value=p.settings?.work_pattern||"일반근무";
}
$("organization").onchange=profileInfo;
guarded($("sample"),async()=>{
  $("situation").value="2026-10-15부터 2026-10-17까지 부산으로 2박 3일 교육출장 다녀왔어. 정산해야 해.";
  $("destination").value="부산";$("purpose").value="교육";$("start-date").value="2026-10-15";$("end-date").value="2026-10-17";$("overnight").value="true";
  $("transport").value="철도";$("meals").checked=false;
  notify("합성 출장 예시를 채웠습니다. 정보를 확인하고 출장 저장을 누르세요.");
});
guarded($("extract"),async()=>{
  const r=await api("/extract","POST",{text:$("situation").value});
  if(r.intent==="unknown") {notify("출장정산으로 분류하지 못했습니다. 출장 내용을 입력하거나 아래 항목을 직접 채워 주세요.",true);return;}
  const map={destination:"destination",purpose:"purpose",start_date:"start-date",end_date:"end-date"};
  for(const [key,id] of Object.entries(map)) $(id).value=r.fields[key]||"";
  const text=$("situation").value;
  const vehicleClues=[];
  if(/개인\s*차량|자가용/.test(text)) vehicleClues.push("개인차량");
  if(/관용차|공무용\s*차량/.test(text)) vehicleClues.push("관용차");
  if(/철도|기차|열차/.test(text)) vehicleClues.push("철도");
  if(/항공|비행기/.test(text)) vehicleClues.push("항공");
  if(/버스/.test(text)) vehicleClues.push("버스");
  if(vehicleClues.length===1 && !/안\s*(했|해|하)|않았|사용\s*안|하지\s*않/.test(text)) $("transport").value=vehicleClues[0];
  const nights=text.match(/(\d+)\s*박/);
  if(nights && !/숙박\s*안|숙박하지|숙박하지\s*않|숙박\s*없/.test(text)) $("overnight").value=Number(nights[1])>0?"true":"false";
  else if(/당일/.test(text) && !/숙박\s*했|숙박\s*있/.test(text)) $("overnight").value="false";
  $("extract-result").textContent=(r.duration_text ? "기간 표현: "+r.duration_text+" · " : "")+r.notice;
  notify("확인된 정보만 채웠습니다. 빈 항목을 입력하고 날짜를 확인하세요.");
});
$("trip-form").onsubmit=async e=>{
  e.preventDefault();const button=e.submitter;button.disabled=true;
  try {
    const r=await api("/cases","POST",{organization_id:$("organization").value,work_pattern:$("work-pattern").value,destination:$("destination").value,purpose:$("purpose").value,start_date:$("start-date").value,end_date:$("end-date").value,transport:$("transport").value,overnight:$("overnight").value==="true",meals_provided:$("meals").checked});
    renderCase(r);notify("출장을 저장했습니다. 이 화면을 새로고침하거나 업무 시작의 ‘하던 업무 이어하기’에서 다시 열 수 있어요.");
  }catch(e){notify(e.message,true);}finally{button.disabled=false;}
};
guarded($("new-case"),async()=>{
  state.current=null;
  for(const link of document.querySelectorAll("a[data-toolbox-href]"))link.href=link.dataset.toolboxHref;
  const url=new URL(location.href);url.searchParams.delete('case');url.hash='settle';history.replaceState(null,'',url.pathname+url.search+url.hash);
  $("trip-form").reset();$("situation").value="";$("extract-result").textContent="";
  $("step1").closest("ol").hidden=false;$("handoff-note").hidden=true;$("setup").hidden=false;$("case-workspace").hidden=true;
  $("step1").classList.add("current");$("step2").classList.remove("current");$("step3").classList.remove("current");$("draft-result").replaceChildren();
  profileInfo();showPage('settle');$("situation").focus();notify("새 출장 정보를 입력하세요. 이전 출장은 저장되어 있어요.");
});
guarded($("evidence-sample"),async()=>{
  const t=state.current.trip_json;
  const after=new Date(t.end_date+"T00:00:00Z");after.setUTCDate(after.getUTCDate()+1);
  $("evidence").value=`${t.start_date} 08:14 코레일 52,300원 승인\n${t.start_date} 20:41 가람호텔 88,000원 승인\n${t.end_date} 17:20 코레일 52,300원 승인\n${after.toISOString().slice(0,10)} 13:21 가람카페 6,500원 승인`;
});
guarded($("edge-sample"),async()=>{
  const d=state.current.trip_json.start_date;
  $("evidence").value=`${d} 09:00 SRT 45,000원 승인\n${d} 09:00 SRT 45,000원 승인\n${d} 09:02 SRT 45,000원 승인\n${d} 09:03 SRT 45,000원 취소\n${d} 99:99 가람호텔 금액미확인`;
});
guarded($("import"),async()=>{
  const c=state.current;
  const r=await api(`/cases/${c.id}/evidence`,"POST",{version:c.version,text:$("evidence").value,source_type:$("source-type").value});
  renderCase(r);notify(`${r.import_result.inserted}건을 추가하고 같은 거래 ${r.import_result.duplicates_skipped}건을 중복 등록에서 제외했습니다. 거래별 포함·제외를 확인하세요.`);
});
function ruleHtml(r) {
  const status=r.status==="source_verified"?"공식 원문 확인":r.status==="synthetic"?"합성":"미검증";
  return `<details class="rule"><summary>${escapeHtml(r.title)} · ${escapeHtml(r.article)} <span class="tag">${status}</span></summary><p>${escapeHtml(r.article)} · ${escapeHtml(r.version)}<br>시행 ${escapeHtml(r.effective_date)} ~ ${escapeHtml(r.expiry_date||"종료일 미확인")}<br>규정팩 ${escapeHtml(r.pack_id)}</p><div class="rule-text">${escapeHtml(r.text)}</div>${r.source_url?`<p><a href="${escapeHtml(r.source_url)}" target="_blank" rel="noopener">공식 원문 열기</a><br>확인일 ${escapeHtml(r.verified_on)}<br>원문 SHA-256 ${escapeHtml(r.source_sha256)}</p>`:""}${r.user_review?provenanceHtml(r):""}</details>`;
}
function renderCase(c) {
  const caseChanged=state.current?.id!==c.id;
  const url=new URL(location.href);url.searchParams.set('case',c.id);
  if(url.hash==='#from-guidance')url.hash='settle';
  history.replaceState(null,'',url.pathname+url.search+url.hash);
  if(state.current?.id!==c.id) { $("evidence").value=""; $("source-type").value="card_sms"; }
  if(state.current?.id!==c.id || state.current?.version!==c.version || state.current?.workflow_revision!==c.workflow_revision) $("draft-result").replaceChildren();
  if(caseChanged) $("trip-editor").hidden=true;
  state.current=c;$("setup").hidden=true;$("case-workspace").hidden=false;
  $("step1").classList.remove("current");$("step2").classList.add("current");$("step3").classList.remove("current");
  const t=c.trip_json, rev=c.review;
  $("case-title").textContent=t.destination+" · "+t.purpose+" 출장";
  $("case-meta").textContent=`${c.profile_snapshot.name} / ${c.profile_snapshot.personnel_type} · ${t.start_date} ~ ${t.end_date} · ${t.transport} · ${c.profile_snapshot.work_pattern} · 버전 ${c.version}`;
  $("candidate-total").textContent=money(rev.candidate_total);$("pending-count").textContent=rev.transactions.filter(x=>x.decision==="pending").length+"건";
  $("transaction-count").textContent=rev.transactions.length+"건";
  $("next-actions").innerHTML=rev.next_actions.map(x=>`<li>${escapeHtml(x)}</li>`).join("");
  $("case-rules").innerHTML=c.rule_snapshot.map(ruleHtml).join("")||'<p class="flag">유효한 근거자료가 없습니다.</p>';
  $("parse-issues").innerHTML=c.parse_issues.map(x=>`<div class="issue">${x.line}번째 줄: ${escapeHtml(x.message)}</div>`).join("");
  if(c.parse_issues.length) {
    $("parse-issues").insertAdjacentHTML("beforeend",'<label>해석 실패 자료 처리 사유<input id="issue-reason" placeholder="수정 재입력 또는 제외한 내용을 기록하세요" maxlength="500"></label><button id="resolve-issues" class="secondary">실패 내역 확인 · 해소 기록</button>');
    guarded($("resolve-issues"),async()=>{renderCase(await api(`/cases/${c.id}/resolve-issues`,"POST",{version:state.current.version,reason:$("issue-reason").value}));notify("실패 내역과 처리 사유를 이력에 보존했습니다.");});
  }
  $("transactions").innerHTML=rev.transactions.map((r,i)=>`<article class="transaction" data-index="${i}"><div class="tx-top"><div><strong>${escapeHtml(r.merchant)}</strong><p>${r.transaction_date} ${r.transaction_time} · ${r.source_type==="card_sms"?"카드문자":"영수증 텍스트"} · 진위 미검증</p></div><span class="amount">${money(r.amount)}</span></div>${r.flags.map(f=>`<div class="flag">${escapeHtml(f)}</div>`).join("")}<div class="tx-controls"><label>분류<select class="category">${Object.entries(categories).map(([k,v])=>`<option value="${k}" ${r.category===k?"selected":""}>${v}</option>`).join("")}</select></label><label>처리<select class="decision">${Object.entries(decisions).map(([k,v])=>`<option value="${k}" ${r.decision===k?"selected":""}>${v}</option>`).join("")}</select></label><label>확인 사유<input class="reason" maxlength="500" value="${escapeHtml(r.reason)}" placeholder="예: 출장 승차내역 대조"></label><button class="secondary save">저장</button></div></article>`).join("")||'<p class="empty">아직 결제내역이 없습니다. 위에서 거래자료를 입력하세요.</p>';
  document.querySelectorAll(".transaction").forEach(el=>guarded(el.querySelector(".save"),async()=>{
    const r=state.current.review.transactions[Number(el.dataset.index)];
    const response=await api(`/cases/${c.id}/transactions/${r.id}`,"PATCH",{version:state.current.version,decision:el.querySelector(".decision").value,category:el.querySelector(".category").value,reason:el.querySelector(".reason").value});
    renderCase(response);notify("검토 결과와 사유를 기록했습니다.");
  }));
  $("case-events").innerHTML=c.events.map(x=>`<details class="event"><summary><time>${escapeHtml(new Date(x.created_at).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"}))}</time> ${eventNames[x.event_type]||escapeHtml(x.event_type)}</summary><pre>${escapeHtml(JSON.stringify(x.payload,null,2))}</pre></details>`).join("");
  $("data-mode").textContent=c.profile_snapshot.profile_kind==="registered"?"등록 기관 · 계산팩 검수 필요":c.demo?"모의 기관 · 계산 미지원":"공식 규정 계산 · 검토용";
  renderCalculation(c,caseChanged);
  renderDocuments(c,caseChanged);
  renderTasks(c,caseChanged);
  renderDemo(c);
  renderCaseForms(c);
  if(typeof renderJourney==='function')renderJourney(c);
}
guarded($("draft"),async()=>{
  const c=state.current;
  const d=await api(`/cases/${c.id}/drafts`,"POST",{version:c.version});
  const fresh=await api(`/cases/${c.id}`);renderCase(fresh);
  $("draft-result").innerHTML=`<b>검토용 초안을 보존했습니다 · 출장 버전 ${d.case_version}</b><br><a href="${d.json_url}/print" target="_blank" rel="noopener">정산서 초안 보기 · 인쇄</a><a href="${d.csv_url}">정산 준비표 CSV 다운로드</a><a href="${d.json_url}" target="_blank" rel="noopener">연계용 JSON · 근거·이력 보기</a>`;
  $("draft-result").insertAdjacentHTML("beforeend",formPreviewLinks(d.form_previews||[]));
  $("draft-result").insertAdjacentHTML("beforeend",'<section id="package-result" class="package-result"><p>정산서·증빙·근거 원문을 점검하고 있습니다.</p></section>');
  try{
    const check=await api(`/drafts/${d.id}/package-check`);
    $("package-result").innerHTML=`<div class="tx-top"><strong>제출 준비 묶음</strong><span class="tag">${escapeHtml(check.status)}</span></div><p>${check.file_count}개 파일 · 압축 전 ${(check.total_uncompressed_bytes/1024/1024).toFixed(1)}MB · 원본 ${check.documents.length}건 · 제외 원본 ${check.omitted_documents.length}건</p><p class="help">저장한 초안 기준입니다. 제외 파일은 원본을 넣지 않고 기록을 남깁니다. 이후 변경 사항은 새 초안을 만들어 반영하세요.</p><ul>${check.checklist.map(i=>`<li class="${i.level==="required"?"package-required":""}">${escapeHtml(i.message)}</li>`).join("")}</ul><a class="package-download" href="${escapeHtml(check.package_url)}">정산서·증빙 묶음 ZIP 내려받기</a><p class="help">${escapeHtml(check.notice)}</p>`;
  }catch(e){$("package-result").innerHTML=`<p class="error">묶음 생성 전 확인 필요: ${escapeHtml(e.message)}</p>`;}
  $("step2").classList.remove("current");$("step3").classList.add("current");notify("초안을 저장했습니다. 지급액 미산정·보류 상태도 함께 표시됩니다.");
});
async function loadHistory() {
  return renderHistory();
}
guarded($("reload-history"),loadHistory);
async function loadRules() {
  const params=new URLSearchParams({organization_id:$("rule-organization").value||state.current?.organization_id||$("organization").value,start_date:state.current?.trip_json.start_date||$("start-date").value||"2026-10-15",end_date:state.current?.trip_json.end_date||$("end-date").value||"2026-10-17",q:$("rule-query").value});
  const data=await api("/rules?"+params);
  $("rule-results").innerHTML=data.rules.map(ruleHtml).join("")||'<p class="empty">검색 조건에 맞는 조항이 없습니다.</p>';
}
guarded($("search-rules"),loadRules);
$("rule-form").onsubmit=async e=>{
  e.preventDefault();const button=e.submitter;button.disabled=true;
  try {await api("/rules","POST",{pack_id:$("rule-pack").value,title:$("rule-title").value,article:$("rule-article").value,text:$("rule-text").value,effective_date:$("rule-effective").value,expiry_date:$("rule-expiry").value||null,version:$("rule-version").value,status:$("rule-status").value});notify("규정 조항을 등록했습니다. 기존 출장의 규정 사본은 유지됩니다.");await loadRules();}catch(e){notify(e.message,true);}finally{button.disabled=false;}
};
async function refreshBootstrap(selected) {
  const previous=selected||$("organization").value||"national-general";
  state.boot=await api("/bootstrap");
  $("organization").innerHTML=state.boot.organizations.map(o=>`<option value="${o.id}">${escapeHtml(o.name)}</option>`).join("");
  $("organization").value=previous;
  const ruleOrg=$("rule-organization").value;
  $("rule-organization").innerHTML=$("organization").innerHTML;
  $("rule-organization").value=ruleOrg||previous;
  $("rule-pack").innerHTML=state.boot.packs.filter(p=>!p.id.startsWith("LEGAL_")).map(p=>`<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  if(!state.current) profileInfo();
}
(async()=>{try{await refreshBootstrap();
  const route=location.hash.slice(1);
  const linkedCase=new URLSearchParams(location.search).get('case');
  const hasLinkedCase=linkedCase&&/^[a-f0-9]{32}$/i.test(linkedCase);
  if(hasLinkedCase){renderCase(await api('/cases/'+encodeURIComponent(linkedCase)));showPage('settle',false);}
  if(["settle","demo","history","rules","organizations"].includes(route))showPage(route,false);
  if(route==="from-guidance"&&!hasLinkedCase){
    const handoff=SeomuFlow.take("travel");
    if(handoff){$("situation").value=handoff.text;$("handoff-note").hidden=false;$("handoff-note").textContent="서무 안내의 입력 문장을 가져왔습니다."+(handoff.today?" 안내 기준일: "+handoff.today+".":"")+" 기관·실제 출장 일정·지급 구분을 다시 확인하세요. 안내 화면의 모의 기한·규정은 정산 기준으로 적용하지 않았습니다.";$("extract").click();}
    else notify("가져올 입력 내용이 없거나 30분이 지났습니다. 출장 내용을 직접 입력하세요.");
  }
}catch(e){notify("서버에 연결하지 못했습니다. "+e.message,true);}})();

window.addEventListener("hashchange",()=>{const page=location.hash.slice(1);if(["settle","demo","history","rules","organizations"].includes(page))showPage(page,false);});
// 서로 다른 출장 URL로 돌아가면 최초 진입과 같은 경로로 복원한다.
// 같은 출장 안의 단계·근거 이동은 현재 입력을 유지한다.
window.addEventListener('popstate',()=>{
  const linkedCase=new URLSearchParams(location.search).get('case');
  if((linkedCase||null)!==(state.current?.id||null))location.reload();
});
