const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const test=require('node:test'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
function harness(){
 const nodes=new Map(),calls=[],answers=[];
 function node(){return {value:'',textContent:'',innerHTML:'',disabled:false,isConnected:true,scrollTop:0,scrollHeight:10,classList:{add(){},remove(){}},setAttribute(){},addEventListener(){},prepend(){},getBoundingClientRect(){return {top:0}},querySelector(){return null}};}
 const select=(s,el)=>{if(el)return el.querySelector(s);if(!nodes.has(s))nodes.set(s,node());return nodes.get(s)};
 select('#knowledge-library').selectedOptions=[{textContent:'전체 등록 자료'}];select('#today').value='2026-10-24';
 const c={window:{},document:{createElement:node},console,URL,location:{href:''},$:select,$$:()=>[],esc:String,layers:()=>['공통'],addMsg:()=>node(),renderAnswer:(box,res)=>answers.push(res),api:async(method,url,body)=>{calls.push(body);return {query:body.query,mode:'source_search',summary:'정산 규정 안내',alternatives:[],cited:[],related:[],personal_notes:[]}}};
 vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(root,'static/task-links.js'),'utf8'),c);
 const source=fs.readFileSync(path.join(root,'static/app.js'),'utf8');
 vm.runInContext(source.slice(source.indexOf('const chatRequests ='),source.indexOf('\nfunction renderAnswer('))+'\nthis.requests=chatRequests;',c);
 const flush=()=>new Promise(resolve=>setImmediate(resolve));
 return {c,calls,answers,async send(q,opts){assert.equal(c.requests.send(q,opts),true);await flush()},clear(){c.requests.clear()}};
}
test('follow-up travels through deterministic guidance with user context',async()=>{
 const h=harness(),trip='광주광역시로 2박 3일 출장다녀왔어 개인차량사용했고 숙박은 2박했어';
 await h.send(trip);await h.send('정산하게 도와줘');
 assert.equal(h.calls.length,2);assert.equal(h.calls[1].guidance,true);assert.equal(h.calls[1].use_ai,false);assert(h.calls[1].situation_context.includes(trip));assert.equal(h.calls[1].query,'정산하게 도와줘');
});
test('clear drops prior facts and AI is opt-in per request',async()=>{
 const h=harness();await h.send('광주로 출장다녀왔어');h.clear();await h.send('정산하게 도와줘');assert.equal(h.calls[1].situation_context,'');
});
test('explicit procedure selection retains legacy request flow',async()=>{
 const h=harness();await h.send('출장정산 도와줘',{cardId:'card-travel'});assert.equal(h.calls.length,1);assert.equal(h.calls[0].guidance,false);
});
test('task helper does not synthesize answers or bypass registered sources',()=>{
 const h=harness();assert.equal(h.c.window.SeomuTaskLinks.prepare('출장 정산 도와줘'),null);
});
test('trip extraction prefills explicit vehicle and lodging without guessing dates',async()=>{
 const source=fs.readFileSync(path.join(root,'static/travel.js'),'utf8');
 const start=source.indexOf('guarded($("extract")'),end=source.indexOf('$("trip-form").onsubmit',start);
 for(const [text,vehicle,lodging] of [
  ['광주광역시로 2박 3일 출장다녀왔어 개인차량사용했고 숙박은 2박했어','개인차량','true'],
  ['부산 당일 출장 관용차 사용','관용차','false'],
  ['개인차량 이용 안 했어 출장 숙박 안 했어','기타','false'],
  ['출장 개인차량과 철도를 함께 이용했어','기타','false']
 ]){
  const fields=new Map(),get=id=>{if(!fields.has(id))fields.set(id,{value:'',textContent:''});return fields.get(id)};
  get('situation').value=text;get('transport').value='기타';get('overnight').value='false';
  const c={$:get,guarded:(el,fn)=>{c.run=fn},notify(){},api:async()=>({intent:'travel_settlement',fields:{},notice:'확인'})};
  vm.createContext(c);vm.runInContext(source.slice(start,end),c);await c.run();
  assert.equal(get('transport').value,vehicle,text);assert.equal(get('overnight').value,lodging,text);assert.equal(get('start-date').value,'');assert.equal(get('end-date').value,'');
 }
});

