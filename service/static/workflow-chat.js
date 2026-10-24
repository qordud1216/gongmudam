"use strict";
window.SeomuWorkflowChat = (() => {
  const KEY = "seomu.workflowChat.educationJob";
  const ID = /^[a-f0-9]{32}$/i;
  let selected = null, generation = 0, jobs = [], box = null, select = null, link = null;
  const requests = new Map();
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const validId = id => typeof id === "string" && ID.test(id);
  async function api(path) { const r = await fetch(path); if (!r.ok) throw Error(`업무를 불러오지 못했습니다 (${r.status}).`); return r.json(); }
  function persist(id) { try { if (id && validId(id)) sessionStorage.setItem(KEY, id); else sessionStorage.removeItem(KEY); } catch (_) {} }
  function sync() {
    if (!select) return;
    if (selected && ![...select.options].some(option => option.value === selected.id)) {
      const option = document.createElement("option"); option.value = selected.id; option.textContent = selected.title || "교육 취합 업무"; select.append(option);
    }
    select.value = selected?.id || "";
    link.hidden = !selected;
    link.href = selected ? `adhoc.html#job-${encodeURIComponent(selected.id)}` : "adhoc.html#inbox";
  }
  function setContext(job, save = true) { selected = job && validId(job.id) ? job : null; if (save) persist(selected?.id); sync(); }
  function counters(job) { return { id: job.id, title: job.title || job.settings?.title || "교육 취합 업무", revision: Number(job.workflow?.revision ?? job.revision ?? 0), data_version: Number(job.version ?? job.data_version ?? 0) }; }
  async function hydrate(id, expectedGeneration) {
    if (!validId(id)) return;
    const job = await api(`/api/adhoc/jobs/${encodeURIComponent(id)}`);
    if (generation !== expectedGeneration || selected?.id !== id) return;
    const kind = job.template_snapshot?.kind || job.settings?.template_snapshot?.kind || job.layout?.kind;
    if (kind && kind !== "education") { setContext(null); return; }
    setContext(counters(job), false);
  }
  function init() {
    if (!document.querySelector("#chatLog") || box) return;
    box = document.createElement("div"); box.className = "workflow-chat-context"; box.innerHTML = '<label>수정할 교육 취합 업무 <select aria-label="수정할 교육 취합 업무"><option value="">업무를 선택하세요</option></select></label><a target="_blank" rel="noopener noreferrer" hidden>진행표 열기 ↗</a><button type="button" class="secondary" data-clear>선택 지우기</button><span class="workflow-chat-status" aria-live="polite"></span>';
    const host = document.querySelector("#chat-workflow-options"), log = document.querySelector("#chatLog");
    if(host)host.append(box);else log.parentNode.insertBefore(box, log);
    select = box.querySelector("select"); link = box.querySelector("a");
    select.onchange = () => { const id = select.value; const seq = ++generation; if (!id) { setContext(null); return; } setContext({ id, title: select.selectedOptions[0]?.textContent || "교육 취합 업무" }); hydrate(id, seq).catch(e => { if (generation === seq) status(e.message); }); };
    box.querySelector("[data-clear]").onclick = () => { ++generation; setContext(null); status(""); };
    const seq = ++generation;
    api("/api/adhoc/jobs").then(rows => {
      if (generation !== seq) return;
      jobs = (Array.isArray(rows) ? rows : []).filter(j => {
        const snapshot = j.settings?.template_snapshot ?? j.template_snapshot;
        return !snapshot || snapshot.kind === "education";
      });
      select.innerHTML = '<option value="">업무를 선택하세요</option>' + jobs.map(j => `<option value="${esc(j.id)}">${esc(j.settings?.title || j.title || "교육 취합 업무")}</option>`).join("");
      let saved = null; try { saved = sessionStorage.getItem(KEY); } catch (_) {}
      if (validId(saved) && jobs.some(j => j.id === saved)) {
        setContext({ id: saved, title: jobs.find(j => j.id === saved)?.settings?.title || "교육 취합 업무" }, false);
        hydrate(saved, seq).catch(e => { if (generation === seq) status(e.message); });
      } else if (saved) persist(null);
    }).catch(e => status(e.message));
    sync();
  }
  function status(message) { const node = box?.querySelector(".workflow-chat-status"); if (node) node.textContent = message || ""; }
  function getAskFields() {
    const uuid = window.crypto?.randomUUID ? window.crypto.randomUUID() : fallbackUuid();
    requests.set(uuid, { generation, noSelection: !selected });
    if (requests.size > 100) requests.delete(requests.keys().next().value);
    const fields = { workflow_request_id: uuid };
    if (selected && validId(selected.id)) {
      fields.education_job_id = selected.id;
      if (Number.isFinite(selected.revision) && Number.isFinite(selected.data_version)) Object.assign(fields, { workflow_revision: selected.revision, workflow_data_version: selected.data_version });
    }
    return fields;
  }
  function fallbackUuid() {
    const bytes = new Uint8Array(16);
    if (window.crypto?.getRandomValues) window.crypto.getRandomValues(bytes);
    else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
    bytes[6] = (bytes[6] & 0x0f) | 0x40; bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map(x => x.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  function openFromWorkflow(job) {
    const id = typeof job === "string" ? job : job?.id;
    if (!validId(id)) return false;
    try { sessionStorage.setItem(KEY, id); } catch (_) { return false; }
    location.href = "index.html?v=37#chat";
    return true;
  }
  function jobLink(job) { return `<a href="adhoc.html#job-${encodeURIComponent(job.id)}" target="_blank" rel="noopener noreferrer">${esc(job.title || "진행표 열기")} ↗</a>`; }
  function render(boxEl, res, resend) {
    const w = res.workflow_chat || {}, job = w.job;
    const request = requests.get(w.request_id);
    const responseGeneration = request?.generation ?? generation;
    const rows = (items, label) => !items?.length ? "" : `<section><b>${label}</b><p>${items.map(x => esc(x.title)).join(" → ")}</p></section>`;
    let html = `<div class="bot-hd">대화로 진행표 수정 · 모델 미사용</div><div class="answer">${esc(res.summary || "")}</div>`;
    if (job) html += `<p class="workflow-chat-job">${jobLink(job)}</p>`;
    html += rows(w.before, "변경 전") + rows(w.after, "변경 후");
    if (w.changes?.length) html += `<ul class="workflow-chat-changes">${w.changes.map(c => `<li><b>${esc(c.field)}</b>: ${esc(c.before)} → ${esc(c.after)}</li>`).join("")}</ul>`;
    if (res.answer) html += `<div class="answer-llm">${esc(res.answer)}</div>`;
    if (res.notice) html += `<div class="notice">${esc(res.notice)}</div>`;
    if (w.choices?.length) html += `<div class="workflow-chat-choices">${w.choices.map(c => `<button type="button" class="small" data-choice="${esc(c.id)}">${esc(c.title)}${c.position != null ? ` · ${esc(c.position)}` : ""}</button>`).join("")}</div>`;
    if (w.candidates?.length) html += `<div class="workflow-chat-choices">${w.candidates.map(c => `<button type="button" class="small" data-candidate="${esc(c.id)}">${esc(c.title)}${c.course ? ` · ${esc(c.course)}` : ""}${c.event_date ? ` · ${esc(c.event_date)}` : ""}</button>`).join("")}</div>`;
    boxEl.innerHTML = html;
    const stale = () => { status("업무 선택이 바뀌었습니다. 최신 대화에서 다시 선택해 주세요."); };
    let responseUsed = false;
    const choiceButtons = [...boxEl.querySelectorAll("[data-choice]"), ...boxEl.querySelectorAll("[data-candidate]")];
    const resendOnce = (button, query, fields, candidateChoice = false) => {
      if (responseUsed || button.disabled) return;
      responseUsed = true; choiceButtons.forEach(item => { item.disabled = true; });
      if (candidateChoice) {
        const tracking = requests.get(w.request_id);
        if (tracking) { tracking.generation = generation; tracking.noSelection = false; }
      }
      resend(query, fields);
    };
    boxEl.querySelectorAll("[data-choice]").forEach(button => button.onclick = () => {
      if (responseGeneration !== generation || !job || selected?.id !== job.id) return stale();
      const choice = w.choices.find(c => String(c.id) === button.dataset.choice); if (!choice) return;
      const fields = { workflow_request_id: w.request_id, education_job_id: job.id, workflow_revision: job.revision, workflow_data_version: job.data_version, workflow_selection: { ...(w.selection || {}), [w.role || "target"]: choice.id } };
      resendOnce(button, res.query || "", fields);
    });
    boxEl.querySelectorAll("[data-candidate]").forEach(button => button.onclick = () => {
      if (responseGeneration !== generation) return stale();
      const candidate = w.candidates.find(c => String(c.id) === button.dataset.candidate); if (!candidate) return;
      const revision = candidate.revision, dataVersion = candidate.data_version;
      ++generation;
      setContext(counters({ id: candidate.id, title: candidate.title, revision, data_version: dataVersion }));
      const fields = { workflow_request_id: w.request_id, education_job_id: candidate.id, workflow_revision: revision, workflow_data_version: dataVersion, workflow_selection: { ...(w.selection || {}) } };
      resendOnce(button, res.query || "", fields, true);
    });
    if (["choose_step", "applied", "unchanged"].includes(w.status) && job && !selected && request?.noSelection && request.generation === generation) {
      setContext(counters({ id: job.id, title: job.title, revision: job.revision, data_version: job.data_version }));
      request.noSelection = false;
    }
    if (job && selected?.id === job.id && (w.status === "applied" || w.status === "unchanged")) {
      setContext(counters({ id: job.id, title: job.title, revision: job.revision, data_version: job.data_version }));
      const seq = generation; hydrate(job.id, seq).catch(e => { if (generation === seq && selected?.id === job.id) status(e.message); });
    } else if (job && selected?.id === job.id && w.status === "conflict") {
      const seq = generation; hydrate(job.id, seq).catch(e => { if (generation === seq && selected?.id === job.id) status(e.message); });
    }
  }
  return { init, getAskFields, render, openFromWorkflow };
})();
