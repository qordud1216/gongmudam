(() => {
  const STORAGE_KEY = 'gongmudam.notepad.v1';
  const MAX_LENGTH = 100000;

  function loadText() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw === null) return { text: '', available: true };
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object' && parsed.schema_version === 1 && typeof parsed.text === 'string') {
          return { text: parsed.text.slice(0, MAX_LENGTH), available: true };
        }
      } catch { /* Raw text is also a supported storage format. */ }
      return { text: raw.slice(0, MAX_LENGTH), available: true };
    } catch { return { text: '', available: false }; }
  }

  function init(win, area) {
    const editor = win.querySelector('#notepad-content');
    const status = win.querySelector('#notepad-save-status');
    const handle = win.querySelector('.notepad-resize');
    if (!editor || !status || !handle) return null;
    const usesSharedResizer = win.classList.contains('has-window-resizer');
    if (usesSharedResizer) handle.hidden = true;
    let disposed = false;
    let activeResizeCleanup = null;

    function setStatus(message, isError = false) { status.textContent = message; status.dataset.error = String(isError); }
    function save() {
      if (disposed) return;
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ schema_version: 1, text: editor.value.slice(0, MAX_LENGTH) }));
        setStatus('메모를 이 브라우저에 저장했습니다.');
      } catch {
        setStatus('브라우저 저장에 실패했습니다. 메모는 창이 열려 있는 동안 유지됩니다.', true);
      }
    }

    const stored = loadText(); editor.value = stored.text;
    editor.addEventListener('input', save);
    setStatus(stored.available ? '브라우저에 저장되는 메모입니다.' : '브라우저 저장을 사용할 수 없습니다.', !stored.available);

    function isResizable() {
      return !usesSharedResizer && !disposed && !win.hidden && !win.classList.contains('is-maximized') && area.getBoundingClientRect().width > 700;
    }
    function resizeTo(width, height) {
      const bounds = area.getBoundingClientRect(); const rect = win.getBoundingClientRect();
      const left = rect.left - bounds.left, top = rect.top - bounds.top;
      const availableWidth = Math.max(0, bounds.width - left); const availableHeight = Math.max(0, bounds.height - top);
      const minWidth = Math.min(280, availableWidth); const minHeight = Math.min(240, availableHeight);
      win.style.width = `${Math.max(minWidth, Math.min(width, availableWidth))}px`;
      win.style.height = `${Math.max(minHeight, Math.min(height, availableHeight))}px`;
    }
    function onPointerDown(event) {
      if (event.button !== 0 || !isResizable()) return;
      event.preventDefault();
      const startX = event.clientX, startY = event.clientY;
      const startWidth = win.getBoundingClientRect().width, startHeight = win.getBoundingClientRect().height;
      handle.setPointerCapture(event.pointerId);
      const onMove = (moveEvent) => {
        if (moveEvent.pointerId !== event.pointerId || !isResizable()) return;
        moveEvent.preventDefault(); resizeTo(startWidth + moveEvent.clientX - startX, startHeight + moveEvent.clientY - startY);
      };
      const cleanup = () => {
        if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
        handle.removeEventListener('pointermove', onMove); handle.removeEventListener('pointerup', onFinish); handle.removeEventListener('pointercancel', onFinish);
        if (activeResizeCleanup === cleanup) activeResizeCleanup = null;
      };
      const onFinish = (finishEvent) => {
        if (finishEvent.pointerId !== event.pointerId) return;
        cleanup();
      };
      activeResizeCleanup = cleanup;
      handle.addEventListener('pointermove', onMove); handle.addEventListener('pointerup', onFinish); handle.addEventListener('pointercancel', onFinish);
    }
    function onKeyDown(event) {
      if (!isResizable() || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault(); event.stopPropagation();
      const rect = win.getBoundingClientRect(); const step = event.shiftKey ? 40 : 16;
      const width = rect.width + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0);
      const height = rect.height + (event.key === 'ArrowDown' ? step : event.key === 'ArrowUp' ? -step : 0);
      resizeTo(width, height);
    }
    if (!usesSharedResizer) {
      handle.addEventListener('pointerdown', onPointerDown);
      handle.addEventListener('keydown', onKeyDown);
    }

    function dispose() {
      if (disposed) return;
      disposed = true;
      activeResizeCleanup?.();
      editor.removeEventListener('input', save);
      handle.removeEventListener('pointerdown', onPointerDown);
      handle.removeEventListener('keydown', onKeyDown);
    }
    return { dispose };
  }

  window.GongmudamNotepad = { init };
})();
