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

function tempLabelClass(label) {
  const s = String(label || '');
  if (s.includes('过热') || s.includes('高估')) return 'var(--red)';
  if (s.includes('偏热')) return '#ffc107';
  if (s.includes('偏冷') || s.includes('冰点')) return '#448aff';
  return 'var(--green)';
}

// ── Trend color ────────────────────────────────────────────────────────────

function trendColor(label) {
  const s = String(label || '');
  if (/多头|强势|放量|突破|建议关注/.test(s)) return 'var(--green)';
  if (/空头|弱势|缩量|回避|左侧/.test(s)) return 'var(--red)';
  if (/震荡|中性|观望|正常/.test(s)) return 'var(--muted)';
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
  const s = size != null ? `/${size}` : '';
  return `<span class="wl-rank">#${r}${s}</span>`;
}

function fmtTemp(stock) {
  const pct = stock.industry_temperature_percentile_since_2022;
  const label = stock.industry_temperature_label || '—';
  const emoji = tempEmoji(pct);
  const pctStr = pct != null ? ` ${Number(pct).toFixed(0)}%` : '';
  return `${emoji} ${esc(label)}${pctStr}`;
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

    return `<tr data-idx="${i}" data-market="${esc(s.market)}" data-symbol="${esc(s.symbol)}" data-name="${esc(name)}" tabindex="0">
      <td><span class="wl-stock-name">${esc(name)}</span><span class="wl-stock-symbol">${esc(marketSymbol)}</span></td>
      <td class="num"><span class="wl-score">${ms}</span> ${mr}</td>
      <td class="num"><span class="wl-score">${is_}</span> ${ir}</td>
      <td>${esc(ind)}</td>
      <td>${temp}</td>
      <td style="color:${trendColor(trend)}">${esc(trend)}</td>
      <td style="color:${trendColor(momentum)}">${esc(momentum)}</td>
      <td style="color:${trendColor(volume)}">${esc(volume)}</td>
      <td>${buyTrigger}</td>
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
  container.innerHTML = '<div class="wl-loading">加载K线数据...</div>';
  dialog.showModal();

  try {
    const querySymbol = `${market}:${symbol}`;
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

    container.innerHTML = '';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 800 500');
    svg.style.width = '100%';
    svg.style.height = 'auto';
    svg.style.minHeight = '400px';
    container.appendChild(svg);

    if (!klineChart) {
      klineChart = new KlineChart(svg, { marginRight: 20 });
    } else {
      klineChart.svg = svg;
    }
    klineChart.load(bars, rpsHistory, 250);

  } catch (err) {
    container.innerHTML = `<p style="color:var(--red);padding:20px">K线加载失败: ${esc(err.message)}</p>`;
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

loadWatchlist();
