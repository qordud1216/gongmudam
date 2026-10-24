"use strict";
// 서무비서 화면. 빌드 도구·외부 CDN 없이 동작한다(폐쇄망 대응).
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { settings: null, forms: [], cards: [], docs: [], editingCard: null, editingForm: null };
let settingsProfileRefresh = false;
let settingsLoadSequence = 0, settingsRenderSequence = 0;

async function api(method, url, body, raw = false) {
  const opt = { method, headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* 본문 없음 */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return raw ? r : r.json();
}
const fail = (e) => alert("처리하지 못했습니다: " + e.message);

// ------------------------------------------------------------------ 좌측 메뉴 → 우측 화면
$$(".sb-item[data-view]").forEach((a) => a.addEventListener("click", () => showView(a.dataset.view)));
$("#sbUser").addEventListener("click", () => showView("settings"));
function showView(name) {
  if(!["home","chat","cards","docs","forms","settings"].includes(name)) return;
  if(location.hash!=="#"+name) history.replaceState(null,"","#"+name);
  selectView(name);
  ({ home: loadHome, chat: () => $("#query").focus(), cards: loadCards, docs: loadDocs, forms: loadForms, settings: renderSettings }[name] || (() => {}))();
}
function selectView(name) {
  $$(".sb-item").forEach((a) => {
    const active=a.dataset.view===name;a.classList.toggle("active",active);
    if(active)a.setAttribute("aria-current","page");else a.removeAttribute("aria-current");
  });
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + name));
}
$("#today").addEventListener("change", () => { if ($("#view-home").classList.contains("on")) loadHome(); });

// ------------------------------------------------------------------ 공통 데이터
async function loadSettings() {
  const request = ++settingsLoadSequence;
  const settings = await api("GET", "/api/settings");
  if (request !== settingsLoadSequence) return false;
  S.settings = settings;
  const llm = S.settings.llm;
  if (!$("#today").value) $("#today").value = S.settings.today;
  $('#uploadForm [name=kind]').innerHTML = S.settings.kinds.map((k) => `<option>${k}</option>`).join("");
  $('#uploadForm [name=layer]').innerHTML = S.settings.layers.map((k) => `<option ${k === "기관" ? "selected" : ""}>${k}</option>`).join("");
  const prof = S.settings.profile || {};
  $("#sbName").textContent = prof["성명"] || "사용자";
  $("#sbRole").textContent = [prof["소속"], prof["직급"]].filter(Boolean).join(" · ");
  $("#sbAvatar").textContent = (prof["성명"] || "?").slice(0, 1);
  window.SeomuChatOptions?.refresh();
  return true;
}
async function refreshForms() { S.forms = await api("GET", "/api/forms"); }

// ------------------------------------------------------------------ 홈: 오늘 할 일·기한
async function loadHome() {
  const r = await api("GET", "/api/home?today=" + encodeURIComponent($("#today").value || ""));
  $("#homeToday").textContent = `기준 날짜 ${r.today_text}`;
  $("#upcoming").innerHTML = r.upcoming.slice(0, 12).map((u) => `<li><div class="tl-date">${esc(u.due_text)}</div>
      <div>${esc(u.title)}<div class="tl-task">${esc(u.task)} · ${u.no}단계</div></div><span class="dday ${u.dday.state}">${esc(u.dday.label)}</span></li>`).join("")
    || `<li class="empty">기한이 있는 남은 단계가 없습니다.</li>`;
  $("#taskList").innerHTML = r.tasks.map((t) => {
    if (t.missing) return `<div class="task"><div class="task-hd"><b>${esc(t.label || t.title)}</b><button class="small danger tDel" data-id="${t.id}">삭제</button></div><p class="muted">절차 카드가 삭제되어 기한을 계산할 수 없습니다.</p></div>`;
    const bases = Object.entries(t.base_values).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(" · ");
    return `<div class="task" data-id="${t.id}"><div class="task-hd"><div><b>${esc(t.title)}</b> <span class="tag ${t.layer}">${t.layer}</span><span class="muted">진행 ${t.progress}</span></div>
        <span class="nowrap"><button class="small tAsk" data-card="${t.card_id}">자세히</button> <button class="small danger tDel" data-id="${t.id}">삭제</button></span></div>
      <div class="muted">${t.label && t.label !== t.title ? `“${esc(t.label)}” · ` : ""}${bases}</div>
      ${t.missing_bases.length ? `<div class="notice">기준일(${t.missing_bases.map(esc).join(", ")})이 없어 일부 기한을 계산하지 못했습니다.</div>` : ""}
      ${t.warnings.filter((w) => !w.includes("초안")).map((w) => `<div class="warn">⚠ ${esc(w)}</div>`).join("")}
      <ul class="task-steps">${t.steps.map((s) => `<li class="${s.done ? "done" : t.next && t.next.no === s.no ? "next" : ""}">
        <input type="checkbox" class="tDone" data-no="${s.no}" ${s.done ? "checked" : ""}><span class="t">${s.no}. ${esc(s.title)}</span>
        ${t.next && t.next.no === s.no ? '<span class="tag now">지금 할 일</span>' : ""}
        <span class="d">${esc(s.due_text || "")} ${s.due && !s.done ? `<span class="dday ${s.dday.state}">${esc(s.dday.label)}</span>` : ""}</span></li>`).join("")}</ul></div>`;
  }).join("") || `<div class="empty">등록한 업무가 없습니다.<br>‘서무비서에게 묻기’에서 안내를 받은 뒤 <b>홈에 등록</b>을 누르면 여기에서 기한을 챙겨 드립니다.</div>`;
  $$(".tDel").forEach((b) => b.onclick = async () => { if (!confirm("이 업무를 홈에서 지울까요?")) return; try { await api("DELETE", `/api/tracked/${b.dataset.id}`); loadHome(); } catch (e) { fail(e); } });
  $$(".task[data-id]").forEach((el) => {
    $$(".tDone", el).forEach((cb) => cb.onchange = async () => {
      const done = $$(".tDone:checked", el).map((x) => +x.dataset.no - 1);
      try { await api("PUT", `/api/tracked/${el.dataset.id}`, { done }); loadHome(); } catch (e) { fail(e); }
    });
    const t = r.tasks.find((x) => x.id === el.dataset.id);
    $(".tAsk", el).onclick = () => { showView("chat"); sendAsk(t.label || t.title, { cardId: t.card_id, baseValues: t.base_values }); };
  });
}
$("#quickBtn").addEventListener("click", () => { const q = $("#quickQ").value.trim(); if (!q) return; showView("chat"); if (sendAsk(q)) $("#quickQ").value = ""; });
$("#quickQ").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("#quickBtn").click(); } });

// ------------------------------------------------------------------ 서무비서에게 묻기 (대화)
let msgSeq = 0;
$$(".ex").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); sendAsk(a.textContent); }));
$("#askBtn").addEventListener("click", () => { const q = $("#query").value.trim(); if (q && sendAsk(q)) $("#query").value = ""; });
$("#query").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#askBtn").click(); } });
$("#chatClear").addEventListener("click", () => { chatRequests.clear(); greet(); });
const layers = () => $$(".layer:checked").map((c) => c.value);

function addMsg(who, html, cls = "") {
  const el = document.createElement("div");
  el.className = `msg ${who}`;
  el.innerHTML = `<div class="bubble ${cls}">${html}</div>`;
  $("#chatLog").appendChild(el);
  $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
  return $(".bubble", el);
}
function greet() {
  addMsg("bot", `<div class="answer">출장·휴가·물품 등 지금 처리할 일을 편하게 물어보세요.</div>`);
}

// 한 질문의 조건·요청 번호·표시 수명을 함께 관리한다. 재시도도 같은 요청이다.
const chatRequests = (() => {
  let busy = false, generation = 0, userTurns = [];
  const queryActions = ".alt,.leave-type,.leave-apply,[data-choice],[data-candidate],.chat-retry";
  const status = text => { $("#chat-status").textContent = text; };
  function contextNode(context) {
    const node = document.createElement("p"); node.className = "chat-request-context";
    node.textContent = `질문 기준: ${context.today || "서버 기준일"} · ${context.libraryLabel} · ${context.layers.join("·") || "선택한 규정 층 없음"}`;
    return node;
  }
  function addContext(box, context) {
    const node = contextNode(context), header = $(".bot-hd", box);
    if (header) header.after(node); else box.prepend(node);
  }
  function scrollToAnswer(box) {
    const log = $("#chatLog");
    log.scrollTop += box.getBoundingClientRect().top - log.getBoundingClientRect().top - 60;
  }
  function lock() {
    busy = true;
    const controls = [$("#askBtn"), $("#quickBtn"), ...$$(queryActions, $("#chatLog"))];
    const previous = controls.map(node => [node, node.disabled]);
    previous.forEach(([node]) => { node.disabled = true; });
    $("#askBtn").textContent = "확인 중…";
    $("#chatLog").setAttribute("aria-busy", "true");
    status("답변을 확인하고 있습니다. 다음 질문은 미리 작성해 둘 수 있습니다.");
    return () => {
      previous.forEach(([node, disabled]) => { if (node.isConnected) node.disabled = disabled; });
      $("#askBtn").textContent = "보내기";
      $("#chatLog").setAttribute("aria-busy", "false"); busy = false;
    };
  }
  async function execute(record) {
    const unlock = lock(), { box, context, body, epoch } = record;
    box.classList.add("thinking"); box.innerHTML = "등록 자료와 업무 절차를 확인하고 있습니다…";
    addContext(box, context);
    try {
      const response = record.prepared || await api("POST", "/api/ask", body);
      if (epoch !== generation || !box.isConnected) return;
      box.classList.remove("thinking"); renderAnswer(box, response, context); addContext(box, context);
      status("");
    } catch (error) {
      if (epoch !== generation || !box.isConnected) return;
      box.classList.remove("thinking");
      box.innerHTML = `<p class="err" role="alert">답변을 받지 못했습니다. ${esc(error.message)}</p><p class="muted">입력한 질문과 확인 범위를 유지해 다시 보낼 수 있습니다. 진행표 수정 요청은 같은 요청 번호를 사용합니다.</p><button type="button" class="small chat-retry">같은 조건으로 다시 시도</button>`;
      addContext(box, context);
      $(".chat-retry", box).onclick = () => { if (!busy && epoch === generation && box.isConnected) void execute(record); };
      status("질문을 다시 입력하지 않고 답변 안의 ‘다시 시도’를 누를 수 있습니다.");
    } finally {
      unlock();
      if (epoch === generation && box.isConnected) scrollToAnswer(box);
      else status("이전 요청이 끝났습니다. 작성한 질문을 보낼 수 있습니다. 업무 변경 여부는 해당 진행표에서 확인하세요.");
    }
  }
  // 클릭 시 소비되는 진행표 선택 버튼도 요청 중에는 실행하지 않는다.
  $("#chatLog").addEventListener("click", event => {
    if (busy && event.target.closest(queryActions)) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  return {
    send(query, { cardId = null, baseValues = null, leaveType = null, leaveContext = null, displayQuery = null, workflowFields = null } = {}) {
      if (busy) { status("이전 질문을 확인 중입니다. 입력한 내용은 그대로 두었습니다."); return false; }
      if (!String(query || "").trim()) return false;
      const scope = $("#knowledge-library");
      const prepared = null;
      const body = JSON.parse(JSON.stringify({ query, guidance: !cardId && !leaveType, use_ai: $("#use-local-ai")?.checked === true, situation_context: userTurns.join("\n").slice(-3000), today: $("#today").value, layers: layers(), card_id: cardId, base_values: baseValues, leave_type: leaveType, leave_context: leaveContext, knowledge_library_id: scope.value || null, ...(workflowFields || window.SeomuWorkflowChat?.getAskFields?.() || {}) }));
      if(/그만|취소|하지\s*(?:마|말)/.test(query))userTurns=[];
      else userTurns=[...userTurns,String(query).slice(0,1000)].slice(-6);
      const context = { today: body.today, libraryLabel: scope.selectedOptions[0]?.textContent || "전체 등록 자료", layers: [...body.layers] };
      addMsg("user", esc(displayQuery || query));
      const box = addMsg("bot", "", "thinking");
      void execute({ body, context, box, epoch: generation, prepared }); return true;
    },
    clear() {
      ++generation; userTurns=[]; window.SeomuTaskLinks?.clear(); $("#chatLog").innerHTML = "";
      status(busy ? "대화를 지웠습니다. 진행 중인 요청이 끝나면 다시 보낼 수 있습니다. 업무 변경 여부는 해당 진행표에서 확인하세요." : "대화를 지웠습니다.");
    }
  };
})();
function sendAsk(query, options) { return chatRequests.send(query, options); }

function renderAnswer(box, res, context = {}) {
  if (res.mode === "workflow_edit" && window.SeomuWorkflowChat) { window.SeomuWorkflowChat.render(box, res, (query, fields) => sendAsk(query, { workflowFields: fields })); return; }
  if(res.guidance && window.SeomuGuidance){
    const label=res.guidance.ai_used?`등록 자료 안내 · 로컬 AI 보조 ${esc(res.model||'')}`:'등록 자료 안내 · AI 미사용';
    const tree=res.knowledge?.tree;
    const directTree=tree && tree.kind!=='extract';
    box.innerHTML=`<div class="bot-hd">${label}</div>${directTree?answerTreeHtml(tree,res.knowledge?.evidence?.length||0):''}<div class="guidance-root"></div>${res.knowledge?.evidence?.length?`<details class="answer-original"><summary>규정 원문·근거 자세히 보기 (${res.knowledge.evidence.length}개)</summary>${knowledgeAnswerHtml(res.knowledge)}</details>`:''}${res.notice?`<p class="notice">${esc(res.notice)}</p>`:''}`;
    window.SeomuGuidance.render($('.guidance-root',box),res);
    if(tree)bindAnswerTree(box);
    window.SeomuTaskLinks?.render(box,res,context.today,fail);
    window.SeomuAnswerRecord?.attach(box,res,{today:context.today});
    return;
  }
  const id = "m" + (++msgSeq);
  const treeMode = !!res.knowledge?.tree;
  const clarificationMode = res.mode === "source_clarification";
  const modeText = clarificationMode ? "상황 확인 · 모델 미사용" : res.mode === "travel_workflow" ? "출장정산 준비 · 대화 내용 연결 · 모델 미사용" : res.mode === "source_manual" ? "e-사람 사용법 · 등록 매뉴얼 원문" : res.mode === "folder_workflow" ? "업무자료 정리 안내 · 모델 미사용" : res.mode === "education_workflow" ? "교육 취합 업무 안내 · 모델 미사용" : res.mode === "source_unavailable" ? "추가 자료 필요" : res.mode === "source_llm" ? "등록 자료 확인 · 로컬 AI 도움" : res.mode === "source_search" ? "등록 자료에서 확인" : res.mode === "leave_guide" ? "휴가·휴무 종류 확인 · 등록 안내자료 사용 (모델 미사용)" : res.mode === "llm" ? `규칙 기반 안내 · 절차 선택 보조 모델 ${esc(res.profile)} (${esc(res.model)})` : res.mode === "fallback" ? "규칙 기반 안내 (모델 응답 실패)" : "규칙 기반 안내 (오프라인)";
  let h = `<div class="bot-hd">${modeText}</div>`;
  if (treeMode) h += answerTreeHtml(res.knowledge.tree, res.knowledge.evidence?.length || 0);
  else h += `<div class="answer">${esc(res.summary)}</div>`;
  if (treeMode && res.mode !== "source_unavailable" && !clarificationMode) {
    const inner = `${res.answer && res.mode !== "source_manual" ? `<div class="answer-llm" style="white-space:pre-wrap">${esc(res.answer)}</div>` : ""}${res.notice ? `<div class="notice">${esc(res.notice)}</div>` : ""}${knowledgeAnswerHtml(res.knowledge)}`;
    if (inner) h += `<details class="answer-original"><summary>원문·근거 자세히 보기 (${res.knowledge.evidence?.length || 0}개)</summary>${inner}</details>`;
  } else if (treeMode && !clarificationMode) {
    const k = res.knowledge;
    const experiences = k.experiences?.length ? `<section class="refs"><h3>지난번 처리 경험 · 공식 근거 아님</h3>${k.experiences.map((n) => `<details><summary>${esc(n.title)} · ${esc(n.project_name)}</summary><p>${esc(n.author)} · ${esc(n.created_at.slice(0,10))}</p><p>상황: ${esc(n.situation)}</p><p>처리 방법: ${esc(n.handling)}</p><p>주의점: ${esc(n.caution)}</p></details>`).join("")}</section>` : "";
    const excluded = k.excluded?.length ? `<section class="refs"><h3>답변 근거에서 제외한 자료</h3>${k.excluded.map((d) => `<p>${esc(d.title)}: ${esc(d.reason)}</p>`).join("")}</section>` : "";
    if (experiences || excluded) h += `<details class="answer-original"><summary>참고 기록 보기</summary>${experiences}${excluded}</details>`;
  } else if (!treeMode && res.answer && String(res.mode || "").startsWith("source_")) h += `<div class="answer-source"><strong>원문으로 확인한 답변</strong><div class="muted">등록 자료의 원문을 보여드리며, [숫자] 표시는 아래 출처 조문을 가리킵니다.</div><div class="answer-llm" style="white-space:pre-wrap">${esc(res.answer)}</div></div>`;
  else if (res.answer) {
    // 이전 서버의 업무 시작 안내도 현재 버튼 이름·위치와 맞춘다. 근거 답변 원문에는 적용하지 않는다.
    const answer=res.mode==='folder_workflow'?String(res.answer).replace('아래에서 폴더 정리를 시작하면','위의 ‘이 내용으로 업무자료 정리’를 누르면')
      :res.mode==='education_workflow'?String(res.answer).replace('아래에서 업무를 시작하면','위의 ‘교육 취합 시작하기’를 누르면'):res.answer;
    h += `<div class="answer-llm">${esc(answer)}</div>`;
  }
  if (res.notice && !treeMode) h += `<div class="notice">${esc(res.notice)}</div>`;
  if (res.leave_guide) h += '<div class="leave-guide"></div>';
  if (res.alternatives.length) h += `<div class="row wrap"><span class="muted">다른 절차일 수도 있습니다:</span>${res.alternatives.map((a) => `<button class="small alt" data-id="${a.id}">${esc(a.title)}</button>`).join("")}</div>`;
  h += `<div class="planBox" id="${id}"></div>`;
  // 모델이 쓴 문장은 본문과 나눠 접힌 참고 영역에만 둔다(기한·날짜 문장은 서버에서 이미 뺐다)
  if (res.ai_note) h += `<details class="ai-note"><summary>AI 보충 설명 <span class="muted">(참고용 · 기한·날짜는 위 카드가 기준)</span></summary><div class="ai-note-body">${esc(res.ai_note)}</div>${res.ai_note_dropped ? '<div class="muted">기한·날짜 관련 문장은 제외했습니다.</div>' : ""}</details>`;
  const refs = [...res.cited.map((c) => chunkBox(c, true)), ...res.related.map((c) => chunkBox(c, false))];
  if (refs.length) h += `<div class="refs"><div class="refs-hd">관련 규정 조문${res.cited.length ? ' <span class="muted">(굵게: 답변에 인용됨)</span>' : ""}</div>${refs.join("")}</div>`;
  if (res.personal_notes.length) h += `<div class="refs"><div class="refs-hd">내 메모 <span class="muted">(개인 층, 공식 근거 아님)</span></div>${res.personal_notes.map((c) => chunkBox(c)).join("")}</div>`;
  if (!treeMode) h += knowledgeAnswerHtml(res.knowledge);
  box.innerHTML = h;
  if (treeMode) bindAnswerTree(box);
  if (res.leave_guide) renderLeaveGuide($(".leave-guide",box),res);
  $$(".alt", box).forEach((b) => b.addEventListener("click", () => sendAsk(res.query || b.textContent, { cardId: b.dataset.id })));
  if (res.plan) renderPlan($("#" + id, box), res.plan, res.query);
  window.SeomuTaskLinks?.render(box, res, res.plan?.today || context.today, fail);
  window.SeomuAnswerRecord?.attach(box, res, { today: context.today });
}

function renderLeaveGuide(el,res) {
  const g=res.leave_guide,ctx=g.context;
  const options=(items,current)=>Object.entries(items).map(([value,label])=>`<option value="${esc(value)}" ${value===current?'selected':''}>${esc(label)}</option>`).join('');
  el.innerHTML=`<p class="muted">${g.selection==='candidate'?'입력에서 찾은 후보입니다. 다른 종류라면 아래에서 바꿔 주세요.':'종류를 선택하면 확인할 사항과 준비자료를 보여드립니다.'}</p>
    <div class="leave-types" role="group" aria-label="휴가·휴무 종류">${g.types.map(t=>`<button type="button" class="leave-type ${t.id===g.selected?'selected':''}" data-type="${esc(t.id)}" aria-pressed="${t.id===g.selected}"><span class="leave-group">${esc(t.group)}</span><b>${esc(t.title)}</b><span>${esc(t.description)}</span></button>`).join('')}</div>
    <div class="leave-context"><label>적용 신분<select class="leave-personnel" aria-label="적용 신분">${options(g.personnel_options,ctx.personnel)}</select></label><label>근무형태<select class="leave-work" aria-label="근무형태">${options(g.work_options,ctx.work_pattern)}</select></label></div>
    ${g.selected==='special'?`<label>특별휴가 세부 사유<select class="leave-subtype" aria-label="특별휴가 세부 사유"><option value="">사유를 선택하세요</option>${g.special_options.map(s=>`<option ${s===ctx.subtype?'selected':''}>${esc(s)}</option>`).join('')}</select></label>`:''}
    <div class="row wrap"><button type="button" class="secondary leave-apply">선택한 조건으로 안내 보기</button><span class="muted">${g.missing.length?'확인 필요: '+esc(g.missing.join(' · ')):'신분·근무형태 선택됨 · 기관별 적용 검토 필요'}</span></div>
    <div class="leave-scope">${esc(g.scope)}</div>
    ${g.questions.length?`<h4>먼저 확인할 사항</h4><ol class="leave-checks">${g.questions.map(s=>`<li>${esc(s)}</li>`).join('')}</ol><h4>준비자료 · 해당 여부 확인</h4><ul>${g.documents.map(s=>`<li>${esc(s)}</li>`).join('')}</ul>`:''}
    ${ctx.subtype&&g.selected==='special'?`<p><b>선택 사유: ${esc(ctx.subtype)}</b> · 이 사유에 맞는 대상·증빙·기관별 일수 규정을 추가로 확인하세요.</p>`:''}
    <details class="leave-sources"><summary>공식 참고 근거 · 확인 ${esc(g.checked_at)}</summary><p>${esc(g.basis)}</p>${g.sources.map(s=>`<p><a target="_blank" rel="noopener" href="${esc(s.url)}">${esc(s.title)} ↗</a><br><span class="muted">${esc(s.scope)}</span></p>`).join('')}</details><p class="notice">${esc(g.notice)}</p>`;
  const context=()=>({personnel:$(".leave-personnel",el).value,work_pattern:$(".leave-work",el).value,subtype:$(".leave-subtype",el)?.value||''});
  $$(".leave-type",el).forEach(b=>b.addEventListener('click',()=>sendAsk(res.query,{leaveType:b.dataset.type,leaveContext:context(),displayQuery:g.types.find(t=>t.id===b.dataset.type).title+' 확인하기'})));
  $(".leave-apply",el).addEventListener('click',()=>sendAsk(res.query,{leaveType:g.selected,leaveContext:context(),displayQuery:'선택한 휴가·휴무 조건으로 확인하기'}));
}

function chunkBox(c, strong) {
  return `<div class="chunk"><details><summary>${strong ? "<b>" : ""}<span class="tag ${c.layer}">${c.layer}</span>${esc(c.title)} · ${esc(c.label)} <span class="muted">(${esc(c.loc)})</span>${strong ? "</b>" : ""}</summary><pre>${esc(c.text)}</pre></details></div>`;
}

function renderPlan(el, plan, query) {
  const c = plan.card;
  let h = `<div class="plan-hd"><div><b style="font-size:16px">${esc(c.title)}</b> <span class="tag ${c.layer}">${c.layer}</span><span class="tag ${c.status}">${c.status}</span></div>
    <span><button class="small primary track">＋ 홈에 등록</button> <button class="small openCard">카드 편집</button></span></div><div class="muted">${esc(c.summary)}</div>`;
  plan.warnings.forEach((w) => { h += `<div class="warn">⚠ ${esc(w)}</div>`; });
  if (c.base_dates.length) {
    h += `<div class="bases"><b>기준일</b>${c.base_dates.map((b) => `<label class="inline">${esc(b)} <input type="date" class="baseIn" data-base="${esc(b)}" value="${plan.base_values[b] || ""}"></label>`).join("")}
      <span class="muted">날짜를 바꾸면 기한이 다시 계산됩니다 (공휴일·주말 반영)</span></div>`;
    if (plan.missing_bases.length) h += `<div class="notice">기한을 계산하려면 ${plan.missing_bases.map(esc).join(", ")}을(를) 입력하세요.</div>`;
  }
  h += `<ol class="steps">`;
  plan.steps.forEach((s, i) => {
    h += `<li class="step ${i === plan.next_index ? "next" : ""}"><div class="no">${s.no}</div><div>
      <h4>${esc(s.title)} ${i === plan.next_index ? '<span class="tag now">지금 할 일</span>' : ""}</h4>
      <div>${esc(s.detail)}</div>${s.tip ? `<div class="tip">💡 ${esc(s.tip)}</div>` : ""}
      ${s.forms.length ? `<div class="row wrap">${s.forms.map((f) => `<button class="small formBtn" data-id="${f.id}">📝 ${esc(f.name)} 초안 만들기</button>`).join("")}</div>` : ""}
      <div class="basis">${s.basis.map(basisBox).join("") || '<span class="muted">근거 조문 없음</span>'}</div></div>
      <div class="due">${s.rule ? `<div class="muted">${esc(s.rule)}</div>` : ""}<div>${esc(s.due_text) || ""}</div><span class="dday ${s.dday.state}">${esc(s.dday.label)}</span></div></li>`;
  });
  h += `</ol>`;
  el.innerHTML = h;
  $$(".baseIn", el).forEach((inp) => inp.addEventListener("change", () => replan(el, plan, query)));
  $$(".formBtn", el).forEach((b) => b.addEventListener("click", () => openFormFill(b.dataset.id, plan, query)));
  $(".openCard", el).addEventListener("click", () => { showView("cards"); editCard(c.id); });
  $(".track", el).addEventListener("click", async (e) => {
    try {
      await api("POST", "/api/tracked", { card_id: c.id, base_values: plan.base_values, conditions: plan.conditions, label: query || c.title });
      e.target.disabled = true; e.target.textContent = "✓ 홈에 등록됨";
    } catch (err) { fail(err); }
  });
}

function basisBox(b) {
  if (b.missing) return `<div class="missing">근거: ${esc(b.label)} — 현재 등록된 문서에서 찾을 수 없음</div>`;
  return `<details><summary>근거: <span class="tag ${b.layer}">${b.layer}</span>${esc(b.title)} ${esc(b.label)} <span class="muted">(${esc(b.loc)})</span>${b.changed ? ' <span class="err">· 개정됨</span>' : ""}</summary><pre>${esc(b.text)}</pre></details>`;
}

async function replan(el, plan, query) {
  const bv = {};
  $$(".baseIn", el).forEach((i) => { if (i.value) bv[i.dataset.base] = i.value; });
  try { renderPlan(el, await api("POST", "/api/plan", { card_id: plan.card.id, base_values: bv, conditions: plan.conditions, today: plan.today }), query); } catch (e) { fail(e); }
}

// ------------------------------------------------------------------ 서식 초안
async function openFormFill(formId, plan, query) {
  const dlg = $("#dlg");
  $("#dlgBody").innerHTML = `<p class="muted">서식 칸을 채우는 중입니다…</p>`;
  dlg.showModal();
  try {
    const r = await api("POST", `/api/forms/${formId}/prefill`, { query: query || "", base_values: plan.base_values, today: $("#today").value });
    let h = `<h3 style="margin-top:0">${esc(r.form.name)} 초안</h3>`;
    if (r.form.doc_title) h += `<p class="muted">원본 서식: ${esc(r.form.doc_title)} — <a href="/api/documents/${r.form.doc_id}/download">원본 내려받기</a></p>`;
    if (r.notice) h += `<div class="notice">${esc(r.notice)}</div>`;
    h += `<table class="grid"><tr><th style="width:30%">칸</th><th>값</th></tr>`;
    r.form.fields.forEach((f) => {
      h += `<tr><td>${esc(f.label || f.key)}${r.origin[f.key] ? `<div class="fieldOrigin">← ${esc(r.origin[f.key])}</div>` : ""}</td>
        <td><input class="ffv" data-key="${esc(f.key)}" value="${esc(r.values[f.key] || "")}" placeholder="${esc(f.hint || "")}"></td></tr>`;
    });
    h += `</table><p class="muted">빈칸은 직접 채우세요. 모델이 채운 값도 반드시 확인하세요. 파일은 프로그램 폴더의 output\\ 에도 저장됩니다.</p>
      <div class="row"><button id="dlgClose">닫기</button><button class="primary" id="dlgExport">DOCX 내려받기</button></div>`;
    $("#dlgBody").innerHTML = h;
    $("#dlgClose").onclick = () => dlg.close();
    $("#dlgExport").onclick = async () => {
      const values = {};
      $$(".ffv").forEach((i) => { values[i.dataset.key] = i.value; });
      try {
        const resp = await api("POST", `/api/forms/${formId}/export`, { values, card_title: plan.card.title }, true);
        const name = decodeURIComponent((resp.headers.get("content-disposition") || "").split("filename*=utf-8''")[1] || "서식_초안.docx");
        const a = document.createElement("a");
        a.href = URL.createObjectURL(await resp.blob());
        a.download = name;
        a.click();
      } catch (e) { fail(e); }
    };
  } catch (e) { $("#dlgBody").innerHTML = `<p class="err">${esc(e.message)}</p><button onclick="dlg.close()">닫기</button>`; }
}

// ------------------------------------------------------------------ 절차 카드
async function loadCards() {
  [S.cards] = await Promise.all([api("GET", "/api/cards"), refreshForms()]);
  $("#cardList").innerHTML = S.cards.map((c) => `<li data-id="${c.id}" class="${S.editingCard?.id === c.id ? "on" : ""}"><span class="tag ${c.layer}">${c.layer}</span><span class="tag ${c.status}">${c.status}</span><br>${esc(c.title)} <span class="muted">· ${esc(c.category)}</span></li>`).join("");
  $$("#cardList li").forEach((li) => li.addEventListener("click", () => editCard(li.dataset.id)));
}
$("#newCard").addEventListener("click", () => {
  S.editingCard = { title: "", category: "", layer: "기관", status: "초안", keywords: "", summary: "", base_dates: [], steps: [], notes: "" };
  renderCardEditor();
});
async function editCard(id) {
  if (!S.forms.length) await refreshForms();
  S.editingCard = await api("GET", `/api/cards/${id}`);
  renderCardEditor();
  $$("#cardList li").forEach((li) => li.classList.toggle("on", li.dataset.id === id));
}

function renderCardEditor() {
  const c = S.editingCard;
  const opt = (arr, v) => arr.map((x) => `<option ${x === v ? "selected" : ""}>${x}</option>`).join("");
  let h = `<table class="grid">
    <tr><th>제목</th><td><input id="cTitle" value="${esc(c.title)}"></td><th>분류</th><td><input id="cCat" value="${esc(c.category)}"></td></tr>
    <tr><th>적용 범위</th><td><select id="cLayer">${opt(S.settings.layers, c.layer)}</select></td><th>상태</th><td><select id="cStatus">${opt(["초안", "확정"], c.status)}</select></td></tr>
    <tr><th>검색 낱말</th><td colspan="3"><input id="cKw" value="${esc(c.keywords)}" placeholder="이 절차를 찾을 때 쓸 말 (띄어 쓰기로 구분)"></td></tr>
    <tr><th>요약</th><td colspan="3"><textarea id="cSum" rows="2">${esc(c.summary)}</textarea></td></tr>
    <tr><th>기준일</th><td colspan="3"><input id="cBases" value="${esc(c.base_dates.join(", "))}" placeholder="쉼표로 구분 (예: 출장 시작일, 출장 종료일)"></td></tr>
  </table>
  <p class="muted">${c.reviewed_at ? `마지막 확정: ${esc(c.reviewed_at)}` : "아직 확정되지 않았습니다."} 근거 문서가 확정 이후 수정되면 안내 화면에 경고가 나옵니다.</p>
  <div id="stepsEdit"></div>
  <div class="row"><button id="addStep">+ 단계 추가</button><span>
    ${c.id ? `<button class="danger" id="delCard">카드 삭제</button>` : ""} <button class="primary" id="saveCard">저장</button></span></div>`;
  $("#cardEditor").innerHTML = h;
  renderSteps();
  $("#addStep").onclick = () => { collectCard(); c.steps.push({ title: "", detail: "", tip: "", deadline: null, forms: [], basis: [] }); renderSteps(); };
  $("#saveCard").onclick = async () => {
    collectCard();
    try { S.editingCard = await api("POST", "/api/cards", S.editingCard); await loadCards(); renderCardEditor(); alert("저장했습니다."); } catch (e) { fail(e); }
  };
  if (c.id) $("#delCard").onclick = async () => {
    if (!confirm(`'${c.title}' 카드를 삭제할까요?`)) return;
    try { await api("DELETE", `/api/cards/${c.id}`); S.editingCard = null; $("#cardEditor").innerHTML = '<p class="muted">삭제했습니다.</p>'; loadCards(); } catch (e) { fail(e); }
  };
  $("#cBases").addEventListener("change", () => { collectCard(); renderSteps(); });
}

function renderSteps() {
  const c = S.editingCard;
  const bases = c.base_dates;
  $("#stepsEdit").innerHTML = c.steps.map((s, i) => {
    const dl = s.deadline || {};
    return `<div class="stepEdit" data-i="${i}">
      <div class="row"><b>${i + 1}단계</b><input class="sTitle" style="flex:1" value="${esc(s.title)}" placeholder="단계 이름">
        <button class="small sUp">▲</button><button class="small sDown">▼</button><button class="small danger sDel">삭제</button></div>
      <textarea class="sDetail" rows="2" placeholder="할 일 설명">${esc(s.detail)}</textarea>
      <input class="sTip" style="width:100%;margin-top:4px" value="${esc(s.tip || "")}" placeholder="주의점·요령(선택)">
      <div class="row wrap">기한:
        <select class="dBase"><option value="">기한 없음</option>${bases.map((b) => `<option ${b === dl.base ? "selected" : ""}>${esc(b)}</option>`).join("")}</select>
        <input class="dOff" type="number" style="width:80px" value="${dl.offset ?? 0}">
        <select class="dUnit"><option ${dl.unit !== "업무일" ? "selected" : ""}>일</option><option ${dl.unit === "업무일" ? "selected" : ""}>업무일</option></select>
        <span class="muted">(음수 = 기준일 전, 양수 = 기준일 후)</span></div>
      <div class="row wrap">필요 서식: ${S.forms.map((f) => `<label class="inline"><input type="checkbox" class="sForm" value="${f.id}" ${(s.forms || []).includes(f.id) ? "checked" : ""}>${esc(f.name)}</label>`).join("") || '<span class="muted">등록된 서식 없음</span>'}</div>
      <div class="row wrap">근거: ${(s.basis || []).map((b, j) => `<span class="tag">${esc(b.title || b.doc_id)} ${esc(b.label)} <a href="#" class="bDel" data-j="${j}">✕</a></span>`).join("")}
        <button class="small bAdd">+ 근거 조문 찾기</button></div></div>`;
  }).join("");
  $$(".stepEdit").forEach((el) => {
    const i = +el.dataset.i;
    $(".sDel", el).onclick = () => { collectCard(); c.steps.splice(i, 1); renderSteps(); };
    $(".sUp", el).onclick = () => { collectCard(); if (i > 0) [c.steps[i - 1], c.steps[i]] = [c.steps[i], c.steps[i - 1]]; renderSteps(); };
    $(".sDown", el).onclick = () => { collectCard(); if (i < c.steps.length - 1) [c.steps[i + 1], c.steps[i]] = [c.steps[i], c.steps[i + 1]]; renderSteps(); };
    $$(".bDel", el).forEach((a) => a.onclick = (e) => { e.preventDefault(); collectCard(); c.steps[i].basis.splice(+a.dataset.j, 1); renderSteps(); });
    $(".bAdd", el).onclick = () => { collectCard(); pickBasis(i); };
  });
}

function collectCard() {
  const c = S.editingCard;
  if (!$("#cTitle")) return;
  Object.assign(c, {
    title: $("#cTitle").value, category: $("#cCat").value || "기타", layer: $("#cLayer").value, status: $("#cStatus").value,
    keywords: $("#cKw").value, summary: $("#cSum").value,
    base_dates: $("#cBases").value.split(",").map((x) => x.trim()).filter(Boolean),
  });
  $$(".stepEdit").forEach((el) => {
    const s = c.steps[+el.dataset.i];
    s.title = $(".sTitle", el).value; s.detail = $(".sDetail", el).value; s.tip = $(".sTip", el).value;
    const base = $(".dBase", el).value;
    s.deadline = base ? { ...(s.deadline || {}), base, offset: parseInt($(".dOff", el).value || "0", 10), unit: $(".dUnit", el).value } : null;
    s.forms = $$(".sForm:checked", el).map((x) => x.value);
  });
}

function pickBasis(stepIdx) {
  const dlg = $("#dlg");
  $("#dlgBody").innerHTML = `<h3 style="margin-top:0">근거 조문 찾기</h3>
    <div class="row"><input id="bq" style="flex:1" placeholder="예: 여비 정산 기한" value="${esc(S.editingCard.steps[stepIdx].title)}"><button id="bqBtn" class="primary">검색</button></div>
    <div id="bRes" style="max-height:50vh;overflow:auto;margin-top:8px"></div><div class="row"><span></span><button id="bClose">닫기</button></div>`;
  dlg.showModal();
  const run = async () => {
    const rows = await api("GET", "/api/chunks?q=" + encodeURIComponent($("#bq").value));
    $("#bRes").innerHTML = rows.map((r, k) => `<div class="chunk"><button class="small bPick" data-k="${k}">선택</button> <span class="tag ${r.layer}">${r.layer}</span><b>${esc(r.title)} ${esc(r.label)}</b><pre>${esc(r.text.slice(0, 300))}</pre></div>`).join("") || '<p class="muted">찾지 못했습니다.</p>';
    $$(".bPick").forEach((b) => b.onclick = () => {
      const r = rows[+b.dataset.k];
      const st = S.editingCard.steps[stepIdx];
      st.basis = st.basis || [];
      st.basis.push({ doc_id: r.doc_id, label: r.label, title: r.title });
      dlg.close();
      renderSteps();
    });
  };
  $("#bqBtn").onclick = run;
  $("#bClose").onclick = () => dlg.close();
  run();
}

// ------------------------------------------------------------------ 자료실
async function loadDocs() {
  S.docs = await api("GET", "/api/documents");
  $("#docList").innerHTML = S.docs.map((d) => `<li data-id="${d.id}"><span class="tag ${d.layer}">${d.layer}</span><span class="tag">${d.kind}</span><br>${esc(d.title)} <span class="muted">· 근거 ${d.chunk_count}개</span></li>`).join("") || '<li class="muted">등록된 자료가 없습니다.</li>';
  $$("#docList li[data-id]").forEach((li) => li.addEventListener("click", () => viewDoc(li.dataset.id)));
}
$("#uploadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const d = await api("POST", "/api/documents", new FormData(e.target));
    e.target.reset(); await loadSettings(); await loadDocs(); viewDoc(d.id);
  } catch (err) { fail(err); }
});
async function viewDoc(id) {
  const d = await api("GET", `/api/documents/${id}`);
  $$("#docList li").forEach((li) => li.classList.toggle("on", li.dataset.id === id));
  const opt = (arr, v) => arr.map((x) => `<option ${x === v ? "selected" : ""}>${x}</option>`).join("");
  $("#docView").innerHTML = `<table class="grid">
      <tr><th>이름</th><td><input id="dTitle" value="${esc(d.title)}"></td><th>종류</th><td><select id="dKind">${opt(S.settings.kinds, d.kind)}</select></td></tr>
      <tr><th>적용 범위</th><td><select id="dLayer">${opt(S.settings.layers, d.layer)}</select></td><th>파일</th><td>${esc(d.filename)}</td></tr>
      <tr><th>메모</th><td colspan="3"><input id="dNote" value="${esc(d.note)}"></td></tr></table>
    <p class="muted">등록 ${esc(d.created_at)} · 수정 ${esc(d.updated_at)} · SHA-256 ${esc(d.sha256.slice(0, 16))}…</p>
    <div class="row wrap"><button class="primary" id="dSave">정보 저장</button>
      <label class="inline"><button id="dReplaceBtn" type="button">개정본으로 파일 교체</button><input type="file" id="dReplace" style="display:none"></label>
      <a href="/api/documents/${d.id}/download"><button type="button">원본 사본 내려받기</button></a>
      <button class="danger" id="dDel">삭제</button></div>
    <h4>근거 단위 ${d.chunks.length}개</h4>${d.chunks.map((c) => `<div class="chunk"><b>${esc(c.label)}</b> <span class="muted">(${esc(c.loc)})</span><pre>${esc(c.text)}</pre></div>`).join("")}`;
  $("#dSave").onclick = async () => {
    try { await api("PUT", `/api/documents/${id}`, { title: $("#dTitle").value, kind: $("#dKind").value, layer: $("#dLayer").value, note: $("#dNote").value }); await loadDocs(); viewDoc(id); } catch (e) { fail(e); }
  };
  $("#dReplaceBtn").onclick = () => $("#dReplace").click();
  $("#dReplace").onchange = async (e) => {
    const fd = new FormData(); fd.append("file", e.target.files[0]);
    try { await api("POST", `/api/documents/${id}/file`, fd); await loadDocs(); viewDoc(id); alert("개정본으로 교체했습니다. 이 문서를 근거로 쓰는 절차 카드에 확인 경고가 표시됩니다."); } catch (err) { fail(err); }
  };
  $("#dDel").onclick = async () => {
    if (!confirm(`'${d.title}'을(를) 삭제할까요? 이 문서를 근거로 쓰는 절차 카드에는 '근거 없음'이 표시됩니다.`)) return;
    try { await api("DELETE", `/api/documents/${id}`); $("#docView").innerHTML = '<p class="muted">삭제했습니다.</p>'; loadDocs(); } catch (e) { fail(e); }
  };
}

// ------------------------------------------------------------------ 서식 정의
async function loadForms() {
  await refreshForms();
  if (!S.docs.length) S.docs = await api("GET", "/api/documents");
  $("#formList").innerHTML = S.forms.map((f) => `<li data-id="${f.id}">${esc(f.name)} <span class="muted">· 칸 ${f.fields.length}개</span></li>`).join("") || '<li class="muted">서식이 없습니다.</li>';
  $$("#formList li[data-id]").forEach((li) => li.addEventListener("click", () => { S.editingForm = structuredClone(S.forms.find((f) => f.id === li.dataset.id)); renderFormEditor(); }));
}
$("#newForm").addEventListener("click", () => { S.editingForm = { name: "", doc_id: null, fields: [{ key: "", label: "", source: "", hint: "" }] }; renderFormEditor(); });
function renderFormEditor() {
  const f = S.editingForm;
  const docs = S.docs.filter((d) => d.kind === "서식");
  $("#formEditor").innerHTML = `<table class="grid"><tr><th>서식 이름</th><td><input id="fName" value="${esc(f.name)}"></td>
      <th>원본 서식 파일</th><td><select id="fDoc"><option value="">(없음)</option>${docs.map((d) => `<option value="${d.id}" ${d.id === f.doc_id ? "selected" : ""}>${esc(d.title)}</option>`).join("")}</select></td></tr></table>
    <p class="muted">값 출처: <code>profile:성명</code>(내 정보) · <code>base:출장 종료일</code>(기준일, 기간은 <code>base:시작일~종료일</code>) · <code>today</code>(작성일) · <code>ask</code>(상황 문장에서 모델이 추출) · 비움(직접 입력)</p>
    <table class="grid" id="fFields"><tr><th>칸 이름</th><th>표시 이름</th><th>값 출처</th><th>입력 도움말</th><th></th></tr>
      ${f.fields.map((x, i) => `<tr data-i="${i}"><td><input class="fk" value="${esc(x.key)}"></td><td><input class="fl" value="${esc(x.label || "")}"></td><td><input class="fs" value="${esc(x.source || "")}"></td><td><input class="fh" value="${esc(x.hint || "")}"></td><td><button class="small danger fDel">✕</button></td></tr>`).join("")}</table>
    <div class="row"><button id="fAdd">+ 칸 추가</button><span>${f.id ? '<button class="danger" id="fRemove">서식 삭제</button>' : ""} <button class="primary" id="fSave">저장</button></span></div>`;
  const collect = () => {
    f.name = $("#fName").value; f.doc_id = $("#fDoc").value || null;
    f.fields = $$("#fFields tr[data-i]").map((tr) => ({ key: $(".fk", tr).value.trim(), label: $(".fl", tr).value, source: $(".fs", tr).value.trim(), hint: $(".fh", tr).value }));
  };
  $$(".fDel").forEach((b) => b.onclick = () => { collect(); f.fields.splice(+b.closest("tr").dataset.i, 1); renderFormEditor(); });
  $("#fAdd").onclick = () => { collect(); f.fields.push({ key: "", label: "", source: "", hint: "" }); renderFormEditor(); };
  $("#fSave").onclick = async () => { collect(); try { S.editingForm = await api("POST", "/api/forms", f); await loadForms(); renderFormEditor(); alert("저장했습니다."); } catch (e) { fail(e); } };
  if (f.id) $("#fRemove").onclick = async () => { if (!confirm("서식을 삭제할까요?")) return; try { await api("DELETE", `/api/forms/${f.id}`); $("#formEditor").innerHTML = '<p class="muted">삭제했습니다.</p>'; loadForms(); } catch (e) { fail(e); } };
}

// ------------------------------------------------------------------ 설정
async function renderSettings() {
  const render = ++settingsRenderSequence;
  if (!await loadSettings() || render !== settingsRenderSequence) return;
  const llm = S.settings.llm;
  $("#llmProfiles").innerHTML = Object.entries(llm.profiles).map(([name, p]) => {
    const on = name === llm.active;
    const fields = p.provider === "offline" ? "" : `<details class="profile-options"><summary>연결 주소·모델명·고급 설정</summary><div class="grid2">
      <label>주소(base_url)<input class="pv" data-k="base_url" value="${esc(p.base_url || "")}"></label>
      <label>모델명<input class="pv" data-k="model" value="${esc(p.model || "")}"></label>
      <label>API 키<input class="pv" data-k="api_key" type="password" placeholder="${p.has_api_key ? "저장된 키 있음 (바꿀 때만 입력)" : p.api_key_env ? `비우면 환경변수 ${esc(p.api_key_env)} 사용` : "로컬 서버는 비워도 됨"}"></label>
      <label>온도<input class="pv" data-k="temperature" type="number" step="0.1" value="${p.temperature ?? 0.2}"></label></div></details>`;
    return `<div class="profileCard ${on ? "active" : ""}" data-name="${esc(name)}"><div class="row"><b>${esc(name)}</b> <span class="muted">${esc(p.provider)}</span>
      <span>${on ? '<span class="tag 확정">사용 중</span>' : '<button class="small pUse">이 모델 사용</button>'} ${p.provider !== "offline" ? `<button class="small pSave">연결값 저장</button><button class="small pTest">${on ? "실제 응답 확인" : "연결 시험"}</button>` : ""}</span></div>
      ${fields}<div class="pMsg muted"></div></div>`;
  }).join("");
  $$(".profileCard").forEach((el) => {
    const name = el.dataset.name;
    const wasActive = name === llm.active;
    const vals = () => Object.fromEntries($$(".pv", el).map((i) => [i.dataset.k, i.value]));
    const use = $(".pUse", el), save = $(".pSave", el);
    let busy = false;
    const controls = [use, save, $(".pTest", el)].filter(Boolean);
    const run = async fn => { if (busy) return; busy = true; controls.forEach(b => b.disabled = true); try { await fn(); } catch(e) { fail(e); } finally { busy = false; controls.forEach(b => { if (b.isConnected) b.disabled = false; }); } };
    if (use) use.onclick = () => run(async () => { await api("PUT", "/api/settings/llm", { profile: name, values: $$(".pv", el).length ? vals() : null, active: name }); S.settings.llm.active = name; await window.SeomuModelStatus?.changed(); if(el.isConnected) await renderSettings(); });
    if (save) save.onclick = () => run(async () => { await api("PUT", "/api/settings/llm", { profile: name, values: vals() }); if (name === S.settings.llm.active) await window.SeomuModelStatus?.changed(); if(el.isConnected) $(".pMsg", el).textContent = "저장했습니다."; });
    const test = $(".pTest", el);
    if (test) test.onclick = () => run(async () => {
      const msg = $(".pMsg", el); if (!msg) return;
      msg.textContent = "시험 중…";
      try {
        if (wasActive) {
          const current = await window.SeomuModelStatus?.refresh();
          if (!el.isConnected) return;
          if (current?.profile !== name) {
            await renderSettings();
            const currentCard = $$(".profileCard").find(card => card.dataset.name === name);
            if (currentCard) $(".pMsg", currentCard).textContent = "현재 선택이 변경되었으므로 현재 모델 상태를 확인해 주세요.";
            return;
          }
        }
        if (save) await api("PUT", "/api/settings/llm", { profile: name, values: vals() });
        if (!el.isConnected) return;
        if (name === S.settings.llm.active) {
          await window.SeomuModelStatus?.changed();
          const status = el.isConnected ? await window.SeomuModelStatus?.check(name) : null;
          if (el.isConnected && status?.profile && status.profile !== name) {
            await renderSettings();
            const currentCard = $$(".profileCard").find(card => card.dataset.name === name);
            if (currentCard) $(".pMsg", currentCard).textContent = "현재 선택이 변경되었으므로 현재 모델 상태를 확인했습니다.";
          } else if (el.isConnected) msg.textContent = status?.profile === name
            ? `현재 선택 모델 시험 결과: ${status.response?.state === "verified" ? "최근 시험 응답 확인" : status.response?.state === "model_mismatch" ? "응답 모델 다름" : status.response?.state === "failed" ? "최근 시험 실패" : "현재 상태를 확인했습니다"}`
            : status ? "현재 선택이 바뀌어 현재 모델 상태를 확인했습니다." : "실제 응답 확인을 마쳤습니다. 현재 모델 상태를 확인해 주세요.";
        } else {
          const r = await api("POST", "/api/settings/llm/test", { profile: name });
          await window.SeomuModelStatus?.refresh();
          if (el.isConnected) msg.innerHTML = `이 프로필 시험 결과: <span class="${r.ok ? "ok" : "err"}">${esc(r.message)}</span>`;
        }
      } catch (e) { if (el.isConnected) msg.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
    });
  });
  const prof = S.settings.profile || {};
  const keys = Array.from(new Set(["소속", "직급", "성명", ...Object.keys(prof)]));
  $("#profileForm").innerHTML = keys.map((k) => `<label class="inline">${esc(k)} <input name="${esc(k)}" value="${esc(prof[k] || "")}"></label>`).join("") + `<button class="primary">저장</button>`;
}
window.addEventListener("seomu:model-status", async (event) => {
  const active = S.settings?.llm?.active;
  if (!active || !$("#view-settings").classList.contains("on") || !event.detail?.profile || event.detail.profile === active || settingsProfileRefresh) return;
  const activeCard = $$(".profileCard").find(card => card.dataset.name === active);
  if (activeCard && $(".pTest", activeCard)?.disabled) return;
  settingsProfileRefresh = true;
  try { await renderSettings(); } catch (e) { fail(e); }
  finally { settingsProfileRefresh = false; }
});
$("#profileForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("PUT", "/api/settings/profile", Object.fromEntries(new FormData(e.target))); await loadSettings(); alert("저장했습니다."); } catch (err) { fail(err); }
});
$("#resetBtn").addEventListener("click", async () => {
  if (!confirm("등록 자료·절차 카드·서식을 모두 지우고 모의데이터로 되돌릴까요? (sample_data 원본 파일은 바뀌지 않습니다)")) return;
  try { const r = await api("POST", "/api/settings/reset-sample"); alert(`다시 불러왔습니다: 자료 ${r.documents}건, 서식 ${r.forms}건, 절차 카드 ${r.cards}건`); S.editingCard = null; await loadSettings(); } catch (e) { fail(e); }
});

window.addEventListener("hashchange",()=>showView(location.hash.slice(1)));
// Show the requested screen while settings load, avoiding a flash of the old home screen.
selectView(["home","chat","cards","docs","forms","settings"].includes(location.hash.slice(1))?location.hash.slice(1):"home");
loadSettings().then(()=>{
  const target=location.hash.slice(1);showView(["home","chat","cards","docs","forms","settings"].includes(target)?target:"home");
  const handoff=SeomuFlow.take("question");
  if(handoff){
    showView("chat");const input=$("#query");
    if($("#use-local-ai"))$("#use-local-ai").checked=handoff.use_ai===true;
    // Preserve a new draft typed while settings were loading.
    if(input.value.trim()&&input.value.trim()!==handoff.text.trim()){
      addMsg("bot",'<div class="notice">새로 작성 중인 질문이 있어 첫 화면 질문은 자동 전송하지 않았습니다.</div>');return;
    }
    input.value=handoff.text;
    if(handoff.auto_submit){if(sendAsk(handoff.text))input.value="";return;}
    input.focus();
  }
}).catch(fail);
greet();
loadKnowledgeScope();
window.SeomuWorkflowChat?.init();
