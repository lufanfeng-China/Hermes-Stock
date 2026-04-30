/**
 * rps-pool.js
 * RPS Pool Screener — industry/concept filter → pool table → K-line chart.
 * Also contains the full RPS ranking table with its own state.
 */

import { KlineChart } from './kline-chart.js';

// ─── State ────────────────────────────────────────────────────────────────────

let industryHierarchy = [];        // from /api/industry-hierarchy
let conceptList = [];              // from /api/concept-list
let selectedConcepts = new Set();  // concept_name strings

// Pool
let poolData = [];
let poolPage = 1;
const POOL_PAGE_SIZE = 50;
let poolSelectedSymbol = null;

// Full ranking
let fullRankingData = [];
let fullRankingPage = 1;
const RANKING_PAGE_SIZE = 50;
let fullRankingWindow = 20;
let fullRankingQuery = '';

// Chart
let poolKlineChart = null;
let currentKlinePreset = 60;

// ─── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);

async function init() {
  bindPoolEvents();
  bindRankingEvents();
  bindChartPresetEvents();
  await Promise.all([
    loadIndustryHierarchy(),
    loadConceptList(),
    loadFullRanking(),
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
  params.append('limit', '500');

  try {
    const res = await fetch(`/api/pool-filter?${params.toString()}`);
    const json = await res.json();
    if (!json.ok) {
      console.error('pool-filter error:', json);
      return;
    }
    poolData = json.results || [];
    poolPage = 1;
    document.getElementById('pool-section').classList.remove('hidden');
    document.getElementById('pool-count-badge').textContent = poolData.length;
    document.getElementById('pool-status').textContent =
      `股票池: ${json.pool_size} 只${poolData.length < json.pool_size ? ' (显示前' + poolData.length + ')' : ''}`;
    renderPoolTable();
  } catch (e) {
    console.error('applyPoolFilter error:', e);
  }
}

// ─── Pool Table ─────────────────────────────────────────────────────────────

function renderPoolTable() {
  const tbody = document.getElementById('pool-tbody');
  tbody.innerHTML = '';

  const start = (poolPage - 1) * POOL_PAGE_SIZE;
  const end = Math.min(start + POOL_PAGE_SIZE, poolData.length);
  const pageData = poolData.slice(start, end);
  const totalPages = Math.max(1, Math.ceil(poolData.length / POOL_PAGE_SIZE));

  if (poolData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="no-pool-results">股票池为空，请调整筛选条件</td></tr>`;
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
    const industry = (s.level1 || []).join(' / ');

    tr.innerHTML = `
      <td class="num">${idx}</td>
      <td>${s.symbol}</td>
      <td>${escapeHtml(s.stock_name || '')}</td>
      <td class="num">${s.rps_20 != null ? s.rps_20.toFixed(2) : '—'}</td>
      <td class="num">${s.rps_50 != null ? s.rps_50.toFixed(2) : '—'}</td>
      <td class="num" style="color:${s.return_20_pct > 0 ? '#ef5350' : '#26a69a'}">${ret20}</td>
      <td class="industry-cell" title="${escapeHtml(industry)}">${escapeHtml(industry)}</td>
      <td><button class="pool-kline-btn" data-symbol="${s.symbol}">K线</button></td>
    `;

    tr.addEventListener('click', (e) => {
      if (e.target.classList.contains('pool-kline-btn')) return;
      selectPoolRow(s.symbol);
    });

    tr.querySelector('.pool-kline-btn').addEventListener('click', (e) => {
      e.stopPropagation();
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
    }));

    const svg = document.getElementById('pool-kline-svg');
    if (!poolKlineChart) {
      poolKlineChart = new KlineChart(svg);
      poolKlineChart.onViewportChange = (vis) => {
        const range = poolKlineChart.getVisibleRange();
        document.getElementById('pool-kline-range-label').textContent =
          `${range.start} ~ ${range.end}`;
      };
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

// ─── Full RPS Ranking ────────────────────────────────────────────────────────

function bindRankingEvents() {
  // Window toggle
  document.getElementById('rps-window-controls').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-rps-window]');
    if (!btn) return;
    fullRankingWindow = parseInt(btn.dataset.rpsWindow, 10);
    document.querySelectorAll('#rps-window-controls .zoom-button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    fullRankingPage = 1;
    loadFullRanking();
  });

  // Search form
  document.getElementById('rps-ranking-form').addEventListener('submit', (e) => {
    e.preventDefault();
    fullRankingQuery = document.getElementById('rps-ranking-input').value.trim();
    fullRankingPage = 1;
    loadFullRanking();
  });

  // Pagination
  document.getElementById('rps-page-prev').addEventListener('click', () => {
    if (fullRankingPage > 1) { fullRankingPage--; loadFullRanking(); }
  });
  document.getElementById('rps-page-next').addEventListener('click', () => {
    fullRankingPage++;
    loadFullRanking();
  });
}

async function loadFullRanking() {
  try {
    const params = new URLSearchParams({ window: fullRankingWindow, limit: '99999' });
    if (fullRankingQuery) params.set('q', fullRankingQuery);
    const res = await fetch(`/api/rps-ranking?${params.toString()}`);
    const json = await res.json();
    if (!json.ok) return;
    fullRankingData = json.results || [];
    renderFullRankingTable();
  } catch (e) {
    console.error('loadFullRanking error:', e);
  }
}

function renderFullRankingTable() {
  const tbody = document.getElementById('rps-ranking-tbody');
  tbody.innerHTML = '';

  const start = (fullRankingPage - 1) * RANKING_PAGE_SIZE;
  const end = Math.min(start + RANKING_PAGE_SIZE, fullRankingData.length);
  const pageData = fullRankingData.slice(start, end);
  const totalPages = Math.max(1, Math.ceil(fullRankingData.length / RANKING_PAGE_SIZE));

  document.getElementById('rps-ranking-meta').textContent =
    `${fullRankingData.length} ${fullRankingWindow}D RPS leaders`;

  if (fullRankingData.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:#555;padding:30px">无匹配结果</td></tr>`;
    document.getElementById('rps-page-prev').disabled = true;
    document.getElementById('rps-page-next').disabled = true;
    document.getElementById('rps-page-info').textContent = '0 / 1';
    return;
  }

  for (let i = 0; i < pageData.length; i++) {
    const s = pageData[i];
    const rank = start + i + 1;
    const rpsKey = `rps_${fullRankingWindow}`;
    const retKey = `return_${fullRankingWindow}_pct`;
    const rps = s[rpsKey];
    const ret = s[retKey];
    const retStr = ret != null ? `${ret > 0 ? '+' : ''}${ret.toFixed(2)}%` : '—';

    const tr = document.createElement('tr');
    tr.dataset.symbol = s.symbol;
    tr.innerHTML = `
      <td>${rank}</td>
      <td>${s.symbol}</td>
      <td>${escapeHtml(s.stock_name || s.name || '')}</td>
      <td>${rps != null ? rps.toFixed(2) : '—'}</td>
      <td style="color:${ret > 0 ? '#ef5350' : '#26a69a'}">${retStr}</td>
      <td>${fullRankingWindow}D</td>
    `;
    tr.style.cursor = 'pointer';
    tr.addEventListener('click', () => selectFullRankingRow(s.symbol));
    tbody.appendChild(tr);
  }

  document.getElementById('rps-page-prev').disabled = fullRankingPage <= 1;
  document.getElementById('rps-page-next').disabled = fullRankingPage >= totalPages;
  document.getElementById('rps-page-info').textContent = `${fullRankingPage} / ${totalPages}`;
}

function selectFullRankingRow(symbol) {
  // Deselect pool row
  poolSelectedSymbol = null;
  for (const tr of document.querySelectorAll('#pool-tbody tr')) {
    tr.classList.remove('row-selected');
  }
  selectPoolSymbol(symbol);
}

// ─── Pool Events (bind once) ─────────────────────────────────────────────────

function bindPoolEvents() {
  // Level1 change → repopulate level2
  document.getElementById('pool-level1').addEventListener('change', (e) => {
    populateLevel2(e.target.value);
  });

  // Apply button
  document.getElementById('pool-apply-btn').addEventListener('click', applyPoolFilter);

  // Clear concept tags on init is not needed (they start empty)
}

// ─── Utilities ───────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
