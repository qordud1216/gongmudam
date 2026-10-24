"use strict";
(() => {
  const channel = "BroadcastChannel" in window ? new BroadcastChannel("seomu-toolbox-attachments") : null;
  const mounted = new WeakMap();
  let sequence = 0;

  function mount(container, target) {
    if (!container || !target || !["travel", "adhoc"].includes(target.kind) || !target.id) return;
    const key = `${target.kind}:${target.id}`;
    let state = mounted.get(container);
    if (!state) {
      state = { key: null, token: 0, target: null };
      mounted.set(container, state);
    }
    state.target = { ...target };
    const token = ++sequence;
    state.token = token;
    state.key = key;
    container.classList.add("work-attachments");
    container.replaceChildren();

    const heading = document.createElement("h3");
    heading.textContent = "도구함 첨부파일";
    const shortcut = document.createElement("a");
    shortcut.textContent = "업무도구함에서 파일 만들기";
    shortcut.href = `toolbox.html?work=${encodeURIComponent(target.kind)}&target=${encodeURIComponent(target.id)}`;
    shortcut.target = "_blank";
    shortcut.rel = "noopener noreferrer";
    const note = document.createElement("p");
    note.className = "help";
    note.textContent = "참고 첨부는 거래나 취합 행에 자동 반영되지 않습니다.";
    const list = document.createElement("div");
    list.className = "work-attachments-list";
    container.append(heading, shortcut, note, list);

    const current = () => mounted.get(container) === state && state.token === token && state.key === key;
    const load = async () => {
      list.replaceChildren();
      const loading = document.createElement("p");
      loading.className = "help";
      loading.textContent = "첨부파일을 불러오는 중입니다.";
      list.append(loading);
      try {
        const response = await fetch(`/api/toolbox/${encodeURIComponent(target.kind)}/${encodeURIComponent(target.id)}/attachments`, { headers: { Accept: "application/json" } });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "첨부파일을 불러오지 못했습니다.");
        if (!current()) return;
        list.replaceChildren();
        if (!Array.isArray(data.items) || !data.items.length) {
          const empty = document.createElement("p");
          empty.className = "help";
          empty.textContent = "연결된 첨부파일이 없습니다.";
          list.append(empty);
          return;
        }
        for (const item of data.items) {
          const row = document.createElement("div");
          row.className = "work-attachment-item";
          const link = document.createElement("a");
          link.textContent = String(item.filename || "첨부파일");
          link.href = `/api/toolbox/${encodeURIComponent(target.kind)}/${encodeURIComponent(target.id)}/attachments/${encodeURIComponent(item.id)}/original`;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          row.append(link);
          list.append(row);
        }
      } catch (error) {
        if (!current()) return;
        list.replaceChildren();
        const message = document.createElement("p");
        message.className = "work-attachments-error";
        message.textContent = error.message || "첨부파일을 불러오지 못했습니다.";
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "secondary";
        retry.textContent = "다시 불러오기";
        retry.addEventListener("click", load);
        list.append(message, retry);
      }
    };
    load();
  }

  if (channel) {
    channel.addEventListener("message", event => {
      const data = event.data;
      if (!data || !["travel", "adhoc"].includes(data.kind) || !data.id) return;
      for (const container of document.querySelectorAll(".work-attachments")) {
        const state = mounted.get(container);
        if (!state || state.key !== `${data.kind}:${data.id}`) continue;
        if (data.mode === "reference") mount(container, state.target);
        else if ((data.mode === "receipt" || data.mode === "reply") && !container.querySelector(".work-attachments-latest")) {
          const link = document.createElement("a");
          link.textContent = "업무 최신 내용 열기";
          link.className = "work-attachments-latest";
          link.href = data.kind === "travel" ? `travel.html?case=${encodeURIComponent(data.id)}#settle` : `adhoc.html#job-${encodeURIComponent(data.id)}`;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          container.append(link);
        }
      }
    });
    window.addEventListener("pagehide", () => channel.close(), { once: true });
  }

  window.WorkAttachments = { mount };
})();
