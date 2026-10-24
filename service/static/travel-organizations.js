"use strict";
let selectedOrganization=null;
async function loadOrganizations(selected) {
  if(!state.boot) await refreshBootstrap();
  const key=selected||$("org-select").value||$("organization").value;
  $("org-select").innerHTML=state.boot.organizations.map(o=>`<option value="${o.id}">${escapeHtml(o.name)}</option>`).join("");
  $("org-select").value=key;
  await checkOrganization();
}
async function checkOrganization() {
  const params=new URLSearchParams({start_date:$("org-start").value,end_date:$("org-end").value});
  const d=await api(`/organizations/${$("org-select").value}/diagnostics?${params}`);
  selectedOrganization=d.organization;
  const o=d.organization;
  await loadProvenance(o);
  await loadFormTemplates(o,d.form_bindings||[]);
  $("org-work").value=o.settings.work_pattern;
  $("org-forms").value=o.settings.required_forms.join("\n");
  $("org-note").value=o.settings.note;
  for(const input of $("org-settings-form").querySelectorAll("input,textarea,select,button")) input.disabled=o.profile_kind!=="registered";
  // All server-supplied text is escaped; registered rules never become calculation inputs.
  $("org-diagnostics").innerHTML=`<h3>${escapeHtml(o.name)}</h3><p>${escapeHtml(o.organization_type)} · ${escapeHtml(o.region)} · ${escapeHtml(o.personnel_type)} · 설정 버전 ${o.settings_revision}</p><p><b>${o.calculation_available?"배포된 계산팩 있음 · 계산 시 세부 조건 확인":"계산팩 검수 필요 · 자동 계산 미지원"}</b></p><p>기간 내 조회 ${d.rules.length}개 조항 · 버전 중복 ${d.overlaps.length}쌍</p>${d.calculation_scope?`<p>계산팩 확인 범위 ${escapeHtml(d.calculation_scope.coverage_start)} ~ ${escapeHtml(d.calculation_scope.verified_through)}</p>`:""}<ul>${d.findings.map(f=>`<li class="flag">${escapeHtml(f)}</li>`).join("")}</ul><p class="help">${escapeHtml(d.notice)}</p>${o.profile_kind==="registered"?'<button id="org-add-rule" class="secondary">이 기관 전용 규정 등록 화면</button>':""}${d.rules.map(ruleHtml).join("")}`;
  if($("org-add-rule")) guarded($("org-add-rule"),async()=>{
    $("rule-organization").value=o.id;showPage("rules");$("rule-pack").value=o.rule_packs[0];
    $("rule-results").innerHTML=d.rules.map(ruleHtml).join("")||'<p>등록된 조항이 없습니다.</p>';
    notify("전용 규정팩을 선택했습니다. 기관 설정의 적용 범위 점검에서 등록 결과를 확인하세요.");
  });
}
$("org-select").onchange=()=>checkOrganization().catch(e=>notify(e.message,true));
guarded($("org-check"),checkOrganization);
guarded($("org-use"),async()=>{
  const key=$("org-select").value;
  $("new-case").click();$("organization").value=key;profileInfo();showPage("settle");
  notify("선택한 기관으로 새 출장을 준비합니다. 저장 전 정보와 근무형태를 확인하세요.");
});
$("org-create-form").onsubmit=async e=>{
  e.preventDefault();const b=e.submitter;b.disabled=true;
  try {
    const o=await api("/organizations","POST",{name:$("org-name").value,organization_type:$("org-type").value,region:$("org-region").value,personnel_type:$("org-personnel").value});
    await refreshBootstrap(o.id);await loadOrganizations(o.id);$("org-create-form").reset();
    notify("기관과 전용 규정팩을 등록했습니다. 업무환경과 준비서식을 설정하세요. 자동 계산은 검수 전까지 지원하지 않습니다.");
  }catch(err){notify(err.message,true);}finally{b.disabled=false;}
};
$("org-settings-form").onsubmit=async e=>{
  e.preventDefault();const b=e.submitter;b.disabled=true;
  try {
    const o=selectedOrganization;
    await api(`/organizations/${o.id}/settings`,"PATCH",{revision:o.settings_revision,work_pattern:$("org-work").value,note:$("org-note").value,required_forms:$("org-forms").value.split("\n").map(s=>s.trim()).filter(Boolean)});
    await refreshBootstrap();await checkOrganization();notify("업무환경을 저장했습니다. 기존 출장 사본은 유지되며 새 출장부터 반영됩니다.");
  }catch(err){notify(err.message,true);}finally{b.disabled=selectedOrganization?.profile_kind!=="registered";}
};
