const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');

test('structured guidance can be saved with separate legal and e-Saram evidence', () => {
  const anchors = [];
  const urls = new Map();
  let blobId = 0;
  const box = { children: [], querySelector: () => null, appendChild(node) { this.children.push(node); node.parentNode = this; }, append(...nodes) { nodes.forEach(node => this.appendChild(node)); }, removeChild(node) { this.children = this.children.filter(item => item !== node); } };
  const document = {
    body: { appendChild(node) { node.parentNode = this; }, removeChild(node) {} },
    createElement(tag) {
      const listeners = {};
      const node = { tagName: tag.toUpperCase(), style: {}, attributes: {}, setAttribute(key, value) { this.attributes[key] = value; }, addEventListener(type, callback) { listeners[type] = callback; }, append(...nodes) { this.children = [...(this.children || []), ...nodes]; }, click() { anchors.push({ ...this }); }, remove() {}, _click: () => listeners.click?.() };
      return node;
    }
  };
  const c = {
    window: { setTimeout, URL: { createObjectURL(blob) { const id = `blob:${++blobId}`; urls.set(id, blob); return id; }, revokeObjectURL() {} } },
    document, Blob, URL: { createObjectURL(blob) { const id = `blob:${++blobId}`; urls.set(id, blob); return id; }, revokeObjectURL() {} },
    Intl, Date, Set, Number, String, Array, Object, JSON, Math
  };
  vm.createContext(c);
  vm.runInContext(fs.readFileSync(path.join(root, 'static/answer-record.js'), 'utf8'), c);
  const response = {
    mode: 'structured_guidance', query: '휴가 신청 절차', summary: '등록 자료 기반 안내', answer: '신청 전 확인하세요.',
    guidance: {
      title: '휴가 처리 방법', context: '연가 신청', notice: '실무 준비 제안입니다. 법령 근거를 확인하세요.',
      steps: [{ title: '잔여 일수 확인', detail: '복무 기록 확인' }], questions: ['적용 신분을 확인해 주세요.'],
      deadlines: [{ text: '신청 기한은 기관 기준 확인', ref: 1 }], forms: [{ name: '연가 신청서', href: '/api/documents/doc-1/download', synthetic: true }],
      manual: { evidence: [{ title: 'e-사람 휴가 매뉴얼', page: 27, source_id: 'manual-1', sha256: 'abc123', quote: '휴가 신청 메뉴에서 등록합니다.' }] }
    },
    knowledge: { evidence: [{ title: '복무 규정', kind: '규정', loc: '제12조', source_id: 'legal-1', sha256: 'def456', quote: '휴가에 관한 규정 원문입니다.' }] }
  };
  c.window.SeomuAnswerRecord.attach(box, response, { today: '2026-10-24' });
  const actions = box.children[0];
  assert.equal(actions.className, 'answer-record-actions');
  const button = actions.children[1];
  button._click();
  const anchor = anchors[0];
  assert.match(anchor.download, /^seomu-answer-\d+\.txt$/);
  const blob = urls.get(anchor.href);
  assert.ok(blob);
  return blob.text().then(contents => {
    assert.match(contents, /등록 자료 기반 구조화 안내/);
    assert.match(contents, /실무 준비 안내[\s\S]*잔여 일수 확인/);
    assert.match(contents, /법령 근거 1/);
    assert.match(contents, /복무 규정[\s\S]*휴가에 관한 규정 원문입니다/);
    assert.match(contents, /e-사람 사용법 · 등록 매뉴얼 원문/);
    assert.match(contents, /PDF 쪽수: 27[\s\S]*휴가 신청 메뉴에서 등록합니다/);
    assert.doesNotMatch(contents, /모델:/);
  });
});
