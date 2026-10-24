(() => {
  const ROOT_PARENT = '상위기관 없음 (최상위기관)';
  const text = (value, limit = 300) => typeof value === 'string' ? value.trim().slice(0, limit) : '';
  const validCode = (value) => typeof value === 'string' && /^[A-Z0-9]{7}$/.test(value);

  function normalizeAgency(value) {
    if (!value || typeof value !== 'object' || !validCode(value.agencyCode)) return null;
    const officialName = text(value.officialName);
    const parentCode = value.parentCode == null ? null : value.parentCode;
    const ancestors = Array.isArray(value.ancestors) ? value.ancestors.slice(0, 30).map((item) => ({
      code: validCode(item?.code) ? item.code : null,
      fullName: text(item?.fullName),
    })).filter((item) => item.fullName) : [];
    if (!officialName || (parentCode !== null && !validCode(parentCode))) return null;
    const parentName = parentCode === null ? ROOT_PARENT : ancestors.find((item) => item.code === parentCode)?.fullName || `상위기관 확인 필요 (${parentCode})`;
    const sha256 = text(value.sha256, 64);
    return {
      agencyCode: value.agencyCode,
      officialName,
      parentCode,
      parentName,
      ancestors,
      regionHint: text(value.regionHint, 100),
      regionBasis: text(value.regionBasis, 300),
      sourceUrl: text(value.sourceUrl, 1000),
      sourceUpdatedAt: text(value.sourceUpdatedAt, 100),
      fetchedAt: text(value.fetchedAt, 100),
      sha256: /^[a-f\d]{64}$/i.test(sha256) ? sha256 : '',
    };
  }

  function init(scope) {
    const input = scope.querySelector('#profile-org');
    const searchButton = scope.querySelector('#agency-search');
    const status = scope.querySelector('#agency-status');
    const results = scope.querySelector('#agency-results');
    const pagination = scope.querySelector('#agency-pagination');
    const parent = scope.querySelector('#profile-parent');
    const summary = scope.querySelector('#agency-selected-summary');
    const sourceText = scope.querySelector('#agency-source-date');
    const region = scope.querySelector('#profile-region');
    const form = scope.querySelector('#profile-form');
    if (!input || !searchButton || !status || !results || !pagination || !parent || !summary || !region || !form) return null;

    let selected = null; let requestController = null; let detailController = null;
    let debounceTimer = null; let sequence = 0; let currentQuery = ''; let currentPage = 1;
    let autoRegionValue = ''; let regionOverridden = false; let disposed = false;

    function say(message) { status.textContent = message; }
    function emitSelection() {
      scope.dispatchEvent(new CustomEvent('agency:selectionchange', { bubbles: true, detail: { agency: selected ? { ...selected, ancestors: selected.ancestors.map((item) => ({ ...item })) } : null } }));
    }
    function clearSelection(options = {}) {
      const { manualEdit = false, clearInput = false, clearRegion = true } = options;
      const hadSelection = Boolean(selected);
      selected = null; parent.value = '';
      summary.textContent = ''; if (sourceText) sourceText.textContent = '';
      if (clearInput) input.value = '';
      if (clearRegion && autoRegionValue && !regionOverridden && region.value === autoRegionValue) region.value = '';
      autoRegionValue = ''; regionOverridden = false;
      if (manualEdit && hadSelection) scope.querySelectorAll('input[name="profile-framework"]').forEach((radio) => { radio.checked = false; });
      if (hadSelection) emitSelection();
    }
    function cancelRequests() {
      sequence += 1;
      if (requestController) requestController.abort(); requestController = null;
      if (detailController) detailController.abort(); detailController = null;
      clearTimeout(debounceTimer); debounceTimer = null;
    }
    function sourceDate(source) {
      const value = text(source?.sourceUpdatedAt || source?.fetchedAt, 100);
      return value ? `자료 기준일: ${value}` : '';
    }
    function renderPagination(total, page, limit) {
      pagination.replaceChildren();
      const pages = Math.ceil(total / limit); if (pages <= 1) return;
      const previous = document.createElement('button'); previous.type = 'button'; previous.textContent = '이전'; previous.disabled = page <= 1;
      previous.addEventListener('click', () => search(currentQuery, page - 1));
      const label = document.createElement('span'); label.textContent = `${page} / ${pages}쪽`;
      const next = document.createElement('button'); next.type = 'button'; next.textContent = '다음'; next.disabled = page >= pages;
      next.addEventListener('click', () => search(currentQuery, page + 1));
      pagination.append(previous, label, next);
    }
    async function search(query = input.value.trim(), page = 1) {
      const normalizedQuery = text(query, 300); currentQuery = normalizedQuery; currentPage = page;
      cancelRequests(); const token = sequence;
      results.replaceChildren(); pagination.replaceChildren();
      if (normalizedQuery.length < 2) { say('기관명을 두 글자 이상 입력해 찾을 수 있습니다. 직접 입력도 가능합니다.'); return; }
      requestController = new AbortController(); say('기관 목록을 찾고 있습니다…');
      try {
        const url = new URL('/api/agencies', location.origin); url.searchParams.set('q', normalizedQuery); url.searchParams.set('page', String(page)); url.searchParams.set('limit', '8');
        const response = await fetch(url, { method: 'GET', headers: { Accept: 'application/json' }, signal: requestController.signal, credentials: 'same-origin' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (disposed || token !== sequence) return;
        const items = Array.isArray(data?.items) ? data.items.slice(0, 8) : [];
        if (!items.length) { say('일치하는 기관을 찾지 못했습니다. 기관명을 직접 입력할 수 있습니다.'); return; }
        items.forEach((item) => {
          const code = validCode(item?.code) ? item.code : '';
          const name = text(item?.fullName);
          if (!code || !name) return;
          const candidate = document.createElement('button'); candidate.type = 'button'; candidate.className = 'agency-candidate';
          candidate.setAttribute('aria-label', `${name}, 기관 코드 ${code}`); candidate.textContent = `${name} · ${code}`;
          candidate.addEventListener('click', () => select(code)); results.append(candidate);
        });
        if (!results.childElementCount) { say('표시할 기관 결과가 없습니다. 기관명을 직접 입력할 수 있습니다.'); return; }
        const total = Number.isFinite(data.total) ? Math.max(0, data.total) : items.length;
        const limit = Number.isFinite(data.limit) && data.limit > 0 ? data.limit : 8;
        renderPagination(total, Number.isFinite(data.page) ? data.page : page, limit);
        const updated = sourceDate(data.source);
        say(`${total}개 기관을 찾았습니다.${updated ? ` ${updated}` : ''}`);
      } catch (error) {
        if (error.name === 'AbortError' || disposed || token !== sequence) return;
        say('기관 목록을 불러오지 못했습니다. 나중에 다시 찾거나 기관명을 직접 입력해 주세요.');
      } finally { if (token === sequence) requestController = null; }
    }
    async function select(code) {
      cancelRequests(); const token = sequence; detailController = new AbortController();
      say('기관 정보를 확인하고 있습니다…');
      try {
        const response = await fetch(`/api/agencies/${encodeURIComponent(code)}`, { method: 'GET', headers: { Accept: 'application/json' }, signal: detailController.signal, credentials: 'same-origin' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (disposed || token !== sequence) return;
        const agency = data?.agency;
        const fullName = text(agency?.fullName);
        if (!validCode(agency?.code) || agency.code !== code || !fullName) throw new Error('Invalid agency result');
        const ancestors = Array.isArray(data.ancestors) ? data.ancestors.slice(0, 30).map((item) => ({ code: validCode(item?.code) ? item.code : null, fullName: text(item?.fullName) })).filter((item) => item.fullName) : [];
        const parentCode = agency.parentCode == null ? null : agency.parentCode;
        if (parentCode !== null && !validCode(parentCode)) throw new Error('Invalid parent code');
        const parentName = parentCode === null ? ROOT_PARENT : ancestors.find((item) => item.code === parentCode)?.fullName || `상위기관 확인 필요 (${parentCode})`;
        const source = data.source || {};
        const regionHint = text(data.context?.region?.name, 100);
        selected = normalizeAgency({ agencyCode: agency.code, officialName: fullName, parentCode, parentName, ancestors, regionHint, regionBasis: text(data.context?.region?.basis, 300), sourceUrl: source.sourceUrl, sourceUpdatedAt: source.sourceUpdatedAt, fetchedAt: source.fetchedAt, sha256: source.sha256 });
        if (!selected) throw new Error('Invalid agency result');
        input.value = selected.officialName; parent.value = selected.parentName;
        summary.textContent = `${[...selected.ancestors.map((item) => item.fullName), selected.officialName].join(' › ')} · 기관 코드 ${selected.agencyCode}`;
        if (sourceText) sourceText.textContent = sourceDate(source);
        autoRegionValue = ''; regionOverridden = false;
        if (selected.regionHint && [...region.options].some((option) => option.value === selected.regionHint)) {
          region.value = selected.regionHint; autoRegionValue = selected.regionHint;
        } else region.value = '';
        scope.querySelectorAll('input[name="profile-framework"]').forEach((radio) => { radio.checked = false; });
        results.replaceChildren(); pagination.replaceChildren();
        const warnings = Array.isArray(data.context?.warnings) ? data.context.warnings.map((warning) => text(warning, 300)).filter(Boolean) : [];
        const regionBasisLabels = { agency_hierarchy: '공식 상위기관 경로', official_name_prefix: '공식 기관명' };
        const regionBasisLabel = regionBasisLabels[selected.regionBasis] || '';
        const regionWarningPresent = warnings.some((warning) => /지역|시[·ㆍ]?도/.test(warning));
        const regionStatus = selected.regionHint ? ` 지역 기준: ${selected.regionHint}${regionBasisLabel ? ` (${regionBasisLabel})` : ''}.` : regionWarningPresent ? '' : ' 지역은 직접 선택해 주세요.';
        say(`기관을 선택했습니다.${regionStatus}${warnings.length ? ` ${warnings.join(' ')}` : ''} 국가·지방 공무원 구분은 직접 확인해 주세요.`);
        emitSelection();
      } catch (error) {
        if (error.name === 'AbortError' || disposed || token !== sequence) return;
        clearSelection({ clearRegion: true });
        say('기관 상세 정보를 확인하지 못했습니다. 다시 찾거나 기관명을 직접 입력해 주세요.');
      } finally { if (token === sequence) detailController = null; }
    }

    searchButton.addEventListener('click', () => search());
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); search(); }
    });
    input.addEventListener('input', () => {
      cancelRequests(); results.replaceChildren(); pagination.replaceChildren();
      if (selected && input.value.trim() !== selected.officialName) clearSelection({ manualEdit: true, clearRegion: true });
      if (input.value.trim().length < 2) say('기관명을 두 글자 이상 입력해 찾을 수 있습니다. 직접 입력도 가능합니다.');
      else { say('기관 검색을 준비하고 있습니다…'); debounceTimer = setTimeout(() => search(input.value.trim(), 1), 350); }
    });
    region.addEventListener('change', () => {
      if (selected) regionOverridden = region.value !== autoRegionValue;
      else regionOverridden = true;
    });
    form.addEventListener('reset', () => { cancelRequests(); });

    function clear(options = {}) {
      cancelRequests(); clearSelection({ clearInput: options.clearInput !== false, clearRegion: options.clearRegion !== false });
      results.replaceChildren(); pagination.replaceChildren(); say('기관명을 두 글자 이상 입력해 찾을 수 있습니다. 직접 입력도 가능합니다.');
    }
    function restore(value, selectedRegion = '') {
      const normalized = normalizeAgency(value);
      if (!normalized) { clear({ clearInput: false, clearRegion: false }); return false; }
      cancelRequests(); selected = normalized; input.value = normalized.officialName; parent.value = normalized.parentName;
      summary.textContent = `${[...normalized.ancestors.map((item) => item.fullName), normalized.officialName].join(' › ')} · 기관 코드 ${normalized.agencyCode}`;
      if (sourceText) sourceText.textContent = normalized.sourceUpdatedAt ? `자료 기준일: ${normalized.sourceUpdatedAt}` : '';
      autoRegionValue = normalized.regionHint; regionOverridden = Boolean(selectedRegion && selectedRegion !== autoRegionValue);
      const chosenRegion = selectedRegion || autoRegionValue;
      if (chosenRegion && [...region.options].some((option) => option.value === chosenRegion)) region.value = chosenRegion;
      results.replaceChildren(); pagination.replaceChildren(); say('저장된 공식 기관 선택을 불러왔습니다. 지역은 직접 변경할 수 있습니다.'); emitSelection(); return true;
    }
    function getSelection() { return selected ? { ...selected, ancestors: selected.ancestors.map((item) => ({ ...item })) } : null; }
    function dispose() { disposed = true; cancelRequests(); }
    return { getSelection, restore, clear, dispose };
  }

  window.SeomuAgencyPicker = { init, normalizeAgency };
})();
