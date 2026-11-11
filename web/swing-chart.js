/* Shared audited QFQ swing K-line renderer: analysis and screener use identical markers. */
(function(root) {
  'use strict';
  function escapeHtml(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch])); }
  function swingNumber(value) { return value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(2); }
  // Keep the audited swing source; never silently substitute raw prices or future RPS.
  function chartEvidence(data, history) {
    const day = data && data.as_of_date;
    if (!day || data.price_basis !== 'tdx_export_qfq') throw new Error('缺少同日前复权证据');
    const source = data.bars || [];
    if (!source.length || source[source.length - 1].date !== day || source.some((b,i) =>
      b.date > day || (i && b.date <= source[i-1].date) ||
      ['open','high','low','close'].some(k => !Number.isFinite(Number(b[k])) || Number(b[k]) <= 0) ||
      !Number.isFinite(Number(b.volume)) || Number(b.volume) < 0)) throw new Error('前复权日线日期或价格无效');
    const bars = source.map(b => ({...b, trading_day:b.date}));
    const dates = new Set(bars.map(b => b.trading_day));
    const rpsHistory = (Array.isArray(history) ? history : []).filter(r => dates.has(r.trading_day) && r.trading_day <= day);
    return {bars, rpsHistory, rpsAsOf:rpsHistory.length ? rpsHistory[rpsHistory.length-1].trading_day : ''};
  }
  function verifiedBox(o) {
    const boxFirst=o.box_first_state_v5;
    return o.state==='区间震荡' && o.box_test==='passed' &&
      (boxFirst==null || boxFirst==='区间震荡' || boxFirst==='passed' || boxFirst?.box_test==='passed') &&
      [o.box_lower,o.box_upper].every(v=>v!=null && Number.isFinite(Number(v)));
  }
  // Overlay uses the *same* pixel scale, fractional candle slot, and visible window as KlineChart.
  function overlayMarkup(data, chart) {
    const o = data.observation || {}, d = chart._getPlotDims(), visible = chart._visibleBars ? chart._visibleBars() : chart.bars.slice(chart.visible.windowStart,chart.visible.windowEnd);
    const barW = chart._barWidth(), x = i => d.ml + i*(barW+chart.cfg.candleSpacing)+barW/2;
    const index = new Map(visible.map((b,i) => [b.trading_day,i]));
    const inPrice = y => Number.isFinite(y) && y >= d.priceTop && y <= d.priceTop+d.priceH;
    const marks = [...(o.last_10_peaks||[]).slice(-10).map((p,i,a)=>({...p,kind:'peak',recent:i>=a.length-3})),
      ...(o.last_10_valleys||[]).slice(-10).map((p,i,a)=>({...p,kind:'valley',recent:i>=a.length-3}))];
    let html = marks.map(p => {
      const i=index.get(p.date), price=p.kind==='peak'?p.high:p.low, y=chart._priceToY(Number(price));
      if (i===undefined || price==null || !inPrice(y)) return '';
      const color=p.kind==='peak'?'#ffc36f':'#73dfc4';
      return `<g data-swing-mark="confirmed" data-date="${escapeHtml(p.date)}"><circle cx="${x(i)}" cy="${y}" r="${p.recent?7:4}" fill="${color}" stroke="${p.recent?'#fff':'#09141a'}" stroke-width="2"/><title>确认${p.kind==='peak'?'峰':'谷'} 发生 ${escapeHtml(p.date)} · ${swingNumber(price)}，确认 ${escapeHtml(p.confirmed || '—')}${p.recent?' · 最近3点':''}</title></g>`;
    }).join('');
    const box=o.box_audit||{};
    if (verifiedBox(o)) {
      html += [['前三组下沿',o.box_lower],['前三组上沿',o.box_upper]].map(([label,price]) => {
        const y=chart._priceToY(Number(price));
        return inPrice(y)?`<g data-swing-box="verified"><line x1="${d.ml}" x2="${d.ml+d.plotW}" y1="${y}" y2="${y}" stroke="#8bd8ff" stroke-dasharray="5 5"/><title>${label} ${swingNumber(price)}，仅供第四组检验通过的真实箱体</title></g>`:'';
      }).join('');
      html += (box.fourth_check||[]).map(p => {
        const i=index.get(p.date), y=chart._priceToY(Number(p.price));
        return i===undefined || p.price==null || !inPrice(y)?'':`<g data-swing-box-check="fourth"><rect x="${x(i)-9}" y="${y-9}" width="18" height="18" fill="none" stroke="#8bd8ff" stroke-width="2"/><title>第四组检验点 ${escapeHtml(p.date)} ${swingNumber(p.price)}</title></g>`;
      }).join('');
    }
    html += [...(o.candidate_peaks||[]).map(p=>({...p,kind:'峰',price:p.high})),
      ...(o.candidate_valleys||[]).map(p=>({...p,kind:'谷',price:p.low}))].map(p => {
      const i=index.get(p.date),y=chart._priceToY(Number(p.price));
      return i===undefined || p.price==null || !inPrice(y)?'':`<g data-swing-mark="candidate" data-date="${escapeHtml(p.date)}"><circle cx="${x(i)}" cy="${y}" r="8" fill="none" stroke="#bbaaff" stroke-width="2" stroke-dasharray="3 2"/><title>未确认候选${p.kind} ${escapeHtml(p.date)} · ${swingNumber(p.price)}；尚需 ${Number(p.waiting_bars)||0} 根K线</title></g>`;
    }).join('');
    return html;
  }
  function renderOverlay(data, chart) {
    let layer=chart.svg.querySelector('.kc-swing-overlay');
    if (!layer) {
      layer=document.createElementNS('http://www.w3.org/2000/svg','g');
      layer.setAttribute('class','kc-swing-overlay');
      chart.svg.insertBefore(layer,chart.crosshairGroup);
    }
    layer.innerHTML=overlayMarkup(data,chart);
  }
  function render(data, svg, meta) {
    const o = data.observation || {};
    const bars = (Array.isArray(data.bars) ? data.bars : []).filter(bar => bar.date && ['open','high','low','close'].every(key => bar[key] != null && Number.isFinite(Number(bar[key])) && Number(bar[key]) > 0));
    if (!bars.length) { svg.innerHTML = ''; meta.textContent = '未返回真实前复权 OHLC 日线，无法绘图。'; return; }
    const W = Math.max(950, bars.length * 11 + 105), H = 440, left = 48, right = W - 60;
    const prices = bars.flatMap(bar => [Number(bar.high), Number(bar.low)]);
    const min = Math.min(...prices), max = Math.max(...prices), pad = Math.max((max-min)*.06,.01);
    const y = value => 45 + (max + pad - Number(value)) * 295 / (max-min+2*pad);
    const x = i => left + i*11 + 5;
    const byDate = new Map(bars.map((bar,i) => [String(bar.date),i]));
    const grid = Array.from({length:5},(_,i) => { const price=min-pad+(max-min+2*pad)*i/4; return `<line x1="${left}" y1="${y(price)}" x2="${right}" y2="${y(price)}" stroke="#263842"/><text x="${right+5}" y="${y(price)+4}" fill="#a8bbc3" font-size="11">${swingNumber(price)}</text>`; }).join('');
    const candles = bars.map((bar,i) => { const color=Number(bar.close)>=Number(bar.open)?'#ef8b82':'#73dfc4', top=Math.min(y(bar.open),y(bar.close)); return `<g data-swing-bar="${escapeHtml(bar.date)}"><line x1="${x(i)}" x2="${x(i)}" y1="${y(bar.high)}" y2="${y(bar.low)}" stroke="${color}"/><rect x="${x(i)-3}" y="${top}" width="6" height="${Math.max(1.5,Math.abs(y(bar.open)-y(bar.close)))}" fill="${color}"/><title>${escapeHtml(bar.date)} 开 ${swingNumber(bar.open)} 高 ${swingNumber(bar.high)} 低 ${swingNumber(bar.low)} 收 ${swingNumber(bar.close)}</title>${i%Math.max(1,Math.ceil(bars.length/9))===0?`<text x="${x(i)}" y="415" fill="#a8bbc3" text-anchor="middle" font-size="10">${escapeHtml(String(bar.date).slice(5))}</text>`:''}</g>`; }).join('');
    const points = [...(o.last_10_peaks || []).slice(-10).map((p,i,a)=>({...p,kind:'peak',recent:i>=a.length-3})),...(o.last_10_valleys || []).slice(-10).map((p,i,a)=>({...p,kind:'valley',recent:i>=a.length-3}))];
    const marks = points.map(p => { const i=byDate.get(String(p.date)); if(i===undefined)return ''; const peak=p.kind==='peak', price=peak?p.high:p.low, color=peak?'#ffc36f':'#73dfc4'; return `<g data-swing-mark="confirmed" data-date="${escapeHtml(p.date)}"><circle cx="${x(i)}" cy="${y(price)}" r="${p.recent?7:4}" fill="${color}" stroke="${p.recent?'#fff':'#09141a'}" stroke-width="2"/><title>${peak?'确认峰':'确认谷'} 发生 ${escapeHtml(p.date)} · ${swingNumber(price)}，确认 ${escapeHtml(p.confirmed || '—')}${p.recent?' · 最近3点':''}</title></g>`; }).join('');
    const candidatePoints = [...(o.candidate_peaks || []).map(p => ({...p,kind:'peak',price:p.high})),
                             ...(o.candidate_valleys || []).map(p => ({...p,kind:'valley',price:p.low}))];
    const candidates = candidatePoints.map(p => {
      const i = byDate.get(String(p.date));
      if (i === undefined || !Number.isFinite(Number(p.price))) return '';
      return `<g data-swing-mark="candidate" data-date="${escapeHtml(p.date)}"><circle cx="${x(i)}" cy="${y(p.price)}" r="8" fill="none" stroke="#bbaaff" stroke-width="2" stroke-dasharray="3 2"/><title>未确认候选${p.kind==='peak'?'峰':'谷'} ${escapeHtml(p.date)} · ${swingNumber(p.price)}；尚需 ${Number(p.waiting_bars)||0} 根K线，并非已确认点</title></g>`;
    }).join('');
    // Never draw box lines from an unverified three-pair calculation.
    const box = o.box_audit || {};
    const boxFirst = o.box_first_state_v5;
    const verified = o.state === '区间震荡' && o.box_test === 'passed' && (boxFirst == null || boxFirst === '区间震荡' || boxFirst === 'passed' || boxFirst?.box_test === 'passed');
    const boundary = verified && [o.box_lower,o.box_upper].every(v=>v!=null && Number.isFinite(Number(v))) ? [['前三组下沿',o.box_lower],['前三组上沿',o.box_upper]].map(([label,price])=>`<g data-swing-box="verified"><line x1="${left}" x2="${right}" y1="${y(price)}" y2="${y(price)}" stroke="#8bd8ff" stroke-dasharray="5 5"/><title>${label} ${swingNumber(price)}，仅供第四组检验通过的真实箱体</title></g>`).join('') + (Number.isInteger(box.box_fourth_first_index) ? `<text x="${left}" y="20" fill="#8bd8ff" font-size="11">第四组核验通过 · 边界 ${swingNumber(o.box_lower)}～${swingNumber(o.box_upper)}</text>` : '') : '';
    const boxCheckMarks = verified ? (box.fourth_check || []).map(point => {
      const i = byDate.get(String(point.date));
      if (i === undefined || !Number.isFinite(Number(point.price))) return '';
      return `<g data-swing-box-check="fourth"><rect x="${x(i)-10}" y="${y(point.price)-10}" width="20" height="20" fill="none" stroke="#8bd8ff" stroke-width="2"/><title>第四组检验点 ${escapeHtml(point.date)} ${swingNumber(point.price)}，前三组边界 ${swingNumber(o.box_lower)}～${swingNumber(o.box_upper)}</title></g>`;
    }).join('') : '';
    svg.setAttribute('viewBox',`0 0 ${W} ${H}`); svg.setAttribute('width',String(W)); svg.innerHTML=grid+boundary+candles+marks+boxCheckMarks+candidates;
    const basis = data.price_basis === 'tdx_export_qfq' ? '通达信前复权' : (data.price_basis || '前复权');
    const boxWidth = Number.isFinite(Number(box.box_width_pct)) ? `｜前三组边界宽度 ${Number(box.box_width_pct).toFixed(1)}%，结构检验不等于窄幅整理或交易区间` : '';
    meta.textContent=`${data.symbol || '—'} ${data.name || ''}｜${basis}｜截至 ${data.as_of_date || '—'}｜前复权OHLC ${bars.length}根｜实心峰谷=已确认，虚线圈=候选；${boundary?'v5箱体检验通过：前三组边界/第四组核验':'当前无通过检验的v5箱体'}${boundary?boxWidth:''}`;
  }
  root.SwingChart = { render, chartEvidence, overlayMarkup, renderOverlay, verifiedBox };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.SwingChart;
})(typeof window !== 'undefined' ? window : globalThis);
