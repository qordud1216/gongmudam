"use strict";
const byId=id=>document.getElementById(id),escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let aiOptions=null;
const aiRuns=[];
async function aiApi(path,body){const r=await fetch('/api/local-ai'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'입력값을 확인하세요.');return d;}
function renderAiResult(d,reveal=false){
 if(d.scenario_id){aiRuns.push(d);renderAiSummary();}
 const r=d.result,p=r.plan||{},steps=p.steps||[];
 const card=document.createElement('article');card.className='work-case';
 card.innerHTML=`<div class="tx-top"><h3>${escape(d.requested_model||d.test)}</h3><span class="pill ${d.passed?'green':'amber'}">${d.passed?'검증 항목 통과':'확인 필요'}</span></div><p>응답 모델: ${escape(d.response_model||'실제 모델 응답 없음')} · ${d.elapsed_seconds}초 · 모드 ${escape(r.mode)}</p><p><b>${escape(p.card?.title||'선택된 절차 없음')}</b></p><p>${escape(r.summary)}</p>${r.notice?`<p class="flag">${escape(r.notice)}</p>`:''}<ol>${steps.map(s=>`<li><b>${escape(s.title)}</b> · ${escape(s.due_text||'기한 확인 필요')}<br>필요 서식: ${(s.forms||[]).map(f=>escape(f.name)).join(', ')||'등록된 서식 없음'}<br>근거: ${(s.basis||[]).map(b=>escape(b.title+' '+b.label)).join(', ')||'근거 확인 필요'}</li>`).join('')}</ol>${d.checks?`<p>검사: ${Object.entries(d.checks).map(([k,v])=>escape(k)+': '+(v?'통과':'실패')).join(' · ')}</p>`:''}<details><summary>실제 요청·응답 및 검증 기록 · 원문은 미검토 자료</summary><pre>${escape(JSON.stringify(d,null,2))}</pre></details>`;
 byId('ai-results').prepend(card);
 if(reveal){const details=byId('ai-results').closest('details');if(details)details.open=true;card.tabIndex=-1;card.focus({preventScroll:true});card.scrollIntoView({block:'start',behavior:'auto'});}
}
function busy(value){for(const id of ['ai-run','ai-both','ai-failure'])byId(id).disabled=value;}
async function perform(profile,scenario){byId('ai-message').textContent=profile+' 실제 모델 응답을 기다리고 있습니다.';const d=await aiApi('/run',{profile,scenario});renderAiResult(d,true);return d;}
async function action(fn){busy(true);try{await fn();byId('ai-message').textContent='실행을 마쳤습니다. 실제 모델명·절차·서식·근거와 검증 항목을 확인하세요.';}catch(e){byId('ai-message').textContent='실행 실패: '+e.message;}finally{busy(false);}}
byId('ai-run').onclick=()=>action(()=>perform(byId('ai-profile').value,byId('ai-scenario').value));
byId('ai-both').onclick=()=>action(async()=>{for(const model of ['gemma3:4b','llama3.2:3b']){const p=aiOptions.profiles.find(p=>p.model===model);if(!p)throw Error(model+' 프로필이 없습니다.');byId('ai-profile').value=p.id;await perform(p.id,byId('ai-scenario').value);}});
byId('ai-failure').onclick=()=>action(async()=>renderAiResult(await aiApi('/failure-check',{}),true));
byId('ai-scenario').onchange=()=>{byId('ai-query').textContent=aiOptions.scenarios.find(s=>s.id===byId('ai-scenario').value)?.query||'';};
(async()=>{try{aiOptions=await aiApi('/options');byId('ai-profile').innerHTML=aiOptions.profiles.map(p=>`<option value="${escape(p.id)}">${escape(p.model)} · ${escape(p.id)}</option>`).join('');byId('ai-profile').value=aiOptions.profiles.find(p=>p.model==='gemma3:4b')?.id||aiOptions.profiles[0]?.id;byId('ai-scenario').innerHTML=aiOptions.scenarios.map(s=>`<option value="${s.id}">${escape(s.title)}</option>`).join('');byId('ai-scenario').onchange();byId('ai-environment').innerHTML=`<p>Ollama ${escape(aiOptions.ollama_version||'연결 확인 필요')}</p>`+aiOptions.installed_models.map(m=>`<p><b>${escape(m.name)}</b> · ${(m.size/1024**3).toFixed(2)}GiB · ${escape(m.details?.quantization_level)}<br>다운로드 해시 ${escape(m.digest)}</p>`).join('');byId('ai-message').textContent=aiOptions.notice;
try{const saved=await fetch('local-ai-evidence.json').then(r=>r.ok?r.json():null);if(saved){for(const r of saved.runs)renderAiResult(r);byId('ai-message').textContent='저장한 실제 검증 결과를 표시합니다. 새 실행 버튼으로 재현할 수 있습니다.';}}catch{}
}catch(e){byId('ai-message').textContent=e.message;}})();

function renderAiSummary(){
 const latest={};for(const r of aiRuns)latest[r.scenario_id+':'+r.requested_model]=r;
 byId('ai-summary').innerHTML='<table style="width:100%;border-collapse:collapse;text-align:left"><thead><tr><th>합성 업무</th><th>Gemma 3 4B</th><th>Llama 3.2 3B</th></tr></thead><tbody>'+['travel','leave','purchase'].map(key=>'<tr>'+`<td style="padding:14px 4px">${escape(aiOptions?.scenarios.find(s=>s.id===key)?.title||key)}</td>`+['gemma3:4b','llama3.2:3b'].map(model=>{const r=latest[key+':'+model];return `<td style="padding:14px 4px">${r?(r.passed?'실제 구동 통과':'확인 필요')+' · '+r.elapsed_seconds+'초':'미실행'}</td>`;}).join('')+'</tr>').join('')+'</tbody></table><p class="help">실제 LLM 응답과 카드 선택을 확인한 결과입니다. 근거 ID가 틀리면 앱에서 제외하며 원문 기록에 남깁니다. 연가 사례에는 등록된 서식이 없어 서식 검사는 해당 없음입니다.</p>';
}
