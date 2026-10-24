"use strict";
let provenanceState={organization_id:null,rules:[],sources:[]};
function provenanceHtml(rule) {
  const latest=rule.user_review;
  if(!latest) return '';
  const source=latest.source;
  return `<section class="issue"><b>사용자 등록 원문 · 공식 인증 아님</b><p>${escapeHtml(source.title)} · ${escapeHtml(source.issuer)}<br><a href="${escapeHtml(source.original_url)}">보존 원문 내려받기</a><br>등록 출처: ${escapeHtml(source.source_url||"주소 미등록")}<br>SHA-256 ${escapeHtml(source.sha256)}</p><p>최근 결과: ${latest.outcome==="checked"?"원문 대조 완료 기록":"보완 필요"} · 이력 ${latest.revision}</p><details><summary>대조 이력 ${(rule.review_history||[]).length}건</summary>${(rule.review_history||[]).map(r=>`<p><b>${r.outcome==="checked"?"원문 대조 완료 기록":"보완 필요"}</b> · 버전 ${r.revision}<br>${escapeHtml(r.created_at)}<br>기록자(사용자 입력): ${escapeHtml(r.reviewer)}<br>위치: ${escapeHtml(r.location)}<br>${escapeHtml(r.note)}<br>원문: ${escapeHtml(r.source.filename)} · ${escapeHtml(r.source.sha256)}</p>`).join("")}</details></section>`;
}
async function loadProvenance(org) {
  $("org-provenance").hidden=org.profile_kind!=="registered";
  if(org.profile_kind!=="registered") {provenanceState={organization_id:null,rules:[],sources:[]};return;}
  const d=await api(`/organizations/${org.id}/rule-sources`);
  const oldRule=$("review-rule").value,oldSource=$("review-source").value;
  provenanceState={...d,organization_id:org.id};
  $("rule-source-list").innerHTML=d.sources.map(s=>`<details class="rule"><summary>${escapeHtml(s.title)} · 사용자 등록 원문</summary><p>${escapeHtml(s.filename)} · ${(s.size/1024).toFixed(1)}KB · ${escapeHtml(s.issuer)}<br>출처: ${escapeHtml(s.source_url||"미등록")}<br>보존 SHA-256: ${escapeHtml(s.sha256)}<br><a href="${escapeHtml(s.original_url)}">원문 내려받기 · 직접 대조</a></p></details>`).join("")||'<p class="help">아직 보존한 원문이 없습니다.</p>';
  $("review-rule").innerHTML='<option value="">조항 선택</option>'+d.rules.map(r=>`<option value="${r.id}">${escapeHtml(r.title)} · ${escapeHtml(r.article)} · ${escapeHtml(r.version)}</option>`).join("");
  $("review-source").innerHTML='<option value="">원문 선택</option>'+d.sources.map(s=>`<option value="${s.id}">${escapeHtml(s.title)} · ${escapeHtml(s.filename)}</option>`).join("");
  if(d.rules.some(r=>r.id===oldRule)) $("review-rule").value=oldRule;
  if(d.sources.some(s=>s.id===oldSource)) $("review-source").value=oldSource;
  $("rule-review-history").innerHTML=d.rules.map(r=>`<h3>${escapeHtml(r.title)} · ${escapeHtml(r.article)}</h3>${r.user_review?provenanceHtml(r):'<p class="help">원문 대조 이력 없음</p>'}`).join("");
}
$("rule-source-form").onsubmit=async e=>{
  e.preventDefault();const b=e.submitter;b.disabled=true;
  try {
    if(!provenanceState.organization_id) throw Error("등록 기관을 먼저 선택하세요.");
    const file=$("rule-source-file").files[0];if(!file) throw Error("원문 파일을 선택하세요.");
    const form=new FormData();form.append('file',file);form.append('title',$("rule-source-title").value);form.append('issuer',$("rule-source-issuer").value);form.append('source_url',$("rule-source-url").value);
    const response=await fetch(`/api/travel/organizations/${provenanceState.organization_id}/rule-sources`,{method:'POST',body:form});
    const result=await response.json();if(!response.ok) throw Error(typeof result.detail==='string'?result.detail:'파일과 입력값을 확인하세요.');
    await checkOrganization();$("review-source").value=result.source.id;
    $("rule-source-form").reset();notify(result.duplicate?"동일 원문은 기존 보존본을 사용합니다. 최초 등록한 출처 정보가 유지됩니다.":"원문과 해시를 보존했습니다. 조항을 선택하고 대조 기록을 남기세요.");
  }catch(err){notify(err.message,true);}finally{b.disabled=false;}
};
$("rule-review-form").onsubmit=async e=>{
  e.preventDefault();const b=e.submitter;b.disabled=true;
  try {
    const rule=provenanceState.rules.find(r=>r.id===$("review-rule").value);
    if(!rule) throw Error("대조할 조항을 선택하세요.");
    await api(`/rules/${rule.id}/reviews`,'POST',{revision:rule.user_review?.revision||0,source_id:$("review-source").value,location:$("review-location").value,reviewer:$("review-author").value,outcome:$("review-outcome").value,note:$("review-note").value,original_checked:$("review-checked").checked});
    await checkOrganization();$("review-checked").checked=false;notify("대조 이력을 추가했습니다. 새 출장부터 사본에 반영하며 계산 지원 여부는 바뀌지 않습니다.");
  }catch(err){notify(err.message,true);}finally{b.disabled=false;}
};
