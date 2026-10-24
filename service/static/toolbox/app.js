/* 경기소방 업무도구함 — 공통 모듈
   모든 처리는 브라우저 안에서만 이루어진다. fetch/XHR로 파일을 보내는 코드는 없다. */
(function () {
  'use strict';

  const CATS = [{"id": "admin", "name": "근무·행정", "sub": "날짜, 글자수, 텍스트, 압축"}, {"id": "pdf", "name": "문서·PDF", "sub": "합치기, 나누기, 변환, 글자 인식"}, {"id": "photo", "name": "사진", "sub": "압축, 사진대지, 가리기"}, {"id": "util", "name": "계산·유틸", "sub": "계산기, 특수문자, QR·바코드"}];
  const tools = [];

  /* ---------- DOM helpers ---------- */
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      el.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return el;
  }
  let uid = 0;
  /* 입력 필드: {label, type, value, step, min, max, hint, options:[[v,t]]} */
  function field(o) {
    const id = o.id || 'f' + (++uid);
    let input;
    if (o.type === 'select') {
      input = h('select', { id }, (o.options || []).map(([v, t]) => h('option', { value: v, selected: String(v) === String(o.value) }, t)));
    } else if (o.type === 'textarea') {
      input = h('textarea', { id, rows: o.rows || 6, placeholder: o.placeholder || '' });
      input.value = o.value || '';
    } else {
      input = h('input', { id, type: o.type || 'number', step: o.step || 'any', min: o.min, max: o.max, placeholder: o.placeholder || '', inputmode: (o.type || 'number') === 'number' ? 'decimal' : null });
      if (o.value != null) input.value = o.value;
    }
    const wrap = h('div', { class: 'field' }, h('label', { for: id }, o.label), input, o.hint ? h('span', { class: 'hint' }, o.hint) : null);
    wrap.input = input;
    return wrap;
  }
  const num = (el) => { const v = parseFloat(el.input ? el.input.value : el.value); return isFinite(v) ? v : NaN; };
  function stat(k, unit, hl) {
    const v = h('div', { class: 'v' });
    const el = h('div', { class: 'stat' + (hl ? ' hl' : '') }, h('div', { class: 'k' }, k), v);
    el.set = (val, u = unit) => { v.textContent = val; if (u) v.append(h('small', null, u)); };
    el.set('–');
    return el;
  }
  const fmt = (n, d = 1) => (isFinite(n) ? n.toLocaleString('ko-KR', { maximumFractionDigits: d, minimumFractionDigits: 0 }) : '–');
  const pad = (n) => String(n).padStart(2, '0');
  const fmtTime = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const fmtDur = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); const hh = Math.floor(s / 3600); return (hh ? hh + ':' : '') + pad(Math.floor(s / 60) % 60) + ':' + pad(s % 60); };
  const fmtSize = (b) => b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB' : (b / 1048576).toFixed(2) + ' MB';

  function toast(msg) {
    const t = h('div', { class: 'toast', role: 'status' }, msg);
    document.querySelector('.toolbox-surface').append(t);
    setTimeout(() => t.remove(), 2600);
  }
  async function copy(text) {
    track('copy');
    try { await navigator.clipboard.writeText(text); toast('복사했습니다'); }
    catch (e) {
      const ta = h('textarea', { style: { position: 'fixed', opacity: '0' } }); ta.value = text; document.body.append(ta); ta.select();
      try { document.execCommand('copy'); toast('복사했습니다'); } catch (_) { toast('복사가 막혀 있습니다. 텍스트를 직접 선택해 주세요'); }
      ta.remove();
    }
  }

  /* ---------- 외부 라이브러리 (코드만 내려받음, 데이터는 보내지 않음) ---------- */
  const LIBS = {"pdflib": ["toolbox/vendor/pdf-lib.min.js"], "pdfjs": ["toolbox/vendor/pdf.min.js", "toolbox/vendor/pdf.worker.min.js"], "jszip": ["toolbox/vendor/jszip.min.js"], "qr": ["toolbox/vendor/qrcode.min.js"], "mp3": ["toolbox/vendor/lame.min.js"], "barcode": ["toolbox/vendor/JsBarcode.all.min.js"], "heic": ["toolbox/vendor/heic2any.min.js"], "exifr": ["toolbox/vendor/full.umd.js"], "ocr": ["toolbox/ocr/tesseract.min.js"], "pp": ["toolbox/ocr/ort/ort.wasm.min.js", "toolbox/ocrpp.js"]};
  /* 라이브러리 지문(SRI) — CDN의 파일이 한 글자라도 바뀌어 있으면 브라우저가 실행하지 않는다 (2026-09-29 보안 강화) */
  const SRI = {"toolbox/vendor/pdf-lib.min.js": "sha384-weMABwrltA6jWR8DDe9Jp5blk+tZQh7ugpCsF3JwSA53WZM9/14PjS5LAJNHNjAI", "toolbox/vendor/pdf.min.js": "sha384-/1qUCSGwTur9vjf/z9lmu/eCUYbpOTgSjmpbMQZ1/CtX2v/WcAIKqRv+U1DUCG6e", "toolbox/vendor/pdf.worker.min.js": "sha384-SnzOobpRMLXZ52iJvZm/C0fYw0OQemTXzTjIsdsfMcrCtCEe9qgzxTd3RSklO5x2", "toolbox/vendor/jszip.min.js": "sha384-+mbV2IY1Zk/X1p/nWllGySJSUN8uMs+gUAN10Or95UBH0fpj6GfKgPmgC5EXieXG", "toolbox/vendor/qrcode.min.js": "sha384-mZT2gIty7ZDdOGkxfP6joZcYdMW1Jvj9dRlfpTmaJAKKXTqzygtB22k7FLe+KZC1", "toolbox/vendor/JsBarcode.all.min.js": "sha384-Kk5SjBOKprEnGfyBWfD2zROFd1Cu8kwOXxG2GIhYPcoDL2rBJS9P8Ud1ZMy4412a", "toolbox/vendor/lame.min.js": "sha384-xuasJXVcyv3hZq0eYpelEkBC8l4yufatZXDsKuyCU2rqfhDCb+ftuE/mSfZAteiK", "toolbox/vendor/heic2any.min.js": "sha384-OTofQ0MEeiSgh62havBcemCIK0gqj809wX6UA0uPISNMRnR6NZyCdGzX3SbLrgwL", "toolbox/vendor/full.umd.js": "sha384-KrOocIA+lZcNUz2MDavnT/FuX+CbTREJihUi0bp8QUSwhE2AkGTNpv2b7yMbBkx5"};
  const loaded = {};
  function loadScript(src) {
    return new Promise((res, rej) => {
      const s = document.createElement('script');
      if (SRI[src]) { s.integrity = SRI[src]; s.crossOrigin = 'anonymous'; }
      s.src = src; s.onload = res; s.onerror = () => rej(new Error('도구 파일을 불러오지 못했습니다. 앱을 새로고침하거나 설치 파일을 확인해 주세요.'));
      document.head.append(s);
    });
  }
  function lib(name) {
    if (!loaded[name]) loaded[name] = LIBS[name].reduce((p, src) => p.then(() => loadScript(src)), Promise.resolve()).then(() => {
      if (name === 'pdfjs') window.pdfjsLib.GlobalWorkerOptions.workerSrc = LIBS.pdfjs[1];
    }).catch((e) => { delete loaded[name]; throw e; });
    return loaded[name];
  }

  /* ---------- 결과 전달과 선택적 브라우저 다운로드 ---------- */
  async function download(filename, data) {
    track('save');
    const blob = data instanceof Blob ? data : new Blob([data]);
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: filename }); document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }
  async function save(filename, data) {
    const blob = data instanceof Blob ? data : new Blob([data]);
    if (window.ToolboxOutput) return window.ToolboxOutput.offer([[filename, blob]], null, current?.id || '');
    return download(filename, blob);
  }
  async function saveMany(outs, zipName) {
    if (outs.length === 1) return save(outs[0][0], outs[0][1]);
    if (window.ToolboxOutput) return window.ToolboxOutput.offer(outs, zipName, current?.id || '');
    await lib('jszip'); const z = new JSZip(), taken = new Set();
    for (const [n, b] of outs) {
      const dot = n.lastIndexOf('.'), stem = dot > 0 ? n.slice(0, dot) : n, ext = dot > 0 ? n.slice(dot) : '';
      let nm = n, k = 1;
      while (taken.has(nm.toLowerCase())) nm = `${stem}_${k++}${ext}`;
      taken.add(nm.toLowerCase()); z.file(nm, b);
    }
    save(zipName, await z.generateAsync({ type: 'blob' }));
  }
  /* 작업 단추 보호: 누르면 끝날 때까지 잠가 두 번 눌러 두 번 저장되는 일을 막는다 */
  function busy(fn) {
    return async (e, ...rest) => {
      const b = e && e.currentTarget instanceof HTMLButtonElement ? e.currentTarget : null;
      if (b) { if (b.dataset.busy) return; b.dataset.busy = '1'; b.disabled = true; }
      try { return await fn(e, ...rest); } finally { if (b) { delete b.dataset.busy; b.disabled = false; } }
    };
  }
  function stamp() { const d = new Date(); return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`; }
  const baseName = (n) => n.replace(/\.[^.]+$/, '');

  /* ---------- 파일 입력 (드래그앤드롭) ---------- */
  function dropzone({ accept, multiple = true, label, sub, onFiles }) {
    const inp = h('input', { type: 'file', accept, multiple, hidden: true });
    const dz = h('div', { class: 'dz', tabindex: 0, role: 'button' }, h('b', null, label || '파일을 끌어다 놓거나 클릭해서 선택'), h('span', null, sub || '파일은 이 PC 안에서만 처리됩니다'), inp);
    const pick = () => inp.click();
    dz.addEventListener('click', (e) => { if (e.target !== inp) pick(); });
    dz.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
    dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('over'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('over'));
    dz.addEventListener('drop', (e) => { e.preventDefault(); dz.classList.remove('over'); const f = [...e.dataTransfer.files]; if (f.length) onFiles(multiple ? f : [f[0]]); });
    inp.addEventListener('change', () => { if (inp.files.length) onFiles([...inp.files]); inp.value = ''; });
    return dz;
  }
  /* 순서 변경·삭제 가능한 파일 목록 */
  function fileList(onChange) {
    const files = [];
    const el = h('div', { class: 'flist' });
    function render() {
      el.replaceChildren(...files.map((f, i) => h('div', { class: 'fitem' },
        h('span', { class: 'mono', style: { color: 'var(--ink-3)', width: '22px' } }, i + 1),
        h('span', { class: 'nm', title: f.name }, f.name), h('span', { class: 'sz' }, fmtSize(f.size)),
        h('button', { class: 'ib', type: 'button', title: '위로', 'aria-label': '위로', onclick: () => { if (i > 0) { [files[i - 1], files[i]] = [files[i], files[i - 1]]; render(); } } }, '↑'),
        h('button', { class: 'ib', type: 'button', title: '아래로', 'aria-label': '아래로', onclick: () => { if (i < files.length - 1) { [files[i + 1], files[i]] = [files[i], files[i + 1]]; render(); } } }, '↓'),
        h('button', { class: 'ib', type: 'button', title: '빼기', 'aria-label': '빼기', onclick: () => { files.splice(i, 1); render(); } }, '×'))));
      onChange && onChange(files);
    }
    el.files = files; el.add = (arr) => { files.push(...arr); render(); }; el.clear = () => { files.length = 0; render(); };
    return el;
  }
  const readBuf = (f) => f.arrayBuffer();
  function loadImage(src) {
    return new Promise((res, rej) => {
      const img = new Image(), tmp = typeof src === 'string' ? null : URL.createObjectURL(src);
      img.onload = () => res(img);   /* 성공하면 임시 주소(img.src)는 섬네일 판·사진대지가 계속 쓰다가 release()/cleanup 때 반납한다 */
      img.onerror = () => { if (tmp) URL.revokeObjectURL(tmp); rej(new Error('이미지를 읽지 못했습니다')); };
      img.src = tmp || src;
    });
  }
  const canvasBlob = (c, type = 'image/jpeg', q = 0.9) => new Promise((r) => c.toBlob(r, type, q));

  /* ---------- 등록 & 화면 ---------- */
  function add(t) { if (t.id !== 'writer') tools.push(t); }
  let current = null, cleanup = null, filter = 'all', query = '';
  const app = () => document.getElementById('toolbox-app');

  function renderHome() {
    document.getElementById('band').hidden = false;
    const root = app();
    const searchIn = h('input', { id: 'toolSearch', type: 'search', placeholder: '도구 검색 (예: PDF 합치기, 사진대지, 글자수)', value: query, 'aria-label': '도구 검색' });
    const chips = h('div', { class: 'chips' }, [['all', '전체'], ...CATS.map((c) => [c.id, c.name])].map(([id, nm]) =>
      h('button', { class: 'chip', type: 'button', 'aria-pressed': String(filter === id), onclick: () => { filter = id; renderHome(); } }, nm)));
    const list = h('div');
    function draw() {
      const q = query.trim().toLowerCase();
      list.replaceChildren();
      let n = 0;
      for (const c of CATS) {
        if (filter !== 'all' && filter !== c.id) continue;
        const items = tools.filter((t) => t.cat === c.id && (!q || (t.name + t.desc + t.code + (t.kw || '')).toLowerCase().includes(q)));
        if (!items.length) continue;
        n += items.length;
        list.append(h('section', { class: 'cat' },
          h('div', { class: 'cat-h' }, h('h2', null, c.name), h('span', null, `${items.length}개 · ${c.sub}`)),
          h('div', { class: 'grid' }, items.map((t) => h('button', { class: 'tile', type: 'button', onclick: () => go(t.id) },
            h('span', { class: 'tile-top' }, h('span', { class: 'code' }, t.code), t.ext ? h('span', { class: 'lib', style: { color: 'var(--accent)', borderColor: 'var(--accent)' } }, '별도 사이트') : null),
            h('b', null, t.name), h('p', null, t.desc))))));
      }
      if (!n) list.append(h('p', { class: 'empty' }, `"${query}"에 맞는 도구가 없습니다.`));
    }
    searchIn.addEventListener('input', () => { query = searchIn.value; draw(); });
    root.replaceChildren(h('div', { class: 'controls' },
      h('label', { class: 'search' }, h('span', { 'aria-hidden': 'true', style: { color: 'var(--ink-3)' } }, '⌕'), searchIn), chips), list);
    draw();
  }
  function renderTool(t) {
    document.getElementById('band').hidden = true;
    const body = h('div', { class: 'stack' });
    app().replaceChildren(
      h('div', { class: 'tool-head' }, h('button', { class: 'back', type: 'button', onclick: backHome }, '← 전체 도구'), h('span', { class: 'code' }, t.code), h('h2', null, t.name)),
      h('p', { class: 'tool-desc' }, t.long || t.desc), body);
    try { cleanup = t.render(body) || null; } catch (e) { body.append(h('p', { class: 'note warn' }, '도구를 여는 중 오류가 났습니다: ' + e.message)); }
    window.scrollTo(0, 0);
  }
  /* 화면 이동 (2026-09-29 검토 반영)
     도구를 열 때 방문 기록을 한 칸 쌓는다 → 휴대폰 뒤로가기를 누르면 사이트를 벗어나지 않고 목록으로 돌아온다.
     mode: 'push'(새로 열기) | 'replace'(첫 화면) | 'none'(뒤로가기로 온 경우 — 기록은 이미 바뀌어 있다) */
  function go(id, mode = 'push') {
    const next = tools.find((t) => t.id === id) || null;
    if (next === current && app().childElementCount) return;
    if (cleanup) { try { cleanup(); } catch (_) {} cleanup = null; }
    current = next;
    const url = current ? '#' + current.id : location.pathname + location.search;
    try {
      if (mode === 'push' && current) history.pushState({ tool: current.id, toolboxOwned: true }, '', url);
      else if (mode !== 'none') history.replaceState(current ? { tool: current.id, toolboxOwned: false } : null, '', url);
    } catch (_) {}
    current ? renderTool(current) : renderHome();
    if (current) track('open');
  }
  /* "← 전체 도구": 우리가 쌓은 기록이면 뒤로가기와 똑같이 움직인다 */
  function backHome() {
    if (history.state && history.state.toolboxOwned) history.back();
    else go('', 'replace');
  }
  function routeFromHash() {
    const id = (location.hash || '').slice(1);
    go(tools.some((t) => t.id === id) ? id : '', 'none');
  }


  // Local tools have no usage telemetry or request-board API.
  function track() {}
  function start() {
    document.getElementById('count').textContent = `도구 ${tools.length}개`;
    window.addEventListener('popstate', routeFromHash);
    window.addEventListener('hashchange', routeFromHash);
    const id = (location.hash || '').slice(1);
    go(tools.some((t) => t.id === id) ? id : '', 'replace');
  }
  window.App = { tools: () => tools.slice(), cats: () => CATS.slice(), saveMany, busy, add, start, h, field, num, stat, fmt, pad, fmtTime, fmtDur, fmtSize, toast, copy, lib, save, download, stamp, baseName, dropzone, fileList, readBuf, loadImage, canvasBlob };
})();
