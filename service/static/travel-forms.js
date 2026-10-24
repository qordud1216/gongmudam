"use strict";
const formStatusLabels={ready:'초안 자동 채움 가능',missing:'서식 파일 미등록',overlap:'버전·적용 기간 중복',partial:'출장기간 일부만 적용'};
async function loadFormTemplates(org,bindings) {
  $("org-form-templates").hidden=org.profile_kind!=="registered";
  if(org.profile_kind!=="registered") return;
  const data=await api(`/organizations/${org.id}/form-templates`);
  $("template-name").innerHTML='<option value="">준비서식명 선택</option>'+data.required_forms.map(n=>`<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
  $("form-token-help").textContent='지원하는 채움 항목: '+data.tokens.map(t=>'{{'+t+'}}').join(' · ');
  $("form-template-list").innerHTML=data.templates.map(t=>`<details class="rule"><summary>${escapeHtml(t.name)} · ${escapeHtml(t.version)}</summary><p>시행 ${escapeHtml(t.effective_date)} ~ ${escapeHtml(t.expiry_date||'종료일 미등록')} · 종료일 미포함<br>파일 ${escapeHtml(t.filename)}<br>SHA-256 ${escapeHtml(t.sha256)}<br><a href="/api/travel/organizations/${org.id}/form-templates/${t.id}/original">보존 서식 원본 내려받기</a></p></details>`).join('')||'<p class="help">서식 파일이 없습니다. 준비서식명부터 저장하세요.</p>';
  $("form-binding-check").innerHTML=bindings.map(b=>`<p><b>${escapeHtml(b.name)}</b> · ${formStatusLabels[b.status]}${b.template?' · '+escapeHtml(b.template.version):''}</p>`).join('')||'<p class="help">기관 준비서식명 목록이 비어 있습니다.</p>';
}
function formPreviewLinks(previews) {
  return previews.length?'<section class="package-result"><b>기관 서식 자동 채움 초안</b>'+previews.map(p=>`<p><a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">${escapeHtml(p.name)} · ${escapeHtml(p.version)} 보기·인쇄</a></p>`).join('')+'<p class="help">서식 원본·자동 채움 초안은 ZIP에도 포함됩니다. 담당자 대조·승인 전 자료입니다.</p></section>':'';
}
function renderCaseForms(c) {
  const bindings=c.profile_snapshot.form_bindings||[];
  $("case-forms").hidden=!bindings.length;
  $("case-form-list").innerHTML=bindings.map(b=>`<p><b>${escapeHtml(b.name)}</b> · ${formStatusLabels[b.status]}${b.template?' · '+escapeHtml(b.template.version):''}</p>`).join('');
  $("create-form-draft").disabled=!bindings.some(b=>b.status==='ready');
}
$("create-form-draft").onclick=()=>$("draft").click();
$("form-template-upload").onsubmit=async e=>{
  e.preventDefault();const button=e.submitter;button.disabled=true;
  try {
    const org=selectedOrganization;
    if(!org||org.profile_kind!=='registered') throw Error('등록 기관을 먼저 선택하세요.');
    const file=$("template-file").files[0];if(!file) throw Error('서식 파일을 선택하세요.');
    const data=new FormData();data.append('file',file);data.append('name',$("template-name").value);data.append('version',$("template-version").value);data.append('effective_date',$("template-effective").value);
    if($("template-expiry").value) data.append('expiry_date',$("template-expiry").value);
    const response=await fetch(`/api/travel/organizations/${org.id}/form-templates`,{method:'POST',body:data});
    const result=await response.json();if(!response.ok) throw Error(typeof result.detail==='string'?result.detail:'파일과 적용 기간을 확인하세요.');
    await checkOrganization();$("template-file").value='';notify('서식 파일과 버전을 보존했습니다. 새 출장부터 적용 기간과 버전을 확인해 사본으로 저장합니다.');
  }catch(err){notify(err.message,true);}finally{button.disabled=false;}
};
