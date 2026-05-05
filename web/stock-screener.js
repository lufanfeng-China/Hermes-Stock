import { KlineChart } from './kline-chart.js';

const PAGE_SIZE = 50;
let currentPage = 1;
let currentPayload = { rows: [], total: 0, page: 1, total_pages: 1 };
let klineChart = null;
let currentKlinePreset = 30;
let currentKlineSymbol = '';
let currentKlineName = '';
let currentKlineBars = [];
let currentKlineRpsHistory = [];
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
const klineControlsEl = document.getElementById('stock-screener-kline-controls');
const klineRangeEl = document.getElementById('stock-screener-kline-range');
const klineLatestEl = document.getElementById('stock-screener-kline-latest');
const klineTitleEl = document.getElementById('stock-screener-kline-title');
const klineSectionEl = document.getElementById('stock-screener-kline-section');
const klineSvgEl = document.getElementById('stock-screener-kline-svg');

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

function formatVolume(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  const volume = Number(value);
  if (Math.abs(volume) >= 1_0000_0000) return `${(volume / 1_0000_0000).toFixed(2)}亿`;
  if (Math.abs(volume) >= 1_0000) return `${(volume / 1_0000).toFixed(2)}万`;
  return String(Math.round(volume));
}

function formatRpsValue(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(1);
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

async function runScreener(page = 1) {
  currentPage = page;
  statusEl.textContent = '正在筛选...';
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

function renderKlineRange(range) {
  if (!range?.start || !range?.end) {
    klineRangeEl.textContent = '区间：待加载';
    return;
  }
  klineRangeEl.textContent = `区间：${range.start} 至 ${range.end}`;
}

function renderKlineLatestInfo(bar, rpsRow) {
  if (!bar) {
    klineLatestEl.textContent = '最新：待加载';
    return;
  }
  const price = formatNumber(bar.close ?? bar.price, 2);
  const volume = formatVolume(bar.volume);
  const suffix = [
    `RPS20 ${formatRpsValue(rpsRow?.rps_20)}`,
    `RPS50 ${formatRpsValue(rpsRow?.rps_50)}`,
    `RPS120 ${formatRpsValue(rpsRow?.rps_120)}`,
    `RPS250 ${formatRpsValue(rpsRow?.rps_250)}`,
  ].join(' · ');
  klineLatestEl.textContent = `最新：${bar.trading_day || '—'} · 收盘 ${price} · 成交量 ${volume} · ${suffix}`;
}

function updateKlinePresetButtons() {
  klineControlsEl.querySelectorAll('[data-kline-preset]').forEach((button) => {
    const preset = Number(button.dataset.klinePreset);
    button.classList.toggle('active', preset === currentKlinePreset);
  });
}

function refreshKlineStatus() {
  if (!klineChart || !currentKlineBars.length) {
    renderKlineRange(null);
    renderKlineLatestInfo(null, null);
    return;
  }
  renderKlineRange(klineChart.getVisibleRange());
  const latestBar = currentKlineBars[currentKlineBars.length - 1] || null;
  const rpsByDate = new Map(currentKlineRpsHistory.map((item) => [item.trading_day, item]));
  const latestRps = latestBar ? rpsByDate.get(latestBar.trading_day) : null;
  renderKlineLatestInfo(latestBar, latestRps);
}

async function loadScreenerKline(row) {
  const symbol = row?.dataset?.symbol;
  const name = row?.dataset?.name || symbol;
  if (!symbol) return;
  document.querySelectorAll('.stock-screener-row').forEach((tr) => tr.classList.toggle('row-selected', tr === row));
  currentKlineSymbol = symbol;
  currentKlineName = name;
  klineSectionEl.hidden = false;
  klineTitleEl.textContent = `${name} (${symbol}) · K线加载中...`;
  renderKlineRange(null);
  renderKlineLatestInfo(null, null);
  updateKlinePresetButtons();
  try {
    const [klineResponse, rpsResponse] = await Promise.all([
      fetch(`/api/stock-kline?symbol=${encodeURIComponent(symbol)}&limit=5000`),
      fetch(`/api/stock-rps-history?symbol=${encodeURIComponent(symbol)}`),
    ]);
    const kline = await klineResponse.json();
    const rps = await rpsResponse.json();
    if (!kline.ok) throw new Error(kline?.error?.message || 'K线数据不可用');
    if (!klineChart) {
      klineChart = new KlineChart(klineSvgEl);
      klineChart.onViewportChange = () => {
        renderKlineRange(klineChart.getVisibleRange());
        updateKlinePresetButtons();
      };
    }
    currentKlineBars = kline.bars || [];
    currentKlineRpsHistory = (rps.history || []).map((item) => ({
      trading_day: item.trading_day,
      rps_20: item.rps_20,
      rps_50: item.rps_50,
      rps_120: item.rps_120,
      rps_250: item.rps_250,
    }));
    klineChart.load(currentKlineBars, currentKlineRpsHistory, currentKlinePreset);
    refreshKlineStatus();
    updateKlinePresetButtons();
    klineTitleEl.textContent = `${name} (${symbol}) · K线趋势`;
  } catch (error) {
    currentKlineBars = [];
    currentKlineRpsHistory = [];
    klineTitleEl.textContent = `${name} (${symbol}) · K线加载失败：${error.message}`;
    renderKlineRange(null);
    renderKlineLatestInfo(null, null);
  }
}

function resetFilters() {
  form.reset();
  populateLevel2('');
  currentPage = 1;
  runScreener(1);
}

level1El.addEventListener('change', (event) => {
  populateLevel2(event.target.value);
});
document.getElementById('stock-screener-apply-btn').addEventListener('click', () => runScreener(1));
document.getElementById('stock-screener-reset-btn').addEventListener('click', resetFilters);
prevBtn.addEventListener('click', () => {
  if (currentPage > 1) runScreener(currentPage - 1);
});
nextBtn.addEventListener('click', () => {
  const totalPages = currentPayload.total_pages || 1;
  if (currentPage < totalPages) runScreener(currentPage + 1);
});
klineControlsEl.addEventListener('click', (event) => {
  const button = event.target.closest('[data-kline-preset]');
  if (!button) return;
  currentKlinePreset = Number(button.dataset.klinePreset);
  updateKlinePresetButtons();
  if (!klineChart || !currentKlineBars.length) return;
  klineChart.setPreset(currentKlinePreset);
  refreshKlineStatus();
  if (currentKlineSymbol) {
    klineTitleEl.textContent = `${currentKlineName} (${currentKlineSymbol}) · K线趋势`;
  }
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

updateKlinePresetButtons();
renderKlineRange(null);
renderKlineLatestInfo(null, null);
loadIndustryHierarchy().then(() => runScreener(1));
