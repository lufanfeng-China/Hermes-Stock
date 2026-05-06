import { KlineChart } from './kline-chart.js';

const PAGE_SIZE = 50;
const STRATEGY_PRESETS = {
  rps_standard_launch: {
    strategy: 'rps_standard_launch',
  },
  rps_attack: {
    strategy: 'rps_attack',
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

function buildParams(page = currentPage) {
  const params = new URLSearchParams();
  const data = new FormData(form);
  for (const [key, value] of data.entries()) {
    const text = String(value || '').trim();
    if (text) params.set(key, text);
  }
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

function populateLevel2(level1Name) {
  const values = new Set();
  for (const level1 of industryHierarchy) {
    if (level1Name && level1.name !== level1Name) continue;
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
  form.reset();
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
  collapseScreenerFiltersAfterStrategy();
  currentPage = 1;
  runScreener(1);
}

function renderScreenerLoadingState() {
  currentPayload = { rows: [], total: 0, page: 1, total_pages: 1 };
  countEl.textContent = '…';
  pageInfoEl.textContent = '正在筛选...';
  tbody.innerHTML = '<tr><td colspan="14" class="stock-score-empty-row">正在筛选，请稍候...</td></tr>';
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
    statusEl.textContent = `命中 ${payload.total || 0} 只股票，当前页 ${(payload.rows || []).length} 条`;
  } catch (error) {
    statusEl.textContent = `筛选失败：${error.message}`;
    tbody.innerHTML = '<tr><td colspan="14" class="stock-score-empty-row">筛选失败，请调整条件后重试</td></tr>';
  }
}

function renderScreenerRows(rows) {
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="14" class="stock-score-empty-row">没有符合条件的股票</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row) => {
    const industryText = [row.industry_level_1, row.industry_level_2].filter(Boolean).join(' / ') || '—';
    const marketSymbol = `${String(row.market || '').toUpperCase()}:${row.symbol || ''}`;
    return `<tr class="stock-screener-row" tabindex="0" data-market="${escapeHtml(row.market)}" data-symbol="${escapeHtml(row.symbol)}" data-name="${escapeHtml(row.stock_name || row.symbol)}">
      <td><strong>${escapeHtml(row.stock_name || row.symbol)}</strong><span class="stock-screener-symbol">${escapeHtml(marketSymbol)}</span></td>
      <td class="num">${formatNumber(row.current_price, 2)}</td>
      <td class="num">${formatNumber(row.pe_ttm, 2)}</td>
      <td class="num">${formatNumber(row.ps_ttm, 2)}</td>
      <td class="num">${formatMarketCapYi(row.total_market_cap)}</td>
      <td class="num">${formatRank(row.market_total_rank, row.market_total_universe_size)}</td>
      <td class="num">${formatRank(row.industry_total_rank, row.industry_total_universe_size)}</td>
      <td>${escapeHtml(row.classification_label || row.classification || '—')}</td>
      <td>${escapeHtml(row.valuation_band_label || '—')}</td>
      <td class="num">${formatPercentile(row.primary_percentile)}</td>
      <td>${escapeHtml(row.industry_temperature_label || '—')}<span class="stock-screener-symbol">${escapeHtml(formatPercentile(row.industry_temperature_percentile_since_2022))}</span></td>
      <td>${escapeHtml(industryText)}</td>
      <td class="num">${formatNumber(row.industry_total_score, 1)}</td>
      <td class="num">${formatRank(row.industry_total_rank, row.industry_total_universe_size)}</td>
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
  currentPage = 1;
  runScreener(1);
}

level1El.addEventListener('change', (event) => {
  populateLevel2(event.target.value);
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
loadIndustryHierarchy().then(() => runScreener(1));
