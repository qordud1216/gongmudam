// 브라우저 전달 데이터의 만료·일회성·임의 입력 보존 확인. 앱 실행에는 Node가 필요 없다.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const storage=new Map();let now=10000000;
const context={window:{},Date:{now:()=>now},sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)}};
vm.runInNewContext(fs.readFileSync('static/workspace-flow.js','utf8'),context);
const flow=context.window.SeomuFlow;
assert(flow.write('travel',{text:'<script>입력문장 {{기관명}}</script>',today:'2026-10-19'}));
const input=flow.take('travel');assert.equal(input.text,'<script>입력문장 {{기관명}}</script>');assert.equal(input.today,'2026-10-19');
assert.equal(flow.take('travel'),null);
assert(flow.write('question',{text:'검증 문장'}));now+=31*60*1000;assert.equal(flow.take('question'),null);
storage.set('seomu-flow:question','bad json');assert.equal(flow.take('question'),null);
storage.set('seomu-flow:question',JSON.stringify({text:'미래 기록',created_at:now+120000}));assert.equal(flow.take('question'),null);
assert.equal(flow.write('question',{text:'x'.repeat(3001)}),false);
assert.equal(flow.write('question',{text:'  '}),false);
assert(flow.write('question',{text:'새 문장',today:'not-a-date'}));assert.equal(flow.take('question').today,null);
assert(flow.write('question',{text:'첫 화면 질문',auto_submit:true}));assert.equal(flow.take('question').auto_submit,true);
assert.equal(flow.take('question'),null); // Refresh must not trigger another model call.
assert(flow.write('question',{text:'이전 방식의 초안'}));assert.equal(flow.take('question').auto_submit,false);
assert(flow.write('question',{text:'문자열 플래그',auto_submit:'true'}));assert.equal(flow.take('question').auto_submit,false);
console.log('Workspace transfer checks passed: literal text, once-only, expiry, malformed/future data, length, empty text, date validation.');
