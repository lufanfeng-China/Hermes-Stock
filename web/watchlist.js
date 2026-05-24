// watchlist.js — Watchlist table with K-line popup
import { KlineChart } from './kline-chart.js?v=20260513-ma';

let watchlistData = [];

// ── Temperature helpers ────────────────────────────────────────────────────

function tempEmoji(percentile) {
  if (percentile == null || percentile === '') return '—';
  const p = Number(percentile);
  if (p >= 80) return '🔴';
  if (p >= 60) return '🟡';
  if (p >= 40) return '🟢';
  if (p >= 20) return '🔵';
  return '⚪';
}

// ── Trend color ────────────────────────────────────────────────────────────

function trendColor(label) {
  const s = String(label || '');
  if (/多头|强多|极强|强势|放量|突破|买点|买入|确认|建议关注/.test(s)) return 'var(--accent)';
  if (/空头|强空|极弱|弱势|缩量|回避/.test(s)) return 'var(--danger)';
  if (/震荡|中性|观望|正常|修复|左侧/.test(s)) return 'var(--muted)';
  return 'var(--text)';
}

// ── Format ──────────────────────────────────────────────────────────────────

function esc(s) { return String(s ?? '').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

function fmtScore(v) {
  if (v == null) return '—';
  return Number(v).toFixed(1);
}

function fmtRank(rank, size) {
  if (rank == null) return '';
  const r = Number(rank);
  return `<span class="wl-rank">#${r}</span>`;
}

function fmtTemp(stock) {
  const pct = stock.industry_temperature_percentile_since_2022;
  const label = stock.industry_temperature_label || '—';
  const emoji = tempEmoji(pct);
  const pctStr = pct != null ? `${Number(pct).toFixed(0)}%` : '—';
  return `${emoji} ${pctStr}`;
}

function fmtPct(v) {
  if (v == null) return '—';
  const n = Number(v);
  return (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
}

function pctColor(v) {
  if (v == null) return 'var(--muted)';
  return Number(v) >= 0 ? 'var(--accent)' : 'var(--danger)';
}

// ── Render ──────────────────────────────────────────────────────────────────

function renderTable(stocks) {
  const tbody = document.querySelector('#watchlist-table tbody');
  if (!tbody) return;

  tbody.innerHTML = stocks.map((s, i) => {
    const name = s.stock_name || s.symbol;
    const marketSymbol = `${String(s.market || '').toUpperCase()}:${s.symbol}`;
    const ms = fmtScore(s.market_total_score);
    const mr = fmtRank(s.market_total_rank, s.market_total_universe_size);
    const is_ = fmtScore(s.industry_total_score);
    const ir = fmtRank(s.industry_total_rank, s.industry_total_universe_size);
    const ind = [s.industry_level_1, s.industry_level_2].filter(Boolean).join(' / ') || '—';
    const temp = fmtTemp(s);

    const trend = s.tech_trend_label || '—';
    const momentum = s.tech_momentum_label || '—';
    const volume = s.tech_volume_label || '—';
    const buyTrigger = s.tech_buy_trigger_label ? '✅ ' + esc(s.tech_buy_trigger_label) : '❌ 未触发';
    const conclusion = s.tech_conclusion_label || '—';
    const concColor = s.tech_conclusion_color || trendColor(conclusion);

    const price = s.current_price != null ? Number(s.current_price).toFixed(2) : '—';
    const r5 = fmtPct(s.return_5_pct);
    const r20 = fmtPct(s.return_20_pct);
    const dur = s.trend_duration != null ? String(s.trend_duration) + '天' : '—';

    return `<tr data-idx="${i}" data-market="${esc(s.market)}" data-symbol="${esc(s.symbol)}" data-name="${esc(name)}" tabindex="0">
      <td><span class="wl-stock-name">${esc(name)}</span><br><span class="wl-stock-symbol">${esc(marketSymbol)}</span></td>
      <td class="num">${price}</td>
      <td class="num"><span class="wl-score">${ms}</span> ${mr}</td>
      <td class="num"><span class="wl-score">${is_}</span> ${ir}</td>
      <td>${esc(ind)}</td>
      <td>${temp}</td>
      <td style="color:${trendColor(trend)}">${esc(trend)}</td>
      <td style="color:${trendColor(momentum)}">${esc(momentum)}</td>
      <td style="color:${trendColor(volume)}">${esc(volume)}</td>
      <td>${buyTrigger}</td>
      <td class="num" style="color:${pctColor(s.return_5_pct)}">${r5}</td>
      <td class="num" style="color:${pctColor(s.return_20_pct)}">${r20}</td>
      <td class="num">${dur}</td>
      <td style="color:${concColor};font-weight:600" title="${esc(s.tech_conclusion_reason || '')}">${esc(conclusion)}</td>
      <td><button class="wl-remove-btn" data-idx="${i}" type="button">✕</button></td>
    </tr>`;
  }).join('');

  // Count
  const countEl = document.getElementById('wl-count');
  if (countEl) {
    countEl.textContent = String(stocks.length);
    countEl.style.display = 'inline-block';
  }

  // Bind events
  bindRowEvents();
}

function bindRowEvents() {
  // Remove buttons
  document.querySelectorAll('.wl-remove-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.idx);
      const stock = watchlistData[idx];
      if (!stock) return;
      try {
        const resp = await fetch('/api/watchlist/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ market: stock.market, symbol: stock.symbol }),
        });
        const body = await resp.json();
        if (body.ok) {
          loadWatchlist();
        }
      } catch (err) {
        console.error('Remove failed:', err);
      }
    });
  });

  // Row click → K-line
  document.querySelectorAll('#watchlist-table tbody tr').forEach(row => {
    row.addEventListener('click', () => {
      openKline(row.dataset.market, row.dataset.symbol, row.dataset.name);
    });
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openKline(row.dataset.market, row.dataset.symbol, row.dataset.name);
      }
    });
  });
}

// ── API ─────────────────────────────────────────────────────────────────────

async function loadWatchlist() {
  const loading = document.getElementById('wl-loading');
  const empty = document.getElementById('wl-empty');
  const content = document.getElementById('wl-content');

  loading.style.display = 'block';
  empty.style.display = 'none';
  content.style.display = 'none';

  try {
    const resp = await fetch('/api/watchlist');
    const data = await resp.json();
    watchlistData = data.stocks || [];

    loading.style.display = 'none';

    if (watchlistData.length === 0) {
      empty.style.display = 'block';
    } else {
      content.style.display = 'block';
      renderTable(watchlistData);
    }
  } catch (err) {
    loading.style.display = 'none';
    console.error('Watchlist load failed:', err);
    const statusEl = document.getElementById('wl-status');
    if (statusEl) statusEl.textContent = '加载失败: ' + err.message;
  }
}

// ── K-line Dialog ───────────────────────────────────────────────────────────

let klineChart = null;

async function openKline(market, symbol, name) {
  const dialog = document.getElementById('kline-dialog');
  const title = document.getElementById('kline-dialog-title');
  const container = document.getElementById('kline-container');

  if (!dialog || !container) return;

  title.textContent = `${name || symbol} (${String(market).toUpperCase()}:${symbol})`;
  dialog.showModal();

  try {
    const [klineResp, rpsResp] = await Promise.all([
      fetch(`/api/stock-kline?symbol=${encodeURIComponent(symbol)}&limit=250`),
      fetch(`/api/stock-rps-history?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`),
    ]);
    const klineData = await klineResp.json();
    if (!klineData.ok) throw new Error(klineData.error?.message || 'K-line load failed');

    const rpsData = await rpsResp.json();
    const bars = klineData.bars || [];
    const rpsHistory = (rpsData.ok && rpsData.history) ? rpsData.history.map(h => ({
      trading_day: h.trading_day,
      rps_20: h.rps_20,
      rps_50: h.rps_50,
      rps_120: h.rps_120,
      rps_250: h.rps_250,
    })) : [];

    // Use pre-existing SVG — KlineChart manages its own child groups
    const svg = document.getElementById('kline-chart-svg-wl');
    if (!svg) return;
    // Do NOT clear SVG children — KlineChart.render() clears sub-groups internally

    if (!klineChart) {
      klineChart = new KlineChart(svg, { marginRight: 20 });
    } else {
      klineChart.svg = svg;
    }
    klineChart.load(bars, rpsHistory, 250);

  } catch (err) {
    console.error('Kline load error:', err);
  }
}

// ── Init ────────────────────────────────────────────────────────────────────

document.getElementById('kline-dialog-close')?.addEventListener('click', () => {
  document.getElementById('kline-dialog').close();
});

document.getElementById('kline-dialog')?.addEventListener('click', (e) => {
  if (e.target === e.currentTarget) {
    e.currentTarget.close();
  }
});

document.getElementById('wl-refresh-btn')?.addEventListener('click', loadWatchlist);

document.getElementById('wl-clear-btn')?.addEventListener('click', async () => {
  if (!confirm('确定清空全部自选股？')) return;
  const btn = document.getElementById('wl-clear-btn');
  btn.disabled = true;
  btn.textContent = '清空中...';
  try {
    await fetch('/api/watchlist/clear', { method: 'POST' });
    loadWatchlist();
  } catch (e) {
    alert('清空失败: ' + e.message);
    btn.disabled = false;
    btn.textContent = '清空全部';
  }
});

loadWatchlist();
