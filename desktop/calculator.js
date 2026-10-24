(() => {
  const ERROR = '계산 오류';
  const ZERO_ERROR = '0으로 나눌 수 없어요';
  const numberFormat = (value) => {
    if (!Number.isFinite(value)) throw new Error('invalid');
    const rounded = Number(value.toPrecision(12));
    if (!Number.isFinite(rounded)) throw new Error('invalid');
    return String(Object.is(rounded, -0) ? 0 : rounded);
  };

  function calculate(source) {
    const numberToken = '(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?';
    const tokens = source.match(new RegExp(`${numberToken}|[()+\\-*/]`, 'g')) || [];
    if (!tokens.length || tokens.join('') !== source.replace(/\s/g, '')) throw new Error('invalid');
    let index = 0;
    const peek = () => tokens[index];
    const take = () => tokens[index++];
    function primary() {
      if (peek() === '(') {
        take(); const value = expression();
        if (take() !== ')') throw new Error('invalid');
        return value;
      }
      const token = take();
      if (!token || !/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(token)) throw new Error('invalid');
      const value = Number(token); if (!Number.isFinite(value)) throw new Error('invalid');
      return value;
    }
    function unary() {
      if (peek() === '+') { take(); return unary(); }
      if (peek() === '-') { take(); return -unary(); }
      return primary();
    }
    function term() {
      let value = unary();
      while (peek() === '*' || peek() === '/') {
        const op = take(); const right = unary();
        if (op === '/' && right === 0) throw new Error('division-by-zero');
        value = op === '*' ? value * right : value / right;
        if (!Number.isFinite(value)) throw new Error('invalid');
      }
      return value;
    }
    function expression() {
      let value = term();
      while (peek() === '+' || peek() === '-') {
        const op = take(); const right = term();
        value = op === '+' ? value + right : value - right;
        if (!Number.isFinite(value)) throw new Error('invalid');
      }
      return value;
    }
    const value = expression();
    if (index !== tokens.length) throw new Error('invalid');
    return value;
  }

  const instances = new WeakMap();
  function display(root, expression, value, isError = false) {
    root.querySelector('.calculator-expression').textContent = expression.replace(/\*/g, '×').replace(/\//g, '÷');
    const output = root.querySelector('.calculator-display'); output.textContent = value; output.classList.toggle('is-error', isError);
  }
  function getState(root) {
    let state = instances.get(root);
    if (!state) { state = { expression: '', result: '0', evaluated: false, error: false }; instances.set(root, state); }
    return state;
  }
  function render(root, state) {
    display(root, state.expression, state.result, state.error);
  }
  function press(root, key) {
    const state = getState(root);
    const isDigit = /^\d$/.test(key);
    if (key === 'clear') { state.expression = ''; state.result = '0'; state.evaluated = false; state.error = false; render(root, state); return; }
    if (key === 'backspace') {
      if (state.error || state.evaluated) { state.expression = ''; state.result = '0'; state.evaluated = false; state.error = false; }
      else { state.expression = state.expression.slice(0, -1); state.result = state.expression || '0'; }
      render(root, state); return;
    }
    if (key === 'equals') {
      if (!state.expression || state.error) return;
      try { state.result = numberFormat(calculate(state.expression)); state.expression = state.result; state.evaluated = true; state.error = false; }
      catch (error) { state.result = error.message === 'division-by-zero' ? ZERO_ERROR : ERROR; state.error = true; state.evaluated = false; }
      render(root, state); return;
    }
    if (isDigit || key === '.') {
      if (state.error || state.evaluated) { state.expression = ''; state.result = '0'; state.error = false; state.evaluated = false; }
      if (key === '.') {
        const current = state.expression.split(/[+\-*/()]/).pop();
        if (current.includes('.')) return;
        state.expression += current ? '.' : '0.';
      } else state.expression += key;
      state.result = state.expression; render(root, state); return;
    }
    if (/^[+\-*/()]$/.test(key)) {
      if (state.error) { state.expression = ''; state.result = '0'; state.error = false; }
      if (state.evaluated) state.evaluated = false;
      if (/[+*/-]$/.test(state.expression) && /^[+*/]$/.test(key)) state.expression = state.expression.slice(0, -1) + key;
      else state.expression += key;
      state.result = state.expression || '0'; render(root, state);
    }
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('.calculator-key[data-key]');
    if (!button) return;
    const root = button.closest('.app-window')?.querySelector('.calculator');
    if (!root) return;
    press(root, button.dataset.key);
  });
  document.addEventListener('keydown', (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const root = event.target.closest('.app-window')?.querySelector('.calculator');
    if (!root || !event.target.closest('.app-window')?.classList.contains('is-active')) return;
    const map = { Enter: 'equals', '=': 'equals', Backspace: 'backspace', Delete: 'clear', Escape: 'clear' };
    let key = map[event.key];
    if (/^\d$/.test(event.key) || ['.', '+', '-', '*', '/', '(', ')'].includes(event.key)) key = event.key;
    if (!key) return;
    event.preventDefault(); press(root, key);
  });
})();
