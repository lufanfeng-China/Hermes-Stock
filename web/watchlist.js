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

function esc(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function validPercent(v) { return v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v)) && Number(v) >= 0 && Number(v) <= 100; }
function sourceDate(value) { return /^\d{4}-\d{2}-\d{2}$/.test(String(value || '')) ? String(value) : '未知'; }
function evidenceDate(day) { const value = sourceDate(day); return value === '未知' ? '' : `<small class="wl-evidence-date">截至 ${esc(value)}</small>`; }
function peCell(s) {
  const valid = s.pe_percentile_5y_status === 'ok' && validPercent(s.pe_percentile_5y);
  return `${valid ? Number(s.pe_percentile_5y).toFixed(1) + '%' : '未知'}${evidenceDate(s.pe_percentile_5y_price_date)}`;
}
function turnoverCell(s) {
  const day = sourceDate(s.turnover_percentile_1y_as_of);
  const samples = Number(s.turnover_percentile_1y_sample_count);
  const valid = s.turnover_percentile_1y_status === 'ok' && validPercent(s.turnover_percentile_1y) && samples >= 120 && day !== '未知';
  const label = valid ? Number(s.turnover_percentile_1y).toFixed(1) + '%' : '未知';
  const button = valid && s.market && s.symbol
    ? `<button type="button" class="wl-evidence-btn" data-turnover-trend="1" data-market="${esc(s.market)}" data-symbol="${esc(s.symbol)}" data-name="${esc(s.stock_name || '')}" data-date="${esc(day)}" aria-label="查看截至${esc(day)}换手分位趋势">${label}</button>` : label;
  return `${button}${evidenceDate(day)}<small class="wl-evidence-date">样本 ${Number.isFinite(samples) && samples > 0 ? samples : '未知'}</small>`;
}
function mrsCell(s) {
  const valid = s.mrs_score !== null && s.mrs_score !== undefined && s.mrs_score !== '' && Number.isFinite(Number(s.mrs_score)) && typeof s.mrs_label === 'string' && s.mrs_label.trim();
  return `${valid ? esc(s.mrs_label) + ' · ' + Number(s.mrs_score).toFixed(1) : '未知'}${evidenceDate(s.relative_strength_as_of)}`;
}
function swingCell(s) {
  const swing = s.swing_structure || {};
  const day = sourceDate(s.swing_structure_as_of || swing.as_of);
  const valid = swing.status === 'ok' && swing.state && swing.state !== '证据不足' && ['bull','bear','neutral','caution'].includes(swing.tendency) &&
    sourceDate(swing.as_of || day) === day && sourceDate(swing.last_bar_date) === day && Boolean(swing.source_sha256);
  const tendency = {bull:'偏多',bear:'偏空',neutral:'中性',caution:'谨慎'};
  const label = valid ? `${esc(swing.state)} · ${tendency[swing.tendency]} · ${esc(swing.stars ?? '—')}` : '未知';
  const content = valid && s.market && s.symbol
    ? `<button type="button" class="wl-evidence-btn" data-swing-chart="1" data-market="${esc(s.market)}" data-symbol="${esc(s.symbol)}" data-name="${esc(s.stock_name || '')}" data-date="${esc(day)}" aria-label="查看当前前复权峰谷证据，表格截至${esc(day)}">${label}</button>` : label;
  return `${content}${evidenceDate(day)}`;
}

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
      <td class="num">${peCell(s)}</td>
      <td class="num">${turnoverCell(s)}</td>
      <td>${mrsCell(s)}</td>
      <td class="wl-swing-cell">${swingCell(s)}</td>
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
  document.querySelectorAll('[data-turnover-trend]').forEach(btn => btn.addEventListener('click', e => { e.stopPropagation(); showTurnoverTrend(btn); }));
  document.querySelectorAll('[data-swing-chart]').forEach(btn => btn.addEventListener('click', e => { e.stopPropagation(); showSwingChart(btn); }));
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
      window.location.href = `/stock-analysis.html?${params.toString()}`;
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

// ── Audited evidence dialogs ──────────────────────────────────────────────────
const turnoverDialog = document.getElementById('turnover-trend-dialog');
const turnoverSvg = document.getElementById('turnover-trend-svg');
const turnoverPlot = turnoverDialog.querySelector('.turnover-trend-plot');
const turnoverTooltip = document.getElementById('turnover-trend-tooltip');
let turnoverController, turnoverTrigger, turnoverRows = [];
function turnoverTrendChart(rows, day) {
  const end = Date.parse(day + 'T00:00:00Z');
  if (!Number.isFinite(end)) throw new Error('表格日期无效');
  const startDate = new Date(end); startDate.setUTCFullYear(startDate.getUTCFullYear()-1);
  const start = startDate.getTime(), lower = startDate.toISOString().slice(0,10);
  const points = rows.filter(r => r && /^\d{4}-\d{2}-\d{2}$/.test(r.date) && r.date >= lower && r.date <= day && Number.isFinite(Date.parse(r.date+'T00:00:00Z'))).sort((a,b) => a.date.localeCompare(b.date));
  const y = v => 260-224*v/100;
  const parts = ['<title>每日7日截尾均值换手率历史分位</title><desc>横轴日期，纵轴0至100%；缺失值不连线</desc>'];
  [0,25,50,75,100].forEach(t => parts.push(`<line x1="56" x2="790" y1="${y(t)}" y2="${y(t)}" stroke="#35504a"/><text x="47" y="${y(t)+4}" fill="#a9bcb5" text-anchor="end" font-size="12">${t}%</text>`));
  parts.push(`<text x="56" y="288" fill="#a9bcb5" font-size="12">${lower}</text><text x="790" y="288" fill="#a9bcb5" font-size="12" text-anchor="end">${day}</text>`);
  let segment=[];
  const flush=()=>{ if(segment.length>1)parts.push(`<path d="${segment.join(' ')}" fill="none" stroke="#b7e36b" stroke-width="2"/>`); segment=[]; };
  points.forEach((r,i)=>{
    if (!validPercent(r.percentile) || !Number.isFinite(Number(r.sample_count)) || Number(r.sample_count)<120) { flush(); return; }
    const x=(56+734*(Date.parse(r.date+'T00:00:00Z')-start)/(end-start)).toFixed(2), yy=y(Number(r.percentile)).toFixed(2);
    segment.push(`${segment.length?'L':'M'}${x},${yy}`);
    parts.push(`<circle data-turnover-point="${i}" tabindex="0" role="img" aria-label="${r.date} 换手分位 ${Number(r.percentile).toFixed(1)}%" cx="${x}" cy="${yy}" r="3" fill="#b7e36b"/>`);
  }); flush();
  return {html:parts.join(''),points};
}
function turnoverHover(point) {
  if (!point) { turnoverTooltip.hidden=true; return; }
  const row=turnoverRows[Number(point.dataset.turnoverPoint)]; if (!row) return;
  turnoverTooltip.textContent=`${row.date} · 历史分位 ${Number(row.percentile).toFixed(1)}%\n7日截尾均值 ${row.trimmed_average_pct==null?'未知':Number(row.trimmed_average_pct).toFixed(2)+'%'} · 有效样本 ${row.sample_count??'未知'} 日`;
  turnoverTooltip.hidden=false;
  turnoverTooltip.style.left=Math.max(4,Math.min(turnoverPlot.clientWidth-turnoverTooltip.offsetWidth-4,Number(point.getAttribute('cx'))*turnoverPlot.clientWidth/820-turnoverTooltip.offsetWidth/2))+'px';
  turnoverTooltip.style.top=Math.max(4,Number(point.getAttribute('cy'))*turnoverSvg.clientHeight/300-68)+'px';
}
async function showTurnoverTrend(trigger) {
  turnoverController?.abort(); const controller=new AbortController(); turnoverController=controller; turnoverTrigger=trigger;
  turnoverRows=[]; turnoverSvg.innerHTML=''; turnoverPlot.hidden=true; turnoverTooltip.hidden=true;
  const status=document.getElementById('turnover-trend-status');
  document.getElementById('turnover-trend-title').textContent=`${trigger.dataset.name||trigger.dataset.symbol} ${trigger.dataset.symbol} · 7日截尾均值换手历史分位`;
  status.textContent=`正在加载截至 ${trigger.dataset.date} 的近一年历史分位…`;
  if (!turnoverDialog.open) turnoverDialog.showModal();
  const query=new URLSearchParams({market:trigger.dataset.market,symbol:trigger.dataset.symbol,as_of_date:trigger.dataset.date});
  try {
    const response=await fetch('/api/stock-filter-turnover-trend?'+query,{signal:controller.signal});
    const payload=await response.json(); if(controller.signal.aborted||!turnoverDialog.open)return;
    if(!response.ok||!payload.ok)throw new Error(payload.error?.message||'换手历史分位接口不可用');
    if(payload.as_of_date!==trigger.dataset.date||!Array.isArray(payload.rows))throw new Error('趋势日期与表格日期不一致，拒绝绘制');
    const chart=turnoverTrendChart(payload.rows,trigger.dataset.date); turnoverRows=chart.points; turnoverSvg.innerHTML=chart.html;
    const count=turnoverSvg.querySelectorAll('[data-turnover-point]').length; turnoverPlot.hidden=!count;
    status.textContent=count?`表格截至 ${trigger.dataset.date} · 近一年历史分位 · ${count} 个有效交易日（缺失日不插值）`:'近一年暂无满足120个有效样本的历史分位；缺失日不补值。';
  } catch(error) { if(!controller.signal.aborted&&turnoverDialog.open){turnoverPlot.hidden=true;status.textContent='无法绘制换手历史分位：'+error.message;} }
}
turnoverSvg.addEventListener('pointermove',e=>{
  const rect=turnoverSvg.getBoundingClientRect(),px=(e.clientX-rect.left)*820/rect.width;
  const points=[...turnoverSvg.querySelectorAll('[data-turnover-point]')];
  const nearest=points.reduce((best,p)=>!best||Math.abs(Number(p.getAttribute('cx'))-px)<Math.abs(Number(best.getAttribute('cx'))-px)?p:best,null);
  turnoverHover(nearest&&px>=56&&px<=790&&Math.abs(Number(nearest.getAttribute('cx'))-px)<=12?nearest:null);
});
turnoverSvg.addEventListener('pointerleave',()=>turnoverHover(null));
turnoverSvg.addEventListener('focusin',e=>turnoverHover(e.target.closest('[data-turnover-point]')));
turnoverSvg.addEventListener('focusout',()=>turnoverHover(null));
turnoverDialog.querySelector('.turnover-trend-close').addEventListener('click',()=>turnoverDialog.close());
turnoverDialog.addEventListener('click',e=>{if(e.target===turnoverDialog)turnoverDialog.close();});
turnoverDialog.addEventListener('close',()=>{turnoverController?.abort();if(turnoverTrigger?.isConnected)turnoverTrigger.focus();turnoverController=turnoverTrigger=null;turnoverRows=[];});

// ── Live QFQ swing evidence (never backdate or fall back to raw K-line) ──────
const swingDialog=document.getElementById('swing-chart-dialog');
const swingSvg=document.getElementById('swing-chart-svg');
const swingMacd=document.getElementById('swing-chart-macd');
const swingMeta=document.getElementById('swing-chart-meta');
let swingController,swingTrigger,swingKlineChart,swingChartData,swingChartBars;
function renderSwingViewport(viewport) {
  if (!swingChartData || !swingChartBars) return;
  SwingChart.renderOverlay(swingChartData,swingKlineChart);
  PriceTrendChart.renderMacd(swingMacd,swingChartBars,viewport);
}
async function showSwingChart(trigger) {
  swingController?.abort(); const controller=new AbortController(); swingController=controller; swingTrigger=trigger;
  swingChartData=swingChartBars=null;
  swingDialog.querySelector('.swing-chart-scroll').hidden=true;
  swingMeta.textContent=`${trigger.dataset.symbol}｜正在计算单股当前最新有效前复权结构（表格结构截至 ${trigger.dataset.date}）…`;
  if(!swingDialog.open)swingDialog.showModal();
  const query=new URLSearchParams({market:trigger.dataset.market,symbol:trigger.dataset.symbol});
  try {
    const [response,rpsResponse]=await Promise.all([
      fetch('/api/swing-structure?'+query,{signal:controller.signal}),
      fetch('/api/stock-rps-history?symbol='+encodeURIComponent(trigger.dataset.symbol),{signal:controller.signal})
    ]);
    const payload=await response.json(),rps=await rpsResponse.json().catch(()=>({ok:false}));
    if(controller.signal.aborted||!swingDialog.open)return;
    if(!response.ok||!payload.ok)throw new Error(payload.error?.message||'结构证据无法读取');
    const data=payload.data||{},observation=data.observation||{};
    if(data.market!==trigger.dataset.market||data.symbol!==trigger.dataset.symbol||
       !data.as_of_date||observation.last_bar_date!==data.as_of_date||observation.status!=='ok'||
       data.price_basis!=='tdx_export_qfq'||data.source_type !== 'live_qfq'||!observation.source_sha256)
      throw new Error('当前前复权源、证券代码或结构证据不一致，拒绝绘制');
    const rpsOk=rpsResponse.ok&&rps.ok&&rps.symbol===trigger.dataset.symbol;
    const evidence=SwingChart.chartEvidence(data,rpsOk?rps.history:[]);
    if(!swingKlineChart)swingKlineChart=new KlineChart(swingSvg,{marginRight:48,interpolateRps:false});
    swingChartData=data; swingChartBars=evidence.bars;
    swingKlineChart.onViewportChange=viewport=>{
      renderSwingViewport(viewport);
      swingDialog.querySelectorAll('[data-swing-window]').forEach(b=>b.classList.remove('is-active'));
    };
    swingDialog.querySelector('.swing-chart-scroll').hidden=false;
    swingKlineChart.load(evidence.bars,evidence.rpsHistory,120);
    renderSwingViewport(swingKlineChart.visible);
    swingDialog.querySelectorAll('[data-swing-window]').forEach(b=>b.classList.toggle('is-active',Number(b.dataset.swingWindow)===120));
    swingMeta.textContent=`${trigger.dataset.symbol} ${data.name||trigger.dataset.name||''}｜表格结构截至 ${trigger.dataset.date}（已发布快照）｜当前前复权截至 ${data.as_of_date}（本地即时计算；可能与表格状态不同）｜结构 ${observation.state||'证据不足'}｜有效日线 ${evidence.bars.length} 根｜实心峰谷=确认，虚线圈=候选${SwingChart.verifiedBox(observation)?'｜箱体检验通过':'｜当前无通过检验的箱体'}｜RPS${evidence.rpsAsOf?'截至 '+evidence.rpsAsOf+(evidence.rpsAsOf===data.as_of_date?'':'（当日缺失，不补值）'):'不可用（未绘制）'}${rpsOk?'':'；RPS接口读取失败'}`;
  } catch(error) {
    if(!controller.signal.aborted&&swingDialog.open){swingDialog.querySelector('.swing-chart-scroll').hidden=true;swingChartData=swingChartBars=null;swingMeta.textContent='无法绘制当前前复权结构：'+error.message;}
  }
}
swingDialog.querySelectorAll('[data-swing-window]').forEach(button=>button.addEventListener('click',()=>{
  if(!swingKlineChart||!swingChartBars)return;
  swingKlineChart.setPreset(Number(button.dataset.swingWindow));renderSwingViewport(swingKlineChart.visible);
  swingDialog.querySelectorAll('[data-swing-window]').forEach(b=>b.classList.toggle('is-active',b===button));
}));
swingDialog.querySelector('.swing-chart-close').addEventListener('click',()=>swingDialog.close());
swingDialog.addEventListener('click',e=>{if(e.target===swingDialog)swingDialog.close();});
swingDialog.addEventListener('close',()=>{swingController?.abort();if(swingTrigger?.isConnected)swingTrigger.focus();swingController=swingTrigger=null;swingChartData=swingChartBars=null;});

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
