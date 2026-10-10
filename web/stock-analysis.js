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

  const state = { timer: null, requestId: 0, financialRequestId: 0, selected: null, suggestions: [], recent: [] };

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
    const needsZeroAxis = variant === 'growth' || numeric.some((value) => value < 0);
    target.className = 'analysis-bar-chart';
    target.innerHTML = rows.map((row, index) => {
      const value = values[index];
      const label = Number.isFinite(value) ? formatter(value) : '—';
      if (needsZeroAxis) {
        const direction = value < 0 ? 'negative' : 'positive';
        const barSize = Number.isFinite(value) ? (value === 0 ? 0 : Math.max(3, Math.abs(value) / range * 100)) : 3;
        const zeroClass = value === 0 ? ' zero-value' : '';
        return `<div class="analysis-bar-item analysis-growth-item"><span class="analysis-bar-value">${label}</span><div class="analysis-bar-plot" style="--zero:${zero}%"><span class="analysis-zero-axis"></span><div class="analysis-bar zero-axis ${variant} ${direction}${zeroClass}" style="--bar-size:${barSize}%"></div></div><span class="analysis-bar-year">${periodLabel(row)}</span></div>`;
      }
      const height = Number.isFinite(value) ? (value === 0 ? 0 : Math.max(3, Math.abs(value) / maxAbs * 100)) : 3;
      const zeroClass = value === 0 ? ' zero-value' : '';
      return `<div class="analysis-bar-item"><span class="analysis-bar-value">${label}</span><div class="analysis-bar ${variant}${zeroClass}" style="height:${height}%"></div><span class="analysis-bar-year">${periodLabel(row)}</span></div>`;
    }).join('');
  }

  function renderAnnualBars(targetId, reports, metricKey, variant, display = 'amount') {
    const rows = latestRowsByYear(reports);
    const formatter = display === 'percent'
      ? (value) => `${value.toFixed(1)}%`
      : (value) => (value / 1e8).toFixed(1);
    renderBars(targetId, rows, rows.map((row) => Number(row?.metrics?.[metricKey])), formatter, variant);
  }

  function renderYoYGrowthBars(targetId, reports, metricKey, annualPeriods = null) {
    const annualReports = annualPeriods ? (reports || []).filter((row) => annualPeriods.has(String(row?.period))) : reports;
    const rows = latestRowsByYear(annualReports);
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

  function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  }

  function healthValue(value, suffix = '') {
    return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}${suffix}` : '—';
  }

  function healthEvidenceSummary(evidence) {
    if (!evidence) return '';
    const periods = Array.isArray(evidence.periods) ? evidence.periods.join(' / ') : '';
    const threshold = evidence.threshold ? `阈值：${evidence.threshold}` : evidence.thresholds ? `阈值：${Object.entries(evidence.thresholds).map(([key, value]) => `${key}=${value}`).join('；')}` : '';
    const metrics = evidence.metrics ? `指标：${Object.entries(evidence.metrics).map(([key, value]) => `${key}=${typeof value === 'number' ? Number(value).toFixed(2) : value ?? '—'}`).join('；')}` : '';
    const actual = evidence.actual !== undefined && evidence.actual !== null ? `实际：${typeof evidence.actual === 'object' ? JSON.stringify(evidence.actual) : healthValue(evidence.actual, 'pct')}` : '';
    const inputs = Array.isArray(evidence.inputs) && evidence.inputs.length ? `原始输入：${evidence.inputs.map((value) => {
      if (value && typeof value === 'object' && 'field' in value) return `${value.field}${value.period ? `[${value.period}]` : ''}=${typeof value.value === 'number' ? Number(value.value).toFixed(2) : value.value ?? '—'}`;
      return typeof value === 'number' ? Number(value).toFixed(2) : value ?? '—';
    }).join(' / ')}` : '';
    const subscores = evidence.subscores ? `子项得分：${Object.entries(evidence.subscores).map(([key, value]) => `${key}=${value ?? '—'}`).join('；')}` : '';
    const preTrend = evidence.pre_trend_points !== undefined && evidence.pre_trend_points !== null ? `趋势调整前：${healthValue(evidence.pre_trend_points)} 分` : '';
    const criteria = evidence.criteria ? Object.entries(evidence.criteria).map(([key, value]) => `${key}：${value}`).join('；') : '';
    return [periods && `比较期：${periods}`, metrics, threshold, actual, inputs, subscores, preTrend, criteria].filter(Boolean).join('；');
  }

  function healthEvidenceList(items, emptyMessage) {
    return items.length
      ? `<ul>${items.map((item) => `<li><strong>${escapeHTML(item.title || item.code || '未命名规则')}</strong>${item.detail || item.reason ? `：${escapeHTML(item.detail || item.reason)}` : ''}${healthEvidenceSummary(item.evidence) ? `<small class="health-rule-evidence">${escapeHTML(healthEvidenceSummary(item.evidence))}</small>` : ''}</li>`).join('')}</ul>`
      : `<p class="health-evidence-empty">${escapeHTML(emptyMessage)}</p>`;
  }

  function renderHealthEvidencePanels(health) {
    const redPanel = document.getElementById('health-red-flag-panel');
    const investigationPanel = document.getElementById('health-investigation-panel');
    const unavailablePanel = document.getElementById('health-unavailable-panel');
    const coverageDisclosure = document.getElementById('health-coverage-disclosure');
    const coverageInfo = health?.red_flag_coverage || {};
    const rules = health?.rule_results || [];
    const scoreBreakdown = health?.score_breakdown || [];
    const unavailable = [
      ...rules.filter((item) => item.status === 'unavailable').map((item) => ({ code: item.code, title: item.title || item.code, reason: item.reason || '比较数据不可用', evidence: item.evidence })),
      ...scoreBreakdown.filter((item) => item.available === false).map((item) => ({ code: `score-${item.code}`, title: item.title, reason: item.reason || '评分所需指标不可用' })),
    ];
    const evaluated = coverageInfo.evaluated ?? 0;
    const total = coverageInfo.total ?? 10;
    const triggeredRules = rules.filter((item) => item.status === 'triggered').map((item) => ({ code: item.code, title: item.title || item.code, detail: item.detail || '规则已触发。', evidence: item.evidence }));
    redPanel.innerHTML = healthEvidenceList(triggeredRules, evaluated === total ? '全部已评估规则均未触发红旗。' : `已评估的 ${evaluated} / ${total} 项规则中未触发红旗；其余规则未评估。`);
    investigationPanel.innerHTML = healthEvidenceList(health?.investigation_items || [], '暂无待调查事项。');
    unavailablePanel.innerHTML = healthEvidenceList(unavailable, '全部红旗规则及评分维度均有可用数据。');
    coverageDisclosure.textContent = `评分版本：${health?.score_version || '—'}；完整年报区间：${(health?.periods || []).join(' / ') || '—'}；红旗规则覆盖度：${coverageInfo.evaluated ?? 0} / ${coverageInfo.total ?? 10}；综合评分覆盖权重：${health?.coverage_weight ?? 0} / 100。`;
  }

  function renderHealthSeries(health) {
    const target = document.getElementById('health-series');
    const series = health?.series || {};
    const years = series.years || [];
    const rows = [
      ['现金利润比', 'annual_cash_profit_ratio', ''], ['FCF Margin', 'fcf_margin', '%'],
      ['应收增速差', 'receivable_growth_gap', 'pct'], ['存货增速差', 'inventory_growth_gap', 'pct'],
      ['CapEx 强度', 'capex_intensity', '%'], ['扣非 ROE', 'roe_ex', '%'],
      ['资产负债率', 'debt_ratio', '%'], ['商誉', 'goodwill', ''], ['商誉 / 资产', 'goodwill_assets_ratio', '%'], ['商誉 / 权益', 'goodwill_equity_ratio', '%'],
      ['毛利率', 'gross_margin', '%'], ['净利率', 'net_margin', '%'],
    ];
    if (!years.length) { target.textContent = '暂无可用五年派生序列。'; return; }
    target.innerHTML = `<table><thead><tr><th>指标</th>${years.map((year) => `<th>${escapeHTML(year)}</th>`).join('')}</tr></thead><tbody>${rows.map(([label, key, suffix]) => `<tr><th>${label}</th>${years.map((_, index) => `<td>${healthValue(series[key]?.[index], suffix)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }

  function renderFinancialHealth(health) {
    const period = document.getElementById('health-period');
    const score = document.getElementById('health-score');
    const flags = document.getElementById('health-red-flags');
    const coverage = document.getElementById('health-coverage');
    const dimensions = document.getElementById('health-dimensions');
    const derived = document.getElementById('health-derived');
    const conclusionPanel = document.getElementById('health-conclusions');
    if (!health) {
      period.textContent = '需要最近五个完整年度的财报数据';
      score.innerHTML = '数据不足 <small>/ 100</small>';
      flags.textContent = '—'; coverage.textContent = '—'; derived.textContent = '暂无可用 KPI 数据'; renderHealthSeries(null); renderHealthEvidencePanels(null); conclusionPanel.textContent = '暂无可用结论。'; return;
    }
    if (health.status === 'not_applicable') {
      const industry = [health?.industry?.level_1, health?.industry?.level_2].filter(Boolean).join(' · ');
      period.textContent = industry ? `行业：${industry}` : '行业适用性检查';
      score.innerHTML = '不适用 <small>通用规则</small>';
      flags.textContent = '—'; coverage.textContent = '—'; dimensions.innerHTML = ''; derived.textContent = '该行业须使用专用财务指标和阈值。';
      renderHealthSeries(null); renderHealthEvidencePanels(health); conclusionPanel.textContent = health.reason || '银行、保险、证券及房地产不适用通用工商企业健康度评分。'; return;
    }
    if (!Array.isArray(health.periods) || health.periods.length < 5) {
      const reason = health.reason === 'annual_reports_not_contiguous' ? '最近五个年报不连续，不能按五年口径计算。' : '需要最近五个连续完整年度的财报数据。';
      period.textContent = reason;
      score.innerHTML = '数据不足 <small>/ 100</small>';
      flags.textContent = '—'; coverage.textContent = '—'; dimensions.innerHTML = ''; derived.textContent = '暂无可用 KPI 数据'; renderHealthSeries(null); renderHealthEvidencePanels(health); conclusionPanel.textContent = '暂无可用结论。'; return;
    }
    period.textContent = `计算区间：${health.periods.join(' / ')}`;
    score.innerHTML = `${healthValue(health.score)} <small>/ 100</small>`;
    flags.textContent = `${health.red_flag_count || 0} 项`;
    coverage.textContent = `${health.coverage_weight || 0} / 100`;
    const scoreBreakdown = health.score_breakdown || [];
    const trendLabel = { up: '↑ 改善', down: '↓ 走弱', flat: '→ 平稳', unknown: '—' };
    const scoreEvidence = Object.fromEntries(scoreBreakdown.map((item) => [item.code, item.evidence]));
    dimensions.innerHTML = (health.dimensions || []).map((item) => `<article class="health-dimension ${escapeHTML(item.status)}"><div class="health-dimension-top"><span>${escapeHTML(item.title)}</span><span class="health-dimension-score">${item.available ? `${healthValue(item.score)} / ${item.weight}` : '数据不足'}</span></div><div class="health-dimension-trend">${trendLabel[item.trend] || '—'}</div>${healthEvidenceSummary(scoreEvidence[item.code]) ? `<small class="health-rule-evidence">${escapeHTML(healthEvidenceSummary(scoreEvidence[item.code]))}</small>` : ''}</article>`).join('');
    const d = health.derived || {};
    const latest = (health.series || {});
    const fields = [
      ['营收 CAGR', d.revenue_cagr, '%'], ['扣非利润 CAGR', d.ex_net_profit_cagr, '%'], ['利润增长溢价', d.profit_growth_premium, 'pct'], ['毛利率五年变化', d.gross_margin_change, 'pct'], ['净利率五年变化', d.net_margin_change, 'pct'],
      ['扣非 ROE 五年均值', d.roe_ex_average, '%'], ['最新扣非 ROE', latest.roe_ex?.at?.(-1), '%'], ['最新资产负债率', latest.debt_ratio?.at?.(-1), '%'], ['最新现金利润比', d.annual_cash_profit_ratio, ''], ['五年现金利润比', d.five_year_cash_profit_ratio, ''],
      ['FCF Margin', d.fcf_margin, '%'], ['应收增速差', d.receivable_growth_gap, 'pct'], ['存货增速差', d.inventory_growth_gap, 'pct'], ['CapEx 强度', d.capex_intensity, '%'], ['商誉 / 权益', d.goodwill_equity_ratio, '%'], ['商誉 / 资产', d.goodwill_assets_ratio, '%'],
    ];
    derived.innerHTML = fields.map(([label, value, suffix]) => `<div class="health-derived-item"><span class="health-derived-label">${label}</span><strong class="health-derived-value">${healthValue(value, suffix)}</strong></div>`).join('');
    renderHealthSeries(health);
    renderHealthEvidencePanels(health);
    const conclusionLabel = { improving: '改善', stable: '平稳', watch: '需关注', insufficient: '数据不足' };
    conclusionPanel.innerHTML = (health.conclusions || []).map((item) => `<article class="health-conclusion ${escapeHTML(item.status)}"><strong>${escapeHTML(item.question)}</strong><span>${conclusionLabel[item.status] || '—'}</span><p>${escapeHTML(item.detail)}</p>${healthEvidenceSummary(item.evidence) ? `<small class="health-rule-evidence">${escapeHTML(healthEvidenceSummary(item.evidence))}</small>` : ''}</article>`).join('') || '暂无可用结论。';
  }

  const METRIC_CHARTS = [
    ['revenue-chart', 'revenue', 'revenue', 'amount'],
    ['net-profit-chart', 'net_profit', 'profit', 'amount'],
    ['ex-net-profit-chart', 'ex_net_profit', 'profit', 'amount'],
    ['gross-margin-chart', 'gross_margin', 'ratio', 'percent'],
    ['net-margin-chart', 'net_margin', 'ratio', 'percent'],
    ['roe-ex-chart', 'roe_ex', 'ratio', 'percent'],
    ['debt-ratio-chart', 'debt_ratio', 'ratio', 'percent'],
    ['ocf-chart', 'ocf', 'cash', 'amount'],
    ['free-cf-chart', 'free_cf', 'cash', 'amount'],
    ['capex-chart', 'capex', 'cash', 'amount'],
    ['goodwill-chart', 'goodwill', 'asset', 'amount'],
    ['accounts-receivable-chart', 'accounts_receivable', 'asset', 'amount'],
    ['inventory-chart', 'inventory', 'asset', 'amount'],
  ];

  async function loadAnnualFinancials(stock) {
    const financialRequestId = ++state.financialRequestId;
    const chartIds = [...METRIC_CHARTS.map(([id]) => id), 'revenue-growth-chart'];
    renderFinancialHealth(null);
    for (const id of chartIds) {
      const el = document.getElementById(id);
      el.className = 'analysis-metric-status';
      el.textContent = '加载最近五年财报数据…';
    }
    try {
      // Request one extra year so the earliest displayed point can be compared
      // with the matching report period a year earlier.
      const response = await fetch(`/api/stock-score-report-history?market=${encodeURIComponent(stock.market)}&symbol=${encodeURIComponent(stock.symbol)}&years=6`);
      const payload = await response.json();
      if (financialRequestId !== state.financialRequestId) return;
      if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || `HTTP ${response.status}`);
      renderFinancialHealth(payload.health);
      const annualPeriods = new Set(payload.health?.periods || []);
      const evidenceReports = annualPeriods.size ? payload.reports.filter((row) => annualPeriods.has(String(row.period))) : payload.reports;
      for (const [id, metric, variant, display] of METRIC_CHARTS) renderAnnualBars(id, evidenceReports, metric, variant, display);
      renderYoYGrowthBars('revenue-growth-chart', payload.reports, 'revenue', annualPeriods);
    } catch (error) {
      if (financialRequestId !== state.financialRequestId) return;
      for (const id of chartIds) document.getElementById(id).textContent = `加载失败：${error.message}`;
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
