(function () {
  'use strict';

  var form = document.getElementById('filter-form');
  var results = document.getElementById('results');
  var status = document.getElementById('status');
  var pages = document.getElementById('pagination');
  var matchCount = document.getElementById('match-count');
  var sort = document.getElementById('sort');
  var addToWatchlist = document.getElementById('add-to-watchlist');
  var watchlistSelectedCount = document.getElementById('watchlist-selected-count');
  var watchlistFeedback = document.getElementById('watchlist-feedback');
  var openIndustryDistribution = document.getElementById('open-industry-distribution');
  var industryDistributionDialog = document.getElementById('industry-distribution-dialog');
  var industryDistributionMeta = document.getElementById('industry-distribution-meta');
  var industryDistributionDefinition = document.getElementById('industry-distribution-definition');
  var industryDistributionRows = document.getElementById('industry-distribution-rows');
  var latestIndustryDistribution = null;
  var financialQuarterDialog = document.getElementById('financial-quarter-history-dialog');
  var financialQuarterTitle = document.getElementById('financial-quarter-history-title');
  var financialQuarterMeta = document.getElementById('financial-quarter-history-meta');
  var financialQuarterCharts = document.getElementById('financial-quarter-history-charts');
  var financialQuarterController = null;
  var financialQuarterTrigger = null;
  var selectedStocks = new Map();
  var addingToWatchlist = false;
  var presetInput = form.elements.preset;
  var asOfDate = form.elements.as_of_date;
  var presetOptions = Array.prototype.slice.call(document.querySelectorAll('[data-preset]'));
  var currentPage = 1;
  var runSequence = 0;
  var historicalRetryTimer = null;
  var multi = { trend_daily: true, trend_weekly: true, trend_monthly: true, macd_cross: true, golden_cross: true, ma_alignment: true, wyckoff_type: true, wyckoff_status: true, swing_state: true, swing_tendency: true, swing_star: true, swing_observation: true };
  var industryScopeOpen = document.getElementById('industry-scope-open');
  var conceptScopeOpen = document.getElementById('concept-scope-open');
  var scopeSummary = document.getElementById('scope-selection-summary');
  var industryScopeDialog = document.getElementById('industry-scope-dialog');
  var conceptScopeDialog = document.getElementById('concept-scope-dialog');
  var scopeCatalog = null;
  var selectedIndustryCodes = new Set();
  var selectedIndustryTemperatureLevels = new Set();
  var selectedConceptCodes = new Set();
  var selectedTemperatureLevels = new Set();
  var draftIndustryCodes = new Set();
  var draftIndustryTemperatureLevels = new Set();
  var draftConceptCodes = new Set();
  var draftTemperatureLevels = new Set();

  function esc(value) {
    var node = document.createElement('span');
    node.textContent = value == null || value === '' ? '—' : String(value);
    return node.innerHTML;
  }

  function fixed(value, digits) {
    var number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits == null ? 1 : digits) : '—';
  }
  function basicMarketTitle(row) {
    var items = [
      ['当日涨跌', row.return_1d, '%'], ['量比', row.volume_ratio_5, '倍'],
      ['距MA5', row.ma5_distance_pct, '%'], ['距MA10', row.ma10_distance_pct, '%'],
      ['距MA20', row.ma20_distance_pct, '%']
    ];
    return '前复权截至' + (row.qfq_as_of || '未知') + '｜' + items.map(function (item) {
      return item[0] + ' ' + (item[1] == null ? '—' : fixed(item[1], 2) + item[2]);
    }).join(' · ');
  }

  function selectedValues(field) {
    return Array.prototype.slice.call(field && field.selectedOptions || []).map(function (option) { return option.value; });
  }

  function scopeNameMap(items) {
    var map = new Map();
    (items || []).forEach(function (item) { map.set(String(item.code), item); });
    return map;
  }

  function syncScopeInputs() {
    form.elements.industry_l2_codes.value = Array.from(selectedIndustryCodes).sort().join(',');
    form.elements.industry_temperature_levels.value = Array.from(selectedIndustryTemperatureLevels).sort().join(',');
    form.elements.concept_codes.value = Array.from(selectedConceptCodes).sort().join(',');
    form.elements.concept_temperature_levels.value = Array.from(selectedTemperatureLevels).sort().join(',');
  }

  function selectedLabels(codes, items, fallback) {
    var byCode = scopeNameMap(items);
    var names = Array.from(codes).map(function (code) { return (byCode.get(code) || {}).name || code; });
    return names.length ? names.join('、') : fallback;
  }

  function renderScopeSummary() {
    if (!scopeCatalog) {
      scopeSummary.innerHTML = '<span>正在读取二级行业、概念和概念温度…</span>';
      return;
    }
    var tempMap = new Map((scopeCatalog.temperature_options || []).map(function (item) { return [String(item.value), item.label]; }));
    var industryTemperatures = Array.from(selectedIndustryTemperatureLevels).map(function (value) { return tempMap.get(String(value)) || value; });
    var temperatures = Array.from(selectedTemperatureLevels).map(function (value) { return tempMap.get(String(value)) || value; });
    scopeSummary.innerHTML =
      '<div class="scope-summary-row"><strong>二级行业</strong><span class="scope-summary-values">' + esc(selectedLabels(selectedIndustryCodes, scopeCatalog.industries, '不限')) + '</span></div>' +
      '<div class="scope-summary-row"><strong>行业温度</strong><span class="scope-summary-values">' + esc(industryTemperatures.length ? industryTemperatures.join('、') + '（' + scopeCatalog.industry_temperature_window + '日）' : '不限') + '</span></div>' +
      '<div class="scope-summary-row"><strong>概念</strong><span class="scope-summary-values">' + esc(selectedLabels(selectedConceptCodes, scopeCatalog.concepts, '不限')) + '</span></div>' +
      '<div class="scope-summary-row"><strong>概念温度</strong><span class="scope-summary-values">' + esc(temperatures.length ? temperatures.join('、') + '（' + scopeCatalog.concept_temperature_window + '日）' : '不限') + '</span></div>';
  }

  function renderIndustryScopeOptions() {
    var query = document.getElementById('industry-scope-search').value.trim().toLowerCase();
    var rows = (scopeCatalog && scopeCatalog.industries || []).filter(function (item) {
      var textMatch = !query || String(item.name).toLowerCase().indexOf(query) >= 0 || String(item.code).toLowerCase().indexOf(query) >= 0;
      var tempMatch = !draftIndustryTemperatureLevels.size || draftIndustryTemperatureLevels.has(String(item.temperature));
      return textMatch && (tempMatch || draftIndustryCodes.has(String(item.code)));
    });
    document.getElementById('industry-scope-options').innerHTML = rows.map(function (item) {
      var temperature = item.temperature == null ? '数据不足' : item.temperature_label + ' · ' + item.temperature;
      return '<label class="scope-option"><input type="checkbox" data-scope-industry="' + esc(item.code) + '"' + (draftIndustryCodes.has(String(item.code)) ? ' checked' : '') + '><span class="scope-option-name">' + esc(item.name) + '</span><span class="scope-option-meta">' + esc(temperature) + '<br>' + Number(item.member_count || 0).toLocaleString('zh-CN') + '只</span></label>';
    }).join('') || '<p class="empty-state">没有匹配的二级行业。</p>';
    document.getElementById('industry-scope-count').textContent = '已选择 ' + draftIndustryCodes.size + ' 个行业，' + (draftIndustryTemperatureLevels.size ? draftIndustryTemperatureLevels.size + ' 个温度档位' : '温度不限');
  }

  function renderIndustryTemperatureOptions() {
    var historical = Boolean(asOfDate.value);
    document.getElementById('industry-temperature-options').innerHTML = (scopeCatalog && scopeCatalog.temperature_options || []).map(function (item) {
      var value = String(item.value);
      return '<label><input type="checkbox" data-scope-industry-temperature="' + esc(value) + '"' + (draftIndustryTemperatureLevels.has(value) ? ' checked' : '') + (historical ? ' disabled' : '') + '>' + esc(item.label) + '</label>';
    }).join('');
  }

  function renderTemperatureOptions() {
    document.getElementById('concept-temperature-options').innerHTML = (scopeCatalog && scopeCatalog.temperature_options || []).map(function (item) {
      var value = String(item.value);
      return '<label><input type="checkbox" data-scope-temperature="' + esc(value) + '"' + (draftTemperatureLevels.has(value) ? ' checked' : '') + '>' + esc(item.label) + '</label>';
    }).join('');
  }

  function renderConceptScopeOptions() {
    var query = document.getElementById('concept-scope-search').value.trim().toLowerCase();
    var rows = (scopeCatalog && scopeCatalog.concepts || []).filter(function (item) {
      var textMatch = !query || String(item.name).toLowerCase().indexOf(query) >= 0 || String(item.code).toLowerCase().indexOf(query) >= 0;
      var tempMatch = !draftTemperatureLevels.size || draftTemperatureLevels.has(String(item.temperature));
      return textMatch && (tempMatch || draftConceptCodes.has(String(item.code)));
    });
    document.getElementById('concept-scope-options').innerHTML = rows.map(function (item) {
      var temperature = item.temperature == null ? '数据不足' : item.temperature_label + ' · ' + item.temperature;
      return '<label class="scope-option"><input type="checkbox" data-scope-concept="' + esc(item.code) + '"' + (draftConceptCodes.has(String(item.code)) ? ' checked' : '') + '><span class="scope-option-name">' + esc(item.name) + '</span><span class="scope-option-meta">' + esc(temperature) + '<br>' + Number(item.member_count || 0).toLocaleString('zh-CN') + '只</span></label>';
    }).join('') || '<p class="empty-state">没有匹配的概念。</p>';
    document.getElementById('concept-scope-count').textContent = '已选择 ' + draftConceptCodes.size + ' 个概念，' + (draftTemperatureLevels.size ? draftTemperatureLevels.size + ' 个温度档位' : '温度不限');
  }

  function openScopeDialog(kind) {
    if (!scopeCatalog) return;
    if (kind === 'industry') {
      draftIndustryCodes = new Set(selectedIndustryCodes);
      draftIndustryTemperatureLevels = new Set(selectedIndustryTemperatureLevels);
      document.getElementById('industry-scope-search').value = '';
      renderIndustryTemperatureOptions();
      renderIndustryScopeOptions();
      industryScopeDialog.showModal();
      return;
    }
    draftConceptCodes = new Set(selectedConceptCodes);
    draftTemperatureLevels = new Set(selectedTemperatureLevels);
    document.getElementById('concept-scope-search').value = '';
    renderTemperatureOptions();
    renderConceptScopeOptions();
    conceptScopeDialog.showModal();
  }

  function clearScopeSelection(runNow) {
    selectedIndustryCodes.clear();
    selectedIndustryTemperatureLevels.clear();
    selectedConceptCodes.clear();
    selectedTemperatureLevels.clear();
    syncScopeInputs();
    renderScopeSummary();
    if (runNow) run(1);
  }

  async function loadScopeCatalog() {
    try {
      var response = await fetch('/api/stock-filter/scopes');
      var data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error && data.error.message || '范围数据不可用');
      scopeCatalog = data;
      document.getElementById('industry-scope-meta').textContent = '行业温度读取现有' + data.industry_temperature_window + '日快照，截至 ' + (data.industry_temperature_as_of || '未知') + '；明确行业与温度同时选择时取交集。';
      document.getElementById('concept-scope-meta').textContent = '概念温度读取现有' + data.concept_temperature_window + '日快照，截至 ' + (data.concept_temperature_as_of || '未知') + '；明确概念与温度同时选择时取交集。';
      industryScopeOpen.disabled = Boolean(asOfDate.value);
      conceptScopeOpen.disabled = Boolean(asOfDate.value);
      renderScopeSummary();
    } catch (error) {
      industryScopeOpen.disabled = true;
      conceptScopeOpen.disabled = true;
      scopeSummary.innerHTML = '<span>行业/概念范围不可用：' + esc(error.message) + '</span>';
    }
  }

  industryScopeOpen.disabled = true;
  conceptScopeOpen.disabled = true;
  industryScopeOpen.addEventListener('click', function () { openScopeDialog('industry'); });
  conceptScopeOpen.addEventListener('click', function () { openScopeDialog('concept'); });
  document.getElementById('scope-selection-clear').addEventListener('click', function () { clearScopeSelection(true); });
  document.getElementById('industry-scope-search').addEventListener('input', renderIndustryScopeOptions);
  document.getElementById('concept-scope-search').addEventListener('input', renderConceptScopeOptions);
  document.getElementById('industry-scope-options').addEventListener('change', function (event) {
    var code = event.target.dataset.scopeIndustry;
    if (!code) return;
    if (event.target.checked) draftIndustryCodes.add(code); else draftIndustryCodes.delete(code);
    renderIndustryScopeOptions();
  });
  document.getElementById('industry-temperature-options').addEventListener('change', function (event) {
    var level = event.target.dataset.scopeIndustryTemperature;
    if (level == null) return;
    if (event.target.checked) draftIndustryTemperatureLevels.add(level); else draftIndustryTemperatureLevels.delete(level);
    renderIndustryScopeOptions();
  });
  document.getElementById('concept-scope-options').addEventListener('change', function (event) {
    var code = event.target.dataset.scopeConcept;
    if (!code) return;
    if (event.target.checked) draftConceptCodes.add(code); else draftConceptCodes.delete(code);
    renderConceptScopeOptions();
  });
  document.getElementById('concept-temperature-options').addEventListener('change', function (event) {
    var level = event.target.dataset.scopeTemperature;
    if (level == null) return;
    if (event.target.checked) draftTemperatureLevels.add(level); else draftTemperatureLevels.delete(level);
    renderConceptScopeOptions();
  });
  document.querySelectorAll('[data-scope-close]').forEach(function (button) {
    button.addEventListener('click', function () {
      (button.dataset.scopeClose === 'industry' ? industryScopeDialog : conceptScopeDialog).close();
    });
  });
  document.querySelectorAll('[data-scope-clear-draft]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (button.dataset.scopeClearDraft === 'industry') {
        draftIndustryCodes.clear(); draftIndustryTemperatureLevels.clear(); renderIndustryTemperatureOptions(); renderIndustryScopeOptions();
      } else {
        draftConceptCodes.clear(); draftTemperatureLevels.clear(); renderTemperatureOptions(); renderConceptScopeOptions();
      }
    });
  });
  document.querySelector('[data-scope-confirm="industry"]').addEventListener('click', function () {
    selectedIndustryCodes = new Set(draftIndustryCodes); selectedIndustryTemperatureLevels = new Set(draftIndustryTemperatureLevels); syncScopeInputs(); renderScopeSummary(); industryScopeDialog.close(); clearWatchlistSelection(); run(1);
  });
  document.querySelector('[data-scope-confirm="concept"]').addEventListener('click', function () {
    selectedConceptCodes = new Set(draftConceptCodes); selectedTemperatureLevels = new Set(draftTemperatureLevels); syncScopeInputs(); renderScopeSummary(); conceptScopeDialog.close(); clearWatchlistSelection(); run(1);
  });

  function setPreset(value) {
    var selected = new Set((value || '').split(',').filter(Boolean));
    presetInput.value = presetOptions.filter(function (option) {
      return selected.has(option.dataset.preset);
    }).map(function (option) { return option.dataset.preset; }).join(',');
    presetOptions.forEach(function (option) {
      var active = selected.has(option.dataset.preset);
      option.classList.toggle('is-active', active);
      option.setAttribute('aria-pressed', String(active));
    });
  }

  function togglePreset(value) {
    var selected = new Set((presetInput.value || '').split(',').filter(Boolean));
    if (selected.has(value)) selected.delete(value);
    else selected.add(value);
    setPreset(Array.from(selected).join(','));
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

  function annualScoreBasisLabel(track) {
    return ({ recovery_track: '恢复型', deteriorating_track: '恶化型', not_applicable: '不适用' })[track] || '';
  }

  function annualHealthCell(row, historical) {
    if (historical) return healthCell(row.annual_total, row.annual_period);
    var score = row.annual_total === null || row.annual_total === undefined ? '—' : fixed(row.annual_total);
    var name = row.stock_name || row.symbol;
    var basisLabel = annualScoreBasisLabel(row.annual_score_basis_track);
    var basisTitle = basisLabel ? '；五年健康口径：' + basisLabel + '，增长=' + (row.annual_growth_quality_basis || '未知') + '，现金=' + (row.annual_cash_quality_basis || '未知') : '';
    var subvalue = [row.annual_period, basisLabel].filter(Boolean).join(' · ');
    return '<button type="button" class="financial-history-trigger" data-market="' + esc(row.market) + '" data-symbol="' + esc(row.symbol) + '" data-stock-name="' + esc(name) + '" aria-label="查看' + esc(name) + '五年健康对应的单季度财务指标历史" title="查看七项单季度财务指标历史' + esc(basisTitle) + '">' +
      '<span class="health">' + score + '</span>' + (subvalue ? '<span class="subvalue">' + esc(subvalue) + '</span>' : '') + '</button>';
  }

  function marketCapCell(row) {
    var value = Number(row.total_market_cap);
    if (!Number.isFinite(value) || value < 0) return '—';
    return '<span class="market-cap" title="总市值，单位亿元">' + fixed(value, 1) + '</span>';
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
    var customReturn = Number(row.return_n_pct);
    var customDays = Number(row.return_n_days);
    var custom = Number.isFinite(customReturn) && Number.isInteger(customDays)
      ? '<span class="subvalue" title="前复权收盘价：' + esc(row.return_n_start_close) + ' → ' + esc(row.return_n_end_close) + '；截至 ' + esc(row.return_n_as_of || day || '—') + '">' + customDays + '日 ' + (customReturn > 0 ? '+' : '') + fixed(customReturn, 2) + '%</span>'
      : '';
    var changeDays = Number(row.change_days_n);
    var upDays = Number(row.up_days);
    var downDays = Number(row.down_days);
    var flatDays = Number(row.flat_days);
    var changes = Number.isInteger(changeDays) && Number.isInteger(upDays) && Number.isInteger(downDays) && Number.isInteger(flatDays)
      ? '<span class="subvalue" title="最近' + changeDays + '个有效前复权交易日；截至 ' + esc(row.change_days_as_of || day || '—') + '">' + changeDays + '日 ↑' + upDays + ' ↓' + downDays + ' →' + flatDays + '</span>'
      : '';
    return price + '<span class="subvalue" title="' + esc(title) + '">' + label + '</span>' + custom + changes;
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

  function turnoverCell(row, day) {
    var value = row.turnover_percentile_1y;
    var samples = Number(row.turnover_percentile_1y_sample_count);
    var valid = value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) &&
      Number(value) >= 0 && Number(value) <= 100 && Number.isFinite(samples) && samples >= 120;
    var source = row.turnover_percentile_1y_current_shares_source === 'report_proxy'
      ? '已公告财报代理值（非已核实的逐日实际股本）'
      : row.turnover_percentile_1y_current_shares_source === 'gbbq_verified' ? '已核实变动日的股本' : '未知';
    var reason = {stale_bar: '当日有效日线缺失', missing_current_shares: '当时无已公告的有效股本', missing_valid_bars: '近一年无有效日线', insufficient_history: '近一年有效7日截尾均值样本不足120日'};
    var evidence = valid
      ? '单股截至当日近一年每日7日截尾均值换手率经验分位（已上市流通A股；不高于当日7日截尾均值的有效样本数／有效样本数）；单独记录的当日换手率（非分位计算值） ' +
        (row.turnover_percentile_1y_current_turnover == null ? '未知' : fixed(row.turnover_percentile_1y_current_turnover, 2) + '%') +
        ' · 有效样本 ' + (row.turnover_percentile_1y_sample_count == null ? '未知' : row.turnover_percentile_1y_sample_count) + ' 日' +
        ' · 窗口自 ' + (row.turnover_percentile_1y_window_start || '未知') +
        ' · 截至 ' + (row.turnover_percentile_1y_as_of || '未知') +
        ' · 当日流通股本来源 ' + source +
        ' · 财报 ' + (row.turnover_percentile_1y_report_period || '未知') + '，公告 ' + (row.turnover_percentile_1y_report_announce || '未知') +
        ' · 历史财报代理 ' + (row.turnover_percentile_1y_report_fallback_count == null ? '未知' : row.turnover_percentile_1y_report_fallback_count) + ' 日' +
        '；财报仓保留修订版，历史数值不是严格原始披露版本'
      : '换手分位未知：' + (samples > 0 && samples < 120 ? reason.insufficient_history :
        (reason[row.turnover_percentile_1y_status] || row.turnover_percentile_1y_status || '数据缺失'));
    if (!valid || !day || !row.market || !row.symbol || (row.turnover_percentile_1y_as_of && row.turnover_percentile_1y_as_of !== day)) {
      var display = valid ? fixed(value, 1) + '%' : (row.turnover_percentile_1y_status === 'insufficient_history' || (samples > 0 && samples < 120) ? '样本不足' : '—');
      return '<span class="subvalue" title="' + esc(evidence) + '">' + display + '</span>';
    }
    return '<button type="button" class="turnover-trend-link" data-turnover-trend="1" data-market="' + esc(row.market) +
      '" data-symbol="' + esc(row.symbol) + '" data-date="' + esc(day) + '" data-name="' + esc(row.stock_name || '') +
      '" aria-label="查看' + esc(row.stock_name || row.symbol) + '截至' + esc(day) + '的7日截尾均值换手历史分位趋势" title="' + esc(evidence) + '">' + fixed(value, 1) + '%</button>';
  }

  function turnoverTrendChart(rows, day) {
    var end = Date.parse(day + 'T00:00:00Z');
    if (!Number.isFinite(end)) return '';
    var startDate = new Date(end);
    startDate.setUTCFullYear(startDate.getUTCFullYear() - 1);
    var start = startDate.getTime();
    var lower = startDate.toISOString().slice(0, 10);
    var x = function (time) { return 56 + 734 * (time - start) / (end - start); };
    var y = function (value) { return 260 - 224 * value / 100; };
    var points = (rows || []).filter(function (row) {
      return row && /^\d{4}-\d{2}-\d{2}$/.test(row.date) && row.date >= lower && row.date <= day &&
        Number.isFinite(Date.parse(row.date + 'T00:00:00Z'));
    }).sort(function (a, b) { return a.date.localeCompare(b.date); });
    var parts = ['<title>每日7日截尾均值换手率历史分位</title><desc>横轴日期，纵轴0到100%；缺失值不连线</desc>'];
    [0, 25, 50, 75, 100].forEach(function (tick) {
      parts.push('<line x1="56" x2="790" y1="' + y(tick) + '" y2="' + y(tick) + '" stroke="#35504a" stroke-opacity=".5"/>');
      parts.push('<text x="47" y="' + (y(tick) + 4) + '" fill="#a9bcb5" text-anchor="end" font-size="12">' + tick + '%</text>');
    });
    parts.push('<text x="56" y="288" fill="#a9bcb5" font-size="12">' + lower + '</text>');
    parts.push('<text x="790" y="288" fill="#a9bcb5" font-size="12" text-anchor="end">' + day + '</text>');
    var segment = [];
    function flush() {
      if (segment.length > 1) parts.push('<path d="' + segment.join(' ') + '" fill="none" stroke="#b7e36b" stroke-width="2"/>');
      segment = [];
    }
    points.forEach(function (row, index) {
      var value = row.percentile;
      if (value == null || value === '' || !Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > 100 ||
          !Number.isFinite(Number(row.sample_count)) || Number(row.sample_count) < 120) { flush(); return; }
      var time = Date.parse(row.date + 'T00:00:00Z');
      var px = x(time).toFixed(2), py = y(Number(value)).toFixed(2);
      segment.push((segment.length ? 'L' : 'M') + px + ',' + py);
      parts.push('<circle data-turnover-point="' + index + '" tabindex="0" role="img" aria-label="' + row.date + ' 换手分位 ' + Number(value).toFixed(1) + '%" cx="' + px + '" cy="' + py + '" r="3" fill="#b7e36b"/>');
    });
    flush();
    return parts.join('');
  }


  function swingCell(row, snapshot, historical) {
    var swing = row.swing_structure;
    if (!swing) return '<span class="swing-cell">—<small>未提供该日期结构证据</small></span>';
    var unknown = swing.status !== 'ok' || !swing.state || swing.state === '证据不足' || swing.tendency === 'unknown';
    var statusLabel = swing.status === 'stale_qfq' ? '前复权日线过期' : swing.status === 'missing_qfq' ? '前复权日线缺失' : swing.status === 'out_of_current_tnf' ? '当前TNF研究清单不覆盖' : '证据不足';
    var tendency = {bull:'偏多',bear:'偏空',neutral:'中性',caution:'谨慎'};
    var rating = unknown ? '未知 · ' + statusLabel : (tendency[swing.tendency] || '未知') + ' · ' + (swing.tendency === 'neutral' ? '—' : String(swing.stars || '—').slice(0,5));
    var risk = swing.new_low_risk;
    var baseline = swing.tendency === 'caution' && swing.underlying_rating
      ? '<small>主结构基础评级 ' + esc(tendency[swing.underlying_rating.tendency] || '未知') + ' · ' + esc(swing.underlying_rating.star_count) + ' 星（暂缓）</small>' : '';
    var riskText = risk ? '<small>未确认新低风险 · 谨慎观察：' + esc(risk.date) + ' 低点 ' + esc(risk.low == null ? '—' : fixed(risk.low, 2)) + '；最近确认波谷 ' + esc(risk.confirmed_valley_date) + ' / ' + esc(risk.confirmed_valley_low == null ? '—' : fixed(risk.confirmed_valley_low, 2)) + '；候选低点后已等待 ' + esc(risk.waiting_bars) + ' 根有效K线；触发日' + (risk.break_day_close_below_confirmed_valley ? '收盘低于确认波谷' : '收盘未低于确认波谷') + '；当前' + (risk.close_below_confirmed_valley ? '收盘低于确认波谷' : '收盘未低于确认波谷') + '</small>' : '';
    var pressure = swing.pressure_line;
    var content = '<strong>' + esc(unknown ? '未知' : swing.state) + ' · ' + esc(rating) + '</strong>' + baseline + riskText +
      (swing.state_run && swing.state_run.start_confirmed
        ? '<small class="subvalue">进入 ' + esc(swing.state_run.start_date) + ' · 连续 ' + esc(swing.state_run.trading_days) + ' 个有效交易日 · 上一状态 ' + esc(swing.state_run.previous_state) + '</small>'
        : '');
    var day = snapshot && snapshot.as_of_date;
    if (unknown || !day || swing.as_of !== day || swing.last_bar_date !== day) return '<span class="swing-cell">' + content + '</span>';
    return '<button type="button" class="swing-chart-link" data-swing-chart="1" data-market="' + esc(row.market) + '" data-symbol="' + esc(row.symbol) + '" data-name="' + esc(row.stock_name || '') + '" data-historical="' + (historical ? '1' : '0') + '" data-date="' + esc(day) + '" data-state="' + esc(swing.state) + '" data-source="' + esc(swing.source_sha256 || '') + '"' + (pressure ? ' data-pressure-trigger-date="' + esc(pressure.trigger_date) + '" data-pressure-key="' + esc(pressure.key_price) + '"' : '') + (snapshot.rule_version ? ' data-rule="' + esc(snapshot.rule_version) + '"' : '') + ' aria-label="查看' + esc(row.stock_name) + '的前复权K线与峰谷证据（表格截至' + esc(day) + '）" title="' + (historical ? '查看指定历史日的同日结构证据' : '查看单股当前最新前复权结构；可能与表格快照日不同') + '">' + content + '</button>';
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

  var turnoverTrendDialog = document.getElementById('turnover-trend-dialog');
  var turnoverTrendSvg = document.getElementById('turnover-trend-svg');
  var turnoverTrendStatus = document.getElementById('turnover-trend-status');
  var turnoverTrendPlot = turnoverTrendDialog.querySelector('.turnover-trend-plot');
  var turnoverTrendTooltip = document.getElementById('turnover-trend-tooltip');
  var turnoverTrendController = null;
  var turnoverTrendTrigger = null;
  var turnoverTrendRows = [];
  function turnoverTrendHover(point) {
    if (!point) { turnoverTrendTooltip.hidden = true; return; }
    var row = turnoverTrendRows[Number(point.dataset.turnoverPoint)];
    if (!row) return;
    turnoverTrendTooltip.textContent = row.date + ' · 历史分位 ' + fixed(row.percentile, 1) + '%\n' +
      '7日截尾均值 ' + (row.trimmed_average_pct == null ? '未知' : fixed(row.trimmed_average_pct, 2) + '%') +
      ' · 有效样本 ' + (row.sample_count == null ? '未知' : row.sample_count) + ' 日';
    turnoverTrendTooltip.hidden = false;
    var plotWidth = turnoverTrendPlot.clientWidth;
    turnoverTrendTooltip.style.left = Math.max(4, Math.min(plotWidth - turnoverTrendTooltip.offsetWidth - 4,
      Number(point.getAttribute('cx')) * plotWidth / 820 - turnoverTrendTooltip.offsetWidth / 2)) + 'px';
    turnoverTrendTooltip.style.top = Math.max(4, Number(point.getAttribute('cy')) * turnoverTrendSvg.clientHeight / 300 - 68) + 'px';
  }
  async function showTurnoverTrend(trigger) {
    if (turnoverTrendController) turnoverTrendController.abort();
    var controller = new AbortController();
    turnoverTrendController = controller;
    turnoverTrendTrigger = trigger;
    turnoverTrendRows = [];
    turnoverTrendPlot.hidden = true;
    turnoverTrendTooltip.hidden = true;
    turnoverTrendSvg.innerHTML = '';
    document.getElementById('turnover-trend-title').textContent =
      (trigger.dataset.name || trigger.dataset.symbol) + ' ' + trigger.dataset.symbol + ' · 7日截尾均值换手历史分位';
    turnoverTrendStatus.textContent = '正在加载截至 ' + trigger.dataset.date + ' 的近一年历史分位…';
    if (!turnoverTrendDialog.open) turnoverTrendDialog.showModal();
    var query = new URLSearchParams({market: trigger.dataset.market, symbol: trigger.dataset.symbol, as_of_date: trigger.dataset.date});
    try {
      var response = await fetch('/api/stock-filter-turnover-trend?' + query.toString(), {signal: controller.signal});
      var payload = await response.json().catch(function () { throw new Error('换手历史分位接口未就绪或返回非JSON，请检查服务'); });
      if (controller.signal.aborted || !turnoverTrendDialog.open) return;
      if (!response.ok || !payload.ok) throw new Error(payload.error && (payload.error.message || payload.error) || '换手历史分位接口不可用');
      if (payload.as_of_date !== trigger.dataset.date || !Array.isArray(payload.rows)) throw new Error('趋势日期与筛选日期不一致或返回数据无效，拒绝绘制');
      var svg = turnoverTrendChart(payload.rows, trigger.dataset.date);
      if (!svg) throw new Error('筛选日期无效，无法绘制');
      turnoverTrendRows = payload.rows.filter(function (row) {
        var lower = new Date(trigger.dataset.date + 'T00:00:00Z');
        lower.setUTCFullYear(lower.getUTCFullYear() - 1);
        return row && /^\d{4}-\d{2}-\d{2}$/.test(row.date) && row.date >= lower.toISOString().slice(0, 10) &&
          row.date <= trigger.dataset.date && Number.isFinite(Date.parse(row.date + 'T00:00:00Z'));
      }).sort(function (a, b) { return a.date.localeCompare(b.date); });
      turnoverTrendSvg.innerHTML = svg;
      if (!turnoverTrendSvg.querySelector('[data-turnover-point]')) {
        turnoverTrendStatus.textContent = '该筛选日前一年暂无满足至少120个有效样本的历史分位；缺失日不补值。';
        return;
      }
      turnoverTrendPlot.hidden = false;
      turnoverTrendStatus.textContent = '筛选日 ' + trigger.dataset.date + ' · 近一年历史分位 · ' +
        turnoverTrendSvg.querySelectorAll('[data-turnover-point]').length + ' 个有效交易日（缺失日不插值）';
    } catch (error) {
      if (controller.signal.aborted || !turnoverTrendDialog.open) return;
      turnoverTrendPlot.hidden = true;
      turnoverTrendStatus.textContent = '无法绘制换手历史分位：' + (error.message || '未知错误');
    }
  }
  results.addEventListener('click', function (event) {
    var trigger = event.target.closest('[data-turnover-trend]');
    if (trigger && results.contains(trigger)) showTurnoverTrend(trigger);
  });
  turnoverTrendSvg.addEventListener('pointermove', function (event) {
    var rect = turnoverTrendSvg.getBoundingClientRect();
    var px = (event.clientX - rect.left) * 820 / rect.width;
    if (px < 56 || px > 790) { turnoverTrendHover(null); return; }
    var points = Array.prototype.slice.call(turnoverTrendSvg.querySelectorAll('[data-turnover-point]'));
    var nearest = points.reduce(function (best, point) {
      return !best || Math.abs(Number(point.getAttribute('cx')) - px) < Math.abs(Number(best.getAttribute('cx')) - px) ? point : best;
    }, null);
    turnoverTrendHover(nearest && Math.abs(Number(nearest.getAttribute('cx')) - px) <= 12 ? nearest : null);
  });
  turnoverTrendSvg.addEventListener('pointerleave', function () { turnoverTrendHover(null); });
  turnoverTrendSvg.addEventListener('focusin', function (event) {
    var point = event.target.closest('[data-turnover-point]');
    if (point) turnoverTrendHover(point);
  });
  turnoverTrendSvg.addEventListener('focusout', function () { turnoverTrendHover(null); });
  turnoverTrendDialog.querySelector('.turnover-trend-close').addEventListener('click', function () { turnoverTrendDialog.close(); });
  turnoverTrendDialog.addEventListener('click', function (event) { if (event.target === turnoverTrendDialog) turnoverTrendDialog.close(); });
  turnoverTrendDialog.addEventListener('close', function () {
    if (turnoverTrendDialog.open) return;
    if (turnoverTrendController) turnoverTrendController.abort();
    if (turnoverTrendTrigger && turnoverTrendTrigger.isConnected) turnoverTrendTrigger.focus();
    turnoverTrendController = null; turnoverTrendTrigger = null;
    turnoverTrendRows = [];
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
    swingChartMeta.textContent = trigger.dataset.symbol + (trigger.dataset.historical === '1' ? '｜正在加载历史日 ' + trigger.dataset.date : '｜正在计算单股当前最新有效前复权结构（表格截至 ' + trigger.dataset.date + '）') + ' 的峰谷、成交量、MACD、RPS证据…';
    if (!swingChartDialog.open) swingChartDialog.showModal();
    var query = new URLSearchParams({market: trigger.dataset.market, symbol: trigger.dataset.symbol});
    if (trigger.dataset.historical === '1') query.set('as_of_date', trigger.dataset.date);
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
      var historicalSwing = trigger.dataset.historical === '1';
      if (data.market !== trigger.dataset.market || data.symbol !== trigger.dataset.symbol ||
          !data.as_of_date || observation.last_bar_date !== data.as_of_date ||
          observation.status !== 'ok' || data.price_basis !== 'tdx_export_qfq' ||
          (historicalSwing && (data.as_of_date !== trigger.dataset.date ||
            observation.state !== trigger.dataset.state ||
            (trigger.dataset.source && observation.source_sha256 !== trigger.dataset.source) ||
            (trigger.dataset.pressureTriggerDate && (observation.pressure_line?.trigger_date !== trigger.dataset.pressureTriggerDate ||
              String(observation.pressure_line?.key_price) !== trigger.dataset.pressureKey)) ||
            (trigger.dataset.rule && data.rule_version !== trigger.dataset.rule))) ||
          (!historicalSwing && (data.source_type !== 'live_qfq' || !observation.source_sha256))) {
        throw new Error('详情前复权源、证券代码或结构证据不一致，拒绝绘制。');
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
      swingChartMeta.textContent = trigger.dataset.symbol + ' ' + (data.name || trigger.dataset.name || '') +
        (historicalSwing ? '｜历史筛选与结构同日 ' + data.as_of_date : '｜表格结构截至 ' + trigger.dataset.date + '（已发布快照）｜单股当前前复权截至 ' + data.as_of_date + '（本地即时计算；可能与表格状态不同）') +
        '｜结构 ' + (observation.state || '证据不足') +
        '｜有效日线 ' + evidence.bars.length + ' 根｜实心峰谷=确认，虚线圈=候选' +
        (SwingChart.verifiedBox(observation) ? '｜箱体检验通过：前三组边界／第四组核验' : '｜当前无通过检验的箱体') + '｜RPS' +
        (evidence.rpsAsOf ? '截至 ' + evidence.rpsAsOf + (evidence.rpsAsOf === data.as_of_date ? '' : '（当日缺失，不补值）') : '不可用（未绘制）') +
        (rpsOk ? '' : '；RPS接口读取失败');
    } catch (error) {
      if (controller.signal.aborted || !swingChartDialog.open) return;
      swingChartDialog.querySelector('.swing-chart-scroll').hidden = true;
      swingChartData = null; swingChartBars = null;
      swingChartMeta.textContent = (trigger.dataset.historical === '1' ? '无法绘制历史同日证据：' : '无法绘制单股当前前复权结构：') + (error.message || '未知错误');
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
  function updateWatchlistSelection() {
    watchlistSelectedCount.textContent = '已选 ' + selectedStocks.size + ' 只';
    addToWatchlist.disabled = addingToWatchlist || selectedStocks.size === 0;
  }
  function clearWatchlistSelection() {
    selectedStocks.clear();
    results.querySelectorAll('[data-stock-select]').forEach(function (input) { input.checked = false; });
    watchlistFeedback.textContent = '';
    watchlistFeedback.classList.remove('error');
    updateWatchlistSelection();
  }
  results.addEventListener('change', function (event) {
    var input = event.target;
    if (!input.matches('[data-stock-select]')) return;
    var stock = {market: input.dataset.market, symbol: input.dataset.symbol};
    var key = stock.market + ':' + stock.symbol;
    if (input.checked) selectedStocks.set(key, stock);
    else selectedStocks.delete(key);
    watchlistFeedback.textContent = '';
    watchlistFeedback.classList.remove('error');
    updateWatchlistSelection();
  });
  addToWatchlist.addEventListener('click', async function () {
    if (addingToWatchlist || !selectedStocks.size) return;
    var stocks = Array.from(selectedStocks.values());
    addingToWatchlist = true;
    updateWatchlistSelection();
    watchlistFeedback.textContent = '正在加入自选…';
    watchlistFeedback.classList.remove('error');
    try {
      var response = await fetch('/api/watchlist/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({stocks: stocks})
      });
      var data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error && (data.error.message || data.error) || '自选股服务未返回有效结果');
      stocks.forEach(function (stock) { selectedStocks.delete(stock.market + ':' + stock.symbol); });
      results.querySelectorAll('[data-stock-select]').forEach(function (input) {
        input.checked = selectedStocks.has(input.dataset.market + ':' + input.dataset.symbol);
      });
      watchlistFeedback.textContent = '已加入自选 ' + data.added + ' 只，已存在 ' + data.skipped + ' 只。' + (asOfDate.value ? '历史筛选结果按当前时间加入自选。' : '');
    } catch (error) {
      watchlistFeedback.classList.add('error');
      watchlistFeedback.textContent = '加入自选失败：' + (error.message || '请重试');
    } finally {
      addingToWatchlist = false;
      updateWatchlistSelection();
    }
  });
  function renderFinancialQuarterCharts(payload) {
    var fragment = document.createDocumentFragment();
    QuarterlyFinancialChart.METRICS.forEach(function (metric) {
      var rendered = QuarterlyFinancialChart.renderQuarterMetric(payload, metric.key);
      var card = document.createElement('section');
      card.className = 'financial-quarter-chart-card';
      var title = document.createElement('h3');
      title.textContent = metric.label + ' · 单季度';
      var basis = document.createElement('p');
      basis.textContent = metric.basis + ' · ' + metric.unit;
      var chart = document.createElement('div');
      chart.className = 'financial-quarter-chart-scroll';
      chart.setAttribute('role', 'img');
      chart.setAttribute('aria-label', rendered.ariaLabel);
      if (rendered.svg) chart.innerHTML = rendered.svg;
      else {
        var empty = document.createElement('p');
        empty.className = 'financial-quarter-dialog-state';
        empty.textContent = rendered.emptyMessage;
        chart.appendChild(empty);
      }
      card.append(title, basis, chart);
      fragment.appendChild(card);
    });
    financialQuarterCharts.replaceChildren(fragment);
  }

  async function showFinancialQuarterHistory(trigger) {
    if (financialQuarterController) financialQuarterController.abort();
    var controller = new AbortController();
    financialQuarterController = controller;
    financialQuarterTrigger = trigger;
    var market = trigger.dataset.market;
    var symbol = trigger.dataset.symbol;
    var name = trigger.dataset.stockName || symbol;
    financialQuarterTitle.textContent = name + ' ' + symbol + ' · 单季度财务指标';
    financialQuarterMeta.textContent = '正在读取过去5个完整年度及今年已披露季度…';
    financialQuarterCharts.innerHTML = '<p class="financial-quarter-dialog-state">正在加载七项财务指标…</p>';
    if (!financialQuarterDialog.open) financialQuarterDialog.showModal();
    try {
      var query = new URLSearchParams({ market: market, symbol: symbol, years: '30' });
      var response = await fetch('/api/stock-score-report-history?' + query.toString(), { signal: controller.signal });
      var payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error && payload.error.message || '财务报告历史不可用');
      if (controller.signal.aborted || !financialQuarterDialog.open || financialQuarterTrigger !== trigger) return;
      var reports = Array.isArray(payload.reports) ? payload.reports : [];
      var periods = reports.map(function (row) { return String(row.period || ''); }).filter(Boolean);
      financialQuarterMeta.textContent = (periods.length ? '报告期 ' + periods[0] + '—' + periods[periods.length - 1] + '｜' : '') +
        '最多5个完整年度＋今年已披露季度；不足5年显示全部历史｜累计值逐季差分｜金额亿元、EPS元/股｜正值红、负值绿。';
      renderFinancialQuarterCharts(payload);
    } catch (error) {
      if (controller.signal.aborted || !financialQuarterDialog.open) return;
      financialQuarterMeta.textContent = '单季度财务指标加载失败。';
      financialQuarterCharts.innerHTML = '<p class="financial-quarter-dialog-state">' + esc(error.message || '未知错误') + '</p>';
    }
  }

  results.addEventListener('click', function (event) {
    var trigger = event.target.closest('.financial-history-trigger');
    if (trigger && results.contains(trigger) && !asOfDate.value) showFinancialQuarterHistory(trigger);
  });
  document.getElementById('financial-quarter-history-close').addEventListener('click', function () { financialQuarterDialog.close(); });
  financialQuarterDialog.addEventListener('close', function () {
    if (financialQuarterDialog.open) return;
    if (financialQuarterController) financialQuarterController.abort();
    financialQuarterController = null;
    var trigger = financialQuarterTrigger;
    financialQuarterTrigger = null;
    if (trigger && trigger.isConnected) trigger.focus();
  });

  function renderRows(data) {
    if (!(data.rows || []).length) {
      results.innerHTML = '<tr><td colspan="11" class="empty-state">没有符合当前条件的股票。可以放宽区间或点击重置后重新筛选。</td></tr>';
      return;
    }
    results.innerHTML = data.rows.map(function (row) {
      var href = '/stock-analysis.html?market=' + encodeURIComponent(row.market) + '&symbol=' + encodeURIComponent(row.symbol) + '&name=' + encodeURIComponent(row.stock_name || '');
      var market = esc(row.market).replace(/"/g, '&quot;');
      var symbol = esc(row.symbol).replace(/"/g, '&quot;');
      var checked = selectedStocks.has(row.market + ':' + row.symbol) ? ' checked' : '';
      var nicheLeader = String(row.niche_leader || '').trim();
      var nicheBadge = nicheLeader ? '<span class="niche-leader-badge" title="细分龙头标签：' + esc(nicheLeader).replace(/"/g, '&quot;') + '" aria-label="细分龙头">龙</span>' : '';
      return '<tr>' +
        '<td class="select-cell"><input type="checkbox" data-stock-select data-market="' + market + '" data-symbol="' + symbol + '" aria-label="选择 ' + market + ':' + symbol + '"' + checked + '></td>' +
        '<td>' + nicheBadge + '<a class="stock-link" href="' + href + '">' + esc(row.stock_name) + '</a><span class="stock-code">' + esc(row.market) + ':' + esc(row.symbol) + '</span></td>' +
        '<td>' + esc(row.industry) + '</td>' +
        '<td class="num" title="' + esc(basicMarketTitle(row)).replace(/"/g, '&quot;') + '">' + priceCell(row, data.data_as_of) + '</td>' +
        '<td>' + valuationCell(row) + '</td>' +
        '<td class="num">' + turnoverCell(row, data.data_as_of) + '</td>' +
        '<td>' + relativeStrengthCell(row) + '</td>' +
        '<td>' + annualHealthCell(row, data.is_historical) + '</td>' +
        '<td>' + healthCell(row.quarterly_total, row.quarterly_period) + '</td>' +
        '<td class="num">' + marketCapCell(row) + '</td>' +
        '<td class="swing-cell">' + swingCell(row, data.swing_snapshot || {as_of_date: data.data_as_of}, data.is_historical) + '</td>' +
      '</tr>';
    }).join('');
  }

  function temperatureCurrentCell(row) {
    if (row.temperature === null || row.temperature === undefined || row.temperature === '') return '<span class="temperature-current" data-level="unknown">数据不足</span>';
    var level = Number(row.temperature);
    if (!Number.isInteger(level) || level < 0 || level > 5) return '<span class="temperature-current" data-level="unknown">数据不足</span>';
    return '<span class="temperature-current" data-level="' + level + '" title="当前10日行业温度档位 ' + level + '">' + esc(row.temperature_label || '数据不足') + '（' + level + '）</span>';
  }

  function temperatureChangeCell(row) {
    var change = Number(row.temperature_change);
    var valid = Number.isFinite(change) && row.temperature_previous !== null && row.temperature_previous !== undefined;
    if (!valid) return '<span class="temperature-change unknown">数据不足</span>';
    var trend = ['warming', 'cooling', 'flat'].includes(row.temperature_trend) ? row.temperature_trend : (change > 0 ? 'warming' : change < 0 ? 'cooling' : 'flat');
    var sign = change > 0 ? '+' : '';
    var title = (row.temperature_previous_label || '数据不足') + '（' + row.temperature_previous + '）→ ' +
      (row.temperature_label || '数据不足') + '（' + row.temperature + '）' +
      (row.temperature_previous_gap_days == null ? '' : '；前次有效温度距今 ' + row.temperature_previous_gap_days + ' 个交易日');
    return '<span class="temperature-change ' + trend + '" title="' + esc(title).replace(/"/g, '&quot;') + '">' +
      esc(row.temperature_trend_label || (change > 0 ? '升温' : change < 0 ? '降温' : '持平')) + ' ' + sign + change + '</span>';
  }

  function renderIndustryDistribution(data) {
    var distribution = data && data.industry_distribution;
    latestIndustryDistribution = distribution || null;
    openIndustryDistribution.disabled = !distribution;
    if (!distribution) return;
    var rows = distribution.rows || [];
    var maxPct = rows.reduce(function (max, row) { return Math.max(max, Number(row.pct) || 0); }, 0) || 1;
    industryDistributionMeta.textContent = '筛选结果 ' + Number(distribution.total || 0).toLocaleString('zh-CN') +
      ' 只 · 已分类 ' + Number(distribution.classified || 0).toLocaleString('zh-CN') +
      ' 只 · 二级行业 ' + rows.filter(function (row) { return row.industry_name !== '未分类'; }).length +
      ' 个 · 未分类 ' + Number(distribution.unknown || 0).toLocaleString('zh-CN') + ' 只 · 数据日期 ' + (data.data_as_of || '—') +
      ' · 温度' + (distribution.temperature_window || '—') + '日截至 ' + (distribution.temperature_as_of || '未知');
    industryDistributionDefinition.textContent = '按当前完整筛选结果统计，不受每页50只分页影响；行业归属采用当前申万二级行业映射' +
      (data.is_historical ? '（历史筛选日仍使用当前行业归属，不代表历史时点成分）' : '') +
      '；当前温度与变化读取当前10日行业温度快照，不随历史筛选日期回溯。';
    industryDistributionRows.innerHTML = rows.map(function (row, index) {
      var pct = Number(row.pct) || 0;
      var width = Math.max(pct > 0 ? 2 : 0, pct / maxPct * 100);
      return '<tr><td class="industry-dist-rank">' + (index + 1) + '</td>' +
        '<td class="industry-dist-name">' + esc(row.industry_name) + (row.industry_code ? '<span class="industry-dist-code">' + esc(row.industry_code) + '</span>' : '') + '</td>' +
        '<td>' + temperatureCurrentCell(row) + '</td>' +
        '<td>' + temperatureChangeCell(row) + '</td>' +
        '<td class="num">' + Number(row.count || 0).toLocaleString('zh-CN') + '</td>' +
        '<td class="num">' + fixed(pct, 2) + '%</td>' +
        '<td><div class="industry-share-track" aria-label="' + esc(row.industry_name) + '占比' + fixed(pct, 2) + '%"><span class="industry-share-bar" style="width:' + width.toFixed(2) + '%"></span></div></td></tr>';
    }).join('') || '<tr><td colspan="7" class="empty-state">当前筛选结果为空。</td></tr>';
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
    var selection = data.scope_selection || {};
    var hasCustomScope = (selection.industry_l2_codes || []).length || (selection.industry_temperature_levels || []).length || (selection.concept_codes || []).length || (selection.concept_temperature_levels || []).length;
    var scopeText = hasCustomScope
      ? '行业/概念范围 ' + Number(data.total_universe || 0).toLocaleString('zh-CN') + ' 只（全市场 ' + Number(data.universe_total || 0).toLocaleString('zh-CN') + '）'
      : scopeLabel === '全部'
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
    renderIndustryDistribution(data);
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
    var requestId = ++runSequence;
    if (priceTrendDialog.open) priceTrendDialog.close();
    if (turnoverTrendDialog.open) turnoverTrendDialog.close();
    if (swingChartDialog.open) swingChartDialog.close();
    if (historicalRetryTimer) {
      window.clearTimeout(historicalRetryTimer);
      historicalRetryTimer = null;
    }
    currentPage = page || 1;
    status.classList.remove('error');
    status.textContent = '正在按全市场条件筛选…';
    openIndustryDistribution.disabled = true;
    latestIndustryDistribution = null;
    if (industryDistributionDialog.open) industryDistributionDialog.close();
    results.innerHTML = '<tr><td colspan="11" class="empty-state">正在加载筛选结果…</td></tr>';
    pages.innerHTML = '';
    try {
      var response = await fetch('/api/stock-filter?' + requestParams(currentPage).toString());
      var data = await response.json();
      if (requestId !== runSequence) return;
      if (data.error && data.error.code === 'historical_snapshot_building') {
        scheduleHistoricalSnapshotRetry(currentPage, data.error.message || '快照构建中', data.error.progress);
        return;
      }
      if (!response.ok || !data.ok) throw new Error(data.error && data.error.message || '筛选服务未返回有效结果');
      render(data);
    } catch (error) {
      if (requestId !== runSequence) return;
      matchCount.textContent = '—';
      status.classList.add('error');
      status.textContent = error.message;
      results.innerHTML = '<tr><td colspan="11" class="empty-state">无法读取筛选结果。请检查数据快照后重试。</td></tr>';
    }
  }

  openIndustryDistribution.addEventListener('click', function () {
    if (!latestIndustryDistribution) return;
    if (typeof industryDistributionDialog.showModal === 'function') industryDistributionDialog.showModal();
    else industryDistributionDialog.setAttribute('open', 'open');
  });
  document.getElementById('industry-distribution-close').addEventListener('click', function () { industryDistributionDialog.close(); });
  industryDistributionDialog.addEventListener('click', function (event) {
    if (event.target === industryDistributionDialog) industryDistributionDialog.close();
  });


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
  form.addEventListener('input', clearWatchlistSelection);
  form.addEventListener('change', clearWatchlistSelection);
  form.addEventListener('submit', function (event) { event.preventDefault(); clearWatchlistSelection(); run(1); });
  form.addEventListener('reset', function () { clearWatchlistSelection(); window.setTimeout(function () { clearScopeSelection(false); setPreset(''); updateHistoricalMode(); run(1); }, 0); });
  Array.prototype.slice.call(document.querySelectorAll('.filter-group-toggle')).forEach(function (button) {
    button.addEventListener('click', function () {
      var group = button.closest('fieldset');
      var collapsed = group.classList.toggle('is-collapsed');
      button.setAttribute('aria-expanded', String(!collapsed));
    });
  });
  presetOptions.forEach(function (option) {
    option.addEventListener('click', function () {
      togglePreset(option.dataset.preset);
      clearWatchlistSelection();
      run(1);
    });
  });
  function updateHistoricalMode() {
    var historical = Boolean(asOfDate.value);
    var capabilities = window.StockFilterHistoryCapabilities;
    if (!capabilities) throw new Error('历史日期筛选能力模块未加载');
    capabilities.applyHistoricalFieldState(form, historical);
    capabilities.applyHistoricalSortState(sort, historical);
    ['rps', 'technical', 'relative-strength'].forEach(function (groupName) {
      var group = document.querySelector('[data-filter-group="' + groupName + '"]');
      if (!group) return;
      group.classList.toggle('history-disabled-group', historical);
      var groupToggle = group.querySelector('.filter-group-toggle');
      if (historical) {
        group.dataset.historyBadge = '历史不可用';
        if (groupToggle) groupToggle.dataset.historyBadge = '历史不可用';
      } else {
        delete group.dataset.historyBadge;
        if (groupToggle) delete groupToggle.dataset.historyBadge;
      }
    });
    var stockScope = form.elements.stock_scope;
    [stockScope.closest('label'), document.querySelector('label[for="sort"]')].forEach(function (control) {
      if (!control) return;
      control.classList.toggle('history-partial-control', historical);
      if (historical) control.dataset.historyBadge = '部分选项不可用';
      else delete control.dataset.historyBadge;
    });
    var csi300Option = Array.prototype.slice.call(stockScope.options).find(function (option) { return option.value === 'csi300'; });
    if (csi300Option) {
      csi300Option.disabled = historical;
      csi300Option.title = historical ? '沪深300使用当前成分，仅支持最新日期。' : '';
    }
    if (historical && stockScope.value === 'csi300') stockScope.value = 'all';
    industryScopeOpen.disabled = historical || !scopeCatalog;
    conceptScopeOpen.disabled = historical || !scopeCatalog;
    industryScopeOpen.title = historical ? '行业成员与行业温度均使用当前快照，仅支持最新日期。' : '';
    conceptScopeOpen.title = historical ? '概念成员与概念温度均使用当前快照，仅支持最新日期。' : '';
    [industryScopeOpen, conceptScopeOpen].forEach(function (button) {
      button.classList.toggle('history-disabled-field', historical);
      if (historical) button.dataset.historyBadge = '历史不可用';
      else delete button.dataset.historyBadge;
    });
    if (historical) {
      selectedIndustryCodes.clear();
      selectedIndustryTemperatureLevels.clear();
      selectedConceptCodes.clear();
      selectedTemperatureLevels.clear();
    }
    results.querySelectorAll('.financial-history-trigger').forEach(function (button) {
      button.disabled = historical;
      button.title = historical ? '历史筛选日期不展示当前财报历史，避免未来数据泄漏。' : '查看七项单季度财务指标历史';
    });
    syncScopeInputs();
    renderScopeSummary();
  }

  sort.addEventListener('change', function () { clearWatchlistSelection(); run(1); });
  asOfDate.addEventListener('change', function () {
    var historical = Boolean(asOfDate.value);
    var removedCurrentScope = historical && (selectedIndustryCodes.size || selectedIndustryTemperatureLevels.size || selectedConceptCodes.size || selectedTemperatureLevels.size || form.elements.stock_scope.value === 'csi300');
    updateHistoricalMode();
    // Date is sent as as_of_date by requestParams; the server rejects a missing
    // point-in-time snapshot rather than falling back to current fundamentals.
    status.textContent = asOfDate.value
      ? (removedCurrentScope
          ? '已选择历史信号日期；当前行业/概念范围或沪深300成分已清除，仅保留有同日历史证据的条件。'
          : '已选择历史信号日期；仅最新条件已清空并禁用，悬停可查看原因。')
      : '已切回最新数据。';
  });
  loadScopeCatalog();
  run(1);
}());
