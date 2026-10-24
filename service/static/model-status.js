"use strict";
(() => {
  const mounts = () => [...document.querySelectorAll('[data-model-status]')];
  let seq = 0, generation = 0, snapshot = null, timer = null, initialized = false, checking = false, transientNote = "";
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const dt = s => { if (!s) return "시험 이력 없음"; const d = new Date(s); return Number.isNaN(+d) ? "시간 확인 불가" : new Intl.DateTimeFormat("ko-KR", { timeZone:"Asia/Seoul", dateStyle:"medium", timeStyle:"short" }).format(d); };
  const connectionText = c => ({ready:"서버 연결됨 · 모델 확인",offline:"오프라인 안내",external:"외부 모델",invalid:"설정 확인 필요",unreachable:"서버 연결 실패",unauthorized:"인증 확인 필요",server_error:"서버 오류",unsupported:"목록 확인 미지원",invalid_response:"서버 응답 확인 필요",model_missing:"선택 모델 없음"}[c?.state] || "연결 상태 확인 불가");
  const responseText = r => ({verified:"최근 시험 응답 확인",unverified:"시험 응답 미확인",checking:"시험 응답 확인 중",model_mismatch:"응답 모델 다름",model_unverified:"응답 모델 확인 불가",empty:"시험 응답 없음",failed:"최근 시험 실패",expired:"최근 시험 만료"}[r?.state] || "시험 응답 미확인");
  function render() {
    const c=snapshot?.connection, r=snapshot?.response;
    for (const el of mounts()) {
      const full=el.dataset.modelStatus==="full";
      const sharedChecking=!!snapshot?.check_in_progress;
      const disabled=checking || !!snapshot?.check_in_progress || !snapshot || snapshot.offline || !snapshot.local || c?.state==="external" || c?.state==="invalid";
      const buttonText=checking?"응답 기다리는 중…":sharedChecking?"다른 시험 마무리 중…":"실제 응답 확인";
      const notice=checking?"합성 시험 질문의 실제 응답을 기다리는 중입니다.":sharedChecking?"다른 탭 또는 이전 시험의 응답 확인이 마무리될 때까지 기다려 주세요.":transientNote || snapshot?.notice || (snapshot?"서버 연결 여부와 최근 시험 응답은 각각 표시됩니다.":"상태를 확인하고 있습니다.");
      el.innerHTML=`<div class="ms-head">${esc(snapshot?.profile || "선택 모델")} · ${esc(snapshot?.model || (snapshot?.offline?"모델 없는 안내":"모델 미확인"))}</div><div class="ms-line"><b>${esc(connectionText(c))}</b>${full?`<span>${esc(dt(c?.checked_at || snapshot?.checked_at))}</span>`:""}</div><div class="ms-line"><b>${esc(responseText(r))}</b>${full?`<span>${esc(dt(r?.checked_at))}${r?.elapsed_seconds!=null?` · ${esc(r.elapsed_seconds)}초`:""}${r?.characters!=null?` · ${esc(r.characters)}자`:""}</span>`:""}</div>${full&&r?.response_model?`<div class="ms-line">서버가 보고한 응답 모델: ${esc(r.response_model)}</div>`:""}${full?`<button type="button" class="secondary ms-check" ${disabled?"disabled":""}>${esc(buttonText)}</button><p class="ms-notice" role="status">${esc(notice)}</p>`:""}`;
      const b=el.querySelector(".ms-check"); if(b)b.onclick=()=>check().catch(()=>{});
    }
    window.dispatchEvent(new CustomEvent("seomu:model-status",{detail:snapshot}));
  }
  async function get(retry = true) {
    const n=++seq,g=generation;
    try {
      const res=await fetch("/api/workspace/model-status");
      if(res.status===409&&retry){await res.json().catch(()=>null);if(n===seq&&g===generation)return get(false);return null;}
      if(!res.ok)throw Error();const data=await res.json();if(n!==seq||g!==generation)return null;
      snapshot=data;transientNote="";render();return snapshot;
    }
    catch { if(n===seq&&g===generation){snapshot=null;transientNote="선택 모델 상태를 확인할 수 없습니다. 연결을 다시 확인해 주세요.";render();}return null; }
  }
  async function refresh(){ return get(); }
  function changed(){generation++;seq++;snapshot=null;transientNote="";render();try{localStorage.setItem("seomu.model.selection.changed",String(Date.now())+":"+Math.random().toString(36).slice(2));}catch{} return get();}
  async function check(expectedProfile=null){
    if(checking)return null;
    const g=generation,previousId=snapshot?.selection_id;
    checking=true;render();
    const base=await refresh();
    if(g!==generation||!base?.selection_id||(previousId&&base.selection_id!==previousId)||(expectedProfile&&base.profile!==expectedProfile)){checking=false;render();return snapshot;}
    if(base.offline||!base.local||base.connection?.state==="external"||base.connection?.state==="invalid"||base.check_in_progress){checking=false;render();return null;}
    const id=base.selection_id;
    try {
      const res=await fetch("/api/workspace/model-check",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({selection_id:id})});
      if(res.status===409){let d={};try{d=await res.json()}catch{} if(d.detail?.code==="selection_changed"){if(g===generation){await refresh();transientNote="모델 선택이 바뀌어 새 선택 상태를 다시 확인했습니다.";render();}return null;} if(d.detail?.code==="check_busy"){if(g===generation){await refresh();transientNote="다른 실제 응답 확인이 진행 중입니다. 상태를 다시 확인했습니다.";render();}return null;}}
      if(!res.ok)throw Error("실제 응답 확인을 완료하지 못했습니다.");
      await res.json(); if(g===generation)await refresh(); return snapshot;
    } catch { if(g===generation){await refresh();transientNote="실제 응답 확인을 완료하지 못했습니다. 상태를 다시 확인해 주세요.";render();}return null; }
    finally {checking=false;render();}
  }
  function init(){if(initialized){render();return;}initialized=true;const start=()=>{refresh();timer=setInterval(()=>{if(!document.hidden)refresh();},30000);window.addEventListener("focus",refresh);document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh();});window.addEventListener("storage",e=>{if(e.key==="seomu.model.selection.changed"){generation++;seq++;snapshot=null;transientNote="다른 탭에서 모델 선택이 바뀌어 다시 확인합니다.";render();refresh();}});};if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start,{once:true});else start();}
  window.SeomuModelStatus={init,refresh,changed,check};init();
})();
