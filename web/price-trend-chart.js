/* Filter price dialog: strict QFQ date alignment and TDX MACD(12,26,9). */
(function (root) {
  'use strict';

  function computeMacd(bars) {
    let fast = null, slow = null, dea = 0;
    return bars.map(function (bar) {
      const close = Number(bar.close);
      if (!Number.isFinite(close) || close <= 0) throw new Error('前复权收盘价无效');
      if (fast === null) { fast = close; slow = close; }
      else { fast += (close - fast) * 2 / 13; slow += (close - slow) * 2 / 27; }
      const dif = fast - slow;
      dea += (dif - dea) * 2 / 10;
      return {dif: dif, dea: dea, hist: 2 * (dif - dea)};
    });
  }

  function chartEvidence(payload, day, history) {
    if (!payload || !payload.ok || payload.price_basis !== 'tdx_export_qfq') throw new Error('缺少通达信前复权日线');
    if (payload.as_of_date !== day) throw new Error('前复权图与筛选日期不一致');
    const bars = payload.bars || [];
    if (!bars.length || bars[bars.length - 1].trading_day !== day || bars.some(function (bar, i) {
      return bar.trading_day > day || (i > 0 && bar.trading_day <= bars[i - 1].trading_day) ||
        ['open', 'high', 'low', 'close'].some(function (key) { return !Number.isFinite(Number(bar[key])) || Number(bar[key]) <= 0; });
    })) throw new Error('前复权日线日期或价格无效');
    const dates = new Set(bars.map(function (bar) { return bar.trading_day; }));
    const rpsHistory = (Array.isArray(history) ? history : []).filter(function (row) {
      return dates.has(row.trading_day) && row.trading_day <= day;
    });
    return {bars: bars, rpsHistory: rpsHistory, rpsAsOf: rpsHistory.length ? rpsHistory[rpsHistory.length - 1].trading_day : ''};
  }

  function renderMacd(svg, allBars, viewport) {
    const points = computeMacd(allBars);
    const start = viewport.windowStart, end = viewport.windowEnd;
    const visible = points.slice(start, end);
    if (!visible.length) { svg.innerHTML = ''; return; }
    const width = Math.max(420, svg.getBoundingClientRect().width || 1000), height = 176;
    const left = 8, right = 48, top = 24, bottom = 16;
    const plot = width - left - right, center = (height + top - bottom) / 2;
    const extent = Math.max(0.001, ...visible.map(function (p) { return Math.max(Math.abs(p.dif), Math.abs(p.dea), Math.abs(p.hist)); }));
    const scale = (height - top - bottom) / 2 / extent;
    const slot = plot / visible.length;
    const x = function (i) { return left + slot * (i + 0.5); };
    const y = function (value) { return center - value * scale; };
    const line = function (key) {
      return visible.map(function (p, i) { return (i ? 'L' : 'M') + x(i).toFixed(2) + ' ' + y(p[key]).toFixed(2); }).join(' ');
    };
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.innerHTML = '<line x1="' + left + '" x2="' + (width-right) + '" y1="' + center + '" y2="' + center + '" stroke="#68757f" stroke-dasharray="4 4"/>' +
      visible.map(function (p,i) { const yy = y(p.hist); return '<rect x="' + (x(i)-Math.max(1,slot*0.32)).toFixed(2) + '" y="' + Math.min(center,yy).toFixed(2) + '" width="' + Math.max(2,slot*0.64).toFixed(2) + '" height="' + Math.max(1,Math.abs(center-yy)).toFixed(2) + '" fill="' + (p.hist>=0?'#ef5350':'#26a69a') + '"/>'; }).join('') +
      '<path d="' + line('dif') + '" fill="none" stroke="#f7d06a" stroke-width="1.7"/>' +
      '<path d="' + line('dea') + '" fill="none" stroke="#80cbc4" stroke-width="1.6"/>' +
      '<text x="8" y="15" fill="#c8d5da" font-size="12">MACD(12,26,9) · DIF 黄 / DEA 青 / 柱 红涨绿跌</text>' +
      '<text x="' + (width-4) + '" y="15" text-anchor="end" fill="#a6b7bd" font-size="11">' + visible[visible.length-1].hist.toFixed(3) + '</text>';
  }
  const api = {computeMacd, chartEvidence, renderMacd};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PriceTrendChart = api;
})(typeof window === 'undefined' ? globalThis : window);
