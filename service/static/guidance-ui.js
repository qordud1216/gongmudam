"use strict";
window.SeomuGuidance = (() => {
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const localFormHref = (form) => {
    const href = String(form?.href ?? "");
    if (href === "index.html#forms") return href;
    return /^\/api\/documents\/[A-Za-z0-9_%.-]+\/download$/.test(href) ? href : "";
  };
  function render(box, result) {
    const guidance = result?.guidance;
    if (!box || !guidance || typeof guidance !== "object") return;
    const section = document.createElement("section");
    section.className = "guidance-panel";
    const steps = Array.isArray(guidance.steps) ? guidance.steps : [];
    const questions = Array.isArray(guidance.questions) ? guidance.questions : [];
    const deadlines = Array.isArray(guidance.deadlines) ? guidance.deadlines : [];
    const forms = Array.isArray(guidance.forms) ? guidance.forms : [];
    const evidence = guidance.manual?.evidence;
    const legalEvidence = result.knowledge?.evidence;
    const legalRefs = new Set(Array.isArray(legalEvidence) ? legalEvidence.map((item, index) => index + 1) : []);
    const deadlineHtml = `<section><h3>기한</h3>${deadlines.length ? `<ul>${deadlines.map(item => `<li>${esc(item?.text)}${Number.isSafeInteger(item?.ref) && legalRefs.has(item.ref) ? ` <button type="button" class="guidance-ref" data-guidance-evidence="${item.ref}">[근거 ${item.ref}]</button>` : ""}</li>`).join("")}</ul>` : `<p class="guidance-note">질문에 적용할 정확한 기한을 확인할 등록 근거가 부족해요. 아래 원문과 적용 조건을 확인해 주세요.</p>`}</section>`;
    const formHtml = forms.length ? forms.map(form => {
      const href = localFormHref(form);
      return `<li>${href ? `<a href="${esc(href)}">${esc(form?.name || "서식 보기")}</a>` : esc(form?.name || "서식 이름 미확인")}${form?.synthetic === true ? " <span class=\"guidance-note\">합성·예시 서식 · 기관 현행 양식 확인</span>" : ""}</li>`;
    }).join("") : `<li>관련 서식이 연결되지 않았습니다. <a href="index.html#forms">등록 서식 확인</a></li>`;
    const map = guidance.map && typeof guidance.map === "object" ? guidance.map : null;
    const mapNodes = Array.isArray(map?.nodes) ? map.nodes : [];
    section.innerHTML = `<h2>${esc(guidance.title || "업무 안내")}</h2>${guidance.context ? `<p class="guidance-context">${esc(guidance.context)}</p>` : ""}
      <section><h3>먼저 준비할 내용</h3>${steps.length ? `<ol>${steps.map(step => `<li><strong>${esc(step?.title || "준비 항목")}</strong>${step?.detail ? ` — ${esc(step.detail)}` : ""}</li>`).join("")}</ol>` : `<p class="guidance-note">등록된 처리 순서가 없습니다. 아래 근거 자료를 확인해 주세요.</p>`}</section>
      ${questions.length ? `<section><h3>추가로 확인할 사항</h3><ul>${questions.map(question => `<li>${esc(question)}</li>`).join("")}</ul></section>` : ""}${deadlineHtml}
      <section><h3>관련 서식</h3><ul>${formHtml}</ul></section>
      ${guidance.notice ? `<p class="guidance-note">${esc(guidance.notice)}</p>` : ""}${guidance.ai_requested && !guidance.ai_used ? `<p class="guidance-note" role="status">로컬 AI 보조를 요청했지만 사용하지 못했습니다. 등록 자료를 바탕으로 안내합니다.</p>` : ""}
      <details class="guidance-details"><summary>e-사람 사용법 · 원문과 쪽수</summary>${guidance.manual?.notice ? `<p>${esc(guidance.manual.notice)}</p>` : ""}${guidance.manual?.scope ? `<p>${esc(guidance.manual.scope)}</p>` : ""}${typeof window.knowledgeAnswerHtml === "function" ? window.knowledgeAnswerHtml({ evidence, scope: guidance.manual?.scope }) || `<p class="guidance-note">연결된 매뉴얼 근거가 없습니다. <a href="folders.html">자료함에서 등록 자료 확인</a></p>` : `<p class="guidance-note">매뉴얼 근거를 표시할 수 없습니다. <a href="folders.html">자료함에서 등록 자료 확인</a></p>`}</details>
      ${map ? `<details class="guidance-details"><summary>자료 연결 확인</summary><p>안내 자료 ${mapNodes.length}개 · 연결 ${Array.isArray(map.edges) ? map.edges.length : 0}개</p><p class="guidance-note">${esc(map.note || "자료 사이의 연결 정보입니다.")}</p><ul>${mapNodes.map(node => `<li>${esc(node?.label || node?.title || node?.id || "자료")}${node?.kind ? ` · ${esc(node.kind)}` : ""}${node?.loc ? ` · ${esc(node.loc)}` : ""}${node?.page ? ` · ${esc(node.page)}쪽` : ""}${node?.sha256 ? ` · SHA-256 ${esc(node.sha256)}` : ""}</li>`).join("")}</ul></details>` : ""}`;
    const anchor = box.querySelector(".bot-hd");
    if (anchor) anchor.after(section); else box.prepend(section);
    section.querySelectorAll("[data-guidance-evidence]").forEach(button => button.addEventListener("click", () => {
      const scope = box.closest('.bubble') || box;
      const target = scope.querySelector(`.answer-original .ref[data-evidence-index="${CSS.escape(button.dataset.guidanceEvidence)}"]`);
      if (!target) return;
      let parent = target.parentElement;
      while (parent && parent !== scope) { if (parent.tagName === "DETAILS") parent.open = true; parent = parent.parentElement; }
      target.open = true; target.scrollIntoView({ block: "center", behavior: "smooth" });
    }));
  }
  return { render };
})();
