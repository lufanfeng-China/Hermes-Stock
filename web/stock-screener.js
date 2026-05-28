import { KlineChart } from './kline-chart.js?v=20260513-ma';

const PAGE_SIZE = 50;
const STRATEGY_PRESETS = {
  rps_first: {
    strategy: 'rps_first',
    description: '任意3个RPS≥85且余下≥75，且过去60个交易日首次满足',
  },
  ma_cross: {
    strategy: 'ma_cross',
    description: 'MA5上穿MA20 + MA30>MA5>MA20>MA10 + 阳线 + MA5/MA10向上 + 均线粘合<10%',
  },
  washout: {
    strategy: 'washout',
    description: '30日内有首板涨停; 次日高开低走且量2-4倍; 最新价首次站上洗盘日开盘',
  },
  rps_climb: {
    strategy: 'rps_climb',
    description: 'RPS20>50>120>250多头排列; RPS20>50; RPS20/50/120连续3天高于5日前',
  },
  blowup_stall: {
    strategy: 'blowup_stall',
    description: '放巨量但涨不动：量>2.5x50日均量 + 阳线 + 涨幅<2% + 距20日最高≤2% + 冲高回落/高位, 按信号强度排序',
  },
  blowup_break: {
    strategy: 'blowup_break',
    description: '连续两天真阳线上涨; 每天量>3倍50日均量; 涨前5天量均<2倍50日均量',
  },
};
let currentPage = 1;
let currentPayload = { rows: [], total: 0, page: 1, total_pages: 1 };
let klineChart = null;
let currentKlinePreset = 60;
let industryHierarchy = [];

const form = document.getElementById('stock-screener-filter-form');
const statusEl = document.getElementById('stock-screener-status');
const tbody = document.getElementById('stock-screener-results-tbody');
const countEl = document.getElementById('stock-screener-count');
const pageInfoEl = document.getElementById('stock-screener-page-info');
const prevBtn = document.getElementById('stock-screener-prev');
const nextBtn = document.getElementById('stock-screener-next');
const level1El = document.getElementById('stock-screener-level1');
const level2El = document.getElementById('stock-screener-level2');
const filterToggleEl = document.getElementById('stock-screener-filter-toggle');
const strategyButtonsEl = document.getElementById('stock-screener-strategy-buttons');
const strategyInputEl = form?.elements?.namedItem('strategy');
const temperatureSelectEl = document.getElementById('stock-screener-temperature');
const asOfDateInput = document.getElementById('stock-screener-asof-date');
const asOfDateDisplay = document.getElementById('stock-screener-asof-display');
const asOfDateText = document.getElementById('stock-screener-asof-text');
const asOfDropdown = document.getElementById('stock-screener-asof-dropdown');
const asOfDaysGrid = document.getElementById('asof-days-grid');
const asOfMonthLabel = document.getElementById('asof-month-label');
const asOfPrevBtn = document.getElementById('asof-prev-month');
const asOfNextBtn = document.getElementById('asof-next-month');

// Calendar state
let tradingDaysSet = new Set();
let calendarYear = 2026;
let calendarMonth = 5;
let selectedDate = '';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatNumber(value, digits = 2) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}

function formatRank(rank, universe) {
  if (rank == null || rank === '') return '—';
  return universe ? `${rank}/${universe}` : String(rank);
}

function formatPercentile(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(1)}%`;
}

function formatMarketCapYi(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(1)}亿`;
}

function collectMultiSelectValues(selectEl) {
  if (!selectEl?.multiple) return [];
  return [...selectEl.selectedOptions]
    .map((option) => String(option.value || '').trim())
    .filter(Boolean);
}

function buildParams(page = currentPage) {
  const params = new URLSearchParams();
  const data = new FormData(form);
  for (const [key, value] of data.entries()) {
    if (key === 'industry_temperature_label' && temperatureSelectEl?.multiple) {
      continue;
    }
    const text = String(value || '').trim();
    if (text) params.set(key, text);
  }
  const temperatureLabels = collectMultiSelectValues(temperatureSelectEl);
  if (temperatureLabels.length) {
    params.set('industry_temperature_label', temperatureLabels.join(','));
  }
  const valuationBandEl = document.getElementById('stock-screener-valuation-band');
  const valuationBands = collectMultiSelectValues(valuationBandEl);
  if (valuationBands.length) {
    params.set('valuation_band', valuationBands.join(','));
  }
  const level1Values = collectMultiSelectValues(level1El);
  if (level1Values.length) {
    params.set('industry_level_1', level1Values.join(','));
  }
  const level2Values = collectMultiSelectValues(level2El);
  if (level2Values.length) {
    params.set('industry_level_2', level2Values.join(','));
  }
  const asOfDate = asOfDateInput?.value?.trim();
  if (asOfDate) params.set('as_of_date', asOfDate);
  params.set('page', String(page));
  params.set('page_size', String(PAGE_SIZE));
  return params;
}

async function loadIndustryHierarchy() {
  try {
    const response = await fetch('/api/industry-hierarchy');
    const payload = await response.json();
    if (!payload.ok) return;
    industryHierarchy = payload.industries || [];
    level1El.innerHTML = '<option value="">全部</option>';
    for (const row of industryHierarchy) {
      const option = document.createElement('option');
      option.value = row.name;
      option.textContent = row.name;
      level1El.appendChild(option);
    }
    populateLevel2('');
  } catch (error) {
    console.warn('industry hierarchy unavailable', error);
  }
}

function populateLevel2(level1Names) {
  const names = Array.isArray(level1Names) ? level1Names : (level1Names ? [level1Names] : []);
  const values = new Set();
  for (const level1 of industryHierarchy) {
    if (names.length && !names.includes(level1.name)) continue;
    for (const level2 of level1.level2 || []) values.add(level2);
  }
  level2El.innerHTML = '<option value="">全部</option>';
  [...values].sort().forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    level2El.appendChild(option);
  });
}

function toggleScreenerFilters() {
  const willExpand = form.hidden;
  form.hidden = !willExpand;
  filterToggleEl.setAttribute('aria-expanded', String(willExpand));
  filterToggleEl.textContent = willExpand ? '收起筛选' : '展开筛选';
}

function setActiveStrategyButton(strategy) {
  strategyButtonsEl?.querySelectorAll('[data-strategy]').forEach((button) => {
    button.classList.toggle('active', button.dataset.strategy === strategy);
  });
}

function clearManualFilters() {
  // Preserve date and strategy before reset
  const savedDate = asOfDateInput?.value || '';
  const savedStrategy = strategyInputEl?.value || '';
  form.reset();
  // Restore
  if (asOfDateInput && savedDate) asOfDateInput.value = savedDate;
  if (strategyInputEl && savedStrategy) strategyInputEl.value = savedStrategy;
  if (temperatureSelectEl?.multiple) {
    [...temperatureSelectEl.options].forEach((option) => {
      option.selected = false;
    });
  }
  populateLevel2('');
}

function collapseScreenerFiltersAfterStrategy() {
  form.hidden = true;
  filterToggleEl.setAttribute('aria-expanded', 'false');
  filterToggleEl.textContent = '展开筛选';
}

function applyStrategyPreset(strategy) {
  const preset = STRATEGY_PRESETS[strategy];
  if (!preset) return;
  clearManualFilters();
  if (strategyInputEl) {
    strategyInputEl.value = preset.strategy;
  }
  setActiveStrategyButton(preset.strategy);
  const descEl = document.getElementById('stock-screener-strategy-desc');
  if (descEl) {
    descEl.textContent = preset.description || '';
  }
  collapseScreenerFiltersAfterStrategy();
  currentPage = 1;
  runScreener(1);
}

function renderScreenerLoadingState() {
  currentPayload = { rows: [], total: 0, page: 1, total_pages: 1 };
  countEl.textContent = '…';
  pageInfoEl.textContent = '正在筛选...';
  tbody.innerHTML = '<tr><td colspan="15" class="stock-score-empty-row">正在筛选，请稍候...</td></tr>';
}

async function runScreener(page = 1) {
  currentPage = page;
  statusEl.textContent = '正在筛选...';
  renderScreenerLoadingState();
  const params = buildParams(page);
  try {
    const response = await fetch(`/api/stock-screener?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.error?.message || payload?.error || `HTTP ${response.status}`);
    }
    currentPayload = payload;
    currentPage = payload.page || page;
    renderScreenerRows(payload.rows || []);
    renderPagination(payload);
    // Update watchlist toolbar + highlight rows
    updateWatchlistToolbar();
    rerenderCurrentRows();
    statusEl.textContent = `命中 ${payload.total || 0} 只股票，当前页 ${(payload.rows || []).length} 条`;
    const dateEl = document.getElementById('stock-screener-data-date');
    if (dateEl) {
      const parts = [];
      if (payload.is_historical) {
        parts.push(`回测日期：${payload.effective_date || payload.data_date || '—'}`);
        if (payload.data_date && payload.data_date !== payload.effective_date) {
          parts.push(`RPS 实际数据日：${payload.data_date}`);
        }
        if (!payload.tech_eval_ready) {
          parts.push('⚠ 技术面数据生成中，当前技术面筛选不可用');
        }
        if (payload.is_historical && payload.strategy_ready === false) {
          parts.push('⚠ 策略数据生成中，预设方案暂时不可用');
        }
      } else if (payload.data_date) {
        parts.push(`RPS 数据日期：${payload.data_date}`);
      }
      dateEl.textContent = parts.join(' · ');
    }
  } catch (error) {
    statusEl.textContent = `筛选失败：${error.message}`;
    tbody.innerHTML = '<tr><td colspan="13" class="stock-score-empty-row">筛选失败，请调整条件后重试</td></tr>';
  }
}

function renderScreenerRows(rows) {
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="13" class="stock-score-empty-row">没有符合条件的股票</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row, idx) => {
    const industryText = [row.industry_level_1, row.industry_level_2].filter(Boolean).join(' / ') || '—';
    const marketSymbol = `${String(row.market || '').toUpperCase()}:${row.symbol || ''}`;
    return `<tr class="stock-screener-row" tabindex="0" data-market="${escapeHtml(row.market)}" data-symbol="${escapeHtml(row.symbol)}" data-name="${escapeHtml(row.stock_name || row.symbol)}">
      <td class="stock-screener-check-col"><input type="checkbox" class="stock-screener-row-check" data-idx="${idx}"></td>
      <td><strong>${escapeHtml(row.stock_name || row.symbol)}</strong><span class="stock-screener-symbol">${escapeHtml(marketSymbol)}</span></td>
      <td class="num">${formatNumber(row.current_price, 2)}</td>
      <td class="num">${formatNumber(row.pe_ttm, 2)}</td>
      <td class="num">${formatNumber((row.rps_20||0)+(row.rps_50||0)+(row.rps_120||0)+(row.rps_250||0), 0)} / ${formatNumber(row.rps_20, 0)}/${formatNumber(row.rps_50, 0)}/${formatNumber(row.rps_120, 0)}/${formatNumber(row.rps_250, 0)}</td>
      <td class="num">${formatNumber(row.swing_low_price, 2)}</td>
      <td class="num">${formatRank(row.market_total_rank, row.market_total_universe_size)}</td>
      <td class="num">${formatRank(row.industry_total_rank, row.industry_total_universe_size)}</td>
      <td>${escapeHtml(row.valuation_band_label || '—')}</td>
      <td class="num">${formatPercentile(row.primary_percentile)}</td>
      <td>${escapeHtml(row.industry_temperature_label || '—')}<span class="stock-screener-symbol">${escapeHtml(formatPercentile(row.industry_temperature_percentile_since_2022))}</span></td>
      <td>${escapeHtml(industryText)}</td>
      <td class="num">${formatNumber(row.industry_total_score, 1)}</td>
    </tr>`;
  }).join('');
}

function renderPagination(payload) {
  const page = payload.page || 1;
  const totalPages = payload.total_pages || 1;
  countEl.textContent = String(payload.total || 0);
  pageInfoEl.textContent = `第 ${page} / ${totalPages} 页 · 每页 ${payload.page_size || PAGE_SIZE} 条`;
  prevBtn.disabled = page <= 1;
  nextBtn.disabled = page >= totalPages;
}

async function loadScreenerKline(row) {
  const symbol = row?.dataset?.symbol;
  const name = row?.dataset?.name || symbol;
  if (!symbol) return;
  document.querySelectorAll('.stock-screener-row').forEach((tr) => tr.classList.toggle('row-selected', tr === row));

  document.getElementById('stock-screener-kline-section').classList.remove('hidden');
  document.getElementById('stock-screener-kline-title').textContent = `${symbol} — 加载中…`;

  try {
    const [klineRes, rpsRes] = await Promise.all([
      fetch(`/api/stock-kline?symbol=${encodeURIComponent(symbol)}&limit=300`),
      fetch(`/api/stock-rps-history?symbol=${encodeURIComponent(symbol)}`),
    ]);
    const klineJson = await klineRes.json();
    const rpsJson = await rpsRes.json();

    if (!klineJson.ok) {
      document.getElementById('stock-screener-kline-title').textContent = `${symbol} — 数据不可用`;
      return;
    }

    const bars = klineJson.bars || [];
    const rpsHistory = (rpsJson.history || []).map(h => ({
      trading_day: h.trading_day,
      rps_20: h.rps_20,
      rps_50: h.rps_50,
      rps_120: h.rps_120,
      rps_250: h.rps_250,
    }));

    const svg = document.getElementById('stock-screener-kline-svg');
    if (!klineChart) {
      klineChart = createScreenerKlineChart(svg);
    }

    klineChart.load(bars, rpsHistory, currentKlinePreset);
    const stockName = bars[0]?.name || name || symbol;
    document.getElementById('stock-screener-kline-title').textContent = `${symbol} ${stockName}`;
    const range = klineChart.getVisibleRange();
    document.getElementById('stock-screener-kline-range-label').textContent =
      `${range.start} ~ ${range.end}`;
  } catch (e) {
    console.error('loadScreenerKline error:', e);
    document.getElementById('stock-screener-kline-title').textContent = `${symbol} — 加载失败`;
  }
}

function createScreenerKlineChart(svg) {
  const chart = new KlineChart(svg);
  chart.onViewportChange = () => {
    const range = chart.getVisibleRange();
    document.getElementById('stock-screener-kline-range-label').textContent =
      `${range.start} ~ ${range.end}`;
  };
  return chart;
}

function bindScreenerChartPresetEvents() {
  const container = document.getElementById('stock-screener-preset-controls');
  container.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-preset]');
    if (!btn) return;
    const preset = parseInt(btn.dataset.preset, 10);
    container.querySelectorAll('.zoom-button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentKlinePreset = preset;
    if (klineChart && klineChart.bars.length) {
      klineChart.setPreset(preset);
      const range = klineChart.getVisibleRange();
      document.getElementById('stock-screener-kline-range-label').textContent =
        `${range.start} ~ ${range.end}`;
    }
  });
}

function resetFilters() {
  clearManualFilters();
  if (strategyInputEl) {
    strategyInputEl.value = '';
  }
  setActiveStrategyButton('');
  const descEl = document.getElementById('stock-screener-strategy-desc');
  if (descEl) descEl.textContent = '';
  currentPage = 1;
  runScreener(1);
}

level1El.addEventListener('change', () => {
  const selected = collectMultiSelectValues(level1El);
  populateLevel2(selected);
});
document.getElementById('stock-screener-apply-btn').addEventListener('click', () => runScreener(1));
document.getElementById('stock-screener-reset-btn').addEventListener('click', resetFilters);
filterToggleEl.addEventListener('click', toggleScreenerFilters);
strategyButtonsEl?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-strategy]');
  if (!button) return;
  applyStrategyPreset(button.dataset.strategy);
});
prevBtn.addEventListener('click', () => {
  if (currentPage > 1) runScreener(currentPage - 1);
});
nextBtn.addEventListener('click', () => {
  const totalPages = currentPayload.total_pages || 1;
  if (currentPage < totalPages) runScreener(currentPage + 1);
});
tbody.addEventListener('click', (event) => {
  const row = event.target.closest('.stock-screener-row');
  if (row) loadScreenerKline(row);
});
tbody.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const row = event.target.closest('.stock-screener-row');
  if (!row) return;
  event.preventDefault();
  loadScreenerKline(row);
});

bindScreenerChartPresetEvents();
loadTradingDays().then(() => loadIndustryHierarchy()).then(() => runScreener(1));

// ── Calendar widget ──────────────────────────────────────────

async function loadTradingDays() {
  try {
    const resp = await fetch('/api/rps-trading-days');
    const data = await resp.json();
    if (data.ok && data.trading_days) {
      tradingDaysSet = new Set(data.trading_days);
    }
  } catch (e) {
    console.warn('Failed to load trading days', e);
  }
}

function isTradingDay(dateStr) {
  return tradingDaysSet.has(dateStr);
}

function getLatestTradingDay() {
  const sorted = [...tradingDaysSet].sort();
  return sorted[sorted.length - 1] || '';
}

function formatDateCN(dateStr) {
  if (!dateStr) return '';
  const [y, m, d] = dateStr.split('-');
  return `${y}年${parseInt(m)}月${parseInt(d)}日`;
}

function renderCalendar() {
  if (!asOfDaysGrid) return;
  const year = calendarYear;
  const month = calendarMonth;
  asOfMonthLabel.textContent = `${year}年${month}月`;

  const firstDay = new Date(year, month - 1, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month, 0).getDate();

  let html = '';
  // Empty cells before first day
  for (let i = 0; i < firstDay; i++) {
    html += '<span class="asof-day-cell outside"></span>';
  }
  // Day cells
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const isTrading = isTradingDay(dateStr);
    const isToday = dateStr === todayStr;
    const isSelected = dateStr === selectedDate;
    let cls = 'asof-day-cell';
    if (isTrading) cls += ' trading';
    if (isToday) cls += ' today';
    if (isSelected) cls += ' selected';
    html += `<span class="${cls}" data-date="${dateStr}">${d}</span>`;
  }
  asOfDaysGrid.innerHTML = html;

  // Click handler
  asOfDaysGrid.querySelectorAll('.trading').forEach(cell => {
    cell.addEventListener('click', () => {
      const date = cell.dataset.date;
      selectDate(date);
    });
  });
}

function selectDate(dateStr) {
  selectedDate = dateStr;
  asOfDateInput.value = dateStr;
  if (asOfDateText) {
    asOfDateText.textContent = formatDateCN(dateStr);
  }
  closeCalendar();
  currentPage = 1;
  runScreener(1);
}

function clearDate() {
  selectedDate = '';
  asOfDateInput.value = '';
  if (asOfDateText) {
    asOfDateText.textContent = '当前数据（最新）';
  }
  closeCalendar();
  currentPage = 1;
  runScreener(1);
}

function openCalendar() {
  if (!asOfDropdown) return;
  // Sync calendar to selected date or today
  if (selectedDate) {
    const [y, m] = selectedDate.split('-');
    calendarYear = parseInt(y);
    calendarMonth = parseInt(m);
  } else {
    const now = new Date();
    calendarYear = now.getFullYear();
    calendarMonth = now.getMonth() + 1;
  }
  renderCalendar();
  asOfDropdown.hidden = false;
  asOfDateDisplay?.classList.add('active');
}

function closeCalendar() {
  if (asOfDropdown) asOfDropdown.hidden = true;
  asOfDateDisplay?.classList.remove('active');
}

function toggleCalendar() {
  if (asOfDropdown?.hidden) {
    openCalendar();
  } else {
    closeCalendar();
  }
}

function changeMonth(delta) {
  calendarMonth += delta;
  if (calendarMonth > 12) { calendarMonth = 1; calendarYear++; }
  if (calendarMonth < 1) { calendarMonth = 12; calendarYear--; }
  renderCalendar();
}

// Find the nearest trading day at or before a target date
function nearestTradingDay(targetStr) {
  const sorted = [...tradingDaysSet].sort();
  // Find the last day <= target
  let best = '';
  for (const d of sorted) {
    if (d <= targetStr) best = d;
    else break;
  }
  return best;
}

// Quick preset: go back N calendar days and find nearest trading day
function applyPresetOffset(offsetDays) {
  const target = new Date();
  target.setDate(target.getDate() - offsetDays);
  const targetStr = `${target.getFullYear()}-${String(target.getMonth()+1).padStart(2,'0')}-${String(target.getDate()).padStart(2,'0')}`;
  const trading = nearestTradingDay(targetStr);
  if (trading) {
    selectDate(trading);
  } else {
    console.warn('No trading day found for offset', offsetDays);
  }
}

// Event bindings
if (asOfDateDisplay) {
  asOfDateDisplay.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleCalendar();
  });
}
if (asOfPrevBtn) {
  asOfPrevBtn.addEventListener('click', (e) => { e.stopPropagation(); changeMonth(-1); });
}
if (asOfNextBtn) {
  asOfNextBtn.addEventListener('click', (e) => { e.stopPropagation(); changeMonth(1); });
}
document.getElementById('asof-clear-date')?.addEventListener('click', (e) => { e.stopPropagation(); clearDate(); });
document.getElementById('asof-today-date')?.addEventListener('click', (e) => {
  e.stopPropagation();
  const latest = getLatestTradingDay();
  if (latest) selectDate(latest);
});

// Quick presets
document.querySelectorAll('.asof-preset-btn').forEach(btn => {
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const offset = parseInt(btn.dataset.offset, 10);
    if (!isNaN(offset)) applyPresetOffset(offset);
  });
});

// Close calendar when clicking outside
document.addEventListener('click', (e) => {
  if (asOfDropdown && !asOfDropdown.hidden) {
    const picker = document.getElementById('stock-screener-asof-picker');
    if (picker && !picker.contains(e.target)) {
      closeCalendar();
    }
  }
});

// Sync to Tongdaxin block
setTimeout(() => {
  const syncTdxBtn = document.getElementById('stock-screener-sync-tdx-btn');
  if (!syncTdxBtn) return;
  syncTdxBtn.addEventListener('click', async () => {
    const rows = currentPayload.rows || [];
    if (!rows.length) return;
    const stocks = rows.map(r => ({ market: r.market, symbol: r.symbol }));
    syncTdxBtn.textContent = '同步中...';
    syncTdxBtn.disabled = true;
    try {
      const res = await fetch('/api/sync-to-tdx-block', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stocks }),
      });
      const data = await res.json();
      syncTdxBtn.textContent = data.ok ? `已同步 ${data.written} 只` : '同步失败';
    } catch (e) {
      syncTdxBtn.textContent = '同步失败';
    }
    setTimeout(() => { syncTdxBtn.textContent = '同步到AI股池'; syncTdxBtn.disabled = false; }, 2000);
  });
}, 0);

// ── Watchlist integration ───────────────────────────────────────────────

let watchlistSymbols = new Set();  // "market:symbol" strings of already-watchlisted

async function loadWatchlistSet() {
  try {
    const resp = await fetch('/api/watchlist');
    const data = await resp.json();
    watchlistSymbols = new Set(
      (data.stocks || []).map(s => `${s.market}:${s.symbol}`)
    );
  } catch (e) { /* ignore */ }
}

function isInWatchlist(market, symbol) {
  return watchlistSymbols.has(`${market}:${symbol}`);
}

// Update toolbar visibility + selected count
function updateWatchlistToolbar() {
  const checks = document.querySelectorAll('.stock-screener-row-check:checked');
  const count = checks.length;
  const hasResults = document.querySelectorAll('.stock-screener-row-check').length > 0;

  // Top toolbar
  const toolbar = document.getElementById('stock-screener-results-toolbar');
  if (toolbar) toolbar.style.display = hasResults ? '' : 'none';
  const countEl = document.getElementById('wl-selected-count');
  if (countEl) countEl.textContent = String(count);
  const addBtn = document.getElementById('wl-add-btn');
  if (addBtn) addBtn.disabled = count === 0;

  // Bottom toolbar
  const toolbarBtm = document.getElementById('stock-screener-results-toolbar-bottom');
  if (toolbarBtm) toolbarBtm.style.display = hasResults ? '' : 'none';
  const addBtnBtm = document.getElementById('wl-add-btn-bottom');
  if (addBtnBtm) addBtnBtm.disabled = count === 0;
}

// Select all / deselect all
function setAllCheckboxes(checked) {
  document.querySelectorAll('.stock-screener-row-check').forEach(cb => { cb.checked = checked; });
  document.querySelectorAll('#wl-select-all, #wl-select-all-bottom').forEach(el => { el.checked = checked; });
  updateWatchlistToolbar();
}

document.getElementById('wl-select-all')?.addEventListener('change', function() {
  setAllCheckboxes(this.checked);
});
document.getElementById('wl-select-all-bottom')?.addEventListener('change', function() {
  setAllCheckboxes(this.checked);
});

// Delegate checkbox changes on the results table
document.getElementById('stock-screener-results-tbody')?.addEventListener('change', (e) => {
  if (e.target.classList.contains('stock-screener-row-check')) {
    updateWatchlistToolbar();
  }
});

// Add to watchlist action
async function addToWatchlist() {
  const checks = document.querySelectorAll('.stock-screener-row-check:checked');
  const stocks = [];
  checks.forEach(cb => {
    const row = cb.closest('tr');
    if (!row) return;
    const market = row.dataset.market;
    const symbol = row.dataset.symbol;
    if (market && symbol) stocks.push({ market, symbol });
  });
  if (!stocks.length) return;

  const btn = document.getElementById('wl-add-btn');
  const btnBtm = document.getElementById('wl-add-btn-bottom');
  if (btn) { btn.disabled = true; btn.textContent = '添加中...'; }
  if (btnBtm) { btnBtm.disabled = true; btnBtm.textContent = '添加中...'; }

  try {
    const resp = await fetch('/api/watchlist/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stocks }),
    });
    const data = await resp.json();
    if (data.ok) {
      // Uncheck all + reload watchlist set
      setAllCheckboxes(false);
      await loadWatchlistSet();
      // Re-render rows to update highlight
      rerenderCurrentRows();
      // Feedback
      if (btn) { btn.textContent = `✅ 已添加 ${data.added} 只`; setTimeout(() => { btn.innerHTML = '⭐ 加入自选 (<span id=\"wl-selected-count\">0</span>)'; updateWatchlistToolbar(); }, 2000); }
      if (btnBtm) { btnBtm.textContent = '✅ 已添加'; setTimeout(() => { btnBtm.textContent = '⭐ 加入自选'; }, 2000); }
    } else {
      if (btn) { btn.innerHTML = '⭐ 加入自选 (<span id=\"wl-selected-count\">0</span>)'; btn.disabled = false; }
      if (btnBtm) { btnBtm.textContent = '⭐ 加入自选'; btnBtm.disabled = false; }
    }
  } catch (e) {
    if (btn) { btn.innerHTML = '⭐ 加入自选 (<span id=\"wl-selected-count\">0</span>)'; btn.disabled = false; }
    if (btnBtm) { btnBtm.textContent = '⭐ 加入自选'; btnBtm.disabled = false; }
  }
}

document.getElementById('wl-add-btn')?.addEventListener('click', addToWatchlist);
document.getElementById('wl-add-btn-bottom')?.addEventListener('click', addToWatchlist);

// Re-render current rows (to update watchlist highlight colors)
function rerenderCurrentRows() {
  const rows = document.querySelectorAll('#stock-screener-results-tbody tr');
  rows.forEach(row => {
    const market = row.dataset.market;
    const symbol = row.dataset.symbol;
    if (market && symbol && isInWatchlist(market, symbol)) {
      row.classList.add('wl-highlighted');
    } else {
      row.classList.remove('wl-highlighted');
    }
  });
}

// Load watchlist set on page init
loadWatchlistSet().then(() => {
  // Re-highlight after watchlist data arrives
  rerenderCurrentRows();
  updateWatchlistToolbar();
});
