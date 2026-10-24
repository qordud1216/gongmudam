/* 섬네일 판 — 여러 도구가 함께 쓰는 공용 부품 (2026-09-29, PDF 도구에서 옮겨 옴)
   PDF 쪽이나 사진을 작은 그림으로 펼쳐 놓고 고르고, 끌어서 순서를 바꾸고, 돌린다.
   항목(item)은 { paint(px) → canvas, tag?, color?, label? } 모양이면 무엇이든 올릴 수 있다. */
(function () {
  'use strict';
  const { h, toast } = App;

  /* "1-3, 5, 8-" 형식 → 0부터 시작하는 번호 배열 */
  function parseRange(s, total) {
    const out = [];
    for (const part of String(s).split(',').map((x) => x.trim()).filter(Boolean)) {
      const m = part.match(/^(\d*)\s*-\s*(\d*)$/);
      if (m) { const a = m[1] ? +m[1] : 1, b = m[2] ? +m[2] : total; for (let i = Math.max(1, a); i <= Math.min(total, b); i++) out.push(i - 1); }
      else if (/^\d+$/.test(part) && +part >= 1 && +part <= total) out.push(+part - 1);
    }
    return out;
  }
  /* [0,1,2,4] → "1-3, 5" */
  function picksText(list) {
    const out = [];
    for (let i = 0; i < list.length; i++) { let j = i; while (j + 1 < list.length && list[j + 1] === list[j] + 1) j++; out.push(j > i ? `${list[i] + 1}-${list[j] + 1}` : `${list[i] + 1}`); i = j; }
    return out.join(', ');
  }
  function imageItem(file, img) {
    return {
      file, img,
      async paint(px) {
        const img = this.work || this.img;
        const s = Math.min(1, px / Math.max((img.naturalWidth || img.width), (img.naturalHeight || img.height)));
        const c = document.createElement('canvas'); c.width = Math.max(1, Math.round((img.naturalWidth || img.width) * s)); c.height = Math.max(1, Math.round((img.naturalHeight || img.height) * s));
        const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height); x.drawImage(img, 0, 0, c.width, c.height); return c;
      },
    };
  }

  /* ---------- 섬네일 판 ----------
     select: 'multi'(여러 장 고르기) | 'single'(한 장만) | 'none'(보기만)
     reorder: true 면 끌어다 놓아 순서를 바꾼다 (휴대폰은 ← → 단추).
     누르면 선택, Shift+누르면 사이를 한꺼번에, 두 번 누르면 크게 보기.
     앞 24장은 바로 그리고, 나머지는 스크롤해서 보일 때 그린다. */
  function board(opt = {}) {
    const mode = opt.select || 'multi', reorder = !!opt.reorder;
    const sel = new Set(); let order = [], last = null, alive = true, dragging = null;
    const grid = h('div', { class: 'pgrid' });
    const dpr = window.devicePixelRatio || 1;
    const io = 'IntersectionObserver' in window ? new IntersectionObserver((ents) => {
      ents.forEach((e) => { if (e.isIntersecting) { io.unobserve(e.target); paint(e.target._it); } });
    }, { rootMargin: '600px' }) : null;

    async function paint(it) {
      if (!alive || it.done) return; it.done = true;
      try { const c = await it.paint(170 * dpr); if (!alive) return; it.box.replaceChildren(c); draw(it); }
      catch (_) { it.box.textContent = '미리보기 실패'; }
    }
    function draw(it) {
      const k = order.indexOf(it), on = sel.has(it);
      it.fig.classList.toggle('sel', on);
      if (mode !== 'none') it.fig.setAttribute('aria-checked', String(on));
      it.no.textContent = `${k + 1}`;
      it.rotEl.textContent = it.rot ? `${it.rot}°` : '';
      const c = it.box.querySelector('canvas'); if (c) c.style.transform = it.rot ? `rotate(${it.rot}deg)` : '';
      if (opt.decorate) opt.decorate(it);
    }
    const changed = () => { order.forEach(draw); if (opt.onChange) opt.onChange(); };
    const relayout = () => grid.replaceChildren(...order.map((it) => it.fig));
    function move(items, target, after) {
      const moving = order.filter((x) => items.includes(x));
      if (!moving.length || moving.includes(target)) return;
      order = order.filter((x) => !moving.includes(x));
      let at = target ? order.indexOf(target) + (after ? 1 : 0) : order.length;
      order.splice(at, 0, ...moving); relayout(); changed();
    }
    async function zoom(it) {
      const c = await it.paint(Math.min(1800, (Math.min(960, window.innerWidth) - 60) * dpr));
      c.style.cssText = `width:100%;height:auto;background:#fff;transform:${it.rot ? `rotate(${it.rot}deg)` : 'none'}`;
      const k = order.indexOf(it);
      const bg = h('div', { class: 'modal-bg', onclick: () => bg.remove() }, h('div', { class: 'modal', style: { maxWidth: '960px' } },
        h('h3', null, `${k + 1}번째 / 전체 ${order.length}` + (it.label ? ` · ${it.label}` : '')), c, h('p', { class: 'note', style: { marginTop: '10px' } }, '아무 곳이나 누르면 닫힙니다.')));
      document.querySelector('.toolbox-surface').append(bg);
    }
    function make(it) {
      it.rot = it.rot || 0;
      it.box = h('div', { class: 'box' }, h('span', { class: 'ld' }, '…'));
      it.no = h('figcaption', { class: 'no' });
      it.rotEl = h('span', { class: 'rot' });
      const f = it.fig = h('figure', { class: 'pg' + (mode === 'none' ? ' view' : ''), tabindex: 0, role: mode === 'none' ? 'img' : 'checkbox' },
        mode === 'none' ? null : h('span', { class: 'chk', 'aria-hidden': 'true' }), it.rotEl, it.box, it.no,
        it.tag ? h('span', { class: 'tag', style: { background: it.color || 'var(--ink-3)' } }, it.tag) : null);
      f._it = it;
      f.addEventListener('click', (e) => {
        if (mode === 'none') return zoom(it);
        if (mode === 'single') { sel.clear(); sel.add(it); }
        else if (e.shiftKey && last && order.includes(last)) {
          const a = Math.min(order.indexOf(last), order.indexOf(it)), b = Math.max(order.indexOf(last), order.indexOf(it)), on = !sel.has(it);
          for (let k = a; k <= b; k++) { if (on) sel.add(order[k]); else sel.delete(order[k]); }
        } else if (sel.has(it)) sel.delete(it); else sel.add(it);
        last = it; changed();
        if (opt.onClick) opt.onClick(it);   /* 사진 편집 도구가 '지금 누른 사진'을 편집창에 띄울 때 쓴다 */
      });
      f.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); f.click(); } });
      if (mode !== 'none') f.addEventListener('dblclick', () => zoom(it));
      if (reorder) {
        f.draggable = true;
        f.addEventListener('dragstart', (e) => { dragging = it; e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', ''); } catch (_) {} f.classList.add('dragging'); });
        f.addEventListener('dragend', () => { dragging = null; f.classList.remove('dragging'); grid.querySelectorAll('.over-l,.over-r').forEach((x) => x.classList.remove('over-l', 'over-r')); });
        f.addEventListener('dragover', (e) => { if (!dragging) return; e.preventDefault(); const r = f.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2; f.classList.toggle('over-r', after); f.classList.toggle('over-l', !after); });
        f.addEventListener('dragleave', () => f.classList.remove('over-l', 'over-r'));
        f.addEventListener('drop', (e) => {
          e.preventDefault(); f.classList.remove('over-l', 'over-r'); if (!dragging || dragging === it) return;
          const r = f.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
          move(sel.has(dragging) ? order.filter((x) => sel.has(x)) : [dragging], it, after);
        });
      }
      return it;
    }
    /* 다 쓴 사진·PDF의 메모리를 돌려준다 (사진 수백 장·큰 PDF에서 휴대폰 창이 멈추던 문제, 2026-09-29 검토) */
    function release(items, closeDocs) {
      for (const it of items) {
        if (io && it.fig) io.unobserve(it.fig);
        if (it.img && /^blob:/.test(it.img.src || '')) { try { URL.revokeObjectURL(it.img.src); } catch (_) {} }
        it.work = null;
      }
      if (closeDocs) new Set(items.map((it) => it.pj).filter(Boolean)).forEach((pj) => { try { pj.destroy(); } catch (_) {} });
    }
    const api = {
      el: grid, sel,
      get order() { return order; },
      count: () => order.length,
      picked: () => order.filter((x) => sel.has(x)),
      targets: () => (sel.size ? order.filter((x) => sel.has(x)) : order.slice()),   /* 고른 것이 없으면 전체 */
      add(items) {
        const start = order.length;
        items.forEach(make); order.push(...items); relayout(); changed();
        items.forEach((it, k) => { if (io && start + k >= 24) io.observe(it.fig); });
        const eager = io ? items.filter((_, k) => start + k < 24) : items;
        (async () => { for (const it of eager) { if (!alive) return; await paint(it); } })();
      },
      setPositions(list) { sel.clear(); list.forEach((k) => order[k] && sel.add(order[k])); changed(); },
      all() { order.forEach((x) => sel.add(x)); changed(); },
      none() { sel.clear(); changed(); },
      invert() { order.forEach((x) => { if (sel.has(x)) sel.delete(x); else sel.add(x); }); changed(); },
      turn(items, deg) { items.forEach((x) => (x.rot = (((x.rot + deg) % 360) + 360) % 360)); changed(); },
      reset() { order.forEach((x) => (x.rot = 0)); changed(); },
      remove(items) { order = order.filter((x) => !items.includes(x)); items.forEach((x) => sel.delete(x)); release(items, false); relayout(); changed(); },
      shift(items, delta) {   /* 고른 것들을 한 칸 앞/뒤로 (휴대폰용) */
        if (!items.length) return;
        const idx = items.map((x) => order.indexOf(x)).sort((a, b) => a - b);
        if (delta < 0 && idx[0] === 0) return; if (delta > 0 && idx[idx.length - 1] === order.length - 1) return;
        const target = order[delta < 0 ? idx[0] - 1 : idx[idx.length - 1] + 1];
        move(items, target, delta > 0);
      },
      sort(cmp) { order.sort(cmp); relayout(); changed(); },   /* 순서 되돌리기 등 (2026-10-07) */
      refresh: changed,
      repaint(it) { it.done = false; paint(it); },   /* 편집한 사진의 섬네일 다시 그리기 */
      clear() { release(order, true); order = []; sel.clear(); relayout(); changed(); },
      destroy() { alive = false; if (io) io.disconnect(); release(order, true); },
    };
    return api;
  }
  /* 판 위쪽 막대: 전체·해제·반전 + 번호로 고르기 + 도구별 단추 */
  function boardBar(g, extra, opt = {}) {
    const rng = h('input', { type: 'text', placeholder: '번호로 고르기 (예: 1-3, 5, 8-)', 'aria-label': '번호로 고르기', style: { flex: '1 1 180px', width: 'auto' } });
    const apply = () => { const idx = parseRange(rng.value, g.count()); if (!idx.length) return toast('번호를 확인해 주세요'); g.setPositions(idx); };
    rng.addEventListener('keydown', (e) => { if (e.key === 'Enter') apply(); });
    return h('div', { class: 'pgbar stack', style: { gap: '8px' } },
      opt.noSelect ? null : h('div', { class: 'btns', style: { alignItems: 'center' } },
        h('button', { class: 'btn', type: 'button', onclick: () => g.all() }, '전체 선택'),
        h('button', { class: 'btn', type: 'button', onclick: () => g.none() }, '선택 해제'),
        h('button', { class: 'btn', type: 'button', onclick: () => g.invert() }, '선택 반전'),
        rng, h('button', { class: 'btn', type: 'button', onclick: apply }, '고르기')),
      extra);
  }
  const btn = (label, onclick, primary) => h('button', { class: 'btn' + (primary ? ' primary' : ''), type: 'button', onclick }, label);
  const row = (...kids) => h('div', { class: 'btns', style: { alignItems: 'center' } }, ...kids);
  const hint = (t) => h('p', { class: 'note', style: { margin: 0 } }, t);


  Object.assign(App, { board, boardBar, btn, row, hint, parseRange, picksText, imageItem });
})();
