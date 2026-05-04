const SEARCH_DEBOUNCE_MS = 200;
const MAX_RECENT_STOCK_SEARCHES = 6;
const RELATIVE_VALUATION_RECENT_SEARCHES_STORAGE_KEY = 'relative-valuation-recent-searches';

const relativeValuationInputEl = document.getElementById('relative-valuation-input');
const relativeValuationDropdownEl = document.getElementById('relative-valuation-dropdown');
const relativeValuationStatusEl = document.getElementById('relative-valuation-status');

const relativeValuationState = {
  timer: null,
  requestId: 0,
  selectedStock: null,
  suggestions: [],
  recentSearches: [],
  dropdownMode: 'suggestions',
};

function inferMarketFromInput(text) {
  const value = String(text || '').trim();
  if (!value) return null;
  const prefixed = value.match(/^(sh|sz|bj)\s*:\s*(\d{6})$/i);
  if (prefixed) return { market: prefixed[1].toLowerCase(), symbol: prefixed[2] };
  const plain = value.match(/^(\d{6})$/);
  if (!plain) return null;
  const symbol = plain[1];
  if (symbol.startsWith('6')) return { market: 'sh', symbol };
  if (symbol.startsWith('00') || symbol.startsWith('30')) return { market: 'sz', symbol };
  if (symbol.startsWith('92')) return { market: 'bj', symbol };
  return null;
}

function toStockIdentity(row) {
  if (!row?.market || !row?.symbol) return '';
  return `${String(row.market).toLowerCase()}:${String(row.symbol).trim()}`;
}

function formatNumber(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value ?? '—';
}

function loadRecentStockSearches() {
  try {
    const raw = localStorage.getItem(RELATIVE_VALUATION_RECENT_SEARCHES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((row) => row && row.market && row.symbol)
      .map((row) => ({
        market: String(row.market).toLowerCase(),
        symbol: String(row.symbol).trim(),
        stock_name: String(row.stock_name || row.name || row.symbol).trim(),
      }))
      .slice(0, MAX_RECENT_STOCK_SEARCHES);
  } catch {
    return [];
  }
}

function saveRecentStockSearch(stock) {
  if (!stock?.market || !stock?.symbol) return;
  const normalized = {
    market: String(stock.market).toLowerCase(),
    symbol: String(stock.symbol).trim(),
    stock_name: String(stock.stock_name || stock.name || stock.symbol).trim(),
  };
  const identity = toStockIdentity(normalized);
  const nextItems = [
    normalized,
    ...loadRecentStockSearches().filter((row) => toStockIdentity(row) !== identity),
  ].slice(0, MAX_RECENT_STOCK_SEARCHES);
  relativeValuationState.recentSearches = nextItems;
  try {
    localStorage.setItem(RELATIVE_VALUATION_RECENT_SEARCHES_STORAGE_KEY, JSON.stringify(nextItems));
  } catch {
    // ignore storage errors
  }
}

function hideSuggestions() {
  relativeValuationDropdownEl.classList.remove('visible');
}

function renderRecentStockSearches() {
  const items = loadRecentStockSearches().slice(0, MAX_RECENT_STOCK_SEARCHES);
  relativeValuationState.recentSearches = items;
  relativeValuationState.dropdownMode = 'recent-search';
  relativeValuationState.suggestions = [];
  if (!items.length) {
    relativeValuationDropdownEl.innerHTML = '<div class="search-option empty recent-search">暂无最近搜索</div>';
    relativeValuationDropdownEl.classList.add('visible');
    return;
  }
  relativeValuationDropdownEl.innerHTML = items.map((row, index) => (
    `<button type="button" class="search-option recent-search" data-index="${index}" data-source="recent-search">` +
      `<span class="search-option-main">${row.stock_name}</span>` +
      `<span class="search-option-meta">recent-search · ${row.market.toUpperCase()} · ${row.symbol}</span>` +
    `</button>`
  )).join('');
  relativeValuationDropdownEl.classList.add('visible');
}

function renderSuggestions(results) {
  relativeValuationState.dropdownMode = 'suggestions';
  relativeValuationState.suggestions = results;
  if (!results.length) {
    relativeValuationDropdownEl.innerHTML = '<div class="search-option empty">未找到匹配股票</div>';
    relativeValuationDropdownEl.classList.add('visible');
    return;
  }
  relativeValuationDropdownEl.innerHTML = results.map((row, index) => (
    `<button type="button" class="search-option" data-index="${index}">` +
      `<span class="search-option-main">${row.stock_name}</span>` +
      `<span class="search-option-meta">${row.market.toUpperCase()} · ${row.symbol}</span>` +
    `</button>`
  )).join('');
  relativeValuationDropdownEl.classList.add('visible');
}

async function fetchStockSuggestions(query) {
  const response = await fetch(`/api/search/stocks?q=${encodeURIComponent(query)}&limit=10`);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload?.error?.message || payload?.error || 'stock search unavailable');
  }
  return Array.isArray(payload.results) ? payload.results : [];
}

async function loadSuggestions(query) {
  const trimmed = query.trim();
  const requestId = ++relativeValuationState.requestId;
  if (!trimmed) {
    renderRecentStockSearches();
    return;
  }
  try {
    const results = await fetchStockSuggestions(trimmed);
    if (requestId !== relativeValuationState.requestId) return;
    renderSuggestions(results.slice(0, 10));
  } catch {
    if (requestId !== relativeValuationState.requestId) return;
    relativeValuationDropdownEl.innerHTML = '<div class="search-option empty">搜索失败</div>';
    relativeValuationDropdownEl.classList.add('visible');
  }
}

function applySuggestion(row) {
  if (!row) return;
  relativeValuationState.selectedStock = row;
  relativeValuationInputEl.value = `${row.stock_name} (${row.symbol})`;
  hideSuggestions();
  runRelativeValuationQuery(row);
}

function renderTemperatureHistory(history) {
  const host = document.getElementById('relative-valuation-temperature-history');
  const rows = Array.isArray(history) ? history : [];
  if (!rows.length) {
    host.innerHTML = '<span class="result-empty">暂无历史数据</span>';
    return;
  }
  host.innerHTML = rows.slice(-12).reverse().map((row) => (
    `<button type="button" class="result-item"><strong>${row.trading_day || '—'}</strong><span>行业加权PE ${formatNumber(row.weighted_pe_ttm)}</span></button>`
  )).join('');
}

function renderRiskFlags(flags, notes) {
  const host = document.getElementById('relative-valuation-risk-flags');
  const merged = [...(Array.isArray(flags) ? flags : []), ...(Array.isArray(notes) ? notes : [])].filter(Boolean);
  if (!merged.length) {
    host.innerHTML = '<span class="result-empty">暂无风险提示</span>';
    return;
  }
  host.innerHTML = merged.map((item) => `<button type="button" class="result-item">${item}</button>`).join('');
}

function formatPrimaryMetricLabel(primaryMetric) {
  if (primaryMetric === 'pe_ttm') return '当前按 PE-TTM 排位';
  if (primaryMetric === 'ps_ttm') return '当前按 PS-TTM 排位';
  return '待加载主指标说明';
}

function formatClassificationDisplay(payload) {
  const classification = payload?.classification || '';
  const subClassification = payload?.sub_classification || '';
  if (classification === 'A_NORMAL_EARNING') return 'A类 正常盈利';
  if (classification === 'B_THIN_PROFIT_DISTORTED') return 'B类 微盈利畸高';
  if (classification === 'C_LOSS') {
    if (subClassification === 'C4_LIQUIDATION_RISK' || subClassification === 'C3_NO_REVENUE_CONCEPT') {
      return 'D类 高风险例外';
    }
    return 'C类 亏损经营';
  }
  return classification || '未分类';
}

function formatPrimaryPercentileEmptyReason(payload) {
  if (payload?.sample_status === 'insufficient') return '样本不足，暂不输出行业内估值位置';
  if (payload?.sample_status === 'new_listing' || payload?.is_new_listing) return '次新股，暂不输出行业内估值位置';
  const classification = payload?.classification || '';
  const subClassification = payload?.sub_classification || '';
  if (classification === 'C_LOSS' && (subClassification === 'C3_NO_REVENUE_CONCEPT' || subClassification === 'C4_LIQUIDATION_RISK')) {
    return 'D类高风险例外，原则上不做估值分位';
  }
  return '当前暂无可比样本，暂不输出行业内估值位置';
}

function renderRelativeValuation(payload) {
  setText('rv-name', payload.stock_name || '—');
  setText('rv-symbol', payload.symbol || '—');
  setText('rv-classification', formatClassificationDisplay(payload));
  setText('rv-band', payload.valuation_band_label || '待查询');
  setText('rv-ind1', payload.industry_level_1_name || '—');
  setText('rv-ind2', payload.industry_level_2_name || '—');
  setText('rv-industry-valid-count', payload.industry_valid_member_count != null ? String(payload.industry_valid_member_count) : '—');
  setText('rv-sample-status', payload.sample_status || '—');
  setText('rv-industry-pe', formatNumber(payload.industry_weighted_pe_ttm));
  setText('rv-industry-ps', formatNumber(payload.industry_weighted_ps_ttm));
  setText('rv-pe-threshold', formatNumber(payload.dynamic_pe_invalid_threshold));
  const tempLabel = payload.industry_temperature_label || '暂无';
  const tempPct = payload.industry_temperature_percentile_since_2022 != null ? `${formatNumber(payload.industry_temperature_percentile_since_2022)}%` : '—';
  setText('rv-temperature', `${tempLabel} / ${tempPct}`);
  setText('rv-pe', formatNumber(payload.pe_ttm));
  setText('rv-ps', formatNumber(payload.ps_ttm));
  setText('rv-primary-percentile', payload.primary_percentile != null ? `${formatNumber(payload.primary_percentile)}%` : '—');
  const primaryMetric = payload.primary_percentile_metric || '待加载';
  const primaryMetricLabel = payload.primary_percentile != null
    ? formatPrimaryMetricLabel(primaryMetric)
    : formatPrimaryPercentileEmptyReason(payload);
  setText('rv-primary-metric-label', primaryMetricLabel);
  setText('rv-primary-metric', primaryMetric === 'pe_ttm' ? 'PE-TTM' : primaryMetric === 'ps_ttm' ? 'PS-TTM' : primaryMetric);
  setText('rv-valuation-band', payload.valuation_band_label || '—');
  renderTemperatureHistory(payload.industry_temperature_history);
  renderRiskFlags(payload.risk_flags, payload.notes);
}

async function fetchRelativeValuation(identity) {
  const response = await fetch(`/api/relative-valuation?market=${encodeURIComponent(identity.market)}&symbol=${encodeURIComponent(identity.symbol)}`);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload?.error?.message || payload?.error || 'relative valuation unavailable');
  }
  return payload;
}

async function resolveRelativeValuationIdentity(identity, rawInput) {
  if (identity) return identity;
  const suggestions = await fetchStockSuggestions(rawInput);
  if (suggestions.length === 1) {
    return { market: suggestions[0].market, symbol: suggestions[0].symbol };
  }
  return null;
}

async function runRelativeValuationQuery(selectedRow = null) {
  const rawValue = relativeValuationInputEl.value;
  const baseIdentity = selectedRow ? { market: selectedRow.market, symbol: selectedRow.symbol } : inferMarketFromInput(rawValue);
  let identity = baseIdentity;
  if (!identity) {
    relativeValuationStatusEl.textContent = '正在匹配股票...';
    try {
      identity = await resolveRelativeValuationIdentity(baseIdentity, rawValue.trim());
    } catch (error) {
      relativeValuationStatusEl.textContent = `估值查询失败: ${error.message}`;
      return;
    }
  }
  if (!identity) {
    relativeValuationStatusEl.textContent = '请输入 6 位代码、market:symbol，或输入可唯一匹配的股票名称';
    return;
  }
  relativeValuationStatusEl.textContent = '正在查询相对估值...';
  try {
    const payload = await fetchRelativeValuation(identity);
    renderRelativeValuation(payload);
    saveRecentStockSearch({ market: payload.market, symbol: payload.symbol, stock_name: payload.stock_name });
    relativeValuationStatusEl.textContent = `${payload.stock_name || identity.symbol} 相对估值加载完成`;
  } catch (error) {
    relativeValuationStatusEl.textContent = `估值查询失败: ${error.message}`;
  }
}

document.getElementById('relative-valuation-search-btn').addEventListener('click', () => runRelativeValuationQuery());
relativeValuationInputEl.addEventListener('input', (event) => {
  const value = event.target.value;
  if (relativeValuationState.selectedStock) {
    const selectedLabel = `${relativeValuationState.selectedStock.stock_name} (${relativeValuationState.selectedStock.symbol})`;
    if (value !== selectedLabel) relativeValuationState.selectedStock = null;
  }
  window.clearTimeout(relativeValuationState.timer);
  relativeValuationState.timer = window.setTimeout(() => {
    loadSuggestions(value);
  }, SEARCH_DEBOUNCE_MS);
});
relativeValuationInputEl.addEventListener('focus', () => {
  renderRecentStockSearches();
});
relativeValuationInputEl.addEventListener('click', () => {
  renderRecentStockSearches();
});
relativeValuationInputEl.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    if (relativeValuationState.selectedStock) {
      runRelativeValuationQuery(relativeValuationState.selectedStock);
    } else if (relativeValuationState.suggestions.length === 1) {
      applySuggestion(relativeValuationState.suggestions[0]);
    } else {
      runRelativeValuationQuery();
    }
    hideSuggestions();
  }
});
relativeValuationDropdownEl.addEventListener('click', (event) => {
  const option = event.target.closest('.search-option[data-index]');
  if (!option) return;
  const index = Number(option.dataset.index);
  const list = option.dataset.source === 'recent-search'
    ? relativeValuationState.recentSearches
    : relativeValuationState.suggestions;
  applySuggestion(list[index]);
});
