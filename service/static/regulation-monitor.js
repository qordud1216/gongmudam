"use strict";
(() => {
  const root = document.getElementById('regulation-monitor');
  if (!root) return;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = value => value ? new Date(value).toLocaleString('ko-KR') : '—';
  const stateNames = {unchanged:'변경 없음',changed:'변경 감지',failed:'확인 실패',running:'확인 중',open:'미검토',pending:'미검토',review:'검토 중',reviewing:'검토 중',deferred:'보류',acknowledged:'확인 기록',reviewed:'검토 완료',closed:'종료'};
  const allowedHosts = new Set(['law.go.kr','www.law.go.kr','www.mpm.go.kr']);
  let status = null, changes = [], runs = [], selected = null, detail = null, loading = false, timer = null, stale = false, messageState = null;
  const api = async (url, method='GET', body) => {
    const response = await fetch(url, {method, headers:body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body) : undefined});
    let data; try { data = await response.json(); } catch { data = {}; }
    if (!response.ok) { const error = new Error(response.status === 403 ? '읽기 전용입니다. 조회는 계속할 수 있습니다.' : (data.detail || '요청을 처리하지 못했습니다.')); error.status = response.status; throw error; }
    return data;
  };
  const safeUrl = value => { try { const url = new URL(value); return url.protocol === 'https:' && allowedHosts.has(url.hostname) ? url.href : ''; } catch { return ''; } };
  const link = (url,label) => { const safe=safeUrl(url); return safe ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : '<span class="rm-muted">공식 출처 링크 없음</span>'; };
  function notice(text, error=false) { messageState=text ? {text,error} : null; paintNotice(); }
  function paintNotice() { const el=root.querySelector('.rm-message'); if(!el)return; el.textContent=messageState?.text||''; el.hidden=!messageState; el.classList.toggle('is-error',!!messageState?.error); }
  function schedulePoll() { clearTimeout(timer); timer=setTimeout(poll,status?.last_run?.status==='running'?3000:60000); }
  function readonly() { return !!status?.public_read_only; }
  function render() {
    const s=status||{}; const last=s.last_run||{}; const disabled=readonly()||loading;
    root.innerHTML=`<section class="rm-panel"><div class="rm-head"><div><span class="rm-kicker">출장정산 기준 9종</span><h2>출장 기준 변경 확인</h2></div><button class="rm-button rm-primary" data-action="check" ${disabled||last.status==='running'?'disabled':''}>지금 확인</button></div>
      <p class="rm-notice">확인 기간은 전체 원문이 같을 때만 자동 갱신합니다. 개정 기준은 검토 후 별도 반영합니다.</p><p class="rm-message" role="status" aria-live="polite" hidden></p>
      <div class="rm-stats"><div><span>최근 확인</span><strong>${esc(date(last.finished_at||last.started_at))}</strong></div><div><span>확인 기준일</span><strong>${esc(s.active_pack?.verified_through||last.verified_through||'—')}</strong></div><div><span>다음 확인</span><strong>${esc(date(s.next_check_at))}</strong></div><div><span>상태</span><strong>${esc(stateNames[last.status]||last.status||'대기')}</strong></div></div>
      ${last.summary?`<p class="rm-summary">${esc(last.summary)}</p>`:''}${last.error?`<p class="rm-error">${esc(last.error)}</p>`:''}
      <form class="rm-settings"><label class="rm-toggle"><input type="checkbox" name="enabled" ${s.enabled?'checked':''} ${disabled?'disabled':''}> 자동 확인 사용</label><label>확인 간격 <select name="interval_hours" ${disabled?'disabled':''}>${[6,12,24,168].map(n=>`<option value="${n}" ${Number(s.interval_hours)===n?'selected':''}>${n===168?'매주':`${n}시간마다`}</option>`).join('')}</select></label><button class="rm-button" type="submit" ${disabled?'disabled':''}>설정 저장</button></form>
      <div class="rm-section-head"><h3>변경 사항 <span class="rm-count">${changes.length}</span></h3><button class="rm-button rm-small" data-action="refresh">새로고침</button></div>
      <div class="rm-changes">${changes.length?changes.map(c=>`<article class="rm-card ${selected===c.id?'is-selected':''}"><button class="rm-card-title" data-action="open" data-id="${esc(c.id)}" aria-expanded="${selected===c.id}"><span>${esc(c.title)}</span><span class="rm-pill">${esc(stateNames[c.state]||c.state)}</span></button><p>${esc(c.summary||'')}</p><small>${esc(date(c.detected_at))} · 관련 출장 ${Number(c.affected_count)||0}건 · 기록 ${esc(c.revision)}</small></article>`).join(''):'<p class="rm-empty">검토할 기준 변경이 없습니다.</p>'}</div>
      ${selected&&detail?renderDetail(detail,disabled):''}<details class="rm-history"><summary>확인 이력 ${runs.length}건</summary>${runs.length?runs.map(r=>`<div class="rm-run"><strong>${esc(stateNames[r.status]||r.status)}</strong><span>${esc(date(r.started_at))}</span><p>${esc(r.summary||r.error||'')}</p></div>`).join(''):'<p>이력이 없습니다.</p>'}</details></section>`;
    root.querySelector('.rm-settings').addEventListener('submit',saveSettings);
    root.querySelectorAll('[data-action]').forEach(button=>button.addEventListener('click',onAction));
    paintNotice();
  }
  function renderDetail(d,disabled) {
    const sources=d.sources||[], affected=d.affected||[], history=d.history||[];
    const resolutionNotice=d.resolution_verified?'<div class="rm-resolution" role="status"><strong>다른 법령의 변경 · 여비 기준 동일</strong><p>여비 규정 본문과 현행 버전이 같아 오탐 보류를 해제했습니다. 원래 감지 내용은 아래에 보존합니다.</p></div>':d.resolution?'<p class="rm-error">해결 판정 근거를 다시 확인해야 합니다.</p>':'';
    return `<section class="rm-detail"><div class="rm-section-head"><h3>${esc(d.title)}</h3><span class="rm-pill">${esc(stateNames[d.state]||d.state)}</span></div>${resolutionNotice}<p>${esc(d.summary||'')}</p><p class="rm-notice">${esc(d.notice||'시행일과 적용 대상은 원문에서 확인하세요. 검토 기록만으로 새 기준이 적용되지는 않습니다.')}</p><p class="rm-muted">감지 ${esc(date(d.detected_at))} · 기록 버전 ${esc(d.revision)}</p>
      ${sources.map(src=>`<details class="rm-source" open><summary>${esc(src.title)} · ${esc(src.change_kind||'기준 변경')}</summary><p class="rm-links">${link(src.original_url,'기존 공식 기준')}　${link(src.candidate_url,'확인한 공식 기준')}</p><p class="rm-muted">${esc(src.previous_version||'—')} → ${esc(src.current_version||'—')} · ${src.comparison_complete?'비교 완료':'비교 미완료'}</p><div class="rm-diff"><div><strong>이전 내용</strong><p>${esc(src.before_text||'확인할 수 없습니다.')}</p><small>${esc(src.old_sha||'')}</small></div><div><strong>확인한 내용</strong><p>${esc(src.after_text||'확인할 수 없습니다.')}</p><small>${esc(src.new_sha||'')}</small></div></div>${(src.delta||[]).map(op=>`<p class="rm-delta"><b>${esc(op.op)}</b> ${esc(op.old||'')} ${op.new?`→ ${esc(op.new)}`:''}</p>`).join('')}</details>`).join('')}
      <details class="rm-affected"><summary>영향 가능 출장 ${affected.length}건</summary>${affected.map(a=>{const caseId=String(a.id||'');const href=/^[a-f0-9]{32}$/i.test(caseId)&&a.case_version?`travel.html?case=${caseId}#settle`:'';return `<article class="rm-trip"><strong>${esc(a.organization||'기관 미상')} · ${esc(a.destination||'목적지 미상')}</strong><p>${esc(a.purpose||'')} · ${esc(a.start_date||'')} ~ ${esc(a.end_date||'')}</p><small>${a.scope==='potential'?'영향 가능':esc(a.scope||'영향 가능')} · 계산 ${a.has_calculation?'있음':'없음'} · 초안 ${Number(a.drafts)||0}</small>${href?`<p><a href="${esc(href)}">출장 정산 열기</a></p>`:''}</article>`;}).join('')||'<p>영향 가능 출장 없음</p>'}</details>
      <form class="rm-review" data-id="${esc(d.id)}"><label>검토 메모 <textarea name="reason" rows="2" required maxlength="2000" placeholder="판단 근거를 입력하세요.">${esc(root.querySelector('.rm-review textarea')?.value||'')}</textarea></label><div class="rm-actions">${[['review','검토 시작'],['defer','보류'],['acknowledge','확인 기록'],['reopen','다시 열기']].map(([action,label])=>`<button class="rm-button ${action==='acknowledge'?'rm-primary':''}" type="button" data-action="decision" data-decision="${action}" ${disabled?'disabled':''}>${label}</button>`).join('')}</div></form>
      ${history.length?`<details><summary>검토 이력 ${history.length}건</summary>${history.map(h=>`<p>${esc(date(h.at))} · ${esc(h.action)} · ${esc(h.reason||'')}</p>`).join('')}</details>`:''}</section>`;
  }
  async function load(preserve=true) {
    if(preserve && status?.last_run?.status!=='running' && root.contains(document.activeElement) && document.activeElement.closest('form')) { schedulePoll(); return; }
    const previousId=preserve?selected:null, wasOpen=preserve?root.querySelector('.rm-history')?.open:false, reason=root.querySelector('.rm-review textarea')?.value||'';
    const disclosure=[...root.querySelectorAll('details')].map(el=>el.open), focused=document.activeElement, selection=focused?.matches?.('textarea,input[type="text"],input[type="search"]')?{start:focused.selectionStart,end:focused.selectionEnd}:null;
    try {
      const [s,c,r]=await Promise.all([api('/api/regulations/status'),api('/api/regulations/changes?state=all'),api('/api/regulations/runs?limit=20')]);
      status=s; changes=c.changes||[]; runs=r.runs||[]; selected=previousId&&changes.some(x=>x.id===previousId)?previousId:null;
      if(selected) { detail=await api(`/api/regulations/changes/${encodeURIComponent(selected)}`); }
      render(); root.querySelectorAll('details').forEach((el,i)=>{if(disclosure[i]!==undefined)el.open=disclosure[i];}); const hist=root.querySelector('.rm-history'); if(hist)hist.open=!!wasOpen;
      const textarea=root.querySelector('.rm-review textarea'); if(textarea&&reason)textarea.value=reason;
      if(focused?.closest?.('form') && focused.matches('textarea,input,select')) { const replacement=root.querySelector(`form.${focused.closest('form').classList[0]} [name="${focused.name}"]`); if(replacement){replacement.focus({preventScroll:true});if(selection&&typeof replacement.setSelectionRange==='function')replacement.setSelectionRange(selection.start,selection.end);} }
      messageState=null; paintNotice();
      if(stale){notice('상태가 갱신되었습니다. 변경 내용을 확인한 뒤 다시 선택하세요.',true);stale=false;}
    } catch(e) { render(); notice(e.message,true); }
    finally { schedulePoll(); }
  }
  async function onAction(event) {
    const b=event.currentTarget, action=b.dataset.action;
    if(action==='refresh'){await load();return;}
    if(action==='open') { selected=b.dataset.id;detail=null;render();try{detail=await api(`/api/regulations/changes/${encodeURIComponent(selected)}`);render();}catch(e){notice(e.message,true);}return; }
    if(action==='check') { loading=true;render();try{await api('/api/regulations/check','POST',{});await load();notice('출장 기준 확인을 시작했습니다.');}catch(e){notice(e.message,true);}finally{loading=false;render();}return; }
    if(action==='decision') {
      const form=root.querySelector('.rm-review'), reason=form?.elements.reason.value.trim(); if(!reason){form?.elements.reason.focus();notice('검토 메모를 입력해 주세요.',true);return;}
      const decision=b.dataset.decision; loading=true; render(); try { detail=await api(`/api/regulations/changes/${encodeURIComponent(selected)}/review`,'POST',{revision:detail.revision,action:decision,reason}); await load(); notice(({review:'검토 기록을 저장했습니다.',defer:'변경 사항을 보류했습니다.',acknowledge:'확인 기록을 저장했습니다.',reopen:'변경 사항을 다시 열었습니다.'})[decision]); } catch(e) { if(e.status===409){stale=true;await load(false);} notice(e.message,true); } finally { loading=false; render(); }
    }
  }
  async function saveSettings(event) {
    event.preventDefault(); if(readonly()||loading)return;
    const form=event.currentTarget, settings={revision:status.revision,enabled:form.elements.enabled.checked,interval_hours:Number(form.elements.interval_hours.value)}; loading=true;render();
    try { await api('/api/regulations/settings','PATCH',settings); await load(); notice('확인 설정을 저장했습니다.'); }
    catch(e) { if(e.status===409){stale=true;await load(false);} notice(e.message,true); }
    finally {loading=false;render();}
  }
  async function poll() { await load(); }
  load(false);
})();
