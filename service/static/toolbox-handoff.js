/* Generated Blobs stay in this tab; only an explicit attach sends a file. */
(() => {
  'use strict';
  const host = document.querySelector('.toolbox-surface'), h = App.h;
  let outputs = [], archiveName = '', sourceTool = '', targets = [], loading = 0, isLoading = false, busy = false, zipBlob = null;
  const params = new URLSearchParams(location.search);
  const context = ['travel', 'adhoc'].includes(params.get('work')) && params.get('target') ? `${params.get('work')}:${params.get('target')}` : '';
  const dialog = h('dialog', { id: 'toolbox-output-dialog', 'aria-labelledby': 'toolbox-output-title' });
  const file = h('select', { id: 'toolbox-output-file' }), work = h('select', { id: 'toolbox-output-work' });
  const mode = h('select', { id: 'toolbox-output-mode' }), department = h('select', { id: 'toolbox-output-department' });
  const field = (text, el) => h('label', { for: el.id }, text, el);
  const departmentLabel = field('회신 부서', department);
  const info = h('p', { class: 'note', id: 'toolbox-output-info' });
  const notice = h('p', { id: 'toolbox-output-status', role: 'status', 'aria-live': 'polite' });
  const open = h('a', { id: 'toolbox-output-open', target: '_blank', rel: 'noopener noreferrer', hidden: true }, '첨부한 업무 열기');
  const refresh = h('button', { type: 'button', id: 'toolbox-output-refresh' }, '업무 목록 새로고침');
  const button = (id, text, primary = false) => h('button', { type: 'button', id, class: primary ? 'btn primary' : 'btn' }, text);
  const attach = button('toolbox-output-attach', '선택한 업무에 첨부', true);
  const download = button('toolbox-output-download', '내려받기'), close = button('toolbox-output-close', '닫기');
  const reopen = button('toolbox-output-reopen', '최근 만든 파일'); reopen.hidden = true;
  const chosen = () => targets.find(t => `${t.kind}:${t.id}` === work.value);
  const output = () => outputs[Number(file.value)];
  const ext = () => file.value === 'zip' ? '.zip' : (output()?.name.match(/\.[^.]+$/)?.[0] || '').toLowerCase();
  dialog.append(h('h2', { id: 'toolbox-output-title' }, '만든 파일을 업무에 첨부하세요'), field('만든 파일', file),
    field('첨부할 업무', work), refresh, field('파일 용도', mode), departmentLabel, info, notice, open,
    h('div', { class: 'handoff-actions' }, attach, download, close),
    h('p', { class: 'note' }, '파일은 이 탭에서 보관합니다. 새로고침하거나 탭을 닫으면 없어집니다.'));
  host.append(reopen, dialog);
  function message(text, bad = false) { notice.textContent = text; notice.className = bad ? 'handoff-error' : ''; }
  function setBusy(value) {
    busy = value;
    [file, work, mode, department, refresh].forEach(x => x.disabled = value || isLoading);
    [download, close].forEach(x => x.disabled = value);
    attach.disabled = value || isLoading || !chosen();
  }
  function purpose() {
    departmentLabel.hidden = mode.value !== 'reply';
    info.textContent = mode.value === 'receipt' ? 'PDF·PNG·JPG, 10MB 이하. 원본과 추출 후보를 보존하며, 거래 반영은 해당 출장에서 대조·확인합니다.' :
      mode.value === 'reply' ? '2MB 이하 XLSX. 기존 서식·중복·필수값 검사를 거쳐 검토할 행으로 등록합니다.' :
      '20MB 이하 참고 첨부. 거래·취합 행·계산 금액·완료 상태에는 자동 반영하지 않습니다.';
  }
  function modes(keep = false) {
    const t = chosen(), previous = mode.value;
    mode.replaceChildren();
    if (t?.kind === 'travel' && ['.pdf', '.png', '.jpg', '.jpeg'].includes(ext())) mode.add(new Option('영수증·증빙으로 등록', 'receipt'));
    if (t?.kind === 'adhoc' && ext() === '.xlsx') mode.add(new Option('회신 엑셀로 취합', 'reply'));
    mode.add(new Option('참고 파일로 첨부', 'reference'));
    if (keep && [...mode.options].some(o => o.value === previous)) mode.value = previous;
    department.replaceChildren(new Option('자동 인식 · 부서 열 확인', ''));
    for (const d of t?.departments || []) department.add(new Option(d, d));
    purpose(); attach.disabled = busy || isLoading || !t;
  }
  async function json(response) {
    let data;
    try { data = await response.json(); } catch (_) { throw Error('서버 응답을 읽지 못했습니다. 만든 파일은 유지됩니다.'); }
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : `처리하지 못했습니다 (${response.status}). 파일 크기·형식과 업무 상태를 확인하세요.`);
    return data;
  }
  async function loadTargets(keepMode = true) {
    if (busy) return;
    const seq = ++loading, selected = work.value || context, selectedDepartment = department.value;
    isLoading = true; setBusy(false);
    message('저장한 출장·자료 취합 업무를 찾고 있습니다.');
    try {
      const data = await json(await fetch('/api/toolbox/targets', { cache: 'no-store' }));
      let fresh = data.targets;
      if (context && !fresh.some(t => `${t.kind}:${t.id}` === context)) {
        const at = context.indexOf(':'), kind = context.slice(0, at), id = context.slice(at + 1);
        const r = await json(await fetch(`/api/toolbox/${kind}/${encodeURIComponent(id)}/attachments`, { cache: 'no-store' }));
        fresh = [r.target, ...fresh];
      }
      if (seq !== loading) return;
      targets = fresh;
      work.replaceChildren(new Option('첨부할 업무를 선택하세요', ''));
      for (const t of targets) work.add(new Option(`${t.subtitle} · ${t.title}`, `${t.kind}:${t.id}`));
      if (targets.some(t => `${t.kind}:${t.id}` === selected)) work.value = selected;
      modes(keepMode);
      if (keepMode && [...department.options].some(o => o.value === selectedDepartment)) department.value = selectedDepartment;
      message(targets.length ? '업무와 파일 용도를 확인한 뒤 첨부하세요.' : '저장한 업무가 없습니다. 출장이나 자료 취합 업무를 먼저 만든 뒤 목록을 새로고침하세요.');
    } catch (e) {
      if (seq === loading) { targets = []; work.replaceChildren(new Option('업무 목록을 불러오지 못했습니다', '')); message(e.message, true); }
    } finally { if (seq === loading) { isLoading = false; setBusy(busy); } }
  }
  async function selectedFile() {
    if (file.value !== 'zip') return output();
    if (!zipBlob) {
      await App.lib('jszip'); const z = new JSZip(); outputs.forEach(o => z.file(o.name, o.blob));
      zipBlob = await z.generateAsync({ type: 'blob' });
    }
    return { name: archiveName, blob: zipBlob };
  }
  attach.addEventListener('click', async () => {
    if (busy || isLoading || !chosen()) return;
    const t = chosen(), role = mode.value, dep = department.value;
    setBusy(true); open.hidden = true;
    try {
      const result = await selectedFile(), max = role === 'receipt' ? 10 : role === 'reply' ? 2 : 20;
      if (!result.blob.size || result.blob.size > max * 1024 * 1024) throw Error(`이 용도는 1바이트~${max}MB 파일을 지원합니다. 다른 용도를 선택하거나 파일을 줄여 주세요.`);
      const form = new FormData(); form.append('version', String(t.version)); form.append('file', result.blob, result.name);
      let url;
      if (role === 'receipt') url = `/api/travel/cases/${encodeURIComponent(t.id)}/documents`;
      else if (role === 'reply') { url = `/api/adhoc/jobs/${encodeURIComponent(t.id)}/files`; form.append('department', dep); }
      else { url = `/api/toolbox/${t.kind}/${encodeURIComponent(t.id)}/attachments`; form.append('source_tool', sourceTool); }
      message('선택한 업무에 파일을 첨부하고 있습니다.');
      const data = await json(await fetch(url, { method: 'POST', body: form }));
      t.version = data.target?.version || data.version || t.version;
      const duplicate = data.duplicate || data.upload_result?.duplicate;
      message((duplicate ? '같은 파일이 이미 첨부되어 있습니다. ' : '첨부했습니다. ') +
        (role === 'receipt' ? '해당 출장에서 원본과 거래 후보를 확인하세요.' : role === 'reply' ? '자료 취합에서 새로 등록된 행을 검토하세요.' : '참고 첨부 목록에서 확인할 수 있습니다.'));
      open.href = t.url; open.hidden = false;
      try { const ch = new BroadcastChannel('seomu-toolbox-attachments'); ch.postMessage({ kind: t.kind, id: t.id, mode: role }); ch.close(); } catch (_) {}
    } catch (e) { message(`${e.message} 만든 파일을 보관하고 있으므로 다시 시도하거나 내려받을 수 있습니다.`, true); }
    finally { setBusy(false); }
  });
  download.addEventListener('click', async () => {
    if (busy) return; setBusy(true);
    try { const result = await selectedFile(); await App.download(result.name, result.blob); }
    catch (e) { message(e.message, true); }
    finally { setBusy(false); }
  });
  refresh.addEventListener('click', () => loadTargets(true));
  work.addEventListener('change', () => { modes(); open.hidden = true; message('선택한 업무와 용도를 확인하세요.'); });
  file.addEventListener('change', () => { modes(); open.hidden = true; message('선택한 파일을 업무에 첨부할 수 있습니다.'); });
  mode.addEventListener('change', purpose);
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', e => { if (busy) e.preventDefault(); });
  reopen.addEventListener('click', () => dialog.showModal());
  window.ToolboxOutput = {
    offer(files, zipName, tool) {
      if (!files.length) return;
      const taken = new Set();
      outputs = files.map(([filename, value]) => {
        const base = String(filename).replace(/\\/g, '/').split('/').pop() || '결과파일';
        const dot = base.lastIndexOf('.'), stem = dot > 0 ? base.slice(0, dot) : base, ext = dot > 0 ? base.slice(dot) : '';
        let name = base, n = 1; while (taken.has(name.toLowerCase())) name = `${stem}_${n++}${ext}`;
        taken.add(name.toLowerCase());
        return { name, blob: value instanceof Blob ? value : new Blob([value]) };
      });
      archiveName = zipName || '결과파일.zip'; sourceTool = tool; zipBlob = null;
      file.replaceChildren(...outputs.map((o, i) => new Option(`${o.name} · ${App.fmtSize(o.blob.size)}`, String(i))));
      if (outputs.length > 1) file.add(new Option(`전체 ${outputs.length}개 ZIP · ${archiveName}`, 'zip'));
      open.hidden = true; reopen.hidden = false;
      if (!dialog.open) dialog.showModal();
      loadTargets(false);
    }
  };
})();
