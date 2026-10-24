"use strict";
Object.assign(eventNames,{DOCUMENT_UPLOADED:"영수증 원본·추출문 보존",DOCUMENT_CONFIRMED:"원본 대조·수정 거래 반영",DOCUMENT_DISMISSED:"원본 보존·제외 사유 기록"});
guarded($("upload-receipt"),async()=>{
  const file=$("receipt-file").files[0];if(!file) throw Error("등록할 PDF·PNG·JPG 파일을 선택하세요.");
  if(file.size>10*1024*1024) throw Error("10MB 이하 파일을 선택하세요.");
  const form=new FormData();form.append("version",state.current.version);form.append("file",file);
  notify("파일을 읽고 있습니다. 이미지 OCR에는 잠시 시간이 걸릴 수 있습니다.");
  const response=await fetch(`/api/travel/cases/${state.current.id}/documents`,{method:"POST",body:form});
  const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"파일 형식과 입력값을 확인하세요.");
  renderCase(data);$("receipt-file").value="";
  notify(data.upload_result.duplicate?"동일 원본이 이미 등록되어 있습니다. 기존 확인 상태를 표시합니다.":"원본과 추출문을 저장했습니다. 거래 후보를 대조·수정한 뒤 반영하세요.");
});

function renderDocuments(c,caseChanged){
  const attachments=$("travel-work-attachments");
  if(window.WorkAttachments)WorkAttachments.mount(attachments,{kind:"travel",id:c.id,version:c.version});
  for(const link of document.querySelectorAll('a[data-toolbox-href],a[href="toolbox.html"],a[href^="toolbox.html#"]')){
    const href=link.dataset.toolboxHref||link.getAttribute("href");
    link.dataset.toolboxHref=href;
    const original=new URL(href,location.href);
    const destination=new URL("toolbox.html",location.href);
    destination.searchParams.set("work","travel");
    destination.searchParams.set("target",c.id);
    destination.hash=original.hash;
    link.href=destination.href;
    link.target="_blank";
    link.rel="noopener noreferrer";
  }
  const drafts={};
  if(!caseChanged) document.querySelectorAll(".receipt-document").forEach(el=>{
    if(el.querySelector(".receipt-text")) drafts[el.dataset.document]={text:el.querySelector(".receipt-text").value,reason:el.querySelector(".receipt-reason").value,checked:el.querySelector(".receipt-checked").checked};
  });
  if(caseChanged) $("receipt-file").value="";
  $("receipt-documents").innerHTML=(c.documents||[]).map(d=>{
    const status=!d.confirmed_at?"원본 대조 필요":d.confirmed_text?"거래 반영 완료 · 포함 여부 별도 검토":"사유 기록 · 제외";
    const draft=drafts[d.id];
    return `<article class="receipt-document" id="document-${d.id}" data-document="${d.id}"><div class="tx-top"><strong>${escapeHtml(d.filename)}</strong><span class="tag">${status}</span></div><p class="help">${Math.ceil(d.size/1024)}KB · ${escapeHtml(d.extraction.engine)} · 원본 SHA-256 ${escapeHtml(d.sha256)}</p><a href="${escapeHtml(d.original_url)}">보존 원본 다운로드</a>${d.preview_url?`<details class="receipt-preview"><summary>원본 이미지 보기</summary><img src="${escapeHtml(d.preview_url)}" alt="첨부한 영수증 원본" loading="lazy"></details>`:""}<details><summary>추출된 원문 · 쪽별 확인</summary>${d.extraction.pages.map(p=>`<b>${p.page}쪽</b><pre class="receipt-raw">${escapeHtml(p.text)}</pre>`).join("")||'<p class="help">추출된 텍스트가 없습니다. 원본을 보고 거래를 입력하세요.</p>'}</details>${d.extraction.warnings.map(w=>`<p class="flag">${escapeHtml(w)}</p>`).join("")}${!d.confirmed_at?`<label>대조·수정한 거래 · 한 줄에 한 건<textarea rows="3" class="receipt-text" placeholder="2026-10-15 08:14 코레일 52,300원 승인">${escapeHtml(draft?.text??d.suggested_text)}</textarea></label><label>원본 대조 또는 제외 사유<input class="receipt-reason" maxlength="500" value="${escapeHtml(draft?.reason||"")}" placeholder="예: 원본의 거래일·금액·취소 여부 대조"></label><label class="checkbox"><input class="receipt-checked" type="checkbox" ${draft?.checked?"checked":""}>원본의 날짜·시각·가맹점·금액·취소 여부를 확인했습니다</label><div class="toolbar"><button class="primary confirm-receipt">확인한 거래 반영</button><button class="secondary dismiss-receipt">이 파일 제외 · 사유 기록</button></div>`:`<p>확인 사유: ${escapeHtml(d.confirmation_reason)}</p>${d.confirmed_text?`<pre class="receipt-raw">${escapeHtml(d.confirmed_text)}</pre>`:""}`}</article>`;
  }).join("")||'<p class="empty">아직 첨부한 영수증이 없습니다.</p>';
  document.querySelectorAll(".receipt-document").forEach(el=>{
    if(!el.querySelector(".confirm-receipt"))return;
    guarded(el.querySelector(".confirm-receipt"),async()=>{
      const response=await api(`/cases/${c.id}/documents/${el.dataset.document}/confirm`,"POST",{version:state.current.version,text:el.querySelector(".receipt-text").value,original_checked:el.querySelector(".receipt-checked").checked,reason:el.querySelector(".receipt-reason").value});
      renderCase(response);notify(`${response.import_result.inserted}건을 보류 거래로 등록했습니다. 기존 거래 ${response.import_result.duplicates_skipped}건에는 원본만 연결했습니다. 포함·제외를 검토하세요.`);
    });
    guarded(el.querySelector(".dismiss-receipt"),async()=>{
      renderCase(await api(`/cases/${c.id}/documents/${el.dataset.document}/dismiss`,"POST",{version:state.current.version,reason:el.querySelector(".receipt-reason").value}));notify("원본을 보존하고 제외 사유를 이력에 기록했습니다.");
    });
  });
  document.querySelectorAll(".transaction").forEach((el,i)=>{
    const ids=c.review.transactions[i].document_ids||[];
    if(ids.length)el.insertAdjacentHTML("afterbegin",`<p class="help">연결된 원본: ${ids.map((id,n)=>`<a href="#document-${id}">첨부 ${n+1}</a>`).join(" · ")}</p>`);
  });
}
