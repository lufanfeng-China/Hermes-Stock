(function () {
  'use strict';
  var dateEl = document.getElementById('as-of-date');
  var statusEl = document.getElementById('status');
  var resultsEl = document.getElementById('results');
  var disclosureEl = document.getElementById('disclosure');
  var retryTimer = null;
  var requestId = 0;

  function esc(value) {
    return String(value == null ? '—' : value).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function number(value, suffix, digits) {
    if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
    return Number(value).toFixed(digits == null ? 2 : digits) + (suffix || '');
  }
  function evidenceLine(label, value) {
    return '<div><dt>' + label + '</dt><dd>' + value + '</dd></div>';
  }
  function renderCandidate(row) {
    var e = row.evidence || {};
    var query = new URLSearchParams({market: row.market || '', symbol: row.symbol || '', name: row.stock_name || ''});
    return '<article class="fw-card"><header><div><a class="stock-link" href="/stock-analysis.html?' + esc(query.toString()) + '">' + esc(row.stock_name) + '</a> <span class="stock-code">' + esc(row.market) + ':' + esc(row.symbol) + '</span></div><span class="eligible">四条件全部符合</span></header>' +
      '<p class="candidate-meta">数据日 ' + esc(row.as_of_date) + ' · 信号日 ' + esc(row.signal_date) + ' · 前复权收盘价 ' + number(row.current_close) + '</p>' +
      '<dl class="fw-grid">' +
      evidenceLine('截至昨日20日涨幅', number(e.prior_20d_return_pct, '%')) +
      evidenceLine('当量 / 此前20日最小量', number(e.volume_multiple, ' 倍')) +
      evidenceLine('当天前复权涨幅', number(e.day_return_pct, '%')) +
      evidenceLine('当日开盘 / 收盘（前复权）', number(e.current_open) + ' / ' + number(row.current_close)) +
      evidenceLine('此前20日最大量 / 最小量', number(e.prior_volume_spread, ' 倍')) +
      evidenceLine('当天成交量（原始单位）', number(e.current_volume)) +
      evidenceLine('此前20日最小量（原始单位）', number(e.prior_20d_min_volume)) +
      evidenceLine('此前20日最大量（原始单位）', number(e.prior_20d_max_volume)) +
      '</dl><details><summary>展开审计证据（原始字段）</summary><pre>' + esc(JSON.stringify({classification: row.classification, evidence: e}, null, 2)) + '</pre></details></article>';
  }
  function render(payload) {
    var groups = payload.groups || {};
    var items = groups.main || [];
    disclosureEl.textContent = payload.disclosure || '';
    resultsEl.innerHTML = '<section aria-label="当日四条件候选"><h2>当日四条件候选 <small>' + items.length + ' 只</small></h2>' +
      (items.map(renderCandidate).join('') || '<p class="empty">当日无同时满足全部四条件的候选。</p>') + '</section>';
  }
  async function load() {
    var activeRequest = ++requestId;
    var q = dateEl.value ? '?as_of_date=' + encodeURIComponent(dateEl.value) : '';
    clearTimeout(retryTimer);
    resultsEl.innerHTML = '';
    disclosureEl.textContent = '';
    statusEl.textContent = '加载中…';
    try {
      var res = await fetch('/api/first-wave-start' + q);
      var p = await res.json();
      if (activeRequest !== requestId) return;
      if (!p.ok) {
        var err = p.error || {};
        if (err.code === 'historical_snapshot_building') {
          var pg = err.progress || {};
          statusEl.textContent = (err.message || '构建中') + ' ' + (pg.percent || 0) + '% · ' + (pg.stage || '');
          clearTimeout(retryTimer);
          retryTimer = setTimeout(load, 3000);
          return;
        }
        throw new Error(err.message || '请求失败');
      }
      clearTimeout(retryTimer);
      render(p);
      statusEl.textContent = (p.is_historical ? '历史' : '当前') + ' 数据日期：' + p.data_as_of;
    } catch (e) {
      if (activeRequest !== requestId) return;
      resultsEl.innerHTML = '';
      disclosureEl.textContent = '';
      statusEl.textContent = '无法加载：' + e.message;
    }
  }
  document.getElementById('load').addEventListener('click', load);
  document.getElementById('current').addEventListener('click', function () { dateEl.value = ''; load(); });
  load();
})();
