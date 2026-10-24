/* 사진 도구 — 2026-09-29: 공용 섬네일 판(board.js)으로 사진을 눈으로 보며 고르고 편집한다 */
(function () {
  'use strict';
  const { add, h, field, num, fmtSize, save, stamp, baseName, dropzone, fileList, loadImage, canvasBlob, lib, toast, pad, board, boardBar, btn, row, hint, imageItem } = App;
  const status = () => h('div', { class: 'status' });
  const IMG = 'image/jpeg,image/png,image/webp,image/bmp,image/gif';
  const guard = (st, fn) => App.busy(async (...a) => { try { await fn(...a); } catch (e) { st.textContent = '오류: ' + e.message; console.error(e); } });
  function toCanvas(img, maxSide) {
    const W = img.naturalWidth || img.width, H = img.naturalHeight || img.height, s = maxSide ? Math.min(1, maxSide / Math.max(W, H)) : 1;
    const c = document.createElement('canvas'); c.width = Math.round(W * s); c.height = Math.round(H * s);
    const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.drawImage(img, 0, 0, c.width, c.height); return c;
  }
  const saveMany = App.saveMany;   /* 이름이 겹쳐도 한 장도 빠지지 않는 공용 ZIP 저장 */
  /* 화면에 맞게 줄여 보이는 캔버스에서 포인터 좌표 → 실제 픽셀 좌표 */
  const ptOf = (cv, e) => { const r = cv.getBoundingClientRect(); return [((e.clientX - r.left) * cv.width) / r.width, ((e.clientY - r.top) * cv.height) / r.height]; };
  /* 사진 여러 장 → 판 항목 (용량을 꼬리표로) */
  async function photoItems(files, st) {
    const out = [];
    for (const [k, f] of files.entries()) {
      if (st) st.textContent = `사진 읽는 중 ${k + 1}/${files.length}`;
      try { out.push(Object.assign(imageItem(f, await loadImage(f)), { label: f.name, tag: fmtSize(f.size), color: 'rgba(20,22,25,.62)' })); }
      catch (_) { toast(`${f.name}: 이 브라우저에서 열 수 없는 사진입니다`); }
    }
    return out;
  }
  const countPill = () => h('span', { class: 'pill ok' });
  const pickLabel = (g, unit = '장') => (g.sel.size ? `${g.sel.size}${unit} 선택 (선택한 것만 처리)` : `전체 ${g.count()}${unit}`);

  /* 28. 일괄 압축·리사이즈 */
  add({
    id: 'photos', cat: 'photo', code: 'RESIZE', name: '현장사진 일괄 압축·리사이즈', kw: '용량 줄이기 크기 메일 첨부 보고서 섬네일', lib: true,
    desc: '사진을 섬네일로 보면서 여러 장을 한 번에 줄여 보고서·메일 첨부용으로 저장',
    long: '긴 변 길이와 화질을 정하면 모든 사진을 한 번에 줄입니다. 일부만 줄이려면 섬네일을 눌러 고르세요. 위치(GPS) 등 촬영 정보는 저장 과정에서 자동으로 빠집니다.',
    render(el) {
      const st = status(); const count = countPill(); const area = h('div', { class: 'stack' });
      const g = board({ onChange: () => upd() });
      const side = field({ label: '긴 변 최대 (px)', type: 'select', value: 1600, options: [[800, '800 (메신저)'], [1280, '1280'], [1600, '1600 (보고서 권장)'], [2048, '2048'], [0, '원본 크기 유지']] });
      const q = field({ label: '화질 (%)', type: 'range', value: 80, min: 40, max: 95, step: 5 });
      const fm = field({ label: '형식', type: 'select', value: 'jpg', options: [['jpg', 'JPG'], ['webp', 'WEBP (더 작음)'], ['png', 'PNG (무손실)']] });
      const tb = h('tbody');
      function upd() { const size = g.order.reduce((a, it) => a + it.file.size, 0); count.textContent = `${pickLabel(g)} · 전체 ${fmtSize(size)}`; area.hidden = !g.count(); }
      const go = btn('줄여서 저장', guard(st, async () => {
        const type = { jpg: 'image/jpeg', webp: 'image/webp', png: 'image/png' }[fm.input.value]; const list = g.targets(), outs = []; let before = 0, after = 0; tb.replaceChildren();
        for (const [i, it] of list.entries()) {
          st.textContent = `처리 중 ${i + 1}/${list.length}`;
          const c = toCanvas(it.img, +side.input.value || 0); const bl = await canvasBlob(c, type, num(q) / 100);
          outs.push([`${baseName(it.file.name)}.${fm.input.value}`, bl]); before += it.file.size; after += bl.size;
          tb.append(h('tr', null, h('td', null, it.file.name), h('td', { class: 'mono' }, `${it.img.naturalWidth}×${it.img.naturalHeight} → ${c.width}×${c.height}`), h('td', { class: 'mono' }, `${fmtSize(it.file.size)} → ${fmtSize(bl.size)}`)));
        }
        st.textContent = `${outs.length}장 · ${fmtSize(before)} → ${fmtSize(after)} (${Math.round((1 - after / before) * 100)}% 감소)`;
        await saveMany(outs, `사진_압축_${stamp()}.zip`);
      }), true);
      area.append(boardBar(g, row(count, btn('선택한 사진 빼기', () => { if (!g.sel.size) return toast('뺄 사진을 먼저 고르세요'); g.remove(g.picked()); }), btn('모두 비우기', () => g.clear()))),
        g.el, h('div', { class: 'fields' }, side, q, fm), row(go), st, h('div', { class: 'tbl-wrap' }, h('table', null, tb)));
      area.hidden = true;
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: IMG, sub: '여러 장 한 번에 · 더 넣으면 뒤에 이어 붙습니다 · 여러 장이면 ZIP으로 저장', onFiles: guard(st, async (fs) => { g.add(await photoItems(fs, st)); st.textContent = ''; }) }), area));
      upd();
      return () => g.destroy();
    },
  });

  /* 29. HEIC → JPG */
  add({
    id: 'heic', cat: 'photo', code: 'HEIC', name: 'HEIC → JPG 변환', kw: '아이폰 사진 변환 섬네일', lib: true,
    desc: '아이폰 HEIC 사진을 JPG로 바꾸고, 결과를 섬네일로 확인한 뒤 저장',
    long: 'HEIC는 브라우저가 미리 보여주지 못해서, 먼저 JPG로 바꾼 뒤 결과를 섬네일로 보여드립니다. 필요한 사진만 골라 저장할 수도 있습니다.',
    render(el) {
      const st = status(); const count = countPill(); const area = h('div', { class: 'stack' });
      const list = fileList((f) => (conv.disabled = !f.length));
      const g = board({ onChange: () => upd() });
      function upd() { count.textContent = pickLabel(g); area.hidden = !g.count(); }
      const conv = btn('JPG로 변환', guard(st, async () => {
        st.textContent = '변환 코드를 불러오는 중… (처음 한 번, 약 1.3MB)'; await lib('heic'); const items = [], failed = [];
        for (const [i, f] of list.files.entries()) {
          st.textContent = `변환 중 ${i + 1}/${list.files.length} · 사진 한 장에 몇 초 걸립니다`;
          try {
            let r = await heic2any({ blob: f, toType: 'image/jpeg', quality: 0.9 }); if (Array.isArray(r)) r = r[0];
            const jf = new File([r], `${baseName(f.name)}.jpg`, { type: 'image/jpeg' });
            items.push(Object.assign(imageItem(jf, await loadImage(jf)), { label: jf.name, blob: r, tag: fmtSize(r.size), color: 'rgba(20,22,25,.62)' }));
          } catch (_) { failed.push(f.name); }   /* 한 장이 안 돼도 나머지는 계속 */
        }
        list.clear(); g.add(items);
        st.textContent = `${items.length}장 변환 완료` + (failed.length ? ` · 변환 못 한 사진 ${failed.length}장: ${failed.slice(0, 3).join(', ')}${failed.length > 3 ? ' …' : ''}` : '') + ' — 확인한 뒤 [저장]을 누르세요';
      }), true);
      conv.disabled = true;
      const sv = btn('저장', guard(st, async () => { const t = g.targets(); await saveMany(t.map((it) => [it.file.name, it.blob]), `HEIC변환_${stamp()}.zip`); st.textContent = `${t.length}장 저장`; }), true);
      area.append(h('b', null, '변환 결과'), boardBar(g, row(count, sv, btn('결과 비우기', () => g.clear()))), g.el);
      area.hidden = true;
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: '.heic,.heif,image/heic,image/heif', onFiles: (f) => list.add(f), label: 'HEIC 사진을 끌어다 놓거나 클릭해서 선택' }), list, row(conv), st), h('div', { class: 'panel stack' }, area));
      upd();
      return () => g.destroy();
    },
  });

  /* 30. EXIF 확인·삭제 */
  add({
    id: 'exif', cat: 'photo', code: 'EXIF', name: '사진 촬영정보 확인·삭제', kw: 'EXIF GPS 위치 촬영일시 메타데이터 개인정보 섬네일', lib: true,
    desc: '사진마다 촬영 일시·기기·GPS 위치를 확인하고, 위치정보를 지운 사본을 한 번에 저장',
    long: '스마트폰 사진에는 찍은 장소의 GPS 좌표가 들어 있는 경우가 많습니다. 빨간 "GPS" 표시가 붙은 사진은 위치가 들어 있습니다. 외부에 보내기 전에 지우세요.',
    render(el) {
      const st = status(); const count = countPill(); const area = h('div', { class: 'stack' });
      const g = board({ onChange: () => upd() });
      const tb = h('tbody');
      const fmtDate = (dt) => (dt instanceof Date ? `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())} ${pad(dt.getHours())}:${pad(dt.getMinutes())}` : dt ? String(dt) : '–');
      function drawTable() {
        tb.replaceChildren(...g.order.map((it, k) => {
          const d = it.exif || {}, gps = isFinite(d.latitude);
          return h('tr', null, h('td', { class: 'mono' }, k + 1), h('td', null, it.file.name), h('td', { class: 'mono' }, fmtDate(d.DateTimeOriginal || d.CreateDate)),
            h('td', null, [d.Make, d.Model].filter(Boolean).join(' ') || '–'),
            h('td', null, gps ? h('span', null, h('span', { class: 'pill bad' }, 'GPS'), ' ', h('span', { class: 'mono', style: { fontSize: '12px' } }, `${d.latitude.toFixed(5)}, ${d.longitude.toFixed(5)}`), ' ',
              h('button', { class: 'ib', type: 'button', title: '좌표 복사', 'aria-label': '좌표 복사', style: { width: 'auto', padding: '0 8px' }, onclick: () => App.copy(`${d.latitude.toFixed(6)}, ${d.longitude.toFixed(6)}`) }, '복사')) : h('span', { class: 'pill ok' }, '없음')));
        }));
      }
      function upd() { const gpsN = g.order.filter((it) => it.gps).length; count.textContent = `${pickLabel(g)} · 위치정보 있는 사진 ${gpsN}장`; area.hidden = !g.count(); drawTable(); }
      const strip = btn('촬영정보 지운 사본 저장', guard(st, async () => {
        const list = g.targets().filter((it) => it.img), skipped = g.targets().length - list.length, outs = [];
        for (const [k, it] of list.entries()) { st.textContent = `저장 준비 ${k + 1}/${list.length}`; outs.push([`${baseName(it.file.name)}_정보삭제.jpg`, await canvasBlob(toCanvas(it.img), 'image/jpeg', 0.92)]); }
        if (outs.length) await saveMany(outs, `정보삭제_${stamp()}.zip`);
        st.textContent = `${outs.length}장 저장` + (skipped ? ` · HEIC ${skipped}장은 먼저 "HEIC → JPG"로 바꿔 주세요` : '');
      }), true);
      area.append(boardBar(g, row(count, btn('위치정보 있는 사진만 고르기', () => g.setPositions(g.order.map((it, k) => (it.gps ? k : -1)).filter((k) => k >= 0))), strip, btn('모두 비우기', () => g.clear()))),
        g.el, h('div', { class: 'tbl-wrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '#'), h('th', null, '파일'), h('th', null, '촬영 일시'), h('th', null, '기기'), h('th', null, '위치(GPS)'))), tb)),
        h('p', { class: 'note', style: { margin: 0 } }, '좌표가 필요하면 [복사]한 뒤 ', h('a', { href: 'https://map.vworld.kr/map/maps.do', target: '_blank', rel: 'noopener noreferrer' }, '브이월드 지도'), '에 직접 붙여 넣으세요. 좌표는 자동으로 넘어가지 않습니다.'), st);
      area.hidden = true;
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: 'image/jpeg,image/heic,image/png,image/webp,.heic', sub: '여러 장 한 번에 · 더 넣으면 뒤에 이어 붙습니다', onFiles: guard(st, async (fs) => {
        await lib('exifr'); const items = [];
        for (const [k, f] of fs.entries()) {
          st.textContent = `읽는 중 ${k + 1}/${fs.length}`;
          let d = null; try { d = await exifr.parse(f, { gps: true, tiff: true, exif: true }); } catch (_) {}
          let it;
          try { it = imageItem(f, await loadImage(f)); }
          catch (_) { /* HEIC 등 미리보기가 안 되는 사진 */ it = { file: f, async paint(px) { const c = document.createElement('canvas'); c.width = c.height = Math.round(px * 0.7); const x = c.getContext('2d'); x.fillStyle = '#ddd'; x.fillRect(0, 0, c.width, c.height); x.fillStyle = '#555'; x.font = `700 ${Math.round(px / 8)}px sans-serif`; x.textAlign = 'center'; x.fillText('HEIC', c.width / 2, c.height / 2); return c; } }; }
          const gps = !!(d && isFinite(d.latitude));
          items.push(Object.assign(it, { exif: d, gps, label: f.name, tag: gps ? 'GPS' : '', color: '#B42318' }));
        }
        g.add(items); st.textContent = `${items.length}장 확인 · 위치정보 있는 사진 ${items.filter((i) => i.gps).length}장`;
      }) }), area), h('p', { class: 'note' }, '사본은 JPG로 다시 저장되며 촬영정보가 모두 빠집니다. 섬네일을 고르지 않으면 모든 사진을 저장합니다.'));
      upd();
      return () => g.destroy();
    },
  });

  /* 31. 사진대지 */
  add({
    id: 'sheet', cat: 'photo', code: 'SHEET', name: '사진대지 만들기', kw: '화재조사 현장사진 보고서 첨부 설명 A4 PDF 순서', lib: true,
    desc: '사진과 설명을 넣으면 A4 사진대지 PDF를 자동으로 배치',
    long: '사진을 넣고 각 사진 아래 설명을 적으면 A4 한 쪽에 2장·4장·6장씩 배치한 사진대지 PDF를 만듭니다. 사진은 끌어다 놓아 순서를 바꿀 수 있습니다. 화재조사·점검 결과·활동 보고에 첨부할 수 있습니다.',
    render(el) {
      const st = status(); let items = [], dragFrom = -1;
      const title = field({ label: '제목', type: 'text', value: '화재현장 사진대지' });
      const meta1 = field({ label: '사건·장소', type: 'text', value: '동두천시 ○○동 ○○번지 주택 화재' });
      const meta2 = field({ label: '일시·작성자', type: 'text', value: `${new Date().getFullYear()}. ${new Date().getMonth() + 1}. ${new Date().getDate()}. 화재조사관 ○○○` });
      const per = field({ label: '한 쪽에', type: 'select', value: 2, options: [[2, '2장 (세로 배치)'], [4, '4장 (2×2)'], [6, '6장 (2×3)']] });
      const grid = h('div', { class: 'thumbs', style: { gridTemplateColumns: 'repeat(auto-fill,minmax(200px,1fr))' } });
      const prev = h('canvas', { class: 'work', style: { width: '100%', maxWidth: '420px', background: '#fff' } });
      const moveTo = (from, to) => { if (from === to || from < 0) return; const [m] = items.splice(from, 1); items.splice(to, 0, m); drawGrid(); preview(); };
      function drawGrid() {
        grid.replaceChildren(...items.map((it, i) => {
          const cap = h('textarea', { rows: 2, 'aria-label': `사진 ${i + 1} 설명`, style: { minHeight: '52px', fontSize: '13px' } }); cap.value = it.cap; cap.addEventListener('input', () => { it.cap = cap.value; });
          cap.addEventListener('change', preview);
          const fig = h('figure', { class: 'stack sheet-fig', style: { gap: '6px' }, draggable: 'true' }, h('img', { src: it.url, alt: '', draggable: 'false' }), h('span', null, `사진 ${i + 1} · 끌어서 순서 변경`), cap,
            h('div', { class: 'btns' }, h('button', { class: 'ib', type: 'button', 'aria-label': '앞으로', onclick: () => moveTo(i, Math.max(0, i - 1)) }, '←'),
              h('button', { class: 'ib', type: 'button', 'aria-label': '뒤로', onclick: () => moveTo(i, Math.min(items.length - 1, i + 1)) }, '→'),
              h('button', { class: 'ib', type: 'button', 'aria-label': '빼기', onclick: () => { const [gone] = items.splice(i, 1); URL.revokeObjectURL(gone.url); drawGrid(); preview(); } }, '×')));
          /* 설명 칸에서 글자를 고를 때는 끌기가 시작되지 않게 */
          cap.addEventListener('mousedown', () => (fig.draggable = false)); cap.addEventListener('mouseup', () => (fig.draggable = true)); cap.addEventListener('blur', () => (fig.draggable = true));
          fig.addEventListener('dragstart', (e) => { dragFrom = i; e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', ''); } catch (_) {} fig.classList.add('dragging'); });
          fig.addEventListener('dragend', () => { dragFrom = -1; fig.classList.remove('dragging'); grid.querySelectorAll('.over-l').forEach((x) => x.classList.remove('over-l')); });
          fig.addEventListener('dragover', (e) => { if (dragFrom < 0) return; e.preventDefault(); fig.classList.add('over-l'); });
          fig.addEventListener('dragleave', () => fig.classList.remove('over-l'));
          fig.addEventListener('drop', (e) => { e.preventDefault(); fig.classList.remove('over-l'); moveTo(dragFrom, i); });
          return fig;
        }));
        b.disabled = !items.length;
      }
      /* A4 150dpi 캔버스 한 쪽 그리기 */
      function wrapText(x, text, maxW) { const out = []; for (const para of String(text).split('\n')) { let line = ''; for (const ch of para) { if (x.measureText(line + ch).width > maxW && line) { out.push(line); line = ch; } else line += ch; } out.push(line); } return out; }
      function page(pi, total) {
        const W = 1240, H = 1754, M = 90, n = +per.input.value, c = document.createElement('canvas'); c.width = W; c.height = H; const x = c.getContext('2d');
        const F = '"Pretendard Variable","Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif';
        x.fillStyle = '#fff'; x.fillRect(0, 0, W, H); x.fillStyle = '#111'; x.textBaseline = 'top';
        x.font = `700 44px ${F}`; x.textAlign = 'center'; x.fillText(title.input.value, W / 2, M);
        x.font = `400 24px ${F}`; x.textAlign = 'left'; x.fillText(meta1.input.value, M, M + 72); x.textAlign = 'right'; x.fillText(meta2.input.value, W - M, M + 72);
        x.lineWidth = 3; x.beginPath(); x.moveTo(M, M + 112); x.lineTo(W - M, M + 112); x.stroke();
        const top = M + 132, bottom = H - M - 40, cols = n === 2 ? 1 : 2, rows = n / cols, gap = 24, capH = 86;
        const cw = (W - 2 * M - gap * (cols - 1)) / cols, ch = (bottom - top - gap * (rows - 1)) / rows;
        for (let k = 0; k < n; k++) {
          const idx = pi * n + k, it = items[idx]; if (!it) break;
          const cx = M + (k % cols) * (cw + gap), cy = top + Math.floor(k / cols) * (ch + gap), ih = ch - capH;
          x.strokeStyle = '#333'; x.lineWidth = 2; x.strokeRect(cx, cy, cw, ch);
          const s = Math.min((cw - 16) / it.img.naturalWidth, (ih - 16) / it.img.naturalHeight), w = it.img.naturalWidth * s, hh = it.img.naturalHeight * s;
          x.drawImage(it.img, cx + (cw - w) / 2, cy + 8 + (ih - 16 - hh) / 2, w, hh);
          x.beginPath(); x.moveTo(cx, cy + ih); x.lineTo(cx + cw, cy + ih); x.stroke();
          x.fillStyle = '#111'; x.textAlign = 'left'; x.font = `700 22px ${F}`; x.fillText(`사진 ${idx + 1}`, cx + 12, cy + ih + 10);
          x.font = `400 21px ${F}`; wrapText(x, it.cap, cw - 120).slice(0, 3).forEach((ln, j) => x.fillText(ln, cx + 100, cy + ih + 10 + j * 25));
        }
        x.font = `400 20px ${F}`; x.textAlign = 'center'; x.fillStyle = '#555'; x.fillText(`- ${pi + 1} / ${total} -`, W / 2, H - M + 10);
        return c;
      }
      function preview() { if (!items.length) { prev.width = 1; prev.height = 1; return; } const p = page(0, Math.ceil(items.length / +per.input.value)); prev.width = p.width; prev.height = p.height; prev.getContext('2d').drawImage(p, 0, 0); }
      [title, meta1, meta2].forEach((f) => f.input.addEventListener('change', preview)); per.input.addEventListener('change', preview);
      const b = h('button', { class: 'btn primary', type: 'button', disabled: true }, 'PDF로 저장');
      b.addEventListener('click', guard(st, async () => {
        await lib('pdflib'); const pdf = await PDFLib.PDFDocument.create(); const total = Math.ceil(items.length / +per.input.value);
        for (let i = 0; i < total; i++) { st.textContent = `쪽 만드는 중 ${i + 1}/${total}`; const jpg = await pdf.embedJpg(await (await canvasBlob(page(i, total), 'image/jpeg', 0.88)).arrayBuffer()); pdf.addPage([595.28, 841.89]).drawImage(jpg, { x: 0, y: 0, width: 595.28, height: 841.89 }); }
        const bytes = await pdf.save(); st.textContent = `${total}쪽 · ${fmtSize(bytes.length)}`; save(`${title.input.value || '사진대지'}_${stamp()}.pdf`, new Blob([bytes], { type: 'application/pdf' }));
      }));
      el.append(h('div', { class: 'panel stack' }, h('div', { class: 'fields' }, title, meta1, meta2, per),
        dropzone({ accept: IMG, onFiles: guard(st, async (fs) => { for (const f of fs) { const img = await loadImage(f); items.push({ img, url: img.src, cap: baseName(f.name) }); } drawGrid(); preview(); }), sub: '사진 순서는 끌어다 놓아 바꾸고, 설명은 사진 아래에서 고칩니다' }),
        grid, h('div', { class: 'btns' }, b), st),
        h('div', { class: 'panel stack' }, h('b', null, '1쪽 미리보기'), prev));
      drawGrid();
      /* 도구를 닫으면 사진 임시 주소를 모두 반납 (2026-09-30 점검 #39) */
      return () => { items.forEach((it) => URL.revokeObjectURL(it.url)); items = []; };
    },
  });

  /* 여러 장 편집기 공통: 위에는 섬네일 판, 아래에는 지금 고른 사진의 편집 캔버스.
     편집 결과는 사진마다 it.work(캔버스)에 따로 보관하고, 섬네일에도 바로 반영한다. */
  function editorShell(el, st, opt) {
    let cur = null;
    const g = board({ select: opt.select || 'single', onChange: () => upd(), onClick: (it) => { if (opt.select !== 'multi' || g.sel.has(it)) open(it); } });
    const count = countPill();
    const cv = h('canvas', { class: 'work', style: { width: '100%', cursor: 'crosshair', display: 'block' } });
    const title = h('b');
    const area = h('div', { class: 'stack' });
    const work = (it) => it.work || (it.work = toCanvas(it.img, opt.maxSide || 0));
    function show() { if (!cur) return; const w = work(cur); cv.width = w.width; cv.height = w.height; cv.getContext('2d').drawImage(w, 0, 0); if (opt.overlay) opt.overlay(cv); }
    function reset() { cur = null; title.textContent = ''; cv.width = cv.height = 0; }   /* 사진을 모두 뺐을 때 — 지운 사진을 계속 가리키지 않게 */
    function open(it) { cur = it; title.textContent = `지금 편집: ${it.file.name}`; show(); if (opt.onOpen) opt.onOpen(it); }
    /* 편집 캔버스(cv)의 내용을 사진의 보관본으로 옮기고 섬네일을 다시 그린다 */
    function commit(it = cur) { const w = document.createElement('canvas'); w.width = cv.width; w.height = cv.height; w.getContext('2d').drawImage(cv, 0, 0); it.work = w; it.edited = true; g.repaint(it); g.refresh(); }
    function setWork(it, canvas) { it.work = canvas; it.edited = true; g.repaint(it); if (it === cur) show(); g.refresh(); }
    function upd() { const ed = g.order.filter((it) => it.edited).length; count.textContent = `${g.count()}장` + (g.sel.size > 1 ? ` · ${g.sel.size}장 선택` : '') + (ed ? ` · 편집한 사진 ${ed}장` : ''); area.hidden = !g.count(); }
    async function saveSet(list, suffix, fmt = 'jpg') {
      if (!list.length) return toast('저장할 사진이 없습니다');
      const type = fmt === 'png' ? 'image/png' : 'image/jpeg', outs = [];
      for (const [k, it] of list.entries()) { st.textContent = `저장 준비 ${k + 1}/${list.length}`; outs.push([`${baseName(it.file.name)}_${suffix}.${fmt}`, await canvasBlob(work(it), type, 0.92)]); }
      await saveMany(outs, `사진_${suffix}_${stamp()}.zip`); st.textContent = `${outs.length}장 저장`;
    }
    const drop = dropzone({ accept: IMG, sub: '여러 장 한 번에 · 더 넣으면 뒤에 이어 붙습니다', onFiles: guard(st, async (fs) => {
      const items = await photoItems(fs, st); g.add(items); st.textContent = opt.hint || '';
      if (!cur && items[0]) { if (opt.select !== 'multi') g.setPositions([g.order.indexOf(items[0])]); open(items[0]); }
    }) });
    return { g, cv, count, title, area, drop, work, show, open, reset, commit, setWork, saveSet, get cur() { return cur; }, upd };
  }

  /* 32. 모자이크 */
  add({
    id: 'mosaic', cat: 'photo', code: 'BLUR', name: '사진 모자이크·가리기', kw: '얼굴 번호판 개인정보 블러 마스킹 보도 섬네일',
    desc: '여러 장을 넣고 섬네일에서 골라가며 얼굴·차량번호·문패를 모자이크나 검은 박스로 가리기',
    long: '보도자료·SNS·교육자료에 쓰기 전에 개인을 알아볼 수 있는 부분을 가리세요. 위 섬네일에서 사진을 누르고, 아래 큰 사진에서 가릴 영역을 드래그합니다. 가린 사진은 한 번에 저장할 수 있습니다.',
    render(el) {
      const st = status();
      const E = editorShell(el, st, { maxSide: 3000, hint: '섬네일에서 사진을 누르고, 아래 큰 사진에서 가릴 부분을 드래그하세요' });
      const { g, cv } = E;
      const mode = field({ label: '방식', type: 'select', value: 'mosaic', options: [['mosaic', '모자이크'], ['black', '검은 박스'], ['blur', '흐리게']] });
      const str = field({ label: '강도', type: 'range', value: 5, min: 2, max: 10, step: 1 });
      let start = null, snap = null;
      const tagOf = (it) => { it.tag = it.masks ? `가림 ${it.masks}` : fmtSize(it.file.size); it.color = it.masks ? '#1C7A4A' : 'rgba(20,22,25,.62)'; const t = it.fig.querySelector('.tag'); if (t) { t.textContent = it.tag; t.style.background = it.color; } };
      cv.addEventListener('pointerdown', (e) => { if (!E.cur) return; start = ptOf(cv, e); snap = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height); cv.setPointerCapture(e.pointerId); });
      cv.addEventListener('pointermove', (e) => { if (!start) return; const [x, y] = ptOf(cv, e), c = cv.getContext('2d'); c.putImageData(snap, 0, 0); c.strokeStyle = '#ff3b30'; c.lineWidth = Math.max(2, cv.width / 400); c.setLineDash([10, 6]); c.strokeRect(start[0], start[1], x - start[0], y - start[1]); c.setLineDash([]); });
      cv.addEventListener('pointerup', (e) => {
        if (!start) return; const [x1, y1] = ptOf(cv, e), c = cv.getContext('2d'); c.putImageData(snap, 0, 0);
        const cx0 = Math.max(0, Math.min(start[0], x1)), cy0 = Math.max(0, Math.min(start[1], y1)), cx1 = Math.min(cv.width, Math.max(start[0], x1)), cy1 = Math.min(cv.height, Math.max(start[1], y1));
        const x = Math.round(cx0), y = Math.round(cy0), w = Math.round(cx1 - cx0), hh = Math.round(cy1 - cy0); start = null; snap = null;
        if (w < 4 || hh < 4) return;
        const it = E.cur; it.undo = it.undo || []; it.undo.push({ x, y, d: c.getImageData(x, y, w, hh) }); if (it.undo.length > 20) it.undo.shift();
        const k = num(str);
        if (mode.input.value === 'black') { c.fillStyle = '#000'; c.fillRect(x, y, w, hh); }
        else if (mode.input.value === 'blur') {
          /* 흐리게: 크게 줄였다가 부드럽게 다시 키운다. 브라우저의 blur 효과(filter)는 일부 아이폰에서 조용히 무시돼
             "가림"으로 표시되는데 실제로는 안 가려지는 일이 있어 쓰지 않는다 (2026-09-29 검토) */
          const f = Math.max(6, Math.round(k * 3)), t = document.createElement('canvas');
          t.width = Math.max(1, Math.ceil(w / f)); t.height = Math.max(1, Math.ceil(hh / f));
          const tx = t.getContext('2d'); tx.imageSmoothingEnabled = true; tx.imageSmoothingQuality = 'high'; tx.drawImage(cv, x, y, w, hh, 0, 0, t.width, t.height);
          c.imageSmoothingEnabled = true; c.imageSmoothingQuality = 'high'; c.drawImage(t, 0, 0, t.width, t.height, x, y, w, hh);
        }
        else { const cell = Math.max(4, Math.round((Math.max(cv.width, cv.height) / 900) * k * 4)); const t = document.createElement('canvas'); t.width = Math.max(1, Math.ceil(w / cell)); t.height = Math.max(1, Math.ceil(hh / cell)); t.getContext('2d').drawImage(cv, x, y, w, hh, 0, 0, t.width, t.height); c.imageSmoothingEnabled = false; c.drawImage(t, 0, 0, t.width, t.height, x, y, w, hh); c.imageSmoothingEnabled = true; }
        it.masks = (it.masks || 0) + 1; E.commit(it); tagOf(it); st.textContent = `${it.file.name} · ${it.masks}곳 가림`;
      });
      const undo = () => { const it = E.cur; if (!it || !it.undo || !it.undo.length) return; const u = it.undo.pop(); cv.getContext('2d').putImageData(u.d, u.x, u.y); it.masks = Math.max(0, (it.masks || 1) - 1); E.commit(it); if (!it.masks) it.edited = false; tagOf(it); g.refresh(); st.textContent = `${it.file.name} · ${it.masks}곳 가림`; };
      E.area.append(boardBar(g, row(E.count, btn('사진 빼기', () => { const it = E.cur; if (!it) return; g.remove([it]); if (g.order[0]) { g.setPositions([0]); E.open(g.order[0]); } else E.reset(); }), btn('모두 비우기', () => { g.clear(); E.reset(); })), { noSelect: true }), g.el,
        h('div', { class: 'panel stack', style: { padding: '14px' } }, E.title, h('div', { class: 'fields' }, mode, str),
          row(btn('되돌리기', undo), btn('이 사진 저장', () => E.cur && E.saveSet([E.cur], '가림')), btn('가린 사진 모두 저장', () => E.saveSet(g.order.filter((it) => it.masks), '가림'), true), btn('모든 사진 저장', () => E.saveSet(g.order, '가림'))),
          st, cv));
      E.area.hidden = true;
      el.append(h('div', { class: 'panel stack' }, E.drop, E.area));
      E.upd();
      return () => g.destroy();
    },
  });

  /* 33. 회전·자르기 */
  add({
    id: 'crop', cat: 'photo', code: 'CROP', name: '사진 회전·자르기', kw: '돌리기 반전 잘라내기 트리밍 섬네일 여러장',
    desc: '여러 장을 섬네일에서 골라 한꺼번에 회전·반전하고, 한 장씩 필요한 부분만 자르기',
    long: '섬네일을 눌러 고르면 고른 사진 모두에 회전·반전이 적용됩니다. 마지막으로 누른 사진이 아래에 크게 뜨고, 거기서 드래그하면 그 사진만 자릅니다.',
    render(el) {
      const st = status(); let sel = null, start = null;
      const drawSel = (c) => { if (!sel) return; const x = c.getContext('2d'); x.fillStyle = 'rgba(0,0,0,.5)'; x.beginPath(); x.rect(0, 0, c.width, c.height); x.rect(sel[0], sel[1], sel[2], sel[3]); x.fill('evenodd'); x.strokeStyle = '#fff'; x.lineWidth = Math.max(2, c.width / 500); x.strokeRect(sel[0], sel[1], sel[2], sel[3]); };
      const E = editorShell(el, st, { select: 'multi', overlay: drawSel, onOpen: () => { sel = null; info(); }, hint: '사진을 눌러 고르세요. 회전은 고른 사진 모두에, 자르기는 아래 큰 사진에만 적용됩니다' });
      const { g, cv } = E;
      const info = () => { const w = E.cur && E.work(E.cur); st.textContent = w ? `${E.cur.file.name} · ${w.width}×${w.height}px` + (sel ? ` · 자를 영역 ${Math.round(sel[2])}×${Math.round(sel[3])}` : '') : ''; };
      const transform = (it, fn, wf) => { const src = E.work(it), [w, hh] = wf(src), n = document.createElement('canvas'); n.width = w; n.height = hh; fn(n.getContext('2d'), src); E.setWork(it, n); };
      const rot = (it, dir) => transform(it, (c, s) => { c.translate(s.height / 2, s.width / 2); c.rotate((dir * Math.PI) / 2); c.drawImage(s, -s.width / 2, -s.height / 2); }, (s) => [s.height, s.width]);
      const flip = (it, hz) => transform(it, (c, s) => { c.translate(hz ? s.width : 0, hz ? 0 : s.height); c.scale(hz ? -1 : 1, hz ? 1 : -1); c.drawImage(s, 0, 0); }, (s) => [s.width, s.height]);
      const targets = () => (g.sel.size ? g.picked() : E.cur ? [E.cur] : []);
      const each = (fn) => () => { const t = targets(); if (!t.length) return toast('사진을 먼저 고르세요'); sel = null; t.forEach(fn); info(); };
      cv.addEventListener('pointerdown', (e) => { if (!E.cur) return; start = ptOf(cv, e); cv.setPointerCapture(e.pointerId); });
      cv.addEventListener('pointermove', (e) => { if (!start) return; let [x, y] = ptOf(cv, e); x = Math.max(0, Math.min(cv.width, x)); y = Math.max(0, Math.min(cv.height, y)); sel = [Math.min(start[0], x), Math.min(start[1], y), Math.abs(x - start[0]), Math.abs(y - start[1])]; E.show(); info(); });
      cv.addEventListener('pointerup', () => { start = null; if (sel && (sel[2] < 5 || sel[3] < 5)) { sel = null; E.show(); } info(); });
      const fm = field({ label: '저장 형식', type: 'select', value: 'jpg', options: [['jpg', 'JPG'], ['png', 'PNG']] });
      E.area.append(boardBar(g, h('div', { class: 'stack', style: { gap: '8px' } },
        row(E.count, btn('↺ 왼쪽 90°', each((it) => rot(it, -1))), btn('↻ 오른쪽 90°', each((it) => rot(it, 1))), btn('좌우 반전', each((it) => flip(it, true))), btn('상하 반전', each((it) => flip(it, false))),
          btn('원본으로', each((it) => { it.work = null; it.edited = false; g.repaint(it); if (it === E.cur) E.show(); g.refresh(); }))),
        row(btn('선택한 사진 빼기', () => { if (!g.sel.size) return toast('뺄 사진을 먼저 고르세요'); g.remove(g.picked()); if (!g.order.includes(E.cur)) { if (g.order[0]) E.open(g.order[0]); else E.reset(); } }), btn('모두 비우기', () => { g.clear(); E.reset(); })))),
        g.el,
        h('div', { class: 'panel stack', style: { padding: '14px' } }, E.title,
          row(btn('드래그한 영역 자르기', () => { if (!E.cur || !sel) return toast('아래 사진에서 자를 영역을 드래그해 주세요'); const s = sel.map(Math.round); sel = null; transform(E.cur, (c, src) => c.drawImage(src, s[0], s[1], s[2], s[3], 0, 0, s[2], s[3]), () => [s[2], s[3]]); info(); }),
            fm, btn('이 사진 저장', () => E.cur && E.saveSet([E.cur], '편집', fm.input.value)), btn('편집한 사진 모두 저장', () => E.saveSet(g.order.filter((it) => it.edited), '편집', fm.input.value), true), btn('모든 사진 저장', () => E.saveSet(g.order, '편집', fm.input.value))),
          st, cv));
      E.area.hidden = true;
      el.append(h('div', { class: 'panel stack' }, E.drop, E.area));
      E.upd();
      return () => g.destroy();
    },
  });
})();
