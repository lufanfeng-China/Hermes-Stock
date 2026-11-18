(() => {
  'use strict';
  // This adapter changes only the preview's DOM. The original data renderer and APIs remain shared.
  const form = document.getElementById('stock-analysis-search-form');
  const main = document.querySelector('main.app-shell');
  if (!form || !main) return;
  const hub = document.createElement('div');
  hub.id = 'preview-hub';
  hub.innerHTML = `
    <section class="preview-identity" aria-label="当前股票">
      <div><h2 id="preview-company">选择股票开始阅读</h2>
        <p id="preview-freshness"></p></div>
      <a class="preview-original" href="/stock-analysis-legacy.html" id="preview-original-link">查看旧版页面 ↗</a>
    </section>
    <nav class="preview-tabs" role="tablist" aria-label="股票分析专题">
      <button type="button" role="tab" id="preview-tab-overview" aria-controls="preview-panel-overview" aria-selected="true" data-preview-tab="overview">01 · 总览</button>
      <button type="button" role="tab" id="preview-tab-financial" aria-controls="preview-panel-financial" aria-selected="false" tabindex="-1" data-preview-tab="financial">02 · 财务</button>
      <button type="button" role="tab" id="preview-tab-valuation" aria-controls="preview-panel-valuation" aria-selected="false" tabindex="-1" data-preview-tab="valuation">03 · 估值与同行</button>
      <button type="button" role="tab" id="preview-tab-technical" aria-controls="preview-panel-technical" aria-selected="false" tabindex="-1" data-preview-tab="technical">04 · 走势与形态</button>
    </nav>
    <section id="preview-panel-overview" class="preview-panel" role="tabpanel" aria-labelledby="preview-tab-overview" tabindex="0">
      <section class="preview-overview-block" aria-labelledby="preview-financial-heading">
        <header class="preview-block-header">
          <h2 id="preview-financial-heading"><span class="preview-bars-icon" aria-hidden="true"><i></i><i></i><i></i><i></i></span>财务健康概览</h2>
          <span class="preview-block-period" id="preview-financial-period"></span>
        </header>
        <div class="preview-financial-layout">
          <button type="button" class="preview-gauge" data-preview-target="financial" aria-label="查看财务健康详情">
            <span class="preview-gauge-chart">
              <svg viewBox="0 0 240 170" aria-hidden="true" focusable="false"><defs><linearGradient id="preview-gauge-gradient" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#18cfcc"/><stop offset="55%" stop-color="#83df8d"/><stop offset="85%" stop-color="#ffdc67"/><stop offset="100%" stop-color="#ffc267"/></linearGradient></defs><path class="preview-gauge-track" d="M 24 142 A 96 96 0 0 1 216 142"/><path id="preview-gauge-progress" class="preview-gauge-progress" d="M 24 142 A 96 96 0 0 1 216 142" pathLength="100"/><circle id="preview-gauge-dot" class="preview-gauge-dot" cx="24" cy="142" r="8" hidden/></svg>
              <span class="preview-red-flags" id="preview-red-flags" title="年报红旗数量尚未评估"><b id="preview-red-flag-count">—</b></span>
              <strong id="preview-gauge-value">—</strong><span id="preview-gauge-scale"></span>
            </span>
            <span class="preview-gauge-label">财务健康综合分</span>
          </button>
          <div class="preview-financial-main">
            <div class="preview-summary-grid" id="preview-financial-summary"></div>
            <div class="preview-summary-grid preview-financial-secondary" id="preview-financial-secondary"></div>
          </div>
        </div>
        <section class="preview-eps-section" aria-labelledby="preview-eps-title">
          <div class="preview-eps-heading"><h3 id="preview-eps-title">每股收益 · 单季度</h3><span id="preview-quarter-basis">累计基本 EPS 逐季差分 · 元/股 · 未复权</span></div>
          <label class="preview-quarter-picker">图表指标
            <select id="preview-quarter-metric" aria-label="选择单季度图表指标">
              <option value="basic_eps_cumulative">每股收益</option>
              <option value="revenue_cumulative_verified">营业收入</option>
              <option value="net_profit">归母净利润</option>
              <option value="ex_net_profit">扣归净利润</option>
              <option value="ocf">经营现金流金额</option>
              <option value="capex">资本开支</option>
              <option value="free_cf">自由现金流</option>
            </select>
          </label>
          <div class="preview-eps-scroll" id="preview-eps-chart" role="img" aria-label="选择股票后显示单季度财务指标柱状图">选择股票后加载。</div>
        </section>
      </section>
      <section class="preview-overview-block" aria-labelledby="preview-market-heading">
        <header class="preview-block-header">
          <h2 id="preview-market-heading"><span class="preview-bars-icon" aria-hidden="true"><i></i><i></i><i></i><i></i></span>行情 · 估值 · 结构</h2>
          <span class="preview-block-period" id="preview-market-period"></span>
        </header>
        <div class="preview-summary-grid" id="preview-market-summary"></div>
      </section>
    </section>
    <section id="preview-panel-financial" class="preview-panel" role="tabpanel" aria-labelledby="preview-tab-financial" tabindex="0" hidden>
      <div id="preview-financial-content"></div>
      <div class="preview-charts" id="preview-financial-charts"><h3>经营指标与时间序列</h3></div>
    </section>
    <section id="preview-panel-valuation" class="preview-panel" role="tabpanel" aria-labelledby="preview-tab-valuation" tabindex="0" hidden>
      <div id="preview-valuation-summary" class="preview-summary-grid"></div>
      <div id="preview-valuation-content"></div>
    </section>
    <section id="preview-panel-technical" class="preview-panel" role="tabpanel" aria-labelledby="preview-tab-technical" tabindex="0" hidden>
      <div id="preview-technical-content"></div>
    </section>
    <dialog id="preview-valuation-trend-dialog" class="preview-valuation-trend-dialog" aria-labelledby="preview-valuation-trend-title">
      <button type="button" class="preview-valuation-trend-close" aria-label="关闭历史趋势">关闭 ×</button>
      <h3 id="preview-valuation-trend-title">历史趋势</h3>
      <p id="preview-valuation-trend-status" role="status"></p>
      <svg id="preview-valuation-trend-chart" viewBox="0 0 920 340" role="img" aria-label="分位数历史趋势"></svg>
      <p id="preview-valuation-trend-hover" aria-live="polite"></p>
    </dialog>`;
  form.after(hub);
  // Peer-stock rows in shared dialogs should remain in this preview, not jump to the original page.
  document.addEventListener('click', (event) => {
    const peer = event.target.closest('[data-open-stock]');
    if (!peer) return;
    const [market, symbol] = (peer.dataset.openStock || '').split(':');
    if (!market || !symbol) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    location.href = `/stock-analysis.html?${new URLSearchParams({ market, symbol })}`;
  }, true);
  const byId = (id) => document.getElementById(id);
  const move = (node, target) => { if (node) target.append(node); };
  const financial = byId('financial-health-kpi');
  const valuation = byId('preview-valuation-content');
  const technical = byId('preview-technical-content');
  const financialContent = byId('preview-financial-content');
  const cards = main.querySelector('section.analysis-metric-grid');
  const basic = byId('basic-market-section');
  const relative = byId('market-relative-strength-section');
  const swing = byId('swing-structure-section');
  const wyckoff = byId('wyckoff-observation')?.closest('section');

  // Preserve the original nodes and IDs so all existing renderers, dialogs and event handlers work.
  move(financial?.querySelector('.health-comparison-section'), financialContent);
  move(byId('financial-health-composite'), financialContent);
  // The shared renderer requires this node; suppress only its preview presentation.
  byId('financial-health-composite-risk')?.setAttribute('hidden', '');
  move(byId('health-question-grid')?.closest('section'), financialContent);
  const series = byId('health-derived')?.closest('section');
  move(series, financialContent);
  move(byId('latest-report-change-summary')?.closest('section'), financialContent);
  move(byId('valuation-performance-linkage')?.closest('section'), valuation);
  move(byId('industry-financial-position')?.closest('section'), valuation);
  financial?.remove();

  const fullMarket = document.createElement('details');
  fullMarket.className = 'preview-market-fold';
  fullMarket.innerHTML = '<summary>展开其余基础行情与估值指标 <span>旧季度PE分位已由上方日频卡替代</span></summary>';
  move(basic, fullMarket);
  valuation.append(fullMarket);
  const legacyPeGrid = byId('basic-market-grid');
  const hideLegacyQuarterlyPe = () => {
    legacyPeGrid?.querySelectorAll('.basic-market-card').forEach((card) => {
      if (card.querySelector('strong')?.textContent.trim() === 'PE 5年分位') card.hidden = true;
    });
  };
  if (legacyPeGrid) {
    new MutationObserver(hideLegacyQuarterlyPe).observe(legacyPeGrid, { childList: true });
    hideLegacyQuarterlyPe();
  }
  move(relative, technical);
  move(swing, technical);
  move(wyckoff, technical);

  // Keep every original chart, but open only the four most useful charts by default.
  const chartArea = byId('preview-financial-charts');
  const chartNote = cards?.querySelector('.analysis-metric-basis-note');
  if (chartNote) move(chartNote, chartArea);
  const chartGroups = [
    ['先看四张关键图', ['revenue', 'net_profit', 'ocf', 'free_cf'], true],
    ['成长与盈利能力 · 5 张', ['revenue_growth', 'ex_net_profit', 'gross_margin', 'net_margin', 'roe_ex'], false],
    ['投入、资产与营运 · 5 张', ['capex', 'debt_ratio', 'goodwill', 'accounts_receivable', 'inventory'], false],
  ];
  chartGroups.forEach(([title, keys, open]) => {
    const fold = document.createElement('details');
    fold.className = 'preview-chart-fold';
    fold.open = open;
    const summary = document.createElement('summary');
    summary.textContent = title;
    fold.append(summary);
    const grid = document.createElement('div');
    grid.className = 'analysis-metric-grid';
    keys.forEach((key) => move(cards?.querySelector(`.analysis-metric-card[data-industry-metric="${key}"]`), grid));
    fold.append(grid);
    chartArea.append(fold);
  });
  cards?.remove();

  // Methodology stays one click away; risk and data date remain exposed beside results.
  main.querySelectorAll('.basic-market-note,.health-comparison-note,.latest-report-change-note').forEach((note) => {
    const details = document.createElement('details');
    details.className = 'preview-method';
    const summary = document.createElement('summary');
    summary.textContent = '查看口径与限制';
    note.replaceWith(details);
    details.append(summary, note);
  });

  const wyckoffToggle = document.createElement('button');
  wyckoffToggle.type = 'button';
  wyckoffToggle.className = 'preview-event-toggle';
  wyckoffToggle.hidden = true;
  wyckoff?.append(wyckoffToggle);
  let showAllEvents = false;
  const stockInput = byId('stock-input');
  const stockFromUrl = new URLSearchParams(location.search);
  const originalLink = byId('preview-original-link');
  let pendingSummary = false;
  let overviewFinancialPayload = null;
  let overviewFinancialRequest = 0;
  let marketRequest = 0;
  let marketPosition = null;
  let marketValuation = null;
  let marketDailyPe = null;
  let turnoverTrend = null;
  let industryTemperature = null;
  let industryTemperatureRequest = null;
  let selectedStock = null;
  function loadMarketPosition(stock) {
    const request = ++marketRequest;
    marketPosition = null;
    marketValuation = null;
    marketDailyPe = null;
    turnoverTrend = null;
    industryTemperature = null;
    const params = new URLSearchParams({ market: stock.market, symbol: stock.symbol });
    const get = (path, extra = '') => fetch(`${path}?${params}${extra}`).then(async (response) => {
      const payload = await response.json();
      return response.ok && payload.ok ? payload : null;
    }).catch(() => null);
    get('/api/preview-qfq-price-position').then((payload) => {
      if (request !== marketRequest) return;
      marketPosition = payload;
      queueSummary();
      if (!payload?.as_of_date) return;
      get('/api/stock-filter-turnover-trend', `&as_of_date=${encodeURIComponent(payload.as_of_date)}`).then((trend) => {
        if (request !== marketRequest) return;
        turnoverTrend = trend;
        queueSummary();
      });
    });
    get('/api/relative-valuation').then((payload) => {
      if (request !== marketRequest) return;
      marketValuation = payload;
      queueSummary();
    });
    get('/api/stock-daily-pe-percentile').then((payload) => {
      if (request !== marketRequest) return;
      marketDailyPe = payload;
      queueSummary();
    });
    if (!industryTemperatureRequest) {
      industryTemperatureRequest = fetch('/api/concept-temperature?scope=industry&window=10')
        .then(async (response) => {
          const payload = await response.json();
          return response.ok && payload.ok && payload.scope === 'industry' ? payload : null;
        })
        .catch(() => { industryTemperatureRequest = null; return null; });
    }
    industryTemperatureRequest.then((payload) => {
      if (request !== marketRequest) return;
      industryTemperature = payload;
      queueSummary();
    });
  }
  function financialMetric(value) {
    return value !== null && value !== undefined && Number.isFinite(Number(value))
      ? `${Number(value).toFixed(2)}%` : '—';
  }
  function negativeFinancialTone(value) {
    return value !== null && value !== undefined && Number.isFinite(Number(value)) && Number(value) < 0 ? 'risk' : '';
  }
  const quarterMetrics = {
    basic_eps_cumulative: { label: '每股收益', unit: '元/股', basis: '累计基本 EPS 逐季差分 · 未复权', scale: 1 },
    revenue_cumulative_verified: { label: '营业收入', unit: '亿元', basis: '法定累计营收逐季差分；缺少累计口径时留空', scale: 1e8 },
    net_profit: { label: '归母净利润', unit: '亿元', basis: '财报累计归母净利润逐季差分', scale: 1e8 },
    ex_net_profit: { label: '扣归净利润', unit: '亿元', basis: '财报累计扣非归母净利润逐季差分', scale: 1e8 },
    ocf: { label: '经营现金流金额', unit: '亿元', basis: '累计经营活动现金流净额逐季差分', scale: 1e8 },
    capex: { label: '资本开支', unit: '亿元', basis: '累计购建长期资产所付现金逐季差分', scale: 1e8 },
    free_cf: { label: '自由现金流', unit: '亿元', basis: '累计经营现金流减累计资本开支，逐季差分', scale: 1e8 },
  };
  function renderQuarterChart(payload) {
    const root = byId('preview-eps-chart');
    const metricKey = byId('preview-quarter-metric').value;
    const metric = quarterMetrics[metricKey] || quarterMetrics.basic_eps_cumulative;
    byId('preview-eps-title').textContent = `${metric.label} · 单季度`;
    byId('preview-quarter-basis').textContent = `${metric.basis} · ${metric.unit}`;
    const reports = Array.isArray(payload?.reports) ? payload.reports : [];
    const byPeriod = new Map(reports.map((row) => [String(row.period || ''), row]));
    const annualYears = [...new Set(reports.filter((row) => /^\d{4}A$/.test(String(row.period || '')))
      .map((row) => Number(row.period.slice(0, 4))))].sort((a, b) => a - b).slice(-5);
    const groups = annualYears.map((year) => ({ year, quarters: [1, 2, 3, 4] }));
    const current = reports.filter((row) => /^\d{4}Q[123]$/.test(String(row.period || ''))
      && Number(row.period.slice(0, 4)) > (annualYears.at(-1) || 0))
      .sort((a, b) => a.period.localeCompare(b.period)).at(-1);
    if (current) {
      const latestQuarter = Number(current.period.at(-1));
      groups.push({ year: Number(current.period.slice(0, 4)), quarters: Array.from({ length: latestQuarter }, (_, i) => i + 1), current: true });
    }
    const cumulative = (period) => {
      const raw = byPeriod.get(period)?.metrics?.[metricKey];
      return raw !== null && raw !== undefined && Number.isFinite(Number(raw)) ? Number(raw) / metric.scale : null;
    };
    const entries = groups.flatMap((group, groupIndex) => group.quarters.map((quarter) => {
      const year = group.year;
      const currentPeriod = `${year}${quarter === 4 ? 'A' : `Q${quarter}`}`;
      const priorPeriod = quarter === 1 ? null : `${year}Q${quarter - 1}`;
      const end = cumulative(currentPeriod), start = priorPeriod ? cumulative(priorPeriod) : 0;
      return { year, quarter, groupIndex, current: Boolean(group.current), value: end === null || start === null ? null : end - start };
    }));
    const values = entries.map((entry) => entry.value).filter((value) => value !== null);
    if (!groups.length || !values.length) {
      root.textContent = `暂无可用的累计${metric.label}，不能拆分单季度；缺失期间不会填零。`;
      root.setAttribute('aria-label', root.textContent);
      return;
    }
    const barWidth = 22, quarterGap = 6, groupGap = 40, groupWidth = 4 * barWidth + 3 * quarterGap;
    const width = 120 + groups.length * groupWidth + (groups.length - 1) * groupGap;
    const top = 30, bottom = 204, plotHeight = bottom - top;
    const low = Math.min(0, ...values), high = Math.max(0, ...values);
    const span = Math.max(high - low, 0.01), padding = span * .1;
    const min = low - (low < 0 ? padding : high === 0 ? .1 : 0);
    const max = high + (high > 0 ? padding : low === 0 ? .1 : 0);
    const y = (value) => bottom - (value - min) / (max - min) * plotHeight;
    const baseline = y(0);
    const fmt = (value) => `${value.toFixed(value !== 0 && Math.abs(value) < .01 ? 4 : 2)} ${metric.unit}`;
    const axisNumber = (value) => value.toFixed(Math.abs(value) < 1 && value !== 0 ? 2 : 1);
    const axes = [min, 0, max].filter((v, i, arr) => i === 0 || v !== arr[i - 1]).map((v) => `<line x1="68" y1="${y(v)}" x2="${width - 16}" y2="${y(v)}" stroke="${v === 0 ? '#5f9aaf' : '#20485a'}" stroke-dasharray="${v === 0 ? '' : '4 5'}"/><text x="60" y="${y(v) + 4}" text-anchor="end" fill="#9fbbc9" font-size="11">${axisNumber(v)}</text>`).join('');
    const bars = entries.map((entry) => {
      const x = 76 + entry.groupIndex * (groupWidth + groupGap) + (entry.quarter - 1) * (barWidth + quarterGap);
      const period = `${entry.year}Q${entry.quarter}`;
      const label = `<text x="${x + barWidth / 2}" y="226" text-anchor="middle" fill="#9fbbc9" font-size="11">Q${entry.quarter}</text>`;
      if (entry.value === null) return `<title>${period}：缺少本季或上季累计${metric.label}</title>${label}`;
      const endY = y(entry.value), height = Math.max(2, Math.abs(endY - baseline));
      return `<rect x="${x}" y="${entry.value >= 0 ? baseline - height : baseline}" width="${barWidth}" height="${height}" rx="3" fill="${entry.value < 0 ? '#3bd0a8' : '#f26b76'}"><title>${period}：${fmt(entry.value)}（累计差分）</title></rect>${label}`;
    }).join('');
    const labels = groups.map((group, index) => {
      const occupiedWidth = group.quarters.length * barWidth + (group.quarters.length - 1) * quarterGap;
      const center = 76 + index * (groupWidth + groupGap) + occupiedWidth / 2;
      return `<text x="${center}" y="254" text-anchor="middle" fill="${group.current ? '#ffcb75' : '#e2edf4'}" font-size="13" font-weight="700">${group.year}${group.current ? ' · 最新' : ''}</text>`;
    }).join('');
    root.innerHTML = `<svg class="preview-eps-svg" viewBox="0 0 ${width} 270" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">${axes}${bars}${labels}</svg>`;
    root.setAttribute('aria-label', `${metric.label}单季度（累计差分，${metric.unit}）：${entries.map((entry) => `${entry.year}年Q${entry.quarter} ${entry.value === null ? '缺失' : fmt(entry.value)}`).join('；')}`);
  }
  byId('preview-quarter-metric').addEventListener('change', () => {
    if (overviewFinancialPayload) renderQuarterChart(overviewFinancialPayload);
  });
  function loadOverviewFinancial(stock) {
    const request = ++overviewFinancialRequest;
    overviewFinancialPayload = null;
    byId('preview-eps-chart').textContent = '正在加载单季度财务指标…';
    queueSummary();
    fetch(`/api/stock-score-report-history?${new URLSearchParams({ market: stock.market, symbol: stock.symbol, years: '6' })}`)
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload?.error?.message || `HTTP ${response.status}`);
        return payload;
      })
      .then((payload) => { if (request !== overviewFinancialRequest) return; overviewFinancialPayload = payload; renderQuarterChart(payload); queueSummary(); })
      .catch(() => { if (request !== overviewFinancialRequest) return; byId('preview-eps-chart').textContent = '单季度财务指标加载失败，请重新查询。'; queueSummary(); });
  }
  function cardData(root, label) {
    const card = [...root?.querySelectorAll('.basic-market-card') || []]
      .find((element) => element.querySelector('strong')?.textContent.trim() === label);
    return card ? { value: card.querySelector('span')?.textContent.trim() || '—', status: card.querySelector('em')?.textContent.trim() || '', state: [...card.classList].find((x) => ['strong', 'watch', 'risk'].includes(x)) || '' } : null;
  }
  const summaryIcons = {
    annual: '<path d="m3 8 9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 18l9 5 9-5"/>',
    quarter: '<path d="M2 13h5l3-9 4 17 3-8h5"/>',
    revenue: '<path d="M4 20V14h4v6M10 20V10h4v10M16 20V5h4v15M3 20h18"/>',
    exProfit: '<path d="M3 19h18M5 16l5-5 4 3 6-8m-5 0h5v5"/>',
    roe: '<circle cx="12" cy="12" r="9"/><path d="M7 15l3-5 3 3 4-6M14 7h3v3"/>',
    cash: '<path d="M4 8h16v12H4zM4 11h16M8 16h.01M16 16h.01M7 3h10v5"/>',
    margin: '<path d="M4 19h16M6 15l4-5 4 2 4-7M16 5h2v3"/>',
    debt: '<path d="M4 20h16M6 20V9l6-5 6 5v11M9 13h6M9 16h6"/>',
    composite: '<path d="M12 2 3 6v6c0 6 4 9 9 11 5-2 9-5 9-11V6l-9-4Zm0 5v7m0 4h.01"/>',
    price: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v13c0 2 4 3 8 3s8-1 8-3V5M4 9c0 2 4 3 8 3s8-1 8-3M4 14c0 2 4 3 8 3s8-1 8-3"/>',
    pe: '<path d="M3 11 12 2h9v9l-9 10L3 11Zm14-5h.01"/>',
    rps: '<path d="m3 17 7-7 4 4 7-8m-6 0h6v6"/>',
    er: '<path d="M12 3v18M5 6h14M5 6l-3 8h6L5 6Zm14 0-3 8h6l-3-8ZM8 21h8"/>',
    event: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/><path d="m12 12 7-7"/>',
  };
  function summaryCard(label, value, detail, tab, tone = '', icon = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `preview-summary-card ${tone}`;
    button.dataset.previewTarget = tab;
    const heading = document.createElement('span'); heading.className = 'preview-card-heading';
    if (summaryIcons[icon]) {
      const glyph = document.createElement('span'); glyph.className = 'preview-card-icon';
      glyph.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${summaryIcons[icon]}</svg>`;
      heading.append(glyph);
    }
    const title = document.createElement('small'); title.textContent = label;
    heading.append(title);
    const number = document.createElement('strong'); number.textContent = value || '—';
    button.append(heading, number);
    if (detail) {
      const footer = document.createElement('span'); footer.textContent = detail;
      button.append(footer);
    }
    return button;
  }
  function setCards(container, rows) { container.replaceChildren(...rows); }
  function fitStructureCard() {
    const card = byId('preview-market-summary')?.querySelector('.preview-structure-card');
    const value = card?.querySelector('strong');
    if (!value) return;
    value.style.fontSize = '20px';
    const bottom = card.getBoundingClientRect().bottom - parseFloat(getComputedStyle(card).paddingBottom) - 2;
    let size = 20;
    while ((value.getBoundingClientRect().bottom > bottom || value.scrollHeight > bottom - value.getBoundingClientRect().top + 1) && size > 10) {
      size -= 1;
      value.style.fontSize = `${size}px`;
    }
  }
  window.addEventListener('resize', fitStructureCard);
  function scoreRow(index) {
    const tr = byId('health-comparison-body')?.querySelectorAll('tr')[index];
    const cells = tr?.querySelectorAll('td');
    const coverage = cells?.[2]?.textContent.trim() || '—';
    return { label: cells?.[0]?.textContent.trim() || '报告期未知', value: coverage === '0' || coverage === '—' ? '—' : cells?.[1]?.textContent.trim() || '—', coverage };
  }
  function collapseSwingHistory() {
    const points = byId('swing-structure')?.querySelector('.swing-points');
    if (!points || points.closest('.preview-swing-history')) return;
    const fold = document.createElement('details');
    fold.className = 'preview-swing-history preview-chart-fold';
    const summary = document.createElement('summary');
    summary.textContent = '展开确认峰谷历史（各最近 10 条）';
    points.replaceWith(fold);
    fold.append(summary, points);
  }
  if (byId('swing-structure')) {
    new MutationObserver(collapseSwingHistory).observe(byId('swing-structure'), { childList: true });
    collapseSwingHistory();
  }
  function refreshEvents() {
    const list = byId('wyckoff-observation')?.querySelector('.wyckoff-event-list');
    const count = list?.querySelectorAll('.wyckoff-event').length || 0;
    if (!wyckoffToggle) return;
    wyckoffToggle.hidden = count <= 3;
    wyckoff?.classList.toggle('preview-event-compact', count > 3 && !showAllEvents);
    wyckoffToggle.textContent = showAllEvents ? `收起历史事件（共 ${count} 条）` : `查看全部历史事件（共 ${count} 条，默认显示最新 3 条）`;
    wyckoffToggle.setAttribute('aria-expanded', String(showAllEvents));
  }
  function renderSummary() {
    pendingSummary = false;
    const basicGrid = byId('basic-market-grid');
    const relativeGrid = byId('market-relative-strength-grid');
    const annual = scoreRow(0), quarter = scoreRow(1);
    const compositeRaw = byId('financial-health-composite-score')?.textContent.trim() || '—';
    const compositeStatus = byId('financial-health-composite-status')?.textContent.trim() || '数据不足';
    const composite = /数据不足|暂不生成/.test(compositeStatus) ? '—' : compositeRaw;
    const score = Number.parseFloat(composite);
    const scored = composite !== '—' && Number.isFinite(score) && score >= 0 && score <= 100;
    byId('preview-gauge-value').textContent = scored ? String(score) : '—';
    byId('preview-gauge-scale').textContent = scored ? '' : '评分不可用';
    const progress = byId('preview-gauge-progress');
    progress.style.strokeDasharray = `${scored ? score : 0} 100`;
    const dot = byId('preview-gauge-dot');
    dot.toggleAttribute('hidden', !scored);
    if (scored) {
      const point = progress.getPointAtLength(progress.getTotalLength() * score / 100);
      dot.setAttribute('cx', point.x);
      dot.setAttribute('cy', point.y);
    }
    const annualAsOf = byId('basic-market-period')?.textContent.match(/20\d{2}A/)?.[0];
    byId('preview-financial-period').textContent = `年报：${annual.value === '—' ? '评分不可用' : (annualAsOf || annual.label)} ｜ 季度：${quarter.value === '—' ? '评分不可用' : quarter.label}`;
    const annualData = overviewFinancialPayload?.health;
    const flagCoverage = annualData?.red_flag_coverage;
    const flagCount = annualData?.red_flag_count;
    const flagsKnown = Number.isInteger(flagCount) && flagCount >= 0 && Number(flagCoverage?.evaluated) > 0;
    const flagBadge = byId('preview-red-flags');
    byId('preview-red-flag-count').textContent = flagsKnown ? String(flagCount) : '—';
    flagBadge.title = flagsKnown
      ? `${annualData.assessment_track === 'five_year' ? '五年完整年报' : '已披露年报'}已触发 ${flagCount} 项红旗；已评估 ${flagCoverage.evaluated} / ${flagCoverage.total} 项规则${flagCoverage.evaluated < flagCoverage.total ? '；未评估不代表安全' : ''}。点击查看财务详情。`
      : '年报红旗尚未评估，不能按 0 项处理。点击查看财务详情。';
    byId('preview-hub').querySelector('.preview-gauge').setAttribute('aria-label', flagsKnown
      ? `查看财务健康详情：已触发 ${flagCount} 项年报红旗，已评估 ${flagCoverage.evaluated} / ${flagCoverage.total} 项规则`
      : '查看财务健康详情：红旗数量尚未评估');
    const fiveYear = annualData?.assessment_track === 'five_year' && annualData?.periods?.length === 5;
    const annualDerived = fiveYear ? annualData.derived : null;
    const roeReport = overviewFinancialPayload?.latest_report;
    const annualTone = annual.value === '—' ? '' : ({ green: 'strong', yellow: 'watch', red: 'risk' }[annualData?.status] || '');
    setCards(byId('preview-financial-summary'), [
      summaryCard('年报评分', annual.value, null, 'financial', annualTone, 'annual'),
      summaryCard('季度评分', quarter.value, null, 'financial', '', 'quarter'),
      summaryCard('营收复合', financialMetric(annualDerived?.revenue_cagr), null, 'financial', negativeFinancialTone(annualDerived?.revenue_cagr), 'revenue'),
      summaryCard('扣归复合', financialMetric(annualDerived?.ex_net_profit_cagr), null, 'financial', negativeFinancialTone(annualDerived?.ex_net_profit_cagr), 'exProfit'),
      summaryCard('扣非ROE TTM', financialMetric(roeReport?.metrics?.roe_ex), null, 'financial', negativeFinancialTone(roeReport?.metrics?.roe_ex), 'roe'),
    ]);
    const operatingTiles = [
      ['FCM率TTM', 'FCF率（TTM）', 'margin'],
      ['现金利润比TTM', '现金利润比（TTM）', 'cash'],
      ['毛利率TTM', '毛利率（TTM）', 'margin'],
      ['净利率TTM', '净利率（TTM）', 'margin'],
      ['资产负债率', '资产负债率（最新）', 'debt'],
    ];
    setCards(byId('preview-financial-secondary'), operatingTiles.map(([label, source, icon]) => {
      const original = cardData(basicGrid, source);
      const tile = summaryCard(label, original?.value, null, 'financial', original?.state, icon);
      tile.title = `${source}：${original?.value || '—'}；${original?.status || '数据不足'}；与原版页面同源、同状态`;
      return tile;
    }));
    const price = cardData(basicGrid, '现价');
    const swing = byId('swing-structure')?.querySelector('.swing-summary');
    const structure = swing?.querySelector('div:nth-child(1) strong')?.textContent.trim();
    const tendency = swing?.querySelector('div:nth-child(2) strong')?.textContent.trim();
    const response = byId('wyckoff-equal-volume');
    const responseValue = response?.querySelector('p strong')?.textContent.trim();
    const marketPeriod = byId('market-relative-strength-period')?.textContent.trim() || '未加载';
    const relativeDate = marketPeriod.match(/20\d{2}-\d{2}-\d{2}/)?.[0];
    const position = marketPosition;
    const positionDate = position?.as_of_date;
    const positionAligned = !relativeDate || positionDate === relativeDate;
    const positionValue = positionAligned && Number.isFinite(position?.price_percentile)
      ? `${Number(position.price_percentile).toFixed(1)}%` : '—';
    const priceScope = position?.scope === 'five_year' ? '五年' : position?.scope === 'since_listing' ? '历史' : '口径待核';
    const peComparable = marketValuation?.primary_percentile_metric === 'pe_ttm'
      && marketValuation?.sample_status === 'ok' && Number.isFinite(marketValuation?.primary_percentile)
      && (!relativeDate || marketValuation?.industry_valuation_as_of === relativeDate);
    const pePosition = peComparable ? `${Number(marketValuation.primary_percentile).toFixed(1)}%` : '—';
    const industryName = marketValuation?.industry_level_2_name;
    const industryRow = industryTemperature?.concepts?.find((row) => row.concept_name === industryName);
    const temperatureReady = Boolean(industryName && industryRow && industryTemperature?.price_basis === 'tdx_export_qfq'
      && (!relativeDate || industryTemperature.as_of_date === relativeDate)
      && Number.isInteger(industryRow.temperature) && industryRow.temperature >= 0 && industryRow.temperature <= 5
      && industryRow.temperature_label);
    const display = (label, value, tab, tone, icon, tip) => {
      const card = summaryCard(label, value, null, tab, tone, icon);
      if (tip) card.title = tip;
      return card;
    };
    const cards = [
      display('现价', price?.value, 'valuation', '', 'price', `原始价行情快照；${byId('basic-market-period')?.textContent.trim() || '日期待加载'}`),
      display('股价分位', positionValue, 'valuation', '', 'price', positionValue === '—'
        ? '前复权价格分位不可用或与行情交易日不一致；不回退未复权价格'
        : `${priceScope}窗口内前复权收盘价的经验分位；${position.window_start}～${position.window_end}；有效日 ${position.sample_count}`),
      display('PE行业分位', pePosition, 'valuation', '', 'pe', peComparable
        ? `${marketValuation.industry_level_2_name || '二级行业'}；${marketValuation.classification || '分类待核'}同类PE有效样本 ${marketValuation.peer_sample_count}；数据日期 ${marketValuation.industry_valuation_as_of}；越低估值位置越低`
        : 'PE行业分位不可用（负盈利/改用PS/样本不足/数据日期不一致）；不把PS分位冒充PE'),
    ];
    if (positionValue !== '—') {
      const scope = document.createElement('span');
      scope.textContent = `${priceScope} · 前复权 · ${positionDate}`;
      cards[1].append(scope);
    }
    if (peComparable) {
      const source = document.createElement('span');
      source.textContent = `${marketValuation.industry_level_2_name} · ${marketValuation.industry_valuation_as_of}`;
      cards[2].append(source);
    }
    const dailyPe = marketDailyPe;
    const peUsable = dailyPe?.status === 'ok' && Number.isFinite(dailyPe?.current_pe)
      && dailyPe.current_pe > 0 && Number.isFinite(dailyPe?.percentile);
    const ownPePct = peUsable ? dailyPe.percentile : null;
    const peWindow = dailyPe?.basis === 'five_years' ? '5年' : '历史';
    const pePriceNote = dailyPe?.price_source === 'current_quote_time_unverified'
      ? '当前行情报价（接口未提供报价时间，不能核实为今日）'
      : `本地原始价收盘 ${dailyPe?.price_date || '日期未知'}`;
    const peEvidence = `报告${dailyPe?.latest_report_period || '未知'}（公告${dailyPe?.latest_announce_date || '未知'}）；${pePriceNote}；历史区间${dailyPe?.window_start || '未知'}～${dailyPe?.window_end || '未知'}，有效${dailyPe?.valid_days ?? 0}日；历史股本用当时最近已披露报表股本代理，财报仓未留存历次修订原件。`;
    const peCard = display('PE-TTM', peUsable ? dailyPe.current_pe.toFixed(2) : '—', 'valuation', '', 'pe',
      `${ownPePct === null ? `日频PE分位不可用（${dailyPe?.status || '数据未加载'}）` : `当前PE与自身${peWindow}逐日PE同口径比较，分位${ownPePct.toFixed(2)}%。`} ${peEvidence}`);
    const peFootnote = document.createElement('span');
    peFootnote.className = 'preview-own-pe-percentile';
    peFootnote.textContent = `个股PE${peWindow}分位 ${ownPePct === null ? '—' : `${ownPePct.toFixed(2)}%`}`;
    peCard.append(peFootnote);
    if (dailyPe?.latest_report_period) {
      const source = document.createElement('span');
      source.className = 'preview-pe-source';
      source.textContent = `${dailyPe.latest_report_period} · 行情${dailyPe.price_source === 'raw_daily_close' ? dailyPe.price_date : '时间未核'} · ${dailyPe.valid_days}日`;
      peCard.append(source);
    }
    cards.push(peCard);
    cards.push(display('超额日内响应差', responseValue, 'technical', '', 'er', responseValue && responseValue !== '—'
      ? '前复权同量日内涨幅扣除上证同日日内涨幅，再与历史同量日相比的逐日差值中位数（pp）；不是买卖信号'
      : '同量历史观察数据不足；不以零代替缺失'));
    for (const days of [20, 50, 120]) {
      const item = cardData(basicGrid, `RPS${days}`);
      cards.push(display(`RPS${days}`, item?.value, 'technical', item?.state, 'rps', `前复权${days}日全市场截面排名；${relativeDate || '日期待加载'}；${item?.status || '状态待加载'}`));
    }
    const mrs = cardData(relativeGrid, 'MRS 相对大盘强弱');
    cards.push(display('MRS', mrs?.value?.split('｜')[0], 'technical', '', 'rps', `MRS = 40% RPS20 + 30% RPS50 + 20% RPS120 + 10% RPS250；${mrs?.value || '数据不足'}`));
    const temperatureCard = display('行业温度', temperatureReady ? `${industryRow.temperature} · ${industryRow.temperature_label}` : '—',
      'technical', '', 'er', temperatureReady
        ? `申万二级行业：${industryName}；前复权10日绝对涨幅与广度温度档位；${industryTemperature.as_of_date}；0～5档，非热度分排名`
        : `申万二级行业温度不可用：${industryName || '行业归属待核'}；日期或前复权快照需与行情对齐`);
    if (temperatureReady) {
      const source = document.createElement('span');
      source.textContent = `${industryName} · ${industryTemperature.as_of_date}`;
      temperatureCard.append(source);
    }
    cards.push(temperatureCard);
    for (const days of [5, 20, 50]) {
      const item = cardData(relativeGrid, `ER${days}`);
      cards.push(display(`ER${days}`, item?.value, 'technical', '', 'er', `前复权${days}日相对全A每日等权大盘超额收益，单位pp；${relativeDate || '日期待加载'}`));
    }
    const structureCard = display('当前结构', structure, 'technical', '', 'event', `确认峰谷观察：${structure || '数据不足'}；${byId('swing-structure-period')?.textContent.trim() || '日期待加载'}；未知不代表中性`);
    structureCard.classList.add('preview-structure-card');
    cards.push(structureCard);
    cards.push(display('结构倾向', tendency, 'technical', /偏空/.test(tendency || '') ? 'risk' : /偏多/.test(tendency || '') ? 'strong' : '', 'event', '来自确认峰谷的倾向和星级；不是上涨概率或买卖建议'));
    byId('preview-market-period').textContent = `前复权/相对大盘：${relativeDate || '日期待加载'}｜股价分位：${positionDate || '日期待加载'}｜结构：${byId('swing-structure-period')?.textContent.trim() || '待核'}`;
    setCards(byId('preview-market-summary'), cards);
    fitStructureCard();
    const peBrief = `${dailyPe?.latest_report_period || '财报待核'} · 行情${dailyPe?.price_date || '待核'} · 有效${dailyPe?.valid_days ?? 0}日`;
    const valuationPe = summaryCard('PE-TTM', peUsable ? dailyPe.current_pe.toFixed(2) : '—', peBrief, 'valuation');
    const valuationRank = summaryCard(`个股PE${peWindow}分位`, ownPePct === null ? '—' : `${ownPePct.toFixed(2)}%`, peBrief, 'valuation');
    valuationPe.removeAttribute('data-preview-target');
    valuationPe.setAttribute('data-stock-pe-history', '');
    valuationPe.title = peEvidence;
    valuationRank.title = `日频同口径比较；${peEvidence}`;
    const fiveYearPrice = positionAligned && position?.scope === 'five_year'
      && Number.isFinite(position?.price_percentile) && positionDate;
    const valuationPrice = summaryCard('股价5年分位', fiveYearPrice ? `${position.price_percentile.toFixed(1)}%` : '—',
      fiveYearPrice ? `前复权 · ${positionDate} · ${position.sample_count}日` : '前复权五年证据不足或日期未对齐', 'valuation');
    valuationPrice.title = fiveYearPrice
      ? `前复权收盘价在五年有效日线中的经验分位；${position.window_start}～${position.window_end}；有效${position.sample_count}日；不回退原始价`
      : '五年有效前复权收盘价分位不可用或与行情交易日不一致；不回退原始价，也不以不足五年的上市以来分位冒充五年';
    const last = turnoverTrend?.rows?.at(-1);
    const turnoverReady = turnoverTrend?.as_of_date === positionDate && positionAligned
      && last?.date === positionDate && last?.sample_count >= 120
      && Number.isFinite(last?.percentile) && last.percentile >= 0 && last.percentile <= 100;
    const valuationTurnover = summaryCard('换手率分位', turnoverReady ? `${last.percentile.toFixed(1)}%` : '—',
      turnoverReady ? `近一年 · ${positionDate} · ${last.sample_count}窗` : '逐日证据不足或日期未对齐', 'valuation');
    valuationTurnover.title = turnoverReady
      ? `${turnoverTrend.definition}；窗口${turnoverTrend.window_start}～${positionDate}；当日7日截尾均值${last.trimmed_average_pct?.toFixed(2) ?? '未知'}%；流通股本来源${last.source || '未知'}；不是当日换手率排名`
      : '近一年7日截尾均值换手分位不可用：逐日快照缺失、有效窗口不足120或与前复权行情日期未对齐；不回退过期结果';
    for (const [card, kind] of [[valuationRank, 'pe-rank'], [valuationPrice, 'price-rank'], [valuationTurnover, 'turnover-rank']]) {
      card.removeAttribute('data-preview-target');
      card.dataset.valuationTrend = kind;
    }
    setCards(byId('preview-valuation-summary'), [valuationPe, valuationRank, valuationPrice, valuationTurnover]);
    const name = stockInput?.value.trim() || '选择股票开始阅读';
    byId('preview-company').textContent = name;
    byId('preview-freshness').textContent = `年报：${annual.value === '—' ? '评分不可用' : annual.label} ｜ 季度：${quarter.value === '—' ? '评分不可用' : quarter.label} ｜ 相对大盘：${marketPeriod}`;
    refreshEvents();
  }
  const trendDialog = byId('preview-valuation-trend-dialog');
  const trendChart = byId('preview-valuation-trend-chart');
  const trendStatus = byId('preview-valuation-trend-status');
  const trendHover = byId('preview-valuation-trend-hover');
  let trendController = null;
  let trendTrigger = null;
  let trendPoints = [];
  function drawPercentileTrend(rows, detail) {
    const valid = rows.filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date)
      && Number.isFinite(row.percentile) && row.percentile >= 0 && row.percentile <= 100)
      .sort((a, b) => a.date.localeCompare(b.date));
    if (!valid.length) throw Error('暂无可核验的逐日历史分位，不绘制虚假曲线');
    const left = 56, right = 898, top = 25, bottom = 292;
    const x = (index) => left + (valid.length === 1 ? (right - left) / 2 : index * (right - left) / (valid.length - 1));
    const y = (value) => bottom - value * (bottom - top) / 100;
    trendPoints = valid.map((row, index) => ({ ...row, x: x(index) }));
    const grid = [0, 25, 50, 75, 100].map((tick) =>
      `<line x1="${left}" x2="${right}" y1="${y(tick)}" y2="${y(tick)}" stroke="#275066" stroke-dasharray="4 6"/><text x="48" y="${y(tick) + 4}" text-anchor="end" fill="#9fb9c8" font-size="12">${tick}%</text>`).join('');
    const labels = [0, ...Array.from({ length: 4 }, (_, i) => Math.round((i + 1) * (valid.length - 1) / 4))]
      .filter((index, i, array) => array.indexOf(index) === i).map((index) =>
        `<text x="${x(index)}" y="320" text-anchor="middle" fill="#a4bcca" font-size="11">${valid[index].date}</text>`).join('');
    const path = trendPoints.map((row, index) => `${index ? 'L' : 'M'}${row.x.toFixed(2)},${y(row.percentile).toFixed(2)}`).join(' ');
    const last = trendPoints.at(-1);
    trendChart.innerHTML = `${grid}<path d="${path}" fill="none" stroke="#62b8ff" stroke-width="2.5"/><circle cx="${last.x}" cy="${y(last.percentile)}" r="5" fill="#7ce0c3"/>${labels}`;
    trendChart.removeAttribute('hidden');
    trendStatus.textContent = `${detail}｜${valid.length} 个有效交易日｜${valid[0].date}～${last.date}；缺失日不填值`;
    trendHover.textContent = `${last.date} · ${last.percentile.toFixed(2)}%${last.extra || ''}（移动鼠标查看历史）`;
  }
  async function showValuationTrend(kind, trigger) {
    if (!selectedStock) return;
    trendController?.abort();
    const controller = new AbortController();
    trendController = controller;
    trendTrigger = trigger;
    const stock = selectedStock, position = marketPosition, day = position?.as_of_date;
    const params = new URLSearchParams({ market: stock.market, symbol: stock.symbol });
    const get = (path, extra = '') => fetch(`${path}?${params}${extra}`, { signal: controller.signal })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw Error(payload.error?.message || '历史数据接口不可用');
        return payload;
      });
    byId('preview-valuation-trend-title').textContent = `${stock.stock_name || stock.symbol} ${stock.symbol} · ${{
      'pe-rank': '个股PE历史分位', 'price-rank': '股价5年分位', 'turnover-rank': '换手率分位',
    }[kind]}`;
    trendStatus.textContent = '正在读取同口径历史证据…';
    trendHover.textContent = '';
    trendChart.replaceChildren();
    trendChart.setAttribute('hidden', '');
    trendPoints = [];
    if (!trendDialog.open) trendDialog.showModal();
    try {
      if (kind === 'pe-rank') {
        const payload = await get('/api/stock-daily-pe-percentile', '&history=1');
        if (controller.signal.aborted || !trendDialog.open) return;
        if (payload.price_date !== marketDailyPe?.price_date || payload.history_basis !== 'fixed_current_window')
          throw Error('历史 PE 与卡片数据日期或比较窗口不一致');
        drawPercentileTrend(payload.history || [], `原始价日线 + 已披露 TTM 盈利与股本｜固定截至 ${payload.price_date} 的${payload.basis === 'five_years' ? '五年' : '上市以来'}样本比较；不是逐日滚动分位；实时价若不同于收盘价，卡片数值可能与末点不同`);
      } else if (kind === 'price-rank') {
        if (!position || position.scope !== 'five_year' || !day) throw Error('该股票没有可用的前复权五年分位');
        const response = await fetch(`/api/stock-qfq-trend?${params}&as_of_date=${encodeURIComponent(day)}&limit=2000`, { signal: controller.signal });
        const payload = await response.json();
        if (controller.signal.aborted || !trendDialog.open) return;
        if (!response.ok || !payload.ok) throw Error(payload.error?.message || '前复权日线不可用');
        if (payload.as_of_date !== position.as_of_date || payload.price_basis !== 'tdx_export_qfq')
          throw Error('前复权趋势日期或价格口径与卡片不一致');
        const bars = (payload.bars || []).filter((bar) => bar.trading_day >= position.window_start
          && bar.trading_day <= day && Number.isFinite(bar.close) && bar.close > 0);
        if (bars.length !== position.sample_count || bars.at(-1)?.trading_day !== day)
          throw Error('前复权五年有效日数与卡片快照不一致，拒绝混用');
        const ranks = bars.map((bar) => ({ date: bar.trading_day, percentile:
          Math.round(1000 * bars.filter((peer) => peer.close <= bar.close).length / bars.length) / 10,
          extra: ` · 前复权收盘 ${bar.close.toFixed(2)}` }));
        if (Math.abs(ranks.at(-1).percentile - position.price_percentile) > 0.11)
          throw Error('前复权末日分位与卡片快照不一致');
        drawPercentileTrend(ranks, `前复权收盘价｜固定${position.window_start}～${day}五年样本比较；不是逐日滚动五年分位`);
      } else if (kind === 'turnover-rank') {
        const last = turnoverTrend?.rows?.at(-1);
        if (!day || turnoverTrend?.as_of_date !== day || last?.date !== day || last.sample_count < 120)
          throw Error('同日近一年换手率分位证据不足');
        const rows = turnoverTrend.rows.filter((row) => row.date >= turnoverTrend.window_start && row.date <= day
          && row.sample_count >= 120 && Number.isFinite(row.percentile)).map((row) => ({
          date: row.date, percentile: row.percentile,
          extra: ` · 7日截尾均值 ${Number(row.trimmed_average_pct).toFixed(2)}% · 有效窗口 ${row.sample_count}`,
        }));
        drawPercentileTrend(rows, `截至 ${day} 的近一年逐日7日截尾均值换手分位；每点使用当时可见的有效窗口`);
      }
    } catch (error) {
      if (controller.signal.aborted || !trendDialog.open) return;
      trendChart.replaceChildren();
      trendChart.setAttribute('hidden', '');
      trendPoints = [];
      trendStatus.textContent = `无法绘制历史趋势：${error.message}`;
    }
  }
  hub.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-valuation-trend]');
    if (trigger && byId('preview-valuation-summary').contains(trigger)) showValuationTrend(trigger.dataset.valuationTrend, trigger);
  });
  trendChart.addEventListener('pointermove', (event) => {
    if (!trendPoints.length) return;
    const rect = trendChart.getBoundingClientRect();
    const x = (event.clientX - rect.left) * 920 / rect.width;
    const point = trendPoints.reduce((nearest, row) => !nearest || Math.abs(row.x - x) < Math.abs(nearest.x - x) ? row : nearest, null);
    if (point) trendHover.textContent = `${point.date} · ${point.percentile.toFixed(2)}%${point.extra || ''}`;
  });
  trendDialog.querySelector('.preview-valuation-trend-close').addEventListener('click', () => trendDialog.close());
  trendDialog.addEventListener('click', (event) => { if (event.target === trendDialog) trendDialog.close(); });
  trendDialog.addEventListener('close', () => {
    if (trendDialog.open) return;
    trendController?.abort();
    if (trendTrigger?.isConnected) trendTrigger.focus();
  });
  function queueSummary() {
    if (pendingSummary) return;
    pendingSummary = true;
    requestAnimationFrame(renderSummary);
  }
  [byId('basic-market-grid'), byId('market-relative-strength-grid'), byId('health-comparison-body'), byId('financial-health-composite'), byId('wyckoff-observation'), byId('swing-structure')].forEach((node) => {
    if (node) new MutationObserver(queueSummary).observe(node, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class'] });
  });
  byId('market-relative-strength-period') && new MutationObserver(queueSummary).observe(byId('market-relative-strength-period'), { childList: true, characterData: true, subtree: true });
  wyckoffToggle.addEventListener('click', () => { showAllEvents = !showAllEvents; refreshEvents(); });
  function switchTab(name, focusTab = false) {
    const tab = byId(`preview-tab-${name}`);
    if (!tab) return;
    hub.querySelectorAll('[role="tab"]').forEach((button) => {
      const active = button === tab;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
      byId(`preview-panel-${button.dataset.previewTab}`).hidden = !active;
    });
    if (focusTab) tab.focus();
  }
  hub.querySelectorAll('[role="tab"]').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.previewTab));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const tabs = [...hub.querySelectorAll('[role="tab"]')];
      const current = tabs.indexOf(tab);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
        : (current + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
      switchTab(tabs[next].dataset.previewTab, true);
    });
  });
  hub.addEventListener('click', (event) => {
    const linked = event.target.closest('a[href^="#"]');
    if (linked && hub.contains(linked)) {
      const chart = document.getElementById(decodeURIComponent(linked.hash.slice(1)));
      if (chart) {
        const targetPanel = chart.closest('.preview-panel');
        if (targetPanel) switchTab(targetPanel.id.replace('preview-panel-', ''));
        const fold = chart.closest('.preview-chart-fold');
        if (fold) fold.open = true;
      }
    }
    const target = event.target.closest('[data-preview-target]');
    if (!target) return;
    switchTab(target.dataset.previewTarget);
    hub.querySelector('.preview-tabs').scrollIntoView({ block: 'start', behavior: 'smooth' });
  });
  window.addEventListener('stock-analysis:select', (event) => {
    showAllEvents = false;
    const stock = event.detail;
    selectedStock = stock;
    if (trendDialog.open) trendDialog.close();
    originalLink.href = `/stock-analysis-legacy.html?${new URLSearchParams({ market: stock.market, symbol: stock.symbol, name: stock.stock_name })}`;
    byId('preview-company').textContent = `${stock.stock_name} (${stock.symbol})`;
    byId('preview-freshness').textContent = '正在加载对应股票的数据日期…';
    byId('preview-financial-summary').textContent = '正在加载财务结果…';
    byId('preview-market-summary').textContent = '正在加载行情与形态…';
    loadMarketPosition(stock);
    loadOverviewFinancial(stock);
    queueSummary();
  });
  stockInput?.addEventListener('input', () => { if (stockInput.value !== byId('preview-company').textContent) byId('preview-company').textContent = '正在选择股票…'; });
  queueSummary();
  // The original deep-link initializer does not load the swing structure. Use the existing
  // form submission once on a preview deep link to load both financials and swing without new APIs.
  if (stockFromUrl.get('market') && stockFromUrl.get('symbol')) {
    window.addEventListener('load', () => form.requestSubmit(), { once: true });
  }
})();
