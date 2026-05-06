import { KlineChart } from './kline-chart.js';

const REALTIME_SCENARIOS = {
  tail_session: {
    label: '尾盘选股',
    conditions: {
      gain_min_pct: 3,
      gain_max_pct: 5,
      limit_up_lookback_days: 20,
      min_volume_ratio: 1.4,
      max_market_cap_yi: 200,
      turnover_min_pct: 5,
      turnover_max_pct: 10,
      intraday_above_vwap: true,
      intraday_above_vwap_min_ratio_pct: 80,
      intraday_vwap_max_breach_pct: 0.3,
      current_above_open: true,
      enable_gain_pct: true,
      enable_limit_up_lookback_days: true,
      enable_min_volume_ratio: true,
      enable_max_market_cap_yi: true,
      enable_turnover_pct: true,
      enable_intraday_above_vwap: true,
      enable_current_above_open: true,
    },
  },
};

let monitorTimer = null;
let klineChart = null;
let currentKlinePreset = 60;

const scenarioSelectEl = document.getElementById('realtime-scenario-select');
const loadScenarioBtn = document.getElementById('realtime-load-scenario');
const conditionForm = document.getElementById('realtime-condition-form');
const refreshSecondsEl = document.getElementById('realtime-refresh-seconds');
const startMonitorBtn = document.getElementById('realtime-start-monitor');
const stopMonitorBtn = document.getElementById('realtime-stop-monitor');
const statusEl = document.getElementById('realtime-status');
const tbody = document.getElementById('realtime-results-tbody');
const matchCountEl = document.getElementById('realtime-match-count');
const pageInfoEl = document.getElementById('realtime-page-info');

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

function formatPercent(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(2)}%`;
}

function formatMarketCapYi(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(1)}亿`;
}

function formatRank(rank, total) {
  const rankNum = Number(rank);
  if (!Number.isFinite(rankNum) || rankNum <= 0) return '—';
  const totalNum = Number(total);
  if (!Number.isFinite(totalNum) || totalNum <= 0) return String(Math.trunc(rankNum));
  return `${Math.trunc(rankNum)} / ${Math.trunc(totalNum)}`;
}

function setFieldValue(name, value) {
  const field = conditionForm.elements.namedItem(name);
  if (!field) return;
  if (field.type === 'checkbox') {
    field.checked = Boolean(value);
    return;
  }
  field.value = String(value ?? '');
}

function loadScenario() {
  const scenario = REALTIME_SCENARIOS[scenarioSelectEl.value] || REALTIME_SCENARIOS.tail_session;
  Object.entries(scenario.conditions).forEach(([name, value]) => setFieldValue(name, value));
  conditionForm.hidden = false;
  statusEl.textContent = `已加载方案：${scenario.label}`;
}

function fieldValue(name) {
  const field = conditionForm.elements.namedItem(name);
  if (!field) return '';
  if (field.type === 'checkbox') return field.checked ? 'true' : 'false';
  return String(field.value ?? '').trim();
}

function setConditionFormLocked(locked) {
  [...conditionForm.elements].forEach((field) => {
    field.disabled = locked;
  });
  scenarioSelectEl.disabled = locked;
  loadScenarioBtn.disabled = locked;
  refreshSecondsEl.disabled = locked;
}

function collectConditionPayload() {
  const names = [
    'gain_min_pct', 'gain_max_pct', 'limit_up_lookback_days', 'min_volume_ratio', 'max_market_cap_yi',
    'turnover_min_pct', 'turnover_max_pct', 'intraday_above_vwap', 'intraday_above_vwap_min_ratio_pct',
    'intraday_vwap_max_breach_pct', 'current_above_open', 'enable_gain_pct',
    'enable_limit_up_lookback_days', 'enable_min_volume_ratio', 'enable_max_market_cap_yi',
    'enable_turnover_pct', 'enable_intraday_above_vwap', 'enable_current_above_open',
  ];
  const params = new URLSearchParams();
  params.set('scenario', scenarioSelectEl.value || 'tail_session');
  params.set('monitor', 'true');
  params.set('refresh_seconds', String(Number(refreshSecondsEl.value || 30)));
  names.forEach((name) => {
    const text = fieldValue(name);
    if (text) params.set(name, text);
  });
  return params;
}

function renderRealtimeLoading() {
  matchCountEl.textContent = '…';
  pageInfoEl.textContent = '正在刷新...';
  tbody.innerHTML = '<tr><td colspan="9" class="stock-score-empty-row">正在刷新实时选股结果...</td></tr>';
}

async function refreshRealtimeMatches() {
  renderRealtimeLoading();
  const params = collectConditionPayload();
  try {
    const response = await fetch(`/api/realtime-screener?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.error?.message || payload?.error || `HTTP ${response.status}`);
    }
    renderRealtimeRows(payload.rows || []);
    matchCountEl.textContent = String((payload.rows || []).length);
    pageInfoEl.textContent = `${payload.scenario_label || '实时方案'} · ${payload.data_note || '实时行情'}`;
    statusEl.textContent = `监控中 · 每 ${payload.refresh_seconds || refreshSecondsEl.value || 30} 秒刷新`;
  } catch (error) {
    statusEl.textContent = `实时选股失败：${error.message}`;
    pageInfoEl.textContent = '刷新失败';
    matchCountEl.textContent = '0';
    tbody.innerHTML = '<tr><td colspan="9" class="stock-score-empty-row">实时选股失败，请稍后重试</td></tr>';
  }
}

function startRealtimeMonitor() {
  if (conditionForm.hidden) {
    statusEl.textContent = '请先加载方案，再启动监控';
    return;
  }
  stopRealtimeMonitor({ silent: true });
  const seconds = Math.max(5, Number(refreshSecondsEl.value || 30));
  refreshSecondsEl.value = String(seconds);
  setConditionFormLocked(true);
  statusEl.textContent = `监控中 · 每 ${seconds} 秒刷新`;
  refreshRealtimeMatches();
  monitorTimer = setInterval(refreshRealtimeMatches, seconds * 1000);
}

function stopRealtimeMonitor(options = {}) {
  if (monitorTimer) {
    clearInterval(monitorTimer);
    monitorTimer = null;
  }
  setConditionFormLocked(false);
  if (!options.silent) {
    statusEl.textContent = '监控已停止，可修改参数后重新启动';
  }
}

function renderRealtimeRows(rows) {
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="stock-score-empty-row">暂无满足条件的股票</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row) => {
    const marketSymbol = `${String(row.market || '').toUpperCase()}:${row.symbol || ''}`;
    const industryText = [row.industry_level_1, row.industry_level_2].filter(Boolean).join(' / ') || '—';
    return `<tr class="realtime-row" tabindex="0" data-market="${escapeHtml(row.market)}" data-symbol="${escapeHtml(row.symbol)}" data-name="${escapeHtml(row.stock_name || row.symbol)}">
      <td><strong>${escapeHtml(row.stock_name || row.symbol)}</strong><span class="stock-screener-symbol">${escapeHtml(marketSymbol)}</span></td>
      <td class="num">${formatNumber(row.current_price, 2)}</td>
      <td class="num">${formatPercent(row.gain_pct)}</td>
      <td class="num">${formatNumber(row.volume_ratio, 2)}</td>
      <td class="num">${formatMarketCapYi(row.market_cap_yi)}</td>
      <td class="num">${formatPercent(row.turnover_pct)}</td>
      <td>${escapeHtml(industryText)}</td>
      <td class="num">${formatNumber(row.industry_total_score, 1)}</td>
      <td class="num">${escapeHtml(formatRank(row.industry_total_rank, row.industry_total_universe_size))}</td>
    </tr>`;
  }).join('');
}

async function loadRealtimeKline(row) {
  const symbol = row?.dataset?.symbol;
  const name = row?.dataset?.name || symbol;
  if (!symbol) return;
  document.querySelectorAll('.realtime-row').forEach((tr) => tr.classList.toggle('row-selected', tr === row));
  document.getElementById('realtime-kline-section').classList.remove('hidden');
  document.getElementById('realtime-kline-title').textContent = `${symbol} — 加载中…`;
  try {
    const [klineRes, rpsRes] = await Promise.all([
      fetch(`/api/stock-kline?symbol=${encodeURIComponent(symbol)}&limit=300`),
      fetch(`/api/stock-rps-history?symbol=${encodeURIComponent(symbol)}`),
    ]);
    const klineJson = await klineRes.json();
    const rpsJson = await rpsRes.json();
    if (!klineJson.ok) {
      document.getElementById('realtime-kline-title').textContent = `${symbol} — 数据不可用`;
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
    const svg = document.getElementById('realtime-kline-svg');
    if (!klineChart) {
      klineChart = createRealtimeKlineChart(svg);
    }
    klineChart.load(bars, rpsHistory, currentKlinePreset);
    const stockName = bars[0]?.name || name || symbol;
    document.getElementById('realtime-kline-title').textContent = `${symbol} ${stockName}`;
    const range = klineChart.getVisibleRange();
    document.getElementById('realtime-kline-range-label').textContent = `${range.start} ~ ${range.end}`;
  } catch (error) {
    console.error('loadRealtimeKline error:', error);
    document.getElementById('realtime-kline-title').textContent = `${symbol} — 加载失败`;
  }
}

function createRealtimeKlineChart(svg) {
  const chart = new KlineChart(svg);
  chart.onViewportChange = () => {
    const range = chart.getVisibleRange();
    document.getElementById('realtime-kline-range-label').textContent = `${range.start} ~ ${range.end}`;
  };
  return chart;
}

function bindRealtimeChartPresetEvents() {
  const container = document.getElementById('realtime-preset-controls');
  container.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-preset]');
    if (!btn) return;
    const preset = parseInt(btn.dataset.preset, 10);
    container.querySelectorAll('.zoom-button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentKlinePreset = preset;
    if (klineChart && klineChart.bars.length) {
      klineChart.setPreset(preset);
      const range = klineChart.getVisibleRange();
      document.getElementById('realtime-kline-range-label').textContent = `${range.start} ~ ${range.end}`;
    }
  });
}

loadScenarioBtn.addEventListener('click', loadScenario);
startMonitorBtn.addEventListener('click', startRealtimeMonitor);
stopMonitorBtn.addEventListener('click', stopRealtimeMonitor);
tbody.addEventListener('click', (event) => {
  const row = event.target.closest('.realtime-row');
  if (row) loadRealtimeKline(row);
});
tbody.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const row = event.target.closest('.realtime-row');
  if (!row) return;
  event.preventDefault();
  loadRealtimeKline(row);
});

bindRealtimeChartPresetEvents();
statusEl.textContent = '请选择方案并点击加载方案';
