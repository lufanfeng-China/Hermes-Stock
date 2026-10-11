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

  const FINANCIAL_CACHE_TTL_MS = 5 * 60 * 1000;
  const MAX_FINANCIAL_CACHE_ENTRIES = 24;
  const state = { timer: null, requestId: 0, financialRequestId: 0, financialAbortController: null, financialCache: new Map(), healthComparison: null, selected: null, suggestions: [], recent: [] };

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
    return [...latestByYear.values()].sort((a, b) => String(a.year).localeCompare(String(b.year))).slice(-6);
  }

  function appendLatestQuarter(annualReports, allReports) {
    const quarters = (allReports || []).filter((row) => !String(row?.period || '').endsWith('A'));
    const latestQuarter = quarters.sort((a, b) => String(a?.report_date || '').localeCompare(String(b?.report_date || ''))).at(-1);
    return latestQuarter ? [...(annualReports || []), latestQuarter] : (annualReports || []);
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
      const reportClass = String(row?.period || '').endsWith('A') ? '' : ' latest-quarter';
      if (needsZeroAxis) {
        const direction = value < 0 ? 'negative' : 'positive';
        const barSize = Number.isFinite(value) ? (value === 0 ? 0 : Math.max(3, Math.abs(value) / range * 100)) : 3;
        const zeroClass = value === 0 ? ' zero-value' : '';
        return `<div class="analysis-bar-item analysis-growth-item${reportClass}"><span class="analysis-bar-value">${label}</span><div class="analysis-bar-plot" style="--zero:${zero}%"><span class="analysis-zero-axis"></span><div class="analysis-bar zero-axis ${variant} ${direction}${zeroClass}" style="--bar-size:${barSize}%"></div></div><span class="analysis-bar-year">${periodLabel(row)}</span></div>`;
      }
      const height = Number.isFinite(value) ? (value === 0 ? 0 : Math.max(3, Math.abs(value) / maxAbs * 100)) : 3;
      const zeroClass = value === 0 ? ' zero-value' : '';
      return `<div class="analysis-bar-item${reportClass}"><span class="analysis-bar-value">${label}</span><div class="analysis-bar ${variant}${zeroClass}" style="height:${height}%"></div><span class="analysis-bar-year">${periodLabel(row)}</span></div>`;
    }).join('');
  }

  function renderAnnualBars(targetId, reports, metricKey, variant, display = 'amount') {
    const rows = latestRowsByYear(reports);
    const formatter = display === 'percent'
      ? (value) => `${value.toFixed(1)}%`
      : (value) => (value / 1e8).toFixed(1);
    renderBars(targetId, rows, rows.map((row) => Number(row?.metrics?.[metricKey])), formatter, variant);
  }

  function renderYoYGrowthBars(targetId, reports, metricKey, annualPeriods = null, comparisonReports = reports) {
    const annualReports = annualPeriods ? (reports || []).filter((row) => annualPeriods.has(String(row?.period)) || !String(row?.period || '').endsWith('A')) : reports;
    const rows = latestRowsByYear(annualReports);
    const byPeriod = new Map((comparisonReports || []).map((row) => [String(row?.period || ''), row]));
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

  const HEALTH_FIELD_LABELS = {
    revenue: '营业收入', ex_net_profit: '扣非归母净利润', net_profit: '归母净利润', ocf: '经营现金流', free_cf: '自由现金流', capex: '资本开支', goodwill: '商誉',
    debt_ratio: '资产负债率', roe_ex: '扣非 ROE', gross_margin: '毛利率', net_margin: '净利率', accounts_receivable: '应收账款', inventory: '存货',
    revenue_cagr: '营业收入复合增长率', ex_net_profit_cagr: '扣非归母净利润复合增长率', profit_premium: '利润增长溢价',
    gross_margin_change: '毛利率五年变化', net_margin_change: '净利率五年变化', roe_ex_change: '扣非 ROE 五年变化',
    annual_cash_profit_ratio: '最新现金利润比', five_year_cash_profit_ratio: '五年现金利润比', fcf_margin: '自由现金流率', fcf_margin_change: '自由现金流率变化',
    receivable_growth_gap: '应收账款增速差', inventory_growth_gap: '存货增速差', capex_intensity: '资本开支强度', capex_intensity_trend: '资本开支强度趋势',
    revenue_growth_trend: '营收增长趋势', debt_ratio_trend: '资产负债率趋势', goodwill_equity_ratio: '商誉／权益比', goodwill_equity_trend: '商誉／权益趋势',
  };
  const HEALTH_SCORE_COMPONENT_LABELS = {
    growth: '营收增长', adjusted_profit: '扣非利润增长', premium: '利润增长溢价', gross_margin: '毛利率', net_margin: '净利率', roe: '扣非 ROE',
    annual_cash_profit: '最新现金利润比', five_year_cash_profit: '五年现金利润比', fcf_margin: '自由现金流率', receivable: '应收账款周转', inventory: '存货周转',
    capex_intensity: '资本开支强度', revenue_growth: '营收增长趋势', debt_ratio: '资产负债率', goodwill_equity: '商誉／权益比',
  };
  const HEALTH_METRIC_TOOLTIPS = {
    revenue_cagr: { definition: '五年营业收入的年均复合增长率，反映收入规模的长期扩张速度。', judgement: '持续为正且更高通常更好；增速明显放缓或转负需要关注。' },
    ex_net_profit_cagr: { definition: '五年扣非归母净利润的年均复合增长率，尽量剔除一次性损益影响。', judgement: '持续为正且不低于营收增速通常更好；利润下滑或落后于营收需关注。' },
    profit_growth_premium: { definition: '扣非利润 CAGR 减去营收 CAGR，衡量利润增长是否跑赢收入增长。', judgement: '为正表示利润扩张优于收入；为负表示利润增长落后于收入。' },
    gross_margin: { definition: '毛利占营业收入的比例，反映产品或服务在直接成本后的盈利空间。', judgement: '上升或稳定通常更好；连续下降可能意味着成本、价格或产品结构承压。' },
    net_margin: { definition: '归母净利润占营业收入的比例，反映收入最终转化为净利润的效率。', judgement: '上升或稳定通常更好；下降表示费用、减值或经营效率可能承压。' },
    roe_ex: { definition: '扣除非经常性损益后的净资产收益率，反映股东资本的经常性回报。', judgement: '较高且稳定或上升通常更好；连续下降需关注盈利质量或资本效率。' },
    annual_cash_profit_ratio: { definition: '经营现金流净额除以扣非归母净利润，衡量当期利润的现金回收。', judgement: '接近或高于 0.8 通常说明现金支撑较好；长期偏低或为负需关注。' },
    five_year_cash_profit_ratio: { definition: '五年经营现金流合计除以五年扣非归母净利润合计，观察长期利润现金化。', judgement: '接近或高于 0.8 通常较好；长期偏低说明利润兑现为现金不足。' },
    fcf_margin: { definition: '自由现金流除以营业收入；自由现金流等于经营现金流减资本开支。', judgement: '为正且上升通常更好；持续为负或下降意味着投入后的现金回报承压。' },
    receivable_growth_gap: { definition: '应收账款同比增速减去营收同比增速，衡量应收是否快于收入扩张。', judgement: '较低或为负通常更好；高于营收 15 个百分点以上会触发关注。' },
    inventory_growth_gap: { definition: '存货同比增速减去营收同比增速，衡量库存是否快于收入扩张。', judgement: '较低或为负通常更好；高于营收 15 个百分点以上会触发关注。' },
    capex_intensity: { definition: '资本开支除以营业收入，反映维持和扩张经营所需的投入强度。', judgement: '高低本身不判好坏；投入可控且营收、自由现金流同步改善较好，反之需关注。' },
    debt_ratio: { definition: '总负债占总资产的比例，反映资产负债表的杠杆水平。', judgement: '在同业可比前提下，下降或保持可控通常更好；持续上升会增加偿债压力。' },
    goodwill: { definition: '并购形成、未来可能需要减值测试的商誉账面余额。', judgement: '稳定且有利润、现金流支撑较好；快速增加但利润未兑现需关注。' },
    goodwill_assets_ratio: { definition: '商誉占总资产的比例，衡量商誉对资产负债表的占用。', judgement: '较低或下降通常风险更低；持续上升意味着潜在减值影响扩大。' },
    goodwill_equity_ratio: { definition: '商誉占股东权益的比例，衡量商誉对净资产的潜在影响。', judgement: '较低或下降通常风险更低；持续上升时应关注减值对净资产的冲击。' },
  };

  function healthMetricLabel(key, label) {
    const tooltip = HEALTH_METRIC_TOOLTIPS[key];
    if (!tooltip) return escapeHTML(label);
    const content = `定义：${tooltip.definition}\n判断：${tooltip.judgement}`;
    return `<span class="health-metric-tooltip" tabindex="0" data-health-tooltip="${escapeHTML(content)}" title="${escapeHTML(content)}" aria-label="${escapeHTML(`${label}。${content}`)}"><span class="health-metric-tooltip-trigger">${escapeHTML(label)}</span></span>`;
  }

  const HEALTH_AMOUNT_FIELDS = new Set(['revenue', 'ex_net_profit', 'net_profit', 'ocf', 'free_cf', 'capex', 'goodwill', 'accounts_receivable', 'inventory']);
  function healthEvidenceValue(key, value) {
    if (typeof value !== 'number') return value ?? '—';
    if (HEALTH_AMOUNT_FIELDS.has(key)) return `${(value / 1e8).toFixed(2)} 亿元`;
    if (/(ratio|margin|roe|debt|intensity|growth_gap|cagr|premium|change)/.test(key)) return `${value.toFixed(2)}%`;
    return value.toFixed(2);
  }

  function healthEvidenceSummary(evidence) {
    if (!evidence) return '';
    const periods = Array.isArray(evidence.periods) ? evidence.periods.join(' / ') : '';
    const threshold = evidence.threshold ? `阈值：${evidence.threshold}` : evidence.thresholds ? `阈值：${Object.entries(evidence.thresholds).map(([key, value]) => `${key}=${value}`).join('；')}` : '';
    const metrics = evidence.metrics ? `指标：${Object.entries(evidence.metrics).map(([key, value]) => `${HEALTH_FIELD_LABELS[key] || key}=${healthEvidenceValue(key, value)}`).join('；')}` : '';
    const actual = evidence.actual !== undefined && evidence.actual !== null ? `实际：${typeof evidence.actual === 'object' ? JSON.stringify(evidence.actual) : healthValue(evidence.actual, 'pct')}` : '';
    const inputs = Array.isArray(evidence.inputs) && evidence.inputs.length ? `原始输入：${evidence.inputs.map((value) => {
      if (value && typeof value === 'object' && 'field' in value) return `${HEALTH_FIELD_LABELS[value.field] || value.field}${value.period ? `[${value.period}]` : ''}=${healthEvidenceValue(value.field, value.value)}`;
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

  function renderHealthEvidencePanels(health, uiState = 'ready') {
    const redPanel = document.getElementById('health-red-flag-panel');
    const investigationPanel = document.getElementById('health-investigation-panel');
    const unavailablePanel = document.getElementById('health-unavailable-panel');
    const coverageDisclosure = document.getElementById('health-coverage-disclosure');
    if (!health && uiState !== 'ready') {
      const message = uiState === 'failed' ? '健康度数据加载失败；尚未完成规则与评分评估。' : '正在加载财报与健康度评估结果。';
      redPanel.innerHTML = healthEvidenceList([], message);
      investigationPanel.innerHTML = healthEvidenceList([], message);
      unavailablePanel.innerHTML = healthEvidenceList([], message);
      coverageDisclosure.textContent = message;
      return;
    }
    const coverageInfo = health?.red_flag_coverage || {};
    const rules = health?.rule_results || [];
    const investigationResults = health?.investigation_results || [];
    const investigationCoverage = health?.investigation_coverage || {};
    const investigationUnavailable = investigationCoverage.unavailable || [];
    const investigationEvaluated = investigationCoverage.evaluated ?? investigationResults.length;
    const investigationTotal = investigationCoverage.total ?? investigationResults.length;
    const scoreBreakdown = health?.score_breakdown || [];
    const unavailable = [
      ...rules.filter((item) => item.status === 'unavailable').map((item) => ({ code: item.code, title: item.title || item.code, reason: item.reason || '比较数据不可用', evidence: item.evidence })),
      ...scoreBreakdown.filter((item) => item.available === false).map((item) => ({ code: `score-${item.code}`, title: item.title, reason: item.reason || '评分所需指标不可用' })),
    ];
    const evaluated = coverageInfo.evaluated ?? 0;
    const total = coverageInfo.total ?? 10;
    const triggeredRules = rules.filter((item) => item.status === 'triggered').map((item) => {
      const high = new Set(['fcf_two_year_negative', 'ex_profit_up_ocf_down', 'revenue_up_ex_profit_down', 'debt_ratio_rising']);
      const tier = high.has(item.code) ? '高优先级' : '关注';
      return { ...item, title: `${tier}｜${item.title || item.code}`, detail: item.detail || '规则已触发。' };
    });
    redPanel.innerHTML = healthEvidenceList(triggeredRules, evaluated === total ? '全部已评估规则均未触发红旗。' : `已评估的 ${evaluated} / ${total} 项规则中未触发红旗；其余规则未评估。`);
    const triggeredInvestigations = investigationResults.filter((item) => item.status === 'triggered');
    const investigationEmptyMessage = investigationUnavailable.length
      ? `有 ${investigationUnavailable.length} 项调查规则未评估：${investigationUnavailable.join('、')}。`
      : investigationEvaluated < investigationTotal
        ? `调查规则仅评估 ${investigationEvaluated} / ${investigationTotal} 项；其余规则未评估。`
        : '暂无待调查事项。';
    investigationPanel.innerHTML = healthEvidenceList(triggeredInvestigations, investigationEmptyMessage);
    unavailablePanel.innerHTML = healthEvidenceList(unavailable, '未发现不可用规则或评分维度。');
    coverageDisclosure.textContent = `评分版本：${health?.score_version || '—'}；完整年报区间：${(health?.periods || []).join(' / ') || '—'}；已评估红旗规则：${coverageInfo.evaluated ?? 0} / ${coverageInfo.total ?? 10}；已评估调查规则：${investigationEvaluated} / ${investigationTotal}；调查规则未评估：${investigationUnavailable.length} 项；综合评分覆盖权重：${health?.coverage_weight ?? 0} / 100。`;
  }

  function healthSeriesValue(key, value, suffix) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '—';
    return key === 'goodwill' ? `${(numeric / 1e8).toFixed(2)} 亿元` : healthValue(numeric, suffix);
  }

  function healthMetricTone(key, value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return '';
    const between = (good, bad) => numeric >= good ? 'metric-positive' : numeric <= bad ? 'metric-negative' : '';
    switch (key) {
      case 'revenue_cagr':
      case 'ex_net_profit_cagr': return between(10, 0);
      case 'profit_growth_premium': return between(5, -5);
      case 'gross_margin_change':
      case 'net_margin_change': return between(3, -3);
      case 'gross_margin': return between(40, 10);
      case 'net_margin': return between(15, 0);
      case 'roe_ex': return between(15, 0);
      case 'annual_cash_profit_ratio':
      case 'five_year_cash_profit_ratio': return between(1, 0.6);
      case 'fcf_margin': return between(5, 0);
      case 'receivable_growth_gap':
      case 'inventory_growth_gap': return numeric <= -10 ? 'metric-positive' : numeric >= 15 ? 'metric-negative' : '';
      case 'debt_ratio': return numeric <= 40 ? 'metric-positive' : numeric >= 70 ? 'metric-negative' : '';
      case 'debt_ratio_trend': return numeric <= -3 ? 'metric-positive' : numeric >= 3 ? 'metric-negative' : '';
      case 'goodwill': return numeric === 0 ? 'metric-positive' : '';
      case 'goodwill_growth': return numeric <= 0 ? 'metric-positive' : numeric >= 30 ? 'metric-negative' : '';
      case 'goodwill_assets_ratio': return numeric <= 5 ? 'metric-positive' : numeric >= 30 ? 'metric-negative' : '';
      case 'goodwill_equity_ratio': return numeric <= 10 ? 'metric-positive' : numeric >= 50 ? 'metric-negative' : '';
      default: return '';
    }
  }

  function healthMetricValue(key, value, suffix = '') {
    const display = healthSeriesValue(key, value, suffix);
    const tone = healthMetricTone(key, value);
    return `<span class="health-metric-value ${tone}">${display}</span>`;
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
    target.innerHTML = `<table><thead><tr><th>指标</th>${years.map((year) => `<th>${escapeHTML(year)}</th>`).join('')}</tr></thead><tbody>${rows.map(([label, key, suffix, tooltipKey]) => `<tr><th>${healthMetricLabel(tooltipKey || key, label)}</th>${years.map((_, index) => `<td>${healthMetricValue(key, series[key]?.[index], suffix)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }

  function scoreFormationCopy(item, scoreItem) {
    if (!item?.available || !scoreItem) return '';
    const base = healthValue(scoreItem.evidence?.pre_trend_points);
    const adjustment = Number(scoreItem.trend_adjustment || 0);
    const finalPoints = healthValue(scoreItem.points);
    if (item.code === 'growth_quality') {
      const metrics = scoreItem.evidence?.metrics || {};
      const subscores = scoreItem.evidence?.subscores || {};
      const growthReason = Number(metrics.revenue_cagr) > 0 && Number(metrics.ex_net_profit_cagr) > 0
        ? '营收与扣非利润五年仍保持增长'
        : '营收或扣非利润五年增长不足';
      const speedReason = subscores.growth <= 3 && subscores.adjusted_profit <= 3
        ? '，但复合增速均处于基础档'
        : '';
      const premiumReason = Number(metrics.profit_premium) < 0 ? '，且扣非利润增速略落后于营收' : '';
      const trendReason = adjustment < 0
        ? '营收增速较高点回落，扣非利润近年承压'
        : adjustment > 0
          ? '营收与扣非利润的年度增速整体改善'
          : '营收与扣非利润的年度增速整体平稳';
      return `调整前 ${base} 分：${growthReason}${speedReason}${premiumReason}。\n趋势调整 ${adjustment > 0 ? '+' : ''}${adjustment.toFixed(1)} 分：${trendReason}。\n最终 ${finalPoints} / ${item.weight} 分`;
    }
    const copy = (() => {
      switch (item.code) {
        case 'profitability':
          return { base: '利润率与扣非 ROE 的综合表现形成基础分', down: '利润率或扣非 ROE 整体走弱', up: '利润率与扣非 ROE 整体改善', flat: '利润率与扣非 ROE 整体平稳' };
        case 'cash_quality':
          return { base: '经营现金回收与自由现金流的表现形成基础分', down: '现金转化趋势走弱', up: '现金转化趋势改善', flat: '现金转化趋势平稳' };
        case 'working_capital':
          return { base: '应收与存货相对营收的变化形成基础分', down: '营运资金占用相对营收走弱', up: '营运资金占用相对营收改善', flat: '营运资金占用相对营收平稳' };
        case 'reinvestment':
          return { base: '资本投入、营收增长与自由现金流的联动形成基础分', down: '投入与现金回报的联动走弱', up: '投入与现金回报的联动改善', flat: '投入与现金回报的联动平稳' };
        case 'financial_risk':
          return { base: '负债、商誉与自由现金流的综合风险形成基础分', down: '五年风险趋势已计入基础分，未额外调整', up: '五年风险趋势已计入基础分，未额外调整', flat: '五年风险趋势已计入基础分，未额外调整' };
        default:
          return { base: '相关财务表现形成基础分', down: '整体趋势走弱', up: '整体趋势改善', flat: '整体趋势平稳' };
      }
    })();
    const trendReason = adjustment < 0 ? copy.down : adjustment > 0 ? copy.up : copy.flat;
    return `调整前 ${base} 分：${copy.base}。\n趋势调整 ${adjustment > 0 ? '+' : ''}${adjustment.toFixed(1)} 分：${trendReason}。\n最终 ${finalPoints} / ${item.weight} 分`;
  }

  function conclusionSummary(item) {
    const status = item?.status || 'insufficient';
    const copy = (() => {
      switch (item?.code) {
        case 'growth':
          return { improving: '营收与扣非利润五年保持增长，增长连续性较好。', watch: '营收或扣非利润的增长不连续，增长质量需关注。', stable: '营收与扣非利润整体保持平稳。', insufficient: '缺少连续可比的营收或扣非利润数据。', focus: '关键指标：营收、扣非利润' };
        case 'profit_premium':
          return { improving: '扣非利润增长快于营收，增长质量较好。', watch: '扣非利润增长未跑赢营收，利润扩张需关注。', stable: '利润与营收增速基本匹配。', insufficient: '缺少可比的营收或扣非利润增长数据。', focus: '关键指标：营收增速、扣非利润增速' };
        case 'profitability':
          return { improving: '利润率与扣非 ROE 整体改善，盈利能力增强。', watch: '利润率或扣非 ROE 出现走弱，盈利能力需关注。', stable: '利润率与扣非 ROE 整体平稳。', insufficient: '缺少利润率或扣非 ROE 的连续数据。', focus: '关键指标：毛利率、净利率、扣非 ROE' };
        case 'cash_conversion':
          return { improving: '利润向经营现金和自由现金流的转化在改善。', watch: '现金转化或自由现金流承压，需关注利润含金量。', stable: '现金转化能力整体平稳。', insufficient: '缺少经营现金流、自由现金流或利润数据。', focus: '关键指标：现金利润比、FCF Margin' };
        case 'working_capital':
          return { improving: '应收和存货对资金的占用相对营收在改善。', watch: '应收或存货增速明显快于营收，资金占用需关注。', stable: '应收和存货相对营收的占用整体平稳。', insufficient: '缺少应收、存货或营收的可比数据。', focus: '关键指标：应收、存货相对营收增速' };
        case 'capital_leverage':
          return { improving: '资本投入、负债与自由现金流的配合在改善。', watch: '资本投入或负债上升与现金回报不匹配，需关注。', stable: '资本投入与财务杠杆整体可控。', insufficient: '缺少资本开支、负债或现金流的连续数据。', focus: '关键指标：CapEx 强度、资产负债率、FCF Margin' };
        default:
          return { improving: '核心指标整体改善。', watch: '核心指标存在需关注项。', stable: '核心指标整体平稳。', insufficient: '可用数据不足。', focus: '关键指标：相关财务指标' };
      }
    })();
    return { summary: copy[status] || copy.insufficient, focus: copy.focus };
  }

  function scoreDetailButton(source, item) {
    const value = item?.points ?? item?.score;
    if (item?.available === false || value === null || value === undefined || !Number.isFinite(Number(value))) return '<span class="comparison-unavailable">—</span>';
    return `<button type="button" class="comparison-score-button" data-score-source="${source}" data-score-code="${escapeHTML(item.code)}" aria-label="查看${escapeHTML(item.title || item.code)}得分由来">${Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1)}</button>`;
  }

  function showHealthScoreDetail(source, code) {
    const dialog = document.getElementById('health-score-detail-dialog');
    const title = document.getElementById('health-score-detail-title');
    const content = document.getElementById('health-score-detail-content');
    const data = state.healthComparison;
    if (!dialog || !title || !content || !data) return;
    if (source === 'annual') {
      const scoreItem = (data.health?.score_breakdown || []).find((item) => item.code === code);
      const dimension = (data.health?.dimensions || []).find((item) => item.code === code);
      if (!scoreItem) return;
      title.textContent = `五年年报｜${scoreItem.title}得分由来`;
      const evidence = scoreItem.evidence || {};
      const metrics = Object.entries(evidence.metrics || {}).map(([key, value]) => `<dt>${escapeHTML(HEALTH_FIELD_LABELS[key] || key)}</dt><dd>${escapeHTML(healthEvidenceValue(key, value))}</dd>`).join('');
      const subscores = Object.entries(evidence.subscores || {}).map(([key, value]) => `<dt>子项：${escapeHTML(HEALTH_SCORE_COMPONENT_LABELS[key] || key)}</dt><dd>${escapeHTML(String(value))}</dd>`).join('');
      const thresholds = Object.entries(evidence.thresholds || {}).map(([key, value]) => `${HEALTH_SCORE_COMPONENT_LABELS[key] || HEALTH_FIELD_LABELS[key] || key}：${value}`).join('；');
      const formation = scoreFormationCopy(dimension, scoreItem).split('\n').map(escapeHTML).join('<br>');
      content.innerHTML = `<p class="health-score-detail-score">${scoreItem.points} / ${scoreItem.weight}</p><p>${formation}</p><dl>${metrics}${subscores}<dt>评分阈值</dt><dd>${escapeHTML(thresholds || '—')}</dd></dl>`;
    } else {
      const scoreItem = (data.monitor?.realtime_score?.breakdown || []).find((item) => item.code === code);
      const dimension = (data.monitor?.dimensions || []).find((item) => item.code === code);
      if (!scoreItem) return;
      const statusLabel = { improving: '改善', stable: '平稳', watch: '需关注' }[scoreItem.status] || '不可用';
      const ratio = { improving: '100%', stable: '60%', watch: '25%' }[scoreItem.status] || '—';
      title.textContent = `最新季报｜${scoreItem.title}得分由来`;
      content.innerHTML = `<p class="health-score-detail-score">${scoreItem.points} / ${scoreItem.weight}</p><dl><dt>季度状态</dt><dd>${statusLabel}</dd><dt>评分规则</dt><dd>改善计权重的 100%；平稳计 60%；需关注计 25%。本项按 ${ratio} 折算。</dd><dt>本期依据</dt><dd>${escapeHTML(dimension?.detail || '数据不足')}</dd><dt>口径</dt><dd>最新季度流量按 TTM，资产负债表项目使用最新期末余额。</dd></dl>`;
    }
    dialog.showModal();
  }

  function showHealthOverallDetail(source) {
    const dialog = document.getElementById('health-overall-detail-dialog'); const content = document.getElementById('health-overall-detail-content');
    const data = state.healthComparison; if (!dialog || !content || !data) return;
    const items = ({ annual: data.health.conclusions, quarterly: data.monitor.alerts })[source] || [];
    const label = source === 'annual' ? '五年年报总体分析结论' : '最新季报总体分析结论';
    content.innerHTML = `<h3>${label}</h3>${items.length ? `<ul>${items.map((item) => `<li>${escapeHTML(item.summary || item.detail || item.reason || item.title || String(item))}</li>`).join('')}</ul>` : '<p>当前口径没有可用的总体分析结论。</p>'}`;
    dialog.showModal();
  }

  function showHealthFlagDetail(source) {
    const dialog = document.getElementById('health-flag-detail-dialog'); const content = document.getElementById('health-flag-detail-content');
    const data = state.healthComparison; if (!dialog || !content || !data) return;
    const items = source === 'annual' ? (data.health?.rule_results || []).filter((item) => item.status === 'triggered') : (data.monitor?.alerts || []);
    content.innerHTML = items.length ? `<ul>${items.map((item) => `<li><strong>${escapeHTML(item.title || item.code)}</strong>：${escapeHTML(item.detail || item.reason || item.evidence?.threshold || '已触发规则')}</li>`).join('')}</ul>` : '<p>未触发红旗或季度预警。</p>';
    dialog.showModal();
  }

  function renderHealthMetrics(health) {
    const target = document.getElementById('health-derived');
    if (!target) return;
    if (!health) { target.textContent = '选择股票后加载。'; renderHealthSeries(null); return; }
    const d = health.derived || {}; const series = health.series || {};
    const rows = [
      ['营业收入复合增长率', 'revenue_cagr', d.revenue_cagr, '%'], ['扣非归母净利润复合增长率', 'ex_net_profit_cagr', d.ex_net_profit_cagr, '%'], ['利润增长溢价', 'profit_premium', d.profit_growth_premium, 'pct'],
      ['毛利率五年变化', 'gross_margin_change', d.gross_margin_change, 'pct'], ['净利率五年变化', 'net_margin_change', d.net_margin_change, 'pct'], ['扣非 ROE 五年均值', 'roe_ex', d.roe_ex_average, '%'],
      ['最新现金利润比', 'annual_cash_profit_ratio', d.annual_cash_profit_ratio, ''], ['五年现金利润比', 'five_year_cash_profit_ratio', d.five_year_cash_profit_ratio, ''], ['自由现金流率', 'fcf_margin', d.fcf_margin, '%'],
      ['应收账款增速差', 'receivable_growth_gap', d.receivable_growth_gap, 'pct'], ['存货增速差', 'inventory_growth_gap', d.inventory_growth_gap, 'pct'], ['资本开支强度', 'capex_intensity', d.capex_intensity, '%'],
      ['最新资产负债率', 'debt_ratio', series.debt_ratio?.at?.(-1), '%'], ['商誉／权益比', 'goodwill_equity_ratio', d.goodwill_equity_ratio, '%'],
    ];
    target.innerHTML = rows.map(([label, key, value, suffix]) => `<div class="health-derived-item"><span class="health-derived-label">${healthMetricLabel(key, label)}</span><strong class="health-derived-value">${healthMetricValue(key, value, suffix)}</strong></div>`).join('');
    renderHealthSeries(health);
  }

  function renderHealthComparisonTable(health, monitor) {
    const target = document.getElementById('health-comparison-body');
    if (!target) return;
    state.healthComparison = { health, monitor };
    const unavailable = '<span class="comparison-unavailable">—</span>';
    const points = (item) => { const value = item?.points ?? item?.score; return item?.available === false || value === null || value === undefined || !Number.isFinite(Number(value))
      ? unavailable : Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1); };
    const annualDimension = (code) => (health?.dimensions || []).find((item) => item.code === code);
    const quarterlyDimension = (code) => (monitor?.realtime_score?.breakdown || []).find((item) => item.code === code);
    const annualScore = health?.score !== null && health?.score !== undefined && Number.isFinite(Number(health.score)) ? Number(health.score).toFixed(health.score % 1 ? 1 : 0) : unavailable;
    const quarterlyScore = monitor?.realtime_score?.score !== null && monitor?.realtime_score?.score !== undefined && Number.isFinite(Number(monitor.realtime_score.score)) ? String(monitor.realtime_score.score) : unavailable;
    const annualFlags = health ? `<button type="button" class="comparison-flag-button" data-flag-source="annual">${health.red_flag_count ?? 0}</button>` : unavailable;
    const annualInvestigations = health ? String((health.investigation_results || []).filter((item) => item.status === 'triggered').length) : unavailable;
    const quarterlyAlerts = monitor?.status === 'available' ? `<button type="button" class="comparison-flag-button" data-flag-source="quarterly">${(monitor.alerts || []).length}</button>` : unavailable;
    const quarterlyInvestigations = monitor?.status === 'available' ? '—（未设）' : unavailable;
    const annualPeriod = '五年年报';
    const quarterPeriod = monitor?.latest_period ? `${monitor.latest_period}（TTM）` : '季度监测';
    const overallButton = (source, score) => score === unavailable ? unavailable : `<button type="button" class="comparison-score-button" data-overall-source="${source}" aria-label="查看总体财报分析结论">${score}</button>`;
    const cells = (klass, label, source, score, coverage, dims, flags, investigations) => `<tr><td class="${klass}"><strong>${escapeHTML(label)}</strong></td><td>${overallButton(source, score)}</td><td>${coverage}</td>${dims.map(points => `<td>${points}</td>`).join('')}<td>${flags}</td><td>${investigations}</td></tr>`;
    target.innerHTML = [
      cells('comparison-annual', annualPeriod, 'annual', annualScore, health ? String(health.coverage_weight ?? 0) : unavailable, [annualDimension('growth_quality'), annualDimension('profitability'), annualDimension('cash_quality'), annualDimension('working_capital'), annualDimension('reinvestment'), annualDimension('financial_risk')].map((item) => scoreDetailButton('annual', item)), annualFlags, annualInvestigations),
      cells('comparison-quarter', `最新季报：${quarterPeriod}`, 'quarterly', quarterlyScore, monitor?.realtime_score ? String(monitor.realtime_score.coverage_weight ?? 0) : unavailable, [quarterlyDimension('growth'), quarterlyDimension('profitability'), quarterlyDimension('cash'), quarterlyDimension('working_capital'), quarterlyDimension('reinvestment'), quarterlyDimension('financial_risk')].map((item) => scoreDetailButton('quarterly', item)), quarterlyAlerts, quarterlyInvestigations),
    ].join('');
  }

  function renderQuarterlyMonitor(monitor) {
    const period = document.getElementById('quarterly-monitor-period');
    const scoreEl = document.getElementById('quarterly-realtime-score');
    const coverageEl = document.getElementById('quarterly-realtime-coverage');
    const target = document.getElementById('quarterly-monitor-summary');
    const realtime = monitor?.realtime_score;
    scoreEl.innerHTML = Number.isFinite(realtime?.score) ? `${realtime.score} <small>/ 100</small>` : '— <small>/ 100</small>';
    coverageEl.textContent = `覆盖度：${realtime?.coverage_weight ?? 0} / 100${realtime?.status === 'partial' ? '（部分覆盖）' : realtime?.status === 'insufficient' ? '（不足，未评分）' : ''}`;
    if (!monitor || monitor.status !== 'available') {
      period.textContent = monitor?.status === 'not_applicable' ? '不适用通用季度监测' : '暂无可用季度监测';
      target.textContent = monitor?.reason === 'ttm_comparison_base_unavailable' ? '缺少上年同季或上年年报，暂不能计算 TTM。' : '等待可比季度财报数据。';
      return;
    }
    period.textContent = `截至 ${monitor.latest_period}（TTM 口径）`;
    const state = { improving: '改善', stable: '平稳', watch: '需关注' };
    const dims = (monitor.dimensions || []).map((item) => `<div class="quarterly-monitor-item ${escapeHTML(item.status)}"><strong>${escapeHTML(item.title)}</strong><span>${state[item.status] || '—'}</span><small>${escapeHTML(item.detail || '')}</small></div>`).join('');
    const alerts = monitor.alerts?.length ? `<div class="quarterly-monitor-alerts"><strong>本季预警</strong>${monitor.alerts.map((item) => `<p class="${escapeHTML(item.severity)}">${escapeHTML(item.title)}：${escapeHTML(item.detail)}</p>`).join('')}</div>` : '<div class="quarterly-monitor-alerts"><strong>本季预警</strong><p>未触发季度早期预警。</p></div>';
    target.innerHTML = `${dims}${alerts}`;
  }

  function renderFinancialHealth(health, latestReport = null, uiState = 'ready') {
    const period = document.getElementById('health-period');
    const dataAsOf = document.getElementById('health-data-asof');
    const score = document.getElementById('health-score');
    const flags = document.getElementById('health-red-flags');
    const coverage = document.getElementById('health-coverage');
    const dimensions = document.getElementById('health-dimensions');
    const derived = document.getElementById('health-derived');
    const conclusionPanel = document.getElementById('health-conclusions');
    const evidenceAsOf = health?.periods?.at?.(-1) || '—';
    const notApplicableLabel = { not_applicable: '不适用', unavailable: '数据不足', insufficient: '数据不足' };
    const renderUnavailableDimensions = (items) => {
      dimensions.innerHTML = (items || []).map((item) => `<article class="health-dimension ${escapeHTML(item.status || 'unavailable')}"><div class="health-dimension-top"><span>${escapeHTML(item.title)}</span><span class="health-dimension-score">${escapeHTML(notApplicableLabel[item.status] || '数据不足')}</span></div><div class="health-dimension-trend">${escapeHTML(item.reason || '通用规则未评估')}</div></article>`).join('') || '<p class="health-evidence-empty">未返回维度状态。</p>';
    };
    const renderUnavailableConclusions = (items) => {
      conclusionPanel.innerHTML = (items || []).map((item) => `<article class="health-conclusion ${escapeHTML(item.status || 'insufficient')}"><strong>${escapeHTML(item.question)}</strong><span>${escapeHTML(notApplicableLabel[item.status] || '数据不足')}</span><p>${escapeHTML(item.detail || item.reason || '暂无可用结论。')}</p>${healthEvidenceSummary(item.evidence) ? `<small class="health-rule-evidence">${escapeHTML(healthEvidenceSummary(item.evidence))}</small>` : ''}</article>`).join('') || '<p class="health-evidence-empty">未返回结论状态。</p>';
    };
    const rawAsOf = latestReport?.report_date ? `；原始财报最新 ${latestReport.period || latestReport.year || '—'}（${latestReport.report_date}）` : '';
    dataAsOf.textContent = `资料日期：健康度证据截至 ${evidenceAsOf}${rawAsOf}`;
    if (!health) {
      const failed = uiState === 'failed';
      const message = failed ? '健康度数据加载失败' : '正在加载财报与健康度评估结果';
      period.textContent = message;
      score.innerHTML = `${failed ? '加载失败' : '加载中'} <small>/ 100</small>`;
      flags.textContent = '—'; coverage.textContent = '—'; derived.textContent = message; renderHealthSeries(null); renderHealthEvidencePanels(null, uiState); conclusionPanel.textContent = message; return;
    }
    if (health.status === 'not_applicable') {
      const industry = [health?.industry?.level_1, health?.industry?.level_2].filter(Boolean).join(' · ');
      period.textContent = industry ? `行业：${industry}` : '行业适用性检查';
      score.innerHTML = '不适用 <small>通用规则</small>';
      flags.textContent = '—'; coverage.textContent = '—'; renderUnavailableDimensions(health.dimensions); derived.textContent = '该行业须使用专用财务指标和阈值。';
      renderHealthSeries(null); renderHealthEvidencePanels(health); renderUnavailableConclusions(health.conclusions); return;
    }
    if (!Array.isArray(health.periods) || health.periods.length < 5) {
      const reason = health.reason === 'annual_reports_not_contiguous' ? '最近五个年报不连续，不能按五年口径计算。' : '需要最近五个连续完整年度的财报数据。';
      period.textContent = reason;
      score.innerHTML = '数据不足 <small>/ 100</small>';
      flags.textContent = '—'; coverage.textContent = '—'; renderUnavailableDimensions(health.dimensions); derived.textContent = '暂无可用 KPI 数据'; renderHealthSeries(null); renderHealthEvidencePanels(health); renderUnavailableConclusions(health.conclusions); return;
    }
    period.textContent = `计算区间：${health.periods.join(' / ')}`;
    const scoreLabel = document.querySelector('.health-score-label');
    const partialCoverage = health.score_coverage_status === 'partial';
    const scoreUnavailable = health.score === null || health.score === undefined;
    scoreLabel.textContent = partialCoverage ? '部分覆盖评分' : scoreUnavailable ? '综合评分未生成' : '综合健康度';
    score.innerHTML = scoreUnavailable
      ? '— <small>/ 100</small>'
      : `${healthValue(health.score)} <small>/ 100${partialCoverage ? '（部分覆盖）' : ''}</small>`;
    flags.textContent = `${health.red_flag_count || 0} 项`;
    coverage.textContent = `${health.coverage_weight || 0} / 100`;
    if (scoreUnavailable) {
      period.textContent = `${period.textContent}；综合评分未生成：评分覆盖权重不足 85 / 100。`;
    }
    const scoreBreakdown = health.score_breakdown || [];
    const trendLabel = { up: '↑ 改善', down: '↓ 走弱', flat: '→ 平稳', unknown: '—' };
    dimensions.innerHTML = (health.dimensions || []).map((item) => {
      const scoreItem = scoreBreakdown.find((entry) => entry.code === item.code);
      const formation = scoreFormationCopy(item, scoreItem);
      return `<article class="health-dimension ${escapeHTML(item.status)}"><div class="health-dimension-top"><span>${escapeHTML(item.title)}</span><span class="health-dimension-score">${item.available ? `${healthValue(item.score)} / ${item.weight}` : '数据不足'}</span></div><div class="health-dimension-trend">${trendLabel[item.trend] || '—'}</div>${formation ? `<small class="health-rule-evidence">${formation.split('\n').map(escapeHTML).join('<br>')}</small>` : ''}</article>`;
    }).join('');
    const d = health.derived || {};
    const latest = (health.series || {});
    const debtTrend = Number.isFinite(latest.debt_ratio?.[0]) && Number.isFinite(latest.debt_ratio?.at?.(-1)) ? latest.debt_ratio.at(-1) - latest.debt_ratio[0] : null;
    const goodwillFirst = latest.goodwill?.[0];
    const goodwillLast = latest.goodwill?.at?.(-1);
    const goodwillGrowth = Number.isFinite(goodwillFirst) && Number.isFinite(goodwillLast) && goodwillFirst !== 0 ? (goodwillLast / goodwillFirst - 1) * 100 : null;
    const fields = [
      ['营收 CAGR', d.revenue_cagr, '%', 'revenue_cagr'], ['扣非利润 CAGR', d.ex_net_profit_cagr, '%', 'ex_net_profit_cagr'], ['利润增长溢价', d.profit_growth_premium, 'pct', 'profit_growth_premium'], ['毛利率五年变化', d.gross_margin_change, 'pct', 'gross_margin', 'gross_margin_change'], ['净利率五年变化', d.net_margin_change, 'pct', 'net_margin', 'net_margin_change'],
      ['扣非 ROE 五年均值', d.roe_ex_average, '%', 'roe_ex'], ['最新扣非 ROE', latest.roe_ex?.at?.(-1), '%', 'roe_ex'], ['最新资产负债率', latest.debt_ratio?.at?.(-1), '%', 'debt_ratio'], ['资产负债率趋势', debtTrend, 'pct', 'debt_ratio', 'debt_ratio_trend'], ['商誉五年变化', goodwillGrowth, '%', 'goodwill', 'goodwill_growth'], ['最新现金利润比', d.annual_cash_profit_ratio, '', 'annual_cash_profit_ratio'], ['五年现金利润比', d.five_year_cash_profit_ratio, '', 'five_year_cash_profit_ratio'],
      ['FCF Margin', d.fcf_margin, '%', 'fcf_margin'], ['应收增速差', d.receivable_growth_gap, 'pct', 'receivable_growth_gap'], ['存货增速差', d.inventory_growth_gap, 'pct', 'inventory_growth_gap'], ['CapEx 强度', d.capex_intensity, '%', 'capex_intensity'], ['商誉 / 权益', d.goodwill_equity_ratio, '%', 'goodwill_equity_ratio'], ['商誉 / 资产', d.goodwill_assets_ratio, '%', 'goodwill_assets_ratio'],
    ];
    derived.innerHTML = fields.map(([label, value, suffix, tooltipKey, toneKey]) => `<div class="health-derived-item"><span class="health-derived-label">${healthMetricLabel(tooltipKey, label)}</span><strong class="health-derived-value">${healthMetricValue(toneKey || tooltipKey, value, suffix)}</strong></div>`).join('');
    renderHealthSeries(health);
    renderHealthEvidencePanels(health);
    const conclusionLabel = { improving: '改善', stable: '平稳', watch: '需关注', insufficient: '数据不足' };
    conclusionPanel.innerHTML = (health.conclusions || []).map((item) => {
      const concise = conclusionSummary(item);
      return `<article class="health-conclusion ${escapeHTML(item.status)}"><strong>${escapeHTML(item.question)}</strong><span>${conclusionLabel[item.status] || '—'}</span><p>${escapeHTML(concise.summary)}</p><small class="health-rule-evidence">${escapeHTML(concise.focus)}</small></article>`;
    }).join('') || '暂无可用结论。';
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

  function putFinancialCache(cacheKey, payload) {
    state.financialCache.delete(cacheKey);
    state.financialCache.set(cacheKey, { at: Date.now(), payload });
    while (state.financialCache.size > MAX_FINANCIAL_CACHE_ENTRIES) {
      state.financialCache.delete(state.financialCache.keys().next().value);
    }
  }

  async function loadAnnualFinancials(stock) {
    const financialRequestId = ++state.financialRequestId;
    state.financialAbortController?.abort();
    const cacheKey = `${stock.market}:${stock.symbol}:6`;
    const cached = state.financialCache.get(cacheKey);
    const controller = new AbortController();
    state.financialAbortController = controller;
    const chartIds = [...METRIC_CHARTS.map(([id]) => id), 'revenue-growth-chart'];
    renderHealthComparisonTable(null, null);
    renderHealthMetrics(null);
    for (const id of chartIds) {
      const el = document.getElementById(id);
      el.className = 'analysis-metric-status';
      el.textContent = '加载最近五年财报数据…';
    }
    try {
      // Request one extra year so the earliest displayed point can be compared
      // with the matching report period a year earlier.
      const cacheIsFresh = cached && Date.now() - cached.at < FINANCIAL_CACHE_TTL_MS;
      if (cacheIsFresh) {
        state.financialCache.delete(cacheKey);
        state.financialCache.set(cacheKey, cached);
      }
      const payload = cacheIsFresh
        ? cached.payload
        : await fetch(`/api/stock-score-report-history?market=${encodeURIComponent(stock.market)}&symbol=${encodeURIComponent(stock.symbol)}&years=6`, { signal: controller.signal }).then(async (response) => {
          const body = await response.json();
          if (!response.ok || !body.ok) throw new Error(body?.error?.message || `HTTP ${response.status}`);
          putFinancialCache(cacheKey, body);
          return body;
        });
      if (financialRequestId !== state.financialRequestId) return;
      renderHealthComparisonTable(payload.health, payload.quarterly_monitor);
      renderHealthMetrics(payload.health);
      const annualPeriods = new Set(payload.health?.periods || []);
      const evidenceReports = payload.reports.filter((row) => String(row?.period || '').endsWith('A'));
      const healthEvidenceReports = annualPeriods.size ? evidenceReports.filter((row) => annualPeriods.has(String(row.period))) : evidenceReports;
      const chartReports = appendLatestQuarter(healthEvidenceReports, payload.reports);
      for (const [id, metric, variant, display] of METRIC_CHARTS) renderAnnualBars(id, chartReports, metric, variant, display);
      renderYoYGrowthBars('revenue-growth-chart', chartReports, 'revenue', annualPeriods, payload.reports);
    } catch (error) {
      if (financialRequestId !== state.financialRequestId) return;
      if (error.name === 'AbortError') return;
      renderHealthComparisonTable(null, null);
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
  document.getElementById('health-comparison-body')?.addEventListener('click', (event) => {
    const button = event.target.closest('.comparison-score-button');
    const overall = event.target.closest('[data-overall-source]');
    const flag = event.target.closest('.comparison-flag-button');
    if (overall) showHealthOverallDetail(overall.dataset.overallSource);
    else if (button) showHealthScoreDetail(button.dataset.scoreSource, button.dataset.scoreCode);
    if (flag) showHealthFlagDetail(flag.dataset.flagSource);
  });
  const scoreDetailDialog = document.getElementById('health-score-detail-dialog');
  scoreDetailDialog?.querySelector('.health-score-detail-close')?.addEventListener('click', () => scoreDetailDialog.close());
  scoreDetailDialog?.addEventListener('click', (event) => { if (event.target === scoreDetailDialog) scoreDetailDialog.close(); });
  const flagDetailDialog = document.getElementById('health-flag-detail-dialog');
  flagDetailDialog?.querySelector('.health-flag-detail-close')?.addEventListener('click', () => flagDetailDialog.close());
  flagDetailDialog?.addEventListener('click', (event) => { if (event.target === flagDetailDialog) flagDetailDialog.close(); });
  const overallDetailDialog = document.getElementById('health-overall-detail-dialog');
  overallDetailDialog?.querySelector('.health-overall-detail-close')?.addEventListener('click', () => overallDetailDialog.close());
  overallDetailDialog?.addEventListener('click', (event) => { if (event.target === overallDetailDialog) overallDetailDialog.close(); });

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
