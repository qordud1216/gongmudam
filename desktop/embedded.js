(() => {
  'use strict';
  if (window.parent === window) return;
  let profile = null;
  let pending = null;
  let waitTimer = null;
  const origin = location.origin;
  const nativeFetch = window.fetch.bind(window);
  const labels = {national_public_official: '국가공무원', local_public_official: '지방공무원', other: '구분 확인 필요'};
  const appPages = new Set(['/index.html', '/travel.html', '/adhoc.html', '/folders.html', '/toolbox.html', '/change-inbox.html', '/calendar.html', '/local-ai.html']);
  const post = (message) => window.parent.postMessage(message, origin);

  function cleanProfile(value) {
    if (!value || value.confirmed !== true || !Object.hasOwn(labels, value.personnel_framework)) return null;
    return {personnel_framework: value.personnel_framework,
      organization: String(value.organization || '').slice(0, 300),
      department: String(value.department || '').slice(0, 80), region: String(value.region || '').slice(0, 40)};
  }
  function profileNote() {
    let banner = document.getElementById('gongmudam-context');
    if (!banner) {
      banner = document.createElement('p'); banner.id = 'gongmudam-context';
      banner.setAttribute('role', 'status'); document.body.prepend(banner);
    }
    banner.textContent = profile ? `${labels[profile.personnel_framework]} · ${profile.region} · ${profile.organization} — 질문에 함께 전달합니다. 출장 계산의 적용 기관·규정팩은 정산 화면에서 확인하세요.` : document.documentElement.dataset.gongmudamCloud === '1' ? '운영자 전용 클라우드 · 내 소속을 선택하면 질문에 함께 전달합니다.' : '공개 시연 · 누구나 같은 업무를 볼 수 있어요. 실제 개인정보와 업무자료를 입력하지 마세요.';
  }
  window.fetch = async (input, init) => {
    let url;
    try { url = new URL(typeof input === 'string' ? input : input.url, location.href); } catch { return nativeFetch(input, init); }
    const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (url.origin === origin && url.pathname === '/api/ask' && method === 'POST' && typeof init?.body === 'string' && profile) {
      try {
        const body = JSON.parse(init.body);
        if (typeof body.query === 'string' && body.guidance === true && !/(?:국가|지방)(?:공무원|직)|중앙부처|국가기관|지방자치단체/.test(body.query) && profile.personnel_framework !== 'other') {
          const context = `\n업무환경: ${labels[profile.personnel_framework]} · ${profile.region} · ${profile.organization}`;
          if (body.query.length + context.length <= 3000) body.query += context;
        }
        init = {...init, body: JSON.stringify(body)};
      } catch { /* The existing service will validate the unmodified request. */ }
    }
    const response = await nativeFetch(input, init);
    if (url.origin === origin && !['GET', 'HEAD', 'OPTIONS'].includes(method) && response.ok && url.pathname !== '/api/ask') post({type: 'gongmudam:changed'});
    return response;
  };

  function tryQuestion() {
    if (!pending) return;
    const input = document.getElementById('query');
    const button = document.getElementById('askBtn');
    const loaded = typeof S !== 'undefined' && S.settings;
    if (typeof window.sendAsk === 'function' && input && button && loaded) {
      const question = pending; pending = null;
      clearTimeout(waitTimer);
      if (input.value.trim() && input.value.trim() !== question.text) {
        post({type: 'gongmudam:question-status', requestId: question.requestId, status: 'busy'}); return;
      }
      if (typeof window.showView === 'function') window.showView('chat');
      input.value = question.text;
      const sent = window.sendAsk(question.text);
      if (sent) input.value = '';
      post({type: 'gongmudam:question-status', requestId: question.requestId, status: sent ? 'sent' : 'busy'});
      return;
    }
    if (Date.now() - pending.at > 15000) {
      post({type: 'gongmudam:question-status', requestId: pending.requestId, status: 'error'}); pending = null; return;
    }
    waitTimer = window.setTimeout(tryQuestion, 100);
  }
  window.addEventListener('message', (event) => {
    if (event.origin !== origin || event.source !== window.parent || !event.data) return;
    if (event.data.type === 'gongmudam:context') { profile = cleanProfile(event.data.profile); profileNote(); }
    if (event.data.type === 'gongmudam:question' && typeof event.data.text === 'string' && event.data.text.trim() && event.data.text.length <= 3000) {
      if (pending) { post({type: 'gongmudam:question-status', requestId: event.data.requestId, status: 'busy'}); return; }
      pending = {text: event.data.text.trim(), requestId: event.data.requestId, at: Date.now()}; tryQuestion();
    }
  });
  document.addEventListener('click', (event) => {
    const anchor = event.target.closest('a[href]');
    if (!anchor || anchor.hasAttribute('download') || event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
    const url = new URL(anchor.href, location.href);
    if (url.origin !== origin || !appPages.has(url.pathname) || (url.pathname === location.pathname && !url.search)) return;
    event.preventDefault(); post({type: 'gongmudam:open', href: url.pathname + url.search + url.hash});
  });
  function boot() {
    document.body.classList.add('gongmudam-embedded'); profileNote();
    post({type: 'gongmudam:ready'});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true}); else boot();
  window.addEventListener('pagehide', () => clearTimeout(waitTimer), {once: true});
})();
