// backtest.js — Interactive backtest config + result rendering

const EXIT_LABELS = {take_profit:'🟢 止盈', stop_loss:'🔴 止损', ma_stop:'🔵 均线', trailing_stop:'🟣 回撤', expired:'🟡 到期', force_close:'⚪ 强平'};
const EXIT_COLORS = {take_profit:'#00e676', stop_loss:'#ff5252', ma_stop:'#448aff', trailing_stop:'#ce93d8', expired:'#ffc107', force_close:'#888'};
const EXIT_NAMES = {take_profit:'止盈', stop_loss:'止损', ma_stop:'均线', trailing_stop:'回撤', expired:'到期', force_close:'强平'};

// --- Form Submission ---

function initForm() {
  var form = document.getElementById('backtest-form');
  if (!form) return;
  form.addEventListener('submit', function(e) {
    e.preventDefault();
    runBacktest();
  });
}

function getFormData() {
  var start = document.getElementById('bt-start').value.trim();
  var end = document.getElementById('bt-end').value.trim();
  var strategy = document.getElementById('bt-strategy').value;
  var stopLoss = parseFloat(document.getElementById('bt-stop-loss').value) || 0;
  var takeProfit = parseFloat(document.getElementById('bt-take-profit').value) || 0;
  var maPeriod = parseInt(document.getElementById('bt-ma').value) || 0;
  var trailingPct = parseFloat(document.getElementById('bt-trailing').value) || 0;
  var maxHold = parseInt(document.getElementById('bt-max-hold').value) || 20;
  var maxHoldings = parseInt(document.getElementById('bt-max-holdings').value) || 10;

  return {
    start_date: start,
    end_date: end,
    strategy: strategy || null,
    stop_loss_pct: stopLoss / 100,
    take_profit_pct: takeProfit / 100,
    ma_period: maPeriod || null,
    trailing_pct: trailingPct ? trailingPct / 100 : null,
    max_hold_days: maxHold,
    max_holdings: maxHoldings
  };
}

function validateForm() {
  var start = document.getElementById('bt-start').value.trim();
  var end = document.getElementById('bt-end').value.trim();
  if (!start || !end) {
    showError('请填写起始日期和结束日期');
    return false;
  }
  if (start > end) {
    showError('起始日期不能晚于结束日期');
    return false;
  }
  return true;
}

async function runBacktest() {
  hideError();
  if (!validateForm()) return;

  var data = getFormData();
  var btn = document.getElementById('bt-run-btn');
  var status = document.getElementById('bt-status');
  var loading = document.getElementById('bt-loading');
  var results = document.getElementById('bt-results');

  btn.disabled = true;
  status.textContent = '提交中...';
  loading.classList.add('active');
  results.classList.remove('active');
  hideError();

  try {
    var resp = await fetch('/api/run-backtest', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    var body = await resp.json();

    if (!body.ok) {
      throw new Error(body.error || '回测失败');
    }

    status.textContent = '回测完成，正在加载结果...';

    // Fetch the result JSON
    var resultResp = await fetch(body.result_path);
    if (!resultResp.ok) {
      throw new Error('无法加载回测结果: ' + resultResp.status);
    }
    var resultData = await resultResp.json();

    // Render
    renderConfig(data);
    renderSummary(resultData.summary);
    renderExitPie(resultData.summary && resultData.summary.exit_reasons || {});
    renderReturnHist(resultData.summary && resultData.summary.return_distribution || {});
    renderTrades(resultData.trades || []);

    results.classList.add('active');
    status.textContent = '回测完成';
    setTimeout(function() { status.textContent = ''; }, 3000);

  } catch (e) {
    showError('回测失败: ' + e.message);
    status.textContent = '';
  } finally {
    btn.disabled = false;
    loading.classList.remove('active');
  }
}

function showError(msg) {
  var el = document.getElementById('bt-error');
  el.textContent = msg;
  el.classList.add('active');
}

function hideError() {
  var el = document.getElementById('bt-error');
  el.textContent = '';
  el.classList.remove('active');
}

// --- Rendering (same as before, from backtest.js) ---

function renderConfig(cfg) {
  var el = document.getElementById('backtest-config');
  if (!el || !cfg) return;
  var parts = [];
  if (cfg.strategy) parts.push('策略: ' + cfg.strategy);
  parts.push(cfg.start_date + ' ~ ' + cfg.end_date);
  parts.push('最大持仓: ' + cfg.max_holdings + '只');
  if (cfg.stop_loss_pct != null && cfg.stop_loss_pct !== 0) parts.push('止损: ' + (cfg.stop_loss_pct * 100).toFixed(0) + '%');
  if (cfg.take_profit_pct != null && cfg.take_profit_pct !== 0) parts.push('止盈: ' + (cfg.take_profit_pct * 100).toFixed(0) + '%');
  if (cfg.ma_period) parts.push('均线: MA' + cfg.ma_period);
  if (cfg.trailing_pct) parts.push('回撤: ' + (cfg.trailing_pct * 100).toFixed(0) + '%');
  parts.push('最长持仓: ' + cfg.max_hold_days + '天');
  el.textContent = parts.join(' | ');
}

function renderSummary(s) {
  var el = document.getElementById('backtest-summary');
  if (!el) return;
  if (!s || !s.total_trades) {
    el.innerHTML = '<p class="muted">无交易数据</p>';
    return;
  }
  el.innerHTML =
    '<article class="metric-card"><p class="metric-label">总交易</p><p class="metric-value">' + s.total_trades + '笔</p></article>' +
    '<article class="metric-card"><p class="metric-label">胜率</p><p class="metric-value">' + (s.win_rate * 100).toFixed(1) + '%</p></article>' +
    '<article class="metric-card"><p class="metric-label">平均收益</p><p class="metric-value" style="color:' + (s.avg_return >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (s.avg_return * 100).toFixed(2) + '%</p></article>' +
    '<article class="metric-card"><p class="metric-label">盈亏比</p><p class="metric-value">' + s.profit_factor + '</p></article>' +
    '<article class="metric-card"><p class="metric-label">平均持仓</p><p class="metric-value">' + s.avg_hold_days + '天</p></article>' +
    '<article class="metric-card"><p class="metric-label">最大/最小</p><p class="metric-value"><span style="color:var(--green)">+' + (s.max_return * 100).toFixed(1) + '%</span><span style="color:var(--muted)"> / </span><span style="color:var(--red)">' + (s.min_return * 100).toFixed(1) + '%</span></p></article>';
}

function renderExitPie(reasons) {
  var svg = document.getElementById('exit-pie');
  var legend = document.getElementById('exit-legend');
  if (!svg) return;

  var total = Object.values(reasons).reduce(function(a, b) { return a + b; }, 0);
  if (!total) { svg.innerHTML = ''; legend.innerHTML = ''; return; }

  var entries = Object.entries(reasons).sort(function(a, b) { return b[1] - a[1]; });
  var cx = 100, cy = 100, r = 80;
  var html = '';
  var angle = -Math.PI / 2;
  var legendItems = [];

  for (var i = 0; i < entries.length; i++) {
    var key = entries[i][0];
    var count = entries[i][1];
    var slice = (count / total) * Math.PI * 2;
    var x1 = cx + r * Math.cos(angle);
    var y1 = cy + r * Math.sin(angle);
    var x2 = cx + r * Math.cos(angle + slice);
    var y2 = cy + r * Math.sin(angle + slice);
    var large = slice > Math.PI ? 1 : 0;
    var color = EXIT_COLORS[key] || '#666';
    var label = EXIT_NAMES[key] || key;

    html += '<path d="M' + cx + ',' + cy + ' L' + x1 + ',' + y1 + ' A' + r + ',' + r + ' 0 ' + large + ',1 ' + x2 + ',' + y2 + ' Z" fill="' + color + '" stroke="var(--bg)" stroke-width="1"/>';
    legendItems.push('<span style="color:' + color + '">\u25cf ' + label + ': ' + count + ' (' + (count / total * 100).toFixed(0) + '%)</span>');
    angle += slice;
  }

  svg.innerHTML = html;
  legend.innerHTML = legendItems.join('&nbsp;&nbsp;');
}

function renderReturnHist(dist) {
  var svg = document.getElementById('return-hist');
  if (!svg) return;

  var entries = Object.entries(dist);
  var maxCount = Math.max.apply(null, entries.map(function(e) { return e[1]; }).concat([1]));
  var barW = 38, gap = 8, totalW = entries.length * (barW + gap) - gap;
  var startX = 30;
  var chartH = 150, bottomY = 170;

  var html = '';
  for (var i = 0; i <= 4; i++) {
    var y = bottomY - (chartH * i / 4);
    var val = Math.round(maxCount * i / 4);
    html += '<line x1="' + (startX - 2) + '" x2="' + (startX + totalW) + '" y1="' + y + '" y2="' + y + '" stroke="var(--border)" stroke-dasharray="3,3"/>';
    html += '<text x="' + (startX - 6) + '" y="' + (y + 4) + '" text-anchor="end" fill="var(--muted)" font-size="9">' + val + '</text>';
  }

  entries.forEach(function(e) {
    var label = e[0], count = e[1];
    var x = startX + entries.indexOf(e) * (barW + gap);
    var h = Math.max(1, (count / maxCount) * chartH);
    var y = bottomY - h;
    var isNeg = count > 0 && label.indexOf('-') !== -1;
    var color = count > 0 && isNeg ? 'var(--red)' : count > 0 && !isNeg ? 'var(--green)' : 'var(--border)';
    html += '<rect x="' + x + '" y="' + y + '" width="' + barW + '" height="' + h + '" fill="' + color + '" opacity="0.8" rx="2"/>';
    html += '<text x="' + (x + barW / 2) + '" y="' + (bottomY + 14) + '" text-anchor="middle" fill="var(--muted)" font-size="9">' + label + '</text>';
    html += '<text x="' + (x + barW / 2) + '" y="' + (y - 4) + '" text-anchor="middle" fill="var(--text)" font-size="10">' + count + '</text>';
  });

  svg.innerHTML = html;
}

function renderTrades(trades) {
  var countEl = document.getElementById('trade-count');
  if (countEl) countEl.textContent = String(trades.length);
  var tbody = document.querySelector('#trades-table tbody');
  if (!tbody) return;
  tbody.innerHTML = trades.map(function(t) {
    return '<tr>' +
      '<td>' + esc(t.name) + ' <span class="stock-screener-symbol">' + esc(t.symbol) + '</span></td>' +
      '<td>' + t.signal_date + '</td>' +
      '<td>' + t.buy_date + '</td>' +
      '<td class="num">' + t.buy_price + '</td>' +
      '<td>' + t.sell_date + '</td>' +
      '<td class="num">' + t.sell_price + '</td>' +
      '<td class="num" style="color:' + (t['return'] >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (t['return'] * 100).toFixed(2) + '%</td>' +
      '<td class="num">' + t.hold_days + '天</td>' +
      '<td>' + (EXIT_LABELS[t.exit_reason] || t.exit_reason) + '</td>' +
      '</tr>';
  }).join('');
}

function esc(s) { return String(s).replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

// --- Init ---
initForm();
