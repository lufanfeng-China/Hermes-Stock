/** MACD Extreme Golden Cross — frontend logic */

const API = '/api/macd-extreme-gc';

function fmt(n) { return n == null ? '-' : Math.round(Number(n)).toLocaleString('zh-CN'); }
function fmtPct(n) { return n == null ? '-' : (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%'; }
function fmtPrice(n) { return n == null ? '-' : Number(n).toFixed(2); }

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

function renderSummary(data) {
  const s = data.summary;
  const el = document.getElementById('gc-summary');
  el.innerHTML = `
    <button class="gc-stat trend-trigger" type="button" onclick="showMonthlyMtmTrend()"><div class="val">${fmt(s.equity)}</div><div class="lbl">总权益</div></button>
    <button class="gc-stat trend-trigger" type="button" onclick="showMonthlyMtmTrend()"><div class="val">${fmt(s.deployed)}</div><div class="lbl">持仓市值</div></button>
    <button class="gc-stat trend-trigger" type="button" onclick="showMonthlyMtmTrend()"><div class="val">${fmt(s.cash)}</div><div class="lbl">闲置资金</div></button>
    <div class="gc-stat"><div class="val" style="color:${s.unrealized_pnl>=0?'#10b981':'#ef4444'}">${s.unrealized_pnl ? fmtPct(s.unrealized_pnl/(s.deployed-s.unrealized_pnl||1)*100) : '+0.00%'}</div><div class="lbl">持仓盈亏</div></div>
    <div class="gc-stat"><div class="val" style="color:${s.unrealized_pnl>=0?'#10b981':'#ef4444'}">${fmt(s.unrealized_pnl)}</div><div class="lbl">持仓盈亏金额</div></div>
    <div class="gc-stat"><div class="val" style="color:${s.realized_pnl>=0?'#10b981':'#ef4444'}">${fmtPct(s.realized_pnl_pct)}</div><div class="lbl">平仓盈亏</div></div>
    <div class="gc-stat"><div class="val" style="color:${s.realized_pnl>=0?'#10b981':'#ef4444'}">${fmt(s.realized_pnl)}</div><div class="lbl">平仓盈亏金额</div></div>
    <div class="gc-stat"><div class="val" style="color:${s.equity>=s.total_capital?'#10b981':'#ef4444'}">${fmtPct((s.equity/s.total_capital-1)*100)}</div><div class="lbl" style="cursor:pointer;text-decoration:underline" onclick="showEquityHistory()">总体盈亏</div></div>
  `;
}

function renderBuySignals(buys) {
  document.getElementById('buy-count').textContent = buys.length;
  const tbody = document.getElementById('buy-tbody');
  if (!buys.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="11">无待开仓信号</td></tr>'; return; }
  tbody.innerHTML = buys.map(b => {
    const price = b.tomorrow_open || b.close;
    const qty = Math.floor(b.lot / price);
    const gapPct = b.tomorrow_open ? ((b.tomorrow_open - b.close) / b.close * 100) : ((b.latest_close - b.close) / b.close * 100);
    const alreadyHeld = cachedData?.positions?.some(p => p.code === b.code);
    const actionHtml = alreadyHeld
      ? '<span class="muted">已开</span>'
      : `<button class="btn btn-sm btn-primary" onclick="confirmOpen('${b.code}',${price},${b.lot},'${b.signal_date||''}',${b.ndif})">开仓</button>`;
    return `<tr>
      <td>${b.signal_date || '-'}</td>
      <td>${b.name || b.code} <span class="muted">${b.code}</span></td>
      <td>${fmtPrice(b.close)}</td>
      <td>${b.signal_pct5y != null ? Number(b.signal_pct5y).toFixed(1) + '%' : '-'}</td>
      <td>${b.latest_close ? fmtPrice(b.latest_close) : fmtPrice(b.close)}</td>
      <td class="${gapPct>=0?'green':'danger'}">${fmtPct(gapPct)}</td>
      <td class="${b.ndif < -3 ? 'warn' : ''}">${fmtPct(b.ndif)}</td>
      <td>${b.ma10_rise_days != null ? b.ma10_rise_days + '天' : '-'}</td>
      <td>${b.tomorrow_open ? fmtPrice(b.tomorrow_open) : '<span class="muted">-</span>'}</td>
      <td>${qty}</td>
      <td>${actionHtml}</td>
    </tr>`;
  }).join('');
}

async function confirmOpen(code, price, lot, signalDate, ndif) {
  // Prevent double-click
  if (cachedData?.positions?.some(p => p.code === code)) return;
  
  const shares = Math.floor(lot / price);
  // Disable all buttons for this code immediately
  document.querySelectorAll('button').forEach(b => {
    if (b.onclick && b.onclick.toString().includes(code)) { b.textContent = '...'; b.disabled = true; }
  });
  const result = await api('POST', API + '/open', { code, shares, price, signal_date: signalDate, ndif });
  if (result.ok) {
    const entryDate = signalDate ? (() => { const d=new Date(signalDate); d.setDate(d.getDate()+1); return d.toISOString().slice(0,10); })() : new Date().toISOString().slice(0,10);
    if (!cachedData.positions) cachedData.positions = [];
    // Remove existing to avoid duplicates
    cachedData.positions = cachedData.positions.filter(p => p.code !== code);
    const name = cachedData.buy_signals?.find(s=>s.code===code)?.name || code;
    cachedData.positions.push({code, name, total_shares: shares, avg_cost: price, close: price, pnl_pct: 0, current_value: price*shares, total_cost: price*shares, entries:[{date:entryDate, type:'开仓', price, shares, ndif}], profit_triggered:false, trigger_date:''});
    renderPositions(cachedData.positions);
    // Update buy signals table to show "已开"
    renderBuySignals(cachedData.buy_signals || []);
    // Background rescan
    await scan();
  } else { alert(result.error); }
}

function renderReplenishSignals(reps) {
  document.getElementById('rep-count').textContent = reps.length;
  const tbody = document.getElementById('rep-tbody');
  if (!reps.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="9">无待补仓信号</td></tr>'; return; }
  tbody.innerHTML = reps.map(r => {
    const price = r.tomorrow_open || r.close;
    const qty = Math.floor(r.lot / price);
    return `<tr>
      <td>${r.signal_date || '-'}</td>
      <td>${r.name || r.code} <span class="muted">${r.code}</span></td>
      <td>${fmtPrice(r.close)}</td>
      <td class="danger">${fmtPct(r.loss_pct)}</td>
      <td>${fmtPct(r.ndif)}</td>
      <td>${fmt(r.total_cost)}(${fmtPrice(r.avg_cost)})</td>
      <td>${qty}</td>
      <td>${r.tomorrow_open ? fmtPrice(r.tomorrow_open) : '<span class="muted">-</span>'}</td>
      <td><button class="btn btn-sm btn-primary" onclick="confirmReplenish('${r.code}',${price},${qty})">补仓</button></td>
    </tr>`;
  }).join('');
}

async function confirmReplenish(code, price, shares) {
  const result = await api('POST', API + '/replenish', { code, shares, price });
  if (result.ok) { await scan(); } else { alert(result.error); }
}

function renderSellCandidates(sells) {
  document.getElementById('sell-count').textContent = sells.length;
  const tbody = document.getElementById('sell-tbody');
  if (!sells.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="9">无待卖出信号</td></tr>'; return; }
  tbody.innerHTML = sells.map(s => {
    const cls = s.fell_below || s.is_deadcross ? 'danger' : 'warn';
    const triggerDate = s.trigger_date ? s.trigger_date.slice(0, 10) : '-';
    const daysSince = s.trigger_date ? Math.floor((Date.now() - new Date(s.trigger_date)) / 86400000) : '-';
    return `<tr>
      <td>${s.entry_date || '-'}</td>
      <td>${s.name || s.code} <span class="muted">${s.code}</span></td>
      <td>${fmtPrice(s.close)}</td>
      <td class="green">${fmtPct(s.pnl_pct)}</td>
      <td>${daysSince}天</td>
      <td class="${cls}">${s.status}</td>
      <td>${fmt(s.total_cost)}</td>
      <td>${fmt(s.current_value)}</td>
      <td><button class="btn-sm btn-confirm" onclick="confirmSell('${s.code}')">卖出</button></td>
    </tr>`;
  }).join('');
}

async function confirmSell(code) {
  const result = await api('POST', API + '/sell', { code });
  if (result.ok) { await scan(); } else { alert(result.error); }
}

function toggleDetail(tr, code) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains('entry-detail-row')) {
    next.remove();
  } else {
    const detailRow = document.createElement('tr');
    detailRow.classList.add('entry-detail-row');
    detailRow.innerHTML = `<td colspan="7" id="detail-${code}">加载中...</td>`;
    tr.after(detailRow);
    loadPositionDetail(code);
  }
}

async function loadPositionDetail(code) {
  const pos = (cachedData?.positions || []).find(p => p.code === code);
  const td = document.getElementById('detail-' + code);
  if (!pos || !pos.entries) { if (td) td.textContent = '无记录'; return; }

  let html = '<div class="entry-detail"><table>';
  pos.entries.forEach((e, i) => {
    html += `<tr>
      <td><input id="edit-date-${code}-${i}" value="${e.date}" style="width:100px"></td><td>${e.type}</td>
      <td>ndif ${e.ndif != null ? fmtPct(e.ndif) : '-'}</td>
      <td>价格 <input id="edit-price-${code}-${i}" value="${e.price}"></td>
      <td>股数 <input id="edit-shares-${code}-${i}" value="${e.shares}"></td>
      <td><button class="btn-sm btn-edit" onclick="saveEdit('${code}',${i})">保存</button></td>
    </tr>`;
  });
  html += '</table></div>';
  if (td) td.innerHTML = html;
}

async function saveEdit(code, index) {
  const price = parseFloat(document.getElementById(`edit-price-${code}-${index}`).value);
  const shares = parseInt(document.getElementById(`edit-shares-${code}-${index}`).value);
  const date = document.getElementById(`edit-date-${code}-${index}`).value;
  if (!price || !shares) return alert('价格和股数必填');
  const result = await api('POST', API + '/entry', { code, index, price, shares, date });
  if (result.ok) { await scan(); } else { alert(result.error); }
}

function readEntryPctRange(prefix) {
  const minRaw = document.getElementById(`${prefix}-filter-pct-min`)?.value ?? '';
  const maxRaw = document.getElementById(`${prefix}-filter-pct-max`)?.value ?? '';
  const min = minRaw === '' ? null : Number(minRaw);
  const max = maxRaw === '' ? null : Number(maxRaw);
  return { min, max, active: min !== null || max !== null };
}

function matchesEntryPct(value, range) {
  if (!range.active) return true;
  if (value == null || !Number.isFinite(Number(value))) return false;
  const pct = Number(value);
  return (range.min === null || pct >= range.min) && (range.max === null || pct <= range.max);
}

function renderPositions(positions) {
  const from = document.getElementById('pos-filter-from')?.value || '';
  const to = document.getElementById('pos-filter-to')?.value || '';
  const pctRange = readEntryPctRange('pos');
  
  let filtered = positions;
  if (from || to || pctRange.active) {
    filtered = positions.filter(p => {
      const ed = p.entries && p.entries.length ? p.entries[0].date : '';
      if (from && ed < from) return false;
      if (to && ed > to) return false;
      const pct5y = p.entry_pct5y ?? (p.entries && p.entries[0] ? p.entries[0].pct5y : null);
      if (!matchesEntryPct(pct5y, pctRange)) return false;
      return true;
    });
  }
  
  document.getElementById('pos-count').textContent = filtered.length;
  const stats = MacdExtremeGcUtils.calculatePositionFilterStats(filtered);
  const statsEl = document.getElementById('pos-filter-stats');
  if (statsEl) {
    const cls = stats.pnl >= 0 ? 'green' : 'danger';
    statsEl.innerHTML = `持仓盈亏 <span class="${cls}">${fmt(stats.pnl)}（${fmtPct(stats.pnlPct)}）</span>`;
  }
  const tbody = document.getElementById('pos-tbody');
  if (!filtered.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="10">无持仓</td></tr>'; return; }
  // Sort by entry date descending
  const sorted = [...filtered].sort((a, b) => {
    const da = a.entries && a.entries.length ? a.entries[0].date : '';
    const db = b.entries && b.entries.length ? b.entries[0].date : '';
    return db.localeCompare(da);
  });
  tbody.innerHTML = sorted.map(p => {
    const cls = p.pnl_pct >= 0 ? 'green' : 'danger';
    const entryDate = p.entries && p.entries.length ? p.entries[0].date : '-';
    const lots = p.entries ? p.entries.length : 0;
    const pct5yValue = p.entry_pct5y ?? (p.entries && p.entries[0] ? p.entries[0].pct5y : null);
    const pct5y = pct5yValue != null ? pct5yValue + '%' : '<span class="muted">历史不足</span>';
    return `<tr id="pos-${p.code}">
      <td>${p.name || p.code} <span class="muted">${p.code}</span></td>
      <td>${entryDate}</td>
      <td>${lots}</td>
      <td>${fmt(p.total_shares)}</td>
      <td>${fmtPrice(p.avg_cost)}</td>
      <td>${fmtPrice(p.close)}</td>
      <td class="${cls}">${fmtPct(p.pnl_pct)}</td>
      <td>${fmt(p.current_value)}</td>
      <td>${pct5y}</td>
      <td><button class="btn-sm btn-edit" onclick="toggleDetail(this.parentElement.parentElement,'${p.code}')">+</button></td>
    </tr>`;
  }).join('');
}

function renderHistory(history) {
  const from = document.getElementById('hist-filter-from')?.value || '';
  const to = document.getElementById('hist-filter-to')?.value || '';
  const pctRange = readEntryPctRange('hist');
  
  let filtered = history;
  if (from || to || pctRange.active) {
    filtered = history.filter(h => {
      const ed = h.entry_date || h.date || '';
      if (from && ed < from) return false;
      if (to && ed > to) return false;
      if (!matchesEntryPct(h.pct5y, pctRange)) return false;
      return true;
    });
  }
  
  document.getElementById('hist-count').textContent = filtered.length;
  const stats = MacdExtremeGcUtils.calculateHistoryFilterStats(filtered);
  const statsEl = document.getElementById('hist-filter-stats');
  if (statsEl) {
    const cls = stats.pnl >= 0 ? 'green' : 'danger';
    const averageDays = stats.averageHoldingDays == null ? '—' : `${stats.averageHoldingDays.toFixed(1)}天`;
    statsEl.innerHTML = `平仓盈亏 <span class="${cls}">${fmt(stats.pnl)}（${fmtPct(stats.pnlPct)}）</span> · 平均持仓 ${averageDays}`;
  }
  const tbody = document.getElementById('hist-tbody');
  if (!filtered.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty-row">无记录</td></tr>'; return; }
  tbody.innerHTML = [...filtered].sort((a,b) => (b.entry_date||'').localeCompare(a.entry_date||'')).map(h => {
    const cls = h.pnl >= 0 ? 'green' : 'danger';
    const pct5y = h.pct5y != null ? h.pct5y + '%' : '<span class="muted">历史不足</span>';
    const entryD = h.entry_date ? h.entry_date.slice(0,10) : '-';
    const exitD = h.date ? h.date.slice(0,10) : '-';
    return `<tr>
      <td>${entryD}</td>
      <td>${exitD}</td>
      <td>${h.name || h.code} <span class="muted">${h.code}</span></td>
      <td>${h.exit_reason}</td>
      <td>${fmt(h.buy_cost)}</td>
      <td>${fmt(h.sell_rev)}</td>
      <td class="${cls}">${fmt(h.pnl)}</td>
      <td>${pct5y}</td>
    </tr>`;
  }).join('');
}

function getCapital() { return parseInt(document.getElementById('gc-capital').value) * 10000 || 3000000; }
function getLot() { return parseInt(document.getElementById('gc-lot').value) * 10000 || 50000; }
function getExitParams() {
  const profit_target = Number(document.getElementById('gc-profit-target').value);
  const retrace_floor = Number(document.getElementById('gc-retrace-floor').value);
  if (!Number.isFinite(profit_target) || !Number.isFinite(retrace_floor) || profit_target <= 0 || retrace_floor < 0 || retrace_floor >= profit_target) {
    throw new Error('卖出触发必须大于回撤触发，且回撤触发不能为负数');
  }
  return { profit_target, retrace_floor };
}
function getDateFrom() { return document.getElementById('gc-date-from').value || ''; }
function getDateTo() { return document.getElementById('gc-date-to').value || ''; }
function getStock() { return document.getElementById('gc-stock').value.trim(); }

let cachedData = null;  // last scan result

async function scan() {
  document.getElementById('gc-status').textContent = '扫描中...';
  try {
    const df = getDateFrom(); const dt = getDateTo(); const stk = getStock();
    const params = 'capital=' + getCapital() + '&lot=' + getLot()
      + (df ? '&date_from=' + df : '') + (dt ? '&date_to=' + dt : '')
      + (stk ? '&stock=' + stk : '');
    const data = await api('GET', API + '?' + params);
    if (!data || !data.summary) { document.getElementById('gc-status').textContent = '✗ ' + (data?.error || '扫描异常'); return; }
    cachedData = data;
    renderSummary(data);
    renderBuySignals(data.buy_signals || []);
    renderReplenishSignals(data.replenish_signals || []);
    renderSellCandidates(data.sell_candidates || []);
    renderPositions(data.positions || []);
    renderHistory(data.history || []);
    renderIndustry();
    const basis = data.data_basis || {};
    const basisLabel = basis.signal === 'tdx_export_qfq'
      ? ' · 信号：通达信前复权；成交/盯市：原始价'
      : '';
    document.getElementById('gc-status').textContent = '✓ ' + (data.today || '') + basisLabel;
  } catch (e) {
    document.getElementById('gc-status').textContent = '✗ 扫描失败: ' + e.message;
  }
}

function renderIndustry() {
  const mode = document.getElementById('ind-mode')?.value || 'positions';
  
  let counts = {};
  if (mode === 'history') {
    (cachedData?.history_industry_distribution || []).forEach(i => {
      counts[i.name] = i.count;
    });
  } else {
    // Use positions
    (cachedData?.industry_distribution || []).forEach(i => {
      counts[i.name] = i.count;
    });
  }
  
  const items = Object.entries(counts).sort((a,b) => b[1] - a[1]);
  document.getElementById('ind-count').textContent = items.reduce((s,i) => s + i[1], 0);
  const el = document.getElementById('ind-dist');
  if (!items.length) { el.innerHTML = '<span class="muted">无数据</span>'; return; }
  el.innerHTML = items.map(([name, count]) => 
    `<div class="stat-card" style="min-width:auto;padding:8px 14px">
      <div class="val" style="font-size:16px">${count}</div>
      <div class="lbl">${name}</div>
    </div>`
  ).join('');
}

function fmtWan(n) { return n == null ? '-' : `${(Number(n) / 10000).toFixed(2)}万`; }

function showStrategyPlan() {
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999;padding:20px';
  modal.innerHTML = `<section role="dialog" aria-modal="true" aria-label="极值金叉方案" style="background:var(--canvas);border-radius:24px;padding:28px;max-width:760px;width:100%;max-height:85vh;overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,.28)">
    <header style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px">
      <div><p class="eyebrow">STRATEGY SPECIFICATION</p><h2 style="font-size:22px">极值金叉 · 方案说明</h2></div>
      <button class="btn btn-sm btn-secondary" type="button" aria-label="关闭">✕</button>
    </header>
    <div style="display:grid;gap:16px;line-height:1.7">
      <div><strong>标的与周期</strong><br><span class="muted">当前 CSI300 固定成分股，日线；MACD 参数 12 / 26 / 9。NDIF 为 DIF ÷ 收盘价。</span></div>
      <div><strong>开仓</strong><br><span class="muted">收盘确认 MACD 金叉、NDIF &lt; -1%、MA10 上升；下一交易日开盘买入 1 份。每份金额由页面“每份(万)”设定，默认 5 万。</span></div>
      <div><strong>补仓</strong><br><span class="muted">已持仓标的再次满足开仓信号，且持仓亏损超过 20%、NDIF &lt; -3%，下一交易日开盘补 1 份。</span></div>
      <div><strong>卖出</strong><br><span class="muted">浮盈超过 20% 后进入等待；出现 MACD 死叉或盈利回落至低于 +15% 时，下一交易日开盘卖出。</span></div>
      <div><strong>组合与回测</strong><br><span class="muted">按信号日收盘判定、T+1 开盘成交；逐日现金不透支。权益采用严格 MTM：真实现金 + 未平仓每日收盘市值。开仓 5 年价格分位仅用于页面筛选和观察，不参与任何交易条件。</span></div>
    </div>
  </section>`;
  const close = () => modal.remove();
  modal.querySelector('button').addEventListener('click', close);
  modal.addEventListener('click', event => { if (event.target === modal) close(); });
  document.body.appendChild(modal);
}

async function showBacktestSummary() {
  const button = document.getElementById('gc-backtest-summary');
  button.disabled = true;
  button.textContent = '计算中...';
  let summary;
  try {
    summary = await api('POST', API + '/backtest-summary', {
      start: document.getElementById('gc-bt-start').value || '2012-01-01',
      lot: getLot(), ...getExitParams(),
    });
    if (!summary.ok) throw new Error(summary.error || '总结回测失败');
  } catch (error) {
    alert(error.message || String(error));
    return;
  } finally {
    button.disabled = false;
    button.textContent = '总结';
  }
  const rows = summary.rows.map(row => {
    const returnClass = row.totalReturnPct >= 0 ? 'green' : 'danger';
    return `<tr>
      <td>${fmtWan(row.capital)}</td>
      <td>${fmtWan(row.finalEquity)}</td>
      <td class="${returnClass}">${fmtPct(row.totalReturnPct)}</td>
      <td class="${returnClass}">${fmtPct(row.annualizedReturnPct)}</td>
      <td>${fmt(row.executed)}</td>
      <td>${fmt(row.closedPositions)}</td>
      <td>${fmt(row.openPositions)}</td>
      <td>${fmt(row.rejectedForCash)}</td>
    </tr>`;
  }).join('');

  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999;padding:20px';
  modal.innerHTML = `<section role="dialog" aria-modal="true" aria-label="极值金叉回测总结" style="background:var(--canvas);border-radius:24px;padding:28px;max-width:980px;width:100%;max-height:85vh;overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,.28)">
    <header style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px">
      <div><p class="eyebrow">BACKTEST SUMMARY · MTM</p><h2 style="font-size:22px">极值金叉：${summary.start} 至今资金对比</h2></div>
      <button class="btn btn-sm btn-secondary" type="button" aria-label="关闭">✕</button>
    </header>
    <p class="muted" style="margin-bottom:16px">${summary.start} 至 ${summary.asOf}（2026 为 YTD） · 每份 ${fmtWan(summary.lotCash)} · 开仓：${summary.entryRule} · ${summary.method}</p>
    <div style="overflow-x:auto"><table><thead><tr>
      <th>初始资金</th><th>期末权益</th><th>累计MTM收益</th><th>年化</th><th>已执行</th><th>已平仓</th><th>期末持仓</th><th>现金拒绝</th>
    </tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted" style="margin-top:16px;line-height:1.65">信号使用通达信前复权日线；成交使用原始 T+1 开盘价，权益 = 真实现金 + 未平仓按原始收盘价计算的市值（严格 MTM）。信号收盘确认、逐日现金不透支。使用当前 CSI300 固定成分股，存在幸存者偏差；未计佣金、印花税与滑点。</p>
  </section>`;
  const close = () => modal.remove();
  modal.querySelector('button').addEventListener('click', close);
  modal.addEventListener('click', event => { if (event.target === modal) close(); });
  document.body.appendChild(modal);
}

function fmtTrendValue(value) {
  return `${(Number(value) / 10000).toFixed(0)}万`;
}

function renderMonthlyTrendSvg(rows, key, label, color) {
  const width = 720;
  const height = 190;
  const pad = 34;
  const chart = MacdExtremeGcTrendUtils.buildMonthlyLineGeometry(rows, key, { width, height, pad });
  const grid = Array.from({ length: 4 }, (_, index) => {
    const y = pad + (height - pad * 2) * index / 3;
    const value = chart.max - (chart.max - chart.min) * index / 3;
    return `<line x1="${pad}" x2="${width - pad}" y1="${y}" y2="${y}" stroke="#e6e6e6"/><text x="${width - 4}" y="${y + 4}" text-anchor="end" fill="#777" font-size="10">${fmtTrendValue(value)}</text>`;
  }).join('');
  const ticks = [0, Math.floor((rows.length - 1) / 2), rows.length - 1]
    .filter((value, index, list) => list.indexOf(value) === index)
    .map(index => `<text x="${chart.points[index].x}" y="${height - 7}" text-anchor="middle" fill="#777" font-size="10">${rows[index].month}</text>`)
    .join('');
  const latest = chart.latest;
  return `<article style="border:1px solid var(--hairline);border-radius:14px;padding:14px 12px;background:var(--surface-soft)">
    <div style="display:flex;justify-content:space-between;gap:12px;margin:0 6px 6px"><strong>${label}</strong><span class="muted">${latest.month} · ${fmtTrendValue(latest.value)}</span></div>
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="190" role="img" aria-label="${label}走势">
      ${grid}<path d="${chart.path}" fill="none" stroke="${color}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${latest.x}" cy="${latest.y}" r="4" fill="${color}" stroke="#fff" stroke-width="2"/>${ticks}
    </svg>
  </article>`;
}

async function showMonthlyMtmTrend() {
  const data = await api('GET', API + '/equity-history');
  const rows = (data?.history || []).filter(row => row.month && ["cash", "market_value", "equity"].every(key => Number.isFinite(Number(row[key]))));
  if (!rows.length) {
    alert('暂无月度 MTM 趋势数据。请先运行历史回测生成数据。');
    return;
  }
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;z-index:9999;padding:20px';
  modal.innerHTML = `<section role="dialog" aria-modal="true" aria-label="极值金叉资金走势" style="background:var(--canvas);border-radius:24px;padding:28px;max-width:880px;width:100%;max-height:88vh;overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,.28)">
    <header style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px">
      <div><p class="eyebrow">MONTHLY MTM</p><h2 style="font-size:22px">资金走势</h2><p class="muted">每月最后一个交易日 · 严格 MTM</p></div>
      <button class="btn btn-sm btn-secondary" type="button" aria-label="关闭">✕</button>
    </header>
    <div style="display:grid;gap:14px">
      ${renderMonthlyTrendSvg(rows, 'equity', '总权益', '#111')}
      ${renderMonthlyTrendSvg(rows, 'market_value', '持仓市值', '#1ea64a')}
      ${renderMonthlyTrendSvg(rows, 'cash', '闲置资金', '#7a5af8')}
    </div>
    <p class="muted" style="margin-top:14px">总权益 = 持仓市值 + 闲置资金。走势以每月最后一个交易日收盘后的真实现金与未平仓市值计算。</p>
  </section>`;
  const close = () => modal.remove();
  modal.querySelector('button').addEventListener('click', close);
  modal.addEventListener('click', event => { if (event.target === modal) close(); });
  document.body.appendChild(modal);
}

async function showEquityHistory() {
  return showMonthlyMtmTrend();
}

document.getElementById('gc-scan').addEventListener('click', scan);
document.getElementById('gc-backtest-summary').addEventListener('click', showBacktestSummary);
const planTitle = document.getElementById('gc-plan-title');
planTitle.addEventListener('click', showStrategyPlan);
planTitle.addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    showStrategyPlan();
  }
});

// Backtest button
document.getElementById('gc-backtest').addEventListener('click', async () => {
  const start = document.getElementById('gc-bt-start').value;
  if (!start) return alert('请选择回测起点');
  document.getElementById('gc-backtest').disabled = true;
  document.getElementById('gc-backtest').textContent = '运行中...';
  try {
    const result = await api('POST', API + '/backtest', {
      start, capital: getCapital(), lot: getLot(), ...getExitParams()
    });
    if (result.ok) {
      await scan();
      document.getElementById('gc-status').textContent = 
        `✓ 回测完成: ${result.executed}笔执行 ${result.positions}只持仓 ${result.history}笔平仓`;
    } else {
      alert(result.error || '回测失败');
    }
  } catch(e) { alert('回测失败: ' + e.message); }
  document.getElementById('gc-backtest').disabled = false;
  document.getElementById('gc-backtest').textContent = '历史回测';
});

// Auto-load on page open
scan();
