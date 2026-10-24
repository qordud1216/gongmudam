/* 문서·PDF 도구 — pdf-lib(편집), pdf.js(화면 그리기)를 필요할 때만 불러온다.
   2026-09-29: 모든 PDF 도구를 섬네일 판(board)으로 바꿨다. 쪽을 눈으로 보면서 고르고, 끌어서 순서를 바꾼다. */
(function () {
  'use strict';
  const { add, h, field, num, fmtSize, save, stamp, baseName, dropzone, readBuf, loadImage, canvasBlob, lib, toast, board, boardBar, btn, row, hint, parseRange, picksText, imageItem } = App;
  const status = () => h('div', { class: 'status' });
  const pdfOnly = '.pdf,application/pdf';
  const FILE_COLORS = ['#D0381C', '#1F6FEB', '#1C7A4A', '#9A6200', '#8B3FD9', '#C2185B', '#00838F', '#5D4037'];

  async function openPdf(file) {
    await lib('pdflib');
    let doc;
    try { doc = await PDFLib.PDFDocument.load(await readBuf(file), { ignoreEncryption: true }); }
    catch (e) { throw new Error(`${file.name}: PDF를 열지 못했습니다 (${e.message})`); }
    /* 편집 잠금(암호)이 걸린 PDF는 이 도구로 편집하면 내용이 깨진다 (2026-09-29 검토) */
    if (doc.isEncrypted) throw new Error(`${file.name}은(는) 편집 잠금이 걸린 PDF라 이대로 편집하면 내용이 깨집니다. 작성 기관에서 잠금 없는 파일을 받거나, "PDF 용량 줄이기"로 한 번 다시 저장한 파일을 쓰세요.`);
    return doc;
  }
  async function renderPage(pdfjsDoc, n, scale) {
    const page = await pdfjsDoc.getPage(n);
    const vp = page.getViewport({ scale });
    const c = document.createElement('canvas'); c.width = Math.round(vp.width); c.height = Math.round(vp.height);
    const ctx = c.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height);
    await page.render({ canvasContext: ctx, viewport: vp }).promise;
    return c;
  }
  async function openPdfjs(file) { await lib('pdfjs'); return pdfjsLib.getDocument({ data: new Uint8Array(await readBuf(file)) }).promise; }
  const guard = (st, fn) => App.busy(async (...a) => { try { await fn(...a); } catch (e) { st.textContent = '오류: ' + e.message; console.error(e); } });
  const pdfBlob = async (doc) => new Blob([await doc.save()], { type: 'application/pdf' });
  /* 화면에 보이는 모습(회전·잘림 반영) 그대로의 틀. W·H는 보이는 가로·세로(pt), toPdf(x, y)는 위에서부터 잰 좌표를 PDF 좌표로 바꾼다 */
  async function viewFrame(pj, i) {
    const page = await pj.getPage(i + 1), vp = page.getViewport({ scale: 1 });
    return { W: vp.width, H: vp.height, rot: ((page.rotate % 360) + 360) % 360, toPdf: (x, y) => vp.convertToPdfPoint(x, y) };
  }
  /* 그림의 가운데를 (cx, cy)에 두고, 보이는 화면 기준으로 deg만큼 돌려서(반시계) 그린다 */
  function drawCentered(page, img, cx, cy, w, hh, deg, opacity) {
    const t = (deg * Math.PI) / 180;
    page.drawImage(img, { x: cx - ((w / 2) * Math.cos(t) - (hh / 2) * Math.sin(t)), y: cy - ((w / 2) * Math.sin(t) + (hh / 2) * Math.cos(t)), width: w, height: hh, rotate: PDFLib.degrees(deg), opacity });
  }
  const addRot = (p, deg) => { if (deg) p.setRotation(PDFLib.degrees((((p.getRotation().angle + deg) % 360) + 360) % 360)); };

  /* 판에 올릴 항목 만들기: PDF 쪽 / 이미지 */
  function pdfItems(pj, extra) {
    return Array.from({ length: pj.numPages }, (_, i) => Object.assign({
      i, pj,
      async paint(px) { const page = await pj.getPage(i + 1), vp = page.getViewport({ scale: 1 }); return renderPage(pj, i + 1, px / Math.max(vp.width, vp.height)); },
    }, extra || {}));
  }

  /* 끌어서 순서를 바꾼 쪽은 "2 ← 원래 5쪽"처럼 원래 쪽 번호를 함께 보여준다 (2026-10-07) */
  const showOrig = (getG) => (it) => { const k = getG().order.indexOf(it); if (k !== it.i) it.no.textContent = `${k + 1} ← 원래 ${it.i + 1}쪽`; };
  const isMoved = (g) => g.order.some((x, k) => x.i !== k);

  /* 20. 합치기 */
  add({
    id: 'pdfmerge', cat: 'pdf', code: 'MERGE', name: 'PDF 합치기', kw: '병합 결합 순서 섬네일', lib: true,
    desc: '여러 PDF의 모든 쪽을 섬네일로 펼쳐 놓고 끌어서 순서를 맞춘 뒤 하나로',
    long: '여러 PDF를 넣으면 모든 쪽이 파일별 색 표시(A, B, C…)와 함께 한 판에 펼쳐집니다. 끌어다 놓아 쪽 순서를 바꾸고, 필요 없는 쪽은 골라서 뺀 뒤 합치세요.',
    render(el) {
      const st = status(); const files = []; let n = 0;
      const g = board({ reorder: true, onChange: () => upd() });
      const legend = h('div', { class: 'btns' });
      const count = h('span', { class: 'pill ok' });
      const area = h('div', { class: 'stack' });
      function upd() {
        count.textContent = `총 ${g.count()}쪽 · 파일 ${files.length}개` + (g.sel.size ? ` · ${g.sel.size}쪽 선택` : '');
        legend.replaceChildren(...files.map((f) => h('span', { class: 'pill', style: { background: 'var(--surface-2)', color: 'var(--ink-2)' } }, h('b', { style: { color: f.color } }, f.tag + ' '), `${f.file.name} · ${f.pages}쪽`)));
        area.hidden = !g.count();
      }
      const merge = btn('합쳐서 저장', guard(st, async () => {
        if (!g.count()) return;
        st.textContent = '합치는 중…'; const out = await PDFLib.PDFDocument.create();
        for (const it of g.order) { const [p] = await out.copyPages(it.src.doc, [it.i]); addRot(p, it.rot); out.addPage(p); }
        const blob = await pdfBlob(out); st.textContent = `완료 · ${out.getPageCount()}쪽 · ${fmtSize(blob.size)}`;
        save(`합본_${stamp()}.pdf`, blob);
      }), true);
      area.append(boardBar(g, h('div', { class: 'stack', style: { gap: '8px' } },
        row(count, btn('← 앞으로', () => g.shift(g.picked(), -1)), btn('뒤로 →', () => g.shift(g.picked(), 1)),
          btn('↺', () => (g.sel.size ? g.turn(g.picked(), -90) : toast('돌릴 쪽을 먼저 고르세요'))), btn('↻', () => (g.sel.size ? g.turn(g.picked(), 90) : toast('돌릴 쪽을 먼저 고르세요'))),
          btn('선택한 쪽 빼기', () => { if (!g.sel.size) return toast('뺄 쪽을 먼저 고르세요'); g.remove(g.picked()); }),
          btn('모두 비우기', () => { g.clear(); files.length = 0; n = 0; upd(); }), merge),
        legend)), hint('끌어다 놓으면 순서가 바뀝니다. 여러 쪽을 고른 채 끌면 함께 옮겨집니다. 휴대폰에서는 고른 뒤 ← → 단추를 쓰세요.'), st, g.el);
      area.hidden = true;
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: pdfOnly, sub: '여러 파일을 한 번에 넣어도 되고, 나중에 더 넣어도 뒤에 이어 붙습니다', onFiles: guard(st, async (fs) => {
        for (const file of fs) {
          st.textContent = `${file.name} 여는 중…`;
          const src = { file, doc: await openPdf(file), tag: String.fromCharCode(65 + (n % 26)), color: FILE_COLORS[n % FILE_COLORS.length] }; n++;
          const pj = await openPdfjs(file); src.pages = pj.numPages; files.push(src);
          g.add(pdfItems(pj, { src, tag: src.tag, color: src.color, label: `${file.name}` }));
        }
        upd(); st.textContent = '끌어서 순서를 맞춘 뒤 [합쳐서 저장]을 누르세요';
      }) }), area));
      upd();
      return () => g.destroy();
    },
  });

  /* 21. 페이지 추출·분리 */
  add({
    id: 'pdfsplit', cat: 'pdf', code: 'SPLIT', name: 'PDF 페이지 추출·분리', kw: '나누기 발췌 쪽 삭제 빼기 섬네일 순서 바꾸기 재배열', lib: true,
    desc: '쪽을 섬네일로 보면서 골라 새 PDF로 뽑거나, 빼거나, 한 쪽씩 나누거나, 끌어서 순서 바꾸기',
    long: 'PDF를 넣으면 모든 쪽이 작은 그림으로 펼쳐집니다. 눌러서 고르고(Shift+누르면 사이를 한꺼번에), 두 번 누르면 크게 봅니다. 섬네일을 끌어서 쪽 순서도 바꿀 수 있습니다.',
    render(el) {
      const st = status(); let file = null, doc = null, g = null;
      const area = h('div', { class: 'stack' });
      const count = h('span', { class: 'pill warn' }, '선택 없음');
      const b1 = btn('선택한 쪽만 새 PDF로', null, true), b2 = btn('선택한 쪽 빼고 저장'), b3 = btn('전체를 한 쪽씩 나눠 ZIP으로');
      const b4 = btn('바꾼 순서대로 전체 저장', null, true);   /* 2026-10-07 직원 요청: 섬네일을 끌어 쪽 순서 바꾸기 */
      const idxOf = (items) => items.map((x) => x.i);
      const upd = () => {
        const p = idxOf(g.picked());
        count.textContent = p.length ? `${p.length}쪽 선택 · ${picksText(p)}` : '선택 없음';
        count.className = 'pill ' + (p.length ? 'ok' : 'warn');
        b1.disabled = b2.disabled = !p.length;
        b3.textContent = p.length ? `선택한 ${p.length}쪽을 한 쪽씩 ZIP으로` : '전체를 한 쪽씩 나눠 ZIP으로';
        b4.hidden = !isMoved(g);
      };
      const out = async (idx, suffix) => {
        const o = await PDFLib.PDFDocument.create(); (await o.copyPages(doc, idx)).forEach((p) => o.addPage(p));
        save(`${baseName(file.name)}_${suffix}.pdf`, await pdfBlob(o));
      };
      b1.addEventListener('click', guard(st, async () => { const idx = idxOf(g.picked()); await out(idx, '발췌'); st.textContent = `${idx.length}쪽 추출 (${picksText(idx)})`; }));
      b2.addEventListener('click', guard(st, async () => {
        const idx = g.order.filter((x) => !g.sel.has(x)).map((x) => x.i);
        if (!idx.length) return toast('모든 쪽을 빼면 남는 쪽이 없습니다');
        await out(idx, '편집'); st.textContent = `${g.sel.size}쪽을 빼고 ${idx.length}쪽 저장`;
      }));
      b4.addEventListener('click', guard(st, async () => { const idx = g.order.map((x) => x.i); await out(idx, '순서변경'); st.textContent = `${idx.length}쪽을 바꾼 순서대로 저장`; }));
      b3.addEventListener('click', guard(st, async () => {
        await lib('jszip'); const z = new JSZip(); const idx = idxOf(g.targets());
        for (const [k, i] of idx.entries()) { const o = await PDFLib.PDFDocument.create(); const [p] = await o.copyPages(doc, [i]); o.addPage(p); z.file(`${baseName(file.name)}_${String(i + 1).padStart(3, '0')}.pdf`, await o.save()); st.textContent = `나누는 중 ${k + 1}/${idx.length}`; }
        save(`${baseName(file.name)}_쪽별.zip`, await z.generateAsync({ type: 'blob' })); st.textContent = `${idx.length}개 파일로 나눔`;
      }));
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: pdfOnly, multiple: false, onFiles: guard(st, async ([f]) => {
        st.textContent = '여는 중…'; if (g) g.destroy();
        file = f; doc = await openPdf(f); const pj = await openPdfjs(f);
        g = board({ reorder: true, onChange: () => upd(), decorate: showOrig(() => g) }); g.add(pdfItems(pj));
        area.replaceChildren(boardBar(g, row(count, b1, b2, b3, b4, btn('← 앞으로', () => g.shift(g.picked(), -1)), btn('뒤로 →', () => g.shift(g.picked(), 1)))),
          hint('섬네일을 끌어다 놓으면 쪽 순서가 바뀝니다 (여러 쪽을 고른 채 끌면 함께). 휴대폰은 고른 뒤 ← → 단추. 순서를 바꾸면 [바꾼 순서대로 전체 저장]이 나타납니다.'), st, g.el);
        upd(); st.textContent = `${f.name} · ${g.count()}쪽 · ${fmtSize(f.size)} — 쪽을 눌러 고르세요 (두 번 누르면 크게 보기)`;
      }) }), area));
      return () => { if (g) g.destroy(); };
    },
  });

  /* 22. 회전 */
  add({
    id: 'pdfrotate', cat: 'pdf', code: 'ROTATE', name: 'PDF 페이지 회전', kw: '돌리기 가로 세로 섬네일', lib: true,
    desc: '섬네일로 보면서 돌릴 쪽만 골라 90°·180° 회전',
    long: '쪽을 눌러 고른 뒤 회전 단추를 누르면 섬네일이 바로 돌아갑니다. 아무것도 고르지 않고 누르면 전체가 돌아갑니다.',
    render(el) {
      const st = status(); let file = null, g = null;
      const area = h('div', { class: 'stack' });
      const count = h('span', { class: 'pill ok' }, '선택 없음');
      const upd = () => { const turned = g.order.filter((x) => x.rot).length; count.textContent = (g.sel.size ? `${g.sel.size}쪽 선택` : '선택 없음 (전체에 적용)') + (turned ? ` · 돌린 쪽 ${turned}개` : '') + (isMoved(g) ? ' · 순서 바뀜' : ''); };
      const b = btn('적용해서 저장', guard(st, async () => {
        const turned = g.order.filter((x) => x.rot), moved = isMoved(g);
        if (!turned.length && !moved) return toast('돌리거나 순서를 바꾼 쪽이 없습니다');
        const doc2 = await openPdf(file);
        if (!moved) { turned.forEach((x) => addRot(doc2.getPage(x.i), x.rot)); save(`${baseName(file.name)}_회전.pdf`, await pdfBlob(doc2)); st.textContent = `${turned.length}쪽 회전해서 저장`; return; }
        /* 순서를 바꿨으면 새 PDF에 바뀐 순서대로 옮겨 담는다 (2026-10-07) */
        const o = await PDFLib.PDFDocument.create();
        const pages = await o.copyPages(doc2, g.order.map((x) => x.i));
        pages.forEach((p, k) => { addRot(p, g.order[k].rot); o.addPage(p); });
        save(`${baseName(file.name)}_편집.pdf`, await pdfBlob(o)); st.textContent = `순서 변경` + (turned.length ? ` · ${turned.length}쪽 회전` : '') + `해서 ${pages.length}쪽 저장`;
      }), true);
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: pdfOnly, multiple: false, onFiles: guard(st, async ([f]) => {
        st.textContent = '여는 중…'; if (g) g.destroy();
        file = f; const pj = await openPdfjs(f); g = board({ reorder: true, onChange: () => upd(), decorate: showOrig(() => g) }); g.add(pdfItems(pj));
        area.replaceChildren(boardBar(g, row(count,
          btn('↺ 왼쪽 90°', () => g.turn(g.targets(), -90)), btn('↻ 오른쪽 90°', () => g.turn(g.targets(), 90)), btn('180°', () => g.turn(g.targets(), 180)),
          btn('← 앞으로', () => g.shift(g.picked(), -1)), btn('뒤로 →', () => g.shift(g.picked(), 1)),
          btn('원래대로', () => { g.reset(); g.sort((a, c) => a.i - c.i); }), b)),
          hint('섬네일을 끌어다 놓으면 쪽 순서도 바뀝니다. 휴대폰은 고른 뒤 ← → 단추.'), st, g.el);
        upd(); st.textContent = `${f.name} · ${g.count()}쪽 — 돌릴 쪽을 누르거나, 고르지 않고 단추를 누르면 전체가 돌아갑니다`;
      }) }), area));
      return () => { if (g) g.destroy(); };
    },
  });

  /* 23. 이미지 → PDF */
  add({
    id: 'img2pdf', cat: 'pdf', code: 'IMG→PDF', name: '이미지 → PDF', kw: '사진을 PDF로 이미지 JPG PNG 스캔 변환 순서 섬네일', lib: true,
    desc: '사진·스캔 이미지를 섬네일로 보며 순서·방향을 맞춰 A4 PDF 한 파일로',
    long: '사진을 넣으면 섬네일로 펼쳐집니다. 끌어서 순서를 바꾸고, 옆으로 누운 사진은 골라서 돌린 뒤 PDF로 만드세요.',
    render(el) {
      const st = status();
      const g = board({ reorder: true, onChange: () => upd() });
      const count = h('span', { class: 'pill ok' });
      const area = h('div', { class: 'stack' });
      const fit = field({ label: '용지', type: 'select', value: 'a4', options: [['a4', 'A4에 맞춤 (여백 10mm)'], ['orig', '사진 원본 크기']] });
      const q = field({ label: '화질', type: 'select', value: 0.85, options: [[0.95, '높음'], [0.85, '보통 (권장)'], [0.7, '용량 우선']] });
      function upd() { count.textContent = `${g.count()}장` + (g.sel.size ? ` · ${g.sel.size}장 선택` : ''); area.hidden = !g.count(); }
      const make = btn('PDF 만들기', guard(st, async () => {
        if (!g.count()) return;
        await lib('pdflib'); const pdf = await PDFLib.PDFDocument.create(); const A4 = [595.28, 841.89], M = 28.35;
        for (const [k, it] of g.order.entries()) {
          st.textContent = `처리 중 ${k + 1}/${g.count()}`;
          const img = it.img, s = Math.min(1, 2400 / Math.max(img.naturalWidth, img.naturalHeight));
          const w0 = Math.round(img.naturalWidth * s), h0 = Math.round(img.naturalHeight * s), side = it.rot % 180 !== 0;
          const c = document.createElement('canvas'); c.width = side ? h0 : w0; c.height = side ? w0 : h0;
          const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height);
          x.translate(c.width / 2, c.height / 2); x.rotate((it.rot * Math.PI) / 180); x.drawImage(img, -w0 / 2, -h0 / 2, w0, h0);
          const jpg = await pdf.embedJpg(await (await canvasBlob(c, 'image/jpeg', +q.input.value)).arrayBuffer());
          if (fit.input.value === 'a4') {
            const land = c.width > c.height, [W, H] = land ? [A4[1], A4[0]] : A4;
            const kk = Math.min((W - 2 * M) / c.width, (H - 2 * M) / c.height), w = c.width * kk, hh = c.height * kk;
            pdf.addPage([W, H]).drawImage(jpg, { x: (W - w) / 2, y: (H - hh) / 2, width: w, height: hh });
          } else { const w = (c.width * 72) / 150, hh = (c.height * 72) / 150; pdf.addPage([w, hh]).drawImage(jpg, { x: 0, y: 0, width: w, height: hh }); }
        }
        const blob = await pdfBlob(pdf); st.textContent = `완료 · ${pdf.getPageCount()}쪽 · ${fmtSize(blob.size)}`;
        save(`사진모음_${stamp()}.pdf`, blob);
      }), true);
      area.append(boardBar(g, row(count, btn('← 앞으로', () => g.shift(g.picked(), -1)), btn('뒤로 →', () => g.shift(g.picked(), 1)),
        btn('↺', () => (g.sel.size ? g.turn(g.picked(), -90) : toast('돌릴 사진을 먼저 고르세요'))), btn('↻', () => (g.sel.size ? g.turn(g.picked(), 90) : toast('돌릴 사진을 먼저 고르세요'))),
        btn('선택한 사진 빼기', () => { if (!g.sel.size) return toast('뺄 사진을 먼저 고르세요'); g.remove(g.picked()); }), btn('모두 비우기', () => g.clear()))),
        hint('끌어다 놓으면 순서가 바뀝니다. 돌릴 사진은 고른 뒤 ↺ ↻ 를 누르세요.'), g.el, h('div', { class: 'fields' }, fit, q), row(make), st);
      area.hidden = true;
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: 'image/jpeg,image/png,image/webp', sub: 'JPG·PNG·WEBP · 아이폰 HEIC는 먼저 "HEIC → JPG"로 바꿔 주세요 · 더 넣으면 뒤에 이어 붙습니다', onFiles: guard(st, async (fs) => {
        const items = []; for (const f of fs) { st.textContent = `${f.name} 읽는 중…`; items.push(Object.assign(imageItem(f, await loadImage(f)), { label: f.name })); }
        g.add(items); st.textContent = '';
      }) }), area));
      upd();
      return () => g.destroy();
    },
  });

  /* 글자를 이미지로 그려 넣는다 (PDF 기본 글꼴은 한글을 못 쓰므로) */
  function textImage(text, px, color, alpha) {
    const c = document.createElement('canvas'), x = c.getContext('2d');
    const font = `700 ${px}px "Pretendard Variable","Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",sans-serif`;
    x.font = font; const w = Math.ceil(x.measureText(text).width) + px, hh = Math.ceil(px * 1.5);
    c.width = w; c.height = hh; x.font = font; x.fillStyle = color; x.globalAlpha = alpha; x.textBaseline = 'middle'; x.fillText(text, px / 2, hh / 2);
    return c;
  }

  /* 24. 워터마크 */
  add({
    id: 'pdfmark', cat: 'pdf', code: 'MARK', name: 'PDF 워터마크', kw: '대외비 내부용 사본 표시 섬네일', lib: true,
    desc: '"대외비", "내부 검토용" 같은 한글 문구를 섬네일로 미리 보며 원하는 쪽에 표시',
    long: '문구와 배치를 바꾸면 섬네일에 바로 미리 보입니다. 쪽을 고르면 그 쪽에만, 고르지 않으면 모든 쪽에 넣습니다.',
    render(el) {
      const st = status(); let file = null, g = null, pj = null;
      const area = h('div', { class: 'stack' });
      const txt = field({ label: '문구', type: 'text', value: '대외비 · 경기소방' });
      const pos = field({ label: '배치', type: 'select', value: 'diag', options: [['diag', '가운데 대각선'], ['tile', '바둑판 반복'], ['top', '위쪽 가운데'], ['bottom', '아래쪽 가운데']] });
      const col = field({ label: '색상', type: 'select', value: '#C2311C', options: [['#C2311C', '빨강'], ['#555555', '회색'], ['#1E3A8A', '남색']] });
      const op = field({ label: '투명도 (%)', type: 'range', value: 25, min: 5, max: 80, step: 5 });
      const count = h('span', { class: 'pill ok' });
      /* 섬네일 위 미리보기 — 실제 결과와 비슷한 느낌만 보여준다 */
      function decorate(it) {
        let wm = it.fig.querySelector('.wm');
        if (!wm) { wm = h('div', { class: 'wm' }); it.fig.append(wm); }
        const on = !g || !g.sel.size || g.sel.has(it), mode = pos.input.value, t = txt.input.value || ' ';
        wm.hidden = !on;
        wm.style.color = col.input.value; wm.style.opacity = String(mode === 'top' || mode === 'bottom' ? Math.max(num(op) / 100, 0.6) : Math.max(num(op) / 100, 0.15));
        wm.style.alignItems = mode === 'top' ? 'start' : mode === 'bottom' ? 'end' : 'center';
        wm.replaceChildren(...(mode === 'tile' ? [0, 1, 2, 3].map(() => h('span', { style: { transform: 'rotate(-20deg)', fontSize: '10px' } }, t)) : [h('span', { style: { transform: mode === 'diag' ? 'rotate(-54deg)' : 'none', fontSize: mode === 'diag' ? '14px' : '10px' } }, t)]));
        wm.classList.toggle('tile', mode === 'tile');
      }
      const upd = () => { count.textContent = g && g.sel.size ? `${g.sel.size}쪽에만 넣기` : '모든 쪽에 넣기'; };
      [txt, pos, col, op].forEach((f) => f.input.addEventListener('input', () => g && g.refresh()));
      const b = btn('워터마크 넣어 저장', guard(st, async () => {
        const doc = await openPdf(file);
        const png = await doc.embedPng(await (await canvasBlob(textImage(txt.input.value || ' ', 120, col.input.value, 1), 'image/png')).arrayBuffer());
        const alpha = num(op) / 100, mode = pos.input.value, pages = doc.getPages();
        const targets = g.targets().map((x) => x.i);
        for (const i of targets) {
          /* 돌아간 쪽·잘린 쪽도 화면에 보이는 모습 기준으로 넣는다 (2026-09-29 검토) */
          const p = pages[i], F = await viewFrame(pj, i), W = F.W, H = F.H, put = (x, y, w, hh, deg, o) => { const [cx, cy] = F.toPdf(x, y); drawCentered(p, png, cx, cy, w, hh, deg + F.rot, o); };
          if (mode === 'diag') { const w = Math.hypot(W, H) * 0.6, hh = (w * png.height) / png.width; put(W / 2, H / 2, w, hh, (Math.atan2(H, W) * 180) / Math.PI, alpha); }
          else if (mode === 'tile') { const w = W * 0.38, hh = (w * png.height) / png.width; for (let y = 30; y < H; y += hh * 3.2) for (let x = (Math.round(y) % 2) * 40; x < W; x += w * 1.25) put(x + w / 2, H - y - hh / 2, w, hh, 20, alpha); }
          else { const w = W * 0.4, hh = (w * png.height) / png.width; put(W / 2, mode === 'top' ? 18 + hh / 2 : H - 18 - hh / 2, w, hh, 0, Math.max(alpha, 0.6)); }
        }
        save(`${baseName(file.name)}_워터마크.pdf`, await pdfBlob(doc)); st.textContent = `${targets.length}쪽에 넣었습니다`;
      }), true);
      el.append(h('div', { class: 'panel stack' }, h('div', { class: 'fields' }, txt, pos, col, op),
        dropzone({ accept: pdfOnly, multiple: false, onFiles: guard(st, async ([f]) => {
          st.textContent = '여는 중…'; if (g) g.destroy();
          file = f; pj = await openPdfjs(f); g = board({ onChange: upd, decorate }); g.add(pdfItems(pj));
          area.replaceChildren(boardBar(g, row(count, b)), st, g.el); upd();
          st.textContent = `${f.name} · ${g.count()}쪽 — 넣을 쪽만 고르거나, 그대로 두면 모든 쪽에 넣습니다`;
        }) }), area));
      return () => { if (g) g.destroy(); };
    },
  });

  /* 25. 서명 넣기 */
  add({
    id: 'pdfsign', cat: 'pdf', code: 'SIGN', name: 'PDF 서명 넣기', kw: '사인 서명 결재 날인 섬네일', lib: true,
    desc: '서명을 그리고, 섬네일에서 쪽을 고른 뒤 원하는 위치를 눌러 PDF에 넣기',
    long: '① 서명 칸에 서명을 그립니다 ② PDF를 넣고 섬네일에서 서명할 쪽을 누릅니다 ③ 크게 뜬 쪽에서 서명 위치를 누릅니다 ④ 저장합니다. 여러 쪽에 넣으려면 쪽마다 ②~③을 반복한 뒤 한 번에 저장하면 됩니다. 전자문서법상 공인 전자서명을 대신하지는 않습니다.',
    render(el) {
      const st = status();
      const pad = h('canvas', { class: 'work', width: 600, height: 220, style: { width: '100%', maxWidth: '600px', background: '#fff', cursor: 'crosshair' } });
      const px = pad.getContext('2d'); px.lineWidth = 4; px.lineCap = px.lineJoin = 'round'; px.strokeStyle = '#0b1b3a';
      let drawing = false, drawn = false;
      const pt = (e) => { const r = pad.getBoundingClientRect(); return [((e.clientX - r.left) * pad.width) / r.width, ((e.clientY - r.top) * pad.height) / r.height]; };
      pad.addEventListener('pointerdown', (e) => { drawing = true; drawn = true; pad.setPointerCapture(e.pointerId); px.beginPath(); px.moveTo(...pt(e)); });
      pad.addEventListener('pointermove', (e) => { if (drawing) { px.lineTo(...pt(e)); px.stroke(); } });
      pad.addEventListener('pointerup', () => (drawing = false));
      const penCol = field({ label: '펜 색', type: 'select', value: '#0b1b3a', options: [['#0b1b3a', '검정'], ['#1d4ed8', '파랑'], ['#b91c1c', '빨강']] });
      penCol.input.addEventListener('change', () => (px.strokeStyle = penCol.input.value));
      let file = null, pj = null, g = null, cur = null, base = null;
      const places = new Map();   /* 쪽 번호(0부터) → [x비율, y비율] */
      const sw = field({ label: '서명 너비 (쪽 너비 대비 %)', type: 'range', value: 22, min: 8, max: 50, step: 1 });
      const prev = h('canvas', { class: 'work', style: { width: '100%', maxWidth: '560px', cursor: 'copy' } });
      const prevWrap = h('div', { class: 'stack', hidden: true }, h('b', { id: 'signPageTitle' }), prev, row(btn('이 쪽 서명 지우기', () => { places.delete(cur.i); redraw(); g.refresh(); upd(); })));
      const count = h('span', { class: 'pill warn' }, '서명한 쪽 없음');
      function sigCanvas() { /* 여백을 잘라낸 서명 */
        const d = px.getImageData(0, 0, pad.width, pad.height).data; let x0 = pad.width, y0 = pad.height, x1 = 0, y1 = 0;
        for (let y = 0; y < pad.height; y++) for (let x = 0; x < pad.width; x++) if (d[(y * pad.width + x) * 4 + 3] > 10) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
        if (x1 <= x0) return null; const c = document.createElement('canvas'); c.width = x1 - x0 + 8; c.height = y1 - y0 + 8; c.getContext('2d').drawImage(pad, x0 - 4, y0 - 4, c.width, c.height, 0, 0, c.width, c.height); return c;
      }
      function redraw() {
        if (!base) return; prev.width = base.width; prev.height = base.height; const x = prev.getContext('2d'); x.drawImage(base, 0, 0);
        const s = sigCanvas(), p = places.get(cur.i); if (p && s) { const w = (prev.width * num(sw)) / 100, hh = (w * s.height) / s.width; x.drawImage(s, p[0] * prev.width - w / 2, p[1] * prev.height - hh / 2, w, hh); }
      }
      const upd = () => { count.textContent = places.size ? `서명한 쪽 ${places.size}개: ${picksText([...places.keys()].sort((a, b) => a - b))}` : '서명한 쪽 없음'; count.className = 'pill ' + (places.size ? 'ok' : 'warn'); b.disabled = !places.size; };
      async function showPage(it) {
        cur = it; base = await renderPage(pj, it.i + 1, 1.3); prevWrap.hidden = false;
        prevWrap.querySelector('#signPageTitle').textContent = `③ ${it.i + 1}쪽 — 서명할 위치를 누르세요`; redraw();
        prevWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
      prev.addEventListener('click', (e) => { if (!drawn) return toast('먼저 ① 칸에 서명을 그려 주세요'); const r = prev.getBoundingClientRect(); places.set(cur.i, [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]); redraw(); g.refresh(); upd(); });
      sw.input.addEventListener('input', redraw);
      const b = btn('서명 넣어 저장', guard(st, async () => {
        const s = sigCanvas(); if (!s || !places.size) return;
        const d2 = await openPdf(file); const png = await d2.embedPng(await (await canvasBlob(s, 'image/png')).arrayBuffer());
        for (const [i, p] of places) {
          /* 미리보기에서 누른 자리 → PDF 좌표. 돌아간 쪽·잘린 쪽도 화면에서 본 그대로 들어간다 (2026-09-29 검토) */
          const F = await viewFrame(pj, i), w = (F.W * num(sw)) / 100, hh = (w * s.height) / s.width;
          const [cx, cy] = F.toPdf(p[0] * F.W, p[1] * F.H);
          drawCentered(d2.getPage(i), png, cx, cy, w, hh, F.rot);
        }
        save(`${baseName(file.name)}_서명.pdf`, await pdfBlob(d2)); st.textContent = `${places.size}쪽에 서명을 넣었습니다`;
      }), true);
      b.disabled = true;
      const area = h('div', { class: 'stack' });
      el.append(h('div', { class: 'panel stack' }, h('b', null, '① 서명 그리기'), pad, row(penCol, btn('지우기', () => { px.clearRect(0, 0, pad.width, pad.height); drawn = false; redraw(); })), sw),
        h('div', { class: 'panel stack' }, h('b', null, '② PDF 넣고 서명할 쪽 누르기'), dropzone({ accept: pdfOnly, multiple: false, onFiles: guard(st, async ([f]) => {
          st.textContent = '여는 중…'; if (g) g.destroy(); places.clear(); prevWrap.hidden = true;
          file = f; pj = await openPdfjs(f);
          g = board({ select: 'single', onChange: () => { const it = g.picked()[0]; if (it && it !== cur) showPage(it); }, decorate: (it) => it.fig.classList.toggle('signed', places.has(it.i)) });
          g.add(pdfItems(pj));
          area.replaceChildren(boardBar(g, row(count, b), { noSelect: true }), st, g.el); upd();
          st.textContent = `${f.name} · ${pj.numPages}쪽 — 서명할 쪽을 누르세요 (✎ 표시는 서명한 쪽)`;
        }) }), area, prevWrap));
      return () => { if (g) g.destroy(); };
    },
  });

  /* 26. PDF → 이미지 */
  add({
    id: 'pdf2img', cat: 'pdf', code: 'PDF→IMG', name: 'PDF를 사진으로', kw: '이미지 변환 JPG PNG 캡처 섬네일', lib: true,
    desc: '섬네일로 고른 쪽을 JPG·PNG 이미지로 저장 (여러 장은 ZIP)',
    long: '바꿀 쪽을 눌러 고르세요. 고르지 않으면 모든 쪽을 바꿉니다.',
    render(el) {
      const st = status(); let pj = null, file = null, g = null;
      const area = h('div', { class: 'stack' });
      const fmtF = field({ label: '형식', type: 'select', value: 'jpg', options: [['jpg', 'JPG'], ['png', 'PNG']] });
      const sc = field({ label: '해상도', type: 'select', value: 2, options: [[1, '보통 (72dpi)'], [2, '선명 (144dpi)'], [3, '인쇄용 (216dpi)']] });
      const count = h('span', { class: 'pill ok' });
      const upd = () => { count.textContent = g.sel.size ? `${g.sel.size}쪽 바꾸기 · ${picksText(g.picked().map((x) => x.i))}` : `모든 쪽 (${g.count()}쪽) 바꾸기`; };
      const b = btn('변환해서 저장', guard(st, async () => {
        const idx = g.targets().map((x) => x.i);
        const type = fmtF.input.value === 'png' ? 'image/png' : 'image/jpeg', ext = fmtF.input.value; const outs = [];
        for (const [k, i] of idx.entries()) { st.textContent = `변환 중 ${k + 1}/${idx.length}`; const c = await renderPage(pj, i + 1, +sc.input.value); outs.push([`${baseName(file.name)}_${String(i + 1).padStart(3, '0')}.${ext}`, await canvasBlob(c, type, 0.9)]); }
        if (outs.length === 1) save(outs[0][0], outs[0][1]);
        else { await lib('jszip'); const z = new JSZip(); outs.forEach(([n, bl]) => z.file(n, bl)); save(`${baseName(file.name)}_이미지.zip`, await z.generateAsync({ type: 'blob' })); }
        st.textContent = `${outs.length}장 변환`;
      }), true);
      el.append(h('div', { class: 'panel stack' }, h('div', { class: 'fields' }, fmtF, sc), dropzone({ accept: pdfOnly, multiple: false, onFiles: guard(st, async ([f]) => {
        st.textContent = '여는 중…'; if (g) g.destroy();
        file = f; pj = await openPdfjs(f); g = board({ onChange: upd }); g.add(pdfItems(pj));
        area.replaceChildren(boardBar(g, row(count, b)), st, g.el); upd();
        st.textContent = `${f.name} · ${pj.numPages}쪽 — 바꿀 쪽을 고르거나, 그대로 두면 모든 쪽을 바꿉니다`;
      }) }), area));
      return () => { if (g) g.destroy(); };
    },
  });

  /* 27. 용량 줄이기 */
  add({
    id: 'pdfshrink', cat: 'pdf', code: 'SHRINK', name: 'PDF 용량 줄이기', kw: '압축 메일 첨부 용량 섬네일', lib: true,
    desc: '스캔 PDF를 다시 그려 메일 첨부가 가능한 크기로 줄이기 (섬네일로 미리 확인)',
    long: '각 쪽을 이미지로 다시 그려 저장하는 방식입니다. 스캔본·사진이 많은 PDF에 효과가 큽니다. 결과 PDF에서는 글자 선택·검색이 되지 않습니다. 섬네일을 누르면 크게 볼 수 있습니다.',
    render(el) {
      const st = status(); let pj = null, file = null, g = null, run = 0;
      const area = h('div', { class: 'stack' });
      const LV = { l: [1.6, 0.8], m: [1.25, 0.65], h: [1, 0.5] };
      const NAME = { l: '약하게', m: '보통', h: '강하게' };
      const lv = field({ label: '압축 수준', type: 'select', value: 'm', options: [['l', '약하게 (선명)'], ['m', '보통'], ['h', '강하게 (용량 최소)']] });
      /* 예상 용량 (2026-10-07 직원 요청): 앞·가운데·끝 쪽을 저장할 때와 똑같이(수준별 크기로 그려 JPG로) 줄여 보고,
         그 평균에 전체 쪽 수를 곱해 미리 보여준다. 쪽마다 내용이 다르면 실제 결과와 차이가 날 수 있다 */
      const est = h('div', { class: 'est', style: { display: 'grid', gap: '6px' } });
      async function estimate() {
        const my = ++run, n = pj.numPages, picks = [...new Set([0, Math.floor((n - 1) / 2), n - 1])];
        const sum = { l: 0, m: 0, h: 0 };
        est.replaceChildren(h('span', { class: 'note' }, '예상 용량 계산 중…'));
        for (const k of picks) {
          for (const key of Object.keys(LV)) {
            const [scale, q] = LV[key];
            const c = await renderPage(pj, k + 1, scale); if (my !== run) return;
            sum[key] += (await canvasBlob(c, 'image/jpeg', q)).size; if (my !== run) return;
          }
        }
        const rows = Object.keys(LV).map((key) => {
          const size = Math.round(sum[key] / picks.length * n + n * 400 + 2000), pct = Math.round((1 - size / file.size) * 100);
          const on = lv.input.value === key;
          return h('button', { type: 'button', class: 'btn' + (on ? ' primary' : ''), style: { justifyContent: 'space-between', width: '100%' }, onclick: () => { lv.input.value = key; lv.input.dispatchEvent(new Event('change')); } },
            h('span', null, NAME[key]), h('span', { class: 'mono' }, `약 ${fmtSize(size)} · ` + (pct > 0 ? `${pct}% 감소` : '줄지 않음')));
        });
        est.replaceChildren(h('b', null, `예상 결과 (지금 ${fmtSize(file.size)}, ${picks.length}쪽을 시험해 본 값)`), ...rows,
          h('span', { class: 'note' }, '누르면 그 수준으로 바뀝니다. 쪽마다 내용이 다르면 실제 결과와 차이가 날 수 있습니다.'));
      }
      lv.input.addEventListener('change', () => { if (pj && est.querySelector('button')) est.querySelectorAll('button').forEach((x, k) => x.classList.toggle('primary', Object.keys(LV)[k] === lv.input.value)); });
      const b = btn('줄여서 저장', guard(st, async () => {
        const [scale, q] = LV[lv.input.value];
        await lib('pdflib'); const out = await PDFLib.PDFDocument.create();
        for (let i = 1; i <= pj.numPages; i++) {
          st.textContent = `처리 중 ${i}/${pj.numPages}`;
          const page = await pj.getPage(i), vp1 = page.getViewport({ scale: 1 });
          const c = await renderPage(pj, i, scale); const jpg = await out.embedJpg(await (await canvasBlob(c, 'image/jpeg', q)).arrayBuffer());
          out.addPage([vp1.width, vp1.height]).drawImage(jpg, { x: 0, y: 0, width: vp1.width, height: vp1.height });
        }
        const blob = await pdfBlob(out); const pct = Math.round((1 - blob.size / file.size) * 100);
        st.textContent = `${fmtSize(file.size)} → ${fmtSize(blob.size)} (${pct > 0 ? pct + '% 감소' : '줄어들지 않음. 원본을 쓰세요'})`;
        if (pct > 0) save(`${baseName(file.name)}_압축.pdf`, blob);
      }), true);
      el.append(h('div', { class: 'panel stack' }, lv, dropzone({ accept: pdfOnly, multiple: false, onFiles: guard(st, async ([f]) => {
        st.textContent = '여는 중…'; if (g) g.destroy();
        file = f; pj = await openPdfjs(f); g = board({ select: 'none' }); g.add(pdfItems(pj));
        area.replaceChildren(est, boardBar(g, row(h('span', { class: 'pill ok' }, `${pj.numPages}쪽 · ${fmtSize(f.size)}`), b), { noSelect: true }), st, g.el);
        st.textContent = '섬네일을 누르면 크게 볼 수 있습니다';
        estimate().catch((e) => est.replaceChildren(h('span', { class: 'note' }, '예상 용량을 계산하지 못했습니다: ' + e.message)));
      }) }), area), h('p', { class: 'note warn' }, '글자로 된 문서(한글·워드에서 만든 PDF)는 오히려 커질 수 있습니다. 그런 경우 저장하지 않고 알려드립니다.'));
      return () => { run++; if (g) g.destroy(); };
    },
  });
  /* 28. 텍스트 복사 방지 (2026-09-29 직원 요청) — 각 쪽을 그림으로 다시 만들어 글자 층을 없앤다 */
  add({
    id: 'pdfnocopy', cat: 'pdf', code: 'NOCOPY', name: 'PDF 텍스트 복사 방지', kw: '글자 복사 막기 OCR 제거 이미지화 보안 배포', lib: true,
    desc: '각 쪽을 그림으로 바꿔 글자 선택·복사·검색이 안 되는 PDF로 저장',
    long: 'PDF의 글자 층(검색·복사가 되는 부분, OCR 결과 포함)을 없애고 쪽마다 그림으로 다시 만듭니다. 화면과 인쇄 모양은 그대로입니다. 쪽을 고르면 그 쪽만, 고르지 않으면 모든 쪽을 그림으로 바꿉니다(고르지 않은 쪽은 원래대로 둡니다).',
    render(el) {
      const st = status(); let pj = null, file = null, g = null;
      const area = h('div', { class: 'stack' });
      const dpi = field({ label: '화질', type: 'select', value: 200, options: [[150, '보통 (150dpi · 용량 작음)'], [200, '선명 (200dpi · 권장)'], [300, '인쇄용 (300dpi · 용량 큼)']] });
      const q = field({ label: '그림 압축', type: 'select', value: 0.85, options: [[0.92, '높은 화질'], [0.85, '보통'], [0.7, '용량 우선']] });
      const count = h('span', { class: 'pill ok' });
      const upd = () => { count.textContent = g.sel.size ? `${g.sel.size}쪽만 그림으로 (${picksText(g.picked().map((x) => x.i))})` : `모든 쪽 (${g.count()}쪽) 그림으로`; };
      const b = btn('복사 방지 PDF로 저장', guard(st, async () => {
        await lib('pdflib');
        const src = await openPdf(file);   /* 편집 잠금 PDF면 여기서 멈추고 안내한다 */
        const pick = new Set(g.targets().map((x) => x.i)), out = await PDFLib.PDFDocument.create(), scale = +dpi.input.value / 72;
        for (let i = 0; i < pj.numPages; i++) {
          st.textContent = `처리 중 ${i + 1}/${pj.numPages}`;
          if (!pick.has(i)) { const [p] = await out.copyPages(src, [i]); out.addPage(p); continue; }
          const page = await pj.getPage(i + 1), vp1 = page.getViewport({ scale: 1 });   /* 회전·잘림이 반영된 보이는 모습 그대로 */
          const c = await renderPage(pj, i + 1, scale);
          const jpg = await out.embedJpg(await (await canvasBlob(c, 'image/jpeg', +q.input.value)).arrayBuffer());
          out.addPage([vp1.width, vp1.height]).drawImage(jpg, { x: 0, y: 0, width: vp1.width, height: vp1.height });
          c.width = c.height = 0;
        }
        const blob = await pdfBlob(out);
        st.textContent = `완료 · ${pick.size}쪽을 그림으로 바꿈 · ${fmtSize(file.size)} → ${fmtSize(blob.size)}`;
        save(`${baseName(file.name)}_복사방지.pdf`, blob);
      }), true);
      el.append(h('div', { class: 'panel stack' }, h('div', { class: 'fields' }, dpi, q), dropzone({ accept: pdfOnly, multiple: false, onFiles: guard(st, async ([f]) => {
        st.textContent = '여는 중…'; if (g) g.destroy();
        file = f; pj = await openPdfjs(f); g = board({ onChange: upd }); g.add(pdfItems(pj));
        area.replaceChildren(boardBar(g, row(count, b)), st, g.el); upd();
        st.textContent = `${f.name} · ${pj.numPages}쪽 · ${fmtSize(f.size)}`;
      }) }), area),
        h('p', { class: 'note warn' }, '글자 복사·검색·붙여넣기를 막는 용도입니다. 화면을 캡처하거나 사진을 찍어 글자를 다시 읽는 것(OCR)까지 막지는 못합니다. 결과 파일은 원본보다 커질 수 있습니다.'));
      return () => { if (g) g.destroy(); };
    },
  });

  /* PDF 한 쪽의 글자를 줄 단위로 꺼낸다 — 위에서 아래, 왼쪽에서 오른쪽 순서.
     같은 높이(글자 크기의 절반 이내)는 한 줄로, 줄 사이가 크게 벌어지면 빈 줄을 넣어 문단을 나눈다. */
  async function pageLines(pj, n) {
    const page = await pj.getPage(n), tc = await page.getTextContent(), vp = page.getViewport({ scale: 1 });
    const items = tc.items.filter((it) => it.str && it.str.trim()).map((it) => {
      const [a, b, c, d, e, f] = pdfjsLib.Util.transform(vp.transform, it.transform);
      const hgt = Math.hypot(c, d) || Math.hypot(a, b) || 10;
      return { x: e, y: f, h: hgt, w: it.width * (vp.scale || 1), s: it.str };
    }).sort((p, q) => p.y - q.y || p.x - q.x);
    const lines = [];
    for (const it of items) {
      const L = lines[lines.length - 1];
      if (L && Math.abs(L.y - it.y) < Math.max(L.h, it.h) * 0.5) { L.parts.push(it); L.h = Math.max(L.h, it.h); }
      else lines.push({ y: it.y, h: it.h, parts: [it] });
    }
    const out = []; let prev = null;
    for (const L of lines) {
      L.parts.sort((p, q) => p.x - q.x);
      let s = '', end = null;
      for (const p of L.parts) {
        if (end !== null && p.x - end > p.h * 0.25 && !/\s$/.test(s) && !/^\s/.test(p.s)) s += ' ';
        s += p.s; end = p.x + p.w;
      }
      if (prev && L.y - prev.y > Math.max(prev.h, L.h) * 1.9) out.push('');   /* 문단 사이 */
      out.push(s.replace(/\s+$/, '')); prev = L;
    }
    return out;
  }
  /* 한 문단 안에서 줄바꿈만 된 줄들을 이어 붙인다 (빈 줄·글머리표·번호로 시작하는 줄은 새 문단) */
  function joinParagraphs(lines) {
    /* 짧은 줄은 문단의 끝이거나 제목으로 본다 — 보통 줄 길이의 60%보다 짧으면 다음 줄을 붙이지 않는다 */
    const lens = lines.map((l) => l.trim().length).filter((n) => n > 0).sort((a, b) => a - b);
    const typical = lens.length ? lens[Math.floor(lens.length * 0.7)] : 0;
    const bullet = /^([□■○●◎◆◇▶▷※\-·•*]|\d+[.)]|[가-하][.)]|[①-⑳]|제\s*\d+\s*[조항장절])/;
    const out = []; let lastLen = 0;
    for (const l of lines) {
      const t = l.trim(), last = out.length ? out[out.length - 1] : null;
      if (!t) { if (last !== '') out.push(''); lastLen = 0; continue; }
      const canJoin = last && last !== '' && !bullet.test(t) && !/[.!?。:：]$/.test(last) && lastLen >= typical * 0.6;
      if (canJoin) out[out.length - 1] = last + (/[가-힣a-zA-Z0-9,]$/.test(last) ? ' ' : '') + t;
      else out.push(t);
      lastLen = t.length;
    }
    while (out.length && out[out.length - 1] === '') out.pop();
    return out;
  }


  /* 29. 텍스트 추출 → 한글(HWPX)·ODT·TXT (2026-09-29 직원 요청) */
  add({
    id: 'pdf2doc', cat: 'pdf', code: 'PDF→HWPX', name: 'PDF 글자 추출 → 한글·ODT', kw: '텍스트 추출 한글 hwpx odt txt 변환 문서 편집 복사', lib: true,
    desc: 'PDF의 글자를 꺼내 한글(HWPX)·ODT·TXT 문서로 저장. 저장 전에 고칠 수 있음',
    long: 'PDF 안에 들어 있는 글자를 쪽 순서대로 꺼냅니다. 꺼낸 글은 아래 칸에서 바로 고칠 수 있고, 한글(HWPX)·ODT·TXT로 저장합니다. 표·그림·글꼴 모양은 옮겨지지 않고 글자만 옮겨집니다. 스캔본(사진으로 된 PDF) 쪽은 글자 인식(OCR)으로 읽습니다.',
    render(el) {
      const st = status(); let pj = null, file = null, g = null;
      const area = h('div', { class: 'stack' });
      const fmtF = field({ label: '저장 형식', type: 'select', value: 'hwpx', options: [['hwpx', '한글 문서 (.hwpx)'], ['odt', 'ODT (.odt · 한글·오픈오피스·워드)'], ['txt', '메모장 (.txt)']] });
      const mode = field({ label: '줄 정리', type: 'select', value: 'join', options: [['join', '문단으로 이어 붙이기 (권장)'], ['keep', 'PDF 줄바꿈 그대로']] });
      const pb = h('label', { style: { display: 'flex', gap: '6px', alignItems: 'center', fontSize: '14px' } }, h('input', { type: 'checkbox', id: 'p2dPB', checked: true }), 'PDF 쪽마다 새 쪽에서 시작');
      const ocrOpt = h('label', { style: { display: 'flex', gap: '6px', alignItems: 'center', fontSize: '14px' } }, h('input', { type: 'checkbox', id: 'p2dOCR', checked: true }), '글자가 없는 쪽(스캔본)은 글자 인식(OCR)으로 읽기 · 처음 한 번 인식 데이터를 받습니다');
      const ta = field({ label: '꺼낸 글 (저장 전에 고칠 수 있습니다 · 쪽 구분은 ─── N쪽 ─── 줄)', type: 'textarea', rows: 14 });
      ta.input.style.fontFamily = 'var(--sans)'; ta.input.style.minHeight = '260px';
      const count = h('span', { class: 'pill ok' });
      const warn = h('p', { class: 'note warn', hidden: true });
      const upd = () => { count.textContent = g.sel.size ? `${g.sel.size}쪽에서 꺼내기 · ${picksText(g.picked().map((x) => x.i))}` : `모든 쪽 (${g.count()}쪽)에서 꺼내기`; };
      const MARK = (n) => `─── ${n}쪽 ───`;
      const extract = btn('글자 꺼내기', guard(st, async () => {
        const idx = g.targets().map((x) => x.i), parts = [], empty = [], ocred = [];
        for (const [k, i] of idx.entries()) {
          st.textContent = `꺼내는 중 ${k + 1}/${idx.length}`;
          let lines = await pageLines(pj, i + 1);
          const blank = (ls) => ls.join('').replace(/\s/g, '').length < 5;
          /* 글자가 없는 쪽(스캔본)은 그림으로 그려 글자 인식(OCR) — 이 PC 안에서만 */
          if (blank(lines) && el.querySelector('#p2dOCR').checked) {
            const c = await renderPage(pj, i + 1, 2.5);
            lines = await App.docgen.ocr(c, 'kor+eng', (m) => {
              if (m.status === 'recognizing text') st.textContent = `글자 인식 중 (${k + 1}/${idx.length}) · ${i + 1}쪽 ${Math.round(m.progress * 100)}%`;
              else if (/load|initializ/.test(m.status)) st.textContent = '글자 인식 준비 중… 처음 한 번 인식 모델(약 28MB)을 받습니다' + (m.status === 'loading model' ? ` ${Math.round(m.progress * 100)}%` : '');
            });
            c.width = c.height = 0; ocred.push(i + 1);
          }
          if (blank(lines)) empty.push(i + 1);
          if (mode.input.value === 'join') lines = joinParagraphs(lines);
          parts.push(MARK(i + 1) + '\n' + lines.join('\n'));
        }
        ta.input.value = parts.join('\n\n');
        const msgs = [];
        if (ocred.length) msgs.push(`${picksText(ocred.map((n) => n - 1))}쪽은 스캔본이라 글자 인식(OCR)으로 읽었습니다. 틀린 글자가 있을 수 있으니 꼭 확인하세요.`);
        if (empty.length) msgs.push(`${picksText(empty.map((n) => n - 1))}쪽은 글자를 찾지 못했습니다.`);
        warn.hidden = !msgs.length;
        warn.textContent = msgs.join(' ');
        const chars = ta.input.value.replace(/─── \d+쪽 ───/g, '').replace(/\s/g, '').length;
        st.textContent = `${idx.length}쪽에서 ${chars.toLocaleString('ko-KR')}자를 꺼냈습니다. 확인·수정한 뒤 저장하세요.`;
        saveBtn.disabled = !chars;
      }), true);
      /* 칸의 글 → 쪽별 문단 목록 */
      const toPages = () => {
        const pages = []; let cur = null;
        for (const line of ta.input.value.split(/\r?\n/)) {
          if (/^─── \d+쪽 ───$/.test(line.trim())) { cur = []; pages.push(cur); continue; }
          if (!cur) { cur = []; pages.push(cur); }
          cur.push(line);
        }
        return pages.map((p) => { while (p.length && !p[p.length - 1].trim()) p.pop(); while (p.length && !p[0].trim()) p.shift(); return p; });
      };
      const saveBtn = btn('저장', guard(st, async () => {
        const pages = toPages(), f = fmtF.input.value, opt = { pageBreak: el.querySelector('#p2dPB').checked, title: baseName(file.name) };
        const blob = f === 'hwpx' ? await App.docgen.hwpx(pages, opt) : f === 'odt' ? await App.docgen.odt(pages, opt) : App.docgen.txt(pages);
        save(`${baseName(file.name)}.${f}`, blob); st.textContent = `${f.toUpperCase()}로 저장 · ${fmtSize(blob.size)}`;
      }), true);
      saveBtn.disabled = true;
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: pdfOnly, multiple: false, onFiles: guard(st, async ([f]) => {
        st.textContent = '여는 중…'; if (g) g.destroy();
        file = f; pj = await openPdfjs(f); g = board({ onChange: upd }); g.add(pdfItems(pj));
        ta.input.value = ''; saveBtn.disabled = true; warn.hidden = true;
        area.replaceChildren(boardBar(g, row(count, extract)), g.el, h('div', { class: 'fields' }, mode, fmtF), pb, ocrOpt, st, warn, ta, row(saveBtn));
        upd(); st.textContent = `${f.name} · ${pj.numPages}쪽 — 꺼낼 쪽을 고르거나 그대로 [글자 꺼내기]를 누르세요`;
      }) }), area),
        h('p', { class: 'note' }, '한글(HWPX)은 한컴오피스 2014 이후 버전에서 열립니다. 글자만 옮겨지므로 표·도형·글꼴 모양은 한글에서 다시 정리해야 합니다. 스캔본 쪽의 글자 인식(OCR)은 이 PC 안에서만 이뤄지며, 글꼴·해상도에 따라 틀린 글자가 나올 수 있어 확인이 필요합니다.'));
      return () => { if (g) g.destroy(); App.docgen.ocrEnd(); };
    },
  });
  /* 30. 사진·스캔본 글자 인식 (2026-09-29 직원 요청) — 문서를 찍은 사진·스캔 PDF에서 글자를 읽어 한글·ODT·TXT로 */
  add({
    id: 'ocr', cat: 'pdf', code: 'OCR', name: '사진·스캔본 글자 인식 (OCR)', kw: 'ocr 글자 인식 스캔 사진 문서 텍스트 추출 한글 hwpx 이미지', lib: true,
    desc: '문서를 찍은 사진이나 스캔 PDF에서 글자를 읽어 한글(HWPX)·ODT·TXT로 저장',
    long: '사진(JPG·PNG)이나 스캔 PDF를 넣으면 섬네일로 펼쳐집니다. 읽을 장을 고르고(안 고르면 전부) [글자 인식]을 누르세요. 인식은 이 PC 안에서만 이뤄지고, 처음 한 번 인식 데이터(약 5MB)를 우리 사이트에서 받습니다. 결과는 칸에서 고친 뒤 저장합니다.',
    render(el) {
      const st = status(); const g = board({ onChange: () => upd() });
      const area = h('div', { class: 'stack' }); const count = h('span', { class: 'pill ok' });
      const lang = field({ label: '인식 엔진', type: 'select', value: 'pp', options: [['pp', '정밀 (권장 · 처음 약 28MB 받음)'], ['kor+eng', '가벼운 엔진 (예전 방식 · 약 5MB)']] });
      const mode = field({ label: '줄 정리', type: 'select', value: 'join', options: [['join', '문단으로 이어 붙이기 (권장)'], ['keep', '인식한 줄 그대로']] });
      const fmtF = field({ label: '저장 형식', type: 'select', value: 'hwpx', options: [['hwpx', '한글 문서 (.hwpx)'], ['odt', 'ODT (.odt)'], ['txt', '메모장 (.txt)']] });
      const ta = field({ label: '인식한 글 (틀린 글자를 고친 뒤 저장하세요 · 장 구분은 ─── N번째 ─── 줄)', type: 'textarea', rows: 14 });
      ta.input.style.minHeight = '260px';
      let title = '글자인식';
      function upd() { count.textContent = g.sel.size ? `${g.sel.size}장 읽기` : `전체 ${g.count()}장 읽기`; area.hidden = !g.count(); }
      /* 인식하기 좋은 크기로 그리기: 긴 변 2,000~3,000px 정도 */
      async function toCanvasFor(it) {
        if (it.pj) return renderPage(it.pj, it.i + 1, 2.5);
        const img = it.img, W = img.naturalWidth, H = img.naturalHeight, long = Math.max(W, H);
        const s = long < 1500 ? 2 : long > 3500 ? 3000 / long : 1;
        const c = document.createElement('canvas'); c.width = Math.round(W * s); c.height = Math.round(H * s);
        const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.drawImage(img, 0, 0, c.width, c.height); return c;
      }
      const MARK = (n) => `─── ${n}번째 ───`;
      const run = btn('글자 인식', guard(st, async () => {
        const list = g.targets(), parts = [];
        let direct = 0;
        for (const [k, it] of list.entries()) {
          /* 글자가 이미 들어 있는 PDF 쪽은 인식하지 않고 그대로 꺼낸다 (100% 정확) */
          if (it.pj) {
            const tl = await pageLines(it.pj, it.i + 1);
            if (tl.join('').replace(/\s/g, '').length >= 20) {
              const lines = mode.input.value === 'join' ? joinParagraphs(tl) : tl;
              parts.push(MARK(g.order.indexOf(it) + 1) + '\n' + lines.join('\n')); ta.input.value = parts.join('\n\n'); direct++; continue;
            }
          }
          const c = await toCanvasFor(it);
          let lines = await App.docgen.ocr(c, lang.input.value === 'pp' ? 'kor+eng' : lang.input.value, (m) => {
            if (m.status === 'recognizing text') st.textContent = `글자 인식 중 ${k + 1}/${list.length} · ${Math.round(m.progress * 100)}%`;
            else if (/load|initializ/.test(m.status)) st.textContent = '글자 인식 준비 중… 처음 한 번 인식 모델(약 28MB)을 받습니다' + (m.status === 'loading model' ? ` ${Math.round(m.progress * 100)}%` : '');
          }, { engine: lang.input.value === 'pp' ? 'pp' : 'tesseract' });
          c.width = c.height = 0;
          if (mode.input.value === 'join') lines = joinParagraphs(lines); else lines = lines.map((l) => l.trimEnd());
          parts.push(MARK(g.order.indexOf(it) + 1) + '\n' + lines.join('\n'));
          ta.input.value = parts.join('\n\n');   /* 한 장씩 끝날 때마다 보여준다 */
        }
        const chars = ta.input.value.replace(/─── \d+번째 ───/g, '').replace(/\s/g, '').length;
        st.textContent = `${list.length}장에서 ${chars.toLocaleString('ko-KR')}자를 읽었습니다.` + (direct ? ` (${direct}장은 PDF에 들어 있던 글자를 그대로 꺼냄)` : '') + ' 틀린 글자가 있을 수 있으니 확인·수정한 뒤 저장하세요.';
        sv.disabled = !chars;
      }), true);
      const toPages = () => {
        const pages = []; let cur = null;
        for (const line of ta.input.value.split(/\r?\n/)) {
          if (/^─── \d+번째 ───$/.test(line.trim())) { cur = []; pages.push(cur); continue; }
          if (!cur) { cur = []; pages.push(cur); }
          cur.push(line);
        }
        return pages.map((p) => { while (p.length && !p[p.length - 1].trim()) p.pop(); while (p.length && !p[0].trim()) p.shift(); return p; });
      };
      const sv = btn('저장', guard(st, async () => {
        const pages = toPages(), f = fmtF.input.value, opt = { pageBreak: true, title };
        const blob = f === 'hwpx' ? await App.docgen.hwpx(pages, opt) : f === 'odt' ? await App.docgen.odt(pages, opt) : App.docgen.txt(pages);
        save(`${title}.${f}`, blob); st.textContent = `${f.toUpperCase()}로 저장 · ${fmtSize(blob.size)}`;
      }), true);
      sv.disabled = true;
      area.append(boardBar(g, row(count, run, btn('모두 비우기', () => { g.clear(); ta.input.value = ''; sv.disabled = true; }))), g.el,
        h('div', { class: 'fields' }, lang, mode, fmtF), st, ta, row(sv, btn('복사', () => App.copy(ta.input.value))));
      area.hidden = true;
      el.append(h('div', { class: 'panel stack' }, dropzone({ accept: 'image/jpeg,image/png,image/webp,.pdf,application/pdf', sub: '문서 사진(JPG·PNG)·스캔 PDF · 여러 개 가능 · 더 넣으면 뒤에 이어 붙습니다', onFiles: guard(st, async (fs) => {
        const items = [];
        for (const f of fs) {
          st.textContent = `${f.name} 여는 중…`;
          if (/pdf$/i.test(f.type) || /\.pdf$/i.test(f.name)) { const pj = await openPdfjs(f); items.push(...pdfItems(pj, { label: f.name })); }
          else items.push(Object.assign(imageItem(f, await loadImage(f)), { label: f.name }));
        }
        if (!g.count() && fs[0]) title = `${baseName(fs[0].name)}_글자인식`;
        g.add(items); st.textContent = '읽을 장을 고르거나 그대로 [글자 인식]을 누르세요';
      }) }), area),
        h('p', { class: 'note' }, '반듯하게 찍은 밝은 사진일수록 잘 읽힙니다. 손글씨·도장·표 안의 작은 글씨는 잘 읽히지 않을 수 있습니다. 한 장에 수 초~수십 초 걸립니다.'));
      upd();
      return () => { g.destroy(); App.docgen.ocrEnd(); };
    },
  });
})();
