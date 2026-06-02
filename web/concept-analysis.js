const input = document.getElementById('ca-input');
const btn = document.getElementById('ca-btn');
const meta = document.getElementById('ca-meta');
const results = document.getElementById('ca-results');

const TREND_SIGNALS = {
  strong_bullish: '\u{1F7E2}', bullish: '\u{1F7E2}',
  recovering: '\u{1F7E1}', neutral: '\u26AA',
  weak_bearish: '\u{1F7E0}', bearish: '\u{1F534}', strong_bearish: '\u{1F534}',
};

function formatRank(rank, total) {
  if (rank == null) return '\u2014';
  return `${rank}${total ? '/' + total : ''}`;
}

// Detect multi-concept input (comma-separated)
function isMultiConcept(q) { return q.includes(',') || q.includes('\uFF0C'); }

btn.addEventListener('click', search);
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });

async function search() {
  const q = input.value.trim();
  if (!q) return;
  btn.disabled = true;
  btn.textContent = '\u641C\u7D22\u4E2D...';
  meta.textContent = '';
  results.innerHTML = '<div class="ca-meta">\u67E5\u8BE2\u4E2D...</div>';

  const isCross = isMultiConcept(q);
  const endpoint = isCross ? '/api/concept-cross' : '/api/concept-analysis';

  try {
    const resp = await fetch(`${endpoint}?q=${encodeURIComponent(q)}`);
    const data = await resp.json();
    if (!data.ok) { results.innerHTML = `<div class="ca-meta">\u26A0\uFE0F ${data.error || '\u67E5\u8BE2\u5931\u8D25'}</div>`; return; }

    if (isCross && data.cross) {
      renderCross(data, q);
    } else if (!isCross && data.concept_name) {
      renderSingle(data);
    } else {
      meta.textContent = `\u672A\u627E\u5230\u4E0E"${q}"\u76F8\u5173\u7684\u6982\u5FF5`;
      results.innerHTML = '';
    }
  } catch (e) {
    results.innerHTML = `<div class="ca-meta">\u26A0\uFE0F \u8BF7\u6C42\u5931\u8D25: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '\u641C\u7D22';
  }
}

function renderSingle(data) {
  const tag = data.matched ? '' : ' (\u5173\u952E\u8BCD\u5339\u914D)';
  meta.innerHTML = `<strong>${data.concept_name}</strong>${tag} \xB7 \u76F8\u5173\u80A1\u7968 <strong>${data.stocks.length}</strong> \u53EA \xB7 \u5339\u914D\u65B9\u5F0F: ${data.method}`;
  if (!data.stocks.length) { results.innerHTML = ''; return; }
  results.innerHTML = buildTable(data.stocks, ['\u80A1\u7968', '\u5951\u5408\u5EA6', '\u73B0\u4EF7', 'PE', '\u8D8B\u52BF', 'RPS(20/50/120/250)', '\u603BRPS', '\u5168\u5E02\u573A\u6392\u540D', '\u884C\u4E1A', '\u5165\u9009\u539F\u56E0']);
}

function renderCross(data, q) {
  const conceptNames = (data.concepts || []).map(c => c.name).join(' + ');
  const counts = (data.concepts || []).map(c => `${c.name}(${c.member_count})`).join(' \u2229 ');
  meta.innerHTML = `<strong>${conceptNames}</strong><br>${counts} \u2192 \u4EA4\u96C6 <strong>${data.intersection_count}</strong> \u53EA`;
  if (!data.stocks.length) { results.innerHTML = '<div class="ca-meta">\u4EA4\u96C6\u4E3A\u7A7A\uFF0C\u6CA1\u6709\u540C\u65F6\u5C5E\u4E8E\u8FD9\u4E9B\u6982\u5FF5\u7684\u80A1\u7968</div>'; return; }

  // Add "hit concepts" column for cross mode
  const cols = ['\u80A1\u7968', '\u5951\u5408\u5EA6', '\u547D\u4E2D\u6982\u5FF5', '\u73B0\u4EF7', 'PE', '\u8D8B\u52BF', 'RPS(20/50/120/250)', '\u603BRPS', '\u5168\u5E02\u573A\u6392\u540D', '\u884C\u4E1A', '\u5165\u9009\u539F\u56E0'];
  const rows = data.stocks.map(s => {
    const trend = s.tech_trend;
    const light = TREND_SIGNALS[trend] || '';
    const matchPctClass = s.match_pct != null ? (s.match_pct >= 80 ? 'match-high' : s.match_pct >= 50 ? 'match-mid' : 'match-low') : '';
    const pctDisplay = s.match_pct != null ? `${s.match_pct}%` : '\u2014';
    const hitConcepts = (s.matched_concepts || []).join(', ');
    return `<tr>
      <td><strong>${escapeHtml(s.stock_name)}</strong><br><span class="ca-meta">${s.market.toUpperCase()}:${s.symbol}</span></td>
      <td class="num ${matchPctClass}">${pctDisplay}</td>
      <td style="font-size:12px">${escapeHtml(hitConcepts)}</td>
      <td class="num">${s.current_price != null ? s.current_price.toFixed(2) : '\u2014'}</td>
      <td class="num">${s.pe_ttm != null ? s.pe_ttm.toFixed(1) : '\u2014'}</td>
      <td>${light} ${escapeHtml(s.tech_trend_label || '\u2014')}</td>
      <td class="num">${s.rps_20 != null ? s.rps_20.toFixed(0) : '\u2014'}/${s.rps_50 != null ? s.rps_50.toFixed(0) : '\u2014'}/${s.rps_120 != null ? s.rps_120.toFixed(0) : '\u2014'}/${s.rps_250 != null ? s.rps_250.toFixed(0) : '\u2014'}</td>
      <td class="num">${s.total_rps != null ? s.total_rps : '\u2014'}</td>
      <td class="num">${formatRank(s.market_total_rank, 5517)}</td>
      <td>${escapeHtml(s.industry_display || '\u2014')}</td>
      <td style="font-size:12px;max-width:320px">${escapeHtml(s.narrative || '\u2014')}</td>
    </tr>`;
  }).join('');
  results.innerHTML = buildTableRaw(cols, rows);
}

function buildTable(stocks, cols) {
  const rows = stocks.map(s => {
    const trend = s.tech_trend;
    const light = TREND_SIGNALS[trend] || '';
    const matchPctClass = s.match_pct != null ? (s.match_pct >= 80 ? 'match-high' : s.match_pct >= 50 ? 'match-mid' : 'match-low') : '';
    const pctDisplay = s.match_pct != null ? `${s.match_pct}%` : '\u2014';
    return `<tr>
      <td><strong>${escapeHtml(s.stock_name)}</strong><br><span class="ca-meta">${s.market.toUpperCase()}:${s.symbol}</span></td>
      <td class="num ${matchPctClass}">${pctDisplay}</td>
      <td class="num">${s.current_price != null ? s.current_price.toFixed(2) : '\u2014'}</td>
      <td class="num">${s.pe_ttm != null ? s.pe_ttm.toFixed(1) : '\u2014'}</td>
      <td>${light} ${escapeHtml(s.tech_trend_label || '\u2014')}</td>
      <td class="num">${s.rps_20 != null ? s.rps_20.toFixed(0) : '\u2014'}/${s.rps_50 != null ? s.rps_50.toFixed(0) : '\u2014'}/${s.rps_120 != null ? s.rps_120.toFixed(0) : '\u2014'}/${s.rps_250 != null ? s.rps_250.toFixed(0) : '\u2014'}</td>
      <td class="num">${s.total_rps != null ? s.total_rps : '\u2014'}</td>
      <td class="num">${formatRank(s.market_total_rank, 5517)}</td>
      <td>${escapeHtml(s.industry_display || '\u2014')}</td>
      <td style="font-size:12px;max-width:320px">${escapeHtml(s.narrative || '\u2014')}</td>
    </tr>`;
  }).join('');

  return buildTableRaw(cols, rows);
}

function buildTableRaw(cols, rowsHtml) {
  const headerCells = cols.map(c => {
    const numClass = (c === '\u5951\u5408\u5EA6' || c === '\u73B0\u4EF7' || c === 'PE' || c === 'RPS(20/50/120/250)' || c === '\u603BRPS' || c === '\u5168\u5E02\u573A\u6392\u540D') ? ' class="num"' : '';
    return `<th${numClass}>${c}</th>`;
  }).join('');

  return `<table class="ca-table">
    <thead><tr>${headerCells}</tr></thead>
    <tbody>${rowsHtml}</tbody>
  </table>`;
}

function escapeHtml(s) {
  return String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}
