(() => {
  'use strict';
  fetch('/api/cloud/status', {cache: 'no-store'}).then(r => r.ok ? r.json() : null).then(state => {
    if (!state || state.mode !== 'operator-private-no-llm') return;
    document.documentElement.dataset.gongmudamCloud = '1';
    const context = document.getElementById('gongmudam-context');
    if (context?.textContent.startsWith('공개 시연')) context.textContent = '운영자 전용 클라우드 · 내 소속을 선택하면 질문에 함께 전달합니다.';
    const note = document.createElement('p');
    note.id = 'gongmudam-cloud-status';
    note.setAttribute('role', 'status');
    note.textContent = `${state.notice} 릴리즈 ${state.release_id.slice(0, 12)}`;
    note.style.cssText = 'margin:0;padding:8px 14px;background:#fff3cd;color:#453400;font:13px/1.5 sans-serif;position:relative;z-index:10000';
    document.body.prepend(note);
    document.addEventListener('click', event => {
      if (event.target.closest('[data-open="models"], [data-open="local-ai"]')) {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    }, true);
    document.querySelectorAll('[data-open="models"], [data-open="local-ai"]').forEach(button => {
      button.disabled = true;
      button.title = '현재 릴리즈는 LLM을 사용하지 않습니다.';
    });
  }).catch(() => {});
})();
