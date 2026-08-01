(function () {
  'use strict';
  var PAGE_SIZE = 20;
  var windowEl = document.getElementById('window');
  var conceptsEl = document.getElementById('concepts');
  var membersEl = document.getElementById('members');
  var conceptMeta = document.getElementById('concept-meta');
  var memberMeta = document.getElementById('member-meta');
  var memberTitle = document.getElementById('member-title');
  var conceptCount = document.getElementById('concept-count');
  var memberCount = document.getElementById('member-count');
  var summaryEl = document.getElementById('ct-summary');
  var pagerEl = document.getElementById('concept-pager');
  var dialogEl = document.getElementById('heat-trend-dialog');
  var chartEl = document.getElementById('heat-chart');
  var trendTitle = document.getElementById('trend-title');
  var trendMeta = document.getElementById('trend-meta');
  var trendTooltip = document.getElementById('trend-tooltip');
  var temp = '';
  var selected = '';
  var currentPage = 1;
  var conceptRows = [];

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function pct(value) {
    if (value == null || Number.isNaN(Number(value))) return '—';
    var n = Number(value); return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  }
  function color(value) { return Number(value) >= 0 ? 'positive' : 'negative'; }
  function tempPill(row) {
    if (row.temperature == null) return '<span class="pill t2">数据不足</span>';
    return '<span class="pill t' + row.temperature + '">' + row.temperature + ' ' + esc(row.temperature_label) + '</span>';
  }
  function streak(row) {
    if (row.temperature_streak_days == null) return '—';
    return String(row.temperature_streak_days) + (row.temperature_streak_capped ? '+' : '') + '天';
  }
  function renderSummary(data) {
    var rows = data.concepts || [];
    var counts = [0,1,2,3,4,5].map(function (level) {
      return rows.filter(function (row) { return row.temperature === level; }).length;
    });
    summaryEl.innerHTML = '<div class="stat-card"><div class="val">' + esc(data.as_of_date || '—') + '</div><div class="lbl">数据截至</div></div>' +
      '<div class="stat-card"><div class="val">' + rows.length + '</div><div class="lbl">当前概念数</div></div>' +
      '<div class="stat-card"><div class="val positive">' + counts[5] + '</div><div class="lbl">极热 / 5分</div></div>' +
      '<div class="stat-card"><div class="val">' + counts[4] + '</div><div class="lbl">热门 / 4分</div></div>';
  }
  function totalPages() { return Math.max(1, Math.ceil(conceptRows.length / PAGE_SIZE)); }
  function renderPager() {
    var pages = totalPages();
    if (!conceptRows.length) { pagerEl.innerHTML = ''; return; }
    pagerEl.innerHTML = '<button type="button" data-page="prev"' + (currentPage === 1 ? ' disabled' : '') + '>上一页</button>' +
      '<span class="page-info">第 ' + currentPage + ' / ' + pages + ' 页 · 每页 20 个</span>' +
      '<button type="button" data-page="next"' + (currentPage === pages ? ' disabled' : '') + '>下一页</button>';
    pagerEl.querySelectorAll('button').forEach(function (button) {
      button.addEventListener('click', function () {
        currentPage += button.dataset.page === 'prev' ? -1 : 1;
        renderConceptPage();
      });
    });
  }
  function renderConceptPage() {
    var pages = totalPages();
    if (currentPage > pages) currentPage = pages;
    var start = (currentPage - 1) * PAGE_SIZE;
    var visible = conceptRows.slice(start, start + PAGE_SIZE);
    if (!visible.length) {
      conceptsEl.innerHTML = '<tr><td colspan="8" class="empty">没有符合该温度的概念</td></tr>';
      pagerEl.innerHTML = '';
      return;
    }
    conceptsEl.innerHTML = visible.map(function (row) {
      return '<tr class="concept-row ' + (selected === row.concept_code ? 'selected' : '') + '" data-code="' + esc(row.concept_code) + '"><td>' + tempPill(row) + '</td><td><strong>' + esc(row.concept_name) + '</strong></td><td><button type="button" class="heat-score-btn" data-trend-code="' + esc(row.concept_code) + '" title="查看过去半年热度分趋势">' + Number(row.heat_score).toFixed(1) + '</button></td><td class="' + color(row.median_return_pct) + '">' + pct(row.median_return_pct) + '</td><td>' + Number(row.breadth_pct).toFixed(1) + '%</td><td class="' + color(row.excess_return_pct) + '">' + pct(row.excess_return_pct) + '</td><td>' + streak(row) + '</td><td>' + row.member_count + '</td></tr>';
    }).join('');
    conceptsEl.querySelectorAll('.concept-row').forEach(function (row) {
      row.addEventListener('click', function () {
        selected = row.dataset.code;
        loadMembers();
        renderConceptPage();
      });
    });
    conceptsEl.querySelectorAll('.heat-score-btn').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        openHeatTrend(button.dataset.trendCode);
      });
    });
    renderPager();
  }
  function svgNode(name, attrs) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }
  function renderHeatChart(points) {
    var width = Math.max(360, Math.floor(chartEl.getBoundingClientRect().width || 700));
    var height = 330, ml = 40, mr = 16, mt = 18, mb = 34, plotW = width - ml - mr, plotH = height - mt - mb;
    chartEl.replaceChildren(); chartEl.setAttribute('width', width); chartEl.setAttribute('height', height);
    var x = function (i) { return ml + (points.length < 2 ? plotW / 2 : i * plotW / (points.length - 1)); };
    var y = function (value) { return mt + (100 - value) * plotH / 100; };
    [0, 25, 50, 75, 100].forEach(function (value) {
      chartEl.appendChild(svgNode('line', {x1:ml,y1:y(value),x2:width-mr,y2:y(value),stroke:'#d8ddd2','stroke-width':'1'}));
      var label = svgNode('text', {x:ml-6,y:y(value)+4,'text-anchor':'end',fill:'#666','font-size':'10'}); label.textContent = value; chartEl.appendChild(label);
    });
    [0, Math.floor((points.length - 1) / 2), points.length - 1].filter(function (v, i, arr) { return arr.indexOf(v) === i; }).forEach(function (index) {
      var label = svgNode('text', {x:x(index),y:height-10,'text-anchor':'middle',fill:'#666','font-size':'10'}); label.textContent = points[index].date.slice(5); chartEl.appendChild(label);
    });
    var polyline = svgNode('polyline', {points:points.map(function (point, index) { return x(index) + ',' + y(point.heat_score); }).join(' '),fill:'none',stroke:'#176426','stroke-width':'2.4','stroke-linejoin':'round','stroke-linecap':'round'});
    chartEl.appendChild(polyline);
    var dot = svgNode('circle', {cx:x(points.length-1),cy:y(points[points.length-1].heat_score),r:'4',fill:'#176426'}); chartEl.appendChild(dot);
    var guide = svgNode('line', {stroke:'#000','stroke-width':'1','stroke-dasharray':'3 3',visibility:'hidden'}); chartEl.appendChild(guide);
    var hoverDot = svgNode('circle', {r:'4',fill:'#000',visibility:'hidden'}); chartEl.appendChild(hoverDot);
    chartEl.onpointermove = function (event) {
      var rect = chartEl.getBoundingClientRect();
      var index = Math.max(0, Math.min(points.length - 1, Math.round((event.clientX - rect.left - ml) / plotW * (points.length - 1))));
      var point = points[index]; guide.setAttribute('x1', x(index)); guide.setAttribute('x2', x(index)); guide.setAttribute('y1', mt); guide.setAttribute('y2', height-mb); guide.setAttribute('visibility','visible'); hoverDot.setAttribute('cx',x(index)); hoverDot.setAttribute('cy',y(point.heat_score)); hoverDot.setAttribute('visibility','visible'); trendTooltip.textContent = point.date + ' · 热度分 ' + Number(point.heat_score).toFixed(1);
    };
    chartEl.onpointerleave = function () { guide.setAttribute('visibility','hidden'); hoverDot.setAttribute('visibility','hidden'); trendTooltip.textContent = '将鼠标移到图线上查看日期与热度分'; };
  }
  async function openHeatTrend(code) {
    var row = conceptRows.find(function (item) { return item.concept_code === code; });
    trendTitle.textContent = (row ? row.concept_name : '') + ' · 热度分趋势';
    trendMeta.textContent = '加载 ' + windowEl.value + ' 日窗口的过去半年热度分…'; trendTooltip.textContent = '';
    chartEl.replaceChildren(); dialogEl.showModal();
    try {
      var response = await fetch('/api/concept-temperature/trend?window=' + encodeURIComponent(windowEl.value) + '&concept_code=' + encodeURIComponent(code));
      var data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || '趋势加载失败');
      trendTitle.textContent = data.concept.concept_name + ' · 热度分趋势';
      trendMeta.textContent = '过去半年 · ' + data.window + ' 日窗口 · 前复权口径 · ' + data.points.length + ' 个交易日';
      renderHeatChart(data.points);
    } catch (error) { trendMeta.textContent = '加载失败：' + error.message; }
  }
  async function loadConcepts() {
    conceptsEl.innerHTML = '<tr><td colspan="8" class="empty">加载中…</td></tr>';
    pagerEl.innerHTML = '';
    try {
      var url = '/api/concept-temperature?window=' + encodeURIComponent(windowEl.value) + (temp ? '&temperature=' + temp : '');
      var resp = await fetch(url);
      var data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || '加载失败');
      conceptRows = data.concepts;
      conceptMeta.textContent = '截至 ' + data.as_of_date + ' · ' + data.window + '日窗口 · 前复权涨幅 · 至少 ' + data.min_members + ' 只有效成分股';
      conceptCount.textContent = conceptRows.length;
      renderSummary(data);
      renderConceptPage();
    } catch (err) {
      conceptMeta.textContent = '加载失败：' + err.message;
      conceptsEl.innerHTML = '<tr><td colspan="8" class="empty">无法加载概念温度数据</td></tr>';
    }
  }
  async function loadMembers() {
    if (!selected) return;
    membersEl.innerHTML = '<tr><td colspan="5" class="empty">加载中…</td></tr>';
    try {
      var resp = await fetch('/api/concept-temperature/members?window=' + encodeURIComponent(windowEl.value) + '&concept_code=' + encodeURIComponent(selected));
      var data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || '加载失败');
      memberTitle.textContent = data.concept.concept_name + ' · 成分股';
      memberCount.textContent = data.stocks.length;
      memberMeta.textContent = '共 ' + data.stocks.length + ' 只有效成分股 · 按 ' + data.window + ' 日前复权涨幅降序 · 截至 ' + data.as_of_date;
      membersEl.innerHTML = data.stocks.map(function (row) {
        var market = row.symbol[0] === '6' ? 'sh' : (row.symbol.startsWith('92') ? 'bj' : 'sz');
        var href = '/stock-score.html?market=' + market + '&symbol=' + encodeURIComponent(row.symbol) + '&name=' + encodeURIComponent(row.stock_name);
        return '<tr><td>' + esc(row.symbol) + '</td><td><a class="stock-link" href="' + href + '">' + esc(row.stock_name) + '</a></td><td class="' + color(row.return_pct) + '">' + pct(row.return_pct) + '</td><td>' + Number(row.latest_close).toFixed(2) + '</td><td>' + Number(row.volume_ratio_5d_20d).toFixed(2) + '</td></tr>';
      }).join('');
    } catch (err) {
      memberMeta.textContent = '加载失败：' + err.message;
      membersEl.innerHTML = '<tr><td colspan="5" class="empty">无法加载成分股</td></tr>';
    }
  }
  windowEl.addEventListener('change', function () {
    selected = ''; currentPage = 1; memberTitle.textContent = '成分股清单'; memberCount.textContent = '0';
    memberMeta.textContent = '点击上方概念查看'; membersEl.innerHTML = '<tr><td colspan="5" class="empty">尚未选择概念</td></tr>';
    loadConcepts();
  });
  document.querySelectorAll('.temp-filter').forEach(function (button) {
    button.addEventListener('click', function () {
      temp = button.dataset.temp; currentPage = 1;
      document.querySelectorAll('.temp-filter').forEach(function (item) { item.classList.toggle('active', item === button); });
      loadConcepts();
    });
  });
  document.getElementById('trend-close').addEventListener('click', function () { dialogEl.close(); });
  dialogEl.addEventListener('click', function (event) { if (event.target === dialogEl) dialogEl.close(); });
  loadConcepts();
}());
