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
    <div class="gc-stat"><div class="val">${fmt(s.equity)}</div><div class="lbl">总权益</div></div>
    <div class="gc-stat"><div class="val">${fmt(s.deployed)}</div><div class="lbl">持仓市值</div></div>
    <div class="gc-stat"><div class="val">${fmt(s.cash)}</div><div class="lbl">闲置资金</div></div>
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
  if (!buys.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="10">无待开仓信号</td></tr>'; return; }
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

function renderPositions(positions) {
  const from = document.getElementById('pos-filter-from')?.value || '';
  const to = document.getElementById('pos-filter-to')?.value || '';
  
  let filtered = positions;
  if (from || to) {
    filtered = positions.filter(p => {
      const ed = p.entries && p.entries.length ? p.entries[0].date : '';
      if (from && ed < from) return false;
      if (to && ed > to) return false;
      return true;
    });
  }
  
  document.getElementById('pos-count').textContent = filtered.length;
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
    const pct5y = p.entries && p.entries[0].pct5y != null ? p.entries[0].pct5y + '%' : '-';
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
  
  let filtered = history;
  if (from || to) {
    filtered = history.filter(h => {
      const ed = h.entry_date || h.date || '';
      if (from && ed < from) return false;
      if (to && ed > to) return false;
      return true;
    });
  }
  
  document.getElementById('hist-count').textContent = filtered.length;
  const tbody = document.getElementById('hist-tbody');
  if (!filtered.length) { tbody.innerHTML = '<tr><td colspan="7" class="empty-row">无记录</td></tr>'; return; }
  tbody.innerHTML = [...filtered].sort((a,b) => (b.entry_date||'').localeCompare(a.entry_date||'')).map(h => {
    const cls = h.pnl >= 0 ? 'green' : 'danger';
    const pct5y = h.pct5y != null ? h.pct5y + '%' : '-';
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
    document.getElementById('gc-status').textContent = '✓ ' + (data.today || '');
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

async function showEquityHistory() {
  const data = await api('GET', API + '/equity-history');
  if (!data || !data.history) return;
  const rows = data.history.map(h => {
    const last = data.history[0]; 
    const pct = h.equity / (cachedData?.summary?.total_capital || 3000000);
    return `<tr><td>${h.week}</td><td style="text-align:right">${fmt(h.equity)}</td><td style="text-align:right;color:${pct>=1?'#10b981':'#ef4444'}">${fmtPct((pct-1)*100)}</td></tr>`;
  }).join('');
  
  const modal = document.createElement('div');
  modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999';
  modal.innerHTML = `<div style="background:var(--canvas);border-radius:24px;padding:24px;max-width:500px;max-height:70vh;overflow-y:auto;width:90%">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h3 style="margin:0">权益趋势（周）</h3>
      <button class="btn btn-sm btn-secondary" onclick="this.closest('div').parentElement.remove()">✕</button>
    </div>
    <table class="gc-table"><thead><tr><th>周</th><th style="text-align:right">权益</th><th style="text-align:right">累计</th></tr></thead>
    <tbody>${rows}</tbody></table>
  </div>`;
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
  document.body.appendChild(modal);
}

document.getElementById('gc-scan').addEventListener('click', scan);

// Backtest button
document.getElementById('gc-backtest').addEventListener('click', async () => {
  const start = document.getElementById('gc-bt-start').value;
  if (!start) return alert('请选择回测起点');
  document.getElementById('gc-backtest').disabled = true;
  document.getElementById('gc-backtest').textContent = '运行中...';
  try {
    const result = await api('POST', API + '/backtest', {
      start, capital: getCapital(), lot: getLot()
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
