"use strict";
// A view over the existing job, folder links and saved outputs; no shadow jobs.
window.EducationWorkspace = (() => {
  const $ = id => document.getElementById(id);
  let job = null, generation = 0, session = 0, request = null, folders = null, linking = false;
  const folderKey = item => JSON.stringify([item.library_id, item.project_id]);

  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  }

  function setup() {
    if ($("education-desk")) return;
    const desk = node("div"); desk.id = "education-desk";
    const pane = node("div"); pane.id = "education-work-pane";
    const support = node("aside"); support.id = "education-resources"; support.hidden = true;
    support.setAttribute("aria-label", "이 교육 업무의 자료와 결과");
    support.innerHTML = `
      <section class="panel education-resource-section" aria-labelledby="education-folders-title">
        <div class="education-resource-heading"><h3 id="education-folders-title">관련 폴더</h3><button id="education-folders-refresh" type="button" class="text-button">새로고침</button></div>
        <p id="education-folders-status" class="help" role="status"></p>
        <div id="education-folder-list"></div>
        <details id="education-folder-picker"><summary>기존 폴더 업무 연결</summary>
          <form id="education-folder-form"><label for="education-folder-choice">연결할 업무 묶음</label><select id="education-folder-choice" required></select><button type="submit" class="secondary">이 교육 업무에 연결</button></form>
          <p class="help">연결된 자료를 참고합니다. 파일 내용이 명단에 자동 반영되지는 않습니다.</p>
        </details>
        <a class="education-resource-link" href="folders.html" target="_blank" rel="noopener noreferrer">업무자료 정리에서 폴더 등록·열기 ↗</a>
      </section>
      <section id="education-output-summary" class="panel education-resource-section" aria-labelledby="education-output-title">
        <h3 id="education-output-title">취합본</h3><p id="education-output-state" class="help"></p><div id="education-output-list"></div>
        <button id="education-output-open" type="button" class="secondary">취합본 저장 단계로</button>
      </section>`;
    const workflow = $("education-workflow");
    workflow.before(desk);
    desk.append(workflow, support, pane);
    for (const id of ["adhoc-overview", "request-panel", "upload-panel", "review-panel", "export-panel", "workflow-stage-detail"])
      if ($(id)) pane.append($(id));
    const history = $("adhoc-history").closest("details");
    pane.append(history);
    $("education-output-summary").before($("adhoc-work-attachments"));
    $("education-folders-refresh").onclick = () => load();
    $("education-folder-form").onsubmit = connect;
    $("education-output-open").onclick = () => {
      if (!job) return;
      const report = job.workflow.steps.find(step => step.kind === "report");
      const tab = report && [...document.querySelectorAll("#education-workflow [data-step]")].find(el => el.dataset.step === report.id);
      if (tab) {
        tab.click();
        $("export-panel").scrollIntoView({ block: "start" });
        $("export-panel").setAttribute("tabindex", "-1");
        $("export-panel").focus({ preventScroll: true });
      }
    };
  }

  function folderCard(item) {
    const card = node("article", undefined, "education-folder");
    card.dataset.library = item.library_id; card.dataset.project = item.project_id;
    const a = node("a", item.project_name);
    // Generate all destinations from identifiers, never from stored URLs.
    a.href = `folders.html#${encodeURIComponent(item.library_id)}`;
    a.target = "_blank"; a.rel = "noopener noreferrer";
    card.append(a, node("p", `${item.library_name} · 자료 ${item.file_count}개${item.missing_count ? ` · 이번 분석에서 미확인 ${item.missing_count}개` : ""}`, "help"));
    if (item.files.length) {
      const detail = node("details"), list = node("ul");
      detail.append(node("summary", "이 업무 묶음의 파일 보기"));
      for (const file of item.files) list.append(node("li", `${file.name}${!file.present ? " · 이번 분석에서 확인되지 않음" : file.changed ? " · 변경 확인 필요" : ""}`));
      detail.append(list); card.append(detail);
    }
    return card;
  }

  function paintFolders(data) {
    const list = $("education-folder-list"); list.replaceChildren();
    for (const item of data.linked.slice(0, 2)) list.append(folderCard(item));
    if (data.linked.length > 2) {
      const more = node("details"), summary = node("summary", `연결 폴더 ${data.linked.length - 2}개 더 보기`);
      more.append(summary, ...data.linked.slice(2).map(folderCard)); list.append(more);
    }
    if (!data.linked.length) list.append(node("p", "연결된 폴더가 없습니다. 기존 업무 묶음을 연결하거나 폴더를 등록하세요.", "help"));
    const choice = $("education-folder-choice"), old = choice.value;
    choice.replaceChildren(new Option("업무 묶음을 선택하세요", ""));
    data.available.forEach(item => choice.add(new Option(`${item.library_name} / ${item.project_name} · 자료 ${item.file_count}개`, folderKey(item))));
    if (data.available.some(item => folderKey(item) === old)) choice.value = old;
    choice.disabled = !data.available.length || linking;
    $("education-folder-form").querySelector("button").disabled = !data.available.length || linking;
    $("education-folders-status").textContent = `이 교육 업무에 연결된 업무 묶음 ${data.linked.length}개${!data.available.length ? " · 추가로 연결할 업무 묶음이 없습니다." : ""}`;
  }

  async function readJson(path, signal) {
    const response = await fetch(path, { signal, cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "관련 폴더를 읽지 못했습니다.");
    return data;
  }

  // Older running servers already expose library/project links. Keep the new
  // view usable until their next normal restart, without scans or state copies.
  async function existingFolderLinks(id, signal) {
    await readJson(`/api/adhoc/jobs/${encodeURIComponent(id)}`, signal);
    const libraries = await readJson("/api/folders/libraries", signal);
    const result = { job_id: id, linked: [], available: [] };
    for (const library of libraries) {
      const view = await readJson(`/api/folders/libraries/${encodeURIComponent(library.id)}`, signal);
      for (const project of view.projects) {
        const linked = (project.links || []).some(link => link.job_id === id);
        const files = view.files.filter(file => (file.project_ids || []).includes(project.id));
        const item = {
          library_id: library.id, library_name: view.name,
          project_id: project.id, project_name: project.name,
          library_version: view.version,
          file_count: files.filter(file => file.present).length,
          missing_count: files.filter(file => !file.present).length,
          files: linked ? files.map(file => ({ id: file.id, name: file.name, present: file.present, changed: file.changed })) : []
        };
        result[linked ? "linked" : "available"].push(item);
      }
    }
    return result;
  }

  async function load() {
    if (!job) return;
    request?.abort();
    const controller = new AbortController(); request = controller;
    const id = job.id, turn = ++generation;
    const timer = setTimeout(() => controller.abort(), 15000);
    $("education-folders-status").textContent = "관련 폴더를 확인하고 있습니다.";
    $("education-folders-refresh").disabled = true;
    try {
      const response = await fetch(`/api/adhoc/jobs/${encodeURIComponent(id)}/related-folders`, { signal: controller.signal, cache: "no-store" });
      const data = response.status === 404 ? await existingFolderLinks(id, controller.signal) : await response.json();
      if (!response.ok && response.status !== 404) throw Error(typeof data.detail === "string" ? data.detail : "관련 폴더를 읽지 못했습니다.");
      if (turn !== generation || job?.id !== id) return;
      folders = data; paintFolders(data);
    } catch (error) {
      if (turn !== generation || job?.id !== id) return;
      $("education-folders-status").textContent = `${folders ? "이전 조회 내용을 표시합니다. " : ""}관련 폴더를 읽지 못했습니다. 새로고침해 주세요.`;
    } finally {
      clearTimeout(timer);
      if (turn === generation && job?.id === id) $("education-folders-refresh").disabled = false;
    }
  }

  async function connect(event) {
    event.preventDefault();
    if (linking || !job || !folders || $("education-folder-choice").value === "") return;
    const item = folders.available.find(item => folderKey(item) === $("education-folder-choice").value);
    if (!item) return;
    const id = job.id, turn = session;
    linking = true;
    $("education-folder-choice").disabled = true;
    $("education-folder-form").querySelector("button").disabled = true;
    $("education-folders-refresh").disabled = true;
    $("education-folders-status").textContent = "선택한 업무 묶음을 연결하고 있습니다.";
    try {
      const response = await fetch(`/api/folders/libraries/${encodeURIComponent(item.library_id)}/projects/${encodeURIComponent(item.project_id)}/links`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version: item.library_version, job_id: id })
      });
      const data = await response.json();
      if (!response.ok) throw Error(response.status === 409 ? "폴더 내용이 바뀌었습니다. 새로고침 후 다시 선택해 주세요." : typeof data.detail === "string" ? data.detail : "폴더를 연결하지 못했습니다.");
      if (job?.id !== id || turn !== session) return;
      linking = false; await load();
    } catch (error) {
      if (job?.id === id && turn === session) $("education-folders-status").textContent = error.message;
    } finally {
      if (job?.id === id && turn === session) {
        linking = false;
        $("education-folder-choice").disabled = !folders?.available.length;
        $("education-folder-form").querySelector("button").disabled = !folders?.available.length;
        $("education-folders-refresh").disabled = false;
      }
    }
  }

  function outputLink(v, item) {
    const row = node("p", undefined, "education-saved-output");
    const a = node("a", `명단 v${item.version} · ${item.is_current ? "현재 내용" : "이전 내용"}`);
    a.href = `/api/adhoc/jobs/${encodeURIComponent(v.id)}/exports/${encodeURIComponent(item.id)}`;
    row.append(a, node("small", new Date(item.created_at).toLocaleString("ko-KR")));
    return row;
  }

  function render(v) {
    if (!v.workflow) { leave(); return; }
    setup();
    const changed = job?.id !== v.id;
    if (changed) { leave(); job = v; }
    else job = v;
    $("education-desk").classList.add("education-desk");
    $("education-resources").hidden = false;
    $("education-output-summary").before($("adhoc-work-attachments"));
    const current = v.exports.find(item => item.is_current), other = v.exports.filter(item => item !== current);
    $("education-output-state").textContent = current ? `명단 v${v.version}의 취합본이 저장되어 있습니다.` : v.exports.length ? `명단이 v${v.version}으로 바뀌었습니다. 이전 취합본은 보존되어 있습니다.` : "아직 저장한 취합본이 없습니다.";
    const list = $("education-output-list"); list.replaceChildren();
    if (current) list.append(outputLink(v, current));
    if (other.length) {
      const detail = node("details"); detail.append(node("summary", `다른 저장본 ${other.length}개`), ...other.map(item => outputLink(v, item))); list.append(detail);
    }
    if (changed) {
      $("education-folder-list").replaceChildren();
      $("education-folder-choice").replaceChildren();
      $("education-folder-picker").open = false;
      $("education-folder-form").querySelector("button").disabled = true;
      load();
    }
  }

  function leave() {
    generation++; session++; request?.abort(); request = null; job = null; folders = null; linking = false;
    if ($("education-resources")) {
      $("education-resources").hidden = true;
      $("education-desk").classList.remove("education-desk");
      $("job-detail").append($("adhoc-work-attachments"));
    }
  }

  window.addEventListener("focus", () => { if (job && !linking) load(); });
  return { render, leave };
})();
