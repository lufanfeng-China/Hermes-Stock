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
  var multi = { trend_daily: true, trend_weekly: true, trend_monthly: true, macd_cross: true, golden_cross: true };

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
      if (!field.name || field.disabled) return;
      if (multi[field.name]) {
        var values = selectedValues(field);
        if (values.length) query.set(field.name, values.join(','));
        return;
      }
      if (String(field.value || '').trim()) query.set(field.name, field.value);
    });
    query.set('page', String(page));
    query.set('page_size', '50');
    return query;
  }

  function rpsCell(row) {
    return '<span class="rps-total">' + fixed(row.rps_total) + '</span>' +
      '<span class="subvalue rps-split">' + [row.rps_20, row.rps_50, row.rps_120, row.rps_250].map(function (value) { return fixed(value, 0); }).join(' / ') + '</span>';
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

  function priceCell(row) {
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
    var label = '五年分位 ' + (valid ? fixed(raw, 1) + '%' : '—') + (valid && sinceListing ? '（上市以来）' : '');
    return fixed(row.price, 2) + '<span class="subvalue" title="' + esc(title) + '">' + label + '</span>';
  }

  function valuationCell(row) {
    return '<span class="health">PE ' + fixed(row.pe_ttm, 2) + '</span><span class="subvalue">PS ' + fixed(row.ps_ttm, 2) + '</span>';
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

  function renderRows(data) {
    if (!(data.rows || []).length) {
      results.innerHTML = '<tr><td colspan="10" class="empty-state">没有符合当前条件的股票。可以放宽区间或点击重置后重新筛选。</td></tr>';
      return;
    }
    results.innerHTML = data.rows.map(function (row) {
      var href = '/stock-analysis.html?market=' + encodeURIComponent(row.market) + '&symbol=' + encodeURIComponent(row.symbol) + '&name=' + encodeURIComponent(row.stock_name || '');
      return '<tr>' +
        '<td><a class="stock-link" href="' + href + '">' + esc(row.stock_name) + '</a><span class="stock-code">' + esc(row.market) + ':' + esc(row.symbol) + '</span></td>' +
        '<td>' + esc(row.industry) + '</td>' +
        '<td class="num">' + priceCell(row) + '</td>' +
        '<td>' + valuationCell(row) + '</td>' +
        '<td class="num">' + rpsCell(row) + '</td>' +
        '<td>' + relativeStrengthCell(row) + '</td>' +
        '<td>' + healthCell(row.annual_total, row.annual_period) + '</td>' +
        '<td>' + healthCell(row.quarterly_total, row.quarterly_period) + '</td>' +
        '<td class="num">' + reportReleaseReturnCell(row) + '</td>' +
        '<td class="num">' + epsRatioCell(row) + '</td>' +
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
    status.textContent = scopeText + ' · 数据日期 ' + (data.data_as_of || '—') + historical + ' · 已因已启用字段缺失排除 ' + Number(data.excluded_missing || 0).toLocaleString('zh-CN') + ' 只';
    renderRows(data);
    renderPagination(data);
  }

  function scheduleHistoricalSnapshotRetry(page, message, progress) {
    matchCount.textContent = '—';
    status.classList.remove('error');
    var percent = Math.max(0, Math.min(100, Number(progress && progress.percent) || 0));
    var stage = progress && progress.stage || '正在准备历史快照';
    status.textContent = '正在生成历史快照：' + stage + '（' + percent + '%），将自动重试。';
    results.innerHTML = '<tr><td colspan="10" class="empty-state"><div>首次选择该交易日需生成公告日 point-in-time 快照；页面会自动刷新，无需重复点击。</div><progress value="' + percent + '" max="100"></progress><strong> ' + percent + '%</strong></td></tr>';
    pages.innerHTML = '';
    if (historicalRetryTimer) window.clearTimeout(historicalRetryTimer);
    historicalRetryTimer = window.setTimeout(function () {
      historicalRetryTimer = null;
      run(page);
    }, 3000);
  }

  async function run(page) {
    if (historicalRetryTimer) {
      window.clearTimeout(historicalRetryTimer);
      historicalRetryTimer = null;
    }
    currentPage = page || 1;
    status.classList.remove('error');
    status.textContent = '正在按全市场条件筛选…';
    results.innerHTML = '<tr><td colspan="10" class="empty-state">正在加载筛选结果…</td></tr>';
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
      results.innerHTML = '<tr><td colspan="10" class="empty-state">无法读取筛选结果。请检查数据快照后重试。</td></tr>';
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
