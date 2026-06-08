/**
 * 瓶颈股发现 — 前端交互逻辑
 * ==================================================
 * 支持两种模式:
 *   A) 逐步执行: navigateStep(N) → 每步独立 API → 用户确认 → 下一步
 *   B) 一键全自动: startAuto() → 调用 /api/bottleneck/auto → 流式展示
 *
 * 报告管理:
 *   - 查看历史: /api/bottleneck/reports
 *   - 加载报告: /api/bottleneck/report?filename=xxx
 *   - 重新运行: /api/bottleneck/rerun?filename=xxx
 *   - 保存报告: /api/bottleneck/save-report
 */

import { KlineChart } from './kline-chart.js?v=20260604-ma';

const API_BASE = '';

// ── K-line chart singleton ──
let scoreKlineChart = null;

// ── 全局状态 ──
let state = {
  mode: 'step',       // 'step' | 'auto'
  currentStep: 0,     // 1-7
  selectedTrend: null,
  trendId: null,
  stepResults: {},     // {1: data, 2: data, ...}
  allTrends: [],
};

// ── 初始化 ──
async function init() {
  await loadTrends();
  await loadHistory();
}

async function loadTrends() {
  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/step1`);
    const data = await res.json();
    if (data.ok && data.type === 'list') {
      state.allTrends = data.trends;
    }
  } catch (e) {
    console.error('加载趋势列表失败:', e);
  }
}

// ── 加载历史报告 ──
async function loadHistory() {
  const listEl = document.getElementById('history-list');
  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/reports`);
    const data = await res.json();
    if (data.ok && data.reports.length > 0) {
      listEl.innerHTML = data.reports.slice(0, 5).map(r => `
        <div style="padding:4px 0;border-bottom:1px solid var(--border);cursor:pointer;font-size:12px;"
             onclick="loadSavedReport('${r.filename}')" title="点击查看">
          ${r.trend_name || r.trend_id}<br>
          <span style="color:var(--text-muted)">${r.created_at}</span>
        </div>
      `).join('');
    } else {
      listEl.innerHTML = '暂无历史报告';
    }
  } catch (e) {
    listEl.innerHTML = '加载失败';
  }
}

// ── 历史报告弹窗 ──
function toggleHistory() {
  const popup = document.getElementById('history-popup');
  if (popup.style.display === 'flex') {
    popup.style.display = 'none';
    return;
  }
  popup.style.display = 'flex';
  loadHistoryPopup();
}

async function loadHistoryPopup() {
  const content = document.getElementById('history-popup-content');
  content.innerHTML = '<div class="spinner"></div> 加载中...';
  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/reports`);
    const data = await res.json();
    if (data.ok && data.reports.length > 0) {
      content.innerHTML = data.reports.map(r => `
        <div style="padding:10px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;">
          <div>
            <div style="font-weight:600;">${r.trend_name || r.trend_id}</div>
            <div style="font-size:12px;color:var(--text-muted);">${r.created_at} | ${r.filename}</div>
          </div>
          <div style="display:flex;gap:6px;">
            <button class="btn" onclick="loadSavedReport('${r.filename}')">查看</button>
            <button class="btn btn-accent2" onclick="rerunReport('${r.filename}')">🔄 重跑</button>
          </div>
        </div>
      `).join('');
    } else {
      content.innerHTML = '暂无历史报告';
    }
  } catch (e) {
    content.innerHTML = '加载失败: ' + e.message;
  }
}

async function loadSavedReport(filename) {
  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/report?filename=${encodeURIComponent(filename)}`);
    const data = await res.json();
    if (data.ok && data.report) {
      const report = data.report;
      state.trendId = report.trend_id;
      state.stepResults = report.steps || {};
      state.stepResults.step1 = state.stepResults.step1 || { ok: true, type: 'detail', trend: { id: report.trend_id } };
      // 渲染所有步骤
      for (let i = 1; i <= 7; i++) {
        if (state.stepResults['step' + i]) {
          markStepComplete(i);
        }
      }
      // 直接渲染最终报告
      renderStep7();
      highlightStep(7);
      toggleHistory();
    }
  } catch (e) {
    alert('加载报告失败: ' + e.message);
  }
}

async function rerunReport(filename) {
  if (!confirm('确定要重新运行此报告吗？将获取最新数据并更新时间戳。')) return;
  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/rerun?filename=${encodeURIComponent(filename)}`);
    const data = await res.json();
    if (data.ok) {
      state.stepResults = data.results || {};
      for (let i = 1; i <= 7; i++) {
        if (state.stepResults['step' + i]) {
          renderStep(i);
        }
      }
      markStepComplete(7);
      highlightStep(7);
      loadHistory();
      toggleHistory();
      alert(`已重新分析！新报告: ${data.new_filename}`);
    }
  } catch (e) {
    alert('重新运行失败: ' + e.message);
  }
}

// ── 导航步骤 ──
function navigateStep(step) {
  state.mode = 'step';
  state.currentStep = step;
  highlightStep(step);

  switch (step) {
    case 1: renderStep1(); break;
    case 2: if (state.trendId) renderStep2(); else alert('请先选择趋势'); break;
    case 3: if (state.trendId) renderStep3(); else alert('请先完成步骤2'); break;
    case 4: if (state.stepResults.step3) renderStep4(); else alert('请先完成步骤3'); break;
    case 5: if (state.stepResults.step4) renderStep5(); else alert('请先完成步骤4'); break;
    case 6: if (state.stepResults.step5) renderStep6(); else alert('请先完成步骤5'); break;
    case 7: if (state.stepResults.step6) renderStep7(); else alert('请先完成步骤6'); break;
  }
}

function highlightStep(step) {
  document.querySelectorAll('.step-item').forEach(el => el.classList.remove('active'));
  const nav = document.getElementById('step-nav-' + step);
  if (nav) nav.classList.add('active');
}

function markStepComplete(step) {
  const nav = document.getElementById('step-nav-' + step);
  if (nav) nav.classList.add('done');
}

function markAllComplete() {
  for (let i = 1; i <= 7; i++) markStepComplete(i);
}

function showLoading(cardId) {
  const el = document.getElementById(cardId);
  if (el) el.innerHTML = '<div class="spinner"></div> <span style="color:var(--text-muted);">分析中...</span>';
}

// ── Step 1: 选择趋势 ──
function renderStep1() {
  const wa = document.getElementById('work-area');
  wa.innerHTML = `
    <div class="card" id="step1-card">
      <h2>📌 步骤 1：选择超级趋势</h2>
      <p>Serenity 方法论的第一步是确认一个「确定性极高」的超级趋势。
      趋势必须是不可逆的、有物理/政策/技术规律驱动的。</p>
      <div class="trend-select" id="trend-selector">
        ${state.allTrends.map(t => `
          <div class="trend-card ${state.trendId === t.id ? 'selected' : ''}"
               onclick="selectTrend('${t.id}')" id="trend-${t.id}">
            <div class="trend-name">${t.name}</div>
            <div class="trend-desc">${t.description}</div>
            <div class="trend-anchor">⚓ ${t.anchor || ''}</div>
          </div>
        `).join('')}
        <div class="trend-card ${state.trendId === '__custom__' ? 'selected' : ''}"
             onclick="selectTrend('__custom__')" id="trend-__custom__"
             style="border-style:dashed;">
          <div class="trend-name">➕ 自定义趋势</div>
          <div class="trend-desc">输入你自己的趋势方向，AI 将实时拆解产业链</div>
        </div>
      </div>
      ${state.trendId === '__custom__' ? `
        <div style="margin-top:12px;">
          <textarea id="custom-desc" placeholder="描述你的趋势方向，越具体越好..." style="width:100%;min-height:80px;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:10px;"></textarea>
        </div>
      ` : ''}
      <div style="margin-top:16px;">
        <button class="btn btn-primary" onclick="executeStep1()">✅ 确认选择，进入步骤 2</button>
      </div>
    </div>
  `;
  highlightStep(1);
}

function selectTrend(trendId) {
  state.trendId = trendId;
  document.querySelectorAll('.trend-card').forEach(el => el.classList.remove('selected'));
  const card = document.getElementById('trend-' + trendId);
  if (card) card.classList.add('selected');
  // 如果是自定义，展开输入框
  if (trendId === '__custom__') {
    renderStep1();
  }
}

async function executeStep1() {
  if (!state.trendId) return alert('请先选择一个趋势');
  if (state.trendId === '__custom__') {
    const desc = document.getElementById('custom-desc')?.value?.trim();
    if (!desc) return alert('请输入趋势描述');
    state.stepResults.custom_description = desc;
    state.stepResults.step1 = { ok: true, type: 'detail', trend: { id: '__custom__', name: '自定义趋势', description: desc } };
  } else {
    try {
      const res = await fetch(`${API_BASE}/api/bottleneck/step1?trend_id=${state.trendId}`);
      const data = await res.json();
      if (!data.ok) return alert(data.error);
      state.stepResults.step1 = data;
    } catch (e) { return alert('请求失败: ' + e.message); }
  }
  markStepComplete(1);
  navigateStep(2);
}

// ── Step 2: 拆解产业链 ──
async function renderStep2() {
  const wa = document.getElementById('work-area');
  showLoading('work-area');

  try {
    const customDesc = state.stepResults.custom_description || '';
    const apiUrl = `${API_BASE}/api/bottleneck/step2?trend_id=${state.trendId}&custom_description=${encodeURIComponent(customDesc)}`;
    const res = await fetch(apiUrl);
    const data = await res.json();
    if (!data.ok) { wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${data.error}</p></div>`; return; }
    state.stepResults.step2 = data;

    const layers = data.layers || [];

    // 处理自定义趋势：尚无预置产业链，展示提示
    if (data.type === 'custom' || (layers.length === 0 && state.trendId === '__custom__' && data.type !== 'custom_processing')) {
      const desc = state.stepResults.custom_description || '';
      wa.innerHTML = `
        <div class="card" id="step2-card">
          <h2>🔗 步骤 2：拆解产业链</h2>
          <p style="color:var(--yellow);font-weight:600;">⚠️ 自定义趋势「${desc}」暂无预置产业链数据。</p>
          <p>当前版本支持以下预置趋势的自动拆解：</p>
          <div style="margin:12px 0;">
            ${state.allTrends.map(t => `
              <div class="trend-card" onclick="state.trendId='${t.id}'; markStepComplete(1); renderStep2();" style="cursor:pointer;margin-bottom:8px;">
                <div class="trend-name">${t.name}</div>
                <div class="trend-desc">${t.description.substring(0,100)}...</div>
              </div>
            `).join('')}
          </div>
          <p style="font-size:13px;color:var(--text-muted);">💡 点击上方任一预置趋势可直接切换。自定义趋势的 AI 实时拆解功能正在开发中。</p>
          <div style=\"display:flex;gap:8px;margin-top:16px;\">
            <button class=\"btn\" onclick=\"renderStep1();\">← 返回重新选择</button>
          </div>
        </div>
      `;
      highlightStep(2);
      return;
    }

    // 处理 AI 后台拆解中
    if (data.type === 'custom_processing') {
      const sid = data.session_id || '';
      wa.innerHTML = `
        <div class="card" id="step2-card">
          <h2>🔗 步骤 2：拆解产业链</h2>
          <p style="color:var(--accent2);font-weight:600;font-size:16px;">🤖 AI 正在拆解「${data.custom_description || ''}」的产业链</p>
          <div style="text-align:center;padding:24px;">
            <div class="spinner" style="width:40px;height:40px;border-width:3px;margin-bottom:16px;"></div>
            <div id="ai-status-text" style="font-size:14px;color:var(--text-muted);line-height:2;">
              <div>⏳ Hermes AI 正在逐层推理产业链...</div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:4px;">这需要 1-3 分钟，请耐心等待</div>
            </div>
            <div id="ai-status-log" style="margin-top:16px;font-size:12px;color:var(--text-muted);text-align:left;max-width:400px;margin-left:auto;margin-right:auto;"></div>
          </div>
        </div>
      `;
      highlightStep(2);
      // 轮询等待结果
      pollCustomStatus(sid);
      return;
    }

    wa.innerHTML = `
      <div class="card" id="step2-card">
        <h2>🔗 步骤 2：拆解产业链 ${data._source ? `<span style="font-size:12px;color:var(--text-muted);font-weight:normal;">(${data._source})</span>` : ''}</h2>
        <p>从终端需求出发，<b>逐层向下追问</b>：每层「不可替代」的环节在哪？全球几家？</p>
        <p style="font-size:13px;color:var(--accent);margin:8px 0;">📐 趋势锚点：${data.anchor || '—'}</p>
        <div style="margin:12px 0;">
          ${layers.map(l => `
            <div class="chain-layer">
              <div class="layer-num">L${l.level}</div>
              <div class="layer-content">
                <div class="layer-name">
                  ${l.name}
                  <span class="badge ${l.supplier_count <= 2 ? 'badge-bottleneck' : 'badge-skip'}">
                    ${l.supplier_count <= 1 ? '垄断' : l.supplier_count <= 2 ? '双寡头' : l.supplier_count + '家'}
                  </span>
                </div>
                <div class="layer-role">${l.role}</div>
                <div class="layer-players">
                  🌍 全球：${(l.global_players || []).slice(0,3).join(' / ')}
                  ${(l.global_players || []).length > 3 ? ` +${l.global_players.length-3}家` : ''}
                  &nbsp;&nbsp;|&nbsp;&nbsp;
                  🇨🇳 国内：${(l.domestic_players || []).slice(0,3).join(' / ')}
                  ${(l.domestic_players || []).length > 3 ? ` +${l.domestic_players.length-3}家` : ''}
                </div>
                ${l.supplier_count <= 2 ? `<div class="layer-reason" style="color:var(--red);">🔴 ${l.description.substring(0,200)}...</div>` : ''}
              </div>
            </div>
          `).join('')}
        </div>
        <div style="display:flex;gap:8px;margin-top:16px;">
          <button class="btn btn-primary" onclick="markStepComplete(2); navigateStep(3);">✅ 确认，进入步骤 3</button>
        </div>
      </div>
    `;
  } catch (e) {
    wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${e.message}</p></div>`;
  }
  highlightStep(2);
}

// ── Step 3: 识别瓶颈层 ──
async function renderStep3() {
  const wa = document.getElementById('work-area');
  showLoading('work-area');

  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/step3?trend_id=${state.trendId}`);
    const data = await res.json();
    if (!data.ok) { wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${data.error}</p></div>`; return; }
    state.stepResults.step3 = data;

    const bottlenecks = data.bottlenecks || [];
    wa.innerHTML = `
      <div class="card" id="step3-card">
        <h2>🔍 步骤 3：识别瓶颈层</h2>
        <p>遍历 ${data.total_layers} 层产业链，逐层数供应商数量：</p>
        <table style="width:100%;font-size:13px;margin:12px 0;">
          <tr style="color:var(--text-muted);">
            <td>≥3家 → ⚪ 跳过</td>
            <td>2家 → 🟡 盯住</td>
            <td>≤1家 → 🔴 就是它！</td>
          </tr>
        </table>
        <div class="summary-grid">
          <div class="summary-item"><div class="val">${data.total_layers}</div><div class="label">产业链层数</div></div>
          <div class="summary-item" style="border:1px solid var(--red);"><div class="val" style="color:var(--red);">${data.bottleneck_count}</div><div class="label">瓶颈层数</div></div>
        </div>

        ${bottlenecks.length > 0 ? `
          <h3>🔴 发现的瓶颈层（按卡脖子程度排序）</h3>
          ${bottlenecks.map((b, idx) => `
            <div class="chain-layer bottleneck" style="margin-bottom:8px;">
              <div class="layer-num" style="color:var(--accent);font-weight:700;">#${idx+1}</div>
              <div class="layer-content">
                <div class="layer-name">
                  L${b.level} — ${b.name}
                  <span class="badge badge-bottleneck">${b.bottleneck_level || '瓶颈'}</span>
                  <span class="badge badge-score">卡脖子度 ${'⭐'.repeat(b.bottleneck_score || 0)}</span>
                </div>
                <div class="layer-reason" style="color:var(--text);">${b.bottleneck_reason || ''}</div>
              </div>
            </div>
          `).join('')}
        ` : '<p style="color:var(--text-muted);">未发现符合标准的瓶颈层。</p>'}

        <p style="font-size:13px;color:var(--accent2);margin-top:12px;">💡 ${data.summary || ''}</p>
        <div style="display:flex;gap:8px;margin-top:16px;">
          <button class="btn btn-primary" onclick="markStepComplete(3); navigateStep(4);">✅ 确认，进入步骤 4（映射 A 股）</button>
        </div>
      </div>
    `;
  } catch (e) {
    wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${e.message}</p></div>`;
  }
  highlightStep(3);
}

// ── Step 4: 映射 A 股标的 ──
async function renderStep4() {
  const wa = document.getElementById('work-area');
  showLoading('work-area');

  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/step4?trend_id=${state.trendId}`);
    const data = await res.json();
    if (!data.ok) { wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${data.error}</p></div>`; return; }
    state.stepResults.step4 = data;

    const mapped = data.mapped_layers || [];
    wa.innerHTML = `
      <div class="card" id="step4-card">
        <h2>📋 步骤 4：映射 A 股标的</h2>
        <p>对每个瓶颈层，列出对应的 A 股上市公司。<b>候选 ≤15 家 → 全部列出</b></p>

        ${mapped.map(m => `
          <div style="margin:20px 0;padding:16px;border:1px solid var(--border);border-radius:10px;">
            <h3>
              L${m.level} — ${m.name}
              <span class="badge badge-bottleneck">${m.bottleneck_level || ''}</span>
              <span class="badge badge-score">${'⭐'.repeat(m.bottleneck_score || 0)}</span>
            </h3>
            <p style="font-size:13px;color:var(--text-muted);margin-bottom:8px;">${m.bottleneck_reason || ''}</p>
            <p style="font-size:12px;color:var(--accent2);">
              ${m.show_all ? `✅ 全部 ${m.total_stocks} 家候选标的：` : `📊 共 ${m.total_stocks} 家候选，展示前 ${m.stocks.length} 家（剩余 ${m.remaining} 家）`}
            </p>
            <table class="data-table" style="margin-top:8px;">
              <thead><tr><th>#</th><th>股票代码</th><th>股票名称</th><th>操作</th></tr></thead>
              <tbody>
                ${m.stocks.map((s, idx) => `
                  <tr>
                    <td>${idx+1}</td>
                    <td style="font-weight:600;">${typeof s === 'object' ? s.code : s}</td>
                    <td>${typeof s === 'object' ? (s.name || '—') : '—'}</td>
                    <td>
                      <button class="btn" style="padding:4px 10px;font-size:11px;"
                              onclick="window.open('/stock-score.html?symbol=${typeof s === 'object' ? s.code : s}&market=${(typeof s === 'object' ? s.code : s).startsWith('6')?'sh':'sz'}','_blank')">
                        查看 →
                      </button>
                    </td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        `).join('')}

        <div style="display:flex;gap:8px;margin-top:16px;">
          <button class="btn btn-primary" onclick="markStepComplete(4); navigateStep(5);">✅ 确认，进入步骤 5（数据验证）</button>
        </div>
      </div>
    `;
  } catch (e) {
    wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${e.message}</p></div>`;
  }
  highlightStep(4);
}

// ── Step 5: 系统数据验证 ──
async function renderStep5() {
  const wa = document.getElementById('work-area');
  showLoading('work-area');

  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/step5?trend_id=${state.trendId}`);
    const data = await res.json();
    if (!data.ok) { wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${data.error}</p></div>`; return; }
    state.stepResults.step5 = data;

    const stocks = data.stocks || [];
    wa.innerHTML = `
      <div class="card" id="step5-card">
        <h2>📊 步骤 5：系统数据验证</h2>
        <p>对 ${data.total_verified} 只候选股票调用 Project-Hermes-Stock 财务评分 + RPS + 技术面。</p>

        <table class="data-table">
          <thead>
            <tr>
              <th>代码</th><th>名称</th><th>现价</th>
              <th>5日</th><th>20日</th><th>60日</th>
              <th>总分</th><th>全市场排名</th>
              <th>盈利</th><th>成长</th><th>营运</th><th>现金流</th><th>偿债</th><th>资产</th>
            </tr>
          </thead>
          <tbody>
            ${stocks.map(s => {
              const ds = s.dim_scores || {};
              const rankStr = s.market_rank ? `${s.market_rank}/${s.market_total}` : '—';
              const closeVal = s.close != null ? s.close.toFixed(2) : '—';
              const chg5 = s.change_5d != null ? (s.change_5d >= 0 ? '+' : '') + s.change_5d + '%' : '—';
              const chg20 = s.change_20d != null ? (s.change_20d >= 0 ? '+' : '') + s.change_20d + '%' : '—';
              const chg60 = s.change_60d != null ? (s.change_60d >= 0 ? '+' : '') + s.change_60d + '%' : '—';
              const chgColor = (v) => v == null ? 'var(--text-muted)' : v >= 0 ? 'var(--green)' : 'var(--red)';
              return `
                <tr>
                  <td style="font-weight:600;">${s.code}</td>
                  <td>
                    <a href="/stock-score.html?symbol=${s.code}&market=${s.market}" target="_blank"
                       style="color:var(--accent2);text-decoration:none;cursor:pointer;"
                       title="跳转财务评分页面">
                      ${s.name || '—'}
                    </a>
                    ${s.concept_risk === 'high' ? '<span style="color:var(--red);font-size:10px;">⚠️概念股风险</span>' : s.concept_risk === 'medium' ? '<span style="color:var(--yellow);font-size:10px;">⚠️需验证</span>' : ''}
                  </td>
                  <td style="font-weight:600;cursor:pointer;color:var(--accent2);text-decoration:underline;text-decoration-style:dotted;text-underline-offset:4px;"
                      onclick="openBottleneckKline('${s.market}','${s.code}')"
                      title="点击查看 K 线图">
                    ${closeVal}
                  </td>
                  <td style="color:${chgColor(s.change_5d)};font-weight:600;">${chg5}</td>
                  <td style="color:${chgColor(s.change_20d)};font-weight:600;">${chg20}</td>
                  <td style="color:${chgColor(s.change_60d)};font-weight:600;">${chg60}</td>
                  <td style="font-weight:700;color:${(s.total_score||0)>=60?'var(--green)':(s.total_score||0)>=40?'var(--yellow)':'var(--red)'}">
                    ${s.total_score || '—'}
                  </td>
                  <td>${rankStr}</td>
                  <td style="color:${(ds.profitability||0)>=15?'var(--green)':(ds.profitability||0)>=8?'var(--yellow)':'var(--text-muted)'}">${ds.profitability||'—'}</td>
                  <td style="color:${(ds.growth||0)>=15?'var(--green)':(ds.growth||0)>=8?'var(--yellow)':'var(--text-muted)'}">${ds.growth||'—'}</td>
                  <td style="color:${(ds.operating||0)>=12?'var(--green)':(ds.operating||0)>=6?'var(--yellow)':'var(--text-muted)'}">${ds.operating||'—'}</td>
                  <td style="color:${(ds.cashflow||0)>=12?'var(--green)':(ds.cashflow||0)>=6?'var(--yellow)':'var(--text-muted)'}">${ds.cashflow||'—'}</td>
                  <td style="color:${(ds.solvency||0)>=8?'var(--green)':(ds.solvency||0)>=4?'var(--yellow)':'var(--text-muted)'}">${ds.solvency||'—'}</td>
                  <td style="color:${(ds.asset_quality||0)>=8?'var(--green)':(ds.asset_quality||0)>=4?'var(--yellow)':'var(--text-muted)'}">${ds.asset_quality||'—'}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>

        <p style="font-size:12px;color:var(--text-muted);margin-top:8px;">
          🟢 &ge;60 优秀 | 🟡 &ge;40 中等 | 🔴 &lt;40 弱 | 各维度分数含义同上（满分 25/20/15/10）
        </p>

        <div style="display:flex;gap:8px;margin-top:16px;">
          <button class="btn btn-primary" onclick="markStepComplete(5); navigateStep(6);">✅ 确认，进入步骤 6（交叉验证）</button>
        </div>
      </div>
    `;
  } catch (e) {
    wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${e.message}</p></div>`;
  }
  highlightStep(5);
}

// ── Step 6: Serenity 交叉验证 ──
async function renderStep6() {
  const wa = document.getElementById('work-area');
  showLoading('work-area');

  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/step6?trend_id=${state.trendId}`);
    const data = await res.json();
    if (!data.ok) { wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${data.error}</p></div>`; return; }
    state.stepResults.step6 = data;

    const checks = data.cross_checks || [];
    wa.innerHTML = `
      <div class="card" id="step6-card">
        <h2>🛡️ 步骤 6：Serenity 交叉验证（反方论证）</h2>
        <p style="color:var(--accent);font-weight:600;">
          「不需要找同意你的人，要反过来，专门等专家来反驳。」—— Serenity
        </p>
        <p>以下是对每个瓶颈层的「逻辑推翻条件」清单。当以下条件触发时，该瓶颈的投资逻辑需要重新评估。</p>

        ${checks.map(c => `
          <div style="margin:20px 0;padding:16px;border:1px solid var(--border);border-radius:10px;">
            <h3>
              L${c.level} — ${c.layer_name}
              <span class="badge badge-score">瓶颈度 ${'⭐'.repeat(c.bottleneck_score || 0)}</span>
            </h3>
            <p style="font-size:13px;">
              🌍 全球垄断：${c.global_monopoly || '—'} &nbsp;|&nbsp;
              🇨🇳 国产龙头：${c.domestic_leader || '—'}
            </p>
            <p style="font-size:12px;color:var(--text-muted);margin:4px 0;">
              全部候选：${(c.all_candidates || []).join(' / ')}
            </p>

            <h4 style="margin-top:12px;">⚠️ 逻辑推翻条件检查清单</h4>
            ${(c.key_risks || []).map(r => `
              <div class="risk-item">
                <div class="risk-q">🔍 ${r.question}</div>
                <div class="risk-trigger">📌 触发条件：${r.trigger}</div>
              </div>
            `).join('')}
          </div>
        `).join('')}

        <div style="display:flex;gap:8px;margin-top:16px;">
          <button class="btn btn-primary" onclick="markStepComplete(6); renderStep7();">✅ 确认，生成最终报告</button>
        </div>
      </div>
    `;
  } catch (e) {
    wa.innerHTML = `<div class="card"><h2>❌ 错误</h2><p>${e.message}</p></div>`;
  }
  highlightStep(6);
}

// ── Step 7: 最终报告 ──
async function renderStep7() {
  const wa = document.getElementById('work-area');
  showLoading('work-area');

  // 汇总所有步骤结果
  const s2 = state.stepResults.step2 || {};
  const s3 = state.stepResults.step3 || {};
  const s4 = state.stepResults.step4 || {};
  const s5 = state.stepResults.step5 || {};
  const s6 = state.stepResults.step6 || {};

  const bottlenecks = s3.bottlenecks || [];
  const stocks = s5.stocks || [];
  const mapped = s4.mapped_layers || [];
  const checks = s6.cross_checks || [];
  const trendName = s2.trend_name || state.trendId || '';

  const now = new Date();
  const ts = now.toLocaleString('zh-CN');

  wa.innerHTML = `
    <div class="card report-card" id="step7-card">
      <h2>📊 瓶颈股发现最终报告</h2>
      <p style="font-size:13px;color:var(--text-muted);">
        趋势：${trendName} &nbsp;|&nbsp; 分析时间：${ts}
      </p>

      <div class="summary-grid">
        <div class="summary-item"><div class="val">${s2.total_layers || 0}</div><div class="label">产业链层数</div></div>
        <div class="summary-item" style="border:1px solid var(--red);"><div class="val" style="color:var(--red);">${s3.bottleneck_count || 0}</div><div class="label">瓶颈层数</div></div>
        <div class="summary-item"><div class="val">${s5.total_verified || 0}</div><div class="label">验证标的数</div></div>
      </div>

      <!-- 瓶颈层列表 -->
      <h3>🔴 瓶颈层总览</h3>
      ${bottlenecks.map((b, idx) => `
        <div class="chain-layer bottleneck" style="margin-bottom:8px;">
          <div class="layer-num" style="color:var(--accent);font-weight:700;">#${idx+1}</div>
          <div class="layer-content">
            <div class="layer-name">
              L${b.level} — ${b.name}
              <span class="badge badge-bottleneck">卡脖子度 ${'⭐'.repeat(b.bottleneck_score||0)}</span>
            </div>
            <div class="layer-reason">${b.bottleneck_reason || ''}</div>
          </div>
        </div>
      `).join('')}

      <!-- 标的汇总 -->
      <h3>📈 关键标的系统评分</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th>优先级</th><th>代码</th><th>名称</th><th>现价</th>
            <th>5日</th><th>20日</th><th>60日</th>
            <th>总分</th><th>瓶颈环节</th><th>盈利</th><th>成长</th><th>现金流</th><th>偿债</th>
          </tr>
        </thead>
        <tbody>
          ${stocks.slice(0, 15).map((s, idx) => {
            const ds = s.dim_scores || {};
            const closeVal = s.close != null ? s.close.toFixed(2) : '—';
            const chg5 = s.change_5d != null ? (s.change_5d >= 0 ? '+' : '') + s.change_5d + '%' : '—';
            const chg20 = s.change_20d != null ? (s.change_20d >= 0 ? '+' : '') + s.change_20d + '%' : '—';
            const chg60 = s.change_60d != null ? (s.change_60d >= 0 ? '+' : '') + s.change_60d + '%' : '—';
            const chgColor = (v) => v == null ? 'var(--text-muted)' : v >= 0 ? 'var(--green)' : 'var(--red)';
            return `
              <tr>
                <td>${idx < 3 ? '🥇🥈🥉'[idx] : idx+1}</td>
                <td style="font-weight:600;"><a href="/stock-score.html?symbol=${s.code}&market=${s.market}" style="color:var(--accent2);" target="_blank">${s.code}</a></td>
                <td>
                  <a href="/stock-score.html?symbol=${s.code}&market=${s.market}" target="_blank"
                     style="color:var(--accent2);text-decoration:none;" title="跳转财务评分页面">
                    ${s.name || '—'}
                  </a>
                </td>
                <td style="font-weight:600;cursor:pointer;color:var(--accent2);text-decoration:underline;text-decoration-style:dotted;text-underline-offset:4px;"
                    onclick="openBottleneckKline('${s.market}','${s.code}')"
                    title="点击查看 K 线图">
                  ${closeVal}
                </td>
                <td style="color:${chgColor(s.change_5d)};font-weight:600;">${chg5}</td>
                <td style="color:${chgColor(s.change_20d)};font-weight:600;">${chg20}</td>
                <td style="color:${chgColor(s.change_60d)};font-weight:600;">${chg60}</td>
                <td style="font-weight:700;color:${(s.total_score||0)>=60?'var(--green)':(s.total_score||0)>=40?'var(--yellow)':'var(--red)'}">${s.total_score||'—'}</td>
                <td style="font-size:11px;">${(s.layers||[]).join(' / ')}</td>
                <td>${ds.profitability||'—'}</td>
                <td>${ds.growth||'—'}</td>
                <td>${ds.cashflow||'—'}</td>
                <td>${ds.solvency||'—'}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>

      <!-- 反方论证摘要 -->
      <h3>🛡️ 反方论证核心风险</h3>
      <div style="font-size:13px;color:var(--text-muted);line-height:1.7;">
        ${checks.map(c => (c.key_risks || []).slice(0, 2).map(r =>
          `<div class="risk-item"><div class="risk-q">🔍 L${c.level} ${c.layer_name}：${r.question}</div></div>`
        ).join('')).join('')}
      </div>

      <!-- 一句话结论 -->
      <div class="final-conclusion">
        <strong>💡 一句话结论：</strong><br>
        ${bottlenecks.length > 0
          ? `在「${trendName}」这条趋势中，${bottlenecks.map(b => b.name).join('、')} 是最核心的「紫苏叶」环节——全球被寡头垄断，国产仅有极少玩家能量产。`
          : '未发现符合 Serenity 标准的完美瓶颈层。建议扩大搜索范围或调整趋势方向。'}
        <br><br>
        <span style="font-size:13px;color:var(--text-muted);">
          ⚠️ 以上分析基于产业链逻辑和系统数据，不构成投资建议。
          每个瓶颈层的逻辑可能因技术路线变更、竞争格局变化、政策转向而被推翻。
        </span>
      </div>

      <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap;">
        <button class="btn btn-primary" onclick="saveCurrentReport()">💾 保存报告</button>
        <button class="btn btn-accent2" onclick="exportReport()">📥 导出 JSON</button>
        <button class="btn" onclick="startAuto()">🔄 重新分析</button>
      </div>
    </div>
  `;

  markStepComplete(7);
  highlightStep(7);

  // 保存 step7 结果以便后续保存
  state.stepResults.step7 = {
    timestamp: ts,
    trend_name: trendName,
    bottleneck_count: s3.bottleneck_count || 0,
    total_stocks: s5.total_verified || 0,
  };
}

// ── 保存报告 ──
async function saveCurrentReport() {
  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/save-report`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trend_id: state.trendId,
        step_results: state.stepResults,
      }),
    });
    const data = await res.json();
    if (data.ok) {
      alert(`✅ 报告已保存！\n文件：${data.filename}\n时间：${data.created_at}`);
      loadHistory();
    } else {
      alert('保存失败: ' + (data.error || '未知错误'));
    }
  } catch (e) {
    alert('保存失败: ' + e.message);
  }
}

// ── 导出 JSON ──
function exportReport() {
  const blob = new Blob([JSON.stringify(state.stepResults, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `bottleneck_${state.trendId || 'report'}_${new Date().toISOString().slice(0,10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── 一键全自动 ──
async function startAuto() {
  if (!state.trendId) {
    // 还没有选择趋势，先跳到步骤1
    renderStep1();
    highlightStep(1);
    return;
  }

  if (!confirm(`将对「${state.trendId}」执行全自动分析（约 10-30 秒），是否继续？`)) return;

  const wa = document.getElementById('work-area');
  wa.innerHTML = `<div class="card"><h2>⚡ 一键全自动执行中...</h2>
    <div id="auto-progress" style="margin-top:16px;"></div>
  </div>`;

  const progress = document.getElementById('auto-progress');

  try {
    const res = await fetch(`${API_BASE}/api/bottleneck/auto?trend_id=${state.trendId}`);
    progress.innerHTML += '<div class="status-done">✅ 分析完成，正在渲染结果...</div>';

    const data = await res.json();
    if (!data.ok) {
      progress.innerHTML += `<div class="status-error">❌ ${data.error}</div>`;
      return;
    }

    const results = data.results || {};
    state.stepResults = results;

    // 渲染所有步骤
    for (let i = 1; i <= 7; i++) {
      if (results['step' + i]) {
        progress.innerHTML += `<div class="status-done">✅ 步骤 ${i} 完成</div>`;
      }
    }

    // 渲染最终报告
    renderStep7();
    markAllComplete();
    highlightStep(7);

  } catch (e) {
    progress.innerHTML += `<div class="status-error">❌ 自动执行失败: ${e.message}</div>`;
  }
}

// ── 初始化 ──
init();

// ── 轮询自定义趋势 AI 拆解状态 ──
async function pollCustomStatus(sessionId) {
  let attempts = 0;
  const maxAttempts = 240;  // up to 20 min (240 × 5s)

  const check = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/bottleneck/custom-status?session_id=${sessionId}`);
      const data = await res.json();

      if (data.status === 'done') {
        // 构造 step2 数据
        const aiType = data.type || 'custom_ai';
        const isRuleBased = !!(data.trend_name && data.trend_name.includes('规则引擎')) || aiType === 'rule_based';
        const sourceTag = isRuleBased ? '⚙️ 规则引擎' : '🤖 AI 生成';
        const step2Data = {
          ok: true, type: 'custom_ai',
          trend_name: data.trend_name || '',
          trend_id: state.trendId,
          description: state.stepResults.custom_description || '',
          anchor: data.anchor || '',
          total_layers: data.total_layers || 0,
          layers: data.layers || [],
          _source: sourceTag,
        };
        state.stepResults.step2 = step2Data;

        // 构造瓶颈层数据给 step3 用
        const bottlenecks = (data.layers || []).filter(l => l.is_bottleneck).map(l => ({
          level: l.level, name: l.name,
          supplier_count: l.supplier_count,
          is_bottleneck: true,
          bottleneck_level: l.bottleneck_level || '🔴 核心瓶颈',
          bottleneck_score: l.bottleneck_score || 0,
          bottleneck_reason: l.bottleneck_reason || '',
        }));
        state.stepResults.step3 = {
          ok: true,
          trend_name: data.trend_name || '',
          total_layers: data.total_layers || 0,
          bottleneck_count: data.bottleneck_count || 0,
          all_layers: (data.layers || []).map(l => ({ level: l.level, name: l.name, supplier_count: l.supplier_count, is_bottleneck: l.is_bottleneck, bottleneck_level: l.bottleneck_level, bottleneck_score: l.bottleneck_score, bottleneck_reason: l.bottleneck_reason, skip_reason: l.skip_reason })),
          bottlenecks: bottlenecks,
          summary: `AI 拆解完成：${data.total_layers || 0} 层产业链，识别 ${data.bottleneck_count || 0} 个瓶颈层`,
        };

        // 构造 step4 数据（含候选股票）
        const mappedLayers = (data.layers || []).filter(l => l.is_bottleneck && l.a_share_candidates?.length > 0).map(l => ({
          level: l.level, name: l.name,
          bottleneck_level: l.bottleneck_level || '',
          bottleneck_score: l.bottleneck_score || 0,
          bottleneck_reason: l.bottleneck_reason || '',
          show_all: true,
          total_stocks: (l.a_share_candidates || []).length,
          stocks: (l.a_share_candidates || []).map(c => typeof c === 'object' ? { code: c.code, name: c.name || '' } : { code: c, name: '' }),
          remaining: 0,
        }));
        state.stepResults.step4 = { ok: true, trend_name: data.trend_name || '', mapped_layers: mappedLayers };

        // 渲染产业链
        renderStep2();
        markStepComplete(2);
        markStepComplete(3);
        highlightStep(2);
        return;
      }

      if (data.status === 'error') {
        const errMsg = data.error || '未知错误';
        const wa = document.getElementById('work-area');
        wa.innerHTML = `
          <div class="card">
            <h2>❌ AI 拆解失败</h2>
            <p>${errMsg}</p>
            <p style="font-size:13px;color:var(--text-muted);">💡 建议使用预置趋势或简化描述后重试。</p>
            <button class="btn" onclick="renderStep1();">← 返回重新选择</button>
          </div>
        `;
        return;
      }

      // still processing - update status log
      attempts++;
      if (attempts < maxAttempts) {
        const elapsed = attempts * 5;  // polling every 5s now
        const statusLog = document.getElementById('ai-status-log');
        const messages = [
          '🔍 确定终端需求和应用场景...',
          '🔗 向上追溯产业链上游环节...',
          '🏭 识别每个环节的供应商格局...',
          '🔴 标记供应商≤2家的瓶颈层...',
          '📊 分析供需缺口和竞争壁垒...',
          '🧠 综合 Serenity 方法论评估...',
        ];
        const msgIdx = Math.min(Math.floor(attempts / 8), messages.length - 1);
        if (statusLog) {
          const dots = '.'.repeat((attempts % 3) + 1);
          statusLog.innerHTML = `
            <div style="padding:4px 0;color:var(--accent2);">${messages[msgIdx]}${dots}</div>
            <div style="padding:4px 0;font-size:11px;">⏱ ${elapsed}秒</div>
          `;
        }
        setTimeout(check, 5000);  // poll every 5s instead of 2s
      } else {
        const wa = document.getElementById('work-area');
        wa.innerHTML = `
          <div class="card">
            <h2>⏱️ AI 拆解超时</h2>
            <p>等待超过 5 分钟仍未完成。</p>
            <p style="font-size:13px;color:var(--text-muted);">💡 可能原因：趋势描述过于复杂或 AI 模型当前负载较高。建议：</p>
            <ul style="font-size:13px;color:var(--text-muted);">
              <li>使用预置趋势（AI算力国产化 / 人形机器人 / 先进封装）</li>
              <li>简化趋势描述后重试</li>
            </ul>
            <button class="btn" onclick="renderStep1();">← 返回重新选择</button>
          </div>
        `;
      }
    } catch (e) {
      attempts++;
      if (attempts < maxAttempts) setTimeout(check, 2000);
    }
  };
  setTimeout(check, 3000);
}

// ── K-line Chart Dialog (shared with stock-score page) ──

async function openBottleneckKline(market, symbol) {
  const dialog = document.getElementById('kline-chart-dialog');
  const title = document.getElementById('kline-chart-title');
  const svg = document.getElementById('kline-chart-svg');
  if (!dialog || !title || !svg) return;

  dialog.hidden = false;
  dialog.setAttribute('aria-hidden', 'false');
  title.textContent = `${symbol} — 加载中…`;

  try {
    const [klineRes, rpsRes] = await Promise.all([
      fetch(`/api/stock-kline?symbol=${encodeURIComponent(symbol)}&limit=300`),
      fetch(`/api/stock-rps-history?symbol=${encodeURIComponent(symbol)}`),
    ]);
    const klineJson = await klineRes.json();
    const rpsJson = await rpsRes.json();

    if (!klineJson.ok) {
      title.textContent = `${symbol} — 数据不可用`;
      return;
    }

    const bars = klineJson.bars || [];
    const rpsHistory = (rpsJson.history || []).map(h => ({
      trading_day: h.trading_day,
      rps_20: h.rps_20,
      rps_50: h.rps_50,
      rps_120: h.rps_120,
      rps_250: h.rps_250,
    }));

    const stockName = bars[0]?.name || symbol;
    if (!scoreKlineChart) {
      scoreKlineChart = new KlineChart(svg, { marginRight: 20 });
    }
    scoreKlineChart.load(bars, rpsHistory, 250);
    title.textContent = `${symbol} ${stockName}`;
  } catch (e) {
    console.error('Kline dialog error:', e);
    title.textContent = `${symbol} — 加载失败`;
  }
}

function closeBottleneckKline() {
  const dialog = document.getElementById('kline-chart-dialog');
  if (dialog) {
    dialog.hidden = true;
    dialog.setAttribute('aria-hidden', 'true');
  }
}

// Bind events when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('kline-chart-close')?.addEventListener('click', closeBottleneckKline);
  document.getElementById('kline-chart-dialog')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeBottleneckKline();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeBottleneckKline();
  });
});

// Expose to global scope for onclick attributes
window.openBottleneckKline = openBottleneckKline;
window.closeBottleneckKline = closeBottleneckKline;
