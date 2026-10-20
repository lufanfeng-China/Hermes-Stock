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
  const state = { timer: null, requestId: 0, financialRequestId: 0, financialAbortController: null, financialCache: new Map(), financialPayload: null, healthComparison: null, industryValuation: null, industryValuationPeers: [], industryPeerSort: { key: 'valuation_percentile', direction: 1 }, industryHealthPeers: null, industryHealthPeerView: 'annual', industryHealthPeerSort: { key: 'score', direction: -1 }, industryMetricPeers: null, industryMetricCode: null, industryMetricPeerTrigger: null, industryMetricPeerSort: { key: 'current_value', direction: -1 }, stockProfile: null, selected: null, suggestions: [], recent: [] };

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
    return latestQuarter
      ? [...(annualReports || []), { ...latestQuarter, label: interimPeriodLabel(latestQuarter.period, '非TTM') }]
      : (annualReports || []);
  }

  function interimPeriodLabel(period, basis) {
    return `${String(period).slice(2)}(${basis})`;
  }

  function buildLatestTTMReport(reports, quarterlyMonitor) {
    if (quarterlyMonitor?.status !== 'available' || !quarterlyMonitor?.latest_period) return null;
    const period = String(quarterlyMonitor.latest_period);
    const year = Number(period.slice(0, 4));
    const suffix = period.slice(4);
    const byPeriod = new Map((reports || []).map((row) => [String(row?.period || ''), row]));
    const latest = byPeriod.get(period);
    const annual = byPeriod.get(`${year - 1}A`);
    const samePeriodPriorYear = byPeriod.get(`${year - 1}${suffix}`);
    const olderAnnual = byPeriod.get(`${year - 2}A`);
    const olderSamePeriod = byPeriod.get(`${year - 2}${suffix}`);
    if (!latest || !annual || !samePeriodPriorYear) return null;
    const numberOrNull = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
    const ttm = (metric) => {
      const current = numberOrNull(latest.metrics?.[metric]);
      const priorAnnual = numberOrNull(annual.metrics?.[metric]);
      const priorSame = numberOrNull(samePeriodPriorYear.metrics?.[metric]);
      return current === null || priorAnnual === null || priorSame === null ? null : current + priorAnnual - priorSame;
    };
    const monitorTTM = quarterlyMonitor.ttm || {};
    const revenue = numberOrNull(monitorTTM.revenue) ?? ttm('revenue');
    const exNetProfit = numberOrNull(monitorTTM.ex_net_profit) ?? ttm('ex_net_profit');
    const ocf = numberOrNull(monitorTTM.ocf) ?? ttm('ocf');
    const capex = numberOrNull(monitorTTM.capex) ?? ttm('capex');
    const freeCf = numberOrNull(monitorTTM.free_cf) ?? ttm('free_cf');
    const netProfit = ttm('net_profit');
    const grossProfit = (row) => {
      const revenueValue = numberOrNull(row?.metrics?.revenue);
      const margin = numberOrNull(row?.metrics?.gross_margin);
      return revenueValue === null || margin === null ? null : revenueValue * margin / 100;
    };
    const ttmGrossProfit = [grossProfit(latest), grossProfit(annual), grossProfit(samePeriodPriorYear)].every(Number.isFinite)
      ? grossProfit(latest) + grossProfit(annual) - grossProfit(samePeriodPriorYear) : null;
    const priorTtmInputs = olderAnnual && olderSamePeriod
      ? [numberOrNull(samePeriodPriorYear.metrics?.revenue), numberOrNull(olderAnnual.metrics?.revenue), numberOrNull(olderSamePeriod.metrics?.revenue)]
      : [];
    const priorTtmRevenue = priorTtmInputs.length === 3 && priorTtmInputs.every(Number.isFinite)
      ? priorTtmInputs[0] + priorTtmInputs[1] - priorTtmInputs[2] : null;
    const revenueTtmYoY = Number.isFinite(revenue) && Number.isFinite(priorTtmRevenue) && priorTtmRevenue !== 0
      ? (revenue / priorTtmRevenue - 1) * 100 : null;
    return {
      ...latest,
      label: interimPeriodLabel(period, 'TTM'), basis: 'ttm',
      metrics: {
        ...latest.metrics,
        revenue, ex_net_profit: exNetProfit, net_profit: netProfit, ocf, capex, free_cf: freeCf,
        gross_margin: Number.isFinite(ttmGrossProfit) && Number.isFinite(revenue) && revenue !== 0 ? ttmGrossProfit / revenue * 100 : null,
        net_margin: Number.isFinite(netProfit) && Number.isFinite(revenue) && revenue !== 0 ? netProfit / revenue * 100 : null,
        // The backend financial snapshot already derives this field as TTM deducted profit / ending equity.
        roe_ex: numberOrNull(latest.metrics?.roe_ex),
        revenue_yoy: revenueTtmYoY,
      },
    };
  }

  function periodLabel(row) {
    if (row?.label) return String(row.label);
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
      const explicitYoY = Number(row?.metrics?.[`${metricKey}_yoy`]);
      if (Number.isFinite(explicitYoY)) return explicitYoY;
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
    if (!tooltip) return escapeHtml(label);
    const content = `定义：${tooltip.definition}\n判断：${tooltip.judgement}`;
    return `<span class="health-metric-tooltip" tabindex="0" data-health-tooltip="${escapeHtml(content)}" title="${escapeHTML(content)}" aria-label="${escapeHtml(`${label}。${content}`)}"><span class="health-metric-tooltip-trigger">${escapeHtml(label)}</span></span>`;
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
      ? `<ul>${items.map((item) => `<li><strong>${escapeHtml(item.title || item.code || '未命名规则')}</strong>${item.detail || item.reason ? `：${escapeHtml(item.detail || item.reason)}` : ''}${healthEvidenceSummary(item.evidence) ? `<small class="health-rule-evidence">${escapeHtml(healthEvidenceSummary(item.evidence))}</small>` : ''}</li>`).join('')}</ul>`
      : `<p class="health-evidence-empty">${escapeHtml(emptyMessage)}</p>`;
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

  function latestQuarterSeriesPoint(quarterlyMonitor, latestReport) {
    if (quarterlyMonitor?.status !== 'available' || !quarterlyMonitor?.latest_period) return null;
    const ttm = quarterlyMonitor.ttm || {};
    const gaps = quarterlyMonitor.gaps || {};
    const latestMetrics = latestReport?.metrics || {};
    const numberOrNull = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
    const ratio = (numerator, denominator) => Number.isFinite(numerator) && Number.isFinite(denominator) && denominator !== 0
      ? numerator / denominator : null;
    const percentage = (numerator, denominator) => {
      const value = ratio(numerator, denominator);
      return value === null ? null : value * 100;
    };
    const period = String(quarterlyMonitor.latest_period);
    return {
      year: period.slice(0, 4), period, label: period,
      values: {
        annual_cash_profit_ratio: ratio(numberOrNull(ttm.ocf), numberOrNull(ttm.ex_net_profit)),
        fcf_margin: numberOrNull(ttm.fcf_margin),
        receivable_growth_gap: numberOrNull(gaps.receivable_growth_gap),
        inventory_growth_gap: numberOrNull(gaps.inventory_growth_gap),
        capex_intensity: percentage(numberOrNull(ttm.capex), numberOrNull(ttm.revenue)),
        roe_ex: numberOrNull(latestMetrics.roe_ex),
      },
    };
  }

  const HEALTH_TTM_SERIES_KEYS = new Set(['annual_cash_profit_ratio', 'fcf_margin', 'capex_intensity', 'roe_ex']);

  function renderHealthSeries(health, quarterlyMonitor = null, latestReport = null) {
    const target = document.getElementById('health-series');
    const series = health?.series || {};
    const years = series.years || [];
    const HEALTH_SERIES_CHARTS = [
      ['现金利润比', 'annual_cash_profit_ratio', '', 'cash_profit_ratio'], ['FCF Margin', 'fcf_margin', '%', 'fcf_margin'],
      ['应收增速差', 'receivable_growth_gap', 'pct', 'accounts_receivable_growth_gap'], ['存货增速差', 'inventory_growth_gap', 'pct', 'inventory_growth_gap'],
      ['CapEx 强度', 'capex_intensity', '%', 'capex_intensity'], ['扣非 ROE', 'roe_ex', '%', 'roe_ex'],
    ];
    if (!years.length) { target.textContent = '暂无可用五年派生序列。'; return; }

    const seriesRows = years.map((year) => {
      const label = String(year);
      const annualYear = label.replace(/A$/, '');
      return { year: annualYear, period: `${annualYear}A`, label: String(year) };
    });
    const latestQuarter = latestQuarterSeriesPoint(quarterlyMonitor, latestReport);
    const chartRows = latestQuarter ? [...seriesRows, latestQuarter] : seriesRows;
    target.innerHTML = `<div class="health-series-chart-grid">${HEALTH_SERIES_CHARTS.map(([label, key, suffix, peerMetric]) => {
      const chartId = `health-series-chart-${key}`;
      const clickable = peerMetric ? ` data-industry-metric="${peerMetric}" role="button" tabindex="0" title="查看二级行业全部股票${label}"` : '';
      return `<article class="health-series-chart-card"${clickable}><div class="health-series-chart-heading"><h4>${healthMetricLabel(key, label)}</h4><span>${suffix === 'pct' ? '单位：百分点' : suffix ? '单位：%' : '倍'}</span></div><div id="${chartId}" class="analysis-metric-status">暂无可用数据</div></article>`;
    }).join('')}</div>`;

    HEALTH_SERIES_CHARTS.forEach(([, key, suffix]) => {
      const chartId = `health-series-chart-${key}`;
      const rows = chartRows.map((row) => row.values
        ? { ...row, label: interimPeriodLabel(row.period, HEALTH_TTM_SERIES_KEYS.has(key) ? 'TTM' : '非TTM') }
        : row);
      const values = rows.map((row, index) => row.values ? row.values[key] : Number(series[key]?.[index]));
      renderBars(chartId, rows, values, (value) => healthSeriesValue(key, value, suffix), 'health');
    });
  }

  // This is the single UI contract for every published industry snapshot metric.
  const PEER_METRIC_CONFIG = {
    revenue: { label: '营业收入', unit: '亿元', currentBasis: 'ttm' },
    revenue_growth: { label: '营收增长率', unit: '%', currentBasis: 'quarter', ttmSupported: false },
    net_profit: { label: '归母净利润', unit: '亿元', currentBasis: 'ttm' },
    ex_net_profit: { label: '扣非归母净利润', unit: '亿元', currentBasis: 'ttm' },
    gross_margin: { label: '毛利率', unit: '%', currentBasis: 'ttm' },
    net_margin: { label: '净利率', unit: '%', currentBasis: 'ttm' },
    roe_ex: { label: '扣非 ROE', unit: '%', currentBasis: 'ttm' },
    debt_ratio: { label: '资产负债率', unit: '%', currentBasis: 'quarter', ttmSupported: false },
    ocf: { label: '经营现金流', unit: '亿元', currentBasis: 'ttm' },
    free_cf: { label: '自由现金流', unit: '亿元', currentBasis: 'ttm' },
    capex: { label: '资本开支', unit: '亿元', currentBasis: 'ttm' },
    goodwill: { label: '商誉', unit: '亿元', currentBasis: 'quarter', ttmSupported: false },
    accounts_receivable: { label: '应收账款', unit: '亿元', currentBasis: 'quarter', ttmSupported: false },
    inventory: { label: '库存', unit: '亿元', currentBasis: 'quarter', ttmSupported: false },
    cash_profit_ratio: { label: '现金利润比', unit: '倍', currentBasis: 'ttm' },
    fcf_margin: { label: 'FCF Margin', unit: '%', currentBasis: 'ttm' },
    capex_intensity: { label: '资本开支强度', unit: '%', currentBasis: 'ttm' },
    accounts_receivable_growth_gap: { label: '应收账款增速差', unit: '%', currentBasis: 'quarter', ttmSupported: false },
    inventory_growth_gap: { label: '存货增速差', unit: '%', currentBasis: 'quarter', ttmSupported: false },
  };

  function peerMetricNumber(value) { return Number.isFinite(Number(value)) ? Number(value) : null; }
  function peerMetricDisplayUnit(unit) { return unit === '元' ? '亿元' : unit; }
  function peerMetricValue(value, unit) {
    const numeric = peerMetricNumber(value);
    if (numeric === null) return '—';
    if (unit === '亿元') return `${(numeric / 1e8).toFixed(2)} 亿元`;
    if (unit === '%') return `${numeric.toFixed(2)}%`;
    return `${numeric.toFixed(2)}${unit || ''}`;
  }
  function peerMetricChange(value, unit) {
    const numeric = peerMetricNumber(value);
    if (numeric === null) return '—';
    if (unit === '百分点') return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(2)} 个百分点`;
    return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(2)}%`;
  }
  function stablePeerMetricSort(rows, key, direction) {
    return rows.map((row, index) => ({ row, index })).sort((left, right) => {
      const a = left.row[key]; const b = right.row[key];
      if (key === 'stock_name') return String(a || '').localeCompare(String(b || ''), 'zh-CN') * direction || left.index - right.index;
      const an = peerMetricNumber(a); const bn = peerMetricNumber(b);
      if (an === null || bn === null) return an === bn ? left.index - right.index : an === null ? 1 : -1;
      return (an - bn) * direction || left.index - right.index;
    }).map(({ row }) => row);
  }
  function metricCell(row, basis) { return row.metrics?.[basis] || null; }
  function industryMetricSortHeader(key, label, sort) {
    return `<th aria-sort="${sort.key === key ? (sort.direction === 1 ? 'ascending' : 'descending') : 'none'}"><button type="button" class="industry-metric-peer-sort" data-industry-metric-sort="${key}">${escapeHtml(label)} <span aria-hidden="true">↕</span></button></th>`;
  }
  function renderIndustryMetricPeers(payload) {
    const table = document.getElementById('industry-metric-peer-table'); const status = document.getElementById('industry-metric-peer-status');
    const config = PEER_METRIC_CONFIG[state.industryMetricCode] || {}; if (!table) return;
    const metric = payload.metric || {}; const displayUnit = peerMetricDisplayUnit(metric.unit || config.unit); const ttmSupported = metric.ttm_supported ?? config.ttmSupported ?? true;
    const currentBasis = ttmSupported ? (metric.current_basis || config.currentBasis || 'ttm') : 'quarter';
    const rows = (payload.rows || []).map((row) => {
      const annual = metricCell(row, 'annual'); const quarter = metricCell(row, 'quarter'); const ttm = metricCell(row, 'ttm'); const current = metricCell(row, currentBasis);
      return { ...row, annual_value: annual?.value, annual_change: annual?.yoy_value, quarter_value: quarter?.value, quarter_change: quarter?.yoy_value, ttm_value: ttm?.value, ttm_change: ttm?.yoy_value, current_value: current?.value };
    });
    const sort = state.industryMetricPeerSort; const sorted = stablePeerMetricSort(rows, sort.key, sort.direction);
    const changeLabel = metric.growth_unit === '百分点' ? '变化（百分点）' : (metric.change_label || '同比');
    const cell = (value, period) => `${peerMetricValue(value, displayUnit)}${period ? `<span class="industry-metric-peer-period"> ${escapeHtml(period)}</span>` : ''}`;
    const change = (value) => peerMetricChange(value, metric.growth_unit || '%');
    table.innerHTML = `<thead><tr>${[
      industryMetricSortHeader('stock_name', '股票名称', sort),
      industryMetricSortHeader('annual_value', '全年', sort),
      industryMetricSortHeader('annual_change', changeLabel, sort),
      industryMetricSortHeader('quarter_value', '当季累计', sort),
      industryMetricSortHeader('quarter_change', changeLabel, sort),
      ...(ttmSupported ? [industryMetricSortHeader('ttm_value', 'TTM', sort), industryMetricSortHeader('ttm_change', `TTM ${changeLabel}`, sort)] : []),
    ].join('')}</tr></thead><tbody>${sorted.map((row) => `<tr class="${row.is_current_stock ? 'industry-metric-peer-current' : ''}"><td><button type="button" class="industry-metric-peer-stock-trigger" data-open-stock="${escapeHtml(row.market)}:${escapeHtml(row.symbol)}" title="打开 ${escapeHtml(row.stock_name || row.symbol)} 股票分析"><span>${escapeHtml(row.stock_name || row.symbol)}</span><small>${escapeHtml(`${row.market || ''}:${row.symbol || ''}`)}</small></button></td><td>${cell(row.annual_value, row.metrics?.annual?.period)}</td><td>${change(row.annual_change)}</td><td>${cell(row.quarter_value, row.metrics?.quarter?.period)}</td><td>${change(row.quarter_change)}</td>${ttmSupported ? `<td>${cell(row.ttm_value, row.metrics?.ttm?.period)}</td><td>${change(row.ttm_change)}</td>` : ''}</tr>`).join('') || `<tr><td colspan="${ttmSupported ? 7 : 5}">暂无行业成员数据。</td></tr>`}</tbody>`;
    if (status) status.textContent = `${payload.coverage ? `覆盖：${payload.coverage.members ?? rows.length} 家成员。` : `共 ${rows.length} 只股票。`} 当前按${currentBasis === 'ttm' ? 'TTM' : '最新期末/当季累计'}降序；缺失值始终排最后。${ttmSupported ? ' 当季为累计披露值；同比仅比较同口径。' : ' TTM 不适用：期末时点值。'} 点击列头排序，点击股票打开分析页。`;
  }
  async function showIndustryMetricPeers(metricCode, trigger = null) {
    const config = PEER_METRIC_CONFIG[metricCode]; const dialog = document.getElementById('industry-metric-peer-dialog'); const title = document.getElementById('industry-metric-peer-title'); const status = document.getElementById('industry-metric-peer-status'); const table = document.getElementById('industry-metric-peer-table');
    if (!config || !dialog || !state.selected) return;
    state.industryMetricPeerTrigger = trigger || document.activeElement;
    state.industryMetricCode = metricCode; state.industryMetricPeers = null; state.industryMetricPeerSort = { key: 'current_value', direction: -1 };
    if (!dialog.open) dialog.showModal(); title.textContent = `二级行业｜${config.label}`; status.textContent = '正在读取已发布的二级行业指标快照…'; table.innerHTML = '<tbody><tr><td>正在加载行业成员…</td></tr></tbody>';
    try {
      const response = await fetch(`/api/industry-metric-peers?market=${encodeURIComponent(state.selected.market)}&symbol=${encodeURIComponent(state.selected.symbol)}&metric=${encodeURIComponent(metricCode)}`);
      const payload = await response.json(); if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || payload?.reason || '数据不可用');
      state.industryMetricPeers = payload; const metric = payload.metric || {}; const formula = metric.formula || '公式由行业快照元数据提供'; const displayUnit = peerMetricDisplayUnit(metric.unit || config.unit || '—');
      title.textContent = `${payload.industry_level_2 || '当前二级行业'}｜${metric.label || config.label}｜${formula}｜单位：${displayUnit}｜快照：${payload.snapshot_as_of || '未提供'}`;
      renderIndustryMetricPeers(payload);
    } catch (error) { status.textContent = `加载失败：${error.message || '未知错误'}`; table.innerHTML = '<tbody><tr><td>行业指标快照加载失败。</td></tr></tbody>'; }
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
    return `<button type="button" class="comparison-score-button" data-score-source="${source}" data-score-code="${escapeHtml(item.code)}" aria-label="查看${escapeHtml(item.title || item.code)}得分由来">${Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1)}</button>`;
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
      const metrics = Object.entries(evidence.metrics || {}).map(([key, value]) => `<dt>${escapeHtml(HEALTH_FIELD_LABELS[key] || key)}</dt><dd>${escapeHtml(healthEvidenceValue(key, value))}</dd>`).join('');
      const subscores = Object.entries(evidence.subscores || {}).map(([key, value]) => `<dt>子项：${escapeHtml(HEALTH_SCORE_COMPONENT_LABELS[key] || key)}</dt><dd>${escapeHtml(String(value))}</dd>`).join('');
      const thresholds = Object.entries(evidence.thresholds || {}).map(([key, value]) => `${HEALTH_SCORE_COMPONENT_LABELS[key] || HEALTH_FIELD_LABELS[key] || key}：${value}`).join('；');
      const formation = scoreFormationCopy(dimension, scoreItem).split('\n').map(escapeHTML).join('<br>');
      content.innerHTML = `<p class="health-score-detail-score">${scoreItem.points} / ${scoreItem.weight}</p><p>${formation}</p><dl>${metrics}${subscores}<dt>评分阈值</dt><dd>${escapeHtml(thresholds || '—')}</dd></dl>`;
    } else {
      const scoreItem = (data.monitor?.realtime_score?.breakdown || []).find((item) => item.code === code);
      const dimension = (data.monitor?.dimensions || []).find((item) => item.code === code);
      if (!scoreItem) return;
      const statusLabel = { improving: '改善', stable: '平稳', watch: '需关注' }[scoreItem.status] || '不可用';
      const ratio = { improving: '100%', stable: '60%', watch: '25%' }[scoreItem.status] || '—';
      title.textContent = `最新季报｜${scoreItem.title}得分由来`;
      content.innerHTML = `<p class="health-score-detail-score">${scoreItem.points} / ${scoreItem.weight}</p><dl><dt>季度状态</dt><dd>${statusLabel}</dd><dt>评分规则</dt><dd>改善计权重的 100%；平稳计 60%；需关注计 25%。本项按 ${ratio} 折算。</dd><dt>本期依据</dt><dd>${escapeHtml(dimension?.detail || '数据不足')}</dd><dt>口径</dt><dd>最新季度流量按 TTM，资产负债表项目使用最新期末余额。</dd></dl>`;
    }
    dialog.showModal();
  }

  function annualConclusionDetail(item, derived) {
    const pct = (value, suffix = '%') => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}${suffix}` : '—';
    const metrics = item?.evidence?.metrics || {};
    switch (item?.code) {
      case 'growth': return `${item.status === 'watch' ? '收入和扣非利润虽长期增长较快，但未实现连续增长' : '收入和扣非利润长期增长较快'}：营收 CAGR ${pct(derived?.revenue_cagr)}，扣非归母净利润 CAGR ${pct(derived?.ex_net_profit_cagr)}；${item.detail || conclusionSummary(item).summary}`;
      case 'profit_premium': return `利润增长质量较好：利润增长比收入快 ${pct(derived?.profit_growth_premium, 'pct')}；${item.detail || conclusionSummary(item).summary}`;
      case 'profitability': return `盈利能力整体改善：毛利率五年变化 ${pct(derived?.gross_margin_change, 'pct')}，净利率五年变化 ${pct(derived?.net_margin_change, 'pct')}，扣非 ROE 趋势 ${metrics.roe_ex_trend === 'up' ? '向上' : '未向上'}。`;
      case 'cash_conversion': return `现金流与利润存在背离：五年现金利润比 ${pct(derived?.five_year_cash_profit_ratio, '')}，最新自由现金流率 ${pct(derived?.fcf_margin)}；${item.detail || conclusionSummary(item).summary}`;
      case 'working_capital': return `营运资本占用需关注：应收增速较营收高 ${pct(derived?.receivable_growth_gap, 'pct')}，存货增速较营收高 ${pct(derived?.inventory_growth_gap, 'pct')}。`;
      case 'capital_leverage': return `资本投入与杠杆：资本开支强度 ${pct(derived?.capex_intensity)}；${item.detail || conclusionSummary(item).summary}`;
      default: return item?.detail || conclusionSummary(item).summary;
    }
  }

  function quarterlyDimensionDetail(item, monitor) {
    const detail = item?.detail || '本期指标缺少进一步说明。';
    if (item?.code === 'growth') return `收入、扣非利润同比明显下滑：${detail}。应结合订单、验收与产品结构进一步核查。`;
    if (item?.code === 'cash') return `现金流有所改善：${detail}。`;
    if (item?.code === 'financial_risk') return `杠杆压力有所缓解：${detail}。`;
    if (item?.code === 'working_capital') return `应收账款与库存增长快于营收：${detail}。需核查回款与库存可消化性。`;
    if (item?.code === 'reinvestment') return `资本投入与经营回报需匹配观察：${detail}。`;
    return `${item?.title || '盈利能力'}：${detail}。`;
  }

  function buildAnnualOverallAnalysis(health) {
    const score = Number.isFinite(Number(health?.score)) ? `${Number(health.score).toFixed(health.score % 1 ? 1 : 0)} / 100` : '未生成';
    const annualPeriods = health?.periods || [];
    const periods = annualPeriods.length ? `${annualPeriods[0]}–${annualPeriods.at(-1)}` : '';
    const conclusions = health?.conclusions || [];
    const derived = health?.derived || {};
    const good = conclusions.filter((item) => item.status === 'improving').map((item) => annualConclusionDetail(item, derived));
    const bad = [
      ...conclusions.filter((item) => item.status === 'watch').map((item) => annualConclusionDetail(item, derived)),
      ...(health?.rule_results || []).filter((item) => item.status === 'triggered').map((item) => `${item.title || '年度红旗'}：${item.detail || item.reason || '规则已触发。'}`),
      ...conclusions.filter((item) => item.status === 'insufficient' || item.status === 'unavailable').map((item) => `${item.question || item.title || '部分结论'}：${item.reason || '数据不足，未作判断。'}`),
    ];
    const watchCount = conclusions.filter((item) => item.status === 'watch').length;
    const improvingCount = conclusions.filter((item) => item.status === 'improving').length;
    return { title: '五年年报｜总体财报分析结论', meta: `评估期间：${periods || '—'}；综合得分：${score}；覆盖度：${health?.coverage_weight ?? 0} / 100。`, summary: `五年年报中有 ${improvingCount} 项明确改善、${watchCount} 项需要关注；以下判断只基于最近五个完整年度年报，不包含最新季度数据。`, good, bad };
  }

  function buildQuarterlyOverallAnalysis(monitor) {
    const realtime = monitor?.realtime_score || {};
    const score = Number.isFinite(Number(realtime.score)) ? `${Number(realtime.score).toFixed(realtime.score % 1 ? 1 : 0)} / 100` : '未生成';
    const dimensions = monitor?.dimensions || [];
    const good = dimensions.filter((item) => item.status === 'improving').map((item) => quarterlyDimensionDetail(item, monitor));
    const bad = [
      ...dimensions.filter((item) => item.status === 'watch').map((item) => quarterlyDimensionDetail(item, monitor)),
      ...(monitor?.alerts || []).map((item) => `${item.title || '季度预警'}：${item.detail || item.reason || '预警已触发。'}`),
      ...dimensions.filter((item) => item.available === false).map((item) => `${item.title}：${item.reason || '数据不足，未作判断。'}`),
    ];
    const hasCashAndLeverageImprovement = dimensions.some((item) => item.code === 'cash' && item.status === 'improving') && dimensions.some((item) => item.code === 'financial_risk' && item.status === 'improving');
    const hasGrowthPressure = dimensions.some((item) => item.code === 'growth' && (item.status === 'watch' || /同比\s*[-−]/.test(item.detail || '')));
    const summary = `${hasCashAndLeverageImprovement ? '现金流和杠杆有所改善' : '季度经营指标存在分化'}${hasGrowthPressure ? '，但收入、扣非利润同比明显下滑' : ''}；流量项目按 TTM 口径，资产负债表项目使用最新期末余额；该结论不等同于五年年度评价。`;
    return { title: '最新季报/TTM｜总体财报分析结论', meta: `最新披露：${monitor?.latest_period || '—'}；实时评分：${score}；覆盖度：${realtime.coverage_weight ?? 0} / 100。`, summary, good, bad };
  }

  function overallAnalysisList(items, emptyMessage) {
    return items.length ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>` : `<p class="health-evidence-empty">${escapeHtml(emptyMessage)}</p>`;
  }

  function showHealthOverallDetail(source) {
    const dialog = document.getElementById('health-overall-detail-dialog'); const content = document.getElementById('health-overall-detail-content');
    const data = state.healthComparison; if (!dialog || !content || !data) return;
    const analysis = source === 'annual' ? buildAnnualOverallAnalysis(data.health) : buildQuarterlyOverallAnalysis(data.monitor);
    content.innerHTML = `<h3>${escapeHtml(analysis.title)}</h3><p class="health-score-detail-score">${escapeHtml(analysis.meta)}</p><section><h4>总体概要</h4><p>${escapeHtml(analysis.summary)}</p></section><section><h4>好的部分</h4>${overallAnalysisList(analysis.good, '当前口径没有明确的改善项。')}</section><section><h4>需要关注的部分</h4>${overallAnalysisList(analysis.bad, '当前已评估规则未显示需关注项。')}</section>`;
    dialog.showModal();
  }

  function showHealthFlagDetail(source) {
    const dialog = document.getElementById('health-flag-detail-dialog'); const content = document.getElementById('health-flag-detail-content');
    const data = state.healthComparison; if (!dialog || !content || !data) return;
    const items = source === 'annual' ? (data.health?.rule_results || []).filter((item) => item.status === 'triggered') : (data.monitor?.alerts || []);
    content.innerHTML = items.length ? `<ul>${items.map((item) => `<li><strong>${escapeHtml(item.title || item.code)}</strong>：${escapeHtml(item.detail || item.reason || item.evidence?.threshold || '已触发规则')}</li>`).join('')}</ul>` : '<p>未触发红旗或季度预警。</p>';
    dialog.showModal();
  }

  function renderHealthMetrics(health, quarterlyMonitor = null, latestReport = null) {
    const target = document.getElementById('health-derived');
    const period = document.getElementById('health-derived-period');
    if (!target) return;
    if (!health) { if (period) period.textContent = '选择股票后加载。'; target.textContent = '选择股票后加载。'; renderHealthSeries(null); return; }
    if (period) period.textContent = `${annualAssessmentBasis(health)}；最新季报中现金/FCF/CapEx/扣非 ROE 为 TTM，增速差为非 TTM 期末同比差。`;
    const d = health.derived || {}; const series = health.series || {};
    const windowLabel = health.assessment_track === 'five_year' ? '五年' : `${health.sample_years || health.periods?.length || '—'}年`;
    const rows = [
      [`营业收入${windowLabel}复合增长率`, 'revenue_cagr', d.revenue_cagr, '%'], [`扣非归母净利润${windowLabel}复合增长率`, 'ex_net_profit_cagr', d.ex_net_profit_cagr, '%'], ['利润增长溢价', 'profit_premium', d.profit_growth_premium, 'pct'],
      [`毛利率${windowLabel}变化`, 'gross_margin_change', d.gross_margin_change, 'pct'], [`净利率${windowLabel}变化`, 'net_margin_change', d.net_margin_change, 'pct'], [`扣非 ROE ${windowLabel}均值`, 'roe_ex', d.roe_ex_average, '%'],
      ['最新现金利润比', 'annual_cash_profit_ratio', d.annual_cash_profit_ratio, ''], [`${windowLabel}现金利润比`, 'five_year_cash_profit_ratio', d.five_year_cash_profit_ratio, ''], ['自由现金流率', 'fcf_margin', d.fcf_margin, '%'],
      ['应收账款增速差', 'receivable_growth_gap', d.receivable_growth_gap, 'pct'], ['存货增速差', 'inventory_growth_gap', d.inventory_growth_gap, 'pct'], ['资本开支强度', 'capex_intensity', d.capex_intensity, '%'],
      ['最新资产负债率', 'debt_ratio', series.debt_ratio?.at?.(-1), '%'], ['商誉／权益比', 'goodwill_equity_ratio', d.goodwill_equity_ratio, '%'],
    ];
    target.innerHTML = rows.map(([label, key, value, suffix]) => `<div class="health-derived-item"><span class="health-derived-label">${healthMetricLabel(key, label)}</span><strong class="health-derived-value">${healthMetricValue(key, value, suffix)}</strong></div>`).join('');
    renderHealthSeries(health, quarterlyMonitor, latestReport);
  }

  const HEALTH_QUESTION_PROMPTS = {
    growth: '公司过去 5 年有没有持续增长？',
    profit_premium: '利润增长是否快于收入增长？',
    profitability: '毛利率、净利率和 ROE 是否在改善？',
    cash_conversion: '利润是否真正转化成了现金？',
    working_capital: '应收和库存是否出现异常增长？',
    capital_leverage: '公司增长是否依赖越来越高的资本投入和财务杠杆？',
  };

  function healthQuestionPrompt(code, health) {
    if (code === 'growth' && health?.assessment_track === 'establishment') {
      return `公司成立期 ${health.sample_years || health.periods?.length || '—'} 年完整年报是否持续增长？`;
    }
    return HEALTH_QUESTION_PROMPTS[code];
  }

  function healthQuestionStatus(status) {
    const states = {
      improving: { klass: 'improving', label: '改善' },
      stable: { klass: 'stable', label: '平稳' },
      watch: { klass: 'watch', label: '需关注' },
      insufficient: { klass: 'unavailable', label: '数据不足' },
      unavailable: { klass: 'unavailable', label: '数据不足' },
    };
    return states[status] || states.unavailable;
  }

  function renderHealthQuestions(health) {
    const target = document.getElementById('health-question-grid');
    const period = document.getElementById('health-question-period');
    if (!target) return;
    if (!health) { if (period) period.textContent = '选择股票后加载。'; target.textContent = '选择股票后加载。'; return; }
    if (period) period.textContent = annualAssessmentBasis(health);
    const scoreCode = { growth: 'growth_quality', profit_premium: 'growth_quality', profitability: 'profitability', cash_conversion: 'cash_quality', working_capital: 'working_capital', capital_leverage: 'reinvestment' };
    target.innerHTML = (health.conclusions || []).map((item) => {
      const code = scoreCode[item.code];
      const score = (health.score_breakdown || []).find((row) => row.code === code);
      const copy = conclusionSummary(item);
      const status = healthQuestionStatus(item.status);
      return `<article class="health-question-card ${escapeHtml(status.klass)}"><h4>${escapeHtml(healthQuestionPrompt(item.code, health) || item.title)}</h4><button type="button" data-score-source="annual" data-score-code="${escapeHtml(code)}"><span class="health-question-score">${score?.points ?? '—'} / ${score?.weight ?? '—'}</span><span class="health-question-status ${escapeHtml(status.klass)}">${escapeHtml(status.label)}</span><p>${escapeHtml(copy.summary)}</p></button></article>`;
    }).join('') || '暂无可用问题结论。';
  }

  const LATEST_REPORT_CHANGE_CONFIG = {
    growth: { chartId: 'revenue-growth-chart', basis: '非TTM' },
    profitability: { chartId: 'gross-margin-chart', basis: '非TTM' },
    cash: { chartId: 'free-cf-chart', basis: 'TTM' },
    working_capital: { chartId: 'accounts-receivable-chart', basis: '非TTM' },
    reinvestment: { chartId: 'capex-chart', basis: 'TTM' },
    financial_risk: { chartId: 'debt-ratio-chart', basis: '非TTM' },
  };

  function renderLatestReportChanges(monitor) {
    const target = document.getElementById('latest-report-change-summary');
    const period = document.getElementById('latest-report-change-period');
    if (!target || !period) return;
    if (monitor?.status !== 'available' || !monitor?.latest_period) {
      period.textContent = monitor?.status === 'not_applicable' ? '不适用通用季度监测' : '暂无可用季度数据';
      target.textContent = '暂无可用最新财报变化摘要。';
      return;
    }
    const stateLabel = { watch: '需关注', improving: '改善', stable: '平稳' };
    const priority = { watch: 0, improving: 1, stable: 2 };
    const latestPeriod = String(monitor.latest_period);
    period.textContent = `截至 ${latestPeriod.slice(2)}`;
    const insights = (monitor.dimensions || [])
      .filter((item) => item?.available !== false && LATEST_REPORT_CHANGE_CONFIG[item.code])
      .sort((left, right) => (priority[left.status] ?? 3) - (priority[right.status] ?? 3))
      .slice(0, 3);
    const alert = (monitor.alerts || [])[0];
    const alertMarkup = alert
      ? `<div class="latest-report-change-alert"><strong>本期预警｜${escapeHtml(alert.title || alert.code || '需关注')}</strong>：${escapeHtml(alert.detail || alert.reason || '季度规则已触发。')}</div>`
      : '';
    if (!insights.length) {
      target.innerHTML = `${alertMarkup}<p class="health-evidence-empty">暂无可用最新财报变化摘要。</p>`;
      return;
    }
    target.innerHTML = `${alertMarkup}${insights.map((item) => {
      const config = LATEST_REPORT_CHANGE_CONFIG[item.code];
      const label = stateLabel[item.status] || '数据不足';
      const basis = interimPeriodLabel(latestPeriod, config.basis);
      return `<a class="latest-report-change-item ${escapeHtml(item.status || 'stable')}" href="#${config.chartId}"><strong>${escapeHtml(item.title || item.code)}｜${label}</strong><p>${escapeHtml(item.detail || '暂无指标说明。')}</p><span class="latest-report-change-basis">${basis} · 查看指标图</span></a>`;
    }).join('')}`;
  }

  function compactQuarterPeriod(period) {
    const normalized = String(period || '').trim();
    if (!/^\d{4}Q[1-4]$/.test(normalized)) return '季度监测';
    return `${normalized.slice(2)}-TTM`;
  }

  function annualAssessmentLabel(health) {
    const years = Number(health?.sample_years ?? health?.periods?.length ?? 0);
    if (health?.assessment_track === 'establishment') return `${years}年样本`;
    if (health?.assessment_track === 'snapshot') return `成立期财务快照｜${years || '不足2'}份完整年报｜暂不评分`;
    return '五年年报｜完整';
  }

  function annualAssessmentBasis(health) {
    const years = Number(health?.sample_years ?? health?.periods?.length ?? 0);
    if (health?.assessment_track === 'establishment') {
      const confidence = { low: '低', medium: '中等', higher: '较高' }[health.confidence] || '有限';
      return `成立期 ${years} 个完整年报｜${confidence}置信度｜不可与完整五年评分横比`;
    }
    if (health?.assessment_track === 'snapshot') return `成立期财务快照｜${years || '不足2'}份完整年报｜暂不评分`;
    return '五个完整年报口径';
  }

  function renderNicheLeaderBadge(profile) {
    const target = document.getElementById('basic-market-leader'); const category = String(profile?.profile?.niche_leader || '').trim();
    if (!target) return; target.innerHTML = category ? `<button type="button" class="niche-leader-trigger" data-niche-leader-detail title="查看细分龙头资料">🏆 细分龙头</button>` : '';
  }
  function showNicheLeaderDetail() {
    const profile = state.stockProfile?.profile || {}; const detail = profile.niche_leader_detail || {}; const category = String(detail.category || profile.niche_leader || '').trim(); const dialog = document.getElementById('niche-leader-dialog'); const content = document.getElementById('niche-leader-content');
    if (!dialog || !content || !category) return; document.getElementById('niche-leader-title').textContent = `细分龙头｜${profile.stock_name || state.selected?.symbol || ''}`; content.innerHTML = `<dt>细分领域</dt><dd>${escapeHtml(category)}</dd><dt>认定依据</dt><dd>${escapeHtml(detail.summary || '暂无可展示的认定依据摘要。')}</dd><dt>研究来源</dt><dd>${escapeHtml(detail.source || '细分龙头映射数据集')}</dd><dt>更新时间</dt><dd>${escapeHtml(detail.refreshed_at || '未提供')}</dd>`; dialog.showModal();
  }

  function metricStatus(state, label) { return { state, label }; }

  function peerMetricStatus(percentile) {
    const value = Number(percentile);
    if (!Number.isFinite(value)) return null;
    if (value >= 75) return metricStatus('strong', '行业前25%');
    if (value >= 25) return metricStatus('neutral', '行业中位');
    if (value >= 10) return metricStatus('watch', '行业后25%');
    return metricStatus('risk', '行业后10%');
  }

  function operatingMetricStatus(metric, value, { peerPercentile = null, consecutiveFcfNegative = false } = {}) {
    const number = Number(value);
    if (!Number.isFinite(number)) return metricStatus('unavailable', '数据不足');
    if (metric === 'net_margin') {
      if (number < 0) return metricStatus('risk', '亏损');
      return peerMetricStatus(peerPercentile) || (number >= 10 ? metricStatus('strong', '盈利较强') : number >= 0 ? metricStatus('neutral', '盈利') : metricStatus('risk', '亏损'));
    }
    if (metric === 'cash_profit_ratio') {
      if (number < 0 || number < 0.6) return metricStatus('risk', '现金不足');
      if (number < 0.8) return metricStatus('watch', '现金偏弱');
      return peerMetricStatus(peerPercentile) || (number >= 1 ? metricStatus('strong', '现金充足') : metricStatus('neutral', '基本健康'));
    }
    if (metric === 'debt_ratio') {
      if (number > 85) return metricStatus('risk', '杠杆过高');
      if (number > 70) return metricStatus('watch', '杠杆偏高');
      return peerMetricStatus(peerPercentile) || (number < 40 ? metricStatus('strong', '杠杆较低') : metricStatus('neutral', '杠杆正常'));
    }
    if (metric === 'revenue_yoy') return number >= 20 ? metricStatus('strong', '高增长') : number >= 5 ? metricStatus('neutral', '稳定增长') : number >= 0 ? metricStatus('watch', '低增长') : metricStatus('risk', '营收下滑');
    if (metric === 'revenue_cagr') return number >= 15 ? metricStatus('strong', '持续高增长') : number >= 5 ? metricStatus('neutral', '稳定增长') : number >= 0 ? metricStatus('watch', '长期低增') : metricStatus('risk', '长期收缩');
    if (metric === 'gross_margin') return number < 0 ? metricStatus('risk', '毛利为负') : number < 10 ? metricStatus('watch', '待同业比较') : metricStatus('neutral', '待同业比较');
    if (metric === 'roe_ex') return number >= 15 ? metricStatus('strong', '回报较强') : number >= 8 ? metricStatus('neutral', '回报正常') : number >= 0 ? metricStatus('watch', '回报偏弱') : metricStatus('risk', '回报为负');
    if (metric === 'fcf_margin') return number < -5 || consecutiveFcfNegative ? metricStatus('risk', '持续现金压力') : number < 0 ? metricStatus('watch', '投入期/承压') : number > 5 ? metricStatus('strong', '现金创造强') : metricStatus('neutral', '现金为正');
    return metricStatus('unavailable', '未设规则');
  }

  function valuationMetricStatus(metric, value) {
    const number = Number(value);
    if (!Number.isFinite(number) || (metric === 'pe_ttm' && number <= 0)) return metricStatus('unavailable', '估值不可比');
    if (metric === 'pe_ttm') return metricStatus('neutral', '非质地判断');
    return number <= 20 ? metricStatus('neutral', '历史低位') : number <= 80 ? metricStatus('neutral', '历史中位') : number <= 95 ? metricStatus('watch', '历史高位') : metricStatus('risk', '历史极高位');
  }

  function rpsMetricStatus(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return metricStatus('unavailable', '数据不足');
    return number >= 80 ? metricStatus('strong', '强势') : number >= 50 ? metricStatus('neutral', '偏强') : number >= 20 ? metricStatus('watch', '偏弱') : metricStatus('risk', '弱势');
  }

  function renderBasicMarket(valuation, reports = [], profile = null, pricePercentile = null, peHistory = null, quarterlyMonitor = null, industryFinancialPosition = null) {
    const grid = document.getElementById('basic-market-grid'); const period = document.getElementById('basic-market-period');
    if (!grid) return;
    const n = (v) => Number.isFinite(Number(v)) ? Number(v) : null;
    const text = (v, suffix = '') => n(v) === null ? '—' : `${n(v).toFixed(2)}${suffix}`;
    const pct = (v) => text(v, '%');
    const marketValue = (v) => n(v) === null ? '—' : n(v).toFixed(1);
    const ratioPct = (numerator, denominator) => n(numerator) === null || n(denominator) === null || n(denominator) === 0
      ? null : n(numerator) / n(denominator) * 100;
    const annual = [...reports].filter((r) => String(r?.period || '').endsWith('A')).sort((a,b) => String(a.period).localeCompare(String(b.period)));
    const revenue = (r) => n(r?.metrics?.revenue);
    const growth = (years) => { const end = annual.at(-1), start = annual.at(-(years + 1)); const a = revenue(end), b = revenue(start); return a !== null && b !== null && a > 0 && b > 0 ? ((a / b) ** (1 / years) - 1) * 100 : null; };
    const ttm = buildLatestTTMReport(reports, quarterlyMonitor)?.metrics || {};
    const latestPoint = [...reports].sort((a, b) => String(a?.period || '').localeCompare(String(b?.period || ''))).at(-1)?.metrics || {};
    const industryMetrics = industryFinancialPosition?.status === 'available' ? industryFinancialPosition.metrics || {} : {};
    const peerPercentile = (metric) => industryMetrics[metric]?.percentile;
    const cashProfitRatio = ratioPct(ttm.ocf, ttm.ex_net_profit);
    const fcfMargin = ratioPct(ttm.free_cf, ttm.revenue);
    const latestAnnualFcfMargin = ratioPct(annual.at(-1)?.metrics?.free_cf, annual.at(-1)?.metrics?.revenue);
    const consecutiveFcfNegative = [fcfMargin, latestAnnualFcfMargin].every((value) => Number.isFinite(value) && value < 0);
    const cagr3 = growth(3); const pePercentile = peHistory?.history?.at(-1)?.pe_pct;
    const rps = profile?.profile || {}; const cards = [
      { label: '现价', value: text(valuation?.current_price, ' 元'), kind: 'kline' },
      { label: 'PE-TTM', value: text(valuation?.pe_ttm), kind: 'pe', status: valuationMetricStatus('pe_ttm', valuation?.pe_ttm) },
      { label: '总市值（亿）', value: marketValue(valuation?.total_market_cap) },
      { label: '营收同比（TTM）', value: pct(ttm.revenue_yoy), status: operatingMetricStatus('revenue_yoy', ttm.revenue_yoy) },
      { label: '3年营收 CAGR', value: pct(cagr3), status: operatingMetricStatus('revenue_cagr', cagr3) },
      { label: '毛利率（TTM）', value: pct(ttm.gross_margin), status: operatingMetricStatus('gross_margin', ttm.gross_margin) },
      { label: '净利率（TTM）', value: pct(ttm.net_margin), status: operatingMetricStatus('net_margin', ttm.net_margin, { peerPercentile: peerPercentile('net_margin') }) },
      { label: 'RPS20', value: text(rps.rps_20), kind: 'rps', status: rpsMetricStatus(rps.rps_20) },
      { label: 'RPS50', value: text(rps.rps_50), kind: 'rps', status: rpsMetricStatus(rps.rps_50) },
      { label: '股价五年分位', value: pct(pricePercentile?.price_percentile), status: valuationMetricStatus('price_percentile', pricePercentile?.price_percentile) },
      { label: 'PE 5年分位', value: pct(pePercentile), status: valuationMetricStatus('pe_percentile', pePercentile) },
      { label: '流通市值（亿）', value: marketValue(valuation?.free_float_market_cap) },
      { label: '扣非 ROE（TTM）', value: pct(ttm.roe_ex), status: operatingMetricStatus('roe_ex', ttm.roe_ex) },
      { label: '现金利润比（TTM）', value: text(cashProfitRatio === null ? null : cashProfitRatio / 100), status: operatingMetricStatus('cash_profit_ratio', cashProfitRatio === null ? null : cashProfitRatio / 100, { peerPercentile: peerPercentile('ocf_to_profit') }) },
      { label: 'FCF率（TTM）', value: pct(fcfMargin), status: operatingMetricStatus('fcf_margin', fcfMargin, { consecutiveFcfNegative }) },
      { label: '资产负债率（最新）', value: pct(latestPoint.debt_ratio), status: operatingMetricStatus('debt_ratio', latestPoint.debt_ratio, { peerPercentile: peerPercentile('debt_ratio') }) },
      { label: 'RPS120', value: text(rps.rps_120), kind: 'rps', status: rpsMetricStatus(rps.rps_120) },
      { label: 'RPS250', value: text(rps.rps_250), kind: 'rps', status: rpsMetricStatus(rps.rps_250) },
    ];
    period.textContent = `${valuation?.industry_level_2_name || '—'}｜${annual.at(-1)?.period || '年报覆盖不足'}｜RPS 最新截面`;
    grid.innerHTML = cards.map(({ label, value, kind, status }) => {
      const state = status?.state || ''; const statusLabel = status?.label || '';
      const ariaLabel = statusLabel ? `${label}：${value}；${statusLabel}` : `${label}：${value}`;
      return `<article class="basic-market-card ${state}" aria-label="${escapeHtml(ariaLabel)}"${kind === 'pe' ? ' data-stock-pe-history role="button" tabindex="0" title="查看 PE-TTM 历史走势"' : ''}${kind === 'kline' ? ' data-stock-kline-history role="button" tabindex="0" title="查看历史K线图"' : ''}><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value)}</span>${statusLabel ? `<em class="basic-market-status">${escapeHtml(statusLabel)}</em>` : ''}</article>`;
    }).join('');
  }

  let stockKlineChart = null;
  async function showStockKlineHistory() {
    const d=document.getElementById('stock-kline-dialog'), svg=document.getElementById('stock-kline-svg'), title=document.getElementById('stock-kline-title'), status=document.getElementById('stock-kline-status'), s=state.selected?.symbol;
    if(!d||!svg||!s)return; d.showModal(); title.textContent=`${s}｜历史K线图`; status.textContent='加载前复权日线、成交量、均线和 RPS…';
    try { const [a,b]=await Promise.all([fetch(`/api/stock-kline?symbol=${encodeURIComponent(s)}&limit=300`),fetch(`/api/stock-rps-history?symbol=${encodeURIComponent(s)}`)]); const [k,r]=await Promise.all([a.json(),b.json()]); if(!k.ok)throw Error('数据不可用'); const {KlineChart}=await import('./kline-chart.js?v=20260604-ma'); if(!stockKlineChart)stockKlineChart=new KlineChart(svg,{marginRight:20}); stockKlineChart.load(k.bars||[],r.history||[],250); title.textContent=`${s} ${k.bars?.[0]?.name||''}｜历史K线图`; status.textContent=`前复权日线｜${k.bars?.length||0} 个交易日｜含 MA10/20/30/60 与 RPS`; } catch(e) { status.textContent=`K线加载失败：${e.message||'未知错误'}`; }
  }

  async function showStockPeHistory() {
    const dialog = document.getElementById('stock-pe-history-dialog'), title = document.getElementById('stock-pe-history-title'), meta = document.getElementById('stock-pe-history-meta'), chart = document.getElementById('stock-pe-history-chart'), table = document.getElementById('stock-pe-history-table');
    const stock = state.selected; if (!dialog || !stock) return; title.textContent = `PE-TTM 历史走势 — ${stock.stock_name || stock.symbol}`; meta.textContent = '加载真实季度估值序列…'; chart.innerHTML = ''; table.innerHTML = ''; dialog.showModal();
    try { const res = await fetch(`/api/stock-pe-history?symbol=${encodeURIComponent(stock.symbol)}`); const data = await res.json(); const rows = (data.history || []).filter(r => Number.isFinite(Number(r.pe_ad)) || Number.isFinite(Number(r.ind_median_pe))); if (!res.ok || !data.ok || !rows.length) { meta.textContent = '暂无可用 PE-TTM 历史数据。'; return; }
      meta.textContent = `共 ${rows.length} 个报告期｜橙线为个股披露日 PE-TTM，蓝虚线为同行业中位数，绿虚线为当前实时 PE。`;
      const vals = [...rows.map(r=>Number(r.pe_ad)),...rows.map(r=>Number(r.ind_median_pe)),Number(data.current_pe)].filter(Number.isFinite); const W=920,H=330,L=55,R=28,T=24,B=45,pw=W-L-R,ph=H-T-B,max=Math.max(...vals)*1.1||1, y=v=>T+ph-(v/max)*ph, x=i=>L+(rows.length<2?pw/2:i*pw/(rows.length-1)); let grid=''; for(let i=0;i<=5;i++){const v=max*i/5, yy=y(v);grid+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="rgba(98,184,255,.2)" stroke-dasharray="4 5"/><text x="${L-8}" y="${yy+4}" text-anchor="end" fill="#89a9bb" font-size="11">${v.toFixed(0)}</text>`;} const line=(field)=>rows.map((r,i)=>Number.isFinite(Number(r[field]))?`${i&&Number.isFinite(Number(rows[i-1][field]))?'L':'M'}${x(i).toFixed(1)},${y(Number(r[field])).toFixed(1)}`:'').join(' '); const labels=rows.map((r,i)=>(i===0||i===rows.length-1||i%Math.ceil(rows.length/10)===0)?`<text x="${x(i)}" y="${H-14}" text-anchor="middle" fill="#89a9bb" font-size="10">${escapeHtml(r.period)}</text>`:'').join(''); const dots=rows.map((r,i)=>Number.isFinite(Number(r.pe_ad))?`<circle cx="${x(i)}" cy="${y(Number(r.pe_ad))}" r="3" fill="#ffc36f"><title>${escapeHtml(`${r.period}｜PE-TTM ${Number(r.pe_ad).toFixed(2)}`)}</title></circle>`:'').join(''); const current=Number(data.current_pe); chart.innerHTML=`${grid}<path d="${line('pe_ad')}" fill="none" stroke="#ffc36f" stroke-width="3"/>${dots}<path d="${line('ind_median_pe')}" fill="none" stroke="#62b8ff" stroke-width="2" stroke-dasharray="7 5"/>${Number.isFinite(current)?`<line x1="${L}" y1="${y(current)}" x2="${W-R}" y2="${y(current)}" stroke="#73dfc4" stroke-width="2" stroke-dasharray="8 6"/><text x="${W-R}" y="${y(current)-7}" text-anchor="end" fill="#73dfc4" font-size="11">当前 ${current.toFixed(2)}</text>`:''}${labels}`;
      table.innerHTML=rows.map(r=>`<tr><td>${escapeHtml(r.period)}</td><td>${Number.isFinite(Number(r.pe_ad))?Number(r.pe_ad).toFixed(2):'—'}</td><td>${Number.isFinite(Number(r.ind_median_pe))?Number(r.ind_median_pe).toFixed(2):'—'}</td><td>${Number.isFinite(Number(r.pe_pct))?`${Number(r.pe_pct).toFixed(1)}%`:'—'}</td></tr>`).join('');
    } catch(e) { meta.textContent=`加载 PE-TTM 历史失败：${e.message}`; }
  }

  function renderCompositeFinancialHealth(composite) {
    const root = document.getElementById('financial-health-composite');
    const score = document.getElementById('financial-health-composite-score');
    const status = document.getElementById('financial-health-composite-status');
    const detail = document.getElementById('financial-health-composite-detail');
    const risk = document.getElementById('financial-health-composite-risk');
    if (!root || !score || !status || !detail || !risk) return;
    const labels = { excellent: '优秀', stable: '稳健', watch: '关注', risk: '风险', unavailable: '数据不足' };
    const level = composite?.display_status || 'unavailable';
    root.className = `financial-health-composite ${level}`;
    const value = Number(composite?.score);
    score.innerHTML = Number.isFinite(value) ? `${value.toFixed(1)} <small>/ 100</small>` : '— <small>/ 100</small>';
    const mode = composite?.mode;
    status.textContent = mode === 'blended'
      ? `${labels[level]}｜长期基础与最新当季共同判断`
      : mode === 'annual_only'
        ? `${labels[level]}｜最新当季数据不足，未加入当季修正`
        : mode === 'quarterly_only'
          ? `${labels[level]}｜成立期或非五年样本，仅展示当季监测分`
          : '数据不足｜暂不生成综合判断';
    const formatScore = (item) => Number.isFinite(Number(item)) ? Number(item).toFixed(1) : '—';
    if (mode === 'blended') {
      detail.textContent = `五年基础 ${formatScore(composite.annual_score)} × ${(Number(composite.annual_weight) * 100).toFixed(0)}% + 当季脉冲 ${formatScore(composite.quarterly_score)} × ${(Number(composite.quarterly_weight) * 100).toFixed(0)}%｜最新 ${composite.quarterly_period || '—'}｜当季覆盖 ${composite.quarterly_coverage_weight ?? '—'} / 100。`;
    } else if (mode === 'annual_only') {
      detail.textContent = `五年基础 ${formatScore(composite?.annual_score)} × 100%｜当季监测覆盖 ${composite?.quarterly_coverage_weight ?? '—'} / 100，未达合成门槛。`;
    } else if (mode === 'quarterly_only') {
      detail.textContent = `当季脉冲 ${formatScore(composite?.quarterly_score)} × 100%｜最新 ${composite?.quarterly_period || '—'}；不是五年长期综合分。`;
    } else {
      detail.textContent = '需要连续五年完整年报与可评分的当季监测，才会生成可比较的综合判断。';
    }
    const overlay = composite?.risk_overlay || {};
    risk.className = `financial-health-composite-risk ${overlay.status || 'none'}`;
    risk.textContent = `风险覆盖层：${overlay.message || '尚未完成风险规则评估。'} 数值分不因该提示重复扣减。`;
  }

  function renderFinancialReversalBadge(indicator) {
    const badge = document.getElementById('financial-health-reversal-badge');
    if (!badge) return;
    const matched = indicator?.matched === true;
    badge.hidden = !matched;
    badge.textContent = '财报反转';
    badge.title = matched
      ? `符合财报反转标准｜最新 ${indicator.quarterly_period || '财报'}`
      : '';
  }

  function renderReportReleasePricePerformance(performance) {
    const target = document.getElementById('financial-health-release-return');
    if (!target) return;
    const value = Number(performance?.return_pct);
    const available = performance?.available === true && Number.isFinite(value);
    target.hidden = !available;
    if (!available) {
      target.className = 'financial-health-release-return';
      target.title = '';
      return;
    }
    const tone = value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral';
    target.className = `financial-health-release-return ${tone}`;
    const amount = `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
    target.querySelector('strong').textContent = amount;
    target.title = `原始价｜财报公告 ${performance.announce_date || '—'}；T+1 ${performance.entry_trading_day || '—'} 开盘 ${performance.entry_open ?? '—'}；当前 ${performance.current_price ?? '—'}（${performance.current_price_as_of || '实时'}）`;
  }

  function showReportReleasePriceTrend() {
    const trend = state.reportReleasePriceTrend;
    const dialog = document.getElementById('report-release-price-trend-dialog'); const svg = document.getElementById('report-release-price-trend-svg'); const meta = document.getElementById('report-release-price-trend-meta');
    if (!dialog || !svg || trend?.available !== true || !trend.points?.length) return;
    const rows = trend.points, marks = trend.markers || {}; const values = [...rows.map(r=>Number(r.close)), ...Object.values(marks).map(m=>Number(m?.price))].filter(Number.isFinite); if (!values.length) return;
    const W=920,H=330,L=58,R=28,T=25,B=46,pw=W-L-R,ph=H-T-B,min=Math.min(...values),max=Math.max(...values),pad=Math.max((max-min)*.12,max*.025),lo=min-pad,hi=max+pad,y=v=>T+ph-(v-lo)/(hi-lo)*ph,x=i=>L+(rows.length<2?pw/2:i*pw/(rows.length-1));
    const esc=escapeHtml, path=rows.map((r,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(Number(r.close)).toFixed(1)}`).join(' '); let grid=''; for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,yy=y(v);grid+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="rgba(98,184,255,.2)" stroke-dasharray="4 5"/><text x="${L-8}" y="${yy+4}" text-anchor="end" fill="#89a9bb" font-size="11">${v.toFixed(2)}</text>`;}
    const ticks=rows.map((r,i)=>(i===0||i===rows.length-1||i%Math.ceil(rows.length/6)===0)?`<text x="${x(i)}" y="${H-14}" text-anchor="middle" fill="#89a9bb" font-size="10">${esc(r.trading_day.slice(5))}</text>`:'').join('');
    const specs=[['entry_open','T+1 开盘价','#ffc36f'],['high','最高价','#ff8d8d'],['low','最低价','#73dfc4'],['current','当前价','#8bd8ff']]; const markerSvg=specs.map(([key,label,color])=>{const m=marks[key]; if(!m||!Number.isFinite(Number(m.price)))return ''; const i=Math.max(0,rows.findIndex(r=>r.trading_day===m.trading_day)); const xx=x(i),yy=y(Number(m.price)),anchor=i===0?'start':i===rows.length-1?'end':'middle',labelX=i===0?xx+8:i===rows.length-1?xx-8:xx; return `<circle cx="${xx}" cy="${yy}" r="5" fill="${color}" stroke="#07131a" stroke-width="2"><title>${esc(`${label}｜${m.trading_day}｜${Number(m.price).toFixed(2)}`)}</title></circle><text x="${labelX}" y="${yy-9}" text-anchor="${anchor}" fill="${color}" font-size="11">${label} ${Number(m.price).toFixed(2)}</text>`;}).join('');
    svg.innerHTML=`${grid}<path d="${path}" fill="none" stroke="#62b8ff" stroke-width="3"/>${markerSvg}${ticks}`; meta.textContent=`原始价收盘趋势｜${rows[0].trading_day} 至 ${rows.at(-1).trading_day}｜标记为 T+1 开盘、区间最高/最低及当前价。`; dialog.showModal();
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
    const annualPeriod = annualAssessmentLabel(health);
    const quarterPeriod = compactQuarterPeriod(monitor?.latest_period);
    const overallButton = (source, score) => score === unavailable ? unavailable : `<button type="button" class="comparison-score-button" data-overall-source="${source}" aria-label="查看总体财报分析结论">${score}</button>`;
    const cells = (klass, label, source, score, coverage, dims, flags, investigations) => `<tr><td class="${klass}"><strong>${escapeHtml(label)}</strong></td><td>${overallButton(source, score)}</td><td>${coverage}</td>${dims.map(points => `<td>${points}</td>`).join('')}<td>${flags}</td><td>${investigations}</td></tr>`;
    target.innerHTML = [
      cells('comparison-annual', annualPeriod, 'annual', annualScore, health ? String(health.coverage_weight ?? 0) : unavailable, [annualDimension('growth_quality'), annualDimension('profitability'), annualDimension('cash_quality'), annualDimension('working_capital'), annualDimension('reinvestment'), annualDimension('financial_risk')].map((item) => scoreDetailButton('annual', item)), annualFlags, annualInvestigations),
      cells('comparison-quarter', quarterPeriod, 'quarterly', quarterlyScore, monitor?.realtime_score ? String(monitor.realtime_score.coverage_weight ?? 0) : unavailable, [quarterlyDimension('growth'), quarterlyDimension('profitability'), quarterlyDimension('cash'), quarterlyDimension('working_capital'), quarterlyDimension('reinvestment'), quarterlyDimension('financial_risk')].map((item) => scoreDetailButton('quarterly', item)), quarterlyAlerts, quarterlyInvestigations),
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
    const dims = (monitor.dimensions || []).map((item) => `<div class="quarterly-monitor-item ${escapeHtml(item.status)}"><strong>${escapeHtml(item.title)}</strong><span>${state[item.status] || '—'}</span><small>${escapeHtml(item.detail || '')}</small></div>`).join('');
    const alerts = monitor.alerts?.length ? `<div class="quarterly-monitor-alerts"><strong>本季预警</strong>${monitor.alerts.map((item) => `<p class="${escapeHtml(item.severity)}">${escapeHtml(item.title)}：${escapeHtml(item.detail)}</p>`).join('')}</div>` : '<div class="quarterly-monitor-alerts"><strong>本季预警</strong><p>未触发季度早期预警。</p></div>';
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
      dimensions.innerHTML = (items || []).map((item) => `<article class="health-dimension ${escapeHtml(item.status || 'unavailable')}"><div class="health-dimension-top"><span>${escapeHtml(item.title)}</span><span class="health-dimension-score">${escapeHtml(notApplicableLabel[item.status] || '数据不足')}</span></div><div class="health-dimension-trend">${escapeHtml(item.reason || '通用规则未评估')}</div></article>`).join('') || '<p class="health-evidence-empty">未返回维度状态。</p>';
    };
    const renderUnavailableConclusions = (items) => {
      conclusionPanel.innerHTML = (items || []).map((item) => `<article class="health-conclusion ${escapeHtml(item.status || 'insufficient')}"><strong>${escapeHtml(item.question)}</strong><span>${escapeHtml(notApplicableLabel[item.status] || '数据不足')}</span><p>${escapeHtml(item.detail || item.reason || '暂无可用结论。')}</p>${healthEvidenceSummary(item.evidence) ? `<small class="health-rule-evidence">${escapeHtml(healthEvidenceSummary(item.evidence))}</small>` : ''}</article>`).join('') || '<p class="health-evidence-empty">未返回结论状态。</p>';
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
      return `<article class="health-dimension ${escapeHtml(item.status)}"><div class="health-dimension-top"><span>${escapeHtml(item.title)}</span><span class="health-dimension-score">${item.available ? `${healthValue(item.score)} / ${item.weight}` : '数据不足'}</span></div><div class="health-dimension-trend">${trendLabel[item.trend] || '—'}</div>${formation ? `<small class="health-rule-evidence">${formation.split('\n').map(escapeHTML).join('<br>')}</small>` : ''}</article>`;
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
      return `<article class="health-conclusion ${escapeHtml(item.status)}"><strong>${escapeHtml(item.question)}</strong><span>${conclusionLabel[item.status] || '—'}</span><p>${escapeHtml(concise.summary)}</p><small class="health-rule-evidence">${escapeHtml(concise.focus)}</small></article>`;
    }).join('') || '暂无可用结论。';
  }

  function showIndustryValuationHistory(valuation) {
    const dialog = document.getElementById('industry-valuation-history-dialog');
    const title = document.getElementById('industry-valuation-history-title');
    const meta = document.getElementById('industry-valuation-history-meta');
    const chart = document.getElementById('industry-valuation-history-chart');
    const table = document.getElementById('industry-valuation-history-table');
    if (!dialog || !title || !meta || !chart || !table) return;
    const rows = (valuation?.industry_temperature_history || []).filter((row) => row.trading_day >= '2020-01-01' && Number.isFinite(Number(row.weighted_pe_ttm)));
    const industry = String(valuation?.industry_level_2_name || '二级行业');
    title.textContent = `${industry}｜行业历史估值`;
    if (!rows.length) { meta.textContent = '2020 年以来暂无可用季度加权 PE-TTM。'; chart.innerHTML = ''; table.innerHTML = ''; dialog.showModal(); return; }
    const current = Number(rows.at(-1).weighted_pe_ttm);
    meta.textContent = `行业过热 / ${Number(valuation?.industry_temperature_percentile_since_2022 || 0).toFixed(2)}%｜历史序列基于自 2020 年以来行业加权 PE-TTM。`;
    const values = rows.map((row) => Number(row.weighted_pe_ttm));
    const lo = Math.min(...values); const hi = Math.max(...values); const span = Math.max(hi - lo, 1);
    const d = { w: 920, h: 310, l: 58, r: 28, t: 24, b: 45 }; const pw = d.w - d.l - d.r; const ph = d.h - d.t - d.b;
    const x = (i) => d.l + (rows.length === 1 ? pw / 2 : i * pw / (rows.length - 1));
    const y = (v) => d.t + (hi - v) / span * ph;
    const line = rows.map((row, i) => `${x(i).toFixed(1)},${y(Number(row.weighted_pe_ttm)).toFixed(1)}`).join(' ');
    const ticks = [0, .25, .5, .75, 1].map((ratio) => { const value = hi - ratio * span; const yy = d.t + ratio * ph; return `<line x1="${d.l}" y1="${yy}" x2="${d.w - d.r}" y2="${yy}" stroke="rgba(139,216,255,.2)"/><text x="${d.l - 8}" y="${yy + 4}" text-anchor="end" fill="#89a9bb" font-size="11">${value.toFixed(1)}</text>`; }).join('');
    const labels = rows.map((row, i) => (i === 0 || i === rows.length - 1 || String(row.trading_day).endsWith('-03-31')) ? `<text x="${x(i)}" y="${d.h - 14}" text-anchor="middle" fill="#89a9bb" font-size="11">${String(row.trading_day).slice(2, 7)}</text>` : '').join('');
    const points = rows.map((row, i) => `<circle cx="${x(i)}" cy="${y(Number(row.weighted_pe_ttm))}" r="3.5" fill="#ffc36f"><title>${escapeHtml(`${row.trading_day}｜加权 PE-TTM ${Number(row.weighted_pe_ttm).toFixed(2)}`)}</title></circle>`).join('');
    chart.innerHTML = `${ticks}<line x1="${d.l}" y1="${y(current)}" x2="${d.w - d.r}" y2="${y(current)}" stroke="#73dfc4" stroke-dasharray="7 6"/><text x="${d.w - d.r}" y="${y(current) - 8}" text-anchor="end" fill="#73dfc4" font-size="12">当前 ${current.toFixed(2)}</text><polyline points="${line}" fill="none" stroke="#ffc36f" stroke-width="3"/>${points}${labels}`;
    table.innerHTML = rows.map((row, index) => { const value = Number(row.weighted_pe_ttm); const change = current ? (value / current - 1) * 100 : null; const klass = index === rows.length - 1 ? ' class="industry-valuation-history-current"' : ''; return `<tr${klass}><td>${escapeHtml(row.trading_day)}</td><td>${value.toFixed(2)}</td><td>${Number.isFinite(change) ? `${change >= 0 ? '+' : ''}${change.toFixed(1)}%` : '—'}</td></tr>`; }).join('');
    dialog.showModal();
  }

  async function showIndustryValuationPeers() {
    const dialog = document.getElementById('industry-valuation-peer-dialog'); const title = document.getElementById('industry-valuation-peer-title'); const status = document.getElementById('industry-valuation-peer-status');
    if (!dialog || !title || !status || !state.selected?.market || !state.selected?.symbol) return;
    title.textContent = '行业估值位置对照'; status.textContent = '正在加载二级行业全量股票…'; document.getElementById('industry-valuation-peer-table').innerHTML = ''; dialog.showModal();
    try {
      const url = `/api/industry-valuation-percentile?market=${encodeURIComponent(state.selected.market)}&symbol=${encodeURIComponent(state.selected.symbol)}`;
      const response = await fetch(url); const payload = await response.json();
      if (!response.ok || !payload?.ok) throw new Error(payload?.error?.message || `HTTP ${response.status}`);
      state.industryValuationPeers = Array.isArray(payload.rows) ? payload.rows : [];
      const current = state.industryValuationPeers.find((row) => row.is_current_stock);
      title.textContent = `${payload.industry_level_2_name || '当前行业'}｜${String(payload.primary_metric || 'PE').toUpperCase().replace('_', '-')}估值分位对照${current?.valuation_percentile != null ? `（当前股票：${Number(current.valuation_percentile).toFixed(1)}%）` : ''}`;
      status.textContent = `共 ${state.industryValuationPeers.length} 只股票；分位仅基于可比的有效估值样本计算。点击列头可排序。`;
      renderIndustryValuationPeers();
    } catch (error) { status.textContent = `加载同业估值名单失败：${error.message}`; }
  }

  function renderIndustryValuationPeers() {
    const target = document.getElementById('industry-valuation-peer-table'); if (!target) return;
    const { key, direction } = state.industryPeerSort;
    const rows = [...state.industryValuationPeers].sort((a, b) => { const rawA = a?.[key]; const rawB = b?.[key]; const av = rawA == null || rawA === '' ? NaN : Number(rawA); const bv = rawB == null || rawB === '' ? NaN : Number(rawB); const aok = Number.isFinite(av); const bok = Number.isFinite(bv); if (aok && bok) return direction * (av - bv); if (aok) return -1; if (bok) return 1; return 0; });
    const metric = (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '—';
    target.innerHTML = rows.map((row) => `<tr class="${row.is_current_stock ? 'industry-valuation-peer-current' : ''}"><td>${row.valuation_percentile != null ? `${Number(row.valuation_percentile).toFixed(1)}%` : '—'}</td><td><span class="industry-valuation-peer-stock">${escapeHtml(row.stock_name || '—')}</span><span class="industry-valuation-peer-code">${escapeHtml(`${String(row.market || '').toUpperCase()}:${row.symbol || '—'}`)}</span></td><td>${metric(row.current_price)}</td><td>${metric(row.ps_ttm)}</td><td>${metric(row.pe_ttm)}</td><td>${escapeHtml(row.valuation_band || '估值不可比')}</td></tr>`).join('') || '<tr><td colspan="6">当前行业暂无可展示成员。</td></tr>';
  }

  const HEALTH_PEER_DIMENSIONS = ['growth_quality', 'profitability', 'cash_quality', 'working_capital', 'reinvestment', 'financial_risk'];
  const formatHealthPeerScore = (value) => (value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))) ? Number(value).toFixed(Number.isInteger(Number(value)) ? 0 : 1) : '—';
  const healthPeerDimension = (score, code) => (score?.dimensions || {})[code];
  function renderIndustryHealthPeers() {
    const payload = state.industryHealthPeers; const view = state.industryHealthPeerView; const body = document.getElementById('industry-health-peer-table'); const status = document.getElementById('industry-health-peer-status');
    if (!payload || !body || !status) return;
    const referenceOnly = view === 'latest_available_quarterly'; const { key, direction } = state.industryHealthPeerSort;
    const rows = [...(payload.rows || [])].sort((a, b) => { const av = key === 'stock_name' ? String(a.stock_name || '') : Number(key === 'score' ? a[view]?.score : healthPeerDimension(a[view], key, view)); const bv = key === 'stock_name' ? String(b.stock_name || '') : Number(key === 'score' ? b[view]?.score : healthPeerDimension(b[view], key, view)); if (key === 'stock_name') return av.localeCompare(bv, 'zh-CN') * direction; const aok = Number.isFinite(av), bok = Number.isFinite(bv); if (aok !== bok) return aok ? -1 : 1; return aok ? (av - bv) * direction : String(a.symbol).localeCompare(String(b.symbol)); });
    const valid = rows.filter(row => { const value = row[view]?.score; return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)); }).length;
    const periods = [...new Set(rows.map(row => view === 'annual' ? (row.annual?.periods || []).join('–') : row[view]?.period).filter(Boolean))];
    status.textContent = referenceOnly ? `${payload.industry_level_2 || '当前二级行业'}｜各股最近可用财报（TTM + 对应季度资产负债表）｜可展示 ${valid}/${rows.length}｜报告期因公司而异：${periods.join(' / ') || '—'}。仅供参考；点击列头可排序，不构成同业排名。` : `${payload.industry_level_2 || '当前二级行业'}｜${view === 'annual' ? '完整年报健康评分（5年年报；成立期样本单列）' : '当季最新财报监测（TTM + 最新季度资产负债表）'}｜可评分 ${valid}/${rows.length}｜报告期：${periods.join(' / ') || '—'}。点击列头可排序。`;
    body.innerHTML = rows.map(row => { const score = row[view] || {}; return `<tr class="${row.is_current_stock ? 'industry-health-peer-current' : ''}"><td><span class="industry-health-peer-stock">${escapeHtml(row.stock_name || row.symbol)}</span><span class="industry-health-peer-code">${escapeHtml(`${row.market || ''}:${row.symbol || ''}`)}${view === 'annual' ? `｜${escapeHtml(score.assessment_track === 'establishment' ? `${score.sample_years}年样本` : '5年年报')}` : `｜${escapeHtml(score.period || '—')}${referenceOnly ? '｜仅供参考' : ''}`}</span></td><td>${formatHealthPeerScore(score.score)}</td>${HEALTH_PEER_DIMENSIONS.map(code => `<td>${formatHealthPeerScore(healthPeerDimension(score, code, view))}</td>`).join('')}</tr>`; }).join('') || '<tr><td colspan="8">暂无行业成员数据。</td></tr>';
    document.querySelectorAll('[data-health-peer-view]').forEach(button => button.classList.toggle('active', button.dataset.healthPeerView === view));
  }
  async function showIndustryHealthPeers() {
    const dialog = document.getElementById('industry-health-peer-dialog'); const title = document.getElementById('industry-health-peer-title'); const status = document.getElementById('industry-health-peer-status'); const body = document.getElementById('industry-health-peer-table');
    if (!dialog || !state.selected) return; if (!dialog.open) dialog.showModal(); title.textContent = '行业财务健康度对照'; status.textContent = '正在按该二级行业全部股票的完整财报计算年度评分和最新季度监测，首次加载可能需要约一分钟，完成后会缓存。'; body.innerHTML = '<tr><td colspan="8">正在加载全行业财务健康数据…</td></tr>';
    try { const response = await fetch(`/api/industry-financial-health-peers?market=${encodeURIComponent(state.selected.market)}&symbol=${encodeURIComponent(state.selected.symbol)}`); const payload = await response.json(); if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || payload?.reason || '行业健康度数据不可用'); state.industryHealthPeers = payload; title.textContent = `${payload.industry_level_2 || '当前行业'}｜财务健康度对照`; renderIndustryHealthPeers(); } catch (error) { status.textContent = `加载失败：${error.message || '未知错误'}`; body.innerHTML = '<tr><td colspan="8">行业财务健康度数据加载失败。</td></tr>'; }
  }

  function renderValuationPerformanceLinkage(valuation, health, monitor) {
    const target = document.getElementById('valuation-performance-linkage'); const period = document.getElementById('valuation-performance-linkage-period');
    if (!target || !period) return;
    state.industryValuation = valuation || null;
    if (!valuation?.ok) { period.textContent = '相对估值数据暂不可用'; target.textContent = '财务健康度与季度变化仍可在下方查看。'; return; }
    const valPeriod = `${valuation.industry_level_2_name || '—'}｜${valuation.primary_percentile_metric === 'pe_ttm' ? 'PE-TTM' : 'PS-TTM'}`;
    const healthScore = Number.isFinite(Number(health?.score)) ? `${Number(health.score).toFixed(0)} / 100（${health.status || '—'}）` : '数据不足';
    const flags = Array.isArray(health?.red_flags) ? health.red_flags : [];
    const alerts = Array.isArray(monitor?.alerts) ? monitor.alerts : [];
    const industryName = valuation.industry_level_2_name || '—';
    period.innerHTML = `<button type="button" class="industry-valuation-history-trigger" data-industry-valuation-history>${escapeHtml(industryName)}</button>｜${escapeHtml(valuation.primary_percentile_metric === 'pe_ttm' ? 'PE-TTM' : 'PS-TTM')}｜财报期 ${escapeHtml(monitor?.latest_period || '—')}`;
    target.className = '';
    target.innerHTML = `<div class="latest-report-change-grid"><article class="latest-report-change-item stable" data-industry-valuation-peers role="button" tabindex="0" title="查看该二级行业全部股票估值位置"><strong>行业内估值位置</strong><p>${escapeHtml(valuation.valuation_band_label || '—')}｜${Number.isFinite(Number(valuation.primary_percentile)) ? `${Number(valuation.primary_percentile).toFixed(1)}% 分位` : '分位不可用'}</p><span class="latest-report-change-basis">个股 ${Number.isFinite(Number(valuation.primary_percentile_value)) ? Number(valuation.primary_percentile_value).toFixed(2) : '—'}；行业加权 ${Number.isFinite(Number(valuation.industry_weighted_pe_ttm)) ? `PE ${Number(valuation.industry_weighted_pe_ttm).toFixed(2)}` : '—'}</span></article><article class="latest-report-change-item stable" data-industry-health-peers role="button" tabindex="0" title="查看该二级行业全部股票财务健康度"><strong>财务健康度</strong><p>${escapeHtml(healthScore)}</p><span class="latest-report-change-basis">完整年报：${escapeHtml((health?.periods || []).join('、') || '—')}</span></article><article class="latest-report-change-item ${alerts.length || flags.length ? 'watch' : 'stable'}"><strong>季度变化与红旗</strong><p>季度变化：${alerts.length ? `${alerts.length} 项提示` : '暂无提示'}；红旗：${flags.length} 项</p><span class="latest-report-change-basis">${escapeHtml([...alerts.map((item) => item.title), ...flags.map((item) => item.title)].join('；') || '无已列示事项')}</span></article></div>`;
  }

  function formatIndustryPositionMetric(value, unit) {
    if (!Number.isFinite(Number(value))) return '—';
    const suffix = String(unit || '').trim();
    return `${Number(value).toFixed(2)}${suffix ? ` ${escapeHtml(suffix)}` : ''}`;
  }

  function renderIndustryFinancialPosition(position) {
    const target = document.getElementById('industry-financial-position'); const period = document.getElementById('industry-financial-position-period');
    if (!target || !period) return;
    if (position?.status !== 'available') { period.textContent = '行业对比暂不可用'; target.textContent = '缺少可对齐的行业快照数据。'; return; }
    period.textContent = `${position.industry_level_2}｜${position.report_period}｜覆盖率 ${position.period_alignment_coverage}%（${position.aligned_sample_count}/${position.industry_member_count}）`;
    target.className = '';
    const rows = Object.values(position.metrics || {}).map((m) => `<tr><td>${escapeHtml(m.label)}</td><td>${formatIndustryPositionMetric(m.company_value, m.unit)}</td><td>${formatIndustryPositionMetric(m.industry_median, m.unit)}</td><td>${Number.isFinite(m.percentile) ? `${m.percentile.toFixed(1)}%` : '—'}</td><td>${m.sample_count || 0}</td></tr>`).join('');
    target.innerHTML = `<table class="health-comparison-table"><thead><tr><th>指标</th><th>公司</th><th>行业中位数</th><th>分位</th><th>样本数</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  const METRIC_CHARTS = [
    ['revenue-chart', 'revenue', 'revenue', 'amount', 'ttm'],
    ['net-profit-chart', 'net_profit', 'profit', 'amount', 'ttm'],
    ['ex-net-profit-chart', 'ex_net_profit', 'profit', 'amount', 'ttm'],
    ['gross-margin-chart', 'gross_margin', 'ratio', 'percent', 'ttm'],
    ['net-margin-chart', 'net_margin', 'ratio', 'percent', 'ttm'],
    ['roe-ex-chart', 'roe_ex', 'ratio', 'percent', 'ttm'],
    ['debt-ratio-chart', 'debt_ratio', 'ratio', 'percent', 'point'],
    ['ocf-chart', 'ocf', 'cash', 'amount', 'ttm'],
    ['free-cf-chart', 'free_cf', 'cash', 'amount', 'ttm'],
    ['capex-chart', 'capex', 'cash', 'amount', 'ttm'],
    ['goodwill-chart', 'goodwill', 'asset', 'amount', 'point'],
    ['accounts-receivable-chart', 'accounts_receivable', 'asset', 'amount', 'point'],
    ['inventory-chart', 'inventory', 'asset', 'amount', 'point'],
  ];

  const METRIC_LINEAGE = {
    revenue: { label: '营业收入', basis: 'TTM', unit: '亿元', formula: '本期累计营收 + 上年年报营收 − 上年同期累计营收' },
    revenue_growth: { label: '营收增长率', basis: 'TTM', unit: '%', formula: '本期 TTM 营收 ÷ 上期 TTM 营收 − 1' },
    net_profit: { label: '归母净利润', basis: 'TTM', unit: '亿元', formula: '本期累计利润 + 上年年报利润 − 上年同期累计利润' },
    ex_net_profit: { label: '扣非归母净利润', basis: 'TTM', unit: '亿元', formula: '本期累计扣非利润 + 上年年报扣非利润 − 上年同期累计扣非利润' },
    gross_margin: { label: '毛利率', basis: 'TTM', unit: '%', formula: 'TTM 毛利 ÷ TTM 营收' }, net_margin: { label: '净利率', basis: 'TTM', unit: '%', formula: 'TTM 归母净利润 ÷ TTM 营收' },
    roe_ex: { label: '扣非 ROE', basis: 'TTM', unit: '%', formula: 'TTM 扣非归母净利润 ÷ 最新期末权益' },
    ocf: { label: '经营现金流', basis: 'TTM', unit: '亿元', formula: '本期累计经营现金流 + 上年年报 − 上年同期累计' }, free_cf: { label: '自由现金流', basis: 'TTM', unit: '亿元', formula: 'TTM 经营现金流 − TTM 资本开支' }, capex: { label: '资本开支', basis: 'TTM', unit: '亿元', formula: '本期累计资本开支 + 上年年报 − 上年同期累计' },
    debt_ratio: { label: '资产负债率', basis: '非TTM', unit: '%', formula: '最新期末总负债 ÷ 最新期末总资产', reason: '资产负债率是资产负债表时点比例，跨期相加没有经济含义。' },
    goodwill: { label: '商誉', basis: '非TTM', unit: '亿元', formula: '最新期末商誉账面余额', reason: '商誉是资产负债表时点余额，不能滚动为 TTM。' },
    accounts_receivable: { label: '应收账款', basis: '非TTM', unit: '亿元', formula: '最新期末应收账款余额', reason: '应收账款是资产负债表时点余额，不能滚动为 TTM。' },
    inventory: { label: '库存', basis: '非TTM', unit: '亿元', formula: '最新期末存货余额', reason: '存货是资产负债表时点余额，不能滚动为 TTM。' },
  };

  function showMetricLineage(metricKey) {
    const dialog = document.getElementById('metric-lineage-dialog'); const content = document.getElementById('metric-lineage-content');
    const definition = METRIC_LINEAGE[metricKey]; const payload = state.financialPayload;
    if (!dialog || !content || !definition || !payload) return;
    const period = String(payload.quarterly_monitor?.latest_period || payload.latest_report?.period || '—');
    const ttm = buildLatestTTMReport(payload.reports, payload.quarterly_monitor);
    const metric = metricKey === 'revenue_growth' ? 'revenue_yoy' : metricKey;
    const source = definition.basis === 'TTM' ? ttm?.metrics : payload.latest_report?.metrics;
    const rawValue = Number(source?.[metric]);
    const value = Number.isFinite(rawValue) ? (definition.unit === '亿元' ? `${(rawValue / 1e8).toFixed(2)} 亿元` : `${rawValue.toFixed(2)}%`) : '数据不足';
    const inputs = definition.basis === 'TTM'
      ? `${period}、${Number(period.slice(0, 4)) - 1}A、${Number(period.slice(0, 4)) - 1}${period.slice(4)}`
      : period;
    content.innerHTML = `<h3>${escapeHtml(definition.label)}｜指标口径与数据血缘</h3><dl><dt>当前显示值</dt><dd>${escapeHtml(value)}（${escapeHtml(interimPeriodLabel(period, definition.basis))}）</dd><dt>计算公式</dt><dd>${escapeHtml(definition.formula)}</dd><dt>使用报告期</dt><dd>${escapeHtml(inputs)}</dd><dt>为何不适用 TTM</dt><dd>${escapeHtml(definition.reason || '适用 TTM：该指标为期间流量或由期间流量派生。')}</dd></dl>`;
    dialog.showModal();
  }

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
    const basicMarket = document.getElementById('basic-market-grid');
    if (basicMarket) { basicMarket.innerHTML = '<div class="analysis-metric-status">加载基础行情…</div>'; document.getElementById('basic-market-period').textContent = '加载中'; }
    renderCompositeFinancialHealth(null);
    renderFinancialReversalBadge(null);
    state.reportReleasePriceTrend = null;
    renderReportReleasePricePerformance(null);
    renderHealthComparisonTable(null, null);
    renderValuationPerformanceLinkage(null, null, null);
    renderIndustryFinancialPosition(null);
    renderLatestReportChanges(null);
    renderHealthMetrics(null);
    renderHealthQuestions(null);
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
      const supplementaryRequests = Promise.all([
        fetch(`/api/relative-valuation?market=${encodeURIComponent(stock.market)}&symbol=${encodeURIComponent(stock.symbol)}`, { signal: controller.signal })
          .then(async (response) => { const body = await response.json(); return response.ok && body.ok ? body : null; })
          .catch((error) => error.name === 'AbortError' ? Promise.reject(error) : null),
        fetch(`/api/stock-profile?symbol=${encodeURIComponent(stock.symbol)}`, { signal: controller.signal })
          .then(async (response) => { const body = await response.json(); return response.ok && body.ok ? body : null; })
          .catch((error) => error.name === 'AbortError' ? Promise.reject(error) : null),
        fetch(`/api/stock-price-percentile?symbol=${encodeURIComponent(stock.symbol)}&years=5`, { signal: controller.signal })
          .then(async (response) => { const body = await response.json(); return response.ok && body.ok ? body : null; })
          .catch((error) => error.name === 'AbortError' ? Promise.reject(error) : null),
        fetch(`/api/stock-pe-history?symbol=${encodeURIComponent(stock.symbol)}`, { signal: controller.signal })
          .then(async (response) => { const body = await response.json(); return response.ok && body.ok ? body : null; })
          .catch((error) => error.name === 'AbortError' ? Promise.reject(error) : null),
      ]);
      const payload = cacheIsFresh
        ? cached.payload
        : await fetch(`/api/stock-score-report-history?market=${encodeURIComponent(stock.market)}&symbol=${encodeURIComponent(stock.symbol)}&years=6`, { signal: controller.signal }).then(async (response) => {
          const body = await response.json();
          if (!response.ok || !body.ok) throw new Error(body?.error?.message || `HTTP ${response.status}`);
          putFinancialCache(cacheKey, body);
          return body;
        });
      const [valuation, profile, pricePercentile, peHistory] = await supplementaryRequests;
      if (financialRequestId !== state.financialRequestId) return;
      state.financialPayload = payload;
      state.stockProfile = profile;
      renderNicheLeaderBadge(profile);
      renderBasicMarket(valuation, payload.reports, profile, pricePercentile, peHistory, payload.quarterly_monitor, payload.industry_financial_position);
      renderCompositeFinancialHealth(payload.composite_financial_health);
      renderFinancialReversalBadge(payload.financial_reversal);
      state.reportReleasePriceTrend = payload.report_release_price_trend || null;
      renderReportReleasePricePerformance(payload.report_release_price_performance);
      renderValuationPerformanceLinkage(valuation, payload.health, payload.quarterly_monitor);
      renderHealthComparisonTable(payload.health, payload.quarterly_monitor);
      renderIndustryFinancialPosition(payload.industry_financial_position);
      renderLatestReportChanges(payload.quarterly_monitor);
      renderHealthMetrics(payload.health, payload.quarterly_monitor, payload.latest_report);
      renderHealthQuestions(payload.health);
      const annualPeriods = new Set(payload.health?.periods || []);
      const evidenceReports = payload.reports.filter((row) => String(row?.period || '').endsWith('A'));
      const healthEvidenceReports = annualPeriods.size ? evidenceReports.filter((row) => annualPeriods.has(String(row.period))) : evidenceReports;
      const pointInTimeReports = appendLatestQuarter(healthEvidenceReports, payload.reports);
      const latestTTMReport = buildLatestTTMReport(payload.reports, payload.quarterly_monitor);
      const ttmReports = latestTTMReport ? [...healthEvidenceReports, latestTTMReport] : pointInTimeReports;
      for (const [id, metric, variant, display, interimBasis] of METRIC_CHARTS) {
        renderAnnualBars(id, interimBasis === 'ttm' ? ttmReports : pointInTimeReports, metric, variant, display);
      }
      renderYoYGrowthBars('revenue-growth-chart', ttmReports, 'revenue', annualPeriods, payload.reports);
    } catch (error) {
      if (financialRequestId !== state.financialRequestId) return;
      if (error.name === 'AbortError') return;
      renderHealthComparisonTable(null, null);
      renderLatestReportChanges(null);
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
  document.getElementById('health-question-grid')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-score-source="annual"]');
    if (button) showHealthScoreDetail('annual', button.dataset.scoreCode);
  });
  document.querySelectorAll('.analysis-metric-card').forEach((card) => {
    const chart = card.querySelector('[id$="-chart"]'); const metric = METRIC_CHARTS.find(([id]) => id === chart?.id)?.[1] || (chart?.id === 'revenue-growth-chart' ? 'revenue_growth' : null);
    const heading = card.querySelector('.analysis-metric-heading h2');
    if (metric && heading) heading.innerHTML = `<button type="button" class="metric-lineage-trigger" data-metric-lineage="${metric}" title="查看指标口径与数据血缘">${heading.textContent}</button>`;
  });
  document.addEventListener('click', (event) => { const trigger = event.target.closest('[data-metric-lineage]'); if (trigger) showMetricLineage(trigger.dataset.metricLineage); });
  document.addEventListener('click', (event) => { if (event.target.closest('[data-stock-kline-history]')) showStockKlineHistory(); });
  document.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-stock-kline-history]')) { event.preventDefault(); showStockKlineHistory(); } });
  const stockKlineDialog=document.getElementById('stock-kline-dialog'); stockKlineDialog?.querySelector('.stock-kline-close')?.addEventListener('click',()=>stockKlineDialog.close()); stockKlineDialog?.addEventListener('click',(event)=>{if(event.target===stockKlineDialog)stockKlineDialog.close();});
  document.addEventListener('click', (event) => { if (event.target.closest('[data-report-release-price-trend]')) showReportReleasePriceTrend(); });
  document.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-report-release-price-trend]')) { event.preventDefault(); showReportReleasePriceTrend(); } });
  const reportReleaseTrendDialog = document.getElementById('report-release-price-trend-dialog'); reportReleaseTrendDialog?.querySelector('.report-release-price-trend-close')?.addEventListener('click', () => reportReleaseTrendDialog.close()); reportReleaseTrendDialog?.addEventListener('click', (event) => { if (event.target === reportReleaseTrendDialog) reportReleaseTrendDialog.close(); });
  document.addEventListener('click', (event) => { if (event.target.closest('[data-niche-leader-detail]')) showNicheLeaderDetail(); });
  document.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-niche-leader-detail]')) { event.preventDefault(); showNicheLeaderDetail(); } });
  const nicheLeaderDialog = document.getElementById('niche-leader-dialog');
  nicheLeaderDialog?.querySelector('.niche-leader-close')?.addEventListener('click', () => nicheLeaderDialog.close());
  nicheLeaderDialog?.addEventListener('click', (event) => { if (event.target === nicheLeaderDialog) nicheLeaderDialog.close(); });
  document.addEventListener('click', (event) => { if (event.target.closest('[data-stock-pe-history]')) showStockPeHistory(); });
  document.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-stock-pe-history]')) { event.preventDefault(); showStockPeHistory(); } });
  const stockPeHistoryDialog = document.getElementById('stock-pe-history-dialog');
  stockPeHistoryDialog?.querySelector('.stock-pe-history-close')?.addEventListener('click', () => stockPeHistoryDialog.close());
  stockPeHistoryDialog?.addEventListener('click', (event) => { if (event.target === stockPeHistoryDialog) stockPeHistoryDialog.close(); });
  document.addEventListener('click', (event) => { if (event.target.closest('[data-industry-valuation-history]')) showIndustryValuationHistory(state.industryValuation); });
  document.addEventListener('click', (event) => { if (event.target.closest('[data-industry-valuation-peers]')) showIndustryValuationPeers(); });
  document.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-industry-valuation-peers]')) { event.preventDefault(); showIndustryValuationPeers(); } });
  document.addEventListener('click', (event) => { if (event.target.closest('[data-industry-health-peers]')) showIndustryHealthPeers(); });
  document.addEventListener('click', (event) => { const trigger = event.target.closest('[data-industry-metric]'); if (trigger) showIndustryMetricPeers(trigger.dataset.industryMetric, trigger); });
  document.addEventListener('keydown', (event) => { const trigger = event.target.closest('[data-industry-metric]'); if ((event.key === 'Enter' || event.key === ' ') && trigger) { event.preventDefault(); showIndustryMetricPeers(trigger.dataset.industryMetric, trigger); } });
  document.addEventListener('click', (event) => { const stock = event.target.closest('[data-open-stock]')?.dataset.openStock; if (!stock) return; const [market, symbol] = stock.split(':'); window.location.href = `stock-analysis.html?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`; });
  const industryMetricDialog = document.getElementById('industry-metric-peer-dialog');
  industryMetricDialog?.querySelector('.industry-metric-peer-close')?.addEventListener('click', () => industryMetricDialog.close());
  industryMetricDialog?.addEventListener('click', (event) => { if (event.target === industryMetricDialog) industryMetricDialog.close(); });
  industryMetricDialog?.addEventListener('close', () => { state.industryMetricPeerTrigger?.focus(); state.industryMetricPeerTrigger = null; });
  document.getElementById('industry-metric-peer-table')?.addEventListener('click', (event) => { const header = event.target.closest('[data-industry-metric-sort]'); if (!header || !state.industryMetricPeers) return; const key = header.dataset.industryMetricSort; const old = state.industryMetricPeerSort; state.industryMetricPeerSort = { key, direction: old.key === key ? -old.direction : 1 }; renderIndustryMetricPeers(state.industryMetricPeers); });
  document.addEventListener('keydown', (event) => { if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-industry-health-peers]')) { event.preventDefault(); showIndustryHealthPeers(); } });
  const industryHealthPeerDialog = document.getElementById('industry-health-peer-dialog');
  industryHealthPeerDialog?.querySelector('.industry-health-peer-close')?.addEventListener('click', () => industryHealthPeerDialog.close());
  industryHealthPeerDialog?.addEventListener('click', (event) => { if (event.target === industryHealthPeerDialog) industryHealthPeerDialog.close(); });
  document.querySelectorAll('[data-health-peer-view]').forEach((button) => button.addEventListener('click', () => { state.industryHealthPeerView = button.dataset.healthPeerView; state.industryHealthPeerSort = { key: 'score', direction: -1 }; renderIndustryHealthPeers(); }));
  document.querySelectorAll('[data-health-peer-sort]').forEach((header) => header.addEventListener('click', () => { const key = header.dataset.healthPeerSort; state.industryHealthPeerSort = { key, direction: state.industryHealthPeerSort.key === key ? -state.industryHealthPeerSort.direction : -1 }; renderIndustryHealthPeers(); }));
  const industryPeerDialog = document.getElementById('industry-valuation-peer-dialog');
  industryPeerDialog?.querySelector('.industry-valuation-peer-close')?.addEventListener('click', () => industryPeerDialog.close());
  industryPeerDialog?.addEventListener('click', (event) => { if (event.target === industryPeerDialog) industryPeerDialog.close(); });
  document.querySelectorAll('[data-peer-sort]').forEach((header) => header.addEventListener('click', () => { const key = header.dataset.peerSort; state.industryPeerSort = { key, direction: state.industryPeerSort.key === key ? -state.industryPeerSort.direction : 1 }; renderIndustryValuationPeers(); }));
  const industryValuationHistoryDialog = document.getElementById('industry-valuation-history-dialog');
  industryValuationHistoryDialog?.querySelector('.industry-valuation-history-close')?.addEventListener('click', () => industryValuationHistoryDialog.close());
  industryValuationHistoryDialog?.addEventListener('click', (event) => { if (event.target === industryValuationHistoryDialog) industryValuationHistoryDialog.close(); });
  const lineageDialog = document.getElementById('metric-lineage-dialog');
  lineageDialog?.addEventListener('click', (event) => { if (event.target === lineageDialog || event.target.closest('.metric-lineage-close')) lineageDialog.close(); });

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
