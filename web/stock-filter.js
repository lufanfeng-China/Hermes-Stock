(function () {
  'use strict';
  var form = document.getElementById('filter-form');
  var results = document.getElementById('results');
  var meta = document.getElementById('meta');
  var pages = document.getElementById('pagination');
  var error = document.getElementById('error');
  var currentPage = 1;
  function esc(v) { var d = document.createElement('div'); d.textContent = v == null ? '—' : String(v); return d.innerHTML; }
  function score(v) { return v == null ? '—' : Number(v).toFixed(1); }
  function params(page) {
    var p = new URLSearchParams(), multi = { trend: true, macd_cross: true, golden_cross: true }, values = {};
    new FormData(form).forEach(function (value, key) {
      if (!String(value).trim()) return;
      if (multi[key]) { (values[key] || (values[key] = [])).push(value); } else { p.set(key, value); }
    });
    Object.keys(values).forEach(function (key) { p.set(key, values[key].join(',')); });
    p.set('page', String(page)); p.set('page_size', '50'); return p;
  }
  function render(data) {
    results.innerHTML = (data.rows || []).map(function (r) {
      var href = '/stock-analysis.html?market=' + encodeURIComponent(r.market) + '&symbol=' + encodeURIComponent(r.symbol) + '&name=' + encodeURIComponent(r.stock_name || '');
      return '<tr><td><a href="' + href + '"><strong>' + esc(r.stock_name) + '</strong> ' + esc(r.market) + ':' + esc(r.symbol) + '</a></td><td>' + esc(r.industry) + '</td><td class="num">' + score(r.rps_total) + '</td><td>' + score(r.annual_total) + (r.annual_period ? ' <small class="muted">' + esc(r.annual_period) + '</small>' : '') + '</td><td>' + score(r.quarterly_total) + (r.quarterly_period ? ' <small class="muted">' + esc(r.quarterly_period) + '</small>' : '') + '</td><td>' + esc(r.short_trend_label || r.trend_label) + '</td><td>' + esc(r.macd_cross_label) + '</td><td>' + esc(r.golden_cross_label) + '</td></tr>';
    }).join('') || '<tr><td colspan="8" class="muted">没有符合条件的股票。</td></tr>';
    meta.textContent = '命中 ' + data.total_matched + ' / 全市场 ' + data.total_universe + '｜数据日期 ' + (data.data_as_of || '—') + '｜字段缺失排除 ' + (data.excluded_missing || 0) + '｜第 ' + data.page + '/' + data.total_pages + ' 页，每页 50 只';
    pages.innerHTML = '';
    function button(label, target, disabled) { var b = document.createElement('button'); b.type = 'button'; b.className = 'nav-link'; b.textContent = label; b.disabled = disabled; b.onclick = function () { run(target); }; pages.appendChild(b); }
    button('上一页', data.page - 1, data.page <= 1); button('下一页', data.page + 1, data.page >= data.total_pages);
  }
  async function run(page) {
    currentPage = page || 1; error.classList.add('hidden'); meta.textContent = '正在按全市场条件筛选…';
    try { var response = await fetch('/api/stock-filter?' + params(currentPage)); var data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error && data.error.message || '筛选失败'); render(data); }
    catch (e) { error.textContent = e.message; error.classList.remove('hidden'); meta.textContent = '筛选失败'; }
  }
  form.addEventListener('submit', function (event) { event.preventDefault(); run(1); });
  form.addEventListener('reset', function () { window.setTimeout(function () { run(1); }, 0); });
  run(1);
}());
