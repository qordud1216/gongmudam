"use strict";
Object.assign(eventNames,{LEGAL_PACK_UPDATED:"원문 재확인 기준으로 계산팩 갱신"});
function renderLegalUpdate(c) {
  const target=$("legal-pack-update"),update=c.legal_update;
  target.replaceChildren();
  if(!update?.available)return;
  target.innerHTML=`<p class="flag">이 출장의 원문 확인일은 ${escapeHtml(update.saved_verified_through)}입니다. ${escapeHtml(update.latest_verified_through)}에 다시 확인한 기준을 적용할 수 있습니다.</p><button type="button" id="preview-legal-update" class="text-button">최신 기준 변경 내용 확인</button>`;
  guarded($("preview-legal-update"),async()=>{
    const p=await api(`/cases/${c.id}/legal-pack-preview?version=${c.version}`);
    target.innerHTML=`<div class="calculation-block"><b>계산 기준 갱신</b><p>규정팩 ${escapeHtml(p.previous_version)} → ${escapeHtml(p.next_version)}<br>원문 확인 ${escapeHtml(p.previous_verified_through)} → ${escapeHtml(p.next_verified_through)}</p><p>${p.rates_unchanged?"지급 구분·금액표 단가는 동일합니다.":"금액표 연결이 달라집니다. 지급 구분과 적용 기준을 다시 확인하세요."}</p><p>${escapeHtml(p.notice)}</p><details><summary>다시 확인한 원문 ${p.source_changes.length}건</summary>${p.source_changes.map(s=>`<p><a href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.title)}</a><br>${escapeHtml(s.before_version||"신규")} → ${escapeHtml(s.after_version)}<br>확인일 ${escapeHtml(s.before_verified_on||"없음")} → ${escapeHtml(s.after_verified_on)}</p>`).join("")}</details><p>${escapeHtml(p.temporal.message)}</p><label>갱신 사유<input id="legal-update-reason" maxlength="500" value="최신 공식 원문 재확인에 따른 계산 기준 갱신"></label><label class="checkbox"><input id="legal-update-confirm" type="checkbox">변경 근거를 확인했으며, 이전 초안을 보존하고 현재 출장의 기준을 갱신합니다</label><button type="button" id="apply-legal-update" class="primary">확인한 기준 적용 · 재계산 준비</button></div>`;
    guarded($("apply-legal-update"),async()=>{
      if(!$("legal-update-confirm").checked)throw new Error("변경 근거와 초안 보존 안내를 먼저 확인하세요.");
      const next=await api(`/cases/${c.id}/legal-pack-update`,"POST",{version:c.version,preview_digest:p.preview_digest,confirmed:true,reason:$("legal-update-reason").value});
      renderCase(next);notify("최신 확인 기준을 적용했습니다. 지급 구분과 계산 조건을 다시 확인한 뒤 계산하세요.");
    });
  });
}
guarded($("legal-sample"),async()=>{
  $("organization").value="national-general"; profileInfo();
  $("situation").value="2026-10-15부터 2026-10-17까지 부산으로 2박 3일 회의출장 다녀왔어. 정산해야 해.";
  $("destination").value="부산";$("purpose").value="회의";$("start-date").value="2026-10-15";$("end-date").value="2026-10-17";$("transport").value="철도";$("overnight").value="true";$("meals").checked=false;
  notify("합성 회의출장 정보를 채웠습니다. 실제 규정 계산은 출장 저장·거래 검토 후 입력조건을 확인해 실행하세요.");
});
$("calc-scope").onchange=()=>{
  const inside=$("calc-scope").value==="inside";
  const training=$("calc-workflow").value==="training";
  $("calc-scope").options[0].textContent=training?"근무지외 교육기관":"근무지외 일반 국내출장";
  $("calc-scope").options[1].textContent=training?"근무지내 교육기관":"근무지내 당일 출장";
  $("calc-inside").hidden=!inside||training;$("calc-outside").hidden=inside;
  $("training-inputs").hidden=!training;
  refreshRateSelection();
};
$("calc-workflow").onchange=()=>$("calc-scope").onchange();
$("calc-grade").onchange=()=>{$("calc-group1-standard").checked=false;refreshRateSelection();};
$("calc-journey-area").onchange=()=>refreshRateSelection();
function markCalculationInputsChanged() {
  $("calculation-input-notice").hidden=!state.current?.calculation||Boolean(state.current.calculation.stale);
}
$("calculation-panel").addEventListener("input",markCalculationInputsChanged);
$("calculation-panel").addEventListener("change",event=>{
  if(["calc-grade","calc-workflow","calc-scope","calc-journey-area"].includes(event.target.id)) {
    $("calc-fare").checked=false;$("calc-lodging-confirm").checked=false;$("calc-confirm").checked=false;
  }
  markCalculationInputsChanged();
});
function refreshRateSelection() {
  const table=state.current?.calculation_table, grade=$("calc-grade").value;
  const rates=table?.groups?.[grade], inside=$("calc-scope").value==="inside";
  const training=$("calc-workflow").value==="training", overseas=$("calc-journey-area").value==="overseas";
  $("calc-group1-check").hidden=grade!=="group1"||inside||training||overseas;
  $("calc-fare-label").textContent=`일반 경로·지급 구분에 맞는 철도 등급${rates?`(${rates.rail_class})`:""}·할인 적용 운임 실비임을 확인했습니다`;
  [...$("calc-grade").options].find(o=>o.value==="group1").textContent=table?.groups?.group1?"별표 1 제1호 해당":"제1호 · 이 저장 건은 별도 검토";
  let description="지급 구분을 선택하면 연결된 금액표의 단가를 표시합니다.";
  if(overseas) description="국외는 별표 4의 도시·국가 등급과 환율 등 별도 조건을 확인해야 합니다. 국내 금액표로 계산하지 않습니다.";
  else if(inside) description="근무지내 당일 출장은 별표 2의 숙박·식비 합산 대신 제18조의 시간별 정액을 적용합니다. 공용차량은 1만 원 감액, 전용차량 배정자는 미지급입니다.";
  else if(rates) description=`${rates.label} · 일비 ${money(rates.daily)}/일 · 식비 ${money(rates.meal_daily)}/일 · ${rates.lodging_mode==="actual"?"숙박 실비 (제2호 지역 상한 미적용)":`숙박 상한: 서울 ${money(rates.lodging_caps.seoul)}, 광역시 ${money(rates.lodging_caps.metropolitan)}, 그 밖 ${money(rates.lodging_caps.other)}/박`}`;
  if(training&&grade==="group1") description="제1호 교육훈련은 별도 검토가 필요합니다. 일반출장 금액을 자동 적용하지 않습니다.";
  const policy=table?.validity_policy;
  const period=policy?`적용 시작 ${escapeHtml(table.coverage_start)} · 원문 확인 ${escapeHtml(table.verified_through)}<br>예정 출장 사전산정 지원: ${escapeHtml(policy.preview_until)}까지 · 종료 후 재확인 필요`:`계산 확인 기간 ${escapeHtml(table?.coverage_start)} ~ ${escapeHtml(table?.verified_through)}`;
  const coverage=table?.available?`<p class="help">규정팩 ${escapeHtml(table.version)} · ${period}${table.registered?" · 등록 별표 연결":" · 저장 당시 제2호 기준"}</p>`:"";
  $("calc-table-info").innerHTML=table?.available?`<p>${escapeHtml(description)}</p>${coverage}<details><summary>지급 구분·금액표 원문 확인</summary>${(table.basis||[]).map(basisHtml).join("")}<p class="help">${escapeHtml(table.region_note)}</p></details>`:`<p class="flag">${escapeHtml(table?.message||"검증된 계산 규정팩을 먼저 확인하세요.")}</p>`;
  document.querySelectorAll(".night-region").forEach(select=>{
    [...select.options].forEach(option=>{
      if(!option.value)return;
      const label=table?.regions?.[option.value]||option.value;
      option.textContent=label+(rates?(rates.lodging_mode==="actual"?" · 실비":` · 상한 ${money(rates.lodging_caps[option.value])}`):"");
    });
  });
}
guarded($("fill-training-dates"),async()=>{
  const t=state.current.trip_json,days=[];let day=new Date(t.start_date+"T00:00:00Z");
  while(day.toISOString().slice(0,10)<=t.end_date){days.push(day.toISOString().slice(0,10));day.setUTCDate(day.getUTCDate()+1);}
  $("training-dates").value=days.join(", ");notify("교육기관 일정과 대조해 교육이 없는 날을 삭제하세요. 휴일·전후 이동이 있는 과정은 별도 검토합니다.");
});
function nightRows(nights) {
  $("lodging-nights").innerHTML=nights.map(n=>`<div class="night-row"><label>숙박일<input type="date" class="night-date" value="${escapeHtml(n.night)}"></label><label>실제 숙박지역<select class="night-region"><option value="">지역 확인 필요</option><option value="seoul" ${n.region==="seoul"?"selected":""}>서울특별시</option><option value="metropolitan" ${n.region==="metropolitan"?"selected":""}>광역시·종전 광주광역시</option><option value="other" ${n.region==="other"?"selected":""}>그 밖의 지역·세종·제주·종전 전남 시군</option></select></label><button type="button" class="text-button remove-night">해당 밤 미청구</button></div>`).join("");
  document.querySelectorAll(".remove-night").forEach(b=>b.onclick=()=>b.closest(".night-row").remove());
  refreshRateSelection();
}
guarded($("fill-nights"),async()=>{
  const t=state.current.trip_json;
  const nights=[];let day=new Date(t.start_date+"T00:00:00Z");const end=new Date(t.end_date+"T00:00:00Z");
  const region=t.destination==="서울"?"seoul":["부산","대구","인천","대전","울산","광주"].includes(t.destination)?"metropolitan":"";
  while(day<end){nights.push({night:day.toISOString().slice(0,10),region});day.setUTCDate(day.getUTCDate()+1);}
  nightRows(nights);markCalculationInputsChanged();notify("출장기간의 밤을 채웠습니다. 실제 청구 숙박일·지역과 영수증 범위를 확인하세요.");
});
function basisHtml(ref) {
  return `<details class="rule"><summary>${escapeHtml(ref.document)} · ${escapeHtml(ref.article)}</summary><p>${escapeHtml(ref.summary)}</p><p>시행 ${escapeHtml(ref.effective_date)} · ${escapeHtml(ref.source_version)}<br>원문 확인 ${escapeHtml(ref.verified_on)}${ref.pdf_page?` · PDF ${ref.pdf_page}쪽`:""}</p><a target="_blank" rel="noopener" href="${escapeHtml(ref.url)}">공식 원문 확인</a>${ref.original_url&&ref.original_url!==ref.url?` · <a target="_blank" rel="noopener" href="${escapeHtml(ref.original_url)}">공식 별표 PDF</a>`:""} · <a href="${escapeHtml(ref.download_url)}">보존 원문 다운로드</a><p class="help">원문 SHA-256 ${escapeHtml(ref.source_sha256)}</p></details>`;
}
function resetCalculationInputs(c) {
  const input=c.calculation_inputs_reset?undefined:c.calculation?.inputs;
  const t=input?.training;
  $("calc-workflow").value=t||/교육|훈련|연수/.test(c.trip_json.purpose)?"training":"general";
  $("training-entry").value=t?.entry_date||c.trip_json.start_date;$("training-completion").value=t?.completion_date||c.trip_json.end_date;
  $("training-dates").value=(t?.teaching_dates||[]).join(", ");$("training-residential").value=String(t?.residential||false);
  $("training-dorm").checked=t?.dorm_available||false;$("training-method").value=t?.settlement_method||"actual";
  $("training-reference").value=t?.notice_reference||"";$("training-lodging").value=t?.institution_lodging??0;
  $("training-meal").value=t?.institution_meal??0;$("training-lunch").value=t?.lunch_deduction??0;
  $("training-lunch-only").checked=t?.lunch_only_provided||false;
  $("training-notice-confirmed").checked=t?.notice_confirmed||false;$("training-costs-confirmed").checked=t?.costs_confirmed||false;
  document.querySelectorAll('[name="training-zero"]').forEach(el=>el.checked=(t?.zero_items||[]).includes(el.value));
  $("calc-grade").value=input?.grade||"unconfirmed";$("calc-scope").value=input?.travel_scope||"outside";
  $("calc-journey-area").value=input?.journey_area||"domestic";$("calc-group1-standard").checked=input?.group1_standard_confirmed||false;
  $("calc-fare").checked=input?.ordinary_fare_confirmed||false;$("calc-lodging-confirm").checked=input?.lodging_scope_confirmed||false;
  $("calc-no-lodging").checked=input?.lodging_not_claimed||false;$("calc-confirm").checked=input?.conditions_confirmed||false;
  $("calc-special").checked=input?.additional_review||false;$("calc-assigned").checked=input?.assigned_vehicle||false;
  $("calc-vehicles").value=(input?.vehicle_dates||[]).join(", ");$("calc-minutes").value=input?.within_minutes||"";$("calc-km").value=input?.round_trip_km??"";
  $("calc-local-vehicle").checked=Boolean(input?.vehicle_dates?.length);nightRows(input?.lodging_nights||[]);$("calc-scope").onchange();
}
function renderCalculation(c,caseChanged) {
  $("calculation-input-notice").hidden=true;
  renderLegalUpdate(c);
  $("legal-profile").textContent=c.legal_profile?.title||"이 기관에는 검증된 계산 규정팩이 없습니다. 기관 설정에서 자료와 적용 범위를 점검하세요.";
  if(caseChanged||c.calculation_inputs_reset) resetCalculationInputs(c);
  else refreshRateSelection();
  const calc=c.calculation;
  $("calculation-total").textContent="미산정";
  if(!calc){$("calculation-result").innerHTML='<p class="help">입력조건을 확인하고 계산하면 항목별 계산식과 근거 조문을 표시합니다.</p>';return;}
  if(calc.stale){$("calculation-total").textContent=c.regulatory_hold?.length?"규정 변경 검토 필요":"재계산 필요";$("calculation-result").innerHTML='<p class="flag">'+escapeHtml(calc.stale_reason||'계산 후 출장정보·거래·검토 상태나 원문 확인 기간이 바뀌었습니다. 실제 출장 조건을 확인한 뒤 다시 계산하세요.')+'</p>'+(c.regulatory_hold?.length?'<a href="change-inbox.html#regulation-monitor">변경 알림함에서 검토하기</a>':'');return;}
  const r=calc.result;
  $("calculation-total").textContent=r.estimated_total===null?"계산 보류":money(r.estimated_total);
  $("calculation-result").innerHTML=`<p class="help">규정팩 ${escapeHtml(r.rulepack_id||"없음")} · 버전 ${escapeHtml(r.rulepack_version||"없음")}</p>`+
    (r.rate_snapshot?`<p class="help">적용 금액표: ${escapeHtml(r.rate_snapshot.group.label)} · 원화 · 표 확인 ${escapeHtml(r.rate_snapshot.checked_on)}</p>`:"")+
    (r.estimated_total!==null?`<div class="calculation-summary"><span>${r.temporal?.is_estimate?"예정 출장 · 사전산정액":"검토용 산정액 · 최종 승인 전"}</span><strong>${money(r.estimated_total)}</strong></div>`:"")+
    r.blockers.map(b=>`<div class="calculation-block"><b>확인 필요</b><p>${escapeHtml(b.message)}</p>${b.basis.map(basisHtml).join("")}</div>`).join("")+
    r.lines.map(line=>`<article class="calculation-line"><div class="tx-top"><strong>${escapeHtml(line.label)}</strong><span class="amount">${money(line.amount)}</span></div><p>${escapeHtml(line.formula)}</p>${line.details.night_rates?.length?`<p class="help">${line.details.night_rates.map(n=>`${escapeHtml(n.night)} ${escapeHtml(n.region_label)}: ${n.cap===null?"실비":`상한 ${money(n.cap)}`}`).join("<br>")}</p>`:""}${line.details.over_cap?`<p class="flag">상한 초과 ${money(line.details.over_cap)}은 자동 인정하지 않았습니다.</p>`:""}<details><summary>계산 근거 ${line.basis.length}건 · 조문·원문 확인</summary>${line.basis.map(basisHtml).join("")}</details></article>`).join("")+
    `<p class="help">${escapeHtml(r.notice)}</p>`+r.warnings.map(w=>`<p class="help">${escapeHtml(w)}</p>`).join("");
}
guarded($("calculate"),async()=>{
  const c=state.current,inside=$("calc-scope").value==="inside";
  const vehicles=inside?($("calc-local-vehicle").checked?[c.trip_json.start_date]:[]):$("calc-vehicles").value.split(/[,\s]+/).map(x=>x.trim()).filter(Boolean);
  const nights=inside?[]:[...document.querySelectorAll(".night-row")].map(el=>({night:el.querySelector(".night-date").value,region:el.querySelector(".night-region").value}));
  const body={version:c.version,grade:$("calc-grade").value,group1_standard_confirmed:$("calc-group1-standard").checked,journey_area:$("calc-journey-area").value,travel_scope:$("calc-scope").value,conditions_confirmed:$("calc-confirm").checked,ordinary_fare_confirmed:$("calc-fare").checked,lodging_scope_confirmed:$("calc-lodging-confirm").checked,lodging_not_claimed:$("calc-no-lodging").checked,lodging_nights:nights,vehicle_dates:vehicles,within_minutes:inside&&$("calc-minutes").value?Number($("calc-minutes").value):null,round_trip_km:inside&&$("calc-km").value?$("calc-km").value:null,assigned_vehicle:inside&&$("calc-assigned").checked,additional_review:$("calc-special").checked};
  if($("calc-workflow").value==="training") body.training={entry_date:$("training-entry").value,completion_date:$("training-completion").value,teaching_dates:$("training-dates").value.split(/[,\s]+/).filter(Boolean),residential:$("training-residential").value==="true",dorm_available:$("training-dorm").checked,settlement_method:$("training-method").value,institution_lodging:Number($("training-lodging").value),institution_meal:Number($("training-meal").value),lunch_deduction:Number($("training-lunch").value),notice_reference:$("training-reference").value,notice_confirmed:$("training-notice-confirmed").checked,costs_confirmed:$("training-costs-confirmed").checked,zero_items:[...document.querySelectorAll('[name="training-zero"]:checked')].map(el=>el.value)};
  if(body.training) body.training.lunch_only_provided=$("training-lunch-only").checked;
  const response=await api(`/cases/${c.id}/calculate`,"POST",body);renderCase(response);
  notify(response.calculation.result.estimated_total===null?"계산을 보류한 사유와 근거를 표시했습니다.":"입력조건에 따른 검토용 산정액·계산식·근거를 저장했습니다.");
});
