// technical-score.js — Technical evaluation page
// Reads from /api/stock-screener with tech fields

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

  // Determine market from code
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
    // Try name search
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
    const url = `/api/stock-screener?page_size=500&page=1`;
    const r = await fetch(url);
    const d = await r.json();
    if (!d.ok || !d.rows?.length) {
      $status.textContent = '无数据';
      return;
    }
    // Find exact match
    const row = d.rows.find(r => 
      r.market === market && r.symbol === symbol
    );
    if (!row) {
      // Try loading more pages or fall back
      $status.textContent = '未找到该股票';
      return;
    }
    render(row);
    $status.textContent = '';
  } catch (e) {
    $status.textContent = '错误: ' + e.message;
    $status.className = 'red';
  }
}

function render(row) {
  const name = row.stock_name || (row.market + ':' + row.symbol);
  const price = row.current_price?.toFixed(2) || '--';
  const code = (row.market || '').toUpperCase() + ':' + (row.symbol || '');

  // Tech fields
  const trend = row.tech_trend || '--';
  const trendLabel = row.tech_trend_label || '--';
  const momentum = row.tech_momentum || '--';
  const momentumLabel = row.tech_momentum_label || '--';
  const volume = row.tech_volume_signal || '--';
  const volumeLabel = row.tech_volume_label || '--';
  const position = row.tech_position || '--';
  const positionLabel = row.tech_position_label || '--';
  const conclusion = row.tech_conclusion || 'hold_watch';
  const conclusionLabel = row.tech_conclusion_label || '--';
  const conclusionColor = row.tech_conclusion_color || 'yellow';
  const conclusionReason = row.tech_conclusion_reason || '';
  const buyTrigger = row.tech_buy_trigger;
  const buyLabel = row.tech_buy_trigger_label;
  const entryPrice = row.tech_entry_price;
  const stopLoss = row.tech_stop_loss;
  const riskPct = row.tech_risk_pct;

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
    const isWatch = row.tech_conclusion === 'buy_watch';
    buyHTML = `
    <div class="buy-card${isWatch ? ' watch' : ''}">
      <div style="font-weight:700;margin-bottom:6px">⚡ ${isWatch ? '买点观察' : '买入信号'}: ${buyLabel || buyTrigger}</div>
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
      ${dimSignal('趋势', trend, row.tech_trend_detail || trendLabel)}
      ${dimSignal('动强', momentum, row.tech_momentum_detail || momentumLabel)}
      ${dimSignal('量价', volume, row.tech_volume_detail || volumeLabel)}
      ${dimSignal('位置', position, row.tech_position_detail || positionLabel)}
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
