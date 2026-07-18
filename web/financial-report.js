// Financial Report Analysis — 金融终端风
const periodSelect = document.getElementById('fr-period');
const loadingEl = document.getElementById('fr-loading');
const forecastTbody = document.querySelector('#fr-forecast-table tbody');
const upcomingTbody = document.querySelector('#fr-upcoming-table tbody');
const publishedTbody = document.getElementById('fr-published-tbody');

let currentPeriod = '';
let currentSort = 'deducted_roe';
let currentOrder = 'desc';
let currentPage = 1;
let totalPages = 1;
let totalRows = 0;
const PAGE_SIZE = 100;
let fcastPage = 1;
let fcastTotalPages = 1;
const FCAST_PAGE_SIZE = 50;
let fcastSort = 'forecast_date';
let fcastOrder = 'desc';
let fcastGrowthMin = '';
let fcastProfitMin = '';
let fcastDateFrom = '';

async function loadPeriods() {
  try {
    const resp = await fetch('/api/financial-periods');
    const data = await resp.json();
    if (!data.ok || !data.periods) return;
    periodSelect.innerHTML = data.periods.map(p => `<option value="${p}">${p}</option>`).join('');
    if (data.periods.length > 0) {
      periodSelect.value = data.periods[0];
      currentPeriod = data.periods[0];
      loadAll();
    }
  } catch (e) {
    periodSelect.innerHTML = '<option>加载失败</option>';
  }
}

periodSelect.addEventListener('change', () => {
  currentPeriod = periodSelect.value;
  currentPage = 1;
  loadAll();
});

// ── Forecast (业绩预告) ──
async function loadForecast() {
  try {
    const params = new URLSearchParams({
      page: fcastPage, page_size: FCAST_PAGE_SIZE,
      sort: fcastSort, order: fcastOrder
    });
    if (fcastGrowthMin) params.set('growth_min', fcastGrowthMin);
    if (fcastProfitMin) params.set('profit_min', fcastProfitMin);
    if (fcastDateFrom) params.set('date_from', fcastDateFrom);
    const resp = await fetch(`/api/financial-forecast?${params}`);
    const data = await resp.json();
    if (!data.ok || !data.rows.length) {
      forecastTbody.innerHTML = '<tr><td colspan="8" class="fr-status">暂无业绩预告</td></tr>';
      updateFcastPagination(0, 1, 1);
      return;
    }
    fcastTotalPages = data.total_pages || 1;
    updateFcastPagination(data.total || 0, data.page || 1, fcastTotalPages);
    forecastTbody.innerHTML = data.rows.map(r => {
      const growth = (r.profit_growth_lo != null && r.profit_growth_hi != null)
        ? `${r.profit_growth_lo >= 0 ? '+' : ''}${r.profit_growth_lo.toFixed(1)}% ~ ${r.profit_growth_hi >= 0 ? '+' : ''}${r.profit_growth_hi.toFixed(1)}%`
        : '—';
      const profit = fmtRangeWan(r.net_profit_lo, r.net_profit_hi);
      const price = r.current_price != null ? r.current_price.toFixed(2) : '—';
      const industry = esc(r.industry_l2 || '—');
      const nicheBadge = r.niche_leader
        ? ` <span style="font-size:10px;background:#2a4a3a;color:#4ade80;padding:1px 5px;border-radius:3px;" title="细分龙头: ${esc(r.niche_leader)}">🏆${esc(r.niche_leader)}</span>`
        : '';
      const ret3d = r.return_3d != null
        ? `<span class="${r.return_3d > 0 ? 'fr-up' : r.return_3d < 0 ? 'fr-down' : ''}">${r.return_3d > 0 ? '+' : ''}${r.return_3d.toFixed(2)}%</span>`
        : '—';
      const cls = (r.profit_growth_lo != null && r.profit_growth_lo > 50) ? 'fr-up'
        : (r.profit_growth_lo != null && r.profit_growth_lo < 0) ? 'fr-down' : '';
      return `<tr>
        <td class="name symbol" data-symbol="${r.symbol}">${esc(r.stock_name)}${nicheBadge}</td>
        <td class="num">${price}</td>
        <td class="name" style="font-size:11px;color:var(--fr-muted);">${industry}</td>
        <td class="date">${r.forecast_date}</td>
        <td class="num ${cls}">${growth}</td>
        <td class="num">${pePctHtml(r.pe_pct)}</td>
        <td class="num">${profit}</td>
        <td class="num">${ret3d}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    forecastTbody.innerHTML = '<tr><td colspan="8" class="fr-status">加载失败</td></tr>';
    updateFcastPagination(0, 1, 1);
  }
}

// ── Upcoming ──
async function loadUpcoming() {
  try {
    const resp = await fetch(`/api/financial-upcoming?period=${encodeURIComponent(currentPeriod)}`);
    const data = await resp.json();
    if (!data.ok) { upcomingTbody.innerHTML = '<tr><td colspan="2" class="fr-status">加载失败</td></tr>'; return; }
    if (!data.rows.length) {
      upcomingTbody.innerHTML = '<tr><td colspan="2" class="fr-status">暂无即将公布的财报</td></tr>';
      return;
    }
    upcomingTbody.innerHTML = data.rows.map(r =>
      `<tr><td class="name symbol" data-symbol="${r.symbol}">${esc(r.stock_name)}</td><td class="date">${r.announce_date}</td></tr>`
    ).join('');
  } catch (e) {
    upcomingTbody.innerHTML = '<tr><td colspan="2" class="fr-status">加载失败</td></tr>';
  }
}

let computing = false;

// ── Compute return button ──
document.getElementById('fr-compute-return').addEventListener('click', async () => {
  if (computing) return;
  computing = true;
  const btn = document.getElementById('fr-compute-return');
  btn.textContent = '计算中...';
  btn.disabled = true;
  try {
    currentPage = 1; // 计算后回到第一页
    const resp = await fetch(
      `/api/financial-published?period=${encodeURIComponent(currentPeriod)}&sort=${currentSort}&order=${currentOrder}&compute_return=1&page=${currentPage}&page_size=${PAGE_SIZE}`
    );
    const data = await resp.json();
    if (data.ok) {
      totalRows = data.total || data.rows.length;
      totalPages = data.total_pages || 1;
      updatePagination(totalRows, data.page || 1, totalPages);
      renderPublished(data);
    }
  } catch (e) {}
  btn.textContent = '计算收益率';
  btn.disabled = false;
  computing = false;
});

// ── Published ──
async function loadPublished() {
  publishedTbody.innerHTML = '<tr><td colspan="10" class="fr-status">加载中...</td></tr>';
  try {
    const resp = await fetch(
      `/api/financial-published?period=${encodeURIComponent(currentPeriod)}&sort=${currentSort}&order=${currentOrder}&page=${currentPage}&page_size=${PAGE_SIZE}`
    );
    const data = await resp.json();
    if (!data.ok) { publishedTbody.innerHTML = '<tr><td colspan="10" class="fr-status">加载失败</td></tr>'; updatePagination(0, 1, 1); return; }
    if (!data.rows.length) {
      publishedTbody.innerHTML = '<tr><td colspan="10" class="fr-status">暂无数据</td></tr>';
      updatePagination(0, 1, 1);
      return;
    }
    totalRows = data.total || data.rows.length;
    totalPages = data.total_pages || 1;
    updatePagination(totalRows, data.page || 1, totalPages);
    renderPublished(data);
  } catch (e) {
    publishedTbody.innerHTML = '<tr><td colspan="10" class="fr-status">加载失败</td></tr>';
    updatePagination(0, 1, 1);
  }
}

function renderPublished(data) {
  publishedTbody.innerHTML = data.rows.map(r => {
      return `<tr>
        <td class="name symbol" data-symbol="${r.symbol}">${esc(r.stock_name)}</td>
        <td class="date">${r.announce_date || '—'}</td>
        <td class="num">${fmt(r.deducted_roe, 2)}</td>
        <td class="delta">${deltaHtml(r.deducted_roe, r.deducted_roe_prev, 2)}</td>
        <td class="num">${fmt(r.net_profit, 2)}</td>
        <td class="delta">${deltaHtml(r.net_profit, r.net_profit_prev, 2)}</td>
        <td class="num">${pePctHtml(r.pe_pct)}</td>
        <td class="num">${fmt(r.deducted_np_yoy, 2)}</td>
        <td class="delta">${deltaHtml(r.deducted_np_yoy, r.deducted_np_yoy_prev, 2)}</td>
        <td class="num">${retHtml(r.return_pct)}</td>
      </tr>`;
    }).join('');
}

// ── Helpers ──
function esc(s) { return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmt(v, d) { return v != null ? v.toFixed(d) : '—'; }

function deltaHtml(cur, prev, d) {
  if (cur == null || prev == null) return '—';
  const diff = cur - prev;
  if (Math.abs(diff) < 0.001) return '<span class="fr-down">0</span>';
  const cls = diff > 0 ? 'fr-up' : 'fr-down';
  return `<span class="${cls}">${diff > 0 ? '+' : ''}${diff.toFixed(d)}</span>`;
}

function retHtml(v) {
  if (v == null) return '—';
  const cls = v > 0 ? 'fr-up' : v < 0 ? 'fr-down' : '';
  return `<span class="${cls}">${v > 0 ? '+' : ''}${v.toFixed(2)}%</span>`;
}

function pePctHtml(v) {
  if (v == null) return '—';
  // 分位越低(低估)越绿, 分位越高(高估)越红
  const cls = v <= 30 ? 'fr-down' : v >= 70 ? 'fr-up' : '';
  return `<span class="${cls}">${v.toFixed(1)}%</span>`;
}

function fmtRangeWan(lo, hi) {
  if (lo == null || hi == null) return '—';
  const avg = (lo + hi) / 2;
  if (Math.abs(avg) >= 10000) return `${(avg / 10000).toFixed(1)}亿`;
  if (Math.abs(avg) >= 1) return `${avg.toFixed(0)}万`;
  return `${avg.toFixed(0)}万`;
}

function updatePagination(total, page, pages) {
  document.getElementById('fr-page-info').textContent =
    `第 ${page} 页 / 共 ${pages} 页 (共 ${total} 条)`;
  document.getElementById('fr-prev-btn').disabled = page <= 1;
  document.getElementById('fr-next-btn').disabled = page >= pages;
}

// ── Pagination controls ──
document.getElementById('fr-prev-btn').addEventListener('click', () => {
  if (currentPage > 1) { currentPage--; loadPublished(); }
});
document.getElementById('fr-next-btn').addEventListener('click', () => {
  if (currentPage < totalPages) { currentPage++; loadPublished(); }
});

function updateFcastPagination(total, page, pages) {
  document.getElementById('fr-fcast-page-info').textContent =
    `第 ${page} 页 / 共 ${pages} 页 (共 ${total} 条)`;
  document.getElementById('fr-fcast-prev-btn').disabled = page <= 1;
  document.getElementById('fr-fcast-next-btn').disabled = page >= pages;
}

document.getElementById('fr-fcast-prev-btn').addEventListener('click', () => {
  if (fcastPage > 1) { fcastPage--; loadForecast(); }
});
document.getElementById('fr-fcast-next-btn').addEventListener('click', () => {
  if (fcastPage < fcastTotalPages) { fcastPage++; loadForecast(); }
});

// ── Forecast filter ──
document.getElementById('fr-fcast-filter-btn').addEventListener('click', () => {
  fcastGrowthMin = document.getElementById('fr-fcast-growth-min').value.trim();
  fcastProfitMin = document.getElementById('fr-fcast-profit-min').value.trim();
  fcastDateFrom = document.getElementById('fr-fcast-date-from').value.trim();
  fcastPage = 1;
  loadForecast();
});
document.getElementById('fr-fcast-clear-btn').addEventListener('click', () => {
  document.getElementById('fr-fcast-growth-min').value = '';
  document.getElementById('fr-fcast-profit-min').value = '';
  document.getElementById('fr-fcast-date-from').value = '';
  fcastGrowthMin = '';
  fcastProfitMin = '';
  fcastDateFrom = '';
  fcastPage = 1;
  loadForecast();
});

// ── Forecast sort ──
document.querySelector('#fr-forecast-table thead').addEventListener('click', (e) => {
  const th = e.target.closest('th[data-sort]');
  if (!th) return;
  const sortField = th.dataset.sort;
  if (fcastSort === sortField) {
    fcastOrder = fcastOrder === 'desc' ? 'asc' : 'desc';
  } else {
    fcastSort = sortField;
    fcastOrder = 'desc';
  }
  document.querySelectorAll('#fr-forecast-table th').forEach(h => {
    h.classList.remove('sorted');
    const a = h.querySelector('.sort-arrow');
    if (a) a.remove();
  });
  th.classList.add('sorted');
  const arrow = document.createElement('span');
  arrow.className = 'sort-arrow';
  arrow.textContent = fcastOrder === 'desc' ? '▼' : '▲';
  th.appendChild(arrow);
  fcastPage = 1;
  loadForecast();
});

// ── Sort ──
document.querySelector('#fr-published-table thead').addEventListener('click', (e) => {
  const th = e.target.closest('th[data-sort]');
  if (!th) return;
  const sortField = th.dataset.sort;
  if (currentSort === sortField) {
    currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
  } else {
    currentSort = sortField;
    currentOrder = 'desc';
  }
  document.querySelectorAll('#fr-published-table th').forEach(h => {
    h.classList.remove('sorted');
    const a = h.querySelector('.sort-arrow');
    if (a) a.remove();
  });
  th.classList.add('sorted');
  const arrow = document.createElement('span');
  arrow.className = 'sort-arrow';
  arrow.textContent = currentOrder === 'desc' ? '▼' : '▲';
  th.appendChild(arrow);
  currentPage = 1;
  loadPublished();
});

// ── Click → stock-score page ──
document.addEventListener('click', (e) => {
  const cell = e.target.closest('.symbol[data-symbol]');
  if (!cell) return;
  const sym = cell.dataset.symbol;
  const mkt = sym.startsWith('6') ? 'sh' : sym.startsWith('9') ? 'bj' : 'sz';
  window.open(`/stock-score.html?symbol=${encodeURIComponent(sym)}&market=${mkt}`, '_blank');
});

function loadAll() {
  loadingEl.textContent = '加载中...';
  Promise.all([loadForecast(), loadUpcoming(), loadPublished()]).then(() => { loadingEl.textContent = ''; });
}

loadPeriods();
