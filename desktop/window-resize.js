(() => {
  const directions = new Set(['N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW']);

  function resizeGeometry(direction, origin, delta, bounds, minSize = { width: 320, height: 220 }) {
    const values = [origin?.left, origin?.top, origin?.width, origin?.height, delta?.x, delta?.y, bounds?.width, bounds?.height, minSize?.width, minSize?.height];
    if (!directions.has(direction) || values.some((value) => !Number.isFinite(value)) || bounds.width <= 0 || bounds.height <= 0 || origin.width <= 0 || origin.height <= 0 || minSize.width <= 0 || minSize.height <= 0) return null;
    const clamp = (value, low, high) => Math.max(low, Math.min(value, high));
    let left, width;
    if (direction.includes('W')) {
      const right = clamp(origin.left + origin.width, 0, bounds.width);
      const minWidth = Math.min(minSize.width, right);
      width = clamp(origin.width - delta.x, minWidth, right);
      left = right - width;
    } else if (direction.includes('E')) {
      left = clamp(origin.left, 0, bounds.width);
      const maxWidth = bounds.width - left, minWidth = Math.min(minSize.width, maxWidth);
      width = clamp(origin.width + delta.x, minWidth, maxWidth);
    } else {
      width = Math.min(origin.width, bounds.width);
      left = clamp(origin.left, 0, bounds.width - width);
    }
    let top, height;
    if (direction.includes('N')) {
      const bottom = clamp(origin.top + origin.height, 0, bounds.height);
      const minHeight = Math.min(minSize.height, bottom);
      height = clamp(origin.height - delta.y, minHeight, bottom);
      top = bottom - height;
    } else if (direction.includes('S')) {
      top = clamp(origin.top, 0, bounds.height);
      const maxHeight = bounds.height - top, minHeight = Math.min(minSize.height, maxHeight);
      height = clamp(origin.height + delta.y, minHeight, maxHeight);
    } else {
      height = Math.min(origin.height, bounds.height);
      top = clamp(origin.top, 0, bounds.height - height);
    }
    return { left, top, width, height };
  }

  function init(win, area) {
    if (!win || !area) return null;
    const grips = document.createElement('div');
    grips.className = 'window-resize-grips';
    grips.setAttribute('aria-label', '창 크기 조절');
    const labels = { N: '위쪽', S: '아래쪽', E: '오른쪽', W: '왼쪽', NE: '오른쪽 위 모서리', NW: '왼쪽 위 모서리', SE: '오른쪽 아래 모서리', SW: '왼쪽 아래 모서리' };
    for (const direction of directions) {
      const grip = document.createElement('button');
      grip.type = 'button'; grip.className = 'window-resize-grip'; grip.dataset.direction = direction;
      grip.setAttribute('aria-label', `창 ${labels[direction]} 크기 조절`);
      grip.setAttribute('aria-keyshortcuts', 'ArrowLeft ArrowRight ArrowUp ArrowDown Shift+ArrowLeft Shift+ArrowRight Shift+ArrowUp Shift+ArrowDown');
      grips.append(grip);
    }
    win.append(grips); win.classList.add('has-window-resizer');
    let disposed = false, drag = null;

    function canResize() {
      const bounds = area.getBoundingClientRect();
      return !disposed && win.isConnected && !win.hidden && !win.classList.contains('minimizing') && !win.classList.contains('is-maximized') && !win.classList.contains('closing') && bounds.width > 700 && bounds.height > 0;
    }
    function currentGeometry() {
      const bounds = area.getBoundingClientRect(), rect = win.getBoundingClientRect();
      return { bounds, origin: { left: rect.left - bounds.left, top: rect.top - bounds.top, width: rect.width, height: rect.height } };
    }
    function apply(next) {
      if (!next) return;
      win.style.left = `${next.left}px`; win.style.top = `${next.top}px`;
      win.style.width = `${next.width}px`; win.style.height = `${next.height}px`;
    }
    function cancel() {
      if (!drag) return;
      const active = drag; drag = null;
      active.grip.removeEventListener('pointermove', active.move);
      active.grip.removeEventListener('pointerup', active.finish);
      active.grip.removeEventListener('pointercancel', active.finish);
      if (active.grip.hasPointerCapture(active.pointerId)) active.grip.releasePointerCapture(active.pointerId);
      win.classList.remove('is-resizing');
    }
    function onPointerDown(event) {
      const grip = event.target.closest('.window-resize-grip');
      if (!grip || event.button !== 0 || !canResize()) return;
      const { bounds, origin } = currentGeometry();
      event.preventDefault();
      grip.focus({ preventScroll: true });
      grip.setPointerCapture(event.pointerId);
      win.classList.add('is-resizing');
      const direction = grip.dataset.direction, startX = event.clientX, startY = event.clientY;
      const move = (moveEvent) => {
        if (!drag || moveEvent.pointerId !== drag.pointerId || !canResize()) return;
        moveEvent.preventDefault();
        apply(resizeGeometry(direction, origin, { x: moveEvent.clientX - startX, y: moveEvent.clientY - startY }, { width: area.getBoundingClientRect().width, height: area.getBoundingClientRect().height }));
      };
      const finish = (endEvent) => { if (endEvent.pointerId === event.pointerId) cancel(); };
      drag = { grip, pointerId: event.pointerId, move, finish };
      grip.addEventListener('pointermove', move); grip.addEventListener('pointerup', finish); grip.addEventListener('pointercancel', finish);
    }
    function onKeyDown(event) {
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key) || !canResize()) return;
      const grip = event.target.closest('.window-resize-grip'); if (!grip) return;
      const direction = grip.dataset.direction;
      const horizontal = direction.includes('E') || direction.includes('W');
      const vertical = direction.includes('N') || direction.includes('S');
      if ((event.key.startsWith('ArrowLeft') || event.key.startsWith('ArrowRight')) ? !horizontal : !vertical) return;
      event.preventDefault(); event.stopPropagation();
      const step = event.shiftKey ? 40 : 16;
      const delta = { x: event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0, y: event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0 };
      const { bounds, origin } = currentGeometry(); apply(resizeGeometry(direction, origin, delta, { width: bounds.width, height: bounds.height }));
    }
    grips.addEventListener('pointerdown', onPointerDown);
    grips.addEventListener('keydown', onKeyDown);

    function dispose() {
      if (disposed) return;
      cancel(); disposed = true;
      grips.removeEventListener('pointerdown', onPointerDown); grips.removeEventListener('keydown', onKeyDown);
      grips.remove(); win.classList.remove('has-window-resizer');
    }
    return { cancel, dispose };
  }

  window.GongmudamWindowResize = { init, resizeGeometry };
})();
