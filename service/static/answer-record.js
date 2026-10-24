"use strict";
(() => {
  const allowedModes = new Set(["source_llm", "source_search", "source_unavailable", "source_clarification", "structured_guidance"]);
  const text = (value) => value == null ? "" : String(value);
  const line = (label, value) => value == null || value === "" ? [] : [`${label}: ${text(value)}`];
  const list = (value) => Array.isArray(value) ? value : [];
  const recordText = (response, today) => {
    const knowledge = response.knowledge && typeof response.knowledge === "object" ? response.knowledge : {};
    const evidence = list(knowledge.evidence);
    const tree = knowledge.tree && typeof knowledge.tree === "object" ? knowledge.tree : null;
    const out = ["서무비서 답변 확인 기록", `표시시각 (Asia/Seoul): ${new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "full", timeStyle: "medium", hour12: false }).format(new Date())}`];
    out.push(...line("안내 기준일", today), "", "질문 원문", text(response.query), "", "응답 방식", ({ source_llm: "원문 + 로컬 AI 구절 선택", source_search: "등록 원문만", source_unavailable: "자료 부족", source_clarification: "추가 상황 필요", structured_guidance: "등록 자료 기반 구조화 안내" })[response.mode]);
    if (response.model != null) out.push(...line("모델", response.model));
    if (response.profile != null) out.push(...line("프로필", response.profile));
    out.push("", "요약", text(response.summary));
    const guidance = response.guidance && typeof response.guidance === "object" ? response.guidance : null;
    if (guidance) {
      out.push("", "실무 준비 안내", ...line("제목", guidance.title), ...line("상황", guidance.context));
      list(guidance.steps).forEach((step) => {
        if (!step || typeof step !== "object") return;
        out.push(`- ${text(step.title)}${step.detail ? `: ${text(step.detail)}` : ""}`);
      });
      list(guidance.questions).forEach((question) => out.push(`확인 질문: ${text(question)}`));
      list(guidance.deadlines).forEach((deadline) => {
        if (!deadline || typeof deadline !== "object") return;
        const ref = Number.isInteger(deadline.ref) && deadline.ref > 0 ? ` [법령 근거 ${deadline.ref}]` : "";
        out.push(`기한 안내: ${text(deadline.text)}${ref}`);
      });
      list(guidance.forms).forEach((form) => {
        if (!form || typeof form !== "object") return;
        out.push(`서식: ${text(form.name)}${form.href ? ` (${text(form.href)})` : ""}${form.synthetic ? " · 합성·예시 서식, 기관 현행 양식 확인" : ""}`);
      });
      out.push(...line("실무 안내 범위", guidance.notice));
    }
    if (tree) {
      out.push("", "한눈에 보기", ...line("제목", tree.title));
      list(tree.branches).forEach((branch) => {
        if (!branch || typeof branch !== "object") return;
        out.push(...line("분기", branch.label));
        list(branch.items).forEach((item) => {
          if (!item || typeof item !== "object") return;
          const ref = Number.isInteger(item.ref) && item.ref > 0 && item.ref <= evidence.length ? ` [근거 ${item.ref}]` : "";
          out.push(`- ${text(item.text)}${ref}`);
        });
      });
      out.push(...line("참고", tree.note));
    }
    out.push("", "답변 원문", text(response.answer), ...line("안내", response.notice));
    if (evidence.length) out.push("", "출처 및 인용 원문");
    evidence.forEach((entry, i) => {
      if (!entry || typeof entry !== "object") return;
      out.push(` [근거 ${i + 1}]`, ...line("제목", entry.title), ...line("종류", entry.kind), ...line("기관", entry.institution), ...line("시행일", entry.effective_date), ...line("위치", entry.loc), ...line("자료 ID", entry.source_id ?? entry.id), ...line("SHA-256", entry.sha256));
      const official = entry.official && typeof entry.official === "object" ? entry.official : {};
      ["source_url", "download_url", "issuer", "publication", "retrieved_at", "scope"].forEach((key) => out.push(...line(key, official[key])));
      out.push("인용 원문:", text(entry.quote));
      if (entry.model_selected_quote != null) out.push("AI 선택 구절 (참고):", text(entry.model_selected_quote));
    });
    const manualEvidence = list(guidance?.manual?.evidence);
    if (manualEvidence.length) {
      out.push("", "e-사람 사용법 · 등록 매뉴얼 원문 (화면 조작 안내, 법령 근거와 별도)");
      manualEvidence.forEach((entry) => {
        if (!entry || typeof entry !== "object") return;
        out.push(...line("제목", entry.title), ...line("PDF 쪽수", entry.page), ...line("자료 ID", entry.source_id ?? entry.id), ...line("SHA-256", entry.sha256), "인용 원문:", text(entry.quote), "");
      });
    } else if (guidance?.manual?.notice) out.push("", "e-사람 사용법", text(guidance.manual.notice));
    const experiences = list(knowledge.experiences).filter((x) => x && typeof x === "object");
    if (experiences.length) {
      out.push("", "처리 경험 · 공식 근거 아님");
      experiences.forEach((x) => out.push(...line("상황", x.situation), ...line("처리", x.handling), ...line("주의점", x.caution), ""));
    }
    const excluded = list(knowledge.excluded).filter((x) => x && typeof x === "object");
    if (excluded.length) { out.push("", "답변 근거에서 제외한 자료"); excluded.forEach((x) => out.push(...line("제목", x.title), ...line("사유", x.reason))); }
    out.push("", "답변 당시의 확인 기록입니다. 원문의 현재 유효성이나 기관 승인을 뜻하지 않습니다.");
    return out.join("\n");
  };
  const filenameTime = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date()).replace(/[-: ]/g, "");
  const attach = (box, response, options = {}) => {
    if (!box || !response || !allowedModes.has(response.mode)) return;
    const existing = box.querySelector(":scope > .answer-record-actions");
    if (existing) return;
    let snapshot;
    try { snapshot = recordText(response, options.today); } catch (_) { return; }
    const actions = document.createElement("div");
    actions.className = "answer-record-actions";
    const help = document.createElement("span"); help.textContent = "질문·요약·원문·출처를 TXT로 보관합니다.";
    const status = document.createElement("span"); status.className = "answer-record-status"; status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const button = document.createElement("button"); button.type = "button"; button.className = "secondary answer-record-button"; button.textContent = "답변 기록 저장";
    button.addEventListener("click", () => {
      let url;
      let anchor;
      try {
        const blob = new Blob(["\uFEFF", snapshot], { type: "text/plain;charset=utf-8" });
        url = URL.createObjectURL(blob);
        anchor = document.createElement("a"); anchor.href = url; anchor.download = `seomu-answer-${filenameTime()}.txt`; anchor.style.display = "none";
        document.body.appendChild(anchor); anchor.click();
        status.textContent = "파일 저장 요청을 보냈습니다. 브라우저 다운로드를 확인하세요.";
      } catch (_) { status.textContent = "파일을 저장하지 못했습니다. 브라우저 다운로드 설정을 확인하세요."; }
      finally {
        anchor?.remove();
        if (url) window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    });
    actions.append(help, button, status);
    box.appendChild(actions);
  };
  window.SeomuAnswerRecord = Object.freeze({ attach });
})();
