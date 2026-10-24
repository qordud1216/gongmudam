/* 글자 인식 엔진 2 (2026-09-29) — PaddleOCR PP-OCRv5 한국어 모델을 onnxruntime-web으로 이 PC 안에서 돌린다.
   · 모델·실행기 모두 우리 사이트(ocr/)에 올려 둔 파일만 쓴다 — 외부 전송 없음, CSP connect-src 'self' 유지
   · 순서: ① 글줄 찾기(det) ② 기울기 재서 바로 세우고 다시 찾기 ③ 글줄마다 읽기(rec, CTC)
   · 사용자 문서(저수조 청소 결과보고서)로 시험: 기존 엔진 73~95% → 이 엔진 97~100%, 3° 기운 폰 사진도 96% */
(function () {
  'use strict';
  const BASE = new URL('toolbox/ocr/', location.href).href;
  let S = null, loading = null;

  /* 받는 양을 알려 주며 파일 받기 */
  async function fetchBuf(url, onBytes) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('글자 인식 모델을 받지 못했습니다 (' + r.status + ')');
    const total = +r.headers.get('content-length') || 0;
    if (!r.body || !total) return new Uint8Array(await r.arrayBuffer());
    const rd = r.body.getReader(), parts = []; let got = 0;
    for (;;) { const { done, value } = await rd.read(); if (done) break; parts.push(value); got += value.length; if (onBytes) onBytes(got, total); }
    const out = new Uint8Array(got); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  }
  async function init(progress) {
    if (S) return S;
    if (!loading) loading = (async () => {
      ort.env.wasm.wasmPaths = BASE + 'ort/'; ort.env.wasm.numThreads = 1; ort.env.wasm.proxy = false;
      const sizes = { det: 0, rec: 0 }, got = { det: 0, rec: 0 };
      const tell = () => { const t = sizes.det + sizes.rec; if (progress && t) progress({ status: 'loading model', progress: (got.det + got.rec) / t }); };
      const [det, rec, dict] = await Promise.all([
        fetchBuf(BASE + 'pp/det.onnx', (g, t) => { got.det = g; sizes.det = t; tell(); }),
        fetchBuf(BASE + 'pp/rec_kor.onnx', (g, t) => { got.rec = g; sizes.rec = t; tell(); }),
        fetch(BASE + 'pp/dict_kor.txt').then((r) => r.text()),
      ]);
      if (progress) progress({ status: 'initializing', progress: 1 });
      const opt = { executionProviders: ['wasm'], graphOptimizationLevel: 'all' };
      S = { det: await ort.InferenceSession.create(det, opt), rec: await ort.InferenceSession.create(rec, opt), vocab: ['', ...dict.split('\n')] };
      return S;
    })().catch((e) => { loading = null; throw e; });
    return loading;
  }

  /* 캔버스 → [1,3,H,W] (BGR 순서, 모델 학습 때와 같게) */
  function tensorBGR(ctx, w, h, mean, std) {
    const d = ctx.getImageData(0, 0, w, h).data, n = w * h, f = new Float32Array(3 * n);
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      f[i] = (d[j + 2] / 255 - mean[0]) / std[0];           // B
      f[n + i] = (d[j + 1] / 255 - mean[1]) / std[1];       // G
      f[2 * n + i] = (d[j] / 255 - mean[2]) / std[2];       // R
    }
    return new ort.Tensor('float32', f, [1, 3, h, w]);
  }
  const canvasOf = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };

  /* ① 글줄 찾기: 확률 지도 → 이어진 덩어리 → 상자. 덩어리마다 기울기(주축 각도)도 잰다 */
  async function detect(src) {
    const W = src.width, H = src.height, s = 1600 / Math.max(W, H);
    const nw = Math.max(32, Math.round((W * s) / 32) * 32), nh = Math.max(32, Math.round((H * s) / 32) * 32);
    const c = canvasOf(nw, nh), x = c.getContext('2d', { willReadFrequently: true });
    x.fillStyle = '#fff'; x.fillRect(0, 0, nw, nh); x.imageSmoothingQuality = 'high'; x.drawImage(src, 0, 0, nw, nh);
    const out = await S.det.run({ x: tensorBGR(x, nw, nh, [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]) });
    const prob = out[Object.keys(out)[0]].data, n = nw * nh;
    const seen = new Uint8Array(n), stack = new Int32Array(n), comps = [];
    for (let p0 = 0; p0 < n; p0++) {
      if (seen[p0] || prob[p0] <= 0.3) continue;
      let top = 0, cnt = 0, sum = 0, x0 = 1e9, y0 = 1e9, x1 = -1, y1 = -1, sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
      stack[top++] = p0; seen[p0] = 1;
      while (top) {
        const p = stack[--top], px = p % nw, py = (p - px) / nw;
        cnt++; sum += prob[p]; sx += px; sy += py; sxx += px * px; syy += py * py; sxy += px * py;
        if (px < x0) x0 = px; if (px > x1) x1 = px; if (py < y0) y0 = py; if (py > y1) y1 = py;
        if (px > 0 && !seen[p - 1] && prob[p - 1] > 0.3) { seen[p - 1] = 1; stack[top++] = p - 1; }
        if (px < nw - 1 && !seen[p + 1] && prob[p + 1] > 0.3) { seen[p + 1] = 1; stack[top++] = p + 1; }
        if (py > 0 && !seen[p - nw] && prob[p - nw] > 0.3) { seen[p - nw] = 1; stack[top++] = p - nw; }
        if (py < nh - 1 && !seen[p + nw] && prob[p + nw] > 0.3) { seen[p + nw] = 1; stack[top++] = p + nw; }
      }
      const bw = x1 - x0 + 1, bh = y1 - y0 + 1;
      if (bw < 3 || bh < 3 || sum / cnt < 0.6) continue;
      const mx = sx / cnt, my = sy / cnt, cxx = sxx / cnt - mx * mx, cyy = syy / cnt - my * my, cxy = sxy / cnt - mx * my;
      const ang = 0.5 * Math.atan2(2 * cxy, cxx - cyy), tr = cxx + cyy, det2 = Math.sqrt(Math.max(0, ((cxx - cyy) * (cxx - cyy)) / 4 + cxy * cxy));
      const l1 = tr / 2 + det2, l2 = Math.max(1e-6, tr / 2 - det2);
      comps.push({ x0, y0, bw, bh, ang, elong: Math.sqrt(l1 / l2), len: 2 * Math.sqrt(l1) });
    }
    return { comps, sx: W / nw, sy: H / nh };
  }
  /* ② 기울기: 긴 글줄들의 각도를 길이 가중 중앙값으로 */
  function skew(comps) {
    const L = comps.filter((c) => c.elong > 4 && c.bw >= 40).map((c) => ({ a: c.ang, w: c.len })).sort((p, q) => p.a - q.a);
    if (!L.length) return 0;
    const tot = L.reduce((s, c) => s + c.w, 0); let acc = 0;
    for (const c of L) { acc += c.w; if (acc >= tot / 2) return c.a; }
    return 0;
  }
  function rotated(src, rad) {
    const c = canvasOf(src.width, src.height), x = c.getContext('2d');
    x.fillStyle = '#fff'; x.fillRect(0, 0, c.width, c.height);
    x.translate(c.width / 2, c.height / 2); x.rotate(-rad); x.drawImage(src, -src.width / 2, -src.height / 2);
    return c;
  }
  /* ③ 한 글줄 읽기: 높이 48로 맞춰 모델에 넣고, 같은 글자가 이어진 것·빈칸을 걷어낸다(CTC) */
  async function readBox(src, b) {
    const w = b[2] - b[0], h = b[3] - b[1]; if (w < 2 || h < 2) return '';
    const nw = Math.min(3200, Math.max(8, Math.ceil((48 * w) / h)));
    const c = canvasOf(nw, 48), x = c.getContext('2d', { willReadFrequently: true });
    x.fillStyle = '#fff'; x.fillRect(0, 0, nw, 48); x.imageSmoothingQuality = 'high'; x.drawImage(src, b[0], b[1], w, h, 0, 0, nw, 48);
    const out = await S.rec.run({ x: tensorBGR(x, nw, 48, [0.5, 0.5, 0.5], [0.5, 0.5, 0.5]) });
    const t = out[Object.keys(out)[0]], [, T, C] = t.dims, d = t.data;
    let s = '', prev = -1;
    for (let i = 0; i < T; i++) {
      let best = 0, bv = -Infinity; const o = i * C;
      for (let k = 0; k < C; k++) if (d[o + k] > bv) { bv = d[o + k]; best = k; }
      if (best !== prev && best !== 0) s += S.vocab[best] || '';
      prev = best;
    }
    return s;
  }

  async function recognize(image, progress) {
    await init(progress);
    let src = image;
    if (!(src instanceof HTMLCanvasElement)) { const c = canvasOf(src.naturalWidth || src.width, src.naturalHeight || src.height); c.getContext('2d').drawImage(src, 0, 0); src = c; }
    if (progress) progress({ status: 'recognizing text', progress: 0 });
    let D = await detect(src);
    const a = skew(D.comps);
    if (Math.abs((a * 180) / Math.PI) > 0.3) { src = rotated(src, a); D = await detect(src); }   /* 기울어진 사진은 바로 세워 다시 찾기 */
    /* 상자를 조금 넓히고(글자 가장자리 포함) 원래 크기로 되돌린 뒤, 위→아래·왼→오른 순서로 줄을 묶는다 */
    const boxes = D.comps.map((c) => {
      const d = (c.bw * c.bh * 1.5) / (2 * (c.bw + c.bh));
      return [Math.max(0, (c.x0 - d) * D.sx), Math.max(0, (c.y0 - d) * D.sy), Math.min(src.width, (c.x0 + c.bw + d) * D.sx), Math.min(src.height, (c.y0 + c.bh + d) * D.sy)];
    }).sort((p, q) => p[1] - q[1] || p[0] - q[0]);
    const lines = []; let cur = [];
    for (const b of boxes) {
      const last = cur[cur.length - 1];
      if (last && Math.abs((b[1] + b[3]) / 2 - (last[1] + last[3]) / 2) > (last[3] - last[1]) * 0.5) { lines.push(cur.sort((p, q) => p[0] - q[0])); cur = []; }
      cur.push(b);
    }
    if (cur.length) lines.push(cur.sort((p, q) => p[0] - q[0]));
    const total = boxes.length, out = []; let done = 0;
    for (const L of lines) {
      const parts = [];
      for (const b of L) { parts.push(await readBox(src, b)); done++; if (progress) progress({ status: 'recognizing text', progress: done / total }); }
      out.push(parts.filter(Boolean).join(' '));
    }
    if (src !== image) src.width = src.height = 0;
    return out;
  }

  App.pp = { init, recognize };
})();
