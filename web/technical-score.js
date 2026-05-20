// technical-score.js — Technical evaluation page
// Uses /api/technical-eval for direct single-stock lookup

const $input = document.getElementById('search-input');
const $btn = document.getElementById('search-btn');
const $status = document.getElementById('status');
const $content = document.getElementById('content');

$btn.addEventListener('click', () => search($input.value.trim()));
$input.addEventListener('keydown', e => { if (e.key === 'Enter') search($input.value.trim()); });

async function search(query) {
  if (!query) return;
  $status.textContent = '...';
  $status.className = 'loading';

  let market = 'sh';
  let symbol = query;
  if (query.length >= 8 && query[1] === 'h') {
    market = query.substring(0, 2).toLowerCase();
    symbol = query.substring(2);
  } else if (symbol.startsWith('6') || symbol.startsWith('5') || symbol.startsWith('9')) {
    market = 'sh';
  } else if (symbol.startsWith('0') || symbol.startsWith('3')) {
    market = 'sz';
  } else {
    market = 'bj';
  }

  if (symbol.length !== 6 || !/^\d{6}$/.test(symbol)) {
    // Name search: resolve via stock-search API
    try {
      const r = await fetch(`/api/stock-search?q=${encodeURIComponent(query)}&limit=1`);
      const d = await r.json();
      if (d.ok && d.results?.length > 0) {
        const s = d.results[0];
        market = s.market; symbol = s.symbol;
      } else { $status.textContent = '未找到'; return; }
    } catch { $status.textContent = '搜索失败'; return; }
  }

  try {
    const url = `/api/technical-eval?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`;
    const r = await fetch(url);
    const d = await r.json();
    if (!d.ok) {
      $status.textContent = d.error || '无数据';
      return;
    }
    render(d);
    $status.textContent = '';
  } catch (e) {
    $status.textContent = '错误: ' + e.message;
    $status.className = 'red';
  }
}

function render(d) {
  const name = d.stock_name || (d.market + ':' + d.symbol);
  const price = d.latest_close ? d.latest_close.toFixed(2) : '--';
  const code = (d.market || '').toUpperCase() + ':' + (d.symbol || '');

  // Fields are returned without tech_ prefix from /api/technical-eval
  const trend = d.trend || '--';
  const trendLabel = d.trend_label || '--';
  const trendDetail = d.trend_detail || '';
  const momentum = d.momentum || '--';
  const momentumLabel = d.momentum_label || '--';
  const momentumDetail = d.momentum_detail || '';
  const volume = d.volume_signal || '--';
  const volumeLabel = d.volume_label || '--';
  const volumeDetail = d.volume_detail || '';
  const position = d.position || '--';
  const positionLabel = d.position_label || '--';
  const positionDetail = d.position_detail || '';
  const conclusion = d.conclusion || 'hold_watch';
  const conclusionLabel = d.conclusion_label || '--';
  const conclusionColor = d.conclusion_color || 'yellow';
  const conclusionReason = d.conclusion_reason || '';

  // Buy trigger
  const buyTriggers = d.buy_triggers || [];
  const bestTrigger = buyTriggers[0] || d;
  const buyTrigger = d.buy_trigger;
  const buyLabel = d.buy_trigger_label;
  const buyDetail = d.buy_trigger_detail;
  const entryPrice = d.entry_price;
  const stopLoss = d.stop_loss;
  const riskPct = d.risk_pct;

  const signalEmoji = {
    strong_bullish: '🟢', bullish: '🟢', recovering: '🟡',
    neutral: '🟡', bearish: '🔴', strong_bearish: '🔴',
    super_strong: '🟢', strong: '🟢', startup: '🟢',
    early_startup: '🟡', weak: '🔴',
    bullish: '🟢', normal: '🟡', low_volume: '🟡', divergence: '🔴',
    low: '🟢', mid: '🟡', high: '🔴', overheated: '🔴', new_stock: '⚪',
  };

  const dimSignal = (label, val, detail) => {
    const emoji = signalEmoji[val] || '⚪';
    return `
      <div class="signal-row">
        <span class="signal-icon">${emoji}</span>
        <span class="signal-label">${label}</span>
        <span class="signal-detail">${detail || ''}</span>
      </div>`;
  };

  // Buy trigger section
  let buyHTML = '';
  if (buyTrigger) {
    const isWatch = conclusion === 'buy_watch';
    buyHTML = `
    <div class="buy-card${isWatch ? ' watch' : ''}">
      <div style="font-weight:700;margin-bottom:6px">⚡ ${isWatch ? '买点观察' : '买入信号'}: ${buyLabel || buyTrigger}</div>
      ${buyDetail ? `<div class="meta">${buyDetail}</div>` : ''}
      ${entryPrice ? `<div class="meta">买入参考价: <b>¥${entryPrice}</b></div>` : ''}
      ${stopLoss ? `<div class="meta">止损价: <b class="stop-loss red">¥${stopLoss}</b></div>` : ''}
      ${riskPct != null ? `<div class="meta">风险比例: <b>${(riskPct*100).toFixed(1)}%</b></div>` : ''}
    </div>`;
  }

  // Conclusion
  const concClass = conclusionColor === 'green' ? 'highlight-green' :
                    conclusionColor === 'red' ? 'highlight-red' :
                    conclusionColor === 'gray' ? 'highlight-gray' : 'highlight-yellow';
  const concEmoji = conclusionColor === 'green' ? '🟢' :
                    conclusionColor === 'red' ? '🔴' : '🟡';

  $content.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div>
          <span style="font-size:18px;font-weight:700">${name}</span>
          <span style="font-size:12px;color:var(--muted);margin-left:8px">${code}</span>
        </div>
        <span style="font-size:20px;font-weight:700">¥${price}</span>
      </div>
    </div>

    <div class="card">
      <h3>📈 六维技术评估</h3>
      ${dimSignal('趋势', trend, trendDetail || trendLabel)}
      ${dimSignal('动强', momentum, momentumDetail || momentumLabel)}
      ${dimSignal('量价', volume, volumeDetail || volumeLabel)}
      ${dimSignal('位置', position, positionDetail || positionLabel)}
    </div>

    ${buyHTML}

    <div class="highlight ${concClass}">
      <span class="big-icon">${concEmoji}</span>
      <div>
        <div class="big-text">${conclusionLabel}</div>
        <div class="meta">${conclusionReason}</div>
      </div>
    </div>
  `;
}
