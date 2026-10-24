"use strict";
(()=>{
 const key='folder-scan-job-id',contextKey='folder-scan-job-context',terminal=new Set(['completed','cancelled','failed','interrupted']);
 let activeId=null,timer=null,activeContext=null,lastPercent=null,pollGeneration=0;
 const $=id=>document.getElementById(id);
 const formatBytes=n=>`${Number(n||0).toLocaleString('ko-KR')}바이트`;
 function formSnapshot(){return JSON.stringify([...document.querySelectorAll('input,textarea,select')].map(el=>[el.id,el.type==='checkbox'||el.type==='radio'?el.checked:el.tagName==='SELECT'&&el.multiple?[...el.selectedOptions].map(o=>o.value):el.value]));}
 function contextSnapshot(){return {libraryId:current?.id||null,hash:location.hash,sequence:openSequence,form:formSnapshot()};}
 function canApply(ctx){return !!ctx&&ctx.hash===location.hash&&ctx.libraryId===(current?.id||null)&&(!Number.isInteger(ctx.sequence)||ctx.sequence===openSequence)&&(!ctx.form||ctx.form===formSnapshot());}
 function saveContext(ctx){try{sessionStorage.setItem(contextKey,JSON.stringify(ctx));}catch{}}
 function clearSaved(){try{sessionStorage.removeItem(key);sessionStorage.removeItem(contextKey);}catch{}}
 function show(job){
  const box=$('folder-scan-progress');box.hidden=false;box.dataset.status=job.status;$('folder-scan-retry').hidden=true;
  const names={queued:'대기 중',discovering:'폴더를 살펴보는 중',reading:'파일을 읽는 중',saving:'결과 저장 중'};
  $('folder-scan-title').textContent=job.status==='completed'?'폴더 읽기 완료':job.status==='cancelled'?'폴더 읽기를 취소했습니다':job.status==='failed'||job.status==='interrupted'?'폴더 읽기에 문제가 생겼습니다':'폴더 자료 읽기 진행';
  const meter=$('folder-scan-progress-meter');let percent=null;
  if(job.status==='completed')percent=100;
  else if(job.status==='cancelled'||job.status==='failed'||job.status==='interrupted')percent=lastPercent??0;
  else if(job.phase==='reading'&&Number(job.total)>0)percent=Math.min(100,Math.round(100*Number(job.processed||0)/job.total));
  if(percent===null){meter.removeAttribute('value');meter.setAttribute('aria-label','폴더 자료 읽기 진행 상태');}
  else{meter.value=percent;lastPercent=percent;meter.setAttribute('aria-label',job.status==='completed'?'폴더 읽기 완료':'파일 읽기 진행률');}
  const progress=job.total==null?`${Number(job.processed||0).toLocaleString('ko-KR')}개 처리`:`${Number(job.processed||0).toLocaleString('ko-KR')} / ${Number(job.total).toLocaleString('ko-KR')}개 처리`;
  const phaseLabel={completed:'완료',cancelled:'취소',failed:'실패',interrupted:'중단'}[job.status]||names[job.phase]||names[job.status]||'진행 중';
  $('folder-scan-status').textContent=`${phaseLabel} · 발견 ${Number(job.discovered||0).toLocaleString('ko-KR')}개 · ${progress} · 재사용 ${Number(job.reused||0).toLocaleString('ko-KR')}개 · 실패 ${Number(job.failed_files||0).toLocaleString('ko-KR')}개 · 제한 ${Number(job.limited_files||0).toLocaleString('ko-KR')}개 · 읽은 용량 ${formatBytes(job.bytes_read)} · 원본 총 용량 ${formatBytes(job.total_bytes)}`;
  $('folder-scan-file').textContent=job.current_file?`현재 파일: ${job.current_file} · ${formatBytes(job.current_bytes)}`:'';
  $('folder-scan-warning').textContent=[...(job.warnings||[]),job.error].filter(Boolean).join(' · ');
  $('folder-scan-cancel').disabled=terminal.has(job.status)||job.cancel_requested;
 }
 function finishTimer(){if(timer){clearTimeout(timer);timer=null;}pollGeneration++;}
 function clearTimerOnly(){if(timer){clearTimeout(timer);timer=null;}}
 function exposeResult(id){const a=$('folder-scan-result');a.href=`folders.html#${encodeURIComponent(id)}`;a.textContent='완료한 자료함 열기';a.hidden=false;}
 async function poll(id){if(id!==activeId)return;const generation=++pollGeneration;try{
  const job=await api(`/scan-jobs/${encodeURIComponent(id)}`);if(id!==activeId||generation!==pollGeneration)return;show(job);
  if(job.status==='completed'){clearTimerOnly();if(job.library_id){exposeResult(job.library_id);const library=await api(`/libraries/${encodeURIComponent(job.library_id)}`);if(id!==activeId||generation!==pollGeneration)return;if(canApply(activeContext)){render(library);if(location.hash!==`#${encodeURIComponent(library.id)}`)history.replaceState(null,'',`${location.pathname}${location.search}#${encodeURIComponent(library.id)}`);message('폴더 자료를 읽어 저장했습니다. 분류 제안과 확인할 내용을 살펴보세요.');}else{message('폴더 읽기가 끝났습니다. 현재 입력과 화면은 유지했습니다. 완료한 자료함을 열어 결과를 확인하세요.');}try{await list();}catch{}}else{message('폴더 읽기는 끝났지만 자료함 ID가 없습니다. 결과를 불러오지 못했습니다.',true);}activeId=null;clearSaved();activeContext=null;return;}
  if(terminal.has(job.status)){finishTimer();activeId=null;clearSaved();activeContext=null;message(job.error||($('folder-scan-warning').textContent||`폴더 읽기 작업이 ${job.status} 상태로 끝났습니다.`),true);return;}
  timer=setTimeout(()=>poll(id),500);
 }catch(e){if(id!==activeId||generation!==pollGeneration)return;finishTimer();$('folder-scan-progress').hidden=false;$('folder-scan-title').textContent='진행 상태를 불러오지 못했습니다';$('folder-scan-status').textContent=e.message;$('folder-scan-retry').hidden=false;$('folder-scan-cancel').disabled=false;}}
 async function start(options){
  if(activeId)throw Error('진행 중인 폴더 읽기 작업이 있습니다.');
  const ctx=contextSnapshot();
  const job=await api('/scan-jobs','POST',options);if(!job?.id)throw Error('서버가 폴더 읽기 작업 ID를 돌려주지 않았습니다.');
  $('folder-scan-result').hidden=true;activeId=job.id;activeContext=ctx;lastPercent=null;try{sessionStorage.setItem(key,activeId);saveContext(ctx);}catch{}show(job);poll(activeId);return job;
 }
$('folder-scan-cancel').onclick=async()=>{const id=activeId;if(!id)return;$('folder-scan-cancel').disabled=true;finishTimer();const generation=pollGeneration;try{const job=await api(`/scan-jobs/${encodeURIComponent(id)}/cancel`,'POST',{});if(id!==activeId||generation!==pollGeneration)return;show(job);timer=setTimeout(()=>poll(id),500);}catch(e){if(id!==activeId||generation!==pollGeneration)return;$('folder-scan-status').textContent=e.message;$('folder-scan-cancel').disabled=false;timer=setTimeout(()=>poll(id),500);}};
 $('folder-scan-retry').onclick=()=>{if(!activeId)return;$('folder-scan-retry').hidden=true;poll(activeId);};
 let saved=null;try{saved=sessionStorage.getItem(key);const raw=sessionStorage.getItem(contextKey);activeContext=raw?JSON.parse(raw):null;if(activeContext)activeContext.sequence=null;}catch{}
 if(saved){activeId=saved;poll(saved);}
 window.FolderScan={start};
})();
