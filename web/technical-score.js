// technical-score.js — Technical evaluation with smart search
// Shares recent-search storage with stock-score page

const $input = document.getElementById('search-input');
const $dropdown = document.getElementById('search-dropdown');
const $content = document.getElementById('content');

const MAX_RECENT = 10;
const STORAGE_KEY = 'stock-score-recent-searches'; // shared with stock-score page
let _recent = [];
let _focusedIdx = -1;

// ── Recent searches (shared with stock-score) ──

function loadRecent() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return (Array.isArray(arr) ? arr : [])
      .filter(r => r && r.market && r.symbol)
      .map(r => ({ market: String(r.market).toLowerCase(), symbol: String(r.symbol).trim(), stock_name: String(r.stock_name || r.symbol).trim() }))
      .slice(0, MAX_RECENT);
  } catch { return []; }
}

function saveRecent(stock) {
  if (!stock?.market || !stock?.symbol) return;
  const id = stock.market + ':' + stock.symbol;
  const next = [stock, ...loadRecent().filter(r => r.market + ':' + r.symbol !== id)].slice(0, MAX_RECENT);
  _recent = next;
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch {}
}

function showRecent() {
  _recent = loadRecent();
  _focusedIdx = -1;
  if (!_recent.length) {
    $dropdown.innerHTML = '<div class="search-option" style="color:var(--muted)">暂无最近查询</div>';
  } else {
    $dropdown.innerHTML = _recent.map((r, i) =>
      `<button class="search-option" data-idx="${i}" data-source="recent">
        <span class="name">${r.stock_name}</span>
        <span class="code">${r.market.toUpperCase()}:${r.symbol}</span>
      </button>`).join('');
  }
  $dropdown.classList.add('visible');
}

// ── Suggestions from API ──

let _suggestTimer = null;
async function showSuggestions(q) {
  if (!q || q.trim().length < 1) { showRecent(); return; }
  try {
    const r = await fetch(`/api/stock-search?q=${encodeURIComponent(q.trim())}&limit=10`);
    const d = await r.json();
    const items = d.ok ? (d.results || []) : [];
    _focusedIdx = -1;
    if (!items.length) {
      $dropdown.innerHTML = '<div class="search-option" style="color:var(--muted)">未找到匹配股票</div>';
    } else {
      $dropdown.innerHTML = items.map((s, i) =>
        `<button class="search-option" data-idx="${i}" data-source="suggest" data-market="${s.market}" data-symbol="${s.symbol}" data-name="${s.stock_name || ''}">
          <span class="name">${s.stock_name || s.symbol}</span>
          <span class="code">${s.market.toUpperCase()}:${s.symbol}</span>
        </button>`).join('');
    }
    $dropdown.classList.add('visible');
  } catch {
    $dropdown.innerHTML = '<div class="search-option" style="color:var(--red)">搜索失败</div>';
    $dropdown.classList.add('visible');
  }
}

// ── Query technical eval ──

async function query(market, symbol, name) {
  $dropdown.classList.remove('visible');
  $content.innerHTML = '<div class="card"><p class="loading">加载中...</p></div>';
  try {
    const r = await fetch(`/api/technical-eval?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`);
    const d = await r.json();
    if (!d.ok) { $content.innerHTML = `<div class="card"><p style="color:var(--red)">${d.error || '无数据'}</p></div>`; return; }
    d.stock_name = name || d.stock_name;
    d.market = market;
    render(d);
    saveRecent({ market, symbol, stock_name: name || d.stock_name || symbol });
    $input.value = `${name || d.stock_name} (${symbol})`;
  } catch (e) {
    $content.innerHTML = `<div class="card"><p style="color:var(--red)">错误: ${e.message}</p></div>`;
  }
}

// ── Resolve code or name ──

async function resolveAndQuery(raw) {
  raw = raw.trim();
  if (!raw) return;

  // Try parse as code
  let market = 'sh', symbol = raw;
  const m = raw.match(/^(sh|sz|bj)[:\s]*(\d{6})$/i);
  if (m) { market = m[1].toLowerCase(); symbol = m[2]; }
  else if (/^\d{6}$/.test(raw)) {
    if (raw.startsWith('6') || raw.startsWith('5') || raw.startsWith('9')) market = 'sh';
    else if (raw.startsWith('0') || raw.startsWith('3')) market = 'sz';
    else market = 'bj';
    await query(market, symbol, '');
    return;
  }

  // Name search
  try {
    const r = await fetch(`/api/stock-search?q=${encodeURIComponent(raw)}&limit=1`);
    const d = await r.json();
    if (d.ok && d.results?.length > 0) {
      const s = d.results[0];
      await query(s.market, s.symbol, s.stock_name);
    } else {
      $content.innerHTML = '<div class="card"><p style="color:var(--red)">未找到匹配股票</p></div>';
    }
  } catch (e) {
    $content.innerHTML = `<div class="card"><p style="color:var(--red)">搜索失败: ${e.message}</p></div>`;
  }
}

// ── Render tech eval ──

function render(d) {
  const name = d.stock_name || (d.market + ':' + d.symbol);
  const price = d.latest_close ? d.latest_close.toFixed(2) : '--';
  const code = (d.market || '').toUpperCase() + ':' + (d.symbol || '');
  const dataDate = d.data_date ? ` · 数据日期: ${d.data_date}` : '';

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
  const buyTrigger = d.buy_trigger;
  const buyLabel = d.buy_trigger_label;
  const buyDetail = d.buy_trigger_detail;
  const entryPrice = d.entry_price;
  const stopLoss = d.stop_loss;
  const riskPct = d.risk_pct;

  const emoji = {
    strong_bullish:'🟢',bullish:'🟢',recovering:'🟡',neutral:'🟡',bearish:'🔴',strong_bearish:'🔴',
    super_strong:'🟢',strong:'🟢',startup:'🟢',early_startup:'🟡',weak:'🔴',
    bullish:'🟢',normal:'🟡',low_volume:'🟡',divergence:'🔴',
    low:'🟢',mid:'🟡',high:'🔴',overheated:'🔴',new_stock:'⚪',
  };

  const dim = (label, val, detail) => `
    <div class="signal-row">
      <span class="signal-icon">${emoji[val]||'⚪'}</span>
      <span class="signal-label">${label}</span>
      <span class="signal-detail">${detail||''}</span>
    </div>`;

  let buyHTML = '';
  if (buyTrigger) {
    const isWatch = conclusion === 'buy_watch';
    buyHTML = `
    <div class="buy-card${isWatch?' watch':''}">
      <div style="font-weight:700;margin-bottom:6px">⚡ ${isWatch?'买点观察':'买入信号'}: ${buyLabel||buyTrigger}</div>
      ${buyDetail?`<div class="meta">${buyDetail}</div>`:''}
      ${entryPrice?`<div class="meta">买入参考价: <b>¥${entryPrice}</b></div>`:''}
      ${stopLoss?`<div class="meta">止损价: <b style="color:var(--red)">¥${stopLoss}</b></div>`:''}
      ${riskPct!=null?`<div class="meta">风险比例: <b>${(riskPct*100).toFixed(1)}%</b></div>`:''}
    </div>`;
  }

  const cc = conclusionColor==='green'?'highlight-green':
             conclusionColor==='red'?'highlight-red':'highlight-yellow';
  const ce = conclusionColor==='green'?'🟢':conclusionColor==='red'?'🔴':'🟡';

  $content.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div><span style="font-size:18px;font-weight:700">${name}</span>
          <span style="font-size:12px;color:var(--muted);margin-left:8px">${code}${dataDate}</span></div>
        <span style="font-size:20px;font-weight:700">¥${price}</span>
      </div>
    </div>
    <div class="card">
      <h3>📈 四维评估</h3>
      ${dim('趋势',trend,trendDetail||trendLabel)}
      ${dim('动强',momentum,momentumDetail||momentumLabel)}
      ${dim('量价',volume,volumeDetail||volumeLabel)}
      ${dim('位置',position,positionDetail||positionLabel)}
    </div>
    ${buyHTML}
    <div class="highlight ${cc}">
      <span class="big-icon">${ce}</span>
      <div><div class="big-text">${conclusionLabel}</div><div class="meta">${conclusionReason}</div></div>
    </div>`;
}

// ── Events ──

$input.addEventListener('focus', () => { if (!$input.value.trim()) showRecent(); });
$input.addEventListener('click', () => { if (!$input.value.trim()) showRecent(); });
$input.addEventListener('input', () => {
  clearTimeout(_suggestTimer);
  const q = $input.value.trim();
  if (!q) { showRecent(); return; }
  _suggestTimer = setTimeout(() => showSuggestions(q), 200);
});
$input.addEventListener('keydown', e => {
  const btns = $dropdown.querySelectorAll('.search-option');
  if (e.key === 'ArrowDown') { e.preventDefault(); _focusedIdx = Math.min(_focusedIdx+1, btns.length-1); updateFocus(btns); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); _focusedIdx = Math.max(_focusedIdx-1, -1); updateFocus(btns); }
  else if (e.key === 'Enter') {
    e.preventDefault();
    if (_focusedIdx >= 0 && btns[_focusedIdx]) { btns[_focusedIdx].click(); return; }
    resolveAndQuery($input.value);
  }
  else if (e.key === 'Escape') { $dropdown.classList.remove('visible'); _focusedIdx = -1; }
});

$dropdown.addEventListener('click', e => {
  const btn = e.target.closest('.search-option');
  if (!btn) return;
  const src = btn.dataset.source;
  if (src === 'recent') {
    const r = _recent[parseInt(btn.dataset.idx)];
    if (r) query(r.market, r.symbol, r.stock_name);
  } else if (src === 'suggest') {
    query(btn.dataset.market, btn.dataset.symbol, btn.dataset.name);
  }
});

document.addEventListener('click', e => {
  if (!e.target.closest('.search-wrap')) $dropdown.classList.remove('visible');
});

function updateFocus(btns) {
  btns.forEach((b, i) => b.classList.toggle('focused', i === _focusedIdx));
}
