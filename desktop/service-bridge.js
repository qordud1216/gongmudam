(() => {
  const routes = {
    chat: '/index.html#chat',
    travel: '/travel.html',
    collection: '/adhoc.html#inbox',
    folders: '/folders.html',
    toolbox: '/toolbox.html',
    inbox: '/change-inbox.html',
    calendar: '/calendar.html',
    models: '/local-ai.html',
  };
  const pageToApp = new Map([
    ['/index.html', 'chat'], ['/travel.html', 'travel'], ['/adhoc.html', 'collection'],
    ['/folders.html', 'folders'], ['/toolbox.html', 'toolbox'], ['/change-inbox.html', 'inbox'],
    ['/calendar.html', 'calendar'], ['/local-ai.html', 'models'],
  ]);

  function parseAllowedHref(href) {
    if (typeof href !== 'string' || !href.trim()) return null;
    try {
      const normalized = href.startsWith('/') ? href : `/${href}`;
      const url = new URL(normalized, location.origin);
      const id = url.origin === location.origin ? pageToApp.get(url.pathname) : null;
      return id ? { id, href: `${url.pathname}${url.search}${url.hash}` } : null;
    } catch { return null; }
  }

  function mount(body, id, options = {}) {
    const route = routes[id];
    if (!route) return null;
    body.classList.add('service-window-body');
    const shell = document.createElement('section'); shell.className = 'service-bridge';
    const toolbar = document.createElement('div'); toolbar.className = 'service-bridge-toolbar';
    const status = document.createElement('p'); status.className = 'service-bridge-status'; status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'service-bridge-retry'; retry.textContent = '다시 시도'; retry.hidden = true;
    const openFull = document.createElement('a'); openFull.className = 'service-bridge-full'; openFull.target = '_blank'; openFull.rel = 'noopener'; openFull.textContent = '새 탭에서 열기';
    toolbar.append(status, retry, openFull);
    const frame = document.createElement('iframe'); frame.className = 'service-bridge-frame'; frame.title = `${options.title || id} 서비스 화면`; frame.setAttribute('referrerpolicy', 'same-origin');
    shell.append(toolbar, frame); body.append(shell);

    let currentHref = parseAllowedHref(options.href || route)?.href || route;
    let ready = false; let disposed = false; let unavailable = false; let timeout = null;
    let profile = options.profile || null; let requestQueue = []; let inFlight = null;

    function setStatus(message, failed = false) {
      unavailable = failed; status.textContent = message; status.dataset.unavailable = String(failed); retry.hidden = !failed;
    }
    function updateFullLink() { openFull.href = currentHref; }
    function sendContext() {
      if (ready && !disposed) frame.contentWindow?.postMessage({ type: 'gongmudam:context', profile }, location.origin);
    }
    function sendNextQuestion() {
      if (!ready || disposed || inFlight || !requestQueue.length) return;
      inFlight = requestQueue[0];
      frame.contentWindow?.postMessage({ type: 'gongmudam:question', text: inFlight.text, requestId: inFlight.requestId }, location.origin);
    }
    function load(href = currentHref) {
      const allowed = parseAllowedHref(href); if (!allowed) { setStatus('열 수 없는 서비스 화면입니다.', true); return false; }
      currentHref = allowed.href; updateFullLink(); ready = false; inFlight = null;
      if (timeout) clearTimeout(timeout);
      setStatus('서비스 화면을 불러오는 중입니다.');
      frame.src = currentHref;
      timeout = window.setTimeout(() => {
        if (!ready && !disposed) setStatus('서비스 연결을 확인하지 못했습니다. 다시 시도하거나 새 탭에서 열어 주세요.', true);
      }, 15000);
      return true;
    }
    function onLoad() {
      if (!ready) setStatus('페이지가 열렸습니다. 서비스 연결을 확인하는 중입니다.');
    }
    function onFrameFocus() { options.onFocus?.(); }
    function onMessage(event) {
      if (disposed || event.source !== frame.contentWindow || event.origin !== location.origin) return;
      const data = event.data;
      if (!data || typeof data !== 'object' || typeof data.type !== 'string') return;
      if (data.type === 'gongmudam:ready') {
        ready = true; if (timeout) clearTimeout(timeout); timeout = null;
        setStatus('서비스 화면이 준비되었습니다.'); sendContext(); sendNextQuestion(); return;
      }
      if (!ready) return;
      if (data.type === 'gongmudam:open') {
        const target = parseAllowedHref(data.href);
        if (!target) { setStatus('허용되지 않은 서비스 화면 요청입니다.'); return; }
        options.onOpen?.(target.id, target.href); return;
      }
      if (data.type === 'gongmudam:changed') { options.onChanged?.(); return; }
      if (data.type === 'gongmudam:question-status' && typeof data.requestId === 'string') {
        const index = requestQueue.findIndex((request) => request.requestId === data.requestId);
        if (index < 0) return;
        if (data.status === 'sent') {
          requestQueue.splice(index, 1); if (inFlight?.requestId === data.requestId) inFlight = null;
          setStatus('질문을 서비스에 전달했습니다.'); sendNextQuestion();
        } else if (data.status === 'busy') {
          requestQueue.splice(index, 1); if (inFlight?.requestId === data.requestId) inFlight = null;
          setStatus('서비스가 다른 요청을 처리 중입니다. 잠시 후 다시 보내 주세요.'); sendNextQuestion();
        } else if (data.status === 'error') {
          requestQueue.splice(index, 1); if (inFlight?.requestId === data.requestId) inFlight = null;
          setStatus('질문을 전달하지 못했습니다. 서비스 화면에서 다시 시도해 주세요.'); sendNextQuestion();
        }
      }
    }
    function ask(value) {
      const text = typeof value === 'string' ? value.trim() : '';
      if (!text || disposed) return false;
      if (text.length > 3000) { setStatus('질문은 3,000자 이내로 입력해 주세요.'); return false; }
      const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      requestQueue.push({ requestId, text });
      if (ready) sendNextQuestion(); else setStatus('서비스 연결을 기다리는 동안 질문을 보관했습니다.', unavailable);
      return true;
    }
    function navigate(href) { return load(href); }
    function updateProfile(nextProfile) { profile = nextProfile || null; sendContext(); }
    function dispose() {
      if (disposed) return; disposed = true;
      if (timeout) clearTimeout(timeout);
      window.removeEventListener('message', onMessage);
      frame.removeEventListener('load', onLoad); frame.removeEventListener('focus', onFrameFocus);
      retry.removeEventListener('click', onRetry);
      frame.src = 'about:blank'; shell.remove();
    }
    function onRetry() { load(currentHref); }

    retry.addEventListener('click', onRetry);
    frame.addEventListener('load', onLoad); frame.addEventListener('focus', onFrameFocus);
    window.addEventListener('message', onMessage); updateFullLink(); load(currentHref);
    return { ask, navigate, updateProfile, dispose };
  }

  window.GongmudamServiceBridge = { mount, routes };
})();
