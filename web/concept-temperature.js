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
  var trendFilter = '';
  var scopeEl = document.getElementById('scope');
  var unitHeader = document.getElementById('unit-header');
  var scope = 'concept';
  var minDaysEl = document.getElementById('min-days');
  var maxDaysEl = document.getElementById('max-days');
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
  function numberText(value, digits, suffix) {
    var number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) + (suffix || '') : '—';
  }
  function horizonReturnCell(row, years) {
    var values = {1: row.return_1y_pct, 3: row.return_3y_pct, 5: row.return_5y_pct};
    var bases = {1: row.return_1y_basis, 3: row.return_3y_basis, 5: row.return_5y_basis};
    var starts = {1: row.return_1y_start_date, 3: row.return_3y_start_date, 5: row.return_5y_start_date};
    var value = values[years];
    if (value == null || !Number.isFinite(Number(value))) return '—';
    var fallback = bases[years] === 'all_history' ? '<small class="member-return-basis">全部历史</small>' : '';
    return '<span class="' + color(value) + '" title="起始日 ' + esc(starts[years] || '未知') + '">' + pct(value) + '</span>' + fallback;
  }
  function scoreCell(value, period, basisTrack, growthBasis, cashBasis) {
    var labels = { recovery_track: '恢复型', deteriorating_track: '恶化型', not_applicable: '不适用' };
    var basisLabel = labels[basisTrack] || '';
    var title = basisLabel ? '评分口径：' + basisLabel + '；增长：' + (growthBasis || '未知') + '；现金：' + (cashBasis || '未知') : '';
    return '<span' + (title ? ' title="' + esc(title) + '"' : '') + '>' + numberText(value, 1, '') + '</span>' +
      (basisLabel ? '<small class="member-return-basis">' + basisLabel + '</small>' : (period ? '<small class="member-return-basis">' + esc(period) + '</small>' : ''));
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
  function tempTrend(row) {
    var label = '<span class="trend-flat">查看趋势</span>';
    if (row.temperature_trend !== 'unknown' && row.temperature_previous != null) {
      var arrow = row.temperature_trend === 'warming' ? '↑' : '↓';
      var cls = row.temperature_trend === 'warming' ? 'positive' : 'negative';
      label = '<span class="' + cls + '">' + row.temperature_previous + ' → ' + row.temperature + ' ' +
        arrow + ' ' + esc(row.temperature_trend_label) + '</span>';
    }
    return '<button type="button" class="temperature-trend-btn" data-temperature-trend-code="' +
      esc(row.concept_code) + '" title="查看最近60个交易日历史温度档位" aria-label="查看' +
      esc(row.concept_name) + '的历史温度趋势">' + label + '</button>';
  }
  function renderSummary(data) {
    var rows = data.concepts || [];
    var counts = [0,1,2,3,4,5].map(function (level) {
      return rows.filter(function (row) { return row.temperature === level; }).length;
    });
    summaryEl.innerHTML = '<div class="stat-card"><div class="val">' + esc(data.as_of_date || '—') + '</div><div class="lbl">数据截至</div></div>' +
      '<div class="stat-card"><div class="val">' + rows.length + '</div><div class="lbl">' + (scope === 'industry' ? '当前行业数' : '当前概念数') + '</div></div>' +
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
      conceptsEl.innerHTML = '<tr><td colspan="10" class="empty">没有符合该温度的概念</td></tr>';
      pagerEl.innerHTML = '';
      return;
    }
    conceptsEl.innerHTML = visible.map(function (row) {
      return '<tr class="concept-row ' + (selected === row.concept_code ? 'selected' : '') + '" data-code="' + esc(row.concept_code) + '"><td>' + tempPill(row) + '</td><td>' + tempTrend(row) + '</td><td><strong>' + esc(row.concept_name) + '</strong></td><td><button type="button" class="heat-score-btn" data-trend-code="' + esc(row.concept_code) + '" title="查看最近 60 个交易日热度分趋势">' + Number(row.heat_score).toFixed(1) + '</button></td><td title="同窗口热度分的相对名次，不参与绝对档位">' + (row.heat_rank == null ? '—' : row.heat_rank) + '</td><td class="' + color(row.median_return_pct) + '">' + pct(row.median_return_pct) + '</td><td>' + Number(row.breadth_pct).toFixed(1) + '%</td><td class="' + color(row.excess_return_pct) + '">' + pct(row.excess_return_pct) + '</td><td>' + streak(row) + '</td><td>' + row.member_count + '</td></tr>';
    }).join('');
    conceptsEl.querySelectorAll('.concept-row').forEach(function (row) {
      row.addEventListener('click', function () {
        selected = row.dataset.code;
        loadMembers();
        renderConceptPage();
      });
    });
    conceptsEl.querySelectorAll('.temperature-trend-btn').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        openHeatTrend(button.dataset.temperatureTrendCode, 'temperature');
      });
    });
    conceptsEl.querySelectorAll('.heat-score-btn').forEach(function (button) {
      button.addEventListener('click', function (event) {
        event.stopPropagation();
        openHeatTrend(button.dataset.trendCode, 'heat_score');
      });
    });
    renderPager();
  }
  function svgNode(name, attrs) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    return node;
  }
  function renderHeatChart(points, metric) {
    var levels = metric === 'temperature';
    var width = Math.max(260, Math.floor(chartEl.getBoundingClientRect().width || 700));
    var height = 330, ml = levels ? 58 : 40, mr = 16, mt = 18, mb = 34;
    var plotW = width - ml - mr, plotH = height - mt - mb;
    chartEl.replaceChildren(); chartEl.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    chartEl.setAttribute('aria-label', levels ? '历史温度档位阶梯图' : '热度分趋势图');
    var x = function (i) { return ml + (points.length < 2 ? plotW / 2 : i * plotW / (points.length - 1)); };
    var y = function (value) { return mt + ((levels ? 5 : 100) - value) * plotH / (levels ? 5 : 100); };
    var valid = function (point) { return levels ? Number.isInteger(point.temperature) && point.temperature >= 0 && point.temperature <= 5 :
      point.heat_score != null && Number.isFinite(Number(point.heat_score)); };
    var value = function (point) { return Number(levels ? point.temperature : point.heat_score); };
    (levels ? [0,1,2,3,4,5] : [0,25,50,75,100]).forEach(function (tick) {
      chartEl.appendChild(svgNode('line', {x1:ml,y1:y(tick),x2:width-mr,y2:y(tick),stroke:'#d8ddd2','stroke-width':'1'}));
      var label = svgNode('text', {x:ml-6,y:y(tick)+4,'text-anchor':'end',fill:'#666','font-size':'10'});
      label.textContent = levels ? tick + ' ' + ['冰点','偏冷','中性','升温','热门','极热'][tick] : tick;
      chartEl.appendChild(label);
    });
    [0, Math.floor((points.length - 1) / 2), points.length - 1].filter(function (v, i, arr) { return arr.indexOf(v) === i; }).forEach(function (index) {
      var label = svgNode('text', {x:x(index),y:height-10,'text-anchor':'middle',fill:'#666','font-size':'10'});
      label.textContent = points[index].date.slice(5); chartEl.appendChild(label);
    });
    var path = '', previous = null;
    points.forEach(function (point, index) {
      if (!valid(point)) { previous = null; return; } // 缺失档位不能连接前后两天
      if (previous === null) path += 'M' + x(index) + ',' + y(value(point));
      else if (levels) path += 'H' + x(index) + 'V' + y(value(point));
      else path += 'L' + x(index) + ',' + y(value(point));
      previous = index;
    });
    chartEl.appendChild(svgNode('path', {d:path,fill:'none',stroke:'#176426','stroke-width':'2.4','stroke-linejoin':'round','stroke-linecap':'round'}));
    var lastIndex = points.length - 1;
    if (valid(points[lastIndex])) chartEl.appendChild(svgNode('circle', {cx:x(lastIndex),cy:y(value(points[lastIndex])),r:'4',fill:'#176426'}));
    var guide = svgNode('line', {stroke:'#000','stroke-width':'1','stroke-dasharray':'3 3',visibility:'hidden'}); chartEl.appendChild(guide);
    var hoverDot = svgNode('circle', {r:'4',fill:'#000',visibility:'hidden'}); chartEl.appendChild(hoverDot);
    var hint = levels ? '将鼠标移到图线上查看日期与温度档位' : '将鼠标移到图线上查看日期与热度分';
    trendTooltip.textContent = hint;
    chartEl.onpointermove = function (event) {
      var rect = chartEl.getBoundingClientRect();
      var scaledX = (event.clientX - rect.left) * width / rect.width;
      var index = Math.max(0, Math.min(lastIndex, Math.round((scaledX - ml) / plotW * lastIndex)));
      var point = points[index];
      guide.setAttribute('x1', x(index)); guide.setAttribute('x2', x(index));
      guide.setAttribute('y1', mt); guide.setAttribute('y2', height-mb); guide.setAttribute('visibility','visible');
      hoverDot.setAttribute('visibility', valid(point) ? 'visible' : 'hidden');
      if (valid(point)) { hoverDot.setAttribute('cx',x(index)); hoverDot.setAttribute('cy',y(value(point))); }
      trendTooltip.textContent = point.date + ' · ' + (valid(point) ? (levels ? '温度 ' + point.temperature + ' 档' : '热度分 ' + value(point).toFixed(1)) : '温度数据不足');
    };
    chartEl.onpointerleave = function () { guide.setAttribute('visibility','hidden'); hoverDot.setAttribute('visibility','hidden'); trendTooltip.textContent = hint; };
  }
  async function openHeatTrend(code, metric) {
    var levels = metric === 'temperature';
    var row = conceptRows.find(function (item) { return item.concept_code === code; });
    var title = levels ? '历史温度档位' : '热度分趋势';
    var requestedScope = scope, requestedWindow = windowEl.value;
    trendTitle.textContent = (row ? row.concept_name : '') + ' · ' + title;
    trendMeta.textContent = '加载 ' + requestedWindow + ' 日窗口最近 60 个交易日的' + title + '…';
    trendTooltip.textContent = '';
    chartEl.replaceChildren(); dialogEl.showModal();
    try {
      var response = await fetch('/api/concept-temperature/trend?scope=' + encodeURIComponent(requestedScope) +
        '&window=' + encodeURIComponent(requestedWindow) + '&concept_code=' + encodeURIComponent(code) + '&metric=' + encodeURIComponent(metric));
      var data = await response.json(); if (!response.ok || !data.ok) throw new Error(data.error || '趋势加载失败');
      if (!dialogEl.open || scope !== requestedScope || windowEl.value !== requestedWindow) return;
      trendTitle.textContent = data.concept.concept_name + ' · ' + title;
      trendMeta.textContent = '最近 ' + data.points.length + ' 条交易日记录 · 截至 ' + data.as_of_date + ' · ' +
        data.window + ' 日窗口 · 前复权 · 当前成分回算历史（非历史时点成分）';
      renderHeatChart(data.points, metric);
    } catch (error) { if (dialogEl.open) trendMeta.textContent = '加载失败：' + error.message; }
  }
  async function loadConcepts() {
    conceptsEl.innerHTML = '<tr><td colspan="10" class="empty">加载中…</td></tr>';
    pagerEl.innerHTML = '';
    try {
      var url = '/api/concept-temperature?scope=' + encodeURIComponent(scope) + '&window=' + encodeURIComponent(windowEl.value) + (temp ? '&temperature=' + temp : '') + (trendFilter ? '&trend=' + encodeURIComponent(trendFilter) : '') + (minDaysEl && minDaysEl.value ? '&min_days=' + encodeURIComponent(minDaysEl.value) : '') + (maxDaysEl && maxDaysEl.value ? '&max_days=' + encodeURIComponent(maxDaysEl.value) : '');
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
      conceptsEl.innerHTML = '<tr><td colspan="10" class="empty">无法加载概念温度数据</td></tr>';
    }
  }
  async function loadMembers() {
    if (!selected) return;
    membersEl.innerHTML = '<tr><td colspan="13" class="empty">加载中…</td></tr>';
    try {
      var resp = await fetch('/api/concept-temperature/members?scope=' + encodeURIComponent(scope) + '&window=' + encodeURIComponent(windowEl.value) + '&concept_code=' + encodeURIComponent(selected));
      var data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || '加载失败');
      memberTitle.textContent = data.concept.concept_name + ' · 成分股';
      memberCount.textContent = data.stocks.length;
      memberMeta.textContent = '共 ' + data.stocks.length + ' 只有效成分股 · 按 ' + data.window + ' 日前复权涨幅降序 · 截至 ' + data.as_of_date;
      membersEl.innerHTML = data.stocks.map(function (row) {
        var market = row.symbol[0] === '6' ? 'sh' : (row.symbol.startsWith('92') ? 'bj' : 'sz');
        var href = '/stock-analysis.html?market=' + market + '&symbol=' + encodeURIComponent(row.symbol) + '&name=' + encodeURIComponent(row.stock_name);
        return '<tr><td>' + esc(row.symbol) + '</td><td><a class="stock-link" href="' + href + '">' + esc(row.stock_name) + '</a></td>' +
          '<td class="' + color(row.return_pct) + '">' + pct(row.return_pct) + '</td><td>' + numberText(row.latest_close, 2, '') + '</td>' +
          '<td>' + horizonReturnCell(row, 1) + '</td><td>' + horizonReturnCell(row, 3) + '</td><td>' + horizonReturnCell(row, 5) + '</td>' +
          '<td>' + numberText(row.volume_ratio_5d_20d, 2, '') + '</td><td>' + numberText(row.mrs_score, 1, '') + '</td>' +
          '<td>' + numberText(row.turnover_percentile_1y, 1, '%') + '</td><td>' + numberText(row.pe_ttm, 2, '') + '</td>' +
          '<td>' + scoreCell(row.annual_total, row.annual_period, row.annual_score_basis_track, row.annual_growth_quality_basis, row.annual_cash_quality_basis) + '</td><td>' + scoreCell(row.quarterly_total, row.quarterly_period) + '</td></tr>';
      }).join('');
    } catch (err) {
      memberMeta.textContent = '加载失败：' + err.message;
      membersEl.innerHTML = '<tr><td colspan="13" class="empty">无法加载成分股</td></tr>';
    }
  }
  windowEl.addEventListener('change', function () {
    selected = ''; currentPage = 1; memberTitle.textContent = '成分股清单'; memberCount.textContent = '0';
    memberMeta.textContent = '点击上方概念查看'; membersEl.innerHTML = '<tr><td colspan="13" class="empty">尚未选择概念</td></tr>';
    loadConcepts();
  });
  function bindTemperatureTooltips() {
    var tip = document.getElementById('temp-tip');
    if (!tip || tip.dataset.bound === '1') return;
    tip.dataset.bound = '1';
    function show(button) {
      var text = button.getAttribute('data-tip');
      if (!text) return;
      tip.textContent = text;
      tip.setAttribute('data-open', '1');
      tip.setAttribute('aria-hidden', 'false');
      var rect = button.getBoundingClientRect();
      var width = tip.offsetWidth;
      var left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 8);
      var top = rect.bottom + 10;
      if (top + tip.offsetHeight > window.innerHeight - 8) top = rect.top - tip.offsetHeight - 10;
      tip.style.left = left + 'px';
      tip.style.top = top + 'px';
    }
    function hide() {
      tip.removeAttribute('data-open');
      tip.setAttribute('aria-hidden', 'true');
    }
    document.querySelectorAll('[data-tip]').forEach(function (button) {
      button.addEventListener('mouseenter', function () { show(button); });
      button.addEventListener('focus', function () { show(button); });
      button.addEventListener('mouseleave', hide);
      button.addEventListener('blur', hide);
      button.addEventListener('click', hide);
    });
    window.addEventListener('scroll', hide, true);
  }
  // 气泡元素在脚本之后解析，必须等 DOM 就绪再绑定。
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindTemperatureTooltips);
  } else {
    bindTemperatureTooltips();
  }

  function applyScope() {
    scope = scopeEl ? scopeEl.value : 'concept';
    if (unitHeader) unitHeader.textContent = scope === 'industry' ? '二级行业' : '概念';
    var boardTitle = document.getElementById('board-title');
    if (boardTitle) boardTitle.textContent = scope === 'industry' ? '行业温度榜' : '概念温度榜';
    selected = ''; currentPage = 1;
    memberTitle.textContent = '成分股清单'; memberCount.textContent = '0';
    memberMeta.textContent = '点击上方查看';
    membersEl.innerHTML = '<tr><td colspan="13" class="empty">尚未选择' + (scope === 'industry' ? '行业' : '概念') + '</td></tr>';
    conceptsEl.innerHTML = '<tr><td colspan="10" class="empty">加载中…</td></tr>';
    loadConcepts();
  }
  if (scopeEl) {
    scopeEl.addEventListener('change', applyScope);
    applyScope();
  }
  [minDaysEl, maxDaysEl].forEach(function (input) {
    if (!input) return;
    input.addEventListener('change', function () { currentPage = 1; loadConcepts(); });
  });
  document.querySelectorAll('.trend-filter').forEach(function (button) {
    button.addEventListener('click', function () {
      trendFilter = button.dataset.trend || '';
      currentPage = 1;
      document.querySelectorAll('.trend-filter').forEach(function (item) { item.classList.toggle('active', item === button); });
      loadConcepts();
    });
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
