"use strict";
(()=>{
 const allowed=/\.(txt|md|csv|xlsx|docx|hwpx|pdf)$/i;
 const selectedFiles=new Map();let skipped=0;
 const input=$('folder-upload-input'),summary=$('folder-upload-summary');
 function paint(){const files=[...selectedFiles.values()],total=files.reduce((s,f)=>s+f.size,0);summary.textContent=`선택 ${files.length}개 · ${(total/1024/1024).toFixed(2)}MB${skipped?` · 숨김·미지원 파일 ${skipped}개 제외`:''} — ${[...new Set([...selectedFiles.keys()].map(p=>p.split('/')[0]))].join(', ')}`;$('folder-upload-submit').disabled=!files.length;}
 $('folder-upload-pick').onclick=()=>input.click();
 $('folder-upload-clear').onclick=()=>{selectedFiles.clear();skipped=0;input.value='';paint();};
 input.onchange=()=>{for(const f of input.files){const path=f.webkitRelativePath||f.name;if(!allowed.test(path)||path.split('/').some(p=>p.startsWith('.'))){skipped++;continue;}selectedFiles.set(path,f);}input.value='';paint();};
 $('folder-upload-form').onsubmit=e=>{e.preventDefault();run(async()=>{
   const files=[...selectedFiles.entries()];if(!files.length)throw Error('업로드할 폴더를 먼저 선택하세요.');
   if(files.length>100||files.some(([,f])=>f.size>5*1024*1024)||files.reduce((s,[,f])=>s+f.size,0)>10*1024*1024)throw Error('파일 최대 100개·파일당 5MB·전체 10MB까지 선택하세요.');
   const data=new FormData();data.append('name',$('upload-library-name').value);data.append('paths',JSON.stringify(files.map(([p])=>p)));data.append('situation',$('folder-situation').value);data.append('public_consent',String($('upload-public-consent').checked));
   for(const [,f] of files)data.append('files',f,f.name);
   message('선택한 폴더 자료를 업로드하고 업무 단서를 읽고 있습니다.');
   const r=await fetch('/api/folders/uploads',{method:'POST',body:data});const v=await r.json();if(!r.ok)throw Error(typeof v.detail==='string'?v.detail:'업로드 내용을 확인하세요.');
   render(v);location.hash=v.id;await list();selectedFiles.clear();skipped=0;paint();message(v.import_notice);
 }).finally(paint);};
 async function pick(target){await run(async()=>{
   message('Windows 폴더 선택 창에서 업무 폴더를 고르세요. 취소하면 연결하지 않습니다.');
   const v=await api('/choose-local','POST',{});if(v.cancelled){message('폴더 선택을 취소했습니다.');return;}
   const field=$(target),values=roots(field.value);if(!values.includes(v.path))values.push(v.path);field.value=values.join('\n');message('선택한 폴더를 넣었습니다. 폴더 구성 확인 후 연결·재분석 버튼을 누르세요.');
 });}
 for(const b of document.querySelectorAll('[data-pick-folder]'))b.onclick=()=>pick(b.dataset.pickFolder);
 const local=['127.0.0.1','localhost','[::1]'].includes(location.hostname);
 if(!local){$('local-folder-options').hidden=true;$('folder-upload-options').open=true;for(const b of document.querySelectorAll('[data-pick-folder]'))b.hidden=true;}
 fetch('/api/public-demo/status').then(r=>r.ok?r.json():null).then(v=>{if(!v)return;$('upload-public-notice').hidden=false;$('upload-public-consent').required=true;$('local-folder-options').hidden=true;$('folder-upload-options').open=true;for(const b of document.querySelectorAll('[data-pick-folder]'))b.hidden=true;}).catch(()=>{});
 paint();
})();
