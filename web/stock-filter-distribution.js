/* 板块股价收益比分布弹框：箱线图 + 分箱柱状 + 明细表（无依赖，纯 SVG） */
(function () {
  'use strict';

  var openBtn = document.getElementById('open-eps-distribution');
  var dialog = document.getElementById('eps-distribution-dialog');
  if (!openBtn || !dialog) { return; }

  var metaEl = document.getElementById('dist-meta');
  var defEl = document.getElementById('dist-definition');
  var boxEl = document.getElementById('box-chart');
  var binEl = document.getElementById('bin-chart');
  var rowsEl = document.getElementById('dist-rows');
  var closeBtn = document.getElementById('dist-close');

  var COLORS = { main: '#6ea8fe', chinext: '#f0b45f', star: '#c792ea', bj: '#7fd1a6' };
  var SVGNS = 'http://www.w3.org/2000/svg';
  var loaded = null;

  function el(name, attrs, text) {
    var node = document.createElementNS(SVGNS, name);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  function fmt(value, digits) {
    if (value === null || value === undefined) { return '—'; }
    return Number(value).toFixed(digits === undefined ? 1 : digits);
  }

  function renderBox(boards) {
    var W = 760, H = 300, M = { left: 46, right: 18, top: 20, bottom: 42 };
    var innerW = W - M.left - M.right, innerH = H - M.top - M.bottom;
    var lo = -20, hi = 50;
    var clamp = function (v) { return Math.max(lo, Math.min(hi, v)); };
    var y = function (v) { return M.top + (hi - clamp(v)) / (hi - lo) * innerH; };
    var band = innerW / boards.length;

    boxEl.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    boxEl.textContent = '';

    // 亏损区背景
    boxEl.appendChild(el('rect', { x: M.left, y: y(0), width: innerW, height: M.top + innerH - y(0),
      fill: 'rgba(255,107,107,.07)' }));
    // 网格与刻度
    for (var tick = lo; tick <= hi; tick += 10) {
      boxEl.appendChild(el('line', { x1: M.left, x2: M.left + innerW, y1: y(tick), y2: y(tick),
        stroke: tick === 0 ? 'rgba(255,255,255,.42)' : 'rgba(255,255,255,.10)',
        'stroke-dasharray': tick === 0 ? '4 4' : '2 6' }));
      boxEl.appendChild(el('text', { x: M.left - 8, y: y(tick) + 4, 'text-anchor': 'end',
        fill: '#7d8794', 'font-size': 11 }, tick + '%'));
    }
    boxEl.appendChild(el('text', { x: M.left - 8, y: M.top - 6, 'text-anchor': 'end',
      fill: '#7d8794', 'font-size': 10 }, '五年加总 / 股价'));

    boards.forEach(function (board, index) {
      var cx = M.left + band * (index + 0.5);
      var bw = Math.min(54, band * 0.42);
      var color = COLORS[board.key] || '#8ab4f8';
      var top = y(board.q3), bottom = y(board.q1);

      // 触须（P10–P90），超出坐标范围加箭头
      boxEl.appendChild(el('line', { x1: cx, x2: cx, y1:Math.max(M.top, y(board.p90)), y2: Math.min(M.top + innerH, y(board.p10)),
        stroke: color, 'stroke-width': 1.4, opacity: .85 }));
      [['p90', 1], ['p10', -1]].forEach(function (item) {
        var value = board[item[0]];
        var outside = value > hi || value < lo;
        var yy = Math.max(M.top, Math.min(M.top + innerH, y(value)));
        if (outside) {
          boxEl.appendChild(el('path', { d: 'M ' + (cx - 5) + ' ' + (yy + item[1] * 6) + ' L ' + cx + ' ' + yy +
            ' L ' + (cx + 5) + ' ' + (yy + item[1] * 6), fill: color }));
        } else {
          boxEl.appendChild(el('line', { x1: cx - 9, x2: cx + 9, y1: yy, y2: yy, stroke: color, 'stroke-width': 1.4 }));
        }
      });

      // 箱体 + 中位线
      boxEl.appendChild(el('rect', { x: cx - bw / 2, y: top, width: bw, height: Math.max(2, bottom - top),
        fill: color, 'fill-opacity': .22, stroke: color, 'stroke-width': 1.3, rx: 3 }));
      boxEl.appendChild(el('line', { x1: cx - bw / 2, x2: cx + bw / 2, y1: y(board.median), y2: y(board.median),
        stroke: '#fff', 'stroke-width': 2.4 }));
      // 均值
      boxEl.appendChild(el('circle', { cx: cx, cy: y(board.mean), r: 3.4, fill: 'none', stroke: color,
        'stroke-width': 1.6, 'stroke-dasharray': '2 2' }));

      // 数值标注
      boxEl.appendChild(el('text', { x: cx, y: y(board.median) - 8, 'text-anchor': 'middle',
        fill: '#e8edf4', 'font-size': 12, 'font-weight': 600 }, fmt(board.median) + '%'));
      boxEl.appendChild(el('text', { x: cx, y: y(board.median) + 16, 'text-anchor': 'middle',
        fill: '#9aa4b2', 'font-size': 10 }, 'n=' + board.n));
      boxEl.appendChild(el('text', { x: cx, y: M.top + innerH + 20, 'text-anchor': 'middle',
        fill: '#c8d0da', 'font-size': 12 }, board.label));
      boxEl.appendChild(el('text', { x: cx, y: M.top + innerH + 34, 'text-anchor': 'middle',
        fill: '#7d8794', 'font-size': 10 }, '折算 PE ' + fmt(board.implied_pe, 0)));
    });
  }

  function renderBins(boards, binLabels) {
    var W = 760, H = 290, M = { left: 46, right: 18, top: 26, bottom: 46 };
    var innerW = W - M.left - M.right, innerH = H - M.top - M.bottom;
    var maxPct = 0;
    boards.forEach(function (b) { b.bins.forEach(function (bin) { maxPct = Math.max(maxPct, bin.pct); }); });
    var hi = Math.ceil(maxPct / 10) * 10 || 10;
    var y = function (v) { return M.top + innerH - v / hi * innerH; };
    var band = innerW / binLabels.length;
    var barW = Math.min(18, band * 0.72 / boards.length);

    binEl.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    binEl.textContent = '';

    for (var tick = 0; tick <= hi; tick += 10) {
      binEl.appendChild(el('line', { x1: M.left, x2: M.left + innerW, y1: y(tick), y2: y(tick),
        stroke: 'rgba(255,255,255,.10)', 'stroke-dasharray': '2 6' }));
      binEl.appendChild(el('text', { x: M.left - 8, y: y(tick) + 4, 'text-anchor': 'end',
        fill: '#7d8794', 'font-size': 11 }, tick + '%'));
    }

    binLabels.forEach(function (label, binIndex) {
      var start = M.left + band * binIndex + band / 2 - (barW * boards.length) / 2;
      boards.forEach(function (board, boardIndex) {
        var pct = board.bins[binIndex].pct;
        var x = start + boardIndex * barW;
        var height = Math.max(pct > 0 ? 1.5 : 0, pct / hi * innerH);
        binEl.appendChild(el('rect', { x: x, y: M.top + innerH - height, width: Math.max(2, barW - 2), height: height,
          fill: COLORS[board.key] || '#8ab4f8', 'fill-opacity': .85, rx: 2 }));
        if (pct >= 4) {
          binEl.appendChild(el('text', { x: x + Math.max(2, barW - 2) / 2, y: M.top + innerH - height - 4,
            'text-anchor': 'middle', fill: '#9aa4b2', 'font-size': 9 }, fmt(pct, 0)));
        }
      });
      binEl.appendChild(el('text', { x: M.left + band * (binIndex + 0.5), y: M.top + innerH + 20,
        'text-anchor': 'middle', fill: '#c8d0da', 'font-size': 12 }, label));
    });

    // 图例
    boards.forEach(function (board, index) {
      var lx = M.left + index * 116, ly = 14;
      binEl.appendChild(el('rect', { x: lx, y: ly - 8, width: 10, height: 10, fill: COLORS[board.key],
        'fill-opacity': .85, rx: 2 }));
      binEl.appendChild(el('text', { x: lx + 15, y: ly + 1, fill: '#c8d0da', 'font-size': 11 }, board.label));
    });
  }

  function renderTable(boards) {
    rowsEl.innerHTML = boards.map(function (board) {
      return '<tr><td>' + board.label + '</td><td>' + board.n + '</td><td>' + board.missing + '</td>' +
        '<td><strong>' + fmt(board.median) + '%</strong></td><td>' + fmt(board.q1) + '%</td><td>' + fmt(board.q3) + '%</td>' +
        '<td>' + fmt(board.implied_pe, 0) + '</td><td>' + fmt(board.negative_pct) + '%</td>' +
        '<td>' + board.cheap_30 + '（' + fmt(board.cheap_30_pct) + '%）</td></tr>';
    }).join('');
  }

  function render(data) {
    metaEl.textContent = '数据日期 ' + data.as_of_date + ' · 全 A ' +
      data.boards.reduce(function (sum, b) { return sum + b.n + b.missing; }, 0) + ' 只 · 口径 ' + data.metric;
    defEl.textContent = data.definition;
    renderBox(data.boards);
    renderBins(data.boards, data.bins);
    renderTable(data.boards);
  }

  function load() {
    if (loaded) { return Promise.resolve(loaded); }
    metaEl.textContent = '加载中…';
    return fetch('/api/stock-filter-distribution', { cache: 'no-store' })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        if (!payload.ok) { throw new Error(payload.error && payload.error.message || '分布数据不可用'); }
        loaded = payload;
        render(payload);
        return payload;
      })
      .catch(function (error) {
        metaEl.textContent = '加载失败：' + error.message;
        throw error;
      });
  }

  openBtn.addEventListener('click', function () {
    if (typeof dialog.showModal === 'function') { dialog.showModal(); } else { dialog.setAttribute('open', 'open'); }
    load().catch(function () {});
  });
  closeBtn.addEventListener('click', function () { dialog.close(); });
  dialog.addEventListener('click', function (event) { if (event.target === dialog) { dialog.close(); } });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && dialog.open) { dialog.close(); }
  });
}());
