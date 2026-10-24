document.addEventListener('DOMContentLoaded', () => {
  const area = document.querySelector('#desktop-area');
  const layer = document.querySelector('#window-layer');
  if (!area || !layer) return;

  const apps = new Map();
  document.querySelectorAll('.desktop-app[data-open], .taskbar-favorite[data-open], #profile-affiliation[data-open]').forEach((button) => {
    const id = button.dataset.open;
    if (id && !apps.has(id)) apps.set(id, {
      id,
      label: button.dataset.label || id,
      kind: button.dataset.kind || '',
      icon: button.querySelector('.app-symbol')?.cloneNode(true) || null,
    });
  });
  const serviceRoutes = window.GongmudamServiceBridge?.routes || {};
  const serviceLabels = { chat: '서무 안내', travel: '출장정산', collection: '자료 취합', folders: '업무자료 정리', toolbox: '업무도구함', inbox: '변경 알림함', calendar: '달력', models: '로컬 AI 설정' };
  Object.entries(serviceRoutes).forEach(([id]) => { if (!apps.has(id)) apps.set(id, { id, label: serviceLabels[id] || id, kind: 'service', icon: null }); });
  const recentWorkApps = new Set(['travel', 'collection', 'folders', 'toolbox', 'inbox']);
  let recentWorkRequest = null;
  let recentWorkSequence = 0;

  const windows = new Map();
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const comparisonEnabled = new URLSearchParams(location.search).get('compare') === '1';
  document.body.classList.toggle('approved-design', !comparisonEnabled);
  let zIndex = 10;
  let cascade = 0;
  let showDesktopWindowIds = [];
  let focusIndex = -1;
  let bIconPositions = null;
  let bLayoutSize = null;
  let suppressDraggedIconClick = false;
  let iconDragState = null;
  const profileStorageKey = 'seomu.desktopPreview.profile.v1';
  const frameworks = {
    national_public_official: '국가공무원',
    local_public_official: '지방공무원',
    other: '구분 확인 필요',
  };
  const regions = ['서울특별시', '부산광역시', '대구광역시', '인천광역시', '광주광역시', '대전광역시', '울산광역시', '세종특별자치시', '경기도', '강원특별자치도', '충청북도', '충청남도', '전북특별자치도', '전라남도', '경상북도', '경상남도', '제주특별자치도'];
  const affiliation = { schema_version: 2, personnel_framework: '', region: '', organization: '', department: '', agency: null, confirmed: false, saved_at: '' };
  let openAgencyPicker = null;
  const variantInfo = {
    A: ['서무 데스크', '명령 중심으로 자주 쓰는 업무를 빠르게 여는 구성입니다.'],
    B: ['업무 폴더', '아이콘을 끌어 배치하거나, 눌러 업무를 시작하세요'],
    C: ['모니터 데스크', '화면 프레임 안에 업무 공간을 담은 구성입니다.'],
  };

  function motionDelay(ms) { return reducedMotion.matches ? 0 : ms; }
  function getProfileFramework(scope) {
    return scope.querySelector('input[name="profile-framework"]:checked')?.value || '';
  }
  function clampIconPosition(button, position) {
    const bounds = area.getBoundingClientRect(); const rect = button.getBoundingClientRect();
    const width = rect.width || button.offsetWidth; const height = rect.height || button.offsetHeight;
    const shelf = document.querySelector('.work-shelf');
    const shelfRect = shelf?.getBoundingClientRect();
    const maxLeft = Math.max(0, Math.min(bounds.width - width,
      shelfRect && shelfRect.width > 0 ? shelfRect.left - bounds.left - width - 16 : bounds.width - width));
    return {
      left: Math.max(0, Math.min(position.left, maxLeft)),
      top: Math.max(0, Math.min(position.top, Math.max(0, bounds.height - height))),
    };
  }
  function applyBIconPositions() {
    const icons = [...area.querySelectorAll('.desktop-app[data-open]')];
    if (!icons.length) return;
    const bounds = area.getBoundingClientRect(); const size = { width: bounds.width, height: bounds.height };
    if (!bIconPositions || !bLayoutSize || (bLayoutSize.width > 700) !== (size.width > 700) || Math.abs(bLayoutSize.width - size.width) > Math.max(180, bLayoutSize.width * 0.35)) {
      clearBIconLayout();
      bIconPositions = new Map(icons.map((icon) => { const rect = icon.getBoundingClientRect(); return [icon.dataset.open, { left: rect.left - bounds.left, top: rect.top - bounds.top }]; }));
    }
    bLayoutSize = size;
    area.querySelector('.desktop-apps')?.classList.add('is-arranging');
    icons.forEach((icon) => {
      const point = clampIconPosition(icon, bIconPositions.get(icon.dataset.open) || { left: 20, top: 20 });
      bIconPositions.set(icon.dataset.open, point); icon.style.left = `${point.left}px`; icon.style.top = `${point.top}px`;
    });
  }
  function clearBIconLayout() {
    area.querySelector('.desktop-apps')?.classList.remove('is-arranging');
    area.querySelectorAll('.desktop-app[data-open]').forEach((icon) => { icon.style.removeProperty('left'); icon.style.removeProperty('top'); icon.classList.remove('is-dragging'); });
  }
  function installBIconDrag(icon) {
    icon.addEventListener('pointerdown', (event) => {
      if (document.body.dataset.variant !== 'B' || event.button !== 0 || event.target.closest('input, a, [data-open]:not(.desktop-app)')) return;
      const appsContainer = area.querySelector('.desktop-apps'); if (!appsContainer?.classList.contains('is-arranging')) return;
      const point = bIconPositions.get(icon.dataset.open); if (!point) return;
      iconDragState = { icon, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, startLeft: point.left, startTop: point.top, dragging: false };
      icon.setPointerCapture(event.pointerId);
      const move = (moveEvent) => {
        const state = iconDragState; if (!state || state.icon !== icon || state.pointerId !== moveEvent.pointerId) return;
        const dx = moveEvent.clientX - state.startX, dy = moveEvent.clientY - state.startY;
        if (!state.dragging && Math.hypot(dx, dy) < 6) return;
        if (!state.dragging) {
          state.dragging = true; icon.classList.add('is-dragging');
        }
        moveEvent.preventDefault();
        const point = clampIconPosition(icon, { left: state.startLeft + dx, top: state.startTop + dy });
        icon.style.left = `${point.left}px`; icon.style.top = `${point.top}px`; bIconPositions.set(icon.dataset.open, point);
      };
      const finish = (endEvent) => {
        const state = iconDragState; if (!state || state.icon !== icon || state.pointerId !== endEvent.pointerId) return;
        if (icon.hasPointerCapture(endEvent.pointerId)) icon.releasePointerCapture(endEvent.pointerId);
        if (state.dragging) {
          suppressDraggedIconClick = true; window.setTimeout(() => { suppressDraggedIconClick = false; }, 0);
          window.setTimeout(() => icon.classList.remove('is-dragging'), 0);
        }
        iconDragState = null;
        icon.removeEventListener('pointermove', move); icon.removeEventListener('pointerup', finish); icon.removeEventListener('pointercancel', finish);
      };
      icon.addEventListener('pointermove', move); icon.addEventListener('pointerup', finish); icon.addEventListener('pointercancel', finish);
    });
  }
  area.querySelectorAll('.desktop-app[data-open]').forEach(installBIconDrag);
  function appIcon(app) {
    if (app.icon) return app.icon.cloneNode(true);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', 'M4 5h16v14H4zM4 9h16');
    path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '1.7');
    svg.append(path); return svg;
  }
  function controlIcon(kind) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 16 16'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor'); path.setAttribute('stroke-width', '1.4');
    path.setAttribute('d', kind === 'minimize' ? 'M3 12h10' : kind === 'maximize' ? 'M3 3h10v10H3z' : kind === 'restore' ? 'M5 3h8v8M3 5v8h8' : 'M4 4l8 8M12 4l-8 8');
    svg.append(path); return svg;
  }
  function setControl(button, label, symbol) {
    button.type = 'button'; button.className = 'window-control'; button.title = label; button.setAttribute('aria-label', label);
    button.append(controlIcon(symbol));
  }
  function renderTaskbar() {
    const host = document.querySelector('#running-apps');
    if (!host) return;
    host.replaceChildren();
    for (const [id, state] of windows) {
      const app = apps.get(id); if (!app) continue;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'running-app'; button.dataset.task = id;
      button.title = app.label; button.setAttribute('aria-label', app.label);
      if (state.window.classList.contains('is-active')) button.classList.add('is-active');
      if (state.window.hidden) button.classList.add('is-minimized');
      button.append(appIcon(app)); const label = document.createElement('span'); label.textContent = app.label; button.append(label); host.append(button);
    }
    updatePrototypeState();
  }
  function updatePrototypeState() {
    const output = document.querySelector('#prototype-state'); if (!output) return;
    const minimized = [...windows.values()].filter((state) => state.window.hidden).length;
    const variant = document.body.dataset.variant || 'A';
    output.textContent = `공개 시연 · 열린 창 ${windows.size}개 · 최소화 ${minimized}개`;
  }
  function activate(state, focus = false) {
    if (state.minTimer) { clearTimeout(state.minTimer); state.minTimer = null; }
    windows.forEach((other) => other.window.classList.remove('is-active'));
    state.window.hidden = false; state.window.classList.remove('is-minimized', 'minimizing');
    state.window.classList.add('is-active'); state.window.style.zIndex = String(++zIndex);
    if (focus) state.window.focus({ preventScroll: true });
    renderTaskbar();
    if (state.service && recentWorkApps.has(state.id)) refreshRecentWork();
  }
  function clampWindow(state) {
    state.resizer?.cancel();
    const win = state.window; if (win.hidden || win.classList.contains('is-maximized')) return;
    const bounds = area.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    const rect = win.getBoundingClientRect();
    const width = Math.min(rect.width || parseFloat(win.style.width), bounds.width);
    const height = Math.min(rect.height || parseFloat(win.style.height), bounds.height);
    const left = Math.max(0, Math.min(parseFloat(win.style.left) || 0, bounds.width - width));
    const top = Math.max(0, Math.min(parseFloat(win.style.top) || 0, bounds.height - height));
    win.style.left = `${left}px`; win.style.top = `${top}px`;
    if (bounds.width > 700) { win.style.width = `${width}px`; win.style.height = `${height}px`; }
  }
  function toggleMaximize(state) {
    state.resizer?.cancel();
    const win = state.window;
    if (!win.classList.contains('is-maximized')) {
      state.geometry = { left: win.style.left, top: win.style.top, width: win.style.width, height: win.style.height };
      win.classList.add('is-maximized');
    } else {
      win.classList.remove('is-maximized');
      if (state.geometry) Object.assign(win.style, state.geometry);
      clampWindow(state);
    }
    state.maxButton.replaceChildren(controlIcon(win.classList.contains('is-maximized') ? 'restore' : 'maximize'));
    const label = win.classList.contains('is-maximized') ? '복원' : '최대화';
    state.maxButton.title = label; state.maxButton.setAttribute('aria-label', label);
    activate(state); 
  }
  function minimize(state) {
    state.resizer?.cancel();
    const win = state.window; if (win.hidden || win.classList.contains('minimizing')) return;
    win.classList.add('minimizing'); win.classList.remove('is-active');
    state.minTimer = window.setTimeout(() => { win.hidden = true; win.classList.remove('minimizing'); state.minTimer = null; renderTaskbar(); }, motionDelay(180));
    renderTaskbar();
  }
  function close(state) {
    const win = state.window;
    if (state.minTimer) clearTimeout(state.minTimer);
    state.agencyPicker?.dispose();
    state.resizer?.dispose();
    state.notepad?.dispose();
    state.service?.dispose();
    if (openAgencyPicker === state.agencyPicker) openAgencyPicker = null;
    windows.delete(state.id); win.classList.remove('is-active');
    if (recentWorkApps.has(state.id)) refreshRecentWork();
    win.classList.add('closing');
    state.closeTimer = window.setTimeout(() => win.remove(), motionDelay(150));
    const next = [...windows.values()].reverse().find((item) => !item.window.hidden);
    if (next) activate(next); else renderTaskbar();
  }
  function makeWindow(id, initialHref, itemId) {
    const app = apps.get(id); const template = document.querySelector(`#app-${CSS.escape(id)}`);
    const isServiceApp = Object.hasOwn(serviceRoutes, id);
    if (!app || (!isServiceApp && (!template || !template.content))) return null;
    const win = document.createElement('article'); win.className = 'app-window opening'; win.dataset.app = id;
    win.setAttribute('role', 'region'); win.setAttribute('tabindex', '-1');
    const titlebar = document.createElement('header'); titlebar.className = 'window-titlebar';
    const titleId = `window-title-${id.replace(/[^a-zA-Z0-9_-]/g, '-')}-${Date.now()}`;
    win.setAttribute('aria-labelledby', titleId);
    titlebar.append(appIcon(app)); const title = document.createElement('span'); title.className = 'window-title'; title.id = titleId; title.textContent = app.label; titlebar.append(title);
    const controls = document.createElement('div'); controls.className = 'window-controls';
    const min = document.createElement('button'); setControl(min, '최소화', 'minimize');
    const max = document.createElement('button'); setControl(max, '최대화', 'maximize');
    const shut = document.createElement('button'); setControl(shut, '닫기', 'close');
    controls.append(min, max, shut); titlebar.append(controls); win.append(titlebar);
    const body = document.createElement('div'); body.className = 'window-body';
    if (template?.content) body.append(template.content.cloneNode(true));
    win.append(body);
    if (id === 'settings') {
      const organization = body.querySelector('#profile-org'); const department = body.querySelector('#profile-department');
      const frameworkChoices = body.querySelectorAll('input[name="profile-framework"]'); const region = body.querySelector('#profile-region');
      if (organization) organization.value = affiliation.organization;
      if (department) department.value = affiliation.department;
      frameworkChoices.forEach((choice) => { choice.checked = choice.value === affiliation.personnel_framework; });
      if (region) region.value = affiliation.region;
      renderRuleHint(body);
      const profileForm = body.querySelector('#profile-form');
      if (profileForm && !profileForm.querySelector('#profile-reset')) {
        const reset = document.createElement('button'); reset.id = 'profile-reset'; reset.type = 'button'; reset.textContent = '저장한 소속 지우기';
        profileForm.querySelector('button[type="submit"]')?.after(reset);
      }
      profileForm?.addEventListener('input', () => renderRuleHint(body));
      profileForm?.addEventListener('change', () => renderRuleHint(body));
      body.addEventListener('agency:selectionchange', () => renderRuleHint(body));
      body.querySelector('#profile-org')?.addEventListener('input', (event) => event.currentTarget.setCustomValidity(''));
      profileForm?.querySelector('#profile-reset')?.addEventListener('click', () => resetAffiliation(body));
    }
    const agencyPicker = id === 'settings' ? window.SeomuAgencyPicker?.init(body) || null : null;
    if (agencyPicker) {
      openAgencyPicker = agencyPicker;
      if (affiliation.agency) agencyPicker.restore(affiliation.agency, affiliation.region);
    }
    if (isServiceApp) body.classList.add('service-window-body');
    const bounds = area.getBoundingClientRect();
    const width = id === 'calculator' ? Math.max(0, Math.min(360, bounds.width - 24)) : id === 'notepad' ? Math.max(0, Math.min(520, bounds.width - 24)) : Math.max(Math.min(860, bounds.width - 40), Math.min(320, bounds.width));
    const height = id === 'calculator' ? Math.max(0, Math.min(510, bounds.height - 24)) : id === 'notepad' ? Math.max(0, Math.min(460, bounds.height - 24)) : Math.max(Math.min(id === 'settings' ? 760 : 610, bounds.height - (id === 'settings' ? 32 : 40)), Math.min(200, bounds.height));
    const offset = id === 'notepad' ? 0 : (cascade++ % 8) * 20;
    win.style.left = `${Math.max(0, (bounds.width - width) / 2 + offset)}px`;
    win.style.top = `${Math.max(0, (bounds.height - height) / 2 + offset)}px`;
    win.style.width = `${width}px`; win.style.height = `${height}px`;
    const resizer = window.GongmudamWindowResize?.init(win, area) || null;
    const notepad = id === 'notepad' ? window.GongmudamNotepad?.init(win, area) || null : null;
    const state = { id, window: win, titlebar, minButton: min, maxButton: max, closeButton: shut, geometry: null, minTimer: null, closeTimer: null, agencyPicker, notepad, resizer, service: null, serviceHref: null, serviceItemId: null };
    if (isServiceApp && window.GongmudamServiceBridge) {
      state.serviceHref = initialHref || serviceRoutes[id];
      state.serviceItemId = itemId || null;
      state.service = window.GongmudamServiceBridge.mount(body, id, {
        href: state.serviceHref, title: app.label, profile: getServiceProfile(),
        onOpen: (nextId, href) => openApp(nextId, href),
        onChanged: refreshRecentWork,
        onFocus: () => { if (recentWorkApps.has(id)) refreshRecentWork(); },
      });
    }
    min.addEventListener('click', () => minimize(state)); max.addEventListener('click', () => toggleMaximize(state)); shut.addEventListener('click', () => close(state));
    win.addEventListener('pointerdown', () => activate(state), { passive: true });
    titlebar.addEventListener('dblclick', (event) => { if (!event.target.closest('button')) toggleMaximize(state); });
    titlebar.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || event.target.closest('button') || win.classList.contains('is-maximized')) return;
      const startX = event.clientX, startY = event.clientY, startLeft = parseFloat(win.style.left) || 0, startTop = parseFloat(win.style.top) || 0;
      titlebar.setPointerCapture(event.pointerId);
      const move = (moveEvent) => {
        if (!titlebar.hasPointerCapture(moveEvent.pointerId)) return;
        const areaRect = area.getBoundingClientRect(); const rect = win.getBoundingClientRect();
        const widthNow = rect.width, heightNow = rect.height;
        win.style.left = `${Math.max(0, Math.min(startLeft + moveEvent.clientX - startX, areaRect.width - Math.min(widthNow, areaRect.width)))}px`;
        const maxTop = id === 'notepad' ? areaRect.height - Math.min(heightNow, areaRect.height) : areaRect.height - Math.min(heightNow, 56);
        win.style.top = `${Math.max(0, Math.min(startTop + moveEvent.clientY - startY, maxTop))}px`;
      };
      const end = (endEvent) => { if (titlebar.hasPointerCapture(endEvent.pointerId)) titlebar.releasePointerCapture(endEvent.pointerId); titlebar.removeEventListener('pointermove', move); titlebar.removeEventListener('pointerup', end); titlebar.removeEventListener('pointercancel', end); };
      titlebar.addEventListener('pointermove', move); titlebar.addEventListener('pointerup', end); titlebar.addEventListener('pointercancel', end);
    });
    layer.append(win); windows.set(id, state); activate(state, true);
    window.setTimeout(() => win.classList.remove('opening'), motionDelay(260));
    return state;
  }
  function openApp(id, optionalHref, itemId) {
    if (!apps.has(id) && !Object.hasOwn(serviceRoutes, id)) return null;
    let state = windows.get(id);
    if (!state) state = makeWindow(id, optionalHref, itemId);
    else if (optionalHref && state.service && state.serviceHref !== optionalHref) { state.serviceHref = optionalHref; state.serviceItemId = itemId || null; state.service.navigate(optionalHref); }
    if (state) activate(state, true);
    document.querySelector('#start-menu')?.setAttribute('hidden', '');
    return state;
  }
  function toast(message) {
    const node = document.querySelector('#prototype-toast'); if (!node) return;
    node.textContent = message; node.hidden = false;
    clearTimeout(toast.timer); toast.timer = window.setTimeout(() => { node.hidden = true; }, 2400);
  }
  function resolveRecentHref(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const path = value.startsWith('/') ? value : `/${value}`;
      const url = new URL(path, location.origin);
      if (url.origin !== location.origin) return null;
      const allowedRoutes = new Map([['/travel.html', 'travel'], ['/adhoc.html', 'collection'], ['/folders.html', 'folders']]);
      const id = allowedRoutes.get(url.pathname);
      return id ? { id, href: `${url.pathname}${url.search}${url.hash}` } : null;
    } catch { return null; }
  }
  async function refreshRecentWork() {
    const host = document.querySelector('#recent-work-items'); const status = document.querySelector('#recent-work-status');
    if (!host || !status) return;
    if (recentWorkRequest) recentWorkRequest.abort();
    recentWorkRequest = new AbortController(); const controller = recentWorkRequest; const token = ++recentWorkSequence;
    host.replaceChildren(); status.textContent = '최근 저장한 업무를 확인하고 있습니다…';
    try {
      const response = await fetch('/api/workspace/recent', { method: 'GET', headers: { Accept: 'application/json' }, credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json(); if (token !== recentWorkSequence) return;
      const referenceLibraryIds = new Set(['esaram-manuals-v68', '2d452f42d15242f7b3506c111148aff6']);
      const items = Array.isArray(data?.items) ? data.items.filter((item) => !referenceLibraryIds.has(item?.library_id) && !referenceLibraryIds.has(item?.id)) : [];
      const renderable = items.map((item) => ({ item, itemId: typeof item?.id === 'string' || Number.isFinite(item?.id) ? String(item.id) : '', destination: resolveRecentHref(item?.href) })).filter(({ itemId, destination }) => destination && itemId.length > 0 && itemId.length <= 200);
      if (!renderable.length) {
        status.textContent = items.length ? '열 수 있는 최근 업무가 없습니다.' : '저장된 업무가 없습니다.';
        return;
      }
      renderable.forEach(({ item, itemId, destination }) => {
        const button = document.createElement('button'); button.type = 'button'; button.dataset.open = destination.id;
        button.dataset.serviceHref = destination.href; button.dataset.itemId = itemId; button.className = 'recent-work-item';
        const type = document.createElement('span'); type.className = 'work-type'; type.textContent = ({ travel: '출장정산', collection: '자료 취합', education: '교육 취합', folder: '업무자료' })[item.kind] || '저장한 업무';
        const title = document.createElement('strong'); title.textContent = typeof item.title === 'string' ? item.title : '제목 없는 업무';
        const detail = document.createElement('small'); detail.textContent = [item.status, item.next_action].filter((part) => typeof part === 'string' && part.trim()).join(' · ');
        button.append(type, title, detail); host.append(button);
      });
      status.textContent = `${renderable.length}개의 최근 업무`;
    } catch (error) {
      if (error.name === 'AbortError' || token !== recentWorkSequence) return;
      host.replaceChildren(); status.textContent = '최근 업무를 불러오지 못했습니다. 서비스를 확인해 주세요.';
    } finally { if (token === recentWorkSequence) recentWorkRequest = null; }
  }
  function submitChatQuestion(question) {
    const state = openApp('chat'); return state?.service?.ask(question) === true;
  }
  function updateClock() {
    const now = new Date();
    const dateText = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }).format(now);
    const timeText = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(now);
    const datetime = now.toISOString();
    const clock = document.querySelector('#system-datetime');
    if (clock) { clock.dateTime = datetime; clock.textContent = `${dateText} ${timeText}`; clock.style.fontVariantNumeric = 'tabular-nums'; }
  }
  updateClock(); window.setInterval(updateClock, 1000);
  function renderAffiliation() {
    const output = document.querySelector('#profile-affiliation-text'); if (!output) return;
    output.textContent = affiliation.confirmed ? [affiliation.organization, affiliation.department].filter(Boolean).join(' · ') : '소속 설정';
    output.title = affiliation.confirmed ? [frameworks[affiliation.personnel_framework], affiliation.region, affiliation.organization, affiliation.department].filter(Boolean).join(' · ') : '내 소속 설정';
  }
  function getServiceProfile() {
    if (!affiliation.confirmed) return null;
    return {
      confirmed: true,
      schema_version: affiliation.schema_version,
      personnel_framework: affiliation.personnel_framework,
      region: affiliation.region,
      organization: affiliation.organization,
      department: affiliation.department,
      agency: affiliation.agency || null,
    };
  }
  function broadcastServiceContext() {
    const profile = getServiceProfile();
    windows.forEach((state) => state.service?.updateProfile(profile));
  }
  function renderRuleHint(scope = document) {
    const hint = scope.querySelector('#profile-rule-hint'); if (!hint) return;
    const hasLiveForm = Boolean(scope.querySelector('#profile-form'));
    const framework = hasLiveForm ? getProfileFramework(scope) : affiliation.personnel_framework;
    const region = hasLiveForm ? (scope.querySelector('#profile-region')?.value || '') : affiliation.region;
    const organization = hasLiveForm ? (scope.querySelector('#profile-org')?.value.trim() || '') : affiliation.organization;
    const criteria = [frameworks[framework], region, organization].filter(Boolean);
    const frameworkPrompt = !framework ? '신분 구분을 직접 확인해 주세요. ' : '';
    hint.textContent = `${criteria.length ? `선택 기준: ${criteria.join(' · ')}. ` : '근무 기준을 선택해 주세요. '}${frameworkPrompt}소속 정보는 질문에 함께 전달됩니다. 여비 계산은 출장 화면에서 적용할 규정팩을 직접 선택해야 합니다.`;
  }
  function renderCompanion() {
    const title = document.querySelector('#companion-title'); const message = document.querySelector('#companion-message'); const action = document.querySelector('#companion-action');
    if (!title || !message || !action) return;
    if (!affiliation.confirmed) {
      title.textContent = '안녕하세요, 공무담의 무무예요';
      message.textContent = '어디에서 근무하시나요? 소속을 알려주시면 맞는 업무 기준을 함께 찾을게요.';
      action.textContent = '내 소속 설정하기'; action.dataset.open = 'settings';
    } else {
      title.textContent = '무무가 업무를 함께 챙길게요';
      message.textContent = `${affiliation.region} · ${frameworks[affiliation.personnel_framework]}`;
      action.textContent = '무무에게 물어보기'; action.dataset.open = 'chat';
    }
  }
  function resetAffiliation(scope) {
    let removed = false;
    try { window.localStorage.removeItem(profileStorageKey); removed = true; }
    catch { /* Clear this page session even when browser storage is blocked. */ }
    Object.assign(affiliation, { schema_version: 2, personnel_framework: '', region: '', organization: '', department: '', agency: null, confirmed: false, saved_at: '' });
    scope.querySelector('#profile-form')?.reset();
    scope.querySelector('#profile-org')?.setCustomValidity('');
    openAgencyPicker?.clear({ clearInput: true, clearRegion: true });
    renderAffiliation(); renderCompanion(); renderRuleHint(scope);
    broadcastServiceContext();
    toast(removed ? '저장한 소속 정보를 지웠습니다.' : '현재 화면에서 소속을 지웠습니다. 브라우저 저장을 변경할 수 없습니다.');
  }
  function loadAffiliation() {
    try {
      const raw = window.localStorage.getItem(profileStorageKey); if (!raw) return;
      const profile = JSON.parse(raw);
      if (!profile || typeof profile !== 'object' || ![1, 2].includes(profile.schema_version) || profile.confirmed !== true || !Object.hasOwn(frameworks, profile.personnel_framework) || !regions.includes(profile.region) || typeof profile.organization !== 'string' || !profile.organization.trim() || profile.organization.length > (profile.schema_version === 1 ? 80 : 300) || typeof profile.department !== 'string' || profile.department.length > 80 || typeof profile.saved_at !== 'string') return;
      let agency = profile.schema_version === 2 && window.SeomuAgencyPicker ? window.SeomuAgencyPicker.normalizeAgency(profile.agency) : null;
      if (!agency || agency.officialName !== profile.organization) agency = null;
      Object.assign(affiliation, { schema_version: 2, personnel_framework: profile.personnel_framework, region: profile.region, organization: profile.organization, department: profile.department, agency, confirmed: true, saved_at: profile.saved_at });
    } catch { /* Storage can be unavailable in private or restricted browsing contexts. */ }
  }
  loadAffiliation();
  renderAffiliation();
  renderCompanion();

  document.addEventListener('click', (event) => {
    const open = event.target.closest('[data-open]');
    if (open) {
      if (suppressDraggedIconClick && open.classList.contains('desktop-app')) { event.preventDefault(); event.stopPropagation(); suppressDraggedIconClick = false; return; }
      event.preventDefault(); openApp(open.dataset.open, open.dataset.serviceHref, open.dataset.itemId); return;
    }
    const task = event.target.closest('.running-app[data-task]');
    if (task) {
      const state = windows.get(task.dataset.task); if (!state) return;
      if (!state.window.hidden && state.window.classList.contains('is-active')) minimize(state); else activate(state, true);
      return;
    }
    if (event.target.closest('#show-desktop')) {
      const visible = [...windows.values()].filter((state) => !state.window.hidden && !state.window.classList.contains('minimizing'));
      if (visible.length) {
        showDesktopWindowIds = visible.map((state) => state.id);
        visible.forEach(minimize);
      } else {
        const restoreIds = showDesktopWindowIds.length ? showDesktopWindowIds : [...windows.keys()];
        restoreIds.forEach((id) => { const state = windows.get(id); if (state) activate(state, true); });
        showDesktopWindowIds = [];
      }
      return;
    }
    if (event.target.closest('#start-button')) {
      const menu = document.querySelector('#start-menu'); if (menu) menu.hidden = !menu.hidden;
      return;
    }
    const variantButton = event.target.closest('button[data-variant]');
    if (variantButton) { setVariant(variantButton.dataset.variant); return; }
    if (event.target.closest('#variant-prev')) { cycleVariant(-1); return; }
    if (event.target.closest('#variant-next')) { cycleVariant(1); return; }
    const expanded = event.target.closest('#desktop-expanded');
    if (expanded) {
      const on = document.body.classList.toggle('monitor-expanded');
      expanded.setAttribute('aria-pressed', String(on)); expanded.textContent = on ? '기본 모니터' : '화면 넓히기';
      requestAnimationFrame(() => windows.forEach(clampWindow)); return;
    }
    const frame = event.target.closest('#desktop-frame');
    if (frame) {
      const on = document.body.classList.toggle('has-monitor-frame');
      const label = on ? '화면 테두리 끄기' : '화면 테두리 켜기';
      frame.setAttribute('aria-pressed', String(on)); frame.title = label; frame.setAttribute('aria-label', label);
      const visibleLabel = frame.querySelector('.frame-toggle-label'); if (visibleLabel) visibleLabel.textContent = on ? '테두리 끄기' : '화면 테두리';
      requestAnimationFrame(() => { windows.forEach(clampWindow); if (document.body.dataset.variant === 'B') applyBIconPositions(); });
      return;
    }
  });
  document.addEventListener('submit', (event) => {
    const profile = event.target.closest('#profile-form');
    if (profile) {
      event.preventDefault();
      const personnelFramework = getProfileFramework(profile);
      const region = profile.querySelector('#profile-region')?.value || '';
      const organizationField = profile.querySelector('#profile-org');
      const organization = (organizationField?.value || '').trim().slice(0, 300);
      const department = (profile.querySelector('#profile-department')?.value || '').trim().slice(0, 80);
      if (!Object.hasOwn(frameworks, personnelFramework) || !regions.includes(region) || !organization) {
        if (!organization) organizationField?.setCustomValidity('기관명을 입력해 주세요. 공백만으로는 저장할 수 없습니다.');
        profile.reportValidity(); return;
      }
      let agency = windows.get('settings')?.agencyPicker?.getSelection() || null;
      if (!agency || agency.officialName !== organization) agency = null;
      Object.assign(affiliation, { schema_version: 2, personnel_framework: personnelFramework, region, organization, department, agency, confirmed: true, saved_at: new Date().toISOString() });
      let persisted = false;
      try { window.localStorage.setItem(profileStorageKey, JSON.stringify(affiliation)); persisted = true; }
      catch { /* Keep the submitted profile in memory for this page session. */ }
      renderAffiliation(); renderCompanion(); renderRuleHint(); broadcastServiceContext();
      toast(persisted ? '소속 정보를 저장하고 열린 서비스에 전달했습니다.' : '소속 정보를 저장하지 못했습니다. 브라우저 저장을 사용할 수 없습니다.'); return;
    }
    const search = event.target.closest('#taskbar-search');
    if (search) {
      event.preventDefault();
      const field = search.querySelector('#taskbar-query'); const question = field?.value.trim(); if (!question) return;
      if (submitChatQuestion(question)) search.reset(); return;
    }
    const command = event.target.closest('#desktop-question');
    if (command) {
      event.preventDefault(); const input = command.querySelector('input, textarea'); const question = input?.value.trim(); if (!question) return;
      if (submitChatQuestion(question)) command.reset();
      return;
    }
    return;
  });

  function setVariant(value) {
    const variant = comparisonEnabled ? String(value || '').toUpperCase() : 'B'; if (!variantInfo[variant]) return;
    const previousVariant = document.body.dataset.variant;
    if (previousVariant === 'B' && variant !== 'B') clearBIconLayout();
    document.body.dataset.variant = variant;
    if (variant === 'B') requestAnimationFrame(applyBIconPositions);
    const caption = area.querySelector('.desktop-caption');
    if (caption) caption.textContent = variant === 'B' ? '아이콘을 끌어 배치하거나, 눌러 업무를 시작하세요' : '폴더를 눌러 업무를 시작하세요';
    const url = new URL(location.href); url.searchParams.set('variant', variant); history.replaceState(null, '', url);
    document.querySelectorAll('button[data-variant]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.variant.toUpperCase() === variant)));
    const label = document.querySelector('#variant-label'); if (label) label.textContent = variantInfo[variant][0];
    const description = document.querySelector('#variant-description'); if (description) description.textContent = variantInfo[variant][1];
    updatePrototypeState(); requestAnimationFrame(() => { windows.forEach(clampWindow); if (variant === 'B') applyBIconPositions(); });
  }
  function cycleVariant(step) { const current = document.body.dataset.variant || 'A'; const order = ['A', 'B', 'C']; setVariant(order[(order.indexOf(current) + step + order.length) % order.length]); }
  const params = new URLSearchParams(location.search); setVariant(comparisonEnabled ? (params.get('variant') || document.body.dataset.variant || 'A') : 'B');
  window.addEventListener('resize', () => requestAnimationFrame(() => { windows.forEach(clampWindow); if (document.body.dataset.variant === 'B') applyBIconPositions(); }));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      const menu = document.querySelector('#start-menu'); if (menu && !menu.hidden) { menu.hidden = true; document.querySelector('#start-button')?.focus(); }
      return;
    }
    const editable = event.target.closest('input, textarea, select, [contenteditable="true"], .app-window');
    if (comparisonEnabled && !editable && event.target.closest('button[data-variant], #variant-prev, #variant-next, body')) {
      if (event.key === 'ArrowLeft') { event.preventDefault(); cycleVariant(-1); }
      if (event.key === 'ArrowRight') { event.preventDefault(); cycleVariant(1); }
    }
    if (event.key === 'F6') {
      const visible = [...windows.values()].filter((state) => !state.window.hidden); if (!visible.length) return;
      event.preventDefault(); focusIndex = (focusIndex + 1) % visible.length; activate(visible[focusIndex], true);
    }
  });
  renderTaskbar();
  refreshRecentWork();
});
