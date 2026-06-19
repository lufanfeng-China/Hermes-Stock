// watchlist.js — Watchlist table with K-line popup
import { KlineChart } from './kline-chart.js?v=20260604-ma';

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
    const ind = s.industry_level_2 || '—';

    const trend = s.tech_trend_label || '—';
    const shortTrend = s.tech_short_trend_label || '—';
    const shortTrendSwitch = (() => {
      const cur = s.tech_short_trend || '';
      const prev = s.tech_short_trend_prev || '';
      if (!cur) return '—';
      if (!prev) return '—';
      if (cur !== prev) {
        const bullish = ['strong_bullish','bullish','recovering'];
        if (bullish.includes(cur) && !bullish.includes(prev)) return '🟢 转多';
        if (!bullish.includes(cur) && bullish.includes(prev)) return '🔴 转空';
        return '↔ 切换';
      }
      return '—';
    })();
    const buyTrigger = s.tech_buy_trigger_label ? '✅ ' + esc(s.tech_buy_trigger_label) : '❌ 未触发';
    const conclusion = s.tech_conclusion_label || '—';
    const concColor = s.tech_conclusion_color || trendColor(conclusion);

    const status = s.status || '—';
    const statusIcon = status === '结束' ? '🔴' : status === '持有' ? '🟢' : '';
    const finalRet = s.final_return_pct != null ? fmtPct(s.final_return_pct) : (status === '持有' && s.return_since_add_pct != null ? fmtPct(s.return_since_add_pct) : '—');
    const finalRetColor = s.final_return_pct != null ? pctColor(s.final_return_pct) : (status === '持有' && s.return_since_add_pct != null ? pctColor(s.return_since_add_pct) : 'var(--muted)');

    const price = s.current_price != null ? Number(s.current_price).toFixed(2) : '—';
    const ma10d = s.ma10_dist_pct != null ? (s.ma10_dist_pct>=0?'+':'')+s.ma10_dist_pct.toFixed(1)+'%' : '—';
    const ma10c = s.ma10_dist_pct != null ? pctColor(s.ma10_dist_pct) : 'var(--muted)';
    const ma30s = s.ma30_slope_pct != null ? (s.ma30_slope_pct>=0?'+':'')+s.ma30_slope_pct.toFixed(2)+'%' : '—';
    const ma30sc = s.ma30_slope_pct != null ? pctColor(s.ma30_slope_pct) : 'var(--muted)';
    const ret = s.return_since_add_pct != null ? fmtPct(s.return_since_add_pct) : '—';
    const retColor = s.return_since_add_pct != null ? pctColor(s.return_since_add_pct) : 'var(--muted)';
    const maxRet = s.max_return_pct != null ? fmtPct(s.max_return_pct) : "—";
    const maxRetColor = s.max_return_pct != null ? pctColor(s.max_return_pct) : "var(--muted)";
    const maxLoss = s.max_loss_pct != null ? fmtPct(s.max_loss_pct) : "—";
    const maxLossColor = s.max_loss_pct != null ? pctColor(s.max_loss_pct) : "var(--muted)";
    const addedDate = (s.added_at || "").slice(0, 10) || "—";

    return `<tr data-idx=\"${i}\" data-market=\"${esc(s.market)}\" data-symbol=\"${esc(s.symbol)}\" data-name=\"${esc(name)}\" tabindex=\"0\">
      <td><input type=\"checkbox\" class=\"wl-row-check\" data-idx=\"${i}\"></td>
      <td class=\"wl-name-cell\"><span class=\"wl-stock-name\">${esc(name)}</span><br><span class=\"wl-stock-symbol\">${esc(marketSymbol)}</span></td>
      <td class=\"num wl-price-cell\" title=\"点击查看K线\">${price}</td>
      <td class=\"num\" style=\"color:${ma10c}\">${ma10d}</td>
      <td class=\"num\" style=\"color:${ma30sc}\">${ma30s}</td>
      <td class=\"num\" style=\"color:${retColor}\">${ret}</td>
      <td class=\"num\" style=\"color:${maxRetColor}\">${maxRet}</td>
      <td class=\"num\" style=\"color:${maxLossColor}\">${maxLoss}</td>
      <td>${addedDate}</td>
      <td>${esc(ind)}</td>
      <td style=\"color:${trendColor(trend)}\">${esc(trend)}</td>
      <td style=\"color:${trendColor(shortTrend)}\">${esc(shortTrend)}${shortTrendSwitch !== '—' ? ' ' + shortTrendSwitch : ''}</td>
      <td>${statusIcon} ${esc(status)}</td>
      <td class=\"num\" style=\"color:${finalRetColor}\">${finalRet}</td>
      <td style=\"color:${concColor};font-weight:600\" title=\"${esc(s.tech_conclusion_reason || '')}\">${esc(conclusion)}</td>
      <td><button class=\"wl-remove-btn\" data-idx=\"${i}\" type=\"button\">✕</button></td>
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

  // Name cell click → navigate to stock-score page with auto-load
  document.querySelectorAll('.wl-name-cell').forEach(cell => {
    cell.addEventListener('click', (e) => {
      e.stopPropagation();
      const row = cell.closest('tr');
      if (!row) return;
      const market = row.dataset.market;
      const symbol = row.dataset.symbol;
      const name = row.dataset.name;
      const params = new URLSearchParams({ market, symbol, name });
      window.location.href = `/stock-score.html?${params.toString()}`;
    });
  });

  // Price cell click → open K-line dialog
  document.querySelectorAll('.wl-price-cell').forEach(cell => {
    cell.addEventListener('click', (e) => {
      e.stopPropagation();
      const row = cell.closest('tr');
      if (!row) return;
      openKline(row.dataset.market, row.dataset.symbol, row.dataset.name);
    });
  });
}

// ── Overall Return ───────────────────────────────────────────────────────────

function renderOverall(overall_pct, count) {
  const el = document.getElementById('wl-overall');
  if (!el) return;
  if (overall_pct == null || count === 0) {
    el.style.display = 'none';
    return;
  }
  const sign = overall_pct >= 0 ? '+' : '';
  const color = overall_pct >= 0 ? 'var(--profit,#4ecca3)' : 'var(--loss,#ff6b6b)';
  const icon = overall_pct >= 0 ? '📈' : '📉';
  el.style.display = 'inline-block';
  el.innerHTML = `${icon} 组合总体收益 (${count}只, 等权): <strong style=\"color:${color};font-size:14px\">${sign}${overall_pct.toFixed(1)}%</strong>`;
}

function renderOverallFinal(final_pct, count) {
  const el = document.getElementById('wl-final-overall');
  if (!el) return;
  if (final_pct == null || count === 0) {
    el.style.display = 'none';
    return;
  }
  const sign = final_pct >= 0 ? '+' : '';
  const color = final_pct >= 0 ? 'var(--profit,#4ecca3)' : 'var(--loss,#ff6b6b)';
  const icon = '🏁';
  el.style.display = 'inline-block';
  el.style.marginLeft = '16px';
  el.innerHTML = `${icon} 组合最终收益 (${count}只): <strong style=\"color:${color};font-size:14px\">${sign}${final_pct.toFixed(1)}%</strong>`;
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
      renderOverall(data.overall_return_pct, watchlistData.length);
      // 组合最终收益：结束=MA20跌破价收益，持有=当前收益
      const finalReturns = watchlistData.map(s => {
        if (s.final_return_pct != null) return s.final_return_pct;
        if (s.status === '持有' && s.return_since_add_pct != null) return s.return_since_add_pct;
        return null;
      }).filter(v => v != null);
      const finalOverall = finalReturns.length > 0 ? finalReturns.reduce((a,b)=>a+b,0)/finalReturns.length : null;
      renderOverallFinal(finalOverall, finalReturns.length);
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

// Select all / deselect all
document.getElementById('wl-select-all')?.addEventListener('change', function() {
  document.querySelectorAll('.wl-row-check').forEach(cb => { cb.checked = this.checked; });
});

document.getElementById('wl-sync-tdx-btn')?.addEventListener('click', async () => {
  const checks = document.querySelectorAll('.wl-row-check:checked');
  if (!checks.length) return;
  const stocks = [];
  checks.forEach(cb => {
    const idx = Number(cb.dataset.idx);
    const s = watchlistData[idx];
    if (s) stocks.push({ market: s.market, symbol: s.symbol });
  });
  const btn = document.getElementById('wl-sync-tdx-btn');
  btn.textContent = `同步中(${stocks.length})...`;
  btn.disabled = true;
  try {
    const res = await fetch('/api/sync-to-tdx-block', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stocks }),
    });
    const data = await res.json();
    btn.textContent = data.ok ? `已同步 ${data.written} 只` : '同步失败';
  } catch (e) {
    btn.textContent = '同步失败';
  }
  setTimeout(() => { btn.textContent = '同步到AI股池'; btn.disabled = false; }, 2000);
});

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
