"use strict";
Object.assign(eventNames,{TRIP_CHANGED:'출장정보 변경·등록자료 재검토'});
const tripFieldNames={destination:'출장지',purpose:'출장목적',start_date:'시작일',end_date:'종료일',transport:'교통수단',work_pattern:'근무형태',overnight:'숙박 여부',meals_provided:'식사 제공'};
let tripEditContext=null;
guarded($("edit-trip"),async()=>{
  const c=state.current,t=c.trip_json;
  tripEditContext={case_id:c.id,version:c.version,organization_id:c.organization_id};
  $("trip-editor").hidden=false;
  $("edit-destination").value=t.destination;$("edit-purpose").value=t.purpose;
  $("edit-start").value=t.start_date;$("edit-end").value=t.end_date;
  $("edit-transport").value=t.transport;$("edit-work").value=t.work_pattern;
  $("edit-overnight").value=String(t.overnight);$("edit-meals").checked=t.meals_provided;
  $("edit-reason").value='';$("trip-change-preview").replaceChildren();
  notify('변경 내용을 입력한 뒤 미리보기에서 기간·거래 재검토·서식 변경을 확인하세요.');
});
$("edit-cancel").onclick=()=>{$("trip-editor").hidden=true;tripEditContext=null;$("trip-change-preview").replaceChildren();};
$("trip-edit-form").addEventListener('input',()=>$("trip-change-preview").replaceChildren());
$("trip-edit-form").onsubmit=async e=>{
  e.preventDefault();const button=e.submitter;button.disabled=true;
  try {
    const context=tripEditContext;
    if(!context||context.case_id!==state.current.id) throw Error('출장을 다시 열어 수정하세요.');
    const body={organization_id:context.organization_id,version:context.version,destination:$("edit-destination").value,purpose:$("edit-purpose").value,start_date:$("edit-start").value,end_date:$("edit-end").value,transport:$("edit-transport").value,work_pattern:$("edit-work").value,overnight:$("edit-overnight").value==='true',meals_provided:$("edit-meals").checked,reason:$("edit-reason").value};
    const preview=await api(`/cases/${context.case_id}/change-preview`,'POST',body);
    const value=v=>typeof v==='boolean'?(v?'있음':'없음'):v;
    $("trip-change-preview").innerHTML=`<h3>변경 전후 확인</h3><p>${escapeHtml(preview.notice)}</p><ul>${preview.changed_fields.map(f=>`<li><b>${escapeHtml(tripFieldNames[f.field]||f.field)}</b>: ${escapeHtml(value(f.before))} → ${escapeHtml(value(f.after))}</li>`).join('')||'<li>출장 기본정보는 유지하고 기관 등록자료 사본을 갱신합니다.</li>'}</ul><p>포함 → 보류로 재검토할 거래 <b>${preview.reset_transactions.length}건</b><br>기관 설정 버전 ${preview.before.profile.settings_revision??'미기록'} → ${preview.after.profile.settings_revision}<br>규정 조항 ${preview.before.rules.length} → ${preview.after.rules.length}개</p><details><summary>기관 설정·규정·서식의 변경 전후 사본 보기</summary><pre>${escapeHtml(JSON.stringify({before:preview.before,after:preview.after},null,2))}</pre></details><label class="checkbox"><input id="edit-confirm" type="checkbox">변경 내용과 거래 재검토·재계산 필요 상태를 확인했습니다</label><button id="edit-apply" class="primary">변경 저장 · 재검토 시작</button>`;
    guarded($("edit-apply"),async()=>{
      if(!$("edit-confirm").checked) throw Error('변경 내용과 재검토 안내를 확인하세요.');
      const updated=await api(`/cases/${context.case_id}/trip`,'PATCH',{...body,confirmed:true,preview_digest:preview.preview_digest});
      renderCase(updated);resetCalculationInputs({...updated,calculation:null});
      $("trip-editor").hidden=true;tripEditContext=null;$("trip-change-preview").replaceChildren();
      notify('출장 변경을 저장했습니다. 포함 거래를 보류로 돌렸습니다. 증빙과 기간을 다시 대조하고 계산하세요.');
    });
  }catch(err){notify(err.message,true);}finally{button.disabled=false;}
};
