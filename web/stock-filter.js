(function () {
  'use strict';

  var form = document.getElementById('filter-form');
  var results = document.getElementById('results');
  var status = document.getElementById('status');
  var pages = document.getElementById('pagination');
  var matchCount = document.getElementById('match-count');
  var sort = document.getElementById('sort');
  var presetInput = form.elements.preset;
  var asOfDate = form.elements.as_of_date;
  var presetOptions = Array.prototype.slice.call(document.querySelectorAll('[data-preset]'));
  var currentPage = 1;
  var historicalRetryTimer = null;
  var multi = { trend_daily: true, trend_weekly: true, trend_monthly: true, macd_cross: true, golden_cross: true, wyckoff_type: true, wyckoff_status: true, swing_state: true, swing_tendency: true, swing_star: true };

  function esc(value) {
    var node = document.createElement('span');
    node.textContent = value == null || value === '' ? '—' : String(value);
    return node.innerHTML;
  }

  function fixed(value, digits) {
    var number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits == null ? 1 : digits) : '—';
  }

  function selectedValues(field) {
    return Array.prototype.slice.call(field && field.selectedOptions || []).map(function (option) { return option.value; });
  }

  function setPreset(value) {
    presetInput.value = value || '';
    presetOptions.forEach(function (option) {
      option.classList.toggle('is-active', option.dataset.preset === presetInput.value);
    });
  }

  function requestParams(page) {
    var query = new URLSearchParams();
    Array.prototype.slice.call(form.elements).forEach(function (field) {
      if (!field.name || field.disabled || (field.type === 'checkbox' && !field.checked)) return;
      if (field.name === 'swing_entry_days' && !form.elements.swing_entry_only.checked) return;
      if (multi[field.name]) {
        var values = selectedValues(field);
        if (values.length) query.set(field.name, values.join(','));
        return;
      }
      if (String(field.value || '').trim()) query.set(field.name, field.value);
    });
    // 08 任一条件启用时，未选的方向/状态也限定在页面允许的偏多范围内。
    // 否则单选 Spring 会匹配已失效事件，或只选日期会匹配偏空事件。
    if (query.has('wyckoff_type') || query.has('wyckoff_status') || query.has('wyckoff_since')) {
      if (!query.has('wyckoff_type')) query.set('wyckoff_type', 'Spring,SOS,LPS');
      if (!query.has('wyckoff_status')) query.set('wyckoff_status', 'candidate,confirmed');
    }
    query.set('order', sort.selectedOptions[0].dataset.order || 'desc');
    query.set('page', String(page));
    query.set('page_size', '50');
    return query;
  }

  function relativeStrengthCell(row) {
    var score = Number(row.mrs_score);
    if (!Number.isFinite(score)) return '—';
    var er20 = Number(row.excess_return_20_pp);
    var win = Number(row.down_market_win_rate_20);
    var er = Number.isFinite(er20) ? (er20 > 0 ? '+' : '') + fixed(er20, 2) + 'pp' : '—';
    var anti = row.anti_fall_status === 'available' && Number.isFinite(win) ? '抗跌 ' + fixed(win, 1) + '%' : '抗跌样本不足';
    return '<span class="rps-total">' + fixed(score, 1) + '｜' + esc(row.mrs_label) + '</span><span class="subvalue">ER20 ' + er + ' · ' + anti + '</span><span class="subvalue">' + esc(row.relative_strength_state_label || '—') + '</span>';
  }

  function healthCell(score, period) {
    return '<span class="health">' + fixed(score) + '</span>' + (period ? '<span class="subvalue">' + esc(period) + '</span>' : '');
  }

  function reportReleaseReturnCell(row) {
    var value = Number(row.report_release_return_pct);
    if (!Number.isFinite(value)) return '—';
    var sign = value > 0 ? '+' : '';
    var klass = value > 0 ? 'report-return positive' : value < 0 ? 'report-return negative' : 'report-return';
    var title = '财报公告日后首个交易日（T+1）开盘至最新原始日线收盘价；T+1：' + (row.report_release_entry_trading_day || '—') + '；最新收盘：' + (row.report_release_latest_close_as_of || '—');
    return '<span class="' + klass + '" title="' + esc(title) + '">' + sign + fixed(value, 2) + '%</span>';
  }

  function priceCell(row, day) {
    var raw = row.price_percentile_5y;
    var valid = raw !== null && raw !== undefined && raw !== '' && Number.isFinite(Number(raw));
    var sinceListing = row.price_percentile_5y_basis === 'since_listing';
    var basisText = sinceListing
      ? '上市不足五年，改用上市以来全部历史（自 ' + (row.price_percentile_5y_window_start || '—') + ' 起 ' +
        (row.price_percentile_5y_sample_count || 0) + ' 个交易日）'
      : '近五个自然年窗口';
    var title = valid
      ? '前复权收盘价经验分位：历史收盘价≤当前收盘价的比例；' + basisText + '；截至 ' +
        (row.price_percentile_5y_as_of || row.qfq_as_of || '—')
      : '有效历史不足 60 个交易日，无法计算分位';
    var label = (valid && sinceListing ? '历史分位 ' : '五年分位 ') + (valid ? fixed(raw, 1) + '%' : '—');
    var priceText = fixed(row.price, 2);
    var clickablePrice = day && row.symbol && row.market && row.price != null && Number.isFinite(Number(row.price));
    var price = clickablePrice
      ? '<button type="button" class="price-trend-link" data-price-trend="1" data-market="' + esc(row.market) + '" data-symbol="' + esc(row.symbol) + '" data-day="' + esc(day) + '" data-name="' + esc(row.stock_name || '') + '" data-price="' + esc(row.price) + '" aria-label="查看' + esc(row.stock_name || row.symbol) + '截至' + esc(day) + '的股价趋势、成交量、MACD和RPS">' + priceText + '</button>'
      : priceText;
    return price + '<span class="subvalue" title="' + esc(title) + '">' + label + '</span>';
  }

  function valuationCell(row) {
    var value = row.pe_percentile_5y;
    var valid = value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
    var basis = row.pe_percentile_5y_basis === 'since_listing' ? '上市以来' : '近五自然年';
    var title = valid
      ? '每日原始收盘价 / 公告日之后可用的 TTM 盈利的自身历史 PE 经验分位；' + basis +
        ' · 有效 ' + (row.pe_percentile_5y_sample_count || 0) + ' 日 · 窗口自 ' +
        (row.pe_percentile_5y_window_start || '—') + ' · 价格日 ' + (row.pe_percentile_5y_price_date || '—') +
        ' · 财报 ' + (row.pe_percentile_5y_latest_report_period || '—') + '（公告 ' +
        (row.pe_percentile_5y_latest_announce_date || '—') + '）· 分位计算PE ' +
        (row.pe_percentile_5y_current_pe == null ? '—' : fixed(row.pe_percentile_5y_current_pe, 2)) +
        '；财报仓保留修订版，历史结果不是严格原始披露版本'
      : 'PE分位不可用：' + (row.pe_percentile_5y_status || '盈利非正、有效样本不足或原始行情缺失');
    var pct = valid ? fixed(value, 1) + '%' : '—';
    var label = valid && basis === '上市以来' ? '历史分位 ' : 'PE五年分位 ';
    return '<span class="health">PE ' + fixed(row.pe_ttm, 2) + '</span>' +
      '<span class="subvalue" title="' + esc(title) + '">' + label + pct + '</span>' +
      '<span class="subvalue">PS ' + fixed(row.ps_ttm, 2) + '</span>';
  }

  function epsRatioCell(row) {
    var value = row.eps_ratio_5y;
    if (value === null || value === undefined || !isFinite(Number(value))) return '—';
    var years = Number(row.eps_ratio_5y_years || 0);
    var cls = 'eps-ratio' + (Number(value) < 0 ? ' negative' : (Number(value) >= 50 ? ' positive' : ''));
    var text = Number(value).toFixed(1) + '%';
    var note = years && years < 5 ? '<span class="subvalue">' + years + '年年化</span>' : '';
    return '<span class="' + cls + '" title="5年累计EPS ' + (row.eps_ratio_5y_eps_sum === null || row.eps_ratio_5y_eps_sum === undefined ? '—' : Number(row.eps_ratio_5y_eps_sum).toFixed(3)) + ' 元 · 年化系数 ' + (row.eps_ratio_5y_factor || 1) + ' · 股价 ' + (row.eps_ratio_5y_price || '—') + '">' + text + '</span>' + note;
  }

  function wyckoffCell(row, snapshotLoaded) {
    var event = row.wyckoff_signal;
    if (!event) return snapshotLoaded ? '无符合条件事件' : '未查询';
    var evidence = event.evidence || {};
    var statusLabels = {candidate: '候选', confirmed: '已确认', invalidated: '已失效'};
    function evidenceNumber(value, digits) {
      return value == null || value === '' ? '—' : fixed(value, digits);
    }
    var title = '前复权有效日线 · 冻结边界 ' + evidenceNumber(evidence.boundary, 3) +
      ' · 事前20根成交量中位数比 ' + evidenceNumber(evidence.volume_ratio_20, 2) +
      (event.confirmation_date ? ' · 确认 ' + event.confirmation_date : '') +
      (event.invalidated_by && event.invalidated_by.date ? ' · 失效 ' + event.invalidated_by.date : '');
    return '<span title="' + esc(title) + '">' + esc(event.type) + ' · ' + esc(statusLabels[event.status] || event.status) +
      '</span><span class="subvalue">发生 ' + esc(event.date) + '</span>';
  }

  function swingCell(row, snapshot) {
    var swing = row.swing_structure;
    if (!swing) return '<span class="swing-cell">—<small>未提供该日期结构证据</small></span>';
    var unknown = swing.status !== 'ok' || !swing.state || swing.state === '证据不足' || swing.tendency === 'unknown';
    var statusLabel = swing.status === 'stale_qfq' ? '前复权日线过期' : swing.status === 'missing_qfq' ? '前复权日线缺失' : swing.status === 'out_of_current_tnf' ? '当前TNF研究清单不覆盖' : '证据不足';
    var tendency = {bull:'偏多',bear:'偏空',neutral:'中性'};
    var rating = unknown ? '未知 · ' + statusLabel : (tendency[swing.tendency] || '未知') + ' · ' + (swing.tendency === 'neutral' ? '—' : String(swing.stars || '—').slice(0,5));
    var content = '<strong>' + esc(unknown ? '未知' : swing.state) + ' · ' + esc(rating) + '</strong>' +
      (swing.state_run && swing.state_run.start_confirmed
        ? '<small class="subvalue">进入 ' + esc(swing.state_run.start_date) + ' · 连续 ' + esc(swing.state_run.trading_days) + ' 个有效交易日 · 上一状态 ' + esc(swing.state_run.previous_state) + '</small>'
        : '');
    var day = snapshot && snapshot.as_of_date;
    if (unknown || !day || swing.as_of !== day || swing.last_bar_date !== day) return '<span class="swing-cell">' + content + '</span>';
    return '<button type="button" class="swing-chart-link" data-swing-chart="1" data-market="' + esc(row.market) + '" data-symbol="' + esc(row.symbol) + '" data-date="' + esc(day) + '" data-state="' + esc(swing.state) + '" data-source="' + esc(swing.source_sha256 || '') + '"' + (snapshot.rule_version ? ' data-rule="' + esc(snapshot.rule_version) + '"' : '') + ' aria-label="查看' + esc(row.stock_name) + '截至' + esc(day) + '的前复权K线与峰谷证据" title="查看同日快照的前复权K线与峰谷证据">' + content + '</button>';
  }

  var priceTrendDialog = document.getElementById('price-trend-dialog');
  var priceTrendSvg = document.getElementById('price-trend-svg');
  var priceTrendMacd = document.getElementById('price-trend-macd');
  var priceTrendStatus = document.getElementById('price-trend-status');
  var priceTrendController = null;
  var priceTrendChart = null;
  var priceTrendBars = null;
  var priceTrendTrigger = null;
  function renderPriceTrendMacd(viewport) {
    if (priceTrendBars) PriceTrendChart.renderMacd(priceTrendMacd, priceTrendBars, viewport);
  }
  function setPriceTrendWindow(windowSize) {
    if (!priceTrendChart || !priceTrendBars) return;
    priceTrendChart.setPreset(windowSize);
    renderPriceTrendMacd(priceTrendChart.visible);
    priceTrendDialog.querySelectorAll('[data-trend-window]').forEach(function (button) {
      button.classList.toggle('is-active', Number(button.dataset.trendWindow) === windowSize);
    });
  }
  async function showPriceTrend(trigger) {
    if (priceTrendController) priceTrendController.abort();
    var controller = new AbortController();
    priceTrendController = controller;
    priceTrendTrigger = trigger;
    priceTrendBars = null;
    priceTrendDialog.querySelector('.price-trend-chart-area').hidden = true;
    priceTrendStatus.textContent = trigger.dataset.symbol + '｜正在读取截至 ' + trigger.dataset.day + ' 的前复权K线、成交量、MACD、RPS…';
    document.getElementById('price-trend-title').textContent = (trigger.dataset.name || trigger.dataset.symbol) + ' ' + trigger.dataset.symbol + ' · 股价趋势';
    if (!priceTrendDialog.open) priceTrendDialog.showModal();
    var qs = new URLSearchParams({market: trigger.dataset.market, symbol: trigger.dataset.symbol, as_of_date: trigger.dataset.day, limit: '300'});
    try {
      var responses = await Promise.all([
        fetch('/api/stock-qfq-trend?' + qs.toString(), {signal: controller.signal}),
        fetch('/api/stock-rps-history?symbol=' + encodeURIComponent(trigger.dataset.symbol), {signal: controller.signal}),
        import('./kline-chart.js?v=20261111-price-rps-nointerp-a')
      ]);
      var payloads = await Promise.all([
        responses[0].json().catch(function () { return {ok:false,error:{message:'前复权趋势接口未就绪或返回非JSON，请重启服务'}}; }),
        responses[1].json().catch(function () { return {ok:false}; })
      ]);
      if (controller.signal.aborted || !priceTrendDialog.open) return;
      var k = payloads[0], r = payloads[1], KlineChart = responses[2].KlineChart;
      if (!responses[0].ok || !k.ok) throw new Error(k.error && k.error.code === 'qfq_source_stale'
        ? '筛选日没有有效前复权成交K线；不会回退其他日期或原始价'
        : (k.error && k.error.message || '前复权日线不可用'));
      var rpsOk = responses[1].ok && r.ok && r.symbol === trigger.dataset.symbol;
      var evidence = PriceTrendChart.chartEvidence(k, trigger.dataset.day, rpsOk ? r.history : []);
      priceTrendDialog.querySelector('.price-trend-chart-area').hidden = false;
      if (!priceTrendChart) priceTrendChart = new KlineChart(priceTrendSvg, {marginRight:48, interpolateRps:false});
      priceTrendBars = evidence.bars;
      priceTrendChart.onViewportChange = function (viewport) {
        renderPriceTrendMacd(viewport);
        priceTrendDialog.querySelectorAll('[data-trend-window]').forEach(function (button) { button.classList.remove('is-active'); });
      };
      priceTrendChart.load(evidence.bars, evidence.rpsHistory, 120);
      renderPriceTrendMacd(priceTrendChart.visible);
      priceTrendDialog.querySelectorAll('[data-trend-window]').forEach(function (button) {
        button.classList.toggle('is-active', Number(button.dataset.trendWindow) === 120);
      });
      priceTrendStatus.textContent = '筛选日 ' + trigger.dataset.day + '｜表格原始收盘价 ' + Number(trigger.dataset.price).toFixed(2) + ' 元｜图表通达信前复权有效日线 ' + evidence.bars.length + ' 根｜成交量及MACD同日｜RPS' + (evidence.rpsAsOf ? '截至 ' + evidence.rpsAsOf + (evidence.rpsAsOf !== trigger.dataset.day ? '（筛选日缺失，不补值）' : '') : '不可用（未绘制）') + (rpsOk ? '' : '；RPS接口读取失败');
    } catch (error) {
      if (controller.signal.aborted || !priceTrendDialog.open) return;
      priceTrendDialog.querySelector('.price-trend-chart-area').hidden = true;
      priceTrendBars = null;
      priceTrendStatus.textContent = '无法绘制同日股价趋势：' + (error.message || '未知错误');
    }
  }
  results.addEventListener('click', function (event) {
    var cell = event.target.closest('td.num');
    var trigger = cell && cell.querySelector('[data-price-trend]');
    if (trigger) showPriceTrend(trigger);
  });
  priceTrendDialog.querySelectorAll('[data-trend-window]').forEach(function (button) {
    button.addEventListener('click', function () { setPriceTrendWindow(Number(button.dataset.trendWindow)); });
  });
  priceTrendDialog.querySelector('.price-trend-close').addEventListener('click', function () { priceTrendDialog.close(); });
  priceTrendDialog.addEventListener('click', function (event) { if (event.target === priceTrendDialog) priceTrendDialog.close(); });
  priceTrendDialog.addEventListener('close', function () {
    // close is asynchronous: a quick reopen must not abort the NEW request.
    if (priceTrendDialog.open) return;
    if (priceTrendController) priceTrendController.abort();
    if (priceTrendTrigger && priceTrendTrigger.isConnected) priceTrendTrigger.focus();
    priceTrendController = null; priceTrendTrigger = null;
  });

  var swingChartDialog = document.getElementById('swing-chart-dialog');
  var swingChartSvg = document.getElementById('swing-chart-svg');
  var swingChartMacd = document.getElementById('swing-chart-macd');
  var swingChartMeta = document.getElementById('swing-chart-meta');
  var swingChartController = null;
  var swingChartTrigger = null;
  var swingKlineChart = null;
  var swingChartData = null;
  var swingChartBars = null;
  function renderSwingViewport(viewport) {
    if (!swingChartBars || !swingChartData) return;
    SwingChart.renderOverlay(swingChartData, swingKlineChart);
    PriceTrendChart.renderMacd(swingChartMacd, swingChartBars, viewport);
  }
  function setSwingWindow(size) {
    if (!swingKlineChart || !swingChartBars) return;
    swingKlineChart.setPreset(size);
    renderSwingViewport(swingKlineChart.visible);
    swingChartDialog.querySelectorAll('[data-swing-window]').forEach(function (button) {
      button.classList.toggle('is-active', Number(button.dataset.swingWindow) === size);
    });
  }
  async function showSwingChart(trigger) {
    if (!swingChartDialog || !swingChartSvg || !swingChartMeta) return;
    if (swingChartController) swingChartController.abort();
    var controller = new AbortController();
    swingChartController = controller;
    swingChartTrigger = trigger;
    swingChartData = null; swingChartBars = null;
    swingChartDialog.querySelector('.swing-chart-scroll').hidden = true;
    swingChartMeta.textContent = trigger.dataset.symbol + '｜正在加载截至 ' + trigger.dataset.date + ' 的前复权峰谷、成交量、MACD、RPS证据…';
    if (!swingChartDialog.open) swingChartDialog.showModal();
    var query = new URLSearchParams({market: trigger.dataset.market, symbol: trigger.dataset.symbol, as_of_date: trigger.dataset.date});
    try {
      var responses = await Promise.all([
        fetch('/api/swing-structure?' + query.toString(), {signal: controller.signal}),
        fetch('/api/stock-rps-history?symbol=' + encodeURIComponent(trigger.dataset.symbol), {signal: controller.signal}),
        import('./kline-chart.js?v=20261111-price-rps-nointerp-a')
      ]);
      var payload = await responses[0].json();
      var rps = await responses[1].json().catch(function () { return {ok:false}; });
      if (controller.signal.aborted || !swingChartDialog.open) return;
      if (!responses[0].ok || !payload.ok) throw new Error(payload.error && payload.error.message || '同日结构证据无法读取');
      var data = payload.data || {};
      var observation = data.observation || {};
      if (data.as_of_date !== trigger.dataset.date || observation.last_bar_date !== trigger.dataset.date ||
          observation.state !== trigger.dataset.state || observation.status !== 'ok' ||
          (trigger.dataset.source && observation.source_sha256 !== trigger.dataset.source) ||
          (trigger.dataset.rule && data.rule_version !== trigger.dataset.rule) ||
          data.price_basis !== 'tdx_export_qfq') {
        throw new Error('详情与筛选结果的日期、前复权源或结构版本不一致，拒绝绘制。');
      }
      var rpsOk = responses[1].ok && rps.ok && rps.symbol === trigger.dataset.symbol;
      var evidence = SwingChart.chartEvidence(data, rpsOk ? rps.history : []);
      swingChartDialog.querySelector('.swing-chart-scroll').hidden = false;
      var KlineChart = responses[2].KlineChart;
      if (!swingKlineChart) swingKlineChart = new KlineChart(swingChartSvg, {marginRight:48, interpolateRps:false});
      swingChartData = data; swingChartBars = evidence.bars;
      swingKlineChart.onViewportChange = function (viewport) {
        renderSwingViewport(viewport);
        swingChartDialog.querySelectorAll('[data-swing-window]').forEach(function (button) { button.classList.remove('is-active'); });
      };
      swingKlineChart.load(evidence.bars, evidence.rpsHistory, 120);
      renderSwingViewport(swingKlineChart.visible);
      swingChartDialog.querySelectorAll('[data-swing-window]').forEach(function (button) {
        button.classList.toggle('is-active', Number(button.dataset.swingWindow) === 120);
      });
      swingChartMeta.textContent = trigger.dataset.symbol + ' ' + (data.name || '') + '｜结构 ' + observation.state + '｜通达信前复权 ' + data.as_of_date +
        '｜有效日线 ' + evidence.bars.length + ' 根｜实心峰谷=确认，虚线圈=候选' +
        (SwingChart.verifiedBox(observation) ? '｜箱体检验通过：前三组边界／第四组核验' : '｜当前无通过检验的箱体') + '｜RPS' +
        (evidence.rpsAsOf ? '截至 ' + evidence.rpsAsOf + (evidence.rpsAsOf === data.as_of_date ? '' : '（当日缺失，不补值）') : '不可用（未绘制）') +
        (rpsOk ? '' : '；RPS接口读取失败');
    } catch (error) {
      if (controller.signal.aborted || !swingChartDialog.open) return;
      swingChartDialog.querySelector('.swing-chart-scroll').hidden = true;
      swingChartData = null; swingChartBars = null;
      swingChartMeta.textContent = '无法绘制同日证据：' + (error.message || '未知错误');
    }
  }
  results.addEventListener('click', function (event) {
    var cell = event.target.closest('td.swing-cell');
    var trigger = cell && cell.querySelector('[data-swing-chart]');
    if (trigger) showSwingChart(trigger);
  });
  swingChartDialog.querySelectorAll('[data-swing-window]').forEach(function (button) {
    button.addEventListener('click', function () { setSwingWindow(Number(button.dataset.swingWindow)); });
  });
  swingChartDialog.querySelector('.swing-chart-close').addEventListener('click', function () { swingChartDialog.close(); });
  swingChartDialog.addEventListener('click', function (event) { if (event.target === swingChartDialog) swingChartDialog.close(); });
  swingChartDialog.addEventListener('close', function () {
    if (swingChartController) swingChartController.abort();
    if (swingChartTrigger && swingChartTrigger.isConnected) swingChartTrigger.focus();
    swingChartController = null; swingChartTrigger = null;
  });
  function renderRows(data) {
    if (!(data.rows || []).length) {
      results.innerHTML = '<tr><td colspan="11" class="empty-state">没有符合当前条件的股票。可以放宽区间或点击重置后重新筛选。</td></tr>';
      return;
    }
    results.innerHTML = data.rows.map(function (row) {
      var href = '/stock-analysis.html?market=' + encodeURIComponent(row.market) + '&symbol=' + encodeURIComponent(row.symbol) + '&name=' + encodeURIComponent(row.stock_name || '');
      return '<tr>' +
        '<td><a class="stock-link" href="' + href + '">' + esc(row.stock_name) + '</a><span class="stock-code">' + esc(row.market) + ':' + esc(row.symbol) + '</span></td>' +
        '<td>' + esc(row.industry) + '</td>' +
        '<td class="num">' + priceCell(row, data.data_as_of) + '</td>' +
        '<td>' + valuationCell(row) + '</td>' +
        '<td>' + relativeStrengthCell(row) + '</td>' +
        '<td>' + healthCell(row.annual_total, row.annual_period) + '</td>' +
        '<td>' + healthCell(row.quarterly_total, row.quarterly_period) + '</td>' +
        '<td class="num">' + reportReleaseReturnCell(row) + '</td>' +
        '<td class="num">' + epsRatioCell(row) + '</td>' +
        '<td>' + wyckoffCell(row, Boolean(data.wyckoff_snapshot)) + '</td>' +
        '<td class="swing-cell">' + swingCell(row, data.swing_snapshot || {as_of_date: data.data_as_of}) + '</td>' +
      '</tr>';
    }).join('');
  }

  function renderPagination(data) {
    pages.innerHTML = '';
    var meta = document.createElement('span');
    meta.className = 'page-meta';
    meta.textContent = '第 ' + data.page + ' / ' + data.total_pages + ' 页 · 每页 50 只';
    pages.appendChild(meta);
    [['上一页', data.page - 1, data.page <= 1], ['下一页', data.page + 1, data.page >= data.total_pages]].forEach(function (item) {
      var button = document.createElement('button');
      button.type = 'button'; button.className = 'page-button'; button.textContent = item[0]; button.disabled = item[2];
      button.addEventListener('click', function () { run(item[1]); });
      pages.appendChild(button);
    });
  }

  function render(data) {
    matchCount.textContent = Number(data.total_matched || 0).toLocaleString('zh-CN');
    status.classList.remove('error');
    var historical = data.is_historical ? ' · 历史基本面：公告日 point-in-time · 估值为当日原始收盘价' : '';
    var scopeLabel = data.stock_scope_label || '全部';
    var scopeText = scopeLabel === '全部'
      ? '全市场 ' + Number(data.total_universe || 0).toLocaleString('zh-CN')
      : '范围 ' + scopeLabel + ' ' + Number(data.total_universe || 0).toLocaleString('zh-CN') + ' 只（全市场 ' + Number(data.universe_total || data.total_universe || 0).toLocaleString('zh-CN') + '）';
    var wyckoff = data.wyckoff_snapshot;
    var wyckoffText = wyckoff ? ' · 威科夫前复权 ' + wyckoff.as_of_date + '（' + wyckoff.rule_version + '）' : '';
    if (wyckoff && wyckoff.excluded_lagged) {
      wyckoffText += ' · 前复权未覆盖当日，未参与威科夫筛选 ' + Number(wyckoff.excluded_lagged).toLocaleString('zh-CN') + ' 只（' + (wyckoff.lagged_symbols || []).slice(0, 6).join('、') + '）';
    }
    var swing = data.swing_snapshot;
    var entry = data.swing_entry_snapshot;
    var entryCoverage = entry && entry.coverage || {};
    var entryText = entry ? ' · 新进入≤' + entry.selected_days + '个有效交易日（' + entry.as_of_date + '；其它条件通过但进入窗不符 ' + Number(entry.excluded_after_other_filters).toLocaleString('zh-CN') + ' 只；全市场源状态证据不足 ' + Number(entryCoverage.insufficient_state || 0).toLocaleString('zh-CN') + ' 只、前复权过期 ' + Number(entryCoverage.stale_qfq || 0).toLocaleString('zh-CN') + ' 只）' : '';
    var swingText = swing ? ' · 波峰波谷前复权 ' + (swing.as_of_date || '—') + '（' + (swing.rule_version || '—') + '）' + (swing.excluded_lagged ? ' · 过期 ' + Number(swing.excluded_lagged).toLocaleString('zh-CN') + ' 只' : '') + (swing.outside_current_tnf ? ' · 基础池中不在当前TNF研究清单 ' + Number(swing.outside_current_tnf).toLocaleString('zh-CN') + ' 只（状态未知）' : '') : '';
    var peSnapshot = data.pe_percentile_snapshot;
    var peText = peSnapshot && peSnapshot.status !== 'ready' ? ' · PE-TTM五年分位快照未覆盖该筛选日，暂不提供分位及分位筛选' : '';
    status.textContent = scopeText + ' · 数据日期 ' + (data.data_as_of || '—') + historical + peText + wyckoffText + swingText + entryText + ' · 已因已启用字段缺失排除 ' + Number(data.excluded_missing || 0).toLocaleString('zh-CN') + ' 只';
    renderRows(data);
    renderPagination(data);
  }

  function scheduleHistoricalSnapshotRetry(page, message, progress) {
    matchCount.textContent = '—';
    status.classList.remove('error');
    var percent = Math.max(0, Math.min(100, Number(progress && progress.percent) || 0));
    var stage = progress && progress.stage || '正在准备历史快照';
    status.textContent = '正在生成历史快照：' + stage + '（' + percent + '%），将自动重试。';
    results.innerHTML = '<tr><td colspan="11" class="empty-state"><div>首次选择该交易日需生成公告日 point-in-time 快照；页面会自动刷新，无需重复点击。</div><progress value="' + percent + '%" max="100"></progress><strong> ' + percent + '%</strong></td></tr>';
    pages.innerHTML = '';
    if (historicalRetryTimer) window.clearTimeout(historicalRetryTimer);
    historicalRetryTimer = window.setTimeout(function () {
      historicalRetryTimer = null;
      run(page);
    }, 3000);
  }

  async function run(page) {
    if (priceTrendDialog.open) priceTrendDialog.close();
    if (swingChartDialog.open) swingChartDialog.close();
    if (historicalRetryTimer) {
      window.clearTimeout(historicalRetryTimer);
      historicalRetryTimer = null;
    }
    currentPage = page || 1;
    status.classList.remove('error');
    status.textContent = '正在按全市场条件筛选…';
    results.innerHTML = '<tr><td colspan="11" class="empty-state">正在加载筛选结果…</td></tr>';
    pages.innerHTML = '';
    try {
      var response = await fetch('/api/stock-filter?' + requestParams(currentPage).toString());
      var data = await response.json();
      if (data.error && data.error.code === 'historical_snapshot_building') {
        scheduleHistoricalSnapshotRetry(currentPage, data.error.message || '快照构建中', data.error.progress);
        return;
      }
      if (!response.ok || !data.ok) throw new Error(data.error && data.error.message || '筛选服务未返回有效结果');
      render(data);
    } catch (error) {
      matchCount.textContent = '—';
      status.classList.add('error');
      status.textContent = error.message;
      results.innerHTML = '<tr><td colspan="11" class="empty-state">无法读取筛选结果。请检查数据快照后重试。</td></tr>';
    }
  }


  function bindPresetTooltips() {
    var tip = document.getElementById('filter-tip');
    if (!tip || tip.dataset.bound === '1') return;
    tip.dataset.bound = '1';
    function show(target) {
      var text = target.getAttribute('data-tip');
      if (!text) return;
      tip.textContent = text;
      tip.setAttribute('data-open', '1');
      tip.setAttribute('aria-hidden', 'false');
      var rect = target.getBoundingClientRect();
      var width = tip.offsetWidth, height = tip.offsetHeight;
      // 筛选项在左侧窄栏里，气泡优先贴右侧，避免盖住按钮本身
      var left = rect.right + 12;
      var top = rect.top;
      if (left + width > window.innerWidth - 8) {
        left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 8);
        top = rect.bottom + 10;
        if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - height - 10);
      }
      top = Math.min(Math.max(8, top), Math.max(8, window.innerHeight - height - 8));
      tip.style.left = left + 'px';
      tip.style.top = top + 'px';
    }
    function hide() {
      tip.removeAttribute('data-open');
      tip.setAttribute('aria-hidden', 'true');
    }
    document.querySelectorAll('[data-tip]').forEach(function (target) {
      target.addEventListener('mouseenter', function () { show(target); });
      target.addEventListener('focus', function () { show(target); });
      target.addEventListener('mouseleave', hide);
      target.addEventListener('blur', hide);
      target.addEventListener('click', hide);
    });
    window.addEventListener('scroll', hide, true);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindPresetTooltips);
  } else {
    bindPresetTooltips();
  }
  form.addEventListener('submit', function (event) { event.preventDefault(); run(1); });
  form.addEventListener('reset', function () { window.setTimeout(function () { setPreset(presetInput.value); updateHistoricalMode(); run(1); }, 0); });
  document.getElementById('reset-top').addEventListener('click', function () { form.reset(); });
  Array.prototype.slice.call(document.querySelectorAll('.filter-group-toggle')).forEach(function (button) {
    button.addEventListener('click', function () {
      var group = button.closest('fieldset');
      var collapsed = group.classList.toggle('is-collapsed');
      button.setAttribute('aria-expanded', String(!collapsed));
    });
  });
  presetOptions.forEach(function (option) {
    option.addEventListener('click', function () {
      // Presets clear other controls but signal date is the user's historical
      // context and must survive the reset.
      var preservedSignalDate = asOfDate.value;
      form.reset();
      asOfDate.value = preservedSignalDate;
      setPreset(option.dataset.preset);
      updateHistoricalMode();
    });
  });
  function updateHistoricalMode() {
    var historical = Boolean(asOfDate.value);
    var unsupported = ['rps_20_min', 'rps_20_max', 'rps_50_min', 'rps_50_max', 'rps_120_min', 'rps_120_max', 'rps_250_min', 'rps_250_max', 'rps_total_min', 'rps_total_max', 'total_market_cap_min', 'total_market_cap_max', 'free_float_market_cap_min', 'free_float_market_cap_max', 'niche_leader', 'trend_daily', 'trend_weekly', 'trend_monthly', 'macd_cross', 'golden_cross'];
    unsupported.forEach(function (name) {
      var field = form.elements[name];
      if (field) field.disabled = historical;
    });
  }

  sort.addEventListener('change', function () { run(1); });
  asOfDate.addEventListener('change', function () {
    updateHistoricalMode();
    // Date is sent as as_of_date by requestParams; the server rejects a missing
    // point-in-time snapshot rather than falling back to current fundamentals.
    status.textContent = asOfDate.value ? '已选择历史信号日期，等待筛选。' : '已切回最新数据。';
  });
  run(1);
}());
