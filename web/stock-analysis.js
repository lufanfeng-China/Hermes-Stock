(() => {
  'use strict';

  const SEARCH_DEBOUNCE_MS = 200;
  const MAX_RECENT_STOCK_SEARCHES = 6;
  // Deliberately shared with 财务评分 so the two stock inputs have one history.
  const RECENT_STOCK_SEARCHES_STORAGE_KEY = 'stock-score-recent-searches';
  const input = document.getElementById('stock-input');
  const dropdown = document.getElementById('stock-dropdown');
  const form = document.getElementById('stock-analysis-search-form');
  if (!input || !dropdown || !form) return;

  const state = { timer: null, requestId: 0, selected: null, suggestions: [], recent: [] };

  const normalize = (row) => ({
    market: String(row?.market || '').trim().toLowerCase(),
    symbol: String(row?.symbol || '').trim(),
    stock_name: String(row?.stock_name || row?.name || row?.symbol || '').trim(),
  });
  const identity = (row) => `${row.market}:${row.symbol}`;
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
  const normalizeMarket = (code) => {
    const first = String(code || '').trim()[0];
    if (['6', '5', '9'].includes(first)) return 'sh';
    if (['0', '3'].includes(first)) return 'sz';
    if (['4', '8'].includes(first)) return 'bj';
    return null;
  };
  const selectedLabel = (row) => `${row.stock_name} (${row.symbol})`;

  function getRecent() {
    try {
      const rows = JSON.parse(localStorage.getItem(RECENT_STOCK_SEARCHES_STORAGE_KEY) || '[]');
      return Array.isArray(rows)
        ? rows.map(normalize).filter((row) => row.market && row.symbol).slice(0, MAX_RECENT_STOCK_SEARCHES)
        : [];
    } catch { return []; }
  }

  function saveRecent(row) {
    const normalized = normalize(row);
    if (!normalized.market || !normalized.symbol) return;
    const next = [normalized, ...getRecent().filter((item) => identity(item) !== identity(normalized))]
      .slice(0, MAX_RECENT_STOCK_SEARCHES);
    state.recent = next;
    try { localStorage.setItem(RECENT_STOCK_SEARCHES_STORAGE_KEY, JSON.stringify(next)); } catch { /* no-op */ }
  }

  function show(rows, source = 'suggestions') {
    state.suggestions = source === 'suggestions' ? rows : state.suggestions;
    state.recent = source === 'recent' ? rows : state.recent;
    if (!rows.length) {
      dropdown.innerHTML = `<div class="search-option empty">${source === 'recent' ? '暂无最近搜索' : '未找到匹配股票'}</div>`;
    } else {
      dropdown.innerHTML = rows.map((row, index) => `
        <button type="button" class="search-option${source === 'recent' ? ' recent-search' : ''}" data-index="${index}" data-source="${source}">
          <span class="search-option-main">${escapeHtml(row.stock_name)}</span>
          <span class="search-option-meta">${source === 'recent' ? 'recent-search · ' : ''}${escapeHtml(row.market.toUpperCase())} · ${escapeHtml(row.symbol)}</span>
        </button>`).join('');
    }
    dropdown.classList.add('visible');
  }

  function hide() { dropdown.classList.remove('visible'); }

  async function fetchSuggestions(query) {
    const response = await fetch(`/api/search/stocks?q=${encodeURIComponent(query)}&limit=10`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || `HTTP ${response.status}`);
    return (payload.results || []).map(normalize).filter((row) => row.market && row.symbol);
  }

  async function loadSuggestions(query) {
    const requestId = ++state.requestId;
    const trimmed = query.trim();
    if (!trimmed) { show(getRecent(), 'recent'); return; }
    try {
      const rows = await fetchSuggestions(trimmed);
      if (requestId === state.requestId) show(rows, 'suggestions');
    } catch {
      if (requestId === state.requestId) {
        dropdown.innerHTML = '<div class="search-option empty">搜索失败</div>';
        dropdown.classList.add('visible');
      }
    }
  }

  function latestRowsByYear(reports) {
    const latestByYear = new Map();
    for (const row of reports || []) {
      const year = String(row?.year || '').slice(0, 4);
      if (!/^\d{4}$/.test(year)) continue;
      const previous = latestByYear.get(year);
      if (!previous || String(row?.report_date || '') > String(previous?.report_date || '')) latestByYear.set(year, row);
    }
    return [...latestByYear.values()].sort((a, b) => String(a.year).localeCompare(String(b.year))).slice(-5);
  }

  function periodLabel(row) {
    const period = String(row?.period || '');
    return `${String(row?.year || '').slice(-2)}${period.endsWith('A') ? '' : period.slice(4)}`;
  }

  function renderBars(targetId, rows, values, formatter, variant) {
    const target = document.getElementById(targetId);
    const numeric = values.filter(Number.isFinite);
    if (!rows.length || !numeric.length) { target.textContent = '暂无可用数据'; return; }
    const maxAbs = Math.max(...numeric.map((value) => Math.abs(value)), 1);
    const min = Math.min(0, ...numeric);
    const max = Math.max(0, ...numeric);
    const range = Math.max(max - min, 1);
    const zero = max / range * 100;
    const isGrowth = variant === 'growth';
    target.className = 'analysis-bar-chart';
    target.innerHTML = rows.map((row, index) => {
      const value = values[index];
      const label = Number.isFinite(value) ? formatter(value) : '—';
      if (isGrowth) {
        const direction = value < 0 ? 'negative' : 'positive';
        const barSize = Number.isFinite(value) ? Math.max(3, Math.abs(value) / range * 100) : 3;
        return `<div class="analysis-bar-item analysis-growth-item"><span class="analysis-bar-value">${label}</span><div class="analysis-bar-plot" style="--zero:${zero}%"><span class="analysis-zero-axis"></span><div class="analysis-bar growth ${direction}" style="--bar-size:${barSize}%"></div></div><span class="analysis-bar-year">${periodLabel(row)}</span></div>`;
      }
      const height = Number.isFinite(value) ? Math.max(3, Math.abs(value) / maxAbs * 100) : 3;
      return `<div class="analysis-bar-item"><span class="analysis-bar-value">${label}</span><div class="analysis-bar ${variant}" style="height:${height}%"></div><span class="analysis-bar-year">${periodLabel(row)}</span></div>`;
    }).join('');
  }

  function renderAnnualBars(targetId, reports, metricKey, variant) {
    const rows = latestRowsByYear(reports);
    renderBars(targetId, rows, rows.map((row) => Number(row?.metrics?.[metricKey])), (value) => (value / 1e8).toFixed(1), variant);
  }

  function renderYoYGrowthBars(targetId, reports, metricKey) {
    const rows = latestRowsByYear(reports);
    const byPeriod = new Map((reports || []).map((row) => [String(row?.period || ''), row]));
    const values = rows.map((row) => {
      const year = Number(row?.year);
      const period = String(row?.period || '');
      const prior = byPeriod.get(`${year - 1}${period.slice(4)}`);
      const currentValue = Number(row?.metrics?.[metricKey]);
      const priorValue = Number(prior?.metrics?.[metricKey]);
      return Number.isFinite(currentValue) && Number.isFinite(priorValue) && priorValue !== 0
        ? (currentValue / priorValue - 1) * 100 : NaN;
    });
    renderBars(targetId, rows, values, (value) => `${value.toFixed(1)}%`, 'growth');
  }

  async function loadAnnualFinancials(stock) {
    for (const id of ['revenue-chart', 'revenue-growth-chart', 'profit-chart', 'net-profit-growth-chart', 'total-profit-chart', 'total-profit-growth-chart']) {
      const el = document.getElementById(id);
      el.className = 'analysis-metric-status';
      el.textContent = '加载最近五年年度数据…';
    }
    try {
      // Request one extra year so the earliest displayed point can be compared
      // with the matching report period a year earlier.
      const response = await fetch(`/api/stock-score-report-history?market=${encodeURIComponent(stock.market)}&symbol=${encodeURIComponent(stock.symbol)}&years=6`);
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || `HTTP ${response.status}`);
      renderAnnualBars('revenue-chart', payload.reports, 'revenue', 'revenue');
      renderYoYGrowthBars('revenue-growth-chart', payload.reports, 'revenue');
      renderAnnualBars('profit-chart', payload.reports, 'net_profit', 'profit');
      renderYoYGrowthBars('net-profit-growth-chart', payload.reports, 'net_profit');
      renderAnnualBars('total-profit-chart', payload.reports, 'profit', 'profit');
      renderYoYGrowthBars('total-profit-growth-chart', payload.reports, 'profit');
    } catch (error) {
      for (const id of ['revenue-chart', 'revenue-growth-chart', 'profit-chart', 'net-profit-growth-chart', 'total-profit-chart', 'total-profit-growth-chart']) document.getElementById(id).textContent = `加载失败：${error.message}`;
    }
  }

  function apply(row) {
    const stock = normalize(row);
    if (!stock.market || !stock.symbol) return;
    state.selected = stock;
    input.value = selectedLabel(stock);
    saveRecent(stock);
    hide();
    const params = new URLSearchParams({ market: stock.market, symbol: stock.symbol, name: stock.stock_name });
    history.replaceState(null, '', `${location.pathname}?${params}`);
    loadAnnualFinancials(stock);
    window.dispatchEvent(new CustomEvent('stock-analysis:select', { detail: stock }));
  }

  function chooseFromInput() {
    if (state.selected) return apply(state.selected);
    if (state.suggestions.length) return apply(state.suggestions[0]);
    const value = input.value.trim();
    const [marketPart, symbolPart] = value.split(':', 2);
    const symbol = symbolPart ? symbolPart.trim() : value.replace(/\D/g, '');
    const market = symbolPart ? marketPart.trim().toLowerCase() : normalizeMarket(symbol);
    if (market && symbol) apply({ market, symbol, stock_name: symbol });
  }

  input.addEventListener('input', (event) => {
    if (state.selected && event.target.value !== selectedLabel(state.selected)) state.selected = null;
    clearTimeout(state.timer);
    state.timer = setTimeout(() => loadSuggestions(event.target.value), SEARCH_DEBOUNCE_MS);
  });
  input.addEventListener('focus', () => { if (!input.value.trim()) show(getRecent(), 'recent'); });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') hide();
  });
  form.addEventListener('submit', (event) => { event.preventDefault(); chooseFromInput(); });
  dropdown.addEventListener('click', (event) => {
    const option = event.target.closest('.search-option[data-index]');
    if (!option) return;
    const rows = option.dataset.source === 'recent' ? state.recent : state.suggestions;
    apply(rows[Number(option.dataset.index)]);
  });
  document.addEventListener('click', (event) => { if (!form.contains(event.target)) hide(); });

  const params = new URLSearchParams(location.search);
  const market = params.get('market');
  const symbol = params.get('symbol');
  if (market && symbol) {
    const stock = normalize({ market, symbol, stock_name: params.get('name') || symbol });
    state.selected = stock;
    input.value = selectedLabel(stock);
    loadAnnualFinancials(stock);
  }
})();
