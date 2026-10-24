"use strict";
let registeredTemplates=[],inspectedFile=null,inspectedSheets=null,previewedHeaders=null,headerPreviewSequence=0;
const columnRoles={department:'부서',name:'성명·대상 이름',rank:'직급',course:'교육명',date:'교육일',wish:'참석 희망'};
async function loadTemplates(){
 registeredTemplates=await api('/templates');const previous=$('job-template').value;
 $('job-template').innerHTML='<option value="">기본 교육 참석 희망자 서식</option>'+registeredTemplates.map(t=>`<option value="${esc(t.id)}">${esc(t.institution)} / ${esc(t.name)} / ${esc(t.version_label)}</option>`).join('');
 if(registeredTemplates.some(t=>t.id===previous))$('job-template').value=previous;paintTemplateChoice();
 $('template-list').innerHTML=registeredTemplates.map(t=>`<article class="adhoc-file"><strong>${esc(t.institution)} · ${esc(t.name)}</strong><span class="tag">${esc(t.version_label)}</span><p class="help">${esc(t.config.sheet_name)} · 제목 ${headerRange(t.config)}행 · 데이터 ${t.config.data_start}행부터 ${t.config.data_end||'시트 끝'}까지 · ${t.config.headers.length}열 · 한 건 ${t.config.record_rows||1}행 · ${t.config.kind==='education'?'교육 명단':'일반 표 자료'}</p><p class="help">${t.config.headers.map(esc).join(' / ')}</p><div class="toolbar"><button class="secondary use-template" data-template="${t.id}">이 서식으로 업무 만들기</button><a href="/api/adhoc/templates/${t.id}/original">등록 원본 내려받기</a></div><details><summary>연결 기준·원본 해시</summary><pre class="task-note">${esc(JSON.stringify({record_rows:t.config.record_rows||1,group_columns:t.config.group_columns||{},roles:t.config.roles,required:t.config.required.map(i=>t.config.headers[i]),duplicate_keys:t.config.duplicate_keys.map(i=>t.config.headers[i]),header_merges:t.config.header_merges||[],column_spans:t.config.column_spans||[],fill_merged_columns:(t.config.fill_merged_columns||[]).map(i=>t.config.headers[i]),ignored_sheets:t.config.ignored_sheets,sha256:t.sha256},null,2))}</pre></details></article>`).join('')||'<p class="empty">아직 등록한 기관 취합 서식이 없습니다.</p>';
 for(const b of document.querySelectorAll('.use-template'))b.onclick=()=>{$('job-template').value=b.dataset.template;paintTemplateChoice();location.hash='new';};
}
function paintTemplateChoice(){const t=registeredTemplates.find(t=>t.id===$('job-template').value),generic=t?.config.kind==='generic';$('course-label').textContent=generic?'취합 자료명':'교육명';$('date-label').textContent=generic?'자료 기준일':'교육일';$('job-template-info').textContent=t?`${t.config.sheet_name} 시트 · 제목 ${headerRange(t.config)}행 · 데이터 ${t.config.data_start}행부터 · ${t.config.headers.length}열 · 한 건 ${t.config.record_rows||1}행. 이 서식 버전은 업무에 고정하여 저장합니다.`:'기본 6개 열의 교육 참석 희망자 서식입니다.';}
$('job-template').onchange=paintTemplateChoice;
$('template-file').onchange=()=>{inspectedFile=null;inspectedSheets=null;previewedHeaders=null;++headerPreviewSequence;$('template-form').hidden=true;$('template-status').textContent='시트·제목 행 확인을 눌러 주세요.';};
guarded($('inspect-template'),async()=>{
 const file=$('template-file').files[0];if(!file)throw Error('등록할 XLSX를 선택하세요.');const body=new FormData();body.set('file',file);
 const result=await api('/templates/inspect','POST',body);if($('template-file').files[0]!==file)return;
 inspectedFile=file;inspectedSheets=result.sheets;$('template-sheet').innerHTML=result.sheets.map(s=>`<option>${esc(s.name)}</option>`).join('');$('template-form').hidden=false;$('template-status').textContent=`${result.sheets.length}개 시트를 확인했습니다. 취합할 영역을 선택하세요.`;paintHeaderChoices();
});
function paintHeaderChoices(){const s=inspectedSheets?.find(s=>s.name===$('template-sheet').value);if(!s)return;$('template-header').innerHTML=s.preview.map((row,i)=>`<option value="${i+1}">${i+1}행 · ${esc(row.filter(Boolean).join(' / ').slice(0,160)||'(빈 행)')}</option>`).join('');$('template-header-end').value=$('template-header').value;paintColumns();}
async function paintColumns(){
 $('template-confirm').checked=false;previewedHeaders=null;const seq=++headerPreviewSequence;
 const file=inspectedFile,first=Number($('template-header').value),last=Number($('template-header-end').value),sheet=$('template-sheet').value;
 $('template-columns').replaceChildren();$('header-preview-summary').textContent='병합과 다단 제목을 확인하고 있습니다.';
 if(!file||!Number.isInteger(last)||last<first||last>50||last-first>=10){$('header-preview-summary').textContent='제목 시작 행부터 최대 10행 이내의 끝 행을 지정하세요.';return;}
 $('template-start').value=last+1;
 const body=new FormData();body.set('file',file);body.set('sheet_name',sheet);body.set('header_row',first);body.set('header_end',last);
 let result;
 try{result=await api('/templates/header-preview','POST',body);}catch(error){if(seq===headerPreviewSequence)$('header-preview-summary').textContent=error.message;return;}
 if(seq!==headerPreviewSequence||file!==inspectedFile)return;
 previewedHeaders=result;const headers=result.headers;
 $('header-preview-summary').textContent=`제목 ${first}~${last}행 · 병합 ${result.header_merges.length}곳 → ${headers.length}개 열. 상·하위 제목 연결과 열 의미를 확인하세요.`;
 const aliases={department:['부서','부서명','소속','소속부서'],name:['성명','이름','참석자'],rank:['직급','직위'],course:['교육명','교육과정','과정명'],date:['교육일','교육일자'],wish:['참석 희망','참석여부','희망여부']};
 $('template-columns').innerHTML=headers.map((h,i)=>{const leaf=result.header_paths[i].at(-1);const role=Object.keys(aliases).find(k=>aliases[k].some(a=>a.replace(/\s/g,'')===leaf.replace(/\s/g,'')))||'';return `<div class="template-column" data-column="${i}"><strong>${i+1}. ${esc(h)}</strong><label>열 의미<select class="column-role"><option value="">일반 열 · 원래 이름 유지</option>${Object.entries(columnRoles).map(([k,n])=>`<option value="${k}" ${k===role?'selected':''}>${n}</option>`).join('')}</select></label><label>자료 형식<select class="column-type"><option value="text">문자 · 번호 앞 0 유지</option><option value="number">숫자</option><option value="date" ${role==='date'?'selected':''}>날짜 · YYYY-MM-DD</option></select></label><label class="checkbox"><input type="checkbox" class="column-required" ${role&&role!=='rank'?'checked':''}> 필수값</label><label class="checkbox"><input type="checkbox" class="column-duplicate"> 중복 기준</label><label class="checkbox"><input type="checkbox" class="column-merged-fill"> 세로 공통값 펼침</label><label class="column-group-label">묶음 안 읽기<select class="column-group"></select></label></div>`;}).join('');paintGroupChoices();
}
$('template-sheet').onchange=paintHeaderChoices;$('template-header').onchange=()=>{$('template-header-end').value=$('template-header').value;paintColumns();};$('template-header-end').oninput=paintColumns;
$('template-form').addEventListener('input',e=>{if(e.target.id!=='template-confirm')$('template-confirm').checked=false;});
guarded($('template-form'),async()=>{
 if(!inspectedFile||$('template-file').files[0]!==inspectedFile)throw Error('파일을 다시 확인하세요.');
 const columns=[...document.querySelectorAll('.template-column')];if(!columns.length||!previewedHeaders||previewedHeaders.header_row!==Number($('template-header').value)||previewedHeaders.header_end!==Number($('template-header-end').value))throw Error('제목 범위의 미리보기 확인을 마친 뒤 등록하세요.');
 const roles={},required=[],duplicate_keys=[],column_types={},fill_merged_columns=[],group_columns={};
 for(const el of columns){const i=Number(el.dataset.column);if(Number($('template-record-rows').value)>1)group_columns[i]=el.querySelector('.column-group').value;const role=el.querySelector('.column-role').value;if(role){if(role in roles)throw Error('같은 열 의미를 두 열에 연결할 수 없습니다.');roles[role]=i;}column_types[i]=el.querySelector('.column-type').value;if(el.querySelector('.column-required').checked)required.push(i);if(el.querySelector('.column-duplicate').checked)duplicate_keys.push(i);if(el.querySelector('.column-merged-fill').checked)fill_merged_columns.push(i);}
 const spec={record_rows:Number($('template-record-rows').value),group_columns,institution:$('template-institution').value,name:$('template-name').value,version_label:$('template-version').value,kind:$('template-kind').value,sheet_name:$('template-sheet').value,header_row:Number($('template-header').value),header_end:Number($('template-header-end').value),fill_merged_columns,data_start:Number($('template-start').value),data_end:$('template-end').value?Number($('template-end').value):null,roles,column_types,required,duplicate_keys,positive:$('template-positive').value,negative:$('template-negative').value,selected_area_confirmed:$('template-confirm').checked};
 const body=new FormData();body.set('file',inspectedFile);body.set('metadata',JSON.stringify(spec));const result=await api('/templates','POST',body);await loadTemplates();$('job-template').value=result.id;paintTemplateChoice();$('template-status').textContent='서식 원본과 연결 기준을 버전별로 저장했습니다. 아래에서 이 서식으로 업무를 만들 수 있습니다.';message('기관 취합 서식을 등록했습니다. 새 업무에서 사용할 수 있습니다.');
},'submit');
loadTemplates().catch(e=>message('등록 서식 조회 실패: '+e.message,true));

function paintGroupChoices(){
 const size=Number($('template-record-rows').value);
 for(const el of document.querySelectorAll('.column-group')){const prev=el.value;el.innerHTML='<option value="consistent">공통값 확인 · 서로 다르면 거절</option><option value="join">여러 값 합치기 · 줄바꿈 유지</option>'+Array.from({length:Math.max(0,Math.min(20,size))},(_,i)=>`<option value="row:${i}">묶음의 ${i+1}번째 행만 읽기</option>`).join('');if([...el.options].some(o=>o.value===prev))el.value=prev;el.closest('label').hidden=size===1;}
 paintGroupSummary();
}
function paintGroupSummary(){
 const size=Number($('template-record-rows').value),start=Number($('template-start').value),end=Number($('template-end').value);
 $('group-preview-summary').textContent=size>1?`묶음 예: ${start}~${start+size-1}행 → 한 건, ${start+size}~${start+2*size-1}행 → 다음 건. `+(!end||(end-start+1)%size?'끝 행을 지정하고 전체 행 수를 묶음 크기의 배수로 맞추세요.':`${(end-start+1)/size}개 묶음 영역 · 빈 묶음 제외. 공통값 열의 빈칸은 허용하되 서로 다른 값은 거절합니다.`):'한 행을 한 건으로 취합합니다.';
}
$('template-record-rows').oninput=paintGroupChoices;$('template-start').oninput=paintGroupSummary;$('template-end').oninput=paintGroupSummary;
