// valuation-model.js — Stock valuation models frontend
// Project-Hermes-Stock

let _data = null; // cached API response

// ── DOM refs ──
const $searchInput = document.getElementById('search-input');
const $searchBtn = document.getElementById('search-btn');
const $searchStatus = document.getElementById('search-status');
const $stockInfo = document.getElementById('stock-info');
const $tabs = document.getElementById('tabs');
const $tabContent = document.getElementById('tab-content');

$searchBtn.addEventListener('click', () => search($searchInput.value.trim()));
$searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') search($searchInput.value.trim()); });

// Tab switching
$tabs.addEventListener('click', (e) => {
  if (e.target.tagName === 'BUTTON') {
    $tabs.querySelectorAll('button').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    renderTab(e.target.dataset.tab);
  }
});

// ── Search ──
async function search(query) {
  if (!query) return;
  const m = query.match(/^(sh|sz|bj)/i);
  let market = m ? m[1].toLowerCase() : '';
  let symbol = m ? query.slice(2) : query;
  if (!market) market = symbol.startsWith('6') || symbol.startsWith('5') || symbol.startsWith('9') ? 'sh' : symbol.startsWith('0') || symbol.startsWith('3') ? 'sz' : 'bj';
  if (symbol.length !== 6 || !/^\d{6}$/.test(symbol)) {
    // Try name search
    searchByName(query);
    return;
  }
  $searchStatus.classList.remove('hidden');
  $searchStatus.textContent = '加载中...';
  try {
    const url = `/api/valuation-models?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`;
    const r = await fetch(url);
    const payload = await r.json();
    if (!r.ok || !payload.ok) {
      $searchStatus.textContent = '⚠ ' + (payload.error?.message || '查询失败');
      $searchStatus.classList.add('error');
      return;
    }
    _data = payload;
    $searchStatus.classList.add('hidden');
    renderAll();
  } catch (err) {
    $searchStatus.textContent = '⚠ ' + err.message;
    $searchStatus.classList.add('error');
  }
}

async function searchByName(name) {
  $searchStatus.classList.remove('hidden');
  $searchStatus.textContent = '搜索中...';
  try {
    const r = await fetch(`/api/stock-search?q=${encodeURIComponent(name)}&limit=1`);
    const payload = await r.json();
    if (payload.ok && payload.results?.length > 0) {
      const s = payload.results[0];
      $searchInput.value = s.market + s.symbol;
      search($searchInput.value);
    } else {
      $searchStatus.textContent = '未找到匹配股票';
      $searchStatus.classList.add('error');
    }
  } catch (err) {
    $searchStatus.textContent = '⚠ ' + err.message;
    $searchStatus.classList.add('error');
  }
}

// ── Render ──
function renderAll() {
  if (!_data) return;
  const d = _data;
  // Stock info
  $stockInfo.classList.remove('hidden');
  document.getElementById('si-name').textContent = d.stock_name || (d.market + d.symbol);
  document.getElementById('si-code').textContent = d.market.toUpperCase() + ':' + d.symbol;
  const md = d.market_data || {};
  document.getElementById('si-price').textContent = md.close_price?.toFixed(2) || '--';
  document.getElementById('si-mcap').textContent = md.total_market_cap?.toFixed(1) || '--';
  document.getElementById('si-period').textContent = d.latest_period || '--';
  document.getElementById('si-beta').textContent = md.beta?.toFixed(2) || '1.00';

  $tabs.classList.remove('hidden');
  renderTab('dcf');
}

function renderTab(tab) {
  if (!_data) return;
  const d = _data;
  let html = '';
  switch (tab) {
    case 'dcf': html = renderDCF(d); break;
    case 'wacc': html = renderWACC(d); break;
    case 'altman': html = renderAltman(d); break;
    case 'piotroski': html = renderPiotroski(d); break;
    case 'dupont': html = renderDuPont(d); break;
    case 'gordon': html = renderGordon(d); break;
    case 'ev': html = renderEV(d); break;
    case 'summary': html = renderSummary(d); break;
  }
  $tabContent.innerHTML = html;
}

// ── DCF ──
function renderDCF(d) {
  const m = d.dcf || {};
  const ip = m.intrinsic_value_per_share;
  const price = d.market_data?.close_price || 0;
  const diff = ip ? ((ip - price) / price * 100) : 0;
  const vcolor = diff > 20 ? 'green' : diff > 0 ? 'orange' : 'red';
  const vlabel = diff > 20 ? '显著低估' : diff > 0 ? '略低估' : '高估';

  // Financial company: PB-ROE model
  if (m._financial_note) {
    return `
    <div class="card">
      <div style="background:#2a1a00;border:1px solid var(--orange);border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:12px">
        ⚠ ${m._financial_note}
      </div>
      <div class="highlight">
        <div><span class="label">PB-ROE 内在价值</span><br><span class="big">¥${ip?.toFixed(2) || '--'}</span></div>
        <div><span class="label">当前价格</span><br><span class="big">¥${price.toFixed(2)}</span></div>
        <div><span class="label">偏离</span><br><span class="big ${vcolor}">${diff > 0 ? '+' : ''}${diff.toFixed(1)}%</span>
          <span style="font-size:12px;color:var(--muted)">(${vlabel})</span></div>
      </div>
      <h3>PB-ROE 参数</h3>
      <table>
        <tr><th>每股净资产 (BVPS)</th><td class="num">¥${m.book_value_per_share?.toFixed(2) || '--'}</td></tr>
        <tr><th>ROE</th><td class="num">${((m.roe || 0) * 100).toFixed(1)}%</td></tr>
        <tr><th>权益成本 (COE)</th><td class="num">${((m.cost_of_equity || 0) * 100).toFixed(2)}%</td></tr>
        <tr><th>公式</th><td style="font-size:11px;color:var(--muted)">${m.formula || ''}</td></tr>
      </table>
    </div>`;
  }

  let rows = '';
  if (m.pv_details) {
    for (const pv of m.pv_details) {
      rows += `<tr><td>${pv.year}</td><td class="num">${pv.cash_flow?.toFixed(2)}</td><td class="num">${pv.pv?.toFixed(2)}</td></tr>`;
    }
  }

  return `
    <div class="card">
      <div class="highlight">
        <div><span class="label">内在价值/股</span><br><span class="big">¥${ip?.toFixed(2) || '--'}</span></div>
        <div><span class="label">当前价格</span><br><span class="big">¥${price.toFixed(2)}</span></div>
        <div><span class="label">偏离</span><br><span class="big ${vcolor}">${diff > 0 ? '+' : ''}${diff.toFixed(1)}%</span>
          <span style="font-size:12px;color:var(--muted)">(${vlabel})</span></div>
      </div>
      <h3>DCF 参数</h3>
      <table>
        <tr><th>自由现金流</th><td class="num">${m.free_cash_flow?.toFixed(2)} 亿</td><th>增长率</th><td class="num">${((m.growth_rate || 0) * 100).toFixed(1)}%</td></tr>
        <tr><th>永续增长率</th><td class="num">${((m.perpetual_growth_rate || 0) * 100).toFixed(1)}%</td><th>WACC</th><td class="num">${((m.wacc || 0) * 100).toFixed(2)}%</td></tr>
        <tr><th>预测期数</th><td class="num">${m.periods || 5}</td><th>终值</th><td class="num">${m.terminal_value?.toFixed(2)} 亿</td></tr>
        <tr><th>企业价值</th><td class="num">${m.enterprise_value?.toFixed(2)} 亿</td><th>股权价值</th><td class="num">${m.equity_value?.toFixed(2)} 亿</td></tr>
      </table>
      ${rows ? `<h3 style="margin-top:16px">现金流折现明细</h3><table><tr><th>年份</th><th class="num">现金流(亿)</th><th class="num">现值(亿)</th></tr>${rows}</table>` : ''}
      ${m.error ? `<p class="error">${m.error}</p>` : ''}
    </div>
  `;
}

// ── WACC ──
function renderWACC(d) {
  const m = d.wacc || {};
  return `
    <div class="card">
      <div class="highlight">
        <div><span class="label">WACC</span><br><span class="big">${((m.wacc || 0) * 100).toFixed(2)}%</span></div>
        <div><span class="label">权益成本</span><br><span style="font-size:18px">${((m.cost_of_equity || 0) * 100).toFixed(2)}%</span></div>
        <div><span class="label">税后债务成本</span><br><span style="font-size:18px">${((m.after_tax_cost_of_debt || 0) * 100).toFixed(2)}%</span></div>
      </div>
      <table>
        <tr><th>权益市值</th><td class="num">${m.market_value_equity?.toFixed(2) || '--'} 亿</td><th>权益权重</th><td class="num">${((m.equity_weight || 0) * 100).toFixed(1)}%</td></tr>
        <tr><th>债务市值</th><td class="num">${m.market_value_debt?.toFixed(2) || '--'} 亿</td><th>债务权重</th><td class="num">${((m.debt_weight || 0) * 100).toFixed(1)}%</td></tr>
        <tr><th>债务成本(税前)</th><td class="num">${((m.cost_of_debt || 0) * 100).toFixed(2)}%</td><th>税率</th><td class="num">${((m.tax_rate || 0) * 100).toFixed(1)}%</td></tr>
        <tr><th>总价值</th><td class="num" colspan="3">${m.total_value?.toFixed(2) || '--'} 亿</td></tr>
      </table>
      ${m.error ? `<p class="error">${m.error}</p>` : ''}
    </div>
  `;
}

// ── Altman Z ──
function renderAltman(d) {
  const m = d.altman_z || {};
  const z = m.z_score;
  const zc = z >= 2.99 ? 'green' : z >= 1.81 ? 'orange' : 'red';
  return `
    <div class="card">
      <div class="highlight">
        <div><span class="label">Z-Score</span><br><span class="big ${zc}">${z?.toFixed(2) || '--'}</span></div>
        <div><span class="label">判断</span><br><span class="label-${zc}">${m.zone || '--'}</span></div>
      </div>
      <table>
        <tr><th>X1 营运资本/总资产</th><td class="num">${m.x1_wc_to_ta?.toFixed(4) || '--'}</td><td style="color:var(--muted);font-size:11px">(×1.2)</td></tr>
        <tr><th>X2 留存收益/总资产</th><td class="num">${m.x2_re_to_ta?.toFixed(4) || '--'}</td><td style="color:var(--muted);font-size:11px">(×1.4)</td></tr>
        <tr><th>X3 EBIT/总资产</th><td class="num">${m.x3_ebit_to_ta?.toFixed(4) || '--'}</td><td style="color:var(--muted);font-size:11px">(×3.3)</td></tr>
        <tr><th>X4 市值/总负债</th><td class="num">${m.x4_mve_to_tl?.toFixed(4) || '--'}</td><td style="color:var(--muted);font-size:11px">(×0.6)</td></tr>
        <tr><th>X5 营收/总资产</th><td class="num">${m.x5_sales_to_ta?.toFixed(4) || '--'}</td><td style="color:var(--muted);font-size:11px">(×1.0)</td></tr>
      </table>
      <p style="margin-top:12px;font-size:11px;color:var(--muted)">
        解读：Z &gt; 2.99 安全区 | 1.81–2.99 灰色区 | &lt; 1.81 危险区（适用于制造业上市公司）
      </p>
      ${m.error ? `<p class="error">${m.error}</p>` : ''}
    </div>
  `;
}

// ── Piotroski ──
function renderPiotroski(d) {
  const m = d.piotroski || {};
  const s = m.total_score;
  const sc = s >= 7 ? 'green' : s >= 4 ? 'orange' : 'red';
  let items = '';
  if (m.criteria) {
    for (const c of m.criteria) {
      const cls = c.pass ? 'pass' : '';
      items += `
        <div class="pio-item ${cls}">
          <i class="${c.pass ? 'check' : 'cross'}">${c.pass ? '✓' : '✗'}</i>
          <div style="font-size:13px;margin-top:4px">${c.name}</div>
          <div class="desc">${c.value || ''}</div>
        </div>`;
    }
  }
  return `
    <div class="card">
      <div class="highlight">
        <div><span class="label">Piotroski F-Score</span><br><span class="big ${sc}">${s}/9</span></div>
        <div><span class="label">评级</span><br><span class="label-${sc}">${m.grade || '--'}</span></div>
      </div>
      <div class="pio-grid">${items}</div>
      <p style="margin-top:12px;font-size:11px;color:var(--muted)">
        解读：8-9 优秀 | 6-7 良好 | 3-5 一般 | 0-2 差。基于盈利能力(4分)、杠杆/流动性(3分)、运营效率(2分)
      </p>
    </div>
  `;
}

// ── DuPont ──
function renderDuPont(d) {
  const m = d.dupont || {};
  return `
    <div class="card">
      <h3>DuPont 分析</h3>
      <div class="highlight">
        <div><span class="label">ROE</span><br><span class="big">${((m.roe || 0) * 100).toFixed(2)}%</span></div>
        <div><span class="label">净利率</span><br><span style="font-size:18px">${((m.net_profit_margin || 0) * 100).toFixed(2)}%</span></div>
        <div><span class="label">资产周转率</span><br><span style="font-size:18px">${m.asset_turnover?.toFixed(4)}</span></div>
        <div><span class="label">权益乘数</span><br><span style="font-size:18px">${m.equity_multiplier?.toFixed(2)}</span></div>
      </div>
      <p style="font-size:11px;color:var(--muted);margin-bottom:12px">
        ROE = 净利率 × 资产周转率 × 权益乘数 = ${((m.basic_dupont_roe || 0) * 100).toFixed(2)}%
      </p>
      ${m.tax_burden !== undefined ? `
        <h3>扩展 DuPont (5因素)</h3>
        <table>
          <tr><th>税负率</th><td class="num">${(m.tax_burden * 100).toFixed(1)}%</td></tr>
          <tr><th>利息负担率</th><td class="num">${(m.interest_burden * 100).toFixed(1)}%</td></tr>
          <tr><th>营业利润率</th><td class="num">${(m.operating_margin * 100).toFixed(1)}%</td></tr>
          <tr><th>扩展 ROE</th><td class="num" style="font-weight:600">${((m.extended_dupont_roe || 0) * 100).toFixed(2)}%</td></tr>
        </table>
      ` : ''}
      ${m.error ? `<p class="error">${m.error}</p>` : ''}
    </div>
  `;
}

// ── Gordon Growth ──
function renderGordon(d) {
  const m = d.gordon_growth || {};
  return `
    <div class="card">
      <div class="highlight">
        <div><span class="label">Gordon 内在价值</span><br><span class="big">¥${m.intrinsic_value?.toFixed(2) || '--'}</span></div>
      </div>
      <table>
        <tr><th>每股股息(D0)</th><td class="num">¥${m.dividends_per_share?.toFixed(4) || '--'}</td></tr>
        <tr><th>下期股息(D1)</th><td class="num">¥${m.next_dividend?.toFixed(4) || '--'}</td></tr>
        <tr><th>权益成本(r)</th><td class="num">${((m.cost_of_equity || 0) * 100).toFixed(2)}%</td></tr>
        <tr><th>股息增长率(g)</th><td class="num">${((m.growth_rate || 0) * 100).toFixed(2)}%</td></tr>
      </table>
      <p style="margin-top:8px;font-size:11px;color:var(--muted)">P = D1 / (r - g) — 假设30%分红率，适用于稳定分红公司</p>
      ${m.error ? `<p class="error">${m.error}</p>` : ''}
    </div>
  `;
}

// ── Enterprise Value ──
function renderEV(d) {
  const m = d.enterprise_value || {};
  return `
    <div class="card">
      <div class="highlight">
        <div><span class="label">企业价值 (EV)</span><br><span class="big">${m.enterprise_value?.toFixed(2)} 亿</span></div>
      </div>
      <table>
        <tr><th>总市值</th><td class="num">${m.market_cap?.toFixed(2)} 亿</td></tr>
        <tr><th>+ 总负债</th><td class="num">${m.total_debt?.toFixed(2)} 亿</td></tr>
        <tr><th>+ 优先股</th><td class="num">${m.preferred_equity?.toFixed(2)} 亿</td></tr>
        <tr><th>+ 少数股东权益</th><td class="num">${m.minority_interest?.toFixed(2)} 亿</td></tr>
        <tr><th>- 现金及等价物</th><td class="num red">${m.cash_and_equivalents?.toFixed(2)} 亿</td></tr>
        <tr style="border-top:2px solid var(--accent)"><th>企业价值</th><td class="num" style="font-weight:600">${m.enterprise_value?.toFixed(2)} 亿</td></tr>
      </table>
      ${m.error ? `<p class="error">${m.error}</p>` : ''}
    </div>
  `;
}

// ── Financial Summary ──
function renderSummary(d) {
  const fs = d.financial_summary || {};
  return `
    <div class="card">
      <h3>财务摘要（最新报告期 ${d.latest_period || ''}，单位：亿元）</h3>
      <table>
        <tr><th>营业收入</th><td class="num">${fs.revenue?.toFixed(2)}</td></tr>
        <tr><th>归母净利润</th><td class="num">${fs.net_profit?.toFixed(2)}</td></tr>
        <tr><th>经营现金流</th><td class="num">${fs.ocf?.toFixed(2)}</td></tr>
        <tr><th>自由现金流</th><td class="num ${(fs.free_cf || 0) >= 0 ? 'green' : 'red'}">${fs.free_cf?.toFixed(2)}</td></tr>
        <tr><th>总资产</th><td class="num">${fs.total_assets?.toFixed(2)}</td></tr>
        <tr><th>总负债</th><td class="num">${fs.total_liabilities?.toFixed(2)}</td></tr>
        <tr><th>股东权益</th><td class="num">${fs.total_equity?.toFixed(2)}</td></tr>
        <tr><th>有息负债</th><td class="num">${fs.total_debt?.toFixed(2)}</td></tr>
        <tr><th>现金</th><td class="num">${fs.cash_equiv?.toFixed(2)}</td></tr>
      </table>
    </div>
  `;
}
