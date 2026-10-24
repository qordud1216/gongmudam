const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict'),test=require('node:test'),path=require('path');
const root=path.resolve(__dirname,'..');
function startContext(){const c={};vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(root,'static/start.js'),'utf8').split('let startModelSnapshot')[0],c);return c;}
test('managed manual can open its registered references from start',()=>{
 const c=startContext();assert.equal(c.recentHref({kind:'folder',id:'esaram-manuals-v68'}),'folders.html?view=references#esaram-manuals-v68');
});
test('ordinary recent work links retained and untrusted links rejected',()=>{
 const c=startContext(),id='a'.repeat(32);
 assert.equal(c.recentHref({kind:'folder',id}),`folders.html#${id}`);
 assert.equal(c.recentHref({kind:'travel',id}),`travel.html?case=${id}#settle`);
 assert.equal(c.recentHref({kind:'education',id}),`adhoc.html#job-${id}`);
 for(const bad of ['../../secret','javascript:alert(1)','esaram-manuals-v68" onclick="x','esaram-manuals-v68/other','anything'])assert.equal(c.recentHref({kind:'folder',id:bad,href:'https://evil.example'}),'');
});
test('registered manual card offers original PDF without empty preview detour',async()=>{
 const nodes={};const byId=id=>nodes[id]??=( {innerHTML:'',textContent:''});
 const manual={id:'manual-abc',file_id:'abc',title:'<test> 매뉴얼.pdf',reference_kind:'system_manual',enabled:true,current:true,page_count:111,indexed_pages:111,kind:'업무편람',institution:'제공 파일',effective_date:'',sha256:'123'};
 const library={id:'esaram-manuals-v68',version:1,files:[],projects:[]};
 const c={current:library,$:byId,esc:x=>String(x??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])),document:{querySelectorAll:()=>[]},bind:()=>{},run:()=>{},message:()=>{},fetch:async url=>({ok:true,json:async()=>url.includes('/sources?')?[manual]:[]})};
 vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(root,'static/folder-knowledge.js'),'utf8'),c);await c.loadKnowledge(library);
 const html=byId('knowledge-sources').innerHTML;
 assert(html.includes('/api/knowledge/sources/manual-abc/original#page=1'));
 assert(html.includes('111/111'));assert(html.includes('&lt;test&gt;'));assert(!html.includes('<test>'));
 assert(html.includes('target="_blank"')&&html.includes('noopener'));
});
