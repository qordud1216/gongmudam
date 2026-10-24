/* Self-contained regression checks for the real workflow module; no browser or services. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const sourcePath = path.join(__dirname, '..', 'static', 'adhoc-workflow.js');
let source = fs.readFileSync(sourcePath, 'utf8');
const exportLine = 'return {init,render,leave};';
assert(source.includes(exportLine), 'workflow module export shape changed; update test-only exposure');
source = source.replace(exportLine,
  'return {init,render,leave,openEditor,get editorContext(){return editorContext;}};');

function harness({handoff = null} = {}) {
  const nodes = new Map();
  const apiCalls = [];
  const messages = [];
  let formSubmit = null;
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
      id, value: '', hidden: false, textContent: '', innerHTML: '', open: false,
      addEventListener(type, fn) { if (type === 'submit') formSubmit = fn; },
      showModal() { this.open = true; }, close() { this.open = false; },
      querySelectorAll() { return []; },
      querySelector() { return null; },
    });
    return nodes.get(id);
  }
  const document = {
    getElementById: node,
    createElement(tag) { const el = node(`created-${tag}`); el.tagName = tag.toUpperCase(); return el; },
    body: { append(el) { nodes.set(el.id, el); } },
    querySelector() { return null; },
  };
  const context = {
    document,
    window: { SeomuFlow: { take: () => handoff } },
    current: null,
    esc: value => String(value ?? ''),
    message: (...args) => messages.push(args),
    guarded(el, action, event) { if (event === 'submit') formSubmit = action; },
    api: async (...args) => { apiCalls.push(args); return await new Promise((resolve, reject) => context.pending.push({resolve, reject})); },
    refresh: (previous, updated) => { if(context.current?.id===previous.id) context.current={...context.current,...updated}; },
    pending: [],
    URLSearchParams,
    console,
  };
  vm.createContext(context);
  vm.runInContext(source, context, {filename: sourcePath});
  const workflow = context.window.AdHocWorkflow;
  function makeJob(id, revision = 3, version = 7) {
    return {id, version, workflow: {revision, steps: [{id: 'custom-1', title: '단계', detail: '상세', checks: [],
      caution: '', references: [], kind: 'custom'}]}};
  }
  function submitDraft(title) {
    node('wf-title').value = title;
    node('wf-detail').value = `상세 ${title}`;
    node('wf-checks').value = `확인 ${title}`;
    node('wf-caution').value = `주의 ${title}`;
    assert.equal(typeof formSubmit, 'function', 'editor submit handler was not registered');
    return formSubmit({preventDefault() {}});
  }
  return {context, workflow, node, apiCalls, messages, makeJob, submitDraft};
}

const tick = () => new Promise(resolve => setImmediate(resolve));

async function testDelayedSaveCannotReplaceOtherJobDraft() {
  const h = harness();
  h.context.current = h.makeJob('A');
  h.workflow.openEditor(h.context.current.workflow.steps[0]);
  const saving = h.submitDraft('A 저장');
  assert.equal(h.apiCalls.length, 1);
  h.context.current = h.makeJob('B');
  h.workflow.leave();
  h.workflow.openEditor(null);
  h.node('wf-title').value = 'B 작성 중';
  h.context.pending[0].resolve({workflow: {steps: []}, version: 8});
  await saving;
  assert.equal(h.node('workflow-editor').open, true);
  assert.equal(h.node('wf-title').value, 'B 작성 중');
}

async function testCancelAndReopenSameJobKeepsNewDraft() {
  const h = harness();
  h.context.current = h.makeJob('A');
  h.workflow.openEditor(h.context.current.workflow.steps[0]);
  const saving = h.submitDraft('이전 저장');
  h.workflow.leave();
  h.workflow.openEditor(h.context.current.workflow.steps[0]);
  h.node('wf-title').value = '새로 작성 중';
  h.context.pending[0].resolve({workflow: {steps: []}, version: 8});
  await saving;
  assert.equal(h.node('workflow-editor').open, true);
  assert.equal(h.node('wf-title').value, '새로 작성 중');
}

async function testSaveUsesCapturedRevisionAndDataVersion() {
  const h = harness();
  h.context.current = h.makeJob('A', 4, 12);
  h.workflow.openEditor(h.context.current.workflow.steps[0]);
  h.context.current.workflow.revision = 9;
  h.context.current.version = 27;
  const saving = h.submitDraft('저장');
  const payload = h.apiCalls[0][2];
  assert.equal(payload.revision, 4);
  assert.equal(payload.data_version, 12);
  h.context.pending[0].resolve({workflow: {steps: []}, version: 28});
  await saving;
}

async function testCrossJobSubmitIsRejectedBeforeRequest() {
  const h = harness();
  h.context.current = h.makeJob('A');
  h.workflow.openEditor(h.context.current.workflow.steps[0]);
  h.context.current = h.makeJob('B');
  await h.submitDraft('A의 수정 내용');
  assert.equal(h.apiCalls.length, 0);
}

async function testHandoffPrefillsOriginalTextWithoutCreatingJob() {
  const text = '각 부서 교육 참석 희망자를 취합해 주세요. 원문 표현 그대로 전달합니다.';
  const h = harness({handoff: {text}});
  h.workflow.init();
  assert.equal(h.node('situation').value, text);
  assert.equal(h.apiCalls.length, 0);
  assert.equal(h.context.current, null);
}

(async () => {
  for (const test of [testDelayedSaveCannotReplaceOtherJobDraft, testCancelAndReopenSameJobKeepsNewDraft,
    testSaveUsesCapturedRevisionAndDataVersion, testCrossJobSubmitIsRejectedBeforeRequest, testHandoffPrefillsOriginalTextWithoutCreatingJob]) {
    await test();
    console.log(`PASS ${test.name}`);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
