/* 문서 만들기 공용 부품 (2026-09-29) — 글 뭉치를 한글(HWPX)·ODT·TXT 파일로 만든다. 모두 브라우저 안에서만.
   pages: [[문단, 문단, …], [문단, …]]  — 쪽마다 문단 목록. opt.pageBreak 가 참이면 쪽이 바뀔 때 새 쪽에서 시작한다.
   HWPX 틀은 hwpx 스킬의 기본 템플릿(templates/base)을 그대로 쓴다: 스타일 정의(header.xml)와 미리보기 그림은
   사이트의 hwpx/ 폴더에서 받아 오고, 나머지 작은 파일은 아래에 그대로 적어 두었다.
   규칙(스킬 지침): mimetype 은 ZIP 첫 항목·무압축, 첫 문단 첫 런에 secPr + colPr, 빈 줄은 <hp:t/>. */
(function () {
  'use strict';
  const NS = 'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf/" xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" xmlns:epub="http://www.idpf.org/2007/ops" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0"';
  /* XML에 넣을 수 없는 글자(제어문자)는 빼고 & < > " 는 바꾼다 */
  const esc = (s) => String(s).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F￾￿]/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const SEC_PR = `<hp:p id="3121190098" paraPrIDRef="0" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0"><hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" textVerticalWidthHead="0" masterPageCnt="0"><hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/><hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/><hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/><hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/><hp:pagePr landscape="WIDELY" width="59528" height="84186" gutterType="LEFT_ONLY"><hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/></hp:pagePr><hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/><hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="EACH_COLUMN" beneathText="0"/></hp:footNotePr><hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/><hp:noteLine length="14692344" type="SOLID" width="0.12 mm" color="#000000"/><hp:noteSpacing betweenNotes="0" belowLine="567" aboveLine="850"/><hp:numbering type="CONTINUOUS" newNum="1"/><hp:placement place="END_OF_DOCUMENT" beneathText="0"/></hp:endNotePr><hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill><hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill><hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" headerInside="0" footerInside="0" fillArea="PAPER"><hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill></hp:secPr><hp:ctrl><hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/></hp:ctrl></hp:run><hp:run charPrIDRef="0"><hp:t/></hp:run></hp:p>`;
  const CONTAINER = `<?xml version='1.0' encoding='UTF-8'?>\n<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf">\n  <ocf:rootfiles>\n    <ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>\n    <ocf:rootfile full-path="Preview/PrvText.txt" media-type="text/plain"/>\n    <ocf:rootfile full-path="META-INF/container.rdf" media-type="application/rdf+xml"/>\n  </ocf:rootfiles>\n</ocf:container>\n`;
  const RDF = `<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about=""><ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" rdf:resource="Contents/header.xml"/></rdf:Description><rdf:Description rdf:about="Contents/header.xml"><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#HeaderFile"/></rdf:Description><rdf:Description rdf:about=""><ns0:hasPart xmlns:ns0="http://www.hancom.co.kr/hwpml/2016/meta/pkg#" rdf:resource="Contents/section0.xml"/></rdf:Description><rdf:Description rdf:about="Contents/section0.xml"><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#SectionFile"/></rdf:Description><rdf:Description rdf:about=""><rdf:type rdf:resource="http://www.hancom.co.kr/hwpml/2016/meta/pkg#Document"/></rdf:Description></rdf:RDF>`;
  const MANIFEST = `<?xml version='1.0' encoding='UTF-8'?>\n<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>\n`;
  const VERSION = `<?xml version='1.0' encoding='UTF-8'?>\n<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.5" application="Hancom Office Hangul" appVersion="13, 0, 0, 1408 WIN32LEWindows_10"/>\n`;
  const SETTINGS = `<?xml version='1.0' encoding='UTF-8'?>\n<ha:HWPApplicationSetting xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">\n  <ha:CaretPosition listIDRef="0" paraIDRef="0" pos="16"/>\n</ha:HWPApplicationSetting>\n`;
  const hpf = (title) => `<?xml version='1.0' encoding='UTF-8'?>\n<opf:package ${NS} version="" unique-identifier="" id="">\n  <opf:metadata>\n    <opf:title>${esc(title || '')}</opf:title>\n    <opf:language>ko</opf:language>\n    <opf:meta name="creator" content="text">경기소방 업무도구함</opf:meta>\n  </opf:metadata>\n  <opf:manifest>\n    <opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>\n    <opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>\n    <opf:item id="settings" href="settings.xml" media-type="application/xml"/>\n  </opf:manifest>\n  <opf:spine>\n    <opf:itemref idref="header" linear="yes"/>\n    <opf:itemref idref="section0" linear="yes"/>\n  </opf:spine>\n</opf:package>\n`;

  function sectionXml(pages, opt) {
    let id = 1000000002; const out = [SEC_PR];
    pages.forEach((paras, pi) => {
      (paras.length ? paras : ['']).forEach((t, k) => {
        const brk = opt.pageBreak && pi > 0 && k === 0 ? '1' : '0';
        const body = t ? `<hp:t>${esc(t)}</hp:t>` : '<hp:t/>';
        out.push(`<hp:p id="${id++}" paraPrIDRef="0" styleIDRef="0" pageBreak="${brk}" columnBreak="0" merged="0"><hp:run charPrIDRef="0">${body}</hp:run></hp:p>`);
      });
    });
    return `<?xml version='1.0' encoding='UTF-8'?>\n<hs:sec ${NS}>${out.join('')}</hs:sec>\n`;
  }
  let tpl = null;
  async function template() {
    if (!tpl) tpl = Promise.all([fetch('toolbox/hwpx/header.xml').then((r) => { if (!r.ok) throw new Error('한글 문서 틀을 받지 못했습니다'); return r.text(); }), fetch('toolbox/hwpx/PrvImage.png').then((r) => r.arrayBuffer())])
      .catch((e) => { tpl = null; throw e; });
    return tpl;
  }
  async function hwpx(pages, opt = {}) {
    await App.lib('jszip');
    const [header, prv] = await template();
    const z = new JSZip();
    z.file('mimetype', 'application/hwp+zip', { compression: 'STORE' });   /* 반드시 첫 항목·무압축 */
    z.file('version.xml', VERSION);
    z.file('Contents/header.xml', header);
    z.file('Contents/section0.xml', sectionXml(pages, opt));
    z.file('Contents/content.hpf', hpf(opt.title));
    z.file('Preview/PrvText.txt', pages.flat().join('\r\n').slice(0, 1000));
    z.file('Preview/PrvImage.png', prv);
    z.file('settings.xml', SETTINGS);
    z.file('META-INF/container.rdf', RDF);
    z.file('META-INF/container.xml', CONTAINER);
    z.file('META-INF/manifest.xml', MANIFEST);
    return z.generateAsync({ type: 'blob', compression: 'DEFLATE', mimeType: 'application/hwp+zip' });
  }

  /* ODT (한컴·LibreOffice·워드에서 열림) — OpenDocument 최소 구성 */
  async function odt(pages, opt = {}) {
    await App.lib('jszip');
    const para = (t, brk) => `<text:p text:style-name="${brk ? 'PB' : 'Body'}">${esc(t).replace(/\t/g, '<text:tab/>')}</text:p>`;
    const body = pages.map((paras, pi) => (paras.length ? paras : ['']).map((t, k) => para(t, opt.pageBreak && pi > 0 && k === 0)).join('')).join('');
    const content = `<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" office:version="1.3">
<office:automatic-styles>
<style:style style:name="Body" style:family="paragraph"><style:paragraph-properties fo:margin-bottom="0.1cm" fo:line-height="160%"/><style:text-properties style:font-name="Malgun Gothic" fo:font-size="10pt" style:font-name-asian="Malgun Gothic" style:font-size-asian="10pt"/></style:style>
<style:style style:name="PB" style:family="paragraph" style:parent-style-name="Body"><style:paragraph-properties fo:break-before="page" fo:margin-bottom="0.1cm" fo:line-height="160%"/><style:text-properties style:font-name="Malgun Gothic" fo:font-size="10pt" style:font-name-asian="Malgun Gothic" style:font-size-asian="10pt"/></style:style>
</office:automatic-styles>
<office:font-face-decls/>
<office:body><office:text>${body}</office:text></office:body>
</office:document-content>`;
    const styles = `<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" office:version="1.3">
<office:font-face-decls><style:font-face style:name="Malgun Gothic" svg:font-family="'Malgun Gothic'" xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"/></office:font-face-decls>
<office:automatic-styles><style:page-layout style:name="A4"><style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm" fo:margin-top="2cm" fo:margin-bottom="1.5cm" fo:margin-left="3cm" fo:margin-right="3cm"/></style:page-layout></office:automatic-styles>
<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="A4"/></office:master-styles>
</office:document-styles>`;
    const meta = `<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" office:version="1.3"><office:meta><dc:title>${esc(opt.title || '')}</dc:title><meta:generator>경기소방 업무도구함</meta:generator></office:meta></office:document-meta>`;
    const manifest = `<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">
<manifest:file-entry manifest:full-path="/" manifest:version="1.3" manifest:media-type="application/vnd.oasis.opendocument.text"/>
<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>
</manifest:manifest>`;
    const z = new JSZip();
    z.file('mimetype', 'application/vnd.oasis.opendocument.text', { compression: 'STORE' });   /* 반드시 첫 항목·무압축 */
    z.file('content.xml', content); z.file('styles.xml', styles); z.file('meta.xml', meta); z.file('META-INF/manifest.xml', manifest);
    return z.generateAsync({ type: 'blob', compression: 'DEFLATE', mimeType: 'application/vnd.oasis.opendocument.text' });
  }
  /* TXT: 윈도 메모장에서 한글이 깨지지 않도록 BOM + CRLF, 쪽 사이는 빈 줄 두 개 */
  function txt(pages) { return new Blob(['﻿' + pages.map((p) => p.join('\r\n')).join('\r\n\r\n\r\n')], { type: 'text/plain;charset=utf-8' }); }

  /* ---------- 글자 인식(OCR) — tesseract.js, 엔진·한국어 데이터 모두 우리 사이트(ocr/)에서 받는다 ----------
     인식은 이 PC 안(웹 워커)에서만 이뤄진다. 인식 데이터는 처음 한 번 받은 뒤 브라우저에 보관된다. */
  let ocrW = null, ocrLang = '', ocrCb = null;
  async function ocrWorker(lang, onProgress) {
    ocrCb = onProgress;
    if (ocrW && ocrLang === lang) return ocrW;
    if (ocrW) { await ocrW.terminate(); ocrW = null; }
    await App.lib('ocr');
    const base = new URL('toolbox/ocr/', location.href).href;
    ocrW = await Tesseract.createWorker(lang.split('+'), 1 /* LSTM만 — 올려 둔 엔진 파일과 맞춘다 */, {
      workerPath: base + 'worker.min.js', corePath: base.replace(/\/$/, ''), langPath: base + 'lang', workerBlobURL: false, gzip: true,
      logger: (m) => { if (ocrCb) ocrCb(m); },
    });
    await ocrW.setParameters({ user_defined_dpi: '300', preserve_interword_spaces: '1' });   /* 보정 후 크기가 약 300dpi 수준이라 알려 준다 */
    ocrLang = lang;
    return ocrW;
  }
  /* 인식 전 사진 보정 (2026-09-29 인식률 개선)
     ① 인식하기 좋은 크기(긴 변 2,400~4,000px)로 맞추고
     ② 흑백으로 바꾼 뒤, 구역마다 가장 밝은 값(=종이 밝기)으로 나눠 그림자·얼룩을 걷어내고
     ③ 대비를 끝까지 늘린다 (가장 어두운 1% → 검정, 가장 밝은 1% → 흰색) */
  function prepImage(src, o = {}) {
    const W0 = src.naturalWidth || src.width, H0 = src.naturalHeight || src.height, long = Math.max(W0, H0);
    const s = long < 2400 ? 2400 / long : long > 4000 ? 4000 / long : 1;
    const W = Math.max(1, Math.round(W0 * s)), H = Math.max(1, Math.round(H0 * s));
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const x = c.getContext('2d', { willReadFrequently: true }); x.fillStyle = '#fff'; x.fillRect(0, 0, W, H);
    x.imageSmoothingQuality = 'high'; x.drawImage(src, 0, 0, W, H);
    const id = x.getImageData(0, 0, W, H), d = id.data, n = W * H, g = new Uint8ClampedArray(n);
    for (let i = 0, j = 0; i < n; i++, j += 4) g[i] = (d[j] * 299 + d[j + 1] * 587 + d[j + 2] * 114) / 1000;
    /* 잡티 줄이기: 3×3 평균을 세 번 (어두운 곳의 종이 결·센서 잡음이 밝기 보정으로 부풀려져
       글자 주변이 검은 점투성이가 되던 문제 — 그림자 진 폰 사진에서 인식률 0%) */
    const tmp = new Uint8ClampedArray(n);
    for (let pass = 0; pass < (o.smooth ?? 3); pass++) {   /* 3번: 시험에서 가장 좋았음 (2번보다 폰 사진 +10%p, 4번은 작은 글씨가 나빠짐) */
      for (let y = 0; y < H; y++) { const r = y * W; for (let xx = 0; xx < W; xx++) { const a = xx > 0 ? g[r + xx - 1] : g[r + xx], b = xx < W - 1 ? g[r + xx + 1] : g[r + xx]; tmp[r + xx] = (a + g[r + xx] + b) / 3; } }
      for (let y = 0; y < H; y++) { const r = y * W, up = y > 0 ? r - W : r, dn = y < H - 1 ? r + W : r; for (let xx = 0; xx < W; xx++) g[r + xx] = (tmp[up + xx] + tmp[r + xx] + tmp[dn + xx]) / 3; }
    }
    /* 종이 밝기: B×B 칸마다 가장 밝은 값 → 부드럽게 키워 배경 지도 */
    const B = Math.max(24, Math.round(Math.max(W, H) / 60)), bw = Math.ceil(W / B), bh = Math.ceil(H / B);
    const small = document.createElement('canvas'); small.width = bw; small.height = bh;
    const sx = small.getContext('2d'), sd = sx.createImageData(bw, bh);
    for (let by = 0; by < bh; by++) for (let bx = 0; bx < bw; bx++) {
      let m = 0; const y1 = Math.min(H, (by + 1) * B), x1 = Math.min(W, (bx + 1) * B);
      for (let y = by * B; y < y1; y += 2) for (let xx = bx * B; xx < x1; xx += 2) { const v = g[y * W + xx]; if (v > m) m = v; }
      const k = (by * bw + bx) * 4; sd.data[k] = sd.data[k + 1] = sd.data[k + 2] = Math.max(m, 40); sd.data[k + 3] = 255;
    }
    sx.putImageData(sd, 0, 0);
    const bg = document.createElement('canvas'); bg.width = W; bg.height = H;
    const bx2 = bg.getContext('2d', { willReadFrequently: true }); bx2.imageSmoothingEnabled = true; bx2.imageSmoothingQuality = 'high'; bx2.drawImage(small, 0, 0, W, H);
    const bd = bx2.getImageData(0, 0, W, H).data;
    const hist = new Uint32Array(256);
    for (let i = 0, j = 0; i < n; i++, j += 4) { const v = Math.min(255, (g[i] * 255) / Math.max(1, bd[j])); g[i] = v; hist[g[i]]++; }
    let lo = 0, hi = 255, acc = 0;
    for (; lo < 255; lo++) { acc += hist[lo]; if (acc > n * 0.01) break; }
    acc = 0; for (; hi > 0; hi--) { acc += hist[hi]; if (acc > n * 0.01) break; }
    const span = Math.max(1, hi - lo);
    for (let i = 0, j = 0; i < n; i++, j += 4) { const v = Math.max(0, Math.min(255, ((g[i] - lo) * 255) / span)); d[j] = d[j + 1] = d[j + 2] = v; d[j + 3] = 255; }
    /* (선택) 흑백 두 가지 색으로: 오츠 방식으로 경계값을 정한다 */
    if (o.bin) {
      const hh = new Uint32Array(256); for (let j = 0; j < d.length; j += 4) hh[d[j]]++;
      let sum = 0; for (let t = 0; t < 256; t++) sum += t * hh[t];
      let sB = 0, wB = 0, best = 0, th = 128;
      for (let t = 0; t < 256; t++) { wB += hh[t]; if (!wB) continue; const wF = n - wB; if (!wF) break; sB += t * hh[t]; const mB = sB / wB, mF = (sum - sB) / wF, v = wB * wF * (mB - mF) * (mB - mF); if (v > best) { best = v; th = t; } }
      for (let j = 0; j < d.length; j += 4) d[j] = d[j + 1] = d[j + 2] = d[j] > th ? 255 : 0;
    }
    x.putImageData(id, 0, 0); small.width = small.height = bg.width = bg.height = 0;
    return c;
  }
  /* 그림(캔버스·이미지)에서 글자를 읽어 줄 목록으로. opt.prep=false 면 보정 없이 */
  async function ocr(image, lang = 'kor+eng', onProgress, opt = {}) {
    /* 기본은 정밀 엔진(PaddleOCR). 불러오지 못하는 브라우저에서는 예전 엔진(tesseract)으로 자동 전환 */
    if (opt.engine !== 'tesseract') {
      try { await App.lib('pp'); return (await App.pp.recognize(image, onProgress)).map(fixBullets); }
      catch (e) { console.warn('정밀 엔진을 쓸 수 없어 예전 엔진으로 읽습니다', e); }
    }
    const w = await ocrWorker(lang, onProgress);
    const input = opt.prep === false ? image : prepImage(image, opt);
    const { data } = await w.recognize(input, { rotateAuto: opt.rotate !== false });
    if (input !== image) input.width = input.height = 0;
    return String(data.text || '').replace(/\r/g, '').split('\n').map(fixBullets);
  }
  /* 공문서 글머리표를 OCR이 흔히 잘못 읽는 모양 바로잡기: "[]"·"ㅁ"·"口" → □, "()"·"O "·"o " → ○ (줄 맨 앞에서만) */
  function fixBullets(line) {
    return line
      .replace(/^(\s*)(\[\s*\]|ㅁ|口|ロ)\s+/, '$1□ ')
      .replace(/^(\s*)(\(\s*\)|[Oo0Ｏ](?=\s))\s*/, '$1○ ')
      .replace(/^(\s*)(ㅇ|°)\s+/, '$1○ ');
  }
  async function ocrEnd() { if (ocrW) { const w = ocrW; ocrW = null; ocrLang = ''; try { await w.terminate(); } catch (_) {} } }

  App.docgen = { hwpx, odt, txt, sectionXml, ocr, ocrEnd };
})();
