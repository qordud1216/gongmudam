/* 계산·유틸 도구 — 계산기, 특수문자·이모지, QR·바코드 */
(function () {
  'use strict';
  const { add, h, field, fmt, copy, save, lib, toast } = App;
  const CANVAS_FONT = '"Pretendard Variable","Noto Sans KR","Malgun Gothic",sans-serif';

  /* ---------- 수식 계산 (eval 없이 직접 해석) ---------- */
  const FUNCS = {
    sin: (x, deg) => Math.sin(deg ? (x * Math.PI) / 180 : x), cos: (x, deg) => Math.cos(deg ? (x * Math.PI) / 180 : x), tan: (x, deg) => Math.tan(deg ? (x * Math.PI) / 180 : x),
    asin: (x, deg) => (deg ? (Math.asin(x) * 180) / Math.PI : Math.asin(x)), acos: (x, deg) => (deg ? (Math.acos(x) * 180) / Math.PI : Math.acos(x)), atan: (x, deg) => (deg ? (Math.atan(x) * 180) / Math.PI : Math.atan(x)),
    log: (x) => Math.log10(x), ln: (x) => Math.log(x), sqrt: (x) => Math.sqrt(x), abs: (x) => Math.abs(x), exp: (x) => Math.exp(x),
  };
  function tokenize(src) {
    const s = src.replace(/×/g, '*').replace(/÷/g, '/').replace(/−/g, '-').replace(/√/g, 'sqrt').replace(/π/g, 'pi').replace(/,/g, '');
    const out = []; let i = 0;
    while (i < s.length) {
      const c = s[i];
      if (/\s/.test(c)) { i++; continue; }
      const m = s.slice(i).match(/^(\d+\.?\d*|\.\d+)(e[+-]?\d+)?/i);
      if (m) { out.push({ t: 'n', v: parseFloat(m[0]) }); i += m[0].length; continue; }
      const w = s.slice(i).match(/^[a-z]+/i);
      if (w) { out.push({ t: 'w', v: w[0].toLowerCase() }); i += w[0].length; continue; }
      if ('+-*/^()!%'.includes(c)) { out.push({ t: c }); i++; continue; }
      throw new Error(`알 수 없는 문자: ${c}`);
    }
    return out;
  }
  function evaluate(src, deg, ans) {
    const tk = tokenize(src); let p = 0;
    const peek = () => tk[p], next = () => tk[p++];
    const startsPrimary = (t) => t && (t.t === 'n' || t.t === 'w' || t.t === '(');
    /* 휴대폰 계산기처럼: "50+10%" = 55, "200-15%" = 170 (더하기·빼기 뒤의 %는 앞 값의 퍼센트) */
    function expr() { let v = term(); while (peek() && (peek().t === '+' || peek().t === '-')) { const o = next().t; const r = term(); const d = tk[p - 1] && tk[p - 1].t === '%' ? v * r : r; v = o === '+' ? v + d : v - d; } return v; }
    function term() {
      let v = unary();
      for (;;) {
        const t = peek();
        if (t && (t.t === '*' || t.t === '/')) { next(); const r = unary(); v = t.t === '*' ? v * r : v / r; }
        else if (startsPrimary(t)) v *= unary(); // 2π, 3(4) 같은 생략된 곱셈
        else return v;
      }
    }
    function unary() { const t = peek(); if (t && (t.t === '-' || t.t === '+')) { next(); const v = unary(); return t.t === '-' ? -v : v; } return power(); }
    function power() { const b = postfix(); if (peek() && peek().t === '^') { next(); return Math.pow(b, unary()); } return b; }
    function fact(n) { if (n < 0 || !Number.isInteger(n)) throw new Error('팩토리얼은 0 이상의 정수만'); if (n > 170) return Infinity; let r = 1; for (let i = 2; i <= n; i++) r *= i; return r; }
    function postfix() { let v = primary(); while (peek() && (peek().t === '!' || peek().t === '%')) { v = next().t === '!' ? fact(v) : v / 100; } return v; }
    function primary() {
      const t = next();
      if (!t) throw new Error('식이 끝나지 않았습니다');
      if (t.t === 'n') return t.v;
      if (t.t === '(') { const v = expr(); if (!peek() || peek().t !== ')') throw new Error('괄호가 닫히지 않았습니다'); next(); return v; }
      if (t.t === 'w') {
        if (t.v === 'pi') return Math.PI; if (t.v === 'e') return Math.E; if (t.v === 'ans') return ans || 0;
        if (FUNCS[t.v]) { const a = peek() && peek().t === '(' ? primary() : postfix(); return FUNCS[t.v](a, deg); }
        throw new Error(`모르는 함수: ${t.v}`);
      }
      throw new Error('식을 확인해 주세요');
    }
    const v = expr(); if (p < tk.length) throw new Error('식을 확인해 주세요'); return v;
  }
  const show = (v) => { if (!isFinite(v)) return isNaN(v) ? '계산 불가' : '∞'; const r = Math.round(v * 1e12) / 1e12; return Math.abs(r) >= 1e15 || (r !== 0 && Math.abs(r) < 1e-9) ? r.toExponential(8) : r.toLocaleString('ko-KR', { maximumFractionDigits: 10 }); };

  function calculator(el, sci) {
    let deg = true, ans = 0;
    const inp = h('input', { type: 'text', id: sci ? 'sciIn' : 'calcIn', 'aria-label': '계산식', inputmode: 'decimal', autocomplete: 'off', style: { fontFamily: 'var(--mono)', fontSize: '22px', textAlign: 'right', padding: '14px' } });
    const res = h('div', { class: 'mono', style: { fontSize: 'clamp(30px,6vw,44px)', fontWeight: 700, textAlign: 'right', minHeight: '1.3em', wordBreak: 'break-all', letterSpacing: '-.02em' } }, '0');
    const hist = h('div', { class: 'flist' });
    const degBtn = h('button', { class: 'btn', type: 'button' }, 'DEG');
    function preview() { if (!inp.value.trim()) { res.textContent = '0'; res.style.color = ''; return; } try { res.textContent = '= ' + show(evaluate(inp.value, deg, ans)); res.style.color = 'var(--ink-3)'; } catch (_) { res.style.color = 'var(--ink-3)'; } }
    function equals() {
      if (!inp.value.trim()) return;
      try {
        const v = evaluate(inp.value, deg, ans); const expr = inp.value;
        if (!isFinite(v)) { res.textContent = show(v); res.style.color = 'var(--bad)'; return; }   /* 계산 불가·무한대는 입력칸을 덮어쓰지 않는다 */
        ans = v; res.textContent = show(v); res.style.color = '';
        hist.prepend(h('button', { class: 'fitem', type: 'button', style: { cursor: 'pointer', textAlign: 'left' }, onclick: () => { inp.value = expr; preview(); inp.focus(); } },
          h('span', { class: 'nm mono' }, expr), h('b', { class: 'mono' }, '= ' + show(v))));
        while (hist.children.length > 20) hist.lastChild.remove();
        inp.value = String(+v.toPrecision(12));
      } catch (e) { res.textContent = e.message; res.style.color = 'var(--bad)'; }
    }
    function press(k) {
      if (k === '=') return equals();
      if (k === 'C') { inp.value = ''; preview(); return; }
      if (k === '⌫') { inp.value = inp.value.slice(0, -1); preview(); return; }
      const map = { 'x²': '^2', 'xʸ': '^', '√': '√(', 'n!': '!', '1/x': '^(-1)', 'sin': 'sin(', 'cos': 'cos(', 'tan': 'tan(', 'asin': 'asin(', 'acos': 'acos(', 'atan': 'atan(', 'log': 'log(', 'ln': 'ln(', 'eˣ': 'exp(', '|x|': 'abs(' };
      inp.value += map[k] || k; preview();
    }
    inp.addEventListener('input', preview);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === '=') { e.preventDefault(); equals(); } if (e.key === 'Escape') press('C'); });
    degBtn.addEventListener('click', () => { deg = !deg; degBtn.textContent = deg ? 'DEG' : 'RAD'; preview(); });
    const key = (k, cls) => h('button', { class: 'btn ' + (cls || ''), type: 'button', style: { padding: '14px 0', fontSize: '18px', fontFamily: /^[\d.]$/.test(k) ? 'var(--mono)' : '' }, onclick: () => press(k) }, k);
    const basic = [['C', 'op'], ['⌫', 'op'], ['(', 'op'], [')', 'op'], ['7'], ['8'], ['9'], ['÷', 'op'], ['4'], ['5'], ['6'], ['×', 'op'], ['1'], ['2'], ['3'], ['−', 'op'], ['0'], ['.'], ['%', 'op'], ['+', 'op']];
    const pad = h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: '8px' } }, basic.map(([k]) => key(k)), h('button', { class: 'btn primary', type: 'button', style: { gridColumn: '1 / -1', padding: '14px 0', fontSize: '20px' }, onclick: equals }, '='));
    const sciKeys = ['sin', 'cos', 'tan', 'π', 'asin', 'acos', 'atan', 'e', 'x²', 'xʸ', '√', 'n!', 'log', 'ln', 'eˣ', '1/x', '|x|', 'Ans'];
    const sciPad = sci ? h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: '8px' } }, degBtn, sciKeys.map((k) => key(k))) : null;
    el.append(h('div', { class: 'cols', style: { alignItems: 'start' } },
      h('div', { class: 'panel stack' }, inp, res, sciPad, pad),
      h('div', { class: 'panel stack' }, h('b', null, '계산 기록'), h('span', { class: 'hint', style: { fontSize: '12px', color: 'var(--ink-3)' } }, '누르면 식을 다시 불러옵니다. 키보드로 입력하고 Enter를 눌러도 됩니다.'), hist)));
    setTimeout(() => inp.focus(), 50);
  }

  add({ id: 'calc', cat: 'util', code: 'CALC', name: '일반 계산기', kw: '사칙연산 퍼센트 계산', desc: '사칙연산·괄호·퍼센트, 키보드 입력과 계산 기록', render: (el) => calculator(el, false) });
  add({
    id: 'sci', cat: 'util', code: 'SCI', name: '공학 계산기', kw: '삼각함수 로그 제곱근 거듭제곱 팩토리얼 sin cos',
    desc: '삼각함수(도·라디안), 로그, 거듭제곱, 제곱근, 팩토리얼',
    long: 'sin(30), 2^10, √(2), 5!, log(1000)처럼 입력할 수 있습니다. DEG 버튼으로 도(°)와 라디안을 바꿉니다. Ans는 직전 결과입니다.',
    render: (el) => calculator(el, true),
  });

  /* ---------- 특수문자·이모지 ---------- */
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => String.fromCodePoint(a + i));
  const SYMS = {
    '자주 쓰는 기호': [...'※○●◎◇◆□■△▲▽▼☆★♡♥☎☏♨✓✔✗✘·‥…¶§†‡♂♀♠♣'],
    '화살표': [...'→←↑↓↔↕⇒⇔⇐⇑⇓↗↘↙↖➡⬅⬆⬇▶◀▷◁►◄'],
    '원·괄호 숫자': [...range(0x2460, 0x2473), ...range(0x2474, 0x2487), ...range(0x3260, 0x326D), ...range(0x326E, 0x327B)],
    '로마 숫자·영문': [...range(0x2160, 0x216B), ...range(0x2170, 0x217B), ...range(0x24B6, 0x24CF)],
    '괄호·문장부호': [...'「」『』【】〈〉《》〔〕〘〙｛｝［］（）“”‘’〃〓―～¡¿'],
    '단위': [...'㎡㎥㎠㎝㎜㎞㎏㎎㎖㎗㎘℃℉°′″‰㎐㎑㎒㎾㎿㏊㎈㎉㎭'],
    '수학': [...'±×÷≠≒≡≤≥∞∴∵√∑∫∮∂∇∈∋⊂⊃∪∩∧∨¬½⅓⅔¼¾²³ⁿ₁₂'],
    '화폐·기타': [...'₩$€¥£¢©®™℡№㈜㉿'],
    '현장·안전 이모지': ['🚒', '🔥', '🧯', '🚑', '🚨', '⚠️', '⛑️', '🧑‍🚒', '👩‍🚒', '🏥', '📞', '📢', '📍', '📌', '🗺️', '💧', '🌊', '⚡', '☢️', '☣️', '🆘', '✅', '❌', '⭕', '🔴', '🟡', '🟢', '⚫'],
    '업무 이모지': ['📋', '📝', '📄', '📑', '📎', '📅', '⏰', '⏱️', '📊', '📈', '💡', '🔔', '🔒', '🔑', '💬', '📷', '🖨️', '💻', '📱', '✉️', '🗂️', '🏆', '🎖️', '🎯'],
    '표정·손짓': ['😊', '😄', '😂', '🥲', '😍', '🤔', '😅', '😭', '😡', '😴', '🥳', '😎', '🙏', '👍', '👏', '💪', '🙌', '👋', '✌️', '🤝', '❤️', '💯', '🎉', '🙇'],
    '날씨·음식': ['☀️', '⛅', '☁️', '🌧️', '⛈️', '❄️', '🌪️', '🌡️', '🌈', '☕', '🍗', '🍕', '🍔', '🍜', '🍚', '🍙', '🥟', '🍩', '🍦', '🍎', '🍉', '🥤'],
  };
  add({
    id: 'symbols', cat: 'util', code: 'SYM', name: '특수문자·이모지', kw: '기호 이모티콘 원숫자 단위 화살표 복사',
    desc: '기호·원 숫자·단위·이모지를 누르면 바로 복사, 여러 개 모아 붙여넣기',
    render(el) {
      const bucket = h('input', { type: 'text', id: 'symBucket', 'aria-label': '모은 문자', placeholder: '누른 문자가 여기에도 쌓입니다', style: { fontSize: '18px' } });
      const q = h('input', { type: 'search', id: 'symFilter', placeholder: '분류 이름으로 찾기 (예: 단위, 화살표)', 'aria-label': '분류 찾기' });
      const box = h('div', { class: 'stack' });
      function draw() {
        const f = q.value.trim();
        box.replaceChildren(...Object.entries(SYMS).filter(([k]) => !f || k.includes(f)).map(([k, list]) => h('div', { class: 'panel stack' }, h('b', null, k),
          h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(44px,1fr))', gap: '6px' } },
            list.map((ch) => h('button', { class: 'btn', type: 'button', title: ch, style: { padding: '8px 0', fontSize: '20px', lineHeight: 1.2 }, onclick: () => { bucket.value += ch; copy(ch); } }, ch))))));
      }
      q.addEventListener('input', draw); draw();
      el.append(h('div', { class: 'panel stack' }, h('div', { class: 'btns', style: { alignItems: 'center' } }, h('div', { style: { flex: '1 1 260px' } }, bucket),
        h('button', { class: 'btn primary', type: 'button', onclick: () => copy(bucket.value) }, '모은 것 복사'), h('button', { class: 'btn', type: 'button', onclick: () => (bucket.value = '') }, '비우기')), q), box,
        h('p', { class: 'note' }, '이모지는 한글(HWP) 문서나 일부 업무 시스템에서 네모(□)로 보일 수 있습니다. 공문에는 위쪽 기호를 쓰는 편이 안전합니다.'));
    },
  });

  /* ---------- QR·바코드 ---------- */
  add({
    id: 'qr', cat: 'util', code: 'QR', name: 'QR·바코드 생성기', kw: 'qr 바코드 barcode code128 라벨 점검표 장비 링크', lib: true,
    desc: 'QR 코드와 바코드(CODE128·EAN-13 등)를 만들고 라벨 문구와 함께 PNG로 저장',
    long: '점검표 링크, 장비 관리번호, 비상연락 안내 등을 QR로 만들 수 있습니다. 한글은 QR에만 들어가고, 바코드는 영문·숫자만 됩니다.',
    render(el) {
      const kind = field({ label: '종류', type: 'select', value: 'qr', options: [['qr', 'QR 코드'], ['CODE128', '바코드 CODE128 (영문·숫자)'], ['CODE39', '바코드 CODE39'], ['EAN13', '바코드 EAN-13 (숫자 12~13자리)'], ['ITF14', '바코드 ITF-14 (숫자 13~14자리)']] });
      const txt = field({ label: '담을 내용', type: 'textarea', rows: 3, value: '경기소방 공기호흡기 SCBA-07 · 최근 점검 2026-09-01' });
      const lab = field({ label: '아래 라벨 문구 (선택)', type: 'text', value: 'SCBA-07' });
      const size = field({ label: '크기', type: 'select', value: 512, options: [[256, '작게'], [512, '보통'], [1024, '크게 (인쇄용)']] });
      const ec = field({ label: 'QR 오류 복원', type: 'select', value: 'M', options: [['L', 'L (7%)'], ['M', 'M (15%)'], ['Q', 'Q (25%)'], ['H', 'H (30%, 훼손 대비)']] });
      const cv = h('canvas', { class: 'work', style: { maxWidth: '360px', background: '#fff' } });
      const st = h('div', { class: 'status' }, '코드를 불러오는 중…');
      function addLabel(src, S) {
        const labelH = lab.input.value ? Math.round(S * 0.14) : 0;
        cv.width = src.width; cv.height = src.height + labelH; const c = cv.getContext('2d');
        c.fillStyle = '#fff'; c.fillRect(0, 0, cv.width, cv.height); c.drawImage(src, 0, 0);
        if (labelH) { c.fillStyle = '#000'; c.font = `700 ${Math.round(labelH * 0.55)}px ${CANVAS_FONT}`; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(lab.input.value, cv.width / 2, src.height + labelH * 0.4, cv.width * 0.92); }
      }
      async function draw() {
        const k = kind.input.value, S = +size.input.value;
        ec.style.display = k === 'qr' ? '' : 'none';
        try {
          if (k === 'qr') {
            await lib('qr');
            window.qrcode.stringToBytes = window.qrcode.stringToBytesFuncs['UTF-8'];
            const q = window.qrcode(0, ec.input.value); q.addData(txt.input.value || ' ', 'Byte'); q.make();
            const n = q.getModuleCount(), quiet = 4, cell = S / (n + quiet * 2);
            const t = document.createElement('canvas'); t.width = t.height = S; const c = t.getContext('2d');
            c.fillStyle = '#fff'; c.fillRect(0, 0, S, S); c.fillStyle = '#000';
            for (let r = 0; r < n; r++) for (let j = 0; j < n; j++) if (q.isDark(r, j)) c.fillRect(Math.floor((j + quiet) * cell), Math.floor((r + quiet) * cell), Math.ceil(cell), Math.ceil(cell));
            addLabel(t, S); st.textContent = `QR ${n}×${n} 모듈 · ${cv.width}×${cv.height}px`;
          } else {
            await lib('barcode');
            const val = txt.input.value.trim();
            if (/[^\x20-\x7E]/.test(val)) { st.textContent = '바코드에는 한글을 넣을 수 없습니다. 영문·숫자로 입력해 주세요.'; return; }
            const t = document.createElement('canvas'); const unit = S / 256;
            JsBarcode(t, val || '0', { format: k, width: Math.max(1, Math.round(2 * unit)), height: Math.round(90 * unit), fontSize: Math.round(18 * unit), margin: Math.round(12 * unit), background: '#ffffff', lineColor: '#000000' });
            addLabel(t, S * 0.6); st.textContent = `${k} · ${cv.width}×${cv.height}px`;
          }
        } catch (e) { st.textContent = k === 'qr' ? '내용이 너무 깁니다. 줄이거나 오류 복원 단계를 낮춰 주세요.' : `이 형식에 맞지 않는 값입니다. ${k === 'EAN13' ? '숫자 12~13자리를 넣어 주세요.' : k === 'ITF14' ? '숫자 13~14자리를 넣어 주세요.' : ''}`; }
      }
      kind.input.addEventListener('change', () => { if (kind.input.value !== 'qr' && /[^\x20-\x7E]/.test(txt.input.value)) txt.input.value = kind.input.value === 'EAN13' ? '880123456789' : kind.input.value === 'ITF14' ? '1880123456789' : 'SCBA-07'; draw(); });
      [txt, lab, size, ec].forEach((f) => f.input.addEventListener('input', draw));
      draw().catch((e) => (st.textContent = e.message));
      el.append(h('div', { class: 'cols' }, h('div', { class: 'panel stack' }, kind, txt, lab, h('div', { class: 'fields' }, size, ec),
        h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', onclick: () => cv.toBlob((b) => save(`${kind.input.value === 'qr' ? 'QR' : '바코드'}_${(lab.input.value || 'code').replace(/[\\/:*?"<>|]/g, '')}.png`, b)) }, 'PNG 저장'))),
        h('div', { class: 'panel stack', style: { alignItems: 'center' } }, cv, st)));
    },
  });
})();
