/* 근무·행정 도구 */
(function () {
  'use strict';
  const { add, h, field, num, stat, fmt, pad, fmtTime, fmtDur, fmtSize, copy, save, stamp, toast, lib, dropzone, fileList } = App;
  let actx = null;
  function beep(freq = 880, dur = 0.2) {
    try { if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)(); if (actx.state === 'suspended') actx.resume();
      const o = actx.createOscillator(), g = actx.createGain(); o.frequency.value = freq; g.gain.value = 0.25; o.connect(g); g.connect(actx.destination); o.start(); o.stop(actx.currentTime + dur); } catch (_) {}
  }
  const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parseD = (s) => { const [y, m, d] = String(s).split('-').map(Number); return new Date(y, (m || 1) - 1, d || 1); };
  const DAY = 86400000;
  const dayDiff = (a, b) => Math.round((Date.UTC(b.getFullYear(), b.getMonth(), b.getDate()) - Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())) / DAY);
  const WD = ['일', '월', '화', '수', '목', '금', '토'];
  const lastDay = (y, m) => new Date(y, m + 1, 0).getDate();
  /* 년·개월을 먼저 더하고(말일 넘으면 말일로) 그다음 일을 더한다 */
  function addYMD(d0, y, m, d) {
    const tm = d0.getMonth() + m + y * 12, yy = d0.getFullYear() + Math.floor(tm / 12), mm = ((tm % 12) + 12) % 12;
    return new Date(yy, mm, Math.min(d0.getDate(), lastDay(yy, mm)) + d);
  }
  /* A~B 기간을 N년 M개월 L일로 (inclusive면 마지막 날까지 센다 — 초일 산입) */
  function ymdBetween(A, B, inclusive) {
    /* 개월을 넘치지 않을 만큼 최대한 더한 뒤 남은 날을 센다 — 1월 31일~3월 1일 = 1개월 1일 (음수 일 방지) */
    const E = inclusive ? new Date(B.getFullYear(), B.getMonth(), B.getDate() + 1) : B;
    let tm = (E.getFullYear() - A.getFullYear()) * 12 + (E.getMonth() - A.getMonth());
    if (addYMD(A, 0, tm, 0) > E) tm--;
    const d = dayDiff(addYMD(A, 0, tm, 0), E), y = Math.floor(tm / 12), m = tm - y * 12;
    return { y, m, d };
  }
  function rand(n) { const a = new Uint32Array(1); crypto.getRandomValues(a); return a[0] % n; }
  function shuffle(arr) { const a = arr.slice(); for (let i = a.length - 1; i > 0; i--) { const j = rand(i + 1); [a[i], a[j]] = [a[j], a[i]]; } return a; }

  /* 12. 교대근무 달력 */
  const PATTERNS = {
    '3-1': { name: '3팀 1교대 (당·비·휴)', p: '당,비,휴', teams: 3 },
    '4-2': { name: '4팀 2교대 (주·야·비·휴)', p: '주,야,비,휴', teams: 4 },
    '4-2b': { name: '4팀 2교대 (주·주·야·야·비·비·휴·휴)', p: '주,주,야,야,비,비,휴,휴', teams: 4 },
    '2-1': { name: '2팀 격일 (당·비)', p: '당,비', teams: 2 },
    'custom': { name: '직접 입력', p: '주,야,비,휴', teams: 4 },
  };
  const SHIFT_COLOR = { '주': ['var(--warn-soft)', 'var(--warn)'], '야': ['#1E3350', '#DCE6F2'], '당': ['var(--accent-soft)', 'var(--accent)'], '비': ['var(--surface-2)', 'var(--ink-2)'], '휴': ['var(--ok-soft)', 'var(--ok)'] };
  add({
    id: 'shift', cat: 'admin', code: 'SHIFT', name: '교대근무 달력', kw: '3조1교대 4조2교대 3팀1교대 4팀2교대 당비휴 주야비휴 근무표 당번',
    desc: '교대 방식과 기준일을 넣으면 팀별 근무 달력을 자동으로 표시',
    long: '기준일은 1팀이 근무 순서의 첫 칸(예: "당" 또는 "주")을 서는 날입니다. 나머지 팀은 순서대로 하루씩(8일 주기는 2일씩) 밀려서 계산됩니다.',
    render(el) {
      const today = new Date();
      const pat = field({ label: '교대 방식', type: 'select', value: '3-1', options: Object.entries(PATTERNS).map(([k, v]) => [k, v.name]) });
      const cus = field({ label: '근무 순서 (쉼표로 구분)', type: 'text', value: PATTERNS['3-1'].p });
      const teamsF = field({ label: '팀 수', value: 3, step: 1, min: 1 });
      const base = field({ label: '기준일 (1팀이 첫 칸 근무)', type: 'date', value: ymd(today) });
      const team = field({ label: '볼 팀', type: 'select', value: 1, options: [[1, '1팀']] });
      let ym = new Date(today.getFullYear(), today.getMonth(), 1);
      const title = h('b', { style: { fontSize: '18px' } });
      const cal = h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: '4px' } });
      const all = h('div', { class: 'tbl-wrap' });
      const sum = h('div', { class: 'btns' });
      const shiftWarn = h('p', { class: 'note warn', hidden: true });
      function seq() { return cus.input.value.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean); }
      function codeFor(t, d) {
        const s = seq(), n = s.length, T = Math.max(1, num(teamsF) | 0);
        if (!n) return '';
        const step = n % T === 0 ? n / T : 1;
        const i = dayDiff(parseD(base.input.value), d) - (t - 1) * step;
        return s[((i % n) + n) % n];
      }
      function chip(c, big) {
        const [bg, fg] = SHIFT_COLOR[c] || ['var(--surface-2)', 'var(--ink)'];
        return h('span', { style: { background: bg, color: fg, fontWeight: 700, borderRadius: '5px', padding: big ? '2px 8px' : '1px 5px', fontSize: big ? '14px' : '12px', display: 'inline-block' } }, c);
      }
      function draw() {
        const T = Math.max(1, num(teamsF) | 0);
        if (team.input.options.length !== T) { const cur = +team.input.value || 1; team.input.replaceChildren(...Array.from({ length: T }, (_, i) => h('option', { value: i + 1, selected: i + 1 === cur }, `${i + 1}팀`))); }
        const t = +team.input.value || 1;
        title.textContent = `${ym.getFullYear()}년 ${ym.getMonth() + 1}월 · ${t}팀`;
        const first = new Date(ym), days = new Date(ym.getFullYear(), ym.getMonth() + 1, 0).getDate();
        const cells = WD.map((w, i) => h('div', { style: { textAlign: 'center', fontSize: '12px', fontWeight: 600, color: i === 0 ? 'var(--bad)' : 'var(--ink-3)' } }, w));
        for (let i = 0; i < first.getDay(); i++) cells.push(h('div'));
        const counts = {};
        for (let d = 1; d <= days; d++) {
          const dt = new Date(ym.getFullYear(), ym.getMonth(), d), c = codeFor(t, dt);
          counts[c] = (counts[c] || 0) + 1;
          const isToday = dayDiff(dt, today) === 0;
          cells.push(h('div', { style: { border: `1px solid ${isToday ? 'var(--accent)' : 'var(--line)'}`, borderRadius: '6px', padding: '6px 4px', minHeight: '58px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', background: 'var(--surface)' } },
            h('span', { class: 'mono', style: { fontSize: '12px', color: dt.getDay() === 0 ? 'var(--bad)' : 'var(--ink-2)' } }, d), chip(c, true)));
        }
        cal.replaceChildren(...cells);
        sum.replaceChildren(...Object.entries(counts).map(([c, n]) => h('span', null, chip(c), ` ${n}일`)));
        /* 직접 입력한 순서가 팀 수로 나누어떨어지지 않거나, 아무 팀도 근무하지 않는 날이 생기면 알린다 (2026-09-29 검토) */
        const S2 = seq(), T2 = Math.max(1, num(teamsF) | 0), off = /^(비|휴|휴무|비번)$/, noDuty = [];
        for (let d = 1; d <= days; d++) { const dt = new Date(ym.getFullYear(), ym.getMonth(), d); if (!Array.from({ length: T2 }, (_, k) => codeFor(k + 1, dt)).some((c) => c && !off.test(c))) noDuty.push(d); }
        const msgs = [];
        if (S2.length % T2 !== 0) msgs.push(`근무 순서 ${S2.length}칸이 팀 수 ${T2}로 나누어떨어지지 않아, 팀마다 하루씩만 밀려서 계산했습니다.`);
        if (noDuty.length) msgs.push(`이번 달 ${noDuty.slice(0, 10).join(', ')}${noDuty.length > 10 ? ' …' : ''}일에는 근무하는 팀이 없습니다. 근무 순서나 팀 수를 확인해 주세요.`);
        shiftWarn.hidden = !msgs.length; shiftWarn.textContent = msgs.join(' ');
        const head = h('tr', null, h('th', null, '팀'), ...Array.from({ length: days }, (_, i) => { const dt = new Date(ym.getFullYear(), ym.getMonth(), i + 1); return h('th', { style: { textAlign: 'center', color: dt.getDay() === 0 ? 'var(--bad)' : '' } }, `${i + 1}`, h('br'), WD[dt.getDay()]); }));
        const rows = Array.from({ length: T }, (_, k) => h('tr', null, h('td', null, `${k + 1}팀`), ...Array.from({ length: days }, (_, i) => h('td', { style: { textAlign: 'center', padding: '4px 2px' } }, chip(codeFor(k + 1, new Date(ym.getFullYear(), ym.getMonth(), i + 1)))))));
        all.replaceChildren(h('table', null, h('thead', null, head), h('tbody', null, rows)));
      }
      pat.input.addEventListener('change', () => { const p = PATTERNS[pat.input.value]; cus.input.value = p.p; teamsF.input.value = p.teams; draw(); });
      [cus, teamsF, base, team].forEach((f) => f.input.addEventListener('input', draw));
      team.input.addEventListener('change', draw);
      function csv() {
        const T = Math.max(1, num(teamsF) | 0), days = new Date(ym.getFullYear(), ym.getMonth() + 1, 0).getDate();
        const lines = [['날짜', '요일', ...Array.from({ length: T }, (_, i) => `${i + 1}팀`)].join(',')];
        for (let d = 1; d <= days; d++) { const dt = new Date(ym.getFullYear(), ym.getMonth(), d); lines.push([ymd(dt), WD[dt.getDay()], ...Array.from({ length: T }, (_, k) => codeFor(k + 1, dt))].join(',')); }
        return '﻿' + lines.join('\r\n');
      }
      el.append(h('div', { class: 'panel stack' }, h('div', { class: 'fields' }, pat, cus, teamsF, base, team)),
        h('div', { class: 'panel stack' },
          h('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' } },
            h('button', { class: 'btn', type: 'button', onclick: () => { ym = new Date(ym.getFullYear(), ym.getMonth() - 1, 1); draw(); } }, '← 이전 달'), title,
            h('button', { class: 'btn', type: 'button', onclick: () => { ym = new Date(ym.getFullYear(), ym.getMonth() + 1, 1); draw(); } }, '다음 달 →'),
            h('button', { class: 'btn', type: 'button', onclick: () => { ym = new Date(today.getFullYear(), today.getMonth(), 1); draw(); } }, '이번 달')),
          cal, sum, shiftWarn),
        h('div', { class: 'panel stack' }, h('div', { style: { display: 'flex', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap', alignItems: 'center' } }, h('b', null, '전체 팀 근무표'),
          h('button', { class: 'btn', type: 'button', onclick: () => save(`근무표_${ym.getFullYear()}${pad(ym.getMonth() + 1)}.csv`, csv()) }, '엑셀용 CSV 저장')), all),
        h('p', { class: 'note' }, '공휴일·교육·휴가 등 개인 일정은 반영하지 않습니다. 교대 순서가 다르면 "근무 순서"를 직접 고쳐 쓰세요.'));
      draw();
    },
  });

  /* 글쓰기 도우미 (2026-09-29) — 따로 운영하는 사이트로 연결한다.
     이 도구함과 달리 'AI 다듬기'는 글 내용이 서버로 전송되므로, 열기 전에 그 차이를 알린다. */
  add({
    id: 'writer', cat: 'admin', code: 'WRITE', name: '소방 글쓰기 도우미', ext: true, kw: '보도자료 인사말 축사 홍보문 민원 답변 상황 속보 글쓰기 AI',
    desc: '보도자료·인사말·안전 홍보문·민원 답변·상황 속보 초안을 빠르게 작성 (별도 사이트)',
    render(el) {
      const url = 'https://write.visanu81.workers.dev/?from=toolbox';
      el.append(h('div', { class: 'panel stack' },
        h('p', { style: { margin: 0, fontSize: '15px' } }, '행사·사안 정보를 넣으면 보도자료, 기관장 인사말·축사, 안전 홍보문, 민원 답변서, 화재·사고 상황 속보 초안을 만들어 주는 별도 사이트입니다. 한글·워드로 바로 저장할 수 있습니다.'),
        h('p', { class: 'note warn', style: { margin: 0 } }, '이 도구함과 다른 점: 글쓰기 도우미의 [AI로 다듬기]를 누르면 작성한 글이 AI 서버로 전송됩니다. 개인정보·비공개 내용은 넣지 말고, 필요하면 AI 다듬기 없이 [글 만들기]만 쓰세요.'),
        h('div', { class: 'btns' }, h('a', { class: 'btn primary big', href: url, target: '_blank', rel: 'noopener', style: { textDecoration: 'none' } }, '글쓰기 도우미 열기 (새 창) ↗')),
        h('p', { class: 'hint', style: { margin: 0, fontSize: '12.5px', color: 'var(--ink-3)' } }, '주소: write.visanu81.workers.dev')));
    },
  });

  /* 13. 날짜 계산 */
  add({
    id: 'dday', cat: 'admin', code: 'DATE', name: '날짜·D-day·카운트다운', kw: '일수 기간 평일 근무일 점검 주기 교육 카운트다운 남은시간 전역 퇴근 공적조서 재직기간 근무기간 년 개월',
    desc: '실시간 카운트다운, 두 날짜 사이 일수·기간(년·개월·일), 기준일로부터 N년 M개월 L일 계산',
    render(el) {
      const t = new Date(), later = new Date(t.getTime() + 30 * DAY);
      const a = field({ label: '시작일', type: 'date', value: ymd(t) }), b = field({ label: '종료일', type: 'date', value: ymd(later) });
      const inc = field({ label: '계산 방식', type: 'select', value: 'x', options: [['x', '시작일 제외'], ['i', '시작일 포함 (초일 산입)']] });
      const r1 = stat('차이', '일', true), r2 = stat('평일 (월~금)', '일'), r3 = stat('주 · 일', ''), r4 = stat('D-day', ''), r5 = stat('기간 (년·개월·일)', '');
      /* 기준일로부터 N년 M개월 L일 (2026-09-29 직원 요청: 공적조서 작성 등) */
      const s = field({ label: '기준일', type: 'date', value: ymd(t) });
      const dir = field({ label: '방향', type: 'select', value: '1', options: [['1', '뒤 (이후)'], ['-1', '전 (이전)']] });
      const ny = field({ label: '년', value: 0, step: 1, min: 0 }), nm = field({ label: '개월', value: 0, step: 1, min: 0 }), n = field({ label: '일', value: 100, step: 1, min: 0 });
      const incS = field({ label: '기준일 포함', type: 'select', value: 'x', options: [['x', '포함 안 함'], ['i', '포함 (초일 산입 · 하루 빼기)']] });
      const o1 = stat('결과 날짜', '', true), o2 = stat('요일', ''), o3 = stat('기준일과의 차이', '일');
      function c1() {
        const A = parseD(a.input.value), B = parseD(b.input.value); let d = dayDiff(A, B); if (inc.input.value === 'i') d += d >= 0 ? 1 : -1;
        let wd = 0; const lo = A < B ? A : B, cnt = Math.abs(dayDiff(A, B)) + 1;
        for (let i = 0; i < cnt; i++) { const x = new Date(lo.getFullYear(), lo.getMonth(), lo.getDate() + i).getDay(); if (x && x < 6) wd++; }
        if (inc.input.value === 'x' && A.getDay() && A.getDay() < 6) wd--;   /* 시작일 제외: 시작일이 평일이면 빼고 센다 */
        r1.set(fmt(d, 0)); r2.set(fmt(wd, 0)); r3.set(`${Math.floor(Math.abs(d) / 7)}주 ${Math.abs(d) % 7}일`);
        const P = ymdBetween(A < B ? A : B, A < B ? B : A, inc.input.value === 'i'); r5.set(`${P.y}년 ${P.m}개월 ${P.d}일`);
        const dd = dayDiff(new Date(), B); r4.set(dd === 0 ? 'D-DAY' : dd > 0 ? `D-${dd}` : `D+${-dd}`);
      }
      function c2() {
        const S = parseD(s.input.value), sg = +dir.input.value;
        let R = addYMD(S, sg * (num(ny) | 0), sg * (num(nm) | 0), sg * (num(n) | 0));
        if (incS.input.value === 'i') R = new Date(R.getFullYear(), R.getMonth(), R.getDate() - sg);   /* 기준일을 첫날로 세면 하루 당겨진다 */
        o1.set(ymd(R)); o2.set(WD[R.getDay()] + '요일'); o3.set(fmt(dayDiff(S, R), 0));
      }
      [a, b, inc].forEach((f) => f.input.addEventListener('input', c1)); [s, dir, ny, nm, n, incS].forEach((f) => f.input.addEventListener('input', c2)); c1(); c2();
      /* 실시간 카운트다운 (여러 개) */
      const cds = [], cdBox = h('div', { class: 'cols' });
      const cdName = field({ label: '이름', type: 'text', value: '' , placeholder: '예: 소방기술경연대회' });
      const cdDate = field({ label: '목표 날짜', type: 'date', value: `${t.getFullYear()}-12-31` });
      const cdTime = field({ label: '목표 시각', type: 'time', value: '18:00' });
      function addCd(name, d, tm) {
        const [y, m, dd] = d.split('-').map(Number), [hh, mi] = (tm || '00:00').split(':').map(Number);
        const target = new Date(y, m - 1, dd, hh || 0, mi || 0, 0);
        if (isNaN(target)) return toast('날짜를 확인해 주세요');
        const big = h('div', { class: 'mono', style: { fontSize: 'clamp(26px,5vw,38px)', fontWeight: 700, letterSpacing: '-.02em', lineHeight: 1.2 } });
        const dLabel = h('span', { class: 'pill ok' });
        const item = { target, big, dLabel };
        item.el = h('div', { class: 'panel stack' },
          h('div', { style: { display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' } }, h('b', null, name || '카운트다운'),
            h('button', { class: 'ib', type: 'button', 'aria-label': '삭제', onclick: () => { cds.splice(cds.indexOf(item), 1); item.el.remove(); } }, '×')),
          dLabel, big, h('span', { class: 'hint', style: { fontSize: '12px', color: 'var(--ink-3)' } }, `${ymd(target)} (${WD[target.getDay()]}) ${pad(target.getHours())}:${pad(target.getMinutes())}`));
        cds.push(item); cdBox.append(item.el); tickCd();
      }
      function tickCd() {
        const now = Date.now();
        for (const c of cds) {
          let ms = c.target - now; const past = ms < 0; ms = Math.abs(ms);
          const d = Math.floor(ms / DAY), hh = Math.floor(ms / 3600000) % 24, mi = Math.floor(ms / 60000) % 60, se = Math.floor(ms / 1000) % 60;
          c.big.textContent = `${d}일 ${pad(hh)}:${pad(mi)}:${pad(se)}`;
          const dd = dayDiff(new Date(), c.target);
          c.dLabel.className = 'pill ' + (past ? 'bad' : dd <= 7 ? 'warn' : 'ok');
          c.dLabel.textContent = past ? `지남 · D+${-dd}` : dd === 0 ? 'D-DAY · 오늘' : `D-${dd}`;
        }
      }
      const cdIv = setInterval(tickCd, 1000);
      addCd('올해 마지막 날 퇴근까지', `${t.getFullYear()}-12-31`, '18:00');
      el.append(h('div', { class: 'panel stack' }, h('b', null, '카운트다운'), h('div', { class: 'fields' }, cdName, cdDate, cdTime),
        h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', onclick: () => { addCd(cdName.input.value.trim(), cdDate.input.value, cdTime.input.value); cdName.input.value = ''; } }, '카운트다운 추가'))), cdBox);
      el.append(h('div', { class: 'panel stack' }, h('b', null, '두 날짜 사이'), h('div', { class: 'fields' }, a, b, inc), h('div', { class: 'result' }, r1, r5, r2, r3, r4)),
        h('div', { class: 'panel stack' }, h('b', null, '기준일로부터 N년 M개월 L일'), h('div', { class: 'fields' }, s, dir, ny, nm, n, incS), h('div', { class: 'result' }, o1, o2, o3),
          h('p', { class: 'hint', style: { margin: 0, fontSize: '12.5px', color: 'var(--ink-3)' } }, '년·개월을 먼저 더하고 일을 더합니다. 달의 끝을 넘으면 그 달 마지막 날로 맞춥니다 (예: 1월 31일 + 1개월 = 2월 28일 또는 29일).')),
        h('p', { class: 'note' }, '평일 수에는 공휴일이 빠져 있지 않습니다. 법정 기간 계산은 관련 규정의 초일 산입 여부를 확인하세요.'));
      return () => clearInterval(cdIv);
    },
  });

  /* 14. 글자수 세기 */
  add({
    id: 'chars', cat: 'admin', code: 'TEXT', name: '글자수 세기', kw: '보도자료 원고지 바이트 문자',
    desc: '공백 포함·제외 글자수, 단어, 줄, 바이트, 원고지 매수',
    render(el) {
      const ta = field({ label: '내용', type: 'textarea', rows: 10, value: '경기소방은 가을철 화재 예방을 위해 관내 전통시장과 공동주택을 대상으로 합동 소방안전점검을 실시한다고 밝혔다.' });
      const s = ['공백 포함', '공백 제외', '단어', '줄', '바이트 (UTF-8)', '바이트 (EUC-KR)', '200자 원고지'].map((k, i) => stat(k, i === 6 ? '매' : '', i === 0));
      function c() {
        const v = ta.input.value;
        const withS = [...v.replace(/\r?\n/g, '')].length, noS = [...v.replace(/\s/g, '')].length;
        const words = (v.trim().match(/\S+/g) || []).length, lines = v ? v.split(/\n/).length : 0;
        const u8 = new TextEncoder().encode(v).length; let euc = 0; for (const ch of v) euc += ch.charCodeAt(0) > 127 ? 2 : 1;
        [withS, noS, words, lines, u8, euc, Math.ceil([...v].length / 200)].forEach((x, i) => s[i].set(fmt(x, 0)));
      }
      ta.input.addEventListener('input', c); c();
      el.append(h('div', { class: 'panel stack' }, ta, h('div', { class: 'result' }, s)));
    },
  });

  /* 15. 텍스트 정리 · 개인정보 가리기 */
  add({
    id: 'clean', cat: 'admin', code: 'MASK', name: '텍스트 정리·개인정보 가리기', kw: '마스킹 전화번호 주민번호 중복 줄 공백 명단',
    desc: '전화번호·주민번호·이메일 가리기, 중복 줄·빈 줄 제거, 정렬',
    long: '보고서·보도자료·명단을 외부로 보내기 전에 개인정보를 가릴 때 씁니다. 원하는 항목을 고르고 "적용"을 누르세요.',
    render(el) {
      const inp = field({ label: '원문', type: 'textarea', rows: 9, value: '홍길동 010-1234-5678 hong@example.com\n김소방 010 9876 5432 850101-1234567\n\n홍길동 010-1234-5678 hong@example.com\n동두천시 중앙로 123' });
      const out = field({ label: '결과', type: 'textarea', rows: 9 });
      const opts = [['phone', '전화번호 가운데 가리기', true], ['rrn', '주민등록번호 뒷자리 가리기', true], ['email', '이메일 아이디 가리기', true], ['name', '2~4자 한글 낱말의 가운데 가리기 (이름이 아닌 낱말도 가려짐)', false], ['dup', '중복 줄 제거', true], ['blank', '빈 줄 제거', true], ['trim', '줄 앞뒤 공백 정리', true], ['sort', '가나다순 정렬', false]]
        .map(([k, t, on]) => { const c = h('input', { type: 'checkbox', id: 'cl_' + k, checked: on }); return { k, c, el: h('label', { for: 'cl_' + k, style: { display: 'flex', gap: '6px', alignItems: 'center', fontSize: '14px' } }, c, t) }; });
      const on = (k) => opts.find((o) => o.k === k).c.checked;
      function run() {
        let lines = inp.input.value.split(/\r?\n/);
        if (on('trim')) lines = lines.map((l) => l.trim().replace(/\s{2,}/g, ' '));
        if (on('blank')) lines = lines.filter((l) => l.trim());
        if (on('dup')) { const seen = new Set(); lines = lines.filter((l) => (seen.has(l) ? false : seen.add(l))); }
        if (on('sort')) lines.sort((a, b) => a.localeCompare(b, 'ko'));
        let t = lines.join('\n');
        /* 2026-09-29 검토 반영: 앞뒤가 숫자인 경우(날짜·사건번호)는 건드리지 않고, 외국인 번호(뒷자리 5~8)와 +82·괄호 형식도 가린다 */
        if (on('rrn')) t = t.replace(/(?<!\d)(\d{6})[-\s]?([1-8])\d{6}(?!\d)/g, '$1-$2******');
        if (on('phone')) t = t.replace(/(?<!\d)(\+82[-\s]?)?(\(?0?1[016789]\)?|\(?0\d{1,2}\)?)([-\s.]?)(\d{3,4})([-\s.]?)(\d{4})(?!\d)/g, (m, cc, a, s1, b, s2, c) => `${cc || ''}${a}${s1}${'*'.repeat(b.length)}${s2}${c}`);
        if (on('email')) t = t.replace(/([A-Za-z0-9._%+-]{1,2})[A-Za-z0-9._%+-]*@/g, '$1***@');
        if (on('name')) t = t.replace(/(^|[\s,(])([가-힣])([가-힣]{1,2})([가-힣])?(?=[\s,)]|$)/gm, (m, p, a, b, c) => c ? `${p}${a}${'*'.repeat(b.length)}${c}` : b.length === 1 ? `${p}${a}*` : `${p}${a}*${b.slice(1)}`);
        out.input.value = t;
      }
      el.append(h('div', { class: 'panel stack' }, h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: '8px' } }, opts.map((o) => o.el)),
        h('div', { class: 'cols' }, inp, out),
        h('div', { class: 'btns' }, h('button', { class: 'btn primary', type: 'button', onclick: run }, '적용'), h('button', { class: 'btn', type: 'button', onclick: () => copy(out.input.value) }, '결과 복사'))),
        h('p', { class: 'note warn' }, '자동 가리기는 형식이 정해진 값만 찾습니다. 이름·주소 등은 누락될 수 있으니 결과를 반드시 눈으로 확인하세요.'));
      run();
    },
  });

  /* 16. 추첨·당번 배정 */
  add({
    id: 'draw', cat: 'admin', code: 'DRAW', name: '추첨·당번 배정', kw: '랜덤 순서 뽑기 당직 청소',
    desc: '명단에서 N명 추첨, 순서 섞기, 날짜별 당번 자동 배정',
    render(el) {
      const names = field({ label: '명단 (한 줄에 한 명)', type: 'textarea', rows: 8, value: '김소방\n이구조\n박구급\n최진압\n정예방\n강행정' });
      const mode = field({ label: '방식', type: 'select', value: 'pick', options: [['pick', 'N명 추첨'], ['order', '전체 순서 섞기'], ['duty', '날짜별 당번 배정']] });
      const cnt = field({ label: '추첨 인원', value: 2, step: 1, min: 1 });
      const start = field({ label: '당번 시작일', type: 'date', value: ymd(new Date()) });
      const days = field({ label: '배정 일수', value: 14, step: 1 });
      const skipWk = h('label', { style: { display: 'flex', gap: '6px', alignItems: 'center', fontSize: '14px' } }, h('input', { type: 'checkbox', id: 'dr_wk' }), '주말 제외');
      const res = h('div', { class: 'stack' }); let lastText = '';
      function run() {
        const list = names.input.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
        if (!list.length) return toast('명단을 입력해 주세요');
        const m = mode.input.value, stampT = fmtTime(new Date());
        let rows = [];
        if (m === 'pick') rows = shuffle(list).slice(0, Math.min(list.length, num(cnt) | 0 || 1)).map((n, i) => [`${i + 1}`, n]);
        if (m === 'order') rows = shuffle(list).map((n, i) => [`${i + 1}`, n]);
        if (m === 'duty') {
          const order = shuffle(list); let d = parseD(start.input.value), k = 0; const N = num(days) | 0; const skip = el.querySelector('#dr_wk').checked;
          for (let i = 0; rows.length < N && i < N * 3; i++) { const dt = new Date(d.getFullYear(), d.getMonth(), d.getDate() + i); if (skip && (dt.getDay() === 0 || dt.getDay() === 6)) continue; rows.push([`${ymd(dt)} (${WD[dt.getDay()]})`, order[k++ % order.length]]); }
        }
        lastText = rows.map((r) => r.join('\t')).join('\n');
        res.replaceChildren(h('span', { class: 'note' }, `추첨 시각 ${stampT} · 브라우저 암호학적 난수(crypto) 사용`),
          h('div', { class: 'tbl-wrap' }, h('table', null, h('tbody', null, rows.map((r) => h('tr', null, h('td', { class: 'mono' }, r[0]), h('td', { style: { fontWeight: 600 } }, r[1])))))),
          h('div', { class: 'btns' }, h('button', { class: 'btn', type: 'button', onclick: () => copy(lastText) }, '결과 복사')));
      }
      el.append(h('div', { class: 'panel stack' }, h('div', { class: 'cols' }, names, h('div', { class: 'stack' }, mode, cnt, start, days, skipWk)),
        h('div', { class: 'btns' }, h('button', { class: 'btn primary big', type: 'button', onclick: run }, '추첨하기'))), h('div', { class: 'panel' }, res));
      run();
    },
  });

  /* 17. 타이머·스톱워치 */
  add({
    id: 'timer', cat: 'admin', code: 'TIME', name: '타이머·스톱워치', kw: '카운트다운 랩 훈련 측정',
    desc: '알림음 카운트다운과 구간기록(랩) 스톱워치, 훈련 기록 측정용',
    render(el) {
      const mm = field({ label: '분', value: 5, step: 1, min: 0 }), ss = field({ label: '초', value: 0, step: 1, min: 0, max: 59 });
      const cd = h('div', { class: 'mono', style: { fontSize: 'clamp(48px,14vw,96px)', fontWeight: 600, textAlign: 'center' } }, '05:00');
      let cdEnd = 0, cdLeft = 300000, cdRun = false;
      const cdBtn = h('button', { class: 'btn primary big', type: 'button' }, '시작');
      const presets = h('div', { class: 'btns' }, [1, 3, 5, 10, 20, 30].map((m) => h('button', { class: 'btn', type: 'button', onclick: () => { mm.input.value = m; ss.input.value = 0; resetCd(); } }, `${m}분`)));
      function resetCd() { cdRun = false; cdLeft = ((num(mm) || 0) * 60 + (num(ss) || 0)) * 1000; cd.textContent = fmtDur(cdLeft); cd.style.color = ''; cdBtn.textContent = '시작'; }
      cdBtn.addEventListener('click', () => { beep(0, 0.001); if (cdRun) { cdRun = false; cdLeft = cdEnd - Date.now(); cdBtn.textContent = '계속'; } else { if (cdLeft <= 0) resetCd(); cdEnd = Date.now() + cdLeft; cdRun = true; cdBtn.textContent = '일시정지'; } });
      [mm, ss].forEach((f) => f.input.addEventListener('input', resetCd));
      const sw = h('div', { class: 'mono', style: { fontSize: 'clamp(48px,14vw,96px)', fontWeight: 600, textAlign: 'center' } }, '00:00.0');
      let swStart = 0, swAcc = 0, swRun = false; const laps = h('tbody');
      const swFmt = (ms) => fmtDur(ms) + '.' + Math.floor((ms % 1000) / 100);
      const swBtn = h('button', { class: 'btn primary big', type: 'button', onclick: () => { if (swRun) { swAcc += Date.now() - swStart; swRun = false; swBtn.textContent = '계속'; } else { swStart = Date.now(); swRun = true; swBtn.textContent = '정지'; } } }, '시작');
      const swNow = () => swAcc + (swRun ? Date.now() - swStart : 0);
      let lastLap = 0;
      const lapBtn = h('button', { class: 'btn big', type: 'button', onclick: () => { const t = swNow(); laps.prepend(h('tr', null, h('td', null, `${laps.children.length + 1}`), h('td', { class: 'mono' }, swFmt(t - lastLap)), h('td', { class: 'mono' }, swFmt(t)))); lastLap = t; } }, '구간');
      const swReset = h('button', { class: 'btn big', type: 'button', onclick: () => { swRun = false; swAcc = 0; lastLap = 0; laps.replaceChildren(); swBtn.textContent = '시작'; sw.textContent = '00:00.0'; } }, '초기화');
      const iv = setInterval(() => {
        if (cdRun) { const left = cdEnd - Date.now(); cd.textContent = fmtDur(Math.max(0, left) + 999); if (left <= 0) { cdRun = false; cdLeft = 0; cd.textContent = '00:00'; cd.style.color = 'var(--accent)'; cdBtn.textContent = '다시'; [0, 400, 800, 1200].forEach((d) => setTimeout(() => beep(880, 0.25), d)); } }
        if (swRun) sw.textContent = swFmt(swNow());
      }, 100);
      el.append(h('div', { class: 'cols' },
        h('div', { class: 'panel stack' }, h('b', null, '타이머'), h('div', { class: 'fields' }, mm, ss), presets, cd, h('div', { class: 'btns' }, cdBtn, h('button', { class: 'btn big', type: 'button', onclick: resetCd }, '초기화'))),
        h('div', { class: 'panel stack' }, h('b', null, '스톱워치'), sw, h('div', { class: 'btns' }, swBtn, lapBtn, swReset), h('div', { class: 'tbl-wrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '#'), h('th', null, '구간'), h('th', null, '누적'))), laps)))));
      return () => clearInterval(iv);
    },
  });

  /* 19. ZIP 압축·해제 */
  add({
    id: 'zip', cat: 'admin', code: 'ZIP', name: 'ZIP 압축·풀기', kw: '압축 파일 묶기 해제', lib: true,
    desc: '여러 파일을 ZIP 하나로 묶거나, ZIP 안의 파일을 꺼내기',
    render(el) {
      const list = fileList(() => (btn.disabled = !list.files.length));
      const nm = field({ label: 'ZIP 파일 이름', type: 'text', value: `묶음_${stamp()}` });
      const st = h('div', { class: 'status' });
      const btn = h('button', { class: 'btn primary', type: 'button', disabled: true, onclick: async () => {
        st.textContent = '압축하는 중…'; await lib('jszip'); const z = new JSZip();
        list.files.forEach((f) => z.file(f.name, f));
        const blob = await z.generateAsync({ type: 'blob', compression: 'DEFLATE' }, (m) => (st.textContent = `압축 ${m.percent.toFixed(0)}%`));
        st.textContent = `완료 · ${fmtSize(blob.size)}`; save((nm.input.value || '묶음') + '.zip', blob);
      } }, 'ZIP으로 묶기');
      const out = h('div', { class: 'flist' }); const st2 = h('div', { class: 'status' });
      el.append(h('div', { class: 'cols' },
        h('div', { class: 'panel stack' }, h('b', null, '묶기'), dropzone({ onFiles: (f) => list.add(f) }), list, nm, h('div', { class: 'btns' }, btn), st),
        h('div', { class: 'panel stack' }, h('b', null, '풀기'), dropzone({ accept: '.zip', multiple: false, label: 'ZIP 파일 선택', onFiles: async ([f]) => {
          st2.textContent = '여는 중…'; await lib('jszip');
          try {
            const z = await JSZip.loadAsync(f, { decodeFileName: (b) => { try { return new TextDecoder('utf-8', { fatal: true }).decode(b); } catch (_) { return new TextDecoder('euc-kr').decode(b); } } });
            const ents = Object.values(z.files).filter((e) => !e.dir);
            out.replaceChildren(...ents.map((e) => h('div', { class: 'fitem' }, h('span', { class: 'nm', title: e.name }, e.name),
              h('button', { class: 'btn', type: 'button', onclick: async () => save(e.name.split('/').pop(), await e.async('blob')) }, '저장'))));
            st2.textContent = `${ents.length}개 파일`;
          } catch (e) { st2.textContent = 'ZIP 파일을 열지 못했습니다: ' + e.message; }
        } }), st2, out)));
    },
  });
})();
