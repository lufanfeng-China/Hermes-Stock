const input = document.getElementById('ca-input');
const btn = document.getElementById('ca-btn');
const meta = document.getElementById('ca-meta');
const results = document.getElementById('ca-results');

const TREND_SIGNALS = {
  strong_bullish: '🟢', bullish: '🟢',
  recovering: '🟡', neutral: '⚪',
  weak_bearish: '🟠', bearish: '🔴', strong_bearish: '🔴',
};

function formatRank(rank, total) {
  if (rank == null) return '—';
  return `${rank}${total ? '/' + total : ''}`;
}

btn.addEventListener('click', search);
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });

async function search() {
  const q = input.value.trim();
  if (!q) return;
  btn.disabled = true;
  btn.textContent = '搜索中...';
  meta.textContent = '';
  results.innerHTML = '<div class="ca-meta">查询中...</div>';

  try {
    const resp = await fetch(`/api/concept-analysis?q=${encodeURIComponent(q)}`);
    const data = await resp.json();
    if (!data.ok) { results.innerHTML = `<div class="ca-meta">⚠️ ${data.error || '查询失败'}</div>`; return; }

    if (!data.concept_name) {
      meta.textContent = `未找到与"${q}"相关的概念`;
      results.innerHTML = '';
      return;
    }

    const tag = data.matched ? '' : ' (关键词匹配)';
    meta.innerHTML = `<strong>${data.concept_name}</strong>${tag} · 相关股票 <strong>${data.stocks.length}</strong> 只 · 匹配方式: ${data.method}`;

    if (!data.stocks.length) { results.innerHTML = ''; return; }

    const rows = data.stocks.map(s => {
      const trend = s.tech_trend;
      const light = TREND_SIGNALS[trend] || '';
      const matchPctClass = s.match_pct != null ? (s.match_pct >= 80 ? 'match-high' : s.match_pct >= 50 ? 'match-mid' : 'match-low') : '';
      const pctDisplay = s.match_pct != null ? `${s.match_pct}%` : '—';
      return `<tr>
        <td><strong>${escapeHtml(s.stock_name)}</strong><br><span class="ca-meta">${s.market.toUpperCase()}:${s.symbol}</span></td>
        <td class="num ${matchPctClass}">${pctDisplay}</td>
        <td class="num">${s.current_price != null ? s.current_price.toFixed(2) : '—'}</td>
        <td class="num">${s.pe_ttm != null ? s.pe_ttm.toFixed(1) : '—'}</td>
        <td>${light} ${escapeHtml(s.tech_trend_label || '—')}</td>
        <td class="num">${s.rps_20 != null ? s.rps_20.toFixed(0) : '—'}/${s.rps_50 != null ? s.rps_50.toFixed(0) : '—'}/${s.rps_120 != null ? s.rps_120.toFixed(0) : '—'}/${s.rps_250 != null ? s.rps_250.toFixed(0) : '—'}</td>
        <td class="num">${s.total_rps != null ? s.total_rps : '—'}</td>
        <td class="num">${formatRank(s.market_total_rank, 5517)}</td>
        <td>${escapeHtml(s.industry_display || '—')}</td>
        <td style="font-size:12px;max-width:320px">${escapeHtml(s.narrative || '—')}</td>
      </tr>`;
    }).join('');

    results.innerHTML = `<table class="ca-table">
      <thead><tr>
        <th>股票</th><th class="num">契合度</th><th class="num">现价</th><th class="num">PE</th><th>趋势</th>
        <th class="num">RPS(20/50/120/250)</th><th class="num">总RPS</th><th class="num">全市场排名</th><th>行业</th>
        <th>入选原因</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  } catch (e) {
    results.innerHTML = `<div class="ca-meta">⚠️ 请求失败: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '搜索';
  }
}

function escapeHtml(s) {
  return String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}
