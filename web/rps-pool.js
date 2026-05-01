/**
 * rps-pool.js
 * RPS Pool Screener — industry/concept filter → pool table → K-line chart.
 */

import { KlineChart } from './kline-chart.js';

// ─── State ────────────────────────────────────────────────────────────────────

let industryHierarchy = [];        // from /api/industry-hierarchy
let conceptList = [];              // from /api/concept-list
let selectedConcepts = new Set();  // concept_name strings

// Pool
let poolData = [];
let industryRpsData = [];
let poolPage = 1;
const POOL_PAGE_SIZE = 50;
let poolSelectedSymbol = null;
let poolSortKey = 'rps_20';
let poolSortDirection = 'desc';
let industryRpsSortKey = 'industry_rps_20';
let industryRpsSortDirection = 'desc';

// Chart
let poolKlineChart = null;
let currentKlinePreset = 60;

// ─── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);

async function init() {
  bindPoolEvents();
  bindChartPresetEvents();
  await Promise.all([
    loadIndustryHierarchy(),
    loadConceptList(),
  ]);
}

// ─── Industry Hierarchy ─────────────────────────────────────────────────────

async function loadIndustryHierarchy() {
  try {
    const res = await fetch('/api/industry-hierarchy');
    const json = await res.json();
    if (!json.ok) return;
    industryHierarchy = json.industries || [];
    populateLevel1();
  } catch (e) {
    console.error('loadIndustryHierarchy error:', e);
  }
}

function populateLevel1() {
  const el = document.getElementById('pool-level1');
  el.innerHTML = '<option value="">全部行业</option>';
  for (const l1 of industryHierarchy) {
    const opt = document.createElement('option');
    opt.value = l1.name;
    opt.textContent = l1.name;
    el.appendChild(opt);
  }
}

function populateLevel2(level1Name) {
  const el = document.getElementById('pool-level2');
  el.innerHTML = '<option value="">全部二级</option>';
  if (!level1Name) {
    // Show all level2 from all level1
    const allL2 = new Set();
    for (const l1 of industryHierarchy) {
      for (const l2 of l1.level2) allL2.add(l2);
    }
    for (const name of [...allL2].sort()) {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      el.appendChild(opt);
    }
    return;
  }
  const l1 = industryHierarchy.find(x => x.name === level1Name);
  if (!l1) return;
  for (const name of l1.level2) {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    el.appendChild(opt);
  }
}

document.getElementById('pool-level1').addEventListener('change', (e) => {
  populateLevel2(e.target.value);
});

// ─── Concept List & Dropdown ────────────────────────────────────────────────

async function loadConceptList() {
  try {
    const res = await fetch('/api/concept-list?limit=500');
    const json = await res.json();
    if (!json.ok) return;
    conceptList = json.results || [];
  } catch (e) {
    console.error('loadConceptList error:', e);
  }
}

const conceptInput = document.getElementById('pool-concept-input');
const conceptDropdown = document.getElementById('pool-concept-dropdown');

conceptInput.addEventListener('input', (e) => {
  const val = e.target.value.trim();
  if (val.length < 1) {
    conceptDropdown.classList.remove('active');
    return;
  }
  showConceptDropdown(val);
});

conceptInput.addEventListener('focus', () => {
  if (conceptInput.value.trim().length > 0) {
    showConceptDropdown(conceptInput.value.trim());
  }
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.concept-input-wrap')) {
    conceptDropdown.classList.remove('active');
  }
});

function showConceptDropdown(query) {
  const q = query.toLowerCase();
  const filtered = conceptList
    .filter(c => (c.concept_name || '').toLowerCase().includes(q))
    .slice(0, 20);

  if (filtered.length === 0) {
    conceptDropdown.innerHTML = '<div class="concept-option" style="color:#555;cursor:default">无匹配概念</div>';
    conceptDropdown.classList.add('active');
    return;
  }

  conceptDropdown.innerHTML = '';
  for (const c of filtered) {
    const div = document.createElement('div');
    div.className = 'concept-option' + (selectedConcepts.has(c.concept_name) ? ' selected' : '');
    div.textContent = c.concept_name;
    div.addEventListener('click', (e) => {
      e.stopPropagation();
      addConcept(c.concept_name);
      conceptInput.value = '';
      conceptDropdown.classList.remove('active');
    });
    conceptDropdown.appendChild(div);
  }
  conceptDropdown.classList.add('active');
}

function addConcept(name) {
  selectedConcepts.add(name);
  renderConceptTags();
}

function removeConcept(name) {
  selectedConcepts.delete(name);
  renderConceptTags();
}

function renderConceptTags() {
  const container = document.getElementById('pool-concept-tags');
  container.innerHTML = '';
  for (const name of selectedConcepts) {
    const tag = document.createElement('span');
    tag.className = 'concept-tag';
    tag.innerHTML = `
      <span>${escapeHtml(name)}</span>
      <span class="concept-tag-remove" data-name="${escapeHtml(name)}">&times;</span>
    `;
    tag.querySelector('.concept-tag-remove').addEventListener('click', () => removeConcept(name));
    container.appendChild(tag);
  }
}

// ─── Pool Filter ─────────────────────────────────────────────────────────────

document.getElementById('pool-apply-btn').addEventListener('click', applyPoolFilter);

async function applyPoolFilter() {
  const level1 = document.getElementById('pool-level1').value;
  const level2 = document.getElementById('pool-level2').value;

  const params = new URLSearchParams();
  if (level1) params.append('level1', level1);
  if (level2) params.append('level2', level2);
  for (const c of selectedConcepts) params.append('concepts', c);

  try {
    const res = await fetch(`/api/pool-filter?${params.toString()}`);
    const json = await res.json();
    if (!json.ok) {
      console.error('pool-filter error:', json);
      return;
    }
    poolData = json.results || [];
    industryRpsData = buildIndustryRpsRows(poolData);
    sortPoolData();
    sortIndustryRpsData();
    poolPage = 1;
    document.getElementById('pool-section').classList.remove('hidden');
    document.getElementById('pool-count-badge').textContent = poolData.length;
    document.getElementById('pool-status').textContent =
      `股票池: ${json.pool_size} 只${poolData.length < json.pool_size ? ' (显示前' + poolData.length + ')' : ''}`;
    renderPoolTable();
    renderIndustryRpsTable();
  } catch (e) {
    console.error('applyPoolFilter error:', e);
  }
}

// ─── Pool Table ─────────────────────────────────────────────────────────────

function togglePoolSort(nextKey) {
  if (!nextKey) return;
  if (poolSortKey === nextKey) {
    poolSortDirection = poolSortDirection === 'desc' ? 'asc' : 'desc';
  } else {
    poolSortKey = nextKey;
    poolSortDirection = 'desc';
  }
  sortPoolData();
  poolPage = 1;
  renderPoolTable();
}

function sortPoolData() {
  const direction = poolSortDirection === 'asc' ? 1 : -1;
  poolData.sort((a, b) => {
    const aValue = a?.[poolSortKey];
    const bValue = b?.[poolSortKey];
    const aMissing = aValue == null;
    const bMissing = bValue == null;
    if (aMissing && bMissing) return String(a?.symbol || '').localeCompare(String(b?.symbol || ''));
    if (aMissing) return 1;
    if (bMissing) return -1;
    if (aValue === bValue) return String(a?.symbol || '').localeCompare(String(b?.symbol || ''));
    return (aValue - bValue) * direction;
  });
}

function renderPoolSortIndicators() {
  for (const th of document.querySelectorAll('.pool-table th[data-sort-key]')) {
    const isActive = th.dataset.sortKey === poolSortKey;
    th.classList.toggle('pool-sort-active', isActive);
    th.classList.toggle('pool-sort-asc', isActive && poolSortDirection === 'asc');
    th.classList.toggle('pool-sort-desc', isActive && poolSortDirection === 'desc');
    if (isActive) {
      th.dataset.sortDirection = poolSortDirection;
    } else {
      delete th.dataset.sortDirection;
    }
  }
}

function formatPoolIndustry(entry) {
  const level1 = normalizeIndustryValues(entry?.level1);
  const level2 = normalizeIndustryValues(entry?.level2);
  const primary = level1.join(' / ');
  const secondary = level2.join(' / ');
  const text = primary && secondary
    ? `${primary} / ${secondary}`
    : primary || secondary || '—';

  return {
    text,
    html: secondary
      ? `<span class="pool-industry-primary">${escapeHtml(primary || secondary)}</span><span class="pool-industry-secondary">${escapeHtml(secondary)}</span>`
      : `<span class="pool-industry-primary">${escapeHtml(text)}</span>`,
  };
}

function buildIndustryRpsRows(rows) {
  const grouped = new Map();

  for (const row of rows || []) {
    const level1 = normalizeIndustryValues(row?.level1)[0] || '—';
    const level2 = normalizeIndustryValues(row?.level2)[0] || '未分类';
    const key = `${level1}__${level2}`;
    if (!grouped.has(key)) {
      grouped.set(key, {
        level1,
        level2,
        memberCount: 0,
        rps_20_sum: 0,
        rps_20_count: 0,
        rps_50_sum: 0,
        rps_50_count: 0,
        rps_120_sum: 0,
        rps_120_count: 0,
        rps_250_sum: 0,
        rps_250_count: 0,
      });
    }
    const bucket = grouped.get(key);
    bucket.memberCount += 1;
    for (const metric of ['rps_20', 'rps_50', 'rps_120', 'rps_250']) {
      const value = row?.[metric];
      if (typeof value === 'number' && Number.isFinite(value)) {
        bucket[`${metric}_sum`] += value;
        bucket[`${metric}_count`] += 1;
      }
    }
  }

  return [...grouped.values()]
    .map(bucket => ({
      level1: bucket.level1,
      level2: bucket.level2,
      memberCount: bucket.memberCount,
      rps_20: bucket.rps_20_count ? bucket.rps_20_sum / bucket.rps_20_count : null,
      rps_50: bucket.rps_50_count ? bucket.rps_50_sum / bucket.rps_50_count : null,
      rps_120: bucket.rps_120_count ? bucket.rps_120_sum / bucket.rps_120_count : null,
      rps_250: bucket.rps_250_count ? bucket.rps_250_sum / bucket.rps_250_count : null,
    }))
    .sort((a, b) => {
      const av = a.rps_20 ?? -1;
      const bv = b.rps_20 ?? -1;
      if (av !== bv) return bv - av;
      if (a.memberCount !== b.memberCount) return b.memberCount - a.memberCount;
      return String(a.level2).localeCompare(String(b.level2));
    });
}

function toggleIndustryRpsSort(nextKey) {
  if (!nextKey) return;
  if (industryRpsSortKey === nextKey) {
    industryRpsSortDirection = industryRpsSortDirection === 'desc' ? 'asc' : 'desc';
  } else {
    industryRpsSortKey = nextKey;
    industryRpsSortDirection = 'desc';
  }
  sortIndustryRpsData();
  renderIndustryRpsTable();
}

function sortIndustryRpsData() {
  const metricKey = String(industryRpsSortKey || '').replace(/^industry_/, '');
  const direction = industryRpsSortDirection === 'asc' ? 1 : -1;
  industryRpsData.sort((a, b) => {
    const aValue = a?.[metricKey];
    const bValue = b?.[metricKey];
    const aMissing = aValue == null;
    const bMissing = bValue == null;
    if (aMissing && bMissing) return String(a?.level2 || '').localeCompare(String(b?.level2 || ''));
    if (aMissing) return 1;
    if (bMissing) return -1;
    if (aValue === bValue) return String(a?.level2 || '').localeCompare(String(b?.level2 || ''));
    return (aValue - bValue) * direction;
  });
}

function renderIndustryRpsSortIndicators() {
  for (const th of document.querySelectorAll('.industry-rps-table th[data-sort-key]')) {
    const isActive = th.dataset.sortKey === industryRpsSortKey;
    th.classList.toggle('pool-sort-active', isActive);
    th.classList.toggle('pool-sort-asc', isActive && industryRpsSortDirection === 'asc');
    th.classList.toggle('pool-sort-desc', isActive && industryRpsSortDirection === 'desc');
    if (isActive) {
      th.dataset.sortDirection = industryRpsSortDirection;
    } else {
      delete th.dataset.sortDirection;
    }
  }
}

function renderIndustryRpsTable() {
  const section = document.getElementById('industry-rps-section');
  const tbody = document.getElementById('industry-rps-tbody');
  const badge = document.getElementById('industry-rps-count-badge');
  if (!section || !tbody || !badge) return;

  tbody.innerHTML = '';
  badge.textContent = String(industryRpsData.length || 0);
  renderIndustryRpsSortIndicators();

  if (!industryRpsData.length) {
    section.classList.add('hidden');
    tbody.innerHTML = '<tr><td colspan="7" class="no-pool-results">暂无二级行业RPS数据</td></tr>';
    return;
  }

  section.classList.remove('hidden');
  for (const row of industryRpsData) {
    const tr = document.createElement('tr');
    tr.dataset.industryLevel1 = row.level1 || '';
    tr.dataset.industryLevel2 = row.level2 || '';
    tr.innerHTML = `
      <td>${escapeHtml(row.level1 || '—')}</td>
      <td>${escapeHtml(row.level2 || '—')}</td>
      <td class="num">${row.memberCount}</td>
      <td class="num">${row.rps_20 != null ? row.rps_20.toFixed(2) : '—'}</td>
      <td class="num">${row.rps_50 != null ? row.rps_50.toFixed(2) : '—'}</td>
      <td class="num">${row.rps_120 != null ? row.rps_120.toFixed(2) : '—'}</td>
      <td class="num">${row.rps_250 != null ? row.rps_250.toFixed(2) : '—'}</td>
    `;
    tr.addEventListener('click', () => {
      loadIndustryKline(row.level1, row.level2);
    });
    tbody.appendChild(tr);
  }
}

function renderPoolTable() {
  const tbody = document.getElementById('pool-tbody');
  tbody.innerHTML = '';
  renderPoolSortIndicators();

  const start = (poolPage - 1) * POOL_PAGE_SIZE;
  const end = Math.min(start + POOL_PAGE_SIZE, poolData.length);
  const pageData = poolData.slice(start, end);
  const totalPages = Math.max(1, Math.ceil(poolData.length / POOL_PAGE_SIZE));

  if (poolData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="no-pool-results">股票池为空，请调整筛选条件</td></tr>`;
    document.getElementById('pool-prev').disabled = true;
    document.getElementById('pool-next').disabled = true;
    document.getElementById('pool-page-info').textContent = '0 / 1';
    return;
  }

  for (let i = 0; i < pageData.length; i++) {
    const s = pageData[i];
    const idx = start + i + 1;
    const tr = document.createElement('tr');
    tr.dataset.symbol = s.symbol;

    if (s.symbol === poolSelectedSymbol) tr.classList.add('row-selected');

    const ret20 = s.return_20_pct != null ? `${s.return_20_pct > 0 ? '+' : ''}${s.return_20_pct.toFixed(2)}%` : '—';
    const industry = formatPoolIndustry(s);

    tr.innerHTML = `
      <td class="num">${idx}</td>
      <td>${s.symbol}</td>
      <td>${escapeHtml(s.stock_name || '')}</td>
      <td class="num">${s.rps_20 != null ? s.rps_20.toFixed(2) : '—'}</td>
      <td class="num">${s.rps_50 != null ? s.rps_50.toFixed(2) : '—'}</td>
      <td class="num">${s.rps_120 != null ? s.rps_120.toFixed(2) : '—'}</td>
      <td class="num">${s.rps_250 != null ? s.rps_250.toFixed(2) : '—'}</td>
      <td class="num" style="color:${s.return_20_pct > 0 ? '#ef5350' : '#26a69a'}">${ret20}</td>
      <td class="industry-cell" title="${escapeHtml(industry.text)}">${industry.html}</td>
    `;

    tr.addEventListener('click', () => {
      selectPoolRow(s.symbol);
    });

    tbody.appendChild(tr);
  }

  document.getElementById('pool-prev').disabled = poolPage <= 1;
  document.getElementById('pool-next').disabled = poolPage >= totalPages;
  document.getElementById('pool-page-info').textContent = `${poolPage} / ${totalPages}`;
}

function selectPoolSymbol(symbol) {
  poolSelectedSymbol = symbol;

  // Highlight row
  for (const tr of document.querySelectorAll('#pool-tbody tr')) {
    tr.classList.toggle('row-selected', tr.dataset.symbol === symbol);
  }

  // Show chart section
  document.getElementById('pool-chart-section').classList.remove('hidden');
  loadPoolKline(symbol);
}

document.getElementById('pool-prev').addEventListener('click', () => {
  if (poolPage > 1) { poolPage--; renderPoolTable(); }
});
document.getElementById('pool-next').addEventListener('click', () => {
  const totalPages = Math.max(1, Math.ceil(poolData.length / POOL_PAGE_SIZE));
  if (poolPage < totalPages) { poolPage++; renderPoolTable(); }
});

// Alias for clarity
const selectPoolRow = selectPoolSymbol;

// ─── Shared K-line Chart ─────────────────────────────────────────────────────

async function loadPoolKline(symbol) {
  document.getElementById('pool-kline-stock-title').textContent = `${symbol} — 加载中…`;

  try {
    const [klineRes, rpsRes] = await Promise.all([
      fetch(`/api/stock-kline?symbol=${symbol}&limit=300`),
      fetch(`/api/stock-rps-history?symbol=${symbol}`),
    ]);
    const klineJson = await klineRes.json();
    const rpsJson = await rpsRes.json();

    if (!klineJson.ok) {
      document.getElementById('pool-kline-stock-title').textContent = `${symbol} — 数据不可用`;
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

    const svg = document.getElementById('pool-kline-svg');
    if (!poolKlineChart) {
      poolKlineChart = createPoolKlineChart(svg);
    }

    poolKlineChart.load(bars, rpsHistory, currentKlinePreset);
    const stockName = bars[0]?.name || symbol;
    document.getElementById('pool-kline-stock-title').textContent = `${symbol} ${stockName}`;
    const range = poolKlineChart.getVisibleRange();
    document.getElementById('pool-kline-range-label').textContent =
      `${range.start} ~ ${range.end}`;
  } catch (e) {
    console.error('loadPoolKline error:', e);
    document.getElementById('pool-kline-stock-title').textContent = `${symbol} — 加载失败`;
  }
}

async function loadIndustryKline(level1, level2) {
  const title = level2 || level1 || '二级行业';
  document.getElementById('pool-chart-section').classList.remove('hidden');
  document.getElementById('pool-kline-stock-title').textContent = `${title} — 加载中…`;

  try {
    const response = await fetch('/api/industry-heatmap?limit=999&lookback=120');
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error('industry heatmap request failed');
    }

    const heatmapRow = (payload.rows || []).find((row) => row.industry_level_2_name === level2);
    if (!heatmapRow) {
      document.getElementById('pool-kline-stock-title').textContent = `${title} — 数据不可用`;
      return;
    }

    const bars = buildIndustryKlineBars(heatmapRow, title);
    const rpsHistory = computeIndustryRpsHistory(bars);

    const svg = document.getElementById('pool-kline-svg');
    if (!poolKlineChart) {
      poolKlineChart = createPoolKlineChart(svg);
    }

    poolKlineChart.load(bars, rpsHistory, currentKlinePreset);
    document.getElementById('pool-kline-stock-title').textContent = `${title} 等权行业指数`;
    const range = poolKlineChart.getVisibleRange();
    document.getElementById('pool-kline-range-label').textContent =
      `${range.start} ~ ${range.end}`;
  } catch (e) {
    console.error('loadIndustryKline error:', e);
    document.getElementById('pool-kline-stock-title').textContent = `${title} — 加载失败`;
  }
}

function buildIndustryKlineBars(industryRow, title) {
  const cells = Array.isArray(industryRow?.cells) ? [...industryRow.cells] : [];
  cells.sort((a, b) => String(a?.trading_day || '').localeCompare(String(b?.trading_day || '')));

  let previousClose = 100;
  return cells.map((cell) => {
    const pctChange = typeof cell?.pct_change === 'number' && Number.isFinite(cell.pct_change)
      ? cell.pct_change
      : 0;
    const open = previousClose;
    const close = open * (1 + pctChange / 100);
    const baseHigh = Math.max(open, close);
    const baseLow = Math.min(open, close);
    const wickPadding = Math.max(baseHigh * 0.002, Math.abs(close - open) * 0.25);
    const fallbackVolume = Math.round(Math.abs(pctChange) * Math.max(Number(cell?.stock_count || 0), 1) * 1000);
    const bar = {
      trading_day: cell?.trading_day || '',
      open: Number(open.toFixed(4)),
      high: Number((baseHigh + wickPadding).toFixed(4)),
      low: Number(Math.max(0.0001, baseLow - wickPadding).toFixed(4)),
      close: Number(close.toFixed(4)),
      volume: Number(cell?.daily_volume || fallbackVolume),
      name: title,
    };
    previousClose = bar.close;
    return bar;
  });
}

function computeIndustryRpsHistory(bars) {
  const closes = (bars || []).map((bar) => Number(bar?.close ?? NaN));

  function rollingReturn(values, window) {
    const out = new Array(values.length).fill(null);
    for (let i = 1; i < values.length; i++) {
      const lookback = Math.min(window, i);
      const base = values[i - lookback];
      const current = values[i];
      if (!Number.isFinite(base) || !Number.isFinite(current) || base === 0) continue;
      out[i] = ((current - base) / base) * 100;
    }
    return out;
  }

  function rollingRps(values, window = 120) {
    const out = new Array(values.length).fill(null);
    for (let i = 0; i < values.length; i++) {
      const current = values[i];
      if (!Number.isFinite(current)) continue;
      const start = Math.max(0, i - window + 1);
      const slice = values.slice(start, i + 1).filter(v => Number.isFinite(v));
      if (!slice.length) continue;
      const below = slice.filter(v => v < current).length;
      out[i] = Number(((below / slice.length) * 100).toFixed(2));
    }
    return out;
  }

  const ret20 = rollingReturn(closes, 20);
  const ret50 = rollingReturn(closes, 50);
  const ret120 = rollingReturn(closes, 120);
  const ret250 = rollingReturn(closes, 250);
  const rps20 = rollingRps(ret20);
  const rps50 = rollingRps(ret50);
  const rps120 = rollingRps(ret120);
  const rps250 = rollingRps(ret250);

  return (bars || []).map((bar, i) => ({
    trading_day: bar.trading_day,
    rps_20: rps20[i],
    rps_50: rps50[i],
    rps_120: rps120[i],
    rps_250: rps250[i],
  }));
}

function createPoolKlineChart(svg) {
  const chart = new KlineChart(svg);
  chart.onViewportChange = () => {
    const range = chart.getVisibleRange();
    document.getElementById('pool-kline-range-label').textContent =
      `${range.start} ~ ${range.end}`;
  };
  return chart;
}

// ─── Chart Preset Buttons ────────────────────────────────────────────────────

function bindChartPresetEvents() {
  const container = document.getElementById('pool-preset-controls');
  container.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-preset]');
    if (!btn) return;
    const preset = parseInt(btn.dataset.preset, 10);
    container.querySelectorAll('.zoom-button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentKlinePreset = preset;
    if (poolKlineChart && poolKlineChart.bars.length) {
      poolKlineChart.setPreset(preset);
      const range = poolKlineChart.getVisibleRange();
      document.getElementById('pool-kline-range-label').textContent =
        `${range.start} ~ ${range.end}`;
    }
  });
}

// ─── Pool Events (bind once) ─────────────────────────────────────────────────

function bindPoolEvents() {
  // Level1 change → repopulate level2
  document.getElementById('pool-level1').addEventListener('change', (e) => {
    populateLevel2(e.target.value);
  });

  // Apply button
  document.getElementById('pool-apply-btn').addEventListener('click', applyPoolFilter);

  document.querySelector('.pool-table thead').addEventListener('click', (e) => {
    const th = e.target.closest('[data-sort-key]');
    if (!th) return;
    togglePoolSort(th.dataset.sortKey);
  });
  document.querySelector('.industry-rps-table thead').addEventListener('click', (e) => {
    const th = e.target.closest('[data-sort-key]');
    if (!th) return;
    toggleIndustryRpsSort(th.dataset.sortKey);
  });

  // Clear concept tags on init is not needed (they start empty)
  renderPoolSortIndicators();
  renderIndustryRpsSortIndicators();
}

// ─── Utilities ───────────────────────────────────────────────────────────────

function normalizeIndustryValues(value) {
  if (Array.isArray(value)) {
    return value
      .map(item => String(item || '').trim())
      .filter(Boolean);
  }
  const text = String(value || '').trim();
  return text ? [text] : [];
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
