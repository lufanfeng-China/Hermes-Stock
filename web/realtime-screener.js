import { KlineChart } from './kline-chart.js';

/**
 * 方案配置 — 模块化条件系统
 * 每个方案 = 一个或多个模块，每个模块可独立激活/禁用
 * 每个条件 = 名称 + 标签 + 类型 + 默认值 + 启用开关（可选）
 *
 * 新增方案：在这里加一项，HTML 会自动生成对应模块 UI
 */
const REALTIME_SCENARIOS = {
  tail_session: {
    key: 'tail_session',
    label: '尾盘选股',
    modules: [
      {
        id: 'basic',
        label: '基础条件',
        enabled: true,
        conditions: [
          {
            name: 'gain_pct',
            label: '涨幅范围',
            type: 'range',
            min: { value: 3, step: 0.1, suffix: '%' },
            max: { value: 5, step: 0.1, suffix: '%' },
            enableName: 'enable_gain_pct',
          },
          {
            name: 'limit_up_lookback_days',
            label: 'N天内涨停',
            type: 'value',
            value: { value: 20, step: 1, suffix: '天' },
            enableName: 'enable_limit_up_lookback_days',
          },
          {
            name: 'min_volume_ratio',
            label: '量比 ≥',
            type: 'value',
            value: { value: 1.4, step: 0.1, suffix: '' },
            enableName: 'enable_min_volume_ratio',
          },
          {
            name: 'max_market_cap_yi',
            label: '市值 ≤',
            type: 'value',
            value: { value: 200, step: 1, suffix: '亿' },
            enableName: 'enable_max_market_cap_yi',
          },
          {
            name: 'turnover_pct',
            label: '换手率范围',
            type: 'range',
            min: { value: 5, step: 0.1, suffix: '%' },
            max: { value: 10, step: 0.1, suffix: '%' },
            enableName: 'enable_turnover_pct',
          },
          {
            name: 'intraday_above_vwap',
            label: '分时价格在VWAP上方时间占比 ≥',
            type: 'value',
            value: { value: 80, step: 1, suffix: '%' },
            enableName: 'enable_intraday_above_vwap',
          },
          {
            name: 'intraday_vwap_max_breach_pct',
            label: '允许短暂跌破不超过',
            type: 'value',
            value: { value: 0.3, step: 0.1, suffix: '%' },
          },
          {
            name: 'current_above_open',
            label: '当前价高于开盘价',
            type: 'toggle',
            value: true,
            enableName: 'enable_current_above_open',
          },
        ],
      },
    ],
  },

  rps_pullback: {
    key: 'rps_pullback',
    label: 'RPS回踩',
    modules: [
      {
        id: 'basic',
        label: '基础条件',
        enabled: true,
        conditions: [
          {
            name: 'rps250_min',
            label: 'RPS250 ≥',
            type: 'value',
            value: { value: 80, step: 1, suffix: '' },
          },
          {
            name: 'rps120_min',
            label: 'RPS120 ≥',
            type: 'value',
            value: { value: 85, step: 1, suffix: '' },
          },
          {
            name: 'rps50_min',
            label: 'RPS50 ≥',
            type: 'value',
            value: { value: 88, step: 1, suffix: '' },
          },
          {
            name: 'rps20_min',
            label: 'RPS20 ≥',
            type: 'value',
            value: { value: 92, step: 1, suffix: '' },
          },
          {
            name: 'volume_ratio_min',
            label: '量比（放量倍数）≥',
            type: 'value',
            value: { value: 1.2, step: 0.1, suffix: '' },
          },
          {
            name: 'overheat_ratio_max',
            label: '过热阈值（收盘/MA20）<',
            type: 'value',
            value: { value: 1.08, step: 0.01, suffix: '' },
          },
        ],
      },
    ],
  },

  scheme_2560: {
    key: 'scheme_2560',
    label: '2560',
    modules: [
      // ── 模块1：基础条件 ───────────────────────────────────────────
      {
        id: 'basic',
        label: '基础条件',
        enabled: true,
        conditions: [
          {
            name: 'min_listed_days',
            label: '上市满 N 交易日',
            type: 'value',
            value: { value: 120, step: 1, suffix: '天' },
          },
          {
            name: 'min_amount_20d_yi',
            label: '20日日均成交额 ≥',
            type: 'value',
            value: { value: 1, step: 0.1, suffix: '亿' },
          },
          {
            name: 'min_price',
            label: '股价 ≥',
            type: 'value',
            value: { value: 5, step: 0.1, suffix: '元' },
          },

          {
            name: 'gain_20d_max_pct',
            label: '20日涨幅 ≤',
            type: 'value',
            value: { value: 35, step: 1, suffix: '%' },
          },

          {
            name: 'price_ma25_range_pct',
            label: 'C/MA25 - 1 范围上限',
            type: 'value',
            value: { value: 8, step: 0.1, suffix: '%' },
          },
          {
            name: 'vol_ratio_5d_60d_min',
            label: '5日量/60日量 下限',
            type: 'value',
            value: { value: 1.15, step: 0.01, suffix: '' },
          },
          {
            name: 'vol_ratio_5d_60d_max',
            label: '5日量/60日量 上限',
            type: 'value',
            value: { value: 2.5, step: 0.1, suffix: '' },
          },
        ],
      },

      // ── 模块2：回踩买点* ──────────────────────────────────────────
      {
        id: 'pullback_buy',
        label: '回踩买点*',
        enabled: true,
        conditions: [
          {
            name: 'pb_trend_ma25_5d',
            label: '趋势：MA25/5日前MA25 - 1 ≥',
            type: 'value',
            value: { value: 0.5, step: 0.1, suffix: '%' },
          },
          {
            name: 'pb_vol_ratio_min',
            label: '量能：5日量/60日量 下限',
            type: 'value',
            value: { value: 1.15, step: 0.01, suffix: '' },
          },
          {
            name: 'pb_vol_ratio_max',
            label: '量能：5日量/60日量 上限',
            type: 'value',
            value: { value: 2.5, step: 0.1, suffix: '' },
          },
          {
            name: 'pb_low_max_ma25_pct',
            label: '回踩位置：最低价 ≤ MA25 ×',
            type: 'value',
            value: { value: 1.03, step: 0.001, suffix: '' },
          },

          {
            name: 'pb_low_min_ma25_pct',
            label: '跌破幅度限制：最低价 ≥ MA25 ×',
            type: 'value',
            value: { value: 0.97, step: 0.001, suffix: '' },
          },

          {
            name: 'pb_price_ma25_max_pct',
            label: '距离25日线：C/MA25 - 1 ≤',
            type: 'value',
            value: { value: 5, step: 0.1, suffix: '%' },
          },
        ],
      },

      // ── 模块3：突破买点 ───────────────────────────────────────────
      {
        id: 'breakout_buy',
        label: '突破买点',
        enabled: false,
        conditions: [
          {
            name: 'bo_range_10d_max_pct',
            label: '10日振幅 ≤',
            type: 'value',
            value: { value: 12, step: 0.1, suffix: '%' },
          },
          {
            name: 'bo_vol_drop_min_pct',
            label: '近5日量比前5日低 ≥',
            type: 'value',
            value: { value: 15, step: 1, suffix: '%' },
          },
          {
            name: 'bo_close_break_ratio',
            label: '收盘突破：C ≥ 近10日最高 ×',
            type: 'value',
            value: { value: 1.01, step: 0.001, suffix: '' },
          },
          {
            name: 'bo_vol_burst_min',
            label: '放量：当日量 ≥ 近5日均量 ×',
            type: 'value',
            value: { value: 1.3, step: 0.1, suffix: '' },
          },
          {
            name: 'bo_vol_burst_max',
            label: '不能爆量：当日量 ≤ 60日均量 ×',
            type: 'value',
            value: { value: 3, step: 0.1, suffix: '' },
          },
          {
            name: 'bo_price_ma25_max_pct',
            label: '距离25日线：C/MA25 - 1 ≤',
            type: 'value',
            value: { value: 10, step: 0.1, suffix: '%' },
          },
          {
            name: 'bo_ma25_trend_up',
            label: '25日线向上：MA25/5日前MA25 - 1 ≥',
            type: 'value',
            value: { value: 0.5, step: 0.1, suffix: '%' },
          },
        ],
      },

      // ── 模块4：强势回踩 ──────────────────────────────────────────
      {
        id: 'strong_pullback',
        label: '强势回踩',
        enabled: false,
        conditions: [
          {
            name: 'sp_gain_30d_min_pct',
            label: '近30日涨幅 下限',
            type: 'value',
            value: { value: 20, step: 1, suffix: '%' },
          },
          {
            name: 'sp_gain_30d_max_pct',
            label: '近30日涨幅 上限',
            type: 'value',
            value: { value: 60, step: 1, suffix: '%' },
          },
          {
            name: 'sp_above_ma25_days',
            label: '近20日中收盘在MA25上方天数 ≥',
            type: 'value',
            value: { value: 20, step: 1, suffix: '天' },
          },
          {
            name: 'sp_recent_revert_max_pct',
            label: '最近3日内第一次回到MA25 ×',
            type: 'value',
            value: { value: 1.03, step: 0.001, suffix: '' },
          },
          {
            name: 'sp_low_min_ma25_pct',
            label: '回踩幅度：最低价 ≥ MA25 ×',
            type: 'value',
            value: { value: 0.97, step: 0.001, suffix: '' },
          },
          {
            name: 'sp_vol_shrink_max_ratio',
            label: '缩量：当日量 ≤ 近5日最大量 ×',
            type: 'value',
            value: { value: 0.7, step: 0.05, suffix: '' },
          },
          {
            name: 'sp_vol_ratio_min',
            label: '量能基础：5日量/60日量 ≥',
            type: 'value',
            value: { value: 1.15, step: 0.01, suffix: '' },
          },
        ],
      },
    ],
  },
};

// ─── DOM refs ────────────────────────────────────────────────────────────────

let monitorTimer = null;
let klineChart = null;
let currentKlinePreset = 60;
let monitorMode = 'stopped';
let scenarioLoaded = false;

const scenarioSelectEl = document.getElementById('realtime-scenario-select');
const loadScenarioBtn = document.getElementById('realtime-load-scenario');
const modulesContainerEl = document.getElementById('modules-container');
const conditionSummaryEl = document.getElementById('realtime-condition-summary');
const refreshSecondsEl = document.getElementById('realtime-refresh-seconds');
const startMonitorBtn = document.getElementById('realtime-start-monitor');
const stopMonitorBtn = document.getElementById('realtime-stop-monitor');
const statusEl = document.getElementById('realtime-status');
const tbody = document.getElementById('realtime-results-tbody');
const matchCountEl = document.getElementById('realtime-match-count');
const pageInfoEl = document.getElementById('realtime-page-info');

// ─── Helpers ─────────────────────────────────────────────────────────────────

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatNumber(value, digits = 2) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}

function formatPercent(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(2)}%`;
}

function formatMarketCapYi(value) {
  if (value == null || value === '' || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(1)}亿`;
}

function formatRank(rank, total) {
  const rankNum = Number(rank);
  if (!Number.isFinite(rankNum) || rankNum <= 0) return '—';
  const totalNum = Number(total);
  if (!Number.isFinite(totalNum) || totalNum <= 0) return String(Math.trunc(rankNum));
  return `${Math.trunc(rankNum)} / ${Math.trunc(totalNum)}`;
}

function getTradingSessionMinutes(now = new Date()) {
  const day = now.getDay();
  if (day === 0 || day === 6) return -1;
  return now.getHours() * 60 + now.getMinutes();
}

function isWithinChinaAShareTradingPeriod(now = new Date()) {
  const m = getTradingSessionMinutes(now);
  if (m < 0) return false;
  return (m >= 9 * 60 + 30 && m < 11 * 60 + 30) || (m >= 13 * 60 && m < 15 * 60);
}

function syncConditionToggleDisabledState(scope = modulesContainerEl) {
  scope.querySelectorAll('.condition-toggle').forEach((label) => {
    const input = label.querySelector('input[type="checkbox"]');
    const disabled = Boolean(input?.disabled);
    label.classList.toggle('is-disabled', disabled);
    label.setAttribute('aria-disabled', disabled ? 'true' : 'false');
  });
}

// ─── Module UI Builder ────────────────────────────────────────────────────────

/**
 * 根据 REALTIME_SCENARIOS 配置动态构建模块 UI
 * 每个方案有 1~N 个模块，每个模块可折叠
 */
function buildModulesUI(scenario) {
  modulesContainerEl.innerHTML = '';

  for (const mod of scenario.modules) {
    // Module card
    const card = document.createElement('div');
    card.className = 'module-card';
    card.dataset.moduleId = mod.id;

    // Module header: toggle + label + collapse
    const header = document.createElement('div');
    header.className = 'module-header';

    const toggleWrap = document.createElement('label');
    toggleWrap.className = 'module-toggle';
    toggleWrap.innerHTML = `
      <input type="checkbox" class="module-enable-check" name="enable_module_${mod.id}" data-module="${mod.id}" ${mod.enabled ? 'checked' : ''}>
      <span class="toggle-slider"></span>
    `;

    const label = document.createElement('span');
    label.className = 'module-title';
    label.textContent = mod.label;

    const collapseBtn = document.createElement('button');
    collapseBtn.type = 'button';
    collapseBtn.className = 'module-collapse-btn';
    collapseBtn.dataset.module = mod.id;
    collapseBtn.textContent = '−';
    collapseBtn.title = '折叠模块';

    header.appendChild(toggleWrap);
    header.appendChild(label);
    header.appendChild(collapseBtn);

    // Module body: condition rows
    const body = document.createElement('div');
    body.className = 'module-body';
    body.dataset.module = mod.id;

    for (const cond of mod.conditions) {
      const row = buildConditionRow(cond, scenario.key);
      body.appendChild(row);
    }

    card.appendChild(header);
    card.appendChild(body);
    modulesContainerEl.appendChild(card);
  }

  // Bind module-level events
  // Note: the native <input type=checkbox> is visually hidden (width=0/height=0).
  // Clicking the parent <label> (the visible toggle) should toggle the hidden input.
  // We intercept the label click to ensure browser native toggle + our change handler work together.
  modulesContainerEl.querySelectorAll('.module-enable-check').forEach((check) => {
    const label = check.parentElement;
    if (label) {
      label.addEventListener('click', (e) => {
        // Prevent native label→checkbox toggle; use our own programmatic toggle
        e.preventDefault();
        check.checked = !check.checked;
        // Fire our change handler manually
        check.dispatchEvent(new Event('change', { bubbles: true }));
      });
    }
    check.addEventListener('change', (e) => {
      const modId = e.target.dataset.module;
      const card = modulesContainerEl.querySelector(`[data-module-id="${modId}"]`);
      if (card) {
        card.classList.toggle('module-disabled', !e.target.checked);
        // Disable ALL inputs in the module body (number, text, select, checkbox)
        card.querySelector('.module-body').querySelectorAll('input').forEach((el) => {
          el.disabled = !e.target.checked;
        });
        syncConditionToggleDisabledState(card);
      }
    });
  });

  modulesContainerEl.querySelectorAll('.module-collapse-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const modId = e.target.dataset.module;
      const card = modulesContainerEl.querySelector(`[data-module-id="${modId}"]`);
      const body = card?.querySelector('.module-body');
      if (!body) return;
      const collapsed = body.classList.toggle('module-body-collapsed');
      e.target.textContent = collapsed ? '+' : '−';
      e.target.title = collapsed ? '展开模块' : '折叠模块';
    });
  });

  // Apply initial enabled state
  modulesContainerEl.querySelectorAll('.module-enable-check').forEach((check) => {
    const modId = check.dataset.module;
    const card = modulesContainerEl.querySelector(`[data-module-id="${modId}"]`);
    if (card && !check.checked) {
      card.classList.add('module-disabled');
      // Disable ALL inputs in the module body (number, text, select, checkbox)
      card.querySelector('.module-body').querySelectorAll('input').forEach((el) => {
        el.disabled = true;
      });
    }
  });
  syncConditionToggleDisabledState();

  // Intercept clicks on .condition-enable labels (visible toggle track/thumb)
  // The actual <input type=checkbox> is hidden (width=0); clicks on the visible
  // .cond-enable-track span should toggle the hidden input. We intercept to prevent
  // double-toggle: browser native label→checkbox fires first, then our click handler
  // fires — stopImmediatePropagation blocks the second firing so net effect = 1 toggle.
  modulesContainerEl.querySelectorAll('.condition-enable').forEach((label) => {
    const input = label.querySelector('input[type="checkbox"]');
    if (!input) return;
    label.addEventListener('click', (e) => {
      if (e.target === input) return; // native direct input click — let it through
      e.stopImmediatePropagation(); // prevent browser's label→checkbox native mechanism
      e.preventDefault();
      input.checked = !input.checked;
    });
  });
}

/**
 * 构建单个条件行
 * type: 'value' | 'range' | 'toggle'
 * value/range: { value: {value, step, suffix}, [min], [max] }
 * toggle: { value: true/false }
 */
function buildConditionRow(cond, scenarioKey) {
  const row = document.createElement('div');
  row.className = 'condition-row';

  if (cond.type === 'range') {
    // Range: [label] [enable?] [min] - [max]
    row.innerHTML = `
      <label class="condition-label">${escapeHtml(cond.label)}</label>
      ${cond.enableName ? `
        <label class="condition-enable">
          <input type="checkbox" name="${cond.enableName}" data-scenario="${scenarioKey}" checked>
          <span class="cond-enable-track"><span class="cond-enable-thumb"></span></span>
        </label>` : ''}
      <label class="condition-input"><input name="${cond.name}_min" type="number" step="${cond.min.step}" value="${cond.min.value}"><span class="input-suffix">${cond.min.suffix || ''}</span></label>
      <span class="range-sep">—</span>
      <label class="condition-input"><input name="${cond.name}_max" type="number" step="${cond.max.step}" value="${cond.max.value}"><span class="input-suffix">${cond.max.suffix || ''}</span></label>
    `;
  } else if (cond.type === 'value') {
    // Single value: [label] [enable?] [input]
    row.innerHTML = `
      <label class="condition-label">${escapeHtml(cond.label)}</label>
      ${cond.enableName ? `
        <label class="condition-enable">
          <input type="checkbox" name="${cond.enableName}" data-scenario="${scenarioKey}" checked>
          <span class="cond-enable-track"><span class="cond-enable-thumb"></span></span>
        </label>` : ''}
      <label class="condition-input"><input name="${cond.name}" type="number" step="${cond.value.step}" value="${cond.value.value}"><span class="input-suffix">${cond.value.suffix || ''}</span></label>
    `;
  } else if (cond.type === 'toggle') {
    // Toggle: [label] [enable?] [toggle switch]
    row.innerHTML = `
      <label class="condition-label">${escapeHtml(cond.label)}</label>
      ${cond.enableName ? `
        <label class="condition-enable">
          <input type="checkbox" name="${cond.enableName}" data-scenario="${scenarioKey}" checked>
          <span class="cond-enable-track"><span class="cond-enable-thumb"></span></span>
        </label>` : ''}
      <label class="condition-toggle">
        <input type="checkbox" name="${cond.name}" ${cond.value ? 'checked' : ''} data-scenario="${scenarioKey}">
        <span class="toggle-slider"></span>
      </label>
    `;
  }

  return row;
}

// ─── Scenario loading ─────────────────────────────────────────────────────────

function loadScenario() {
  // Honor ?scenario= URL param if present, otherwise fall back to select value
  const urlParams = new URLSearchParams(window.location.search);
  const paramScenario = urlParams.get('scenario');
  const scenarioKey = paramScenario || scenarioSelectEl.value;
  const scenario = REALTIME_SCENARIOS[scenarioKey] || REALTIME_SCENARIOS.tail_session;
  // Sync select to resolved value
  scenarioSelectEl.value = scenario.key;
  buildModulesUI(scenario);
  conditionSummaryEl.hidden = true;
  scenarioLoaded = true;
  statusEl.textContent = `已加载方案：${scenario.label}`;
}

// ─── Condition collection ─────────────────────────────────────────────────────

/**
 * 收集当前激活的条件名→值映射，供后端 API 调用
 */
function collectActiveConditions() {
  const params = {};
  for (const mod of modulesContainerEl.querySelectorAll('.module-card')) {
    const modEnableInput = mod.querySelector('.module-enable-check');
    const modEnabled = modEnableInput?.checked !== false;
    const modId = modEnableInput?.dataset.module;

    // Collect module-level enable flag (enable_module_{id})
    if (modId && modEnableInput?.name) {
      params[modEnableInput.name] = modEnabled ? 'true' : 'false';
    }
    if (!modEnabled) continue;

    for (const input of mod.querySelectorAll('.module-body input')) {
      const name = input.name;
      if (!name) continue;

      // Skip if disabled (parent module disabled)
      if (input.disabled) continue;

      // Range: name_min / name_max
      if (name.endsWith('_min') || name.endsWith('_max')) {
        const base = name.replace(/_min$|_max$/, '');
        const direction = name.endsWith('_min') ? 'min' : 'max';
        const enableName = `enable_${base}`;
        const enableCheck = mod.querySelector(`[name="${enableName}"]`);
        if (enableCheck && !enableCheck.checked) continue;
        if (!params[base]) params[base] = {};
        params[base][direction] = input.value;
      } else {
        // Regular field
        const enableName = `enable_${name}`;
        const enableCheck = mod.querySelector(`[name="${enableName}"]`);
        if (enableCheck && !enableCheck.checked) continue;
        params[name] = input.type === 'checkbox' ? (input.checked ? 'true' : 'false') : input.value;
      }
    }
  }
  return params;
}

/**
 * 从收集的 conditions 组装 URLSearchParams
 */
function buildConditionParams() {
  const params = new URLSearchParams();
  const conditions = collectActiveConditions();

  // Flatten into API param format
  for (const [name, val] of Object.entries(conditions)) {
    if (val && typeof val === 'object' && ('min' in val || 'max' in val)) {
      if ('min' in val) params.append(`${name}_min`, val.min);
      if ('max' in val) params.append(`${name}_max`, val.max);
    } else {
      params.append(name, String(val));
    }
  }

  return params;
}

function collectConditionPayload() {
  const params = buildConditionParams();
  params.set('scenario', scenarioSelectEl.value || 'tail_session');
  params.set('monitor', 'true');
  params.set('refresh_seconds', String(Number(refreshSecondsEl.value || 30)));
  return params;
}

// ─── Lock / unlock controls ───────────────────────────────────────────────────

function setConditionFormLocked(locked) {
  modulesContainerEl.querySelectorAll('input, select').forEach((el) => {
    el.disabled = locked;
  });
  scenarioSelectEl.disabled = locked;
  loadScenarioBtn.disabled = locked;
  refreshSecondsEl.disabled = locked;
  syncConditionToggleDisabledState();
}

// ─── Realtime monitor ─────────────────────────────────────────────────────────

function renderRealtimeLoading() {
  matchCountEl.textContent = '…';
  pageInfoEl.textContent = '正在刷新...';
    tbody.innerHTML = '<tr><td colspan="10" class="stock-score-empty-row">正在刷新实时选股结果...</td></tr>';
}

async function refreshRealtimeMatches() {
  renderRealtimeLoading();
  const params = collectConditionPayload();
  try {
    const response = await fetch(`/api/realtime-screener?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload?.error?.message || payload?.error || `HTTP ${response.status}`);
    }
    renderRealtimeRows(payload.rows || []);
    matchCountEl.textContent = String((payload.rows || []).length);
    pageInfoEl.textContent = `${payload.scenario_label || '实时方案'} · ${payload.data_note || '实时行情'}`;
    if (monitorMode === 'one-shot') {
      statusEl.textContent = '非交易时段 · 已抓取一次，暂停定时刷新';
    } else {
      statusEl.textContent = `监控中 · 每 ${payload.refresh_seconds || refreshSecondsEl.value || 30} 秒刷新`;
    }
  } catch (error) {
    statusEl.textContent = `实时选股失败：${error.message}`;
    pageInfoEl.textContent = '刷新失败';
    matchCountEl.textContent = '0';
    tbody.innerHTML = '<tr><td colspan="10" class="stock-score-empty-row">实时选股失败，请稍后重试</td></tr>';
  }
}

function startRealtimeMonitor() {
  if (!scenarioLoaded) {
    statusEl.textContent = '请先加载方案，再启动监控';
    return;
  }
  stopRealtimeMonitor({ silent: true });
  const seconds = Math.max(5, Number(refreshSecondsEl.value || 30));
  refreshSecondsEl.value = String(seconds);
  setConditionFormLocked(true);
  if (isWithinChinaAShareTradingPeriod()) {
    monitorMode = 'interval';
    statusEl.textContent = `监控中 · 每 ${seconds} 秒刷新`;
  } else {
    monitorMode = 'one-shot';
    statusEl.textContent = '非交易时段 · 正在抓取一次';
  }
  refreshRealtimeMatches();
  if (isWithinChinaAShareTradingPeriod()) {
    monitorTimer = setInterval(refreshRealtimeMatches, seconds * 1000);
  } else {
    monitorTimer = null;
  }
}

function stopRealtimeMonitor(options = {}) {
  if (monitorTimer) {
    clearInterval(monitorTimer);
    monitorTimer = null;
  }
  monitorMode = 'stopped';
  setConditionFormLocked(false);
  if (!options.silent) {
    statusEl.textContent = '监控已停止，可修改参数后重新启动';
  }
}

// ─── Results table ────────────────────────────────────────────────────────────

function renderRealtimeRows(rows) {
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="stock-score-empty-row">暂无满足条件的股票</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row) => {
    const marketSymbol = `${String(row.market || '').toUpperCase()}:${row.symbol || ''}`;
    const industryText = [row.industry_level_1, row.industry_level_2].filter(Boolean).join(' / ') || '—';
    const matchedMods = Array.isArray(row.matched_conditions) ? row.matched_conditions.join('、') : '';
    return `<tr class="realtime-row" tabindex="0"
      data-market="${escapeHtml(row.market)}"
      data-symbol="${escapeHtml(row.symbol)}"
      data-name="${escapeHtml(row.stock_name || row.symbol)}">
      <td><strong>${escapeHtml(row.stock_name || row.symbol)}</strong><span class="stock-screener-symbol">${escapeHtml(marketSymbol)}</span></td>
      <td class="num">${formatNumber(row.current_price, 2)}</td>
      <td class="num">${formatPercent(row.gain_pct)}</td>
      <td class="num">${formatNumber(row.volume_ratio, 2)}</td>
      <td class="num">${formatMarketCapYi(row.market_cap_yi)}</td>
      <td class="num">${formatPercent(row.turnover_pct)}</td>
      <td>${escapeHtml(industryText)}</td>
      <td class="num">${formatNumber(row.industry_total_score, 1)}</td>
      <td class="num">${escapeHtml(formatRank(row.industry_total_rank, row.industry_total_universe_size))}</td>
      <td class="matched-mods">${escapeHtml(matchedMods)}</td>
    </tr>`;
  }).join('');
}

// ─── K-line chart ────────────────────────────────────────────────────────────

async function loadRealtimeKline(row) {
  const symbol = row?.dataset?.symbol;
  const name = row?.dataset?.name || symbol;
  if (!symbol) return;
  document.querySelectorAll('.realtime-row').forEach((tr) => tr.classList.toggle('row-selected', tr === row));
  const klineSection = document.querySelector('#realtime-kline-section');
  const klineTitle = document.querySelector('#realtime-kline-title');
  if (klineSection) klineSection.classList.remove('hidden');
  if (klineTitle) klineTitle.textContent = `${symbol} — 加载中…`;
  try {
    const [klineRes, rpsRes] = await Promise.all([
      fetch(`/api/stock-kline?symbol=${encodeURIComponent(symbol)}&limit=300`),
      fetch(`/api/stock-rps-history?symbol=${encodeURIComponent(symbol)}`),
    ]);
    const klineJson = await klineRes.json();
    const rpsJson = await rpsRes.json();
    if (!klineJson.ok) {
      if (klineTitle) klineTitle.textContent = `${symbol} — 数据不可用`;
      return;
    }
    const bars = klineJson.bars || [];
    const rpsHistory = (rpsJson.history || []).map((h) => ({
      trading_day: h.trading_day,
      rps_20: h.rps_20,
      rps_50: h.rps_50,
      rps_120: h.rps_120,
      rps_250: h.rps_250,
    }));
    const svg = document.getElementById('realtime-kline-svg');
    if (!klineChart) {
      klineChart = new KlineChart(svg);
      klineChart.onViewportChange = () => {
        const lbl = document.querySelector('#realtime-kline-range-label');
        if (lbl) {
          const range = klineChart.getVisibleRange();
          lbl.textContent = `${range.start} ~ ${range.end}`;
        }
      };
    }
    klineChart.load(bars, rpsHistory, currentKlinePreset);
    if (klineTitle) klineTitle.textContent = `${name} (${symbol})`;
    const klineRangeLabel = document.querySelector('#realtime-kline-range-label');
    if (klineRangeLabel) {
      const range = klineChart.getVisibleRange();
      klineRangeLabel.textContent = `${range.start} ~ ${range.end}`;
    }
  } catch (err) {
    console.error('[loadRealtimeKline]', err.message, err.stack);
    if (klineTitle) klineTitle.textContent = `${symbol} — 加载失败`;
  }
}

// ─── K-line preset buttons ────────────────────────────────────────────────────

function bindRealtimeChartPresetEvents() {
  document.querySelectorAll('[data-kline-preset]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const preset = parseInt(btn.dataset.klinePreset, 10);
      currentKlinePreset = preset;
      document.querySelectorAll('[data-kline-preset]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      if (klineChart && klineChart.bars.length) {
        klineChart.setPreset(preset);
        const lbl = document.querySelector('#realtime-kline-range-label');
        if (lbl) {
          const range = klineChart.getVisibleRange();
          lbl.textContent = `${range.start} ~ ${range.end}`;
        }
      }
    });
  });
}

// ─── Bootstrap ───────────────────────────────────────────────────────────────

scenarioSelectEl.addEventListener('change', loadScenario);
loadScenarioBtn.addEventListener('click', loadScenario);
startMonitorBtn.addEventListener('click', startRealtimeMonitor);
stopMonitorBtn.addEventListener('click', stopRealtimeMonitor);
tbody.addEventListener('click', (event) => {
  const row = event.target.closest('.realtime-row');
  if (row) loadRealtimeKline(row);
});
tbody.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const row = event.target.closest('.realtime-row');
  if (!row) return;
  event.preventDefault();
  loadRealtimeKline(row);
});

bindRealtimeChartPresetEvents();
loadScenario();  // Initialize on page load
statusEl.textContent = '请选择方案并点击加载方案';
