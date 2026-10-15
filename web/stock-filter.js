(function () {
  'use strict';

  var form = document.getElementById('filter-form');
  var results = document.getElementById('results');
  var status = document.getElementById('status');
  var pages = document.getElementById('pagination');
  var matchCount = document.getElementById('match-count');
  var sort = document.getElementById('sort');
  var presetInput = form.elements.preset;
  var presetOptions = Array.prototype.slice.call(document.querySelectorAll('[data-preset]'));
  var currentPage = 1;
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

  function healthCell(score, period) {
    return '<span class="health">' + fixed(score) + '</span>' + (period ? '<span class="subvalue">' + esc(period) + '</span>' : '');
  }

  function renderRows(data) {
    if (!(data.rows || []).length) {
      results.innerHTML = '<tr><td colspan="8" class="empty-state">没有符合当前条件的股票。可以放宽区间或点击重置后重新筛选。</td></tr>';
      return;
    }
    results.innerHTML = data.rows.map(function (row) {
      var href = '/stock-analysis.html?market=' + encodeURIComponent(row.market) + '&symbol=' + encodeURIComponent(row.symbol) + '&name=' + encodeURIComponent(row.stock_name || '');
      var trend = [row.trend_daily_label || row.trend_label, row.trend_weekly_label, row.trend_monthly_label].map(function (value) { return esc(value); }).join(' / ');
      var cross = [row.macd_cross_label, row.golden_cross_label].filter(Boolean).map(esc).join('<br>') || '—';
      return '<tr>' +
        '<td><a class="stock-link" href="' + href + '">' + esc(row.stock_name) + '</a><span class="stock-code">' + esc(row.market) + ':' + esc(row.symbol) + '</span></td>' +
        '<td>' + esc(row.industry) + '</td>' +
        '<td class="num">' + fixed(row.price, 2) + '</td>' +
        '<td class="num">' + rpsCell(row) + '</td>' +
        '<td>' + healthCell(row.annual_total, row.annual_period) + '</td>' +
        '<td>' + healthCell(row.quarterly_total, row.quarterly_period) + '</td>' +
        '<td>' + trend + '</td>' +
        '<td>' + cross + '</td>' +
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
    status.textContent = '全市场 ' + Number(data.total_universe || 0).toLocaleString('zh-CN') + ' 只 · 数据日期 ' + (data.data_as_of || '—') + ' · 已因已启用字段缺失排除 ' + Number(data.excluded_missing || 0).toLocaleString('zh-CN') + ' 只';
    renderRows(data);
    renderPagination(data);
  }

  async function run(page) {
    currentPage = page || 1;
    status.classList.remove('error');
    status.textContent = '正在按全市场条件筛选…';
    results.innerHTML = '<tr><td colspan="8" class="empty-state">正在加载筛选结果…</td></tr>';
    pages.innerHTML = '';
    try {
      var response = await fetch('/api/stock-filter?' + requestParams(currentPage).toString());
      var data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error && data.error.message || '筛选服务未返回有效结果');
      render(data);
    } catch (error) {
      matchCount.textContent = '—';
      status.classList.add('error');
      status.textContent = error.message;
      results.innerHTML = '<tr><td colspan="8" class="empty-state">无法读取筛选结果。请检查数据快照后重试。</td></tr>';
    }
  }

  form.addEventListener('submit', function (event) { event.preventDefault(); run(1); });
  form.addEventListener('reset', function () { window.setTimeout(function () { setPreset(presetInput.value); run(1); }, 0); });
  document.getElementById('reset-top').addEventListener('click', function () { form.reset(); });
  presetOptions.forEach(function (option) {
    option.addEventListener('click', function () { form.reset(); setPreset(option.dataset.preset); });
  });
  sort.addEventListener('change', function () { run(1); });
  run(1);
}());
