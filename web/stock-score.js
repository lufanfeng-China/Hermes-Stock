// stock-score.js — Financial Score Viewer (dual radar: market + industry)

const SUB_META = {
  roe_ex: { name: "扣非ROE", dim: "profitability", higherBetter: true, zeroPenalty: true, unit: "%", desc: "扣除非经常性损益ROE", formula: "扣除非经常性损益后的净利润 / 归属于母公司股东权益", meaning: "反映股东资本的核心回报效率" },
  net_margin: { name: "净利率", dim: "profitability", higherBetter: true, zeroPenalty: true, unit: "%", desc: "净利润率(非金融)", formula: "归属于母公司所有者的净利润 / 营业收入", meaning: "反映每单位营收最终沉淀多少利润" },
  roe_pct: { name: "净资产收益率", dim: "profitability", higherBetter: true, zeroPenalty: true, unit: "%", desc: "ROE（净资产收益率）", formula: "净利润 / 归属于母公司股东权益", meaning: "反映股东资本的整体回报水平" },
  revenue_growth: { name: "营收增速", dim: "growth", higherBetter: true, zeroPenalty: false, unit: "%", desc: "营业收入同比", formula: "(本期营业收入 - 上年同期营业收入) / 上年同期营业收入", meaning: "反映收入扩张速度与需求变化" },
  profit_growth: { name: "净利润增速", dim: "growth", higherBetter: true, zeroPenalty: false, unit: "%", desc: "净利润同比", formula: "(本期净利润 - 上年同期净利润) / 上年同期净利润", meaning: "反映利润释放速度与盈利弹性" },
  ex_profit_growth: { name: "扣非增速", dim: "growth", higherBetter: true, zeroPenalty: false, unit: "%", desc: "扣非净利润同比", formula: "(本期扣非净利润 - 上年同期扣非净利润) / 上年同期扣非净利润", meaning: "反映核心经营利润的增长质量" },
  ar_days: { name: "应收周转天数", dim: "operating", higherBetter: false, zeroPenalty: true, unit: "天", desc: "应收帐款周转天数", formula: "应收账款 / (营业收入 / 365)", meaning: "反映销售回款速度与资金占用程度" },
  inv_days: { name: "存货周转天数", dim: "operating", higherBetter: false, zeroPenalty: true, unit: "天", desc: "存货周转天数", formula: "存货 / (营业成本 / 365)", meaning: "反映库存消化速度与周转压力" },
  asset_turn: { name: "总资产周转率", dim: "operating", higherBetter: true, zeroPenalty: true, unit: "次", desc: "总资产周转率", formula: "营业收入 / 总资产", meaning: "反映资产投入转化为收入的效率" },
  ocf_to_profit: { name: "净现比", dim: "cashflow", higherBetter: true, zeroPenalty: true, unit: "倍", desc: "经营现金流/净利润", formula: "经营活动产生的现金流量净额 / 净利润", meaning: "反映利润转化为现金的含金量" },
  ocf_to_rev: { name: "现金流/营收", dim: "cashflow", higherBetter: true, zeroPenalty: true, unit: "%", desc: "经营现金流/营业收入", formula: "经营活动产生的现金流量净额 / 营业收入", meaning: "反映收入回笼成经营现金的效率" },
  free_cf: { name: "自由现金流", dim: "cashflow", higherBetter: true, zeroPenalty: true, unit: "元", desc: "经营现金流-资本支出", formula: "经营活动产生的现金流量净额 - 资本支出", meaning: "反映资本开支后的现金沉淀能力" },
  debt_ratio: { name: "资产负债率", dim: "solvency", higherBetter: false, zeroPenalty: true, unit: "%", desc: "资产负债率", formula: "总负债 / 总资产", meaning: "反映资产中有多少比例由负债支撑" },
  current_ratio: { name: "流动比率", dim: "solvency", higherBetter: true, zeroPenalty: true, unit: "倍", desc: "流动资产/流动负债", formula: "流动资产 / 流动负债", meaning: "反映短期资产覆盖短期负债的能力" },
  quick_ratio: { name: "速动比率", dim: "solvency", higherBetter: true, zeroPenalty: true, unit: "倍", desc: "(流动资产-存货)/流动负债", formula: "(流动资产 - 存货) / 流动负债", meaning: "反映高流动性资产覆盖短债的能力" },
  ar_to_asset: { name: "应收占比", dim: "asset_quality", higherBetter: false, zeroPenalty: true, unit: "%", desc: "应收账款/总资产", formula: "应收账款 / 总资产", meaning: "反映资产中被客户信用占用的比例" },
  inv_to_asset: { name: "存货占比", dim: "asset_quality", higherBetter: false, zeroPenalty: true, unit: "%", desc: "存货/总资产", formula: "存货 / 总资产", meaning: "反映资产中被库存占用的比例" },
  goodwill_ratio: { name: "商誉占比", dim: "asset_quality", higherBetter: false, zeroPenalty: true, unit: "%", desc: "商誉/总资产", formula: "商誉 / 总资产", meaning: "反映并购形成资产对总资产的占用程度" },
  impair_to_rev: { name: "减值损失率", dim: "asset_quality", higherBetter: false, zeroPenalty: true, unit: "%", desc: "资产减值损失/营业收入", formula: "资产减值损失 / 营业收入", meaning: "反映减值损失对收入与利润稳定性的侵蚀" },
};

function subIndicatorDirectionText(meta) {
  const directionText = meta?.higherBetter === false ? "越小越好" : "越大越好";
  return directionText;
}

function currentValueTrendClass(meta, currentVal, previousVal) {
  const currentNum = Number(currentVal);
  const previousNum = Number(previousVal);
  if (!Number.isFinite(currentNum) || !Number.isFinite(previousNum) || currentNum === previousNum) {
    return "value-trend-flat";
  }
  const improved = meta?.higherBetter === false ? currentNum < previousNum : currentNum > previousNum;
  return improved ? "value-trend-positive" : "value-trend-negative";
}

function renderSubIndicatorInfo(meta) {
  const formula = meta?.formula || meta?.desc || "—";
  const meaning = meta?.meaning || "—";
  const directionText = subIndicatorDirectionText(meta);
  return `
    <div class="sub-rank-formula">formula: ${escapeHtml(formula)}</div>
    <div class="sub-rank-meaning">meaning: ${escapeHtml(meaning)}</div>
    <div class="sub-rank-direction">${escapeHtml(directionText)}</div>`;
}

function renderIndustryPeerFinancialInputs(row, subKey) {
  const inputs = Array.isArray(row?.financial_inputs) ? row.financial_inputs : [];
  if (!inputs.length) return "—";
  return inputs.map((item) => {
    const label = escapeHtml(item?.label || item?.key || "—");
    const currentValue = formatAmountYi(item?.current_value);
    const previousValue = item && Object.prototype.hasOwnProperty.call(item, "previous_value")
      ? formatAmountYi(item.previous_value)
      : null;
    return `<div><strong>${label}</strong>: ${escapeHtml(currentValue)}${previousValue ? ` / 上年同期 ${escapeHtml(previousValue)}` : ""}</div>`;
  }).join("");
}

function renderIndustryPeerDialog(payload) {
  const tbody = document.getElementById("industry-peer-tbody");
  const title = document.getElementById("industry-peer-title");
  const status = document.getElementById("industry-peer-status");
  const indicatorName = payload?.indicator_name || payload?.sub_key || "细分指标";
  const industryName = payload?.ind2 || "当前行业";
  title.textContent = `${industryName} · ${indicatorName} 同业对照`;
  status.textContent = payload?.rows?.length
    ? `共 ${payload.rows.length} 只股票，按${subIndicatorDirectionText(SUB_META[payload.sub_key])}排序`
    : "当前行业暂无可展示样本";

  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  tbody.innerHTML = rows.map((row) => `
    <tr class="${row?.is_current_stock ? "industry-peer-row-current" : ""}">
      <td>${escapeHtml(row?.stock_name || "—")}</td>
      <td>${escapeHtml(`${String(row?.market || "").toUpperCase()}:${row?.symbol || "—"}`)}</td>
      <td>${escapeHtml(formatPrice(row?.current_price))}</td>
      <td class="industry-peer-financial-data">${renderIndustryPeerFinancialInputs(row, payload.sub_key)}</td>
      <td>${escapeHtml(formatRawValue(payload.sub_key, row?.metric_value))}</td>
      <td>${escapeHtml(row?.report_date || "—")}</td>
    </tr>`).join("");
}

function renderIndustryScorePeerDialog(payload) {
  const tbody = document.getElementById("industry-score-peer-tbody");
  const title = document.getElementById("industry-score-peer-title");
  const status = document.getElementById("industry-score-peer-status");
  const industryName = payload?.ind2 || "当前行业";
  title.textContent = `${industryName} · 行业内总分同业对照`;
  status.textContent = payload?.rows?.length
    ? `共 ${payload.rows.length} 只股票，按行业总分从高到低排序`
    : "当前行业暂无可展示样本";

  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  tbody.innerHTML = rows.map((row) => `
    <tr class="${row?.is_current_stock ? "industry-score-peer-row-current" : ""}">
      <td>${escapeHtml(row?.stock_name || "—")}</td>
      <td>${escapeHtml(`${String(row?.market || "").toUpperCase()}:${row?.symbol || "—"}`)}</td>
      <td>${escapeHtml(formatPrice(row?.current_price))}</td>
      <td>${escapeHtml(formatProfileMetric(row?.dimension_scores?.profitability) || "—")}</td>
      <td>${escapeHtml(formatProfileMetric(row?.dimension_scores?.growth) || "—")}</td>
      <td>${escapeHtml(formatProfileMetric(row?.dimension_scores?.operating) || "—")}</td>
      <td>${escapeHtml(formatProfileMetric(row?.dimension_scores?.cashflow) || "—")}</td>
      <td>${escapeHtml(formatProfileMetric(row?.dimension_scores?.solvency) || "—")}</td>
      <td>${escapeHtml(formatProfileMetric(row?.dimension_scores?.asset_quality) || "—")}</td>
      <td>${escapeHtml(formatTotalScore(row?.total_score) || "—")}</td>
      <td>${escapeHtml(row?.report_date || "—")}</td>
    </tr>`).join("");
}

function openIndustryPeerDialog() {
  const dialog = document.getElementById("industry-peer-dialog");
  dialog.hidden = false;
  dialog.setAttribute("aria-hidden", "false");
}

function closeIndustryPeerDialog() {
  const dialog = document.getElementById("industry-peer-dialog");
  dialog.hidden = true;
  dialog.setAttribute("aria-hidden", "true");
}

function openIndustryScorePeerDialog() {
  const dialog = document.getElementById("industry-score-peer-dialog");
  dialog.hidden = false;
  dialog.setAttribute("aria-hidden", "false");
}

function closeIndustryScorePeerDialog() {
  const dialog = document.getElementById("industry-score-peer-dialog");
  dialog.hidden = true;
  dialog.setAttribute("aria-hidden", "true");
}

const DIM_NAMES = {
  profitability:  "盈利能力",
  growth:         "成长能力",
  operating:      "运营效率",
  cashflow:       "现金流质量",
  solvency:       "偿债能力",
  asset_quality:  "资产质量",
};

const DIM_WEIGHT = {
  profitability: 0.25, growth: 0.20, operating: 0.15,
  cashflow: 0.20, solvency: 0.10, asset_quality: 0.10,
};

const MARKET_COLOR = "#64b5f6";
const INDUSTRY_COLOR = "#ff9f43";
const SEARCH_DEBOUNCE_MS = 200;
const MAX_RECENT_STOCK_SEARCHES = 6;
const RECENT_STOCK_SEARCHES_STORAGE_KEY = "stock-score-recent-searches";
const PROFILE_PLACEHOLDERS = {
  industryL1: "暂无申万一级",
  industryL2: "暂无申万二级",
  industryTotalMeta: "暂无行业信息",
  totalMarketRank: "全市场排名: 暂无",
  totalIndustryRank: "二级行业排名: 暂无",
  concepts: "暂无核心概念",
  basicPrice: "待加载现价",
  basicChange: "待加载涨幅",
  basicVolumeRatio: "待加载量比",
  basicMarketCap: "待加载A股市值",
  basicTotalShares: "待加载总股本",
  basicFloatShares: "待加载流通股本",
  basicEps: "待加载收益",
  basicDynamicPe: "待加载动态PE",
  rps20: "RPS20: 暂无",
  rps50: "RPS50: 暂无",
  rps120: "RPS120: 暂无",
  rps250: "RPS250: 暂无",
  rankMarket: "全市场排名: 暂无",
  rankIndustry: "二级行业排名: 暂无",
};

const AI_REPORT_PLACEHOLDERS = {
  overall: "",
  highlights: "",
  risks: "",
  positive: "",
  negative: "",
};

const SUB_DIAG_EXPLANATION_STATUS = {
  idle: "点击按钮生成解释，默认不自动调用 AI。",
  loading: "AI 正在生成该指标的业务解释...",
};
const INDUSTRY_PEER_STATUS_PLACEHOLDER = "点击行业均分后加载同业样本";
const INDUSTRY_SCORE_PEER_STATUS_PLACEHOLDER = "点击行业内总分后加载同业样本";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function scoreColor(v) {
  if (v >= 90) return "score-90";
  if (v >= 70) return "score-70";
  if (v >= 50) return "score-50";
  if (v >= 30) return "score-30";
  return "score-low";
}

function _dimWeight(dim) {
  return DIM_WEIGHT[dim] || 0;
}

function formatPeriod(period) {
  const text = String(period || "").trim();
  const quarterMatch = text.match(/^(\d{4})Q([1-4])$/);
  if (quarterMatch) return `${quarterMatch[1]}年Q${quarterMatch[2]}`;
  const annualMatch = text.match(/^(\d{4})A$/);
  if (annualMatch) return `${annualMatch[1]}年报`;
  return text;
}

function formatPeriodBadge(period) {
  const text = String(period || "").trim();
  const quarterMatch = text.match(/^(\d{4})Q([1-4])$/);
  if (quarterMatch) {
    const year = escapeHtml(quarterMatch[1]);
    const quarterClassMap = {
      "1": "ai-report-period-badge-q1",
      "2": "ai-report-period-badge-q2",
      "3": "ai-report-period-badge-q3",
      "4": "ai-report-period-badge-q4",
    };
    const quarterClass = quarterClassMap[quarterMatch[2]] || "";
    const quarter = escapeHtml(`Q${quarterMatch[2]}`);
    return `<span class="ai-report-period-badge ai-report-period-badge-quarter ${quarterClass}"><strong class="ai-report-period-label">${quarter}</strong><span class="ai-report-period-year">${year}年</span></span>`;
  }

  const annualMatch = text.match(/^(\d{4})A$/);
  if (annualMatch) {
    const year = escapeHtml(annualMatch[1]);
    return `<span class="ai-report-period-badge ai-report-period-badge-annual"><strong class="ai-report-period-label">年报</strong><span class="ai-report-period-year">${year}年</span></span>`;
  }

  return `<span class="ai-report-period-label">${escapeHtml(formatPeriod(text || "—"))}</span>`;
}

function formatRawValue(subKey, value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  if (subKey === "free_cf") return formatAmountYi(value);
  const num = Number(value);
  const unit = SUB_META[subKey]?.unit ?? "";
  const text = Math.abs(num) >= 1000 ? num.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }) : num.toFixed(2);
  return unit ? `${text}${unit}` : text;
}

function formatAmountYi(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  const yi = Number(value) / 1e8;
  return `${yi.toFixed(2)}亿`;
}

function formatProfileMetric(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return null;
  return Number(value).toFixed(2);
}

function formatTotalScore(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return null;
  return Number(value).toFixed(1);
}

function formatPrice(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(2);
}

function formatSignedPercent(value) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  const num = Number(value);
  const sign = num > 0 ? "+" : "";
  return `${sign}${num.toFixed(2)}%`;
}

function formatBasicNumber(value, suffix = "", digits = 2) {
  if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(digits)}${suffix}`;
}

function setProfileField(elementId, text, placeholder) {
  const el = document.getElementById(elementId);
  const hasText = Boolean(text && String(text).trim());
  el.textContent = hasText ? String(text).trim() : placeholder;
  el.classList.toggle("muted", !hasText);
}

function setRpsRow(elementId, text, placeholder) {
  const el = document.getElementById(elementId);
  const hasText = Boolean(text && String(text).trim());
  el.textContent = hasText ? String(text).trim() : placeholder;
  el.classList.toggle("muted", !hasText);
}

function renderAnalysisList(elementId, items, placeholder) {
  const el = document.getElementById(elementId);
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!values.length) {
    el.innerHTML = placeholder ? `<div class="stock-score-analysis-item muted">${placeholder}</div>` : "";
    el.classList.add("muted");
    return;
  }
  el.innerHTML = values.map((item) => `<div class="stock-score-analysis-item">• ${item}</div>`).join("");
  el.classList.remove("muted");
}

function resolveIndustryLevels(profile) {
  const parts = String(profile?.industry_display || "")
    .split("/")
    .map((item) => item.trim())
    .filter(Boolean);
  return {
    level1: parts[0] || "",
    level2: parts[1] || "",
  };
}

function renderIndustryTotalMeta(profile) {
  const { level1, level2 } = resolveIndustryLevels(profile);
  const text = level1 && level2
    ? `${level1} / ${level2}`
    : level1 || level2 || "";
  setProfileField("hdr-total-industry-meta", text, PROFILE_PLACEHOLDERS.industryTotalMeta);
}

function renderTotalScoreRankMeta(label, rank, universe, placeholder) {
  if (rank == null || universe == null) {
    return "";
  }
  return `${label}: ${rank}/${universe}`;
}

function renderSearchConceptSummary(profile) {
  const concepts = Array.isArray(profile?.core_concepts)
    ? profile.core_concepts
    : Array.isArray(profile?.concepts)
      ? profile.concepts
      : [];
  const conceptText = concepts
    .map((row) => String(row?.concept_name || row?.name || row || "").trim())
    .filter(Boolean)
    .slice(0, 4)
    .join(" · ");
  const valueEl = document.getElementById("stock-score-search-concepts-value");
  const hasText = Boolean(conceptText);
  valueEl.textContent = hasText ? conceptText : PROFILE_PLACEHOLDERS.concepts;
  valueEl.classList.toggle("muted", !hasText);
}

function renderBasicInfoSummary(profile) {
  const basicInfo = profile?.basic_info || {};
  setProfileField(
    "hdr-basic-price",
    basicInfo.current_price != null ? `${formatPrice(basicInfo.current_price)}元` : "",
    PROFILE_PLACEHOLDERS.basicPrice,
  );
  setProfileField(
    "hdr-basic-change",
    basicInfo.change_pct != null ? formatSignedPercent(basicInfo.change_pct) : "",
    PROFILE_PLACEHOLDERS.basicChange,
  );
  const changeEl = document.getElementById("hdr-basic-change");
  changeEl.classList.remove("basic-change-positive", "basic-change-negative", "basic-change-flat");
  if (basicInfo.change_pct != null && !Number.isNaN(Number(basicInfo.change_pct))) {
    const changeValue = Number(basicInfo.change_pct);
    if (changeValue > 0) {
      changeEl.classList.add("basic-change-positive");
    } else if (changeValue < 0) {
      changeEl.classList.add("basic-change-negative");
    } else {
      changeEl.classList.add("basic-change-flat");
    }
  }
  setProfileField(
    "hdr-basic-volume-ratio",
    basicInfo.volume_ratio != null ? formatBasicNumber(basicInfo.volume_ratio, "", 2) : "",
    PROFILE_PLACEHOLDERS.basicVolumeRatio,
  );
  setProfileField(
    "hdr-basic-market-cap",
    basicInfo.a_share_market_cap != null ? formatBasicNumber(basicInfo.a_share_market_cap, "亿", 2) : "",
    PROFILE_PLACEHOLDERS.basicMarketCap,
  );
  setProfileField(
    "hdr-basic-total-shares",
    basicInfo.total_shares != null ? formatBasicNumber(basicInfo.total_shares, "亿", 2) : "",
    PROFILE_PLACEHOLDERS.basicTotalShares,
  );
  setProfileField(
    "hdr-basic-float-shares",
    basicInfo.float_shares != null ? formatBasicNumber(basicInfo.float_shares, "亿", 2) : "",
    PROFILE_PLACEHOLDERS.basicFloatShares,
  );
  setProfileField(
    "hdr-basic-eps",
    basicInfo.eps != null ? formatBasicNumber(basicInfo.eps, "元", 2) : "",
    PROFILE_PLACEHOLDERS.basicEps,
  );
  setProfileField(
    "hdr-basic-dynamic-pe",
    basicInfo.dynamic_pe != null ? formatBasicNumber(basicInfo.dynamic_pe, "倍", 2) : "",
    PROFILE_PLACEHOLDERS.basicDynamicPe,
  );
}

function renderProfileSummary(profile) {
  const rps20 = formatProfileMetric(profile?.rps_20);
  const rps50 = formatProfileMetric(profile?.rps_50);
  const rps120 = formatProfileMetric(profile?.rps_120);
  const rps250 = formatProfileMetric(profile?.rps_250);
  const industryLevels = resolveIndustryLevels(profile);

  renderBasicInfoSummary(profile);
  renderIndustryTotalMeta(profile);
  renderSearchConceptSummary(profile);
  setProfileField("hdr-industry-l1", industryLevels.level1, PROFILE_PLACEHOLDERS.industryL1);
  setProfileField("hdr-industry-l2", industryLevels.level2, PROFILE_PLACEHOLDERS.industryL2);
  setRpsRow("hdr-rps20", rps20 ? `RPS20: ${rps20}` : "", PROFILE_PLACEHOLDERS.rps20);
  setRpsRow("hdr-rps50", rps50 ? `RPS50: ${rps50}` : "", PROFILE_PLACEHOLDERS.rps50);
  setRpsRow("hdr-rps120", rps120 ? `RPS120: ${rps120}` : "", PROFILE_PLACEHOLDERS.rps120);
  setRpsRow("hdr-rps250", rps250 ? `RPS250: ${rps250}` : "", PROFILE_PLACEHOLDERS.rps250);
  document.getElementById("hdr-rps-summary").classList.toggle(
    "muted",
    !(rps20 || rps50 || rps120 || rps250),
  );
}

function renderRankSummary(result) {
  const marketTotalRank = result?.market_total_rank;
  const marketTotalUniverseSize = result?.market_total_universe_size;
  const industryTotalRank = result?.industry_total_rank;
  const industryTotalUniverseSize = result?.industry_total_universe_size;

  setRpsRow(
    "hdr-rank-market",
    marketTotalRank != null && marketTotalUniverseSize != null
      ? `全市场排名: ${marketTotalRank}/${marketTotalUniverseSize}`
      : "",
    PROFILE_PLACEHOLDERS.rankMarket,
  );
  setRpsRow(
    "hdr-rank-industry",
    industryTotalRank != null && industryTotalUniverseSize != null
      ? `二级行业排名: ${industryTotalRank}/${industryTotalUniverseSize}`
      : "",
    PROFILE_PLACEHOLDERS.rankIndustry,
  );
  document.getElementById("hdr-rank-summary").classList.toggle(
    "muted",
    !(
      (marketTotalRank != null && marketTotalUniverseSize != null)
      || (industryTotalRank != null && industryTotalUniverseSize != null)
    ),
  );
}

function renderTotalScoreRankSummary(result) {
  setProfileField(
    "hdr-total-market-rank",
    renderTotalScoreRankMeta(
      "全市场排名",
      result?.market_total_rank,
      result?.market_total_universe_size,
      PROFILE_PLACEHOLDERS.totalMarketRank,
    ),
    PROFILE_PLACEHOLDERS.totalMarketRank,
  );
  setProfileField(
    "hdr-total-industry-rank",
    renderTotalScoreRankMeta(
      "二级行业排名",
      result?.industry_total_rank,
      result?.industry_total_universe_size,
      PROFILE_PLACEHOLDERS.totalIndustryRank,
    ),
    PROFILE_PLACEHOLDERS.totalIndustryRank,
  );
}

function resetProfileSummary() {
  renderBasicInfoSummary(null);
  renderProfileSummary(null);
  renderRankSummary(null);
}

function setAiReportStatus(text, isError = false) {
  const el = document.getElementById("ai-report-status");
  el.textContent = text;
  el.classList.toggle("muted", !isError);
  el.classList.toggle("error", isError);
}

function renderAiReportOverall(text) {
  const el = document.getElementById("ai-report-overall");
  const hasText = Boolean(text && String(text).trim());
  el.textContent = hasText ? String(text).trim() : AI_REPORT_PLACEHOLDERS.overall;
  el.classList.toggle("muted", !hasText);
}

function renderAiFinancialReport(analysis) {
  renderAiReportOverall(analysis?.overall || "");
  renderAnalysisList("ai-report-highlights", analysis?.highlights, AI_REPORT_PLACEHOLDERS.highlights);
  renderAnalysisList("ai-report-risks", analysis?.risks, AI_REPORT_PLACEHOLDERS.risks);
  renderAnalysisList("ai-report-positive", analysis?.positive_factors, AI_REPORT_PLACEHOLDERS.positive);
  renderAnalysisList("ai-report-negative", analysis?.negative_factors, AI_REPORT_PLACEHOLDERS.negative);
}

function renderAiReportRawTable(reports) {
  const table = document.getElementById("ai-report-raw-table");
  const tbody = table.querySelector("tbody");
  const rows = Array.isArray(reports) ? reports : [];
  if (!rows.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="10" class="muted">暂无最近 3 年原始财报数据</td>
      </tr>`;
    return;
  }

  tbody.innerHTML = rows.map((report) => {
    const metrics = report?.metrics || {};
    const amountCell = (amount) => `
      <td class="ai-report-raw-cell">
        <div class="ai-report-raw-metric">${escapeHtml(formatAmountYi(amount))}</div>
      </td>`;
    const yoyCell = (yoy) => `
      <td class="ai-report-raw-cell">
        <div class="ai-report-raw-trend"><span class="${yoyClassName(yoy)}">${escapeHtml(formatYoy(yoy))}</span></div>
      </td>`;
    return `
      <tr>
        <td>${formatPeriodBadge(report?.period || report?.latest_period_label || "—")}</td>
        ${amountCell(metrics.revenue)}
        ${yoyCell(metrics.revenue_growth)}
        ${amountCell(metrics.net_profit)}
        ${yoyCell(metrics.profit_growth)}
        ${amountCell(metrics.ex_net_profit)}
        ${yoyCell(metrics.ex_profit_growth)}
        <td>${escapeHtml(formatRawValue("roe_ex", metrics.roe_ex))}</td>
        <td>${escapeHtml(formatRawValue("current_ratio", metrics.current_ratio))}</td>
        <td>${escapeHtml(formatRawValue("quick_ratio", metrics.quick_ratio))}</td>
      </tr>`;
  }).join("");
}

function toggleAiReportRawData(hasData) {
  const details = document.getElementById("ai-report-raw-data");
  const summary = document.getElementById("ai-report-raw-toggle");
  details.classList.toggle("is-empty", !hasData);
  if (!hasData) details.open = false;
  summary.textContent = hasData ? "展开最近3年报告期原始财报数据" : "最近3年报告期原始财报数据待加载";
}

function buildAiReportSummaryText() {
  const sections = [
    ["总体评价", document.getElementById("ai-report-overall")?.textContent || ""],
    ["财报亮点", Array.from(document.querySelectorAll("#ai-report-highlights .stock-score-analysis-item")).map((item) => item.textContent.replace(/^•\s*/, "").trim()).join("；")],
    ["风险警示", Array.from(document.querySelectorAll("#ai-report-risks .stock-score-analysis-item")).map((item) => item.textContent.replace(/^•\s*/, "").trim()).join("；")],
    ["加分项", Array.from(document.querySelectorAll("#ai-report-positive .stock-score-analysis-item")).map((item) => item.textContent.replace(/^•\s*/, "").trim()).join("；")],
    ["减分项", Array.from(document.querySelectorAll("#ai-report-negative .stock-score-analysis-item")).map((item) => item.textContent.replace(/^•\s*/, "").trim()).join("；")],
  ];
  return sections
    .filter(([, content]) => content && content.trim())
    .map(([label, content]) => `${label}：${content.trim()}`)
    .join("\n");
}

async function copyTextWithFallback(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall through to execCommand-based copy for environments without clipboard permission.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  textarea.style.top = "-9999px";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  const copied = typeof document.execCommand === "function" && document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("浏览器未授予剪贴板权限，请手动复制摘要");
  }
}

function resetAiFinancialReport(statusText = "查询股票后可生成分析") {
  renderAiFinancialReport(null);
  renderAiReportRawTable([]);
  toggleAiReportRawData(false);
  setAiReportStatus(statusText);
}

function setAiReportLoading(isLoading) {
  const button = document.getElementById("ai-report-btn");
  const copyButton = document.getElementById("ai-report-copy-btn");
  button.disabled = isLoading;
  button.textContent = isLoading ? "生成中..." : (searchState.currentStock?.aiReportReady ? "重新生成AI财报解读" : "生成AI财报解读");
  copyButton.disabled = isLoading;
}

function updateAiReportButtons() {
  const button = document.getElementById("ai-report-btn");
  const copyButton = document.getElementById("ai-report-copy-btn");
  button.textContent = searchState.currentStock?.aiReportReady ? "重新生成AI财报解读" : "生成AI财报解读";
  copyButton.disabled = !searchState.currentStock?.aiReportReady;
}

function renderScoreMethodology(methodology) {
  const el = document.getElementById("score-methodology-note");
  if (!methodology) {
    el.textContent = "评分口径：当前结果未返回额外方法说明，默认展示接口提供的全市场评分。";
    el.classList.add("muted");
    return;
  }

  const mode = methodology.market_score_mode || "";
  if (mode === "industry_adjusted_market_view") {
    const blendedDims = Array.isArray(methodology.blended_dimensions)
      ? methodology.blended_dimensions
      : ["operating", "solvency", "asset_quality"];
    const blendedNames = blendedDims.map((dim) => DIM_NAMES[dim] || dim).join("、");
    el.textContent = `评分口径：全市场总分已做行业校准，其中${blendedNames}按行业分数70% + 市场分数30%混合；盈利能力、成长能力、现金流质量保持纯全市场分数。`;
    el.classList.remove("muted");
    return;
  }

  el.textContent = "评分口径：当前结果使用全市场原始评分口径，未进行行业校准混合。";
  el.classList.remove("muted");
}

// ── SVG helpers ───────────────────────────────────────────────────────────────
function elt(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) {
    el.setAttribute(k, v);
  }
  return el;
}

// ── Draw one radar chart ─────────────────────────────────────────────────────
function drawRadar(svgId, dimScores, totalScore, fillColor, strokeColor) {
  const svg = document.getElementById(svgId);
  svg.innerHTML = "";

  const dims = Object.keys(DIM_NAMES);
  const n = dims.length;
  const cx = 155, cy = 155, r = 115;

  // Background rings
  for (let ring = 1; ring <= 4; ring++) {
    const rr = (ring / 4) * r;
    const pts = dims.map((_, i) => {
      const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
      return `${cx + rr * Math.cos(angle)},${cy + rr * Math.sin(angle)}`;
    }).join(" ");
    svg.appendChild(elt("polygon", {
      points: pts,
      fill: "none",
      stroke: ring === 4 ? "#2a2a44" : "#1e1e33",
      "stroke-width": ring === 4 ? "1" : "0.5",
    }));
  }

  // Axis lines + labels
  dims.forEach((dim, i) => {
    const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
    const x2 = cx + r * Math.cos(angle), y2 = cy + r * Math.sin(angle);
    svg.appendChild(elt("line", { x1: cx, y1: cy, x2, y2, stroke: "#2a2a44", "stroke-width": "1" }));

    const lr = r + 18;
    const lx = cx + lr * Math.cos(angle), ly = cy + lr * Math.sin(angle);
    svg.appendChild(elt("text", {
      x: lx, y: ly + 4, "text-anchor": "middle",
      fill: "#888899", "font-size": "14", "font-family": "monospace",
    })).textContent = DIM_NAMES[dim];
  });

  // Score polygon
  const scorePts = dims.map((dim, i) => {
    const raw = dimScores[dim] || 0;
    const weighted = raw * _dimWeight(dim);
    const vr = (weighted / 25) * r;
    const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
    return `${cx + vr * Math.cos(angle)},${cy + vr * Math.sin(angle)}`;
  }).join(" ");

  svg.appendChild(elt("polygon", {
    points: scorePts,
    fill: fillColor + "22",
    stroke: strokeColor,
    "stroke-width": "1.5",
  }));

  // Score value on each axis
  dims.forEach((dim, i) => {
    const raw = dimScores[dim] || 0;
    const weighted = raw * _dimWeight(dim);
    const vr = (weighted / 25) * r;
    const angle = (Math.PI * 2 * i / n) - Math.PI / 2;
    const vx = cx + vr * Math.cos(angle), vy = cy + vr * Math.sin(angle);
    const t = elt("text", {
      x: vx, y: vy - 4, "text-anchor": "middle",
      fill: strokeColor, "font-size": "12",
      "font-weight": "bold", "font-family": "monospace",
    });
    t.textContent = weighted.toFixed(1);
    svg.appendChild(t);
  });

  // Center total score
  const ct = elt("text", {
    x: cx, y: cy + 5, "text-anchor": "middle",
    fill: strokeColor, "font-size": "28", "font-weight": "bold", "font-family": "monospace",
  });
  ct.textContent = totalScore.toFixed(1);
  svg.appendChild(ct);
}

// ── Dimension cards ───────────────────────────────────────────────────────────
function renderDimCards(containerId, dimScores, palette) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";

  Object.entries(DIM_NAMES).forEach(([dim, name]) => {
    const rawScore = dimScores[dim] || 0;
    const card = document.createElement("div");
    card.className = "dim-card";
    card.style.borderLeftColor = palette[dim] || "#333";

    card.innerHTML = `
      <div class="dim-name">${name}</div>
      <div class="dim-score ${scoreColor(rawScore)}">${rawScore.toFixed(1)}</div>
      <div class="dim-bar-wrap">
        <div class="dim-bar" style="width:${Math.min(100, rawScore)}%;background:${palette[dim] || '#5a5a9a'};"></div>
      </div>`;
    container.appendChild(card);
  });
}

const DIM_COLORS = {
  profitability: "#64b5f6", growth: "#81c784", operating: "#ffb74d",
  cashflow: "#4dd0e1", solvency: "#ce93d8", asset_quality: "#f48fb1",
};

const DIM_COLORS_INDUSTRY = {
  profitability: "#8cc7ff", growth: "#9dd89c", operating: "#ffc56f",
  cashflow: "#78dfef", solvency: "#e2abff", asset_quality: "#ffb1cb",
};

// ── Sub-indicator table with both market + industry scores + YoY ─────────────────
function computeYoy(subKey, currentVal, prevRaw) {
  if (prevRaw == null || currentVal == null) return null;
  const prev = prevRaw[subKey];
  if (prev == null || prev === 0 || prev !== prev) return null;  // NaN check
  return ((currentVal - prev) / Math.abs(prev)) * 100;
}

function formatYoy(yoy) {
  if (yoy == null) return "—";
  const sign = yoy >= 0 ? "+" : "";
  return `${sign}${yoy.toFixed(1)}%`;
}

function yoyColor(yoy) {
  if (yoy == null || yoy === 0) return "color:#555577";
  return yoy > 0 ? "color:#81c784" : "color:#ef5350";
}

function yoyClassName(yoy) {
  if (yoy == null || yoy === 0) return "ai-report-yoy-flat";
  return yoy > 0 ? "ai-report-yoy-positive" : "ai-report-yoy-negative";
}

function describeYoyDirection(yoy, meta) {
  if (yoy == null) return "缺少可比上年同期数据";
  if (yoy === 0) return "与上年同期基本持平";
  if (meta?.higherBetter === false) {
    return yoy < 0 ? "指标下降，方向偏正面" : "指标抬升，方向偏谨慎";
  }
  return yoy > 0 ? "指标改善，方向偏正面" : "指标走弱，方向偏谨慎";
}

function getSubDiagnosticSummaryList(value, fallback = []) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return fallback;
}

function formatNeedsTextValidation(value) {
  return value ? "是" : "否";
}

function formatValidationSources(value) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).map((item) => String(item).trim()).filter(Boolean).join(" / ");
  }
  return String(value || "未标注").trim() || "未标注";
}

function getStoredSubdiagExplanation(subKey) {
  return searchState.currentStock?.subdiagExplanations?.[subKey] || null;
}

function buildIdleSubdiagExplanationState() {
  return {
    status: "idle",
    summary: "",
    hypotheses: [],
    validation_focus: [],
    confidence: "",
  };
}

function normalizeSubdiagExplanationState(explanation) {
  const base = buildIdleSubdiagExplanationState();
  const merged = { ...base, ...(explanation || {}) };
  const normalizeList = (value) => Array.isArray(value)
    ? value.filter(Boolean).map((item) => String(item).trim()).filter(Boolean)
    : [];
  return {
    status: ["idle", "loading", "ready", "error"].includes(merged.status) ? merged.status : "idle",
    summary: String(merged.summary || "").trim(),
    hypotheses: normalizeList(merged.hypotheses),
    validation_focus: normalizeList(merged.validation_focus),
    confidence: String(merged.confidence || "").trim(),
    error: String(merged.error || "").trim(),
  };
}

function resolveSubdiagExplanationState(subKey, backendDiagnostic) {
  const stored = getStoredSubdiagExplanation(subKey);
  if (stored) return normalizeSubdiagExplanationState(stored);
  if (backendDiagnostic?.explanation?.status === "ready") {
    return normalizeSubdiagExplanationState(backendDiagnostic.explanation);
  }
  return buildIdleSubdiagExplanationState();
}

function explanationButtonText(state) {
  if (state.status === "loading") return "生成中...";
  if (state.status === "ready") return "重新生成解释";
  return "生成解释";
}

function explanationConfidenceLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  if (key === "high") return "高";
  if (key === "low") return "低";
  return "中";
}

function shortenTerminalLine(value, limit = 24) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  const head = text.split(/[；;。.!?]/)[0].trim().replace(/[，、;；:：]+$/g, "");
  if (head.length <= limit) return head;
  return head.slice(0, limit).replace(/[，、;；:：]+$/g, "");
}

function renderTerminalExplanationLine(label, value, limit = 24) {
  const text = shortenTerminalLine(value, limit);
  if (!text) return "";
  return `<div class="subdiag-explanation-terminal-line"><span class="subdiag-explanation-terminal-label">${label}</span><span>${escapeHtml(text)}</span></div>`;
}

function renderTerminalExplanationChip(label, value, limit = 24) {
  const text = shortenTerminalLine(value, limit);
  if (!text) return "";
  return `<div class="subdiag-explanation-signal-chip"><span class="subdiag-explanation-terminal-label">${label}</span><span>${escapeHtml(text)}</span></div>`;
}

function renderSubdiagExplanationContent(subKey, explanationState) {
  if (explanationState.status === "loading") {
    return {
      statusText: SUB_DIAG_EXPLANATION_STATUS.loading,
      statusClassName: "profile-meta",
      bodyHtml: "",
      bodyMuted: true,
    };
  }

  if (explanationState.status === "error") {
    const message = explanationState.error || "生成失败，请重试。";
    return {
      statusText: `${message} 点击按钮生成解释，默认不自动调用 AI。`,
      statusClassName: "profile-meta error subdiag-explanation-retry",
      bodyHtml: '<div class="profile-meta subdiag-explanation-retry">可重试生成该指标解释。</div>',
      bodyMuted: false,
    };
  }

  if (explanationState.status === "ready") {
    const summaryLine = explanationState.summary
      ? renderTerminalExplanationLine("结论:", explanationState.summary, 30)
      : "";
    const chips = ['<div class="subdiag-explanation-status-chip">SIGNAL READY</div>'];
    if (explanationState.hypotheses.length) {
      explanationState.hypotheses.slice(0, 2).forEach((item) => {
        chips.push(renderTerminalExplanationChip("原因:", item, 18));
      });
    }
    if (explanationState.validation_focus.length) {
      explanationState.validation_focus.slice(0, 2).forEach((item) => {
        chips.push(renderTerminalExplanationChip("验证:", item, 18));
      });
    }
    if (explanationState.confidence) {
      chips.push(renderTerminalExplanationChip("置信:", explanationConfidenceLabel(explanationState.confidence), 4));
    }
    const signalGrid = chips.length
      ? `<div class="subdiag-explanation-signal-grid">${chips.join("")}</div>`
      : "";
    const bodyHtml = summaryLine || signalGrid
      ? `<div class="subdiag-explanation-terminal-panel">${summaryLine}${signalGrid}</div>`
      : "";
    return {
      statusText: "已生成该指标解释",
      statusClassName: "profile-meta",
      bodyHtml,
      bodyMuted: !(summaryLine || signalGrid),
    };
  }

  return {
    statusText: SUB_DIAG_EXPLANATION_STATUS.idle,
    statusClassName: "profile-meta",
    bodyHtml: "",
    bodyMuted: true,
  };
}

function renderSubIndicatorDiagnostic(subKey, meta, context) {
  const {
    currentDisplay,
    previousDisplay,
    yoy,
    marketScore,
    industryScore,
    backendDiagnostic,
    explanationState,
  } = context;
  const yoyBadge = `<span class="${yoyClassName(yoy)}">${formatYoy(yoy)}</span>`;
  const scoreGap = marketScore - industryScore;
  const gapDirection = scoreGap === 0 ? "双口径评分接近" : scoreGap > 0 ? "全市场口径略强" : "行业口径略强";
  const rankBasis = meta?.higherBetter === false ? "数值越低通常越优" : "数值越高通常越优";
  const changeSummary = backendDiagnostic?.change?.summary || `当期 ${currentDisplay} / 上年同期 ${previousDisplay} / 同比 ${formatYoy(yoy)}`;
  const attributionLines = backendDiagnostic
    ? getSubDiagnosticSummaryList(backendDiagnostic.attribution?.summary, [
      "已接入后端诊断模板",
      `模板类型: ${backendDiagnostic.attribution?.template_type || "未标注"}`,
    ])
    : [
      "详细归因待接入",
      "当前仅展示固定模板，不伪造未接线的驱动拆解。",
      `口径提示: ${rankBasis}`,
    ];
  const impactLines = backendDiagnostic
    ? getSubDiagnosticSummaryList(backendDiagnostic.impact?.impact_risks, [
      backendDiagnostic.impact?.impact_summary || "已接入后端影响摘要",
    ])
    : [
      `全市场分 ${marketScore.toFixed(1)} / 行业内分 ${industryScore.toFixed(1)}`,
      `分差 ${scoreGap.toFixed(1)}，${gapDirection}。`,
      "详细分值贡献链路待后端接入。",
    ];
  const explanationView = renderSubdiagExplanationContent(subKey, explanationState);
  const impactHeadline = backendDiagnostic
    ? (backendDiagnostic.impact?.impact_summary || `全市场分 ${marketScore.toFixed(1)} / 行业内分 ${industryScore.toFixed(1)}`)
    : `全市场分 ${marketScore.toFixed(1)} / 行业内分 ${industryScore.toFixed(1)}`;
  const attributionHeadline = backendDiagnostic
    ? (backendDiagnostic.attribution?.template_type || "已接入模板")
    : "固定占位模板";
  const evidenceStrength = backendDiagnostic?.attribution?.evidence_strength || "未标注";
  const needsTextValidation = formatNeedsTextValidation(backendDiagnostic?.attribution?.needs_text_validation);
  const validationSources = formatValidationSources(backendDiagnostic?.attribution?.validation_sources);
  const industryScope = backendDiagnostic?.attribution?.industry_scope || "未标注";

  return `
    <div class="stock-score-subdiag" data-subdiag-key="${escapeHtml(subKey)}">
      <div class="stock-score-subdiag-grid">
        <section class="profile-field stock-score-profile-field">
          <span class="profile-label">变动快照</span>
          <div class="profile-value">
            <div><strong>${escapeHtml(meta.name)}</strong> · ${escapeHtml(DIM_NAMES[meta.dim] || "未分类")}</div>
            <div>当期 ${escapeHtml(currentDisplay)} / 上年同期 ${escapeHtml(previousDisplay)} / 同比 ${yoyBadge}</div>
            <div class="profile-meta">${escapeHtml(changeSummary)}</div>
            <div class="profile-meta">${escapeHtml(describeYoyDirection(yoy, meta))}</div>
          </div>
        </section>
        <section class="profile-field stock-score-profile-field stock-score-subdiag-attribution">
          <span class="profile-label">归因卡</span>
          <div class="profile-value">
            <div>${escapeHtml(attributionHeadline)}</div>
            ${backendDiagnostic ? `<div class="profile-meta">证据强度: ${escapeHtml(evidenceStrength)}</div>` : ""}
            ${backendDiagnostic ? `<div class="profile-meta">需文本验证: ${escapeHtml(needsTextValidation)}</div>` : ""}
            ${backendDiagnostic ? `<div class="profile-meta">建议验证来源: ${escapeHtml(validationSources)}</div>` : ""}
            ${backendDiagnostic ? `<div class="profile-meta">行业适用: ${escapeHtml(industryScope)}</div>` : ""}
            ${attributionLines.map((line) => `<div class="profile-meta">${escapeHtml(line)}</div>`).join("")}
            ${backendDiagnostic ? `<div class="profile-meta">口径提示: ${escapeHtml(rankBasis)}</div>` : ""}
          </div>
        </section>
        <section class="profile-field stock-score-profile-field stock-score-subdiag-impact">
          <span class="profile-label">影响卡</span>
          <div class="profile-value">
            <div>${escapeHtml(impactHeadline)}</div>
            ${impactLines.map((line) => `<div class="profile-meta">${escapeHtml(line)}</div>`).join("")}
            <div class="profile-meta">分差 ${escapeHtml(scoreGap.toFixed(1))}，${escapeHtml(gapDirection)}。</div>
          </div>
        </section>
        <section class="profile-field stock-score-profile-field stock-score-subdiag-explanation">
          <span class="profile-label">解释卡</span>
          <div class="ai-report-action-row">
            <button type="button" class="stock-score-subdiag-trigger" data-subdiag-action="explain" data-subdiag-key="${escapeHtml(subKey)}"${explanationState.status === "loading" ? " disabled" : ""}>${escapeHtml(explanationButtonText(explanationState))}</button>
            <div class="${escapeHtml(explanationView.statusClassName)}" id="subdiag-explanation-status-${escapeHtml(subKey)}">${escapeHtml(explanationView.statusText)}</div>
          </div>
          <div class="profile-value${explanationView.bodyMuted ? " muted" : ""}" id="subdiag-explanation-${escapeHtml(subKey)}">${explanationView.bodyHtml}</div>
        </section>
      </div>
    </div>`;
}

function renderSubTable(scoreData, indSubIndicators, rawSubIndicators, prevRawSubIndicators, industryRawSubIndicatorAvgs, subIndicatorDiagnostics = {}) {
  const tbody = document.getElementById("sub-tbody");
  tbody.innerHTML = "";
  const columnCount = document.querySelectorAll("#sub-table thead th").length || 8;

  Object.entries(scoreData).forEach(([key, val]) => {
    if (typeof val !== "number") return;

    const meta = SUB_META[key];
    if (!meta) return;

    const indVal = indSubIndicators ? (indSubIndicators[key] || 0) : 0;
    const rawVal = rawSubIndicators ? rawSubIndicators[key] : null;
    const prevVal = prevRawSubIndicators ? prevRawSubIndicators[key] : null;
    const industryAverageVal = industryRawSubIndicatorAvgs ? industryRawSubIndicatorAvgs[key] : null;
    const yoy = computeYoy(key, rawVal, prevRawSubIndicators || {});
    const currentDisplay = key === "free_cf" ? formatAmountYi(rawVal) : formatRawValue(key, rawVal);
    const previousDisplay = key === "free_cf" ? formatAmountYi(prevVal) : formatRawValue(key, prevVal);
    const industryAverageDisplay = key === "free_cf" ? formatAmountYi(industryAverageVal) : formatRawValue(key, industryAverageVal);
    const currentTrendClass = currentValueTrendClass(meta, rawVal, prevVal);
    const isExpanded = searchState.expandedSubDiagKey === key;
    const backendDiagnostic = subIndicatorDiagnostics[key] || null;
    const explanationState = resolveSubdiagExplanationState(key, backendDiagnostic);

    const row = document.createElement("tr");
    row.className = "stock-score-subrow";
    row.dataset.subdiagKey = key;
    row.innerHTML = `
      <td style="color:${DIM_COLORS[meta.dim] || "#888"};font-size:13px;">${DIM_NAMES[meta.dim]}</td>
      <td class="sub-name">
        <button type="button" class="stock-score-subdiag-trigger" data-subdiag-action="toggle" data-subdiag-key="${escapeHtml(key)}" aria-expanded="${isExpanded ? "true" : "false"}">
          <span>${meta.name}</span>
          <span>${isExpanded ? "收起" : "诊断"}</span>
        </button>
      </td>
      <td class="sub-period-current ${currentTrendClass}">${currentDisplay}</td>
      <td class="sub-period-previous">${previousDisplay}</td>
      <td class="sub-period-industry-average">
        <button type="button" class="sub-period-industry-average-btn industry-peer-trigger" data-subdiag-action="industry-peer" data-subdiag-key="${escapeHtml(key)}">
          ${industryAverageDisplay}
        </button>
      </td>
      <td class="sub-score ${scoreColor(val)}" style="color:${MARKET_COLOR};">${val.toFixed(1)}</td>
      <td class="sub-score ${scoreColor(indVal)}" style="color:${INDUSTRY_COLOR};">${indVal.toFixed(1)}</td>
      <td class="sub-rank">${renderSubIndicatorInfo(meta)}</td>`;
    tbody.appendChild(row);

    const detailRow = document.createElement("tr");
    detailRow.className = "stock-score-subdiag-row";
    detailRow.hidden = !isExpanded;
    detailRow.innerHTML = `
      <td colspan="${columnCount}">
        ${renderSubIndicatorDiagnostic(key, meta, {
          currentDisplay,
          previousDisplay,
          yoy,
          marketScore: val,
          industryScore: indVal,
          backendDiagnostic,
          explanationState,
        })}
      </td>`;
    tbody.appendChild(detailRow);
  });
}

// ── Main render ───────────────────────────────────────────────────────────────
function renderScore(result) {
  const {
    ok, stock_name, report_date, latest_period,
    total_score, dim_scores,
    score_data: sd,
    sub_indicators,
    ind_total_score, ind_dim_scores, ind_sub_indicators,
    raw_sub_indicators,
    prev_raw_sub_indicators,
    industry_raw_sub_indicator_avgs,
    score_methodology,
    sub_indicator_diagnostics,
    market_total_rank,
    market_total_universe_size,
    industry_total_rank,
    industry_total_universe_size,
  } = result;

  if (!ok || !total_score) {
    document.getElementById("loading-msg").textContent = "未找到评分数据";
    return;
  }

  document.getElementById("score-header").classList.add("visible");
  document.getElementById("loading-msg").style.display = "none";

  // Header
  document.getElementById("hdr-name").textContent = stock_name || "—";
  document.getElementById("hdr-symbol").textContent = `${result.market}:${result.symbol}`;

  const rdEl = document.getElementById("hdr-report-date");
  const adEl = document.getElementById("hdr-announce-date");
  const periodText = formatPeriod(latest_period);
  if (report_date && report_date.length === 8) {
    rdEl.textContent = `财报 ${report_date.slice(0,4)}-${report_date.slice(4,6)}-${report_date.slice(6,8)}${periodText ? ` · ${periodText}` : ""}`;
  } else if (report_date) {
    rdEl.textContent = `财报 ${report_date}${periodText ? ` · ${periodText}` : ""}`;
  } else if (periodText) {
    rdEl.textContent = periodText;
  } else {
    rdEl.textContent = "";
  }
  // 公告日期
  const announce_date = result.announce_date || "";
  if (announce_date && announce_date.length === 8) {
    adEl.textContent = `公告 ${announce_date.slice(0,4)}-${announce_date.slice(4,6)}-${announce_date.slice(6,8)}`;
  } else if (announce_date) {
    adEl.textContent = `公告 ${announce_date}`;
  } else {
    adEl.textContent = "";
  }

  // Total badges
  const mTotal = total_score || 0;
  const iTotal = ind_total_score || 0;
  document.getElementById("hdr-total-market").textContent = formatTotalScore(mTotal) || "—";
  document.getElementById("hdr-total-industry").textContent = formatTotalScore(iTotal) || "—";
  renderScoreMethodology(score_methodology);
  renderTotalScoreRankSummary({
    market_total_rank,
    market_total_universe_size,
    industry_total_rank,
    industry_total_universe_size,
  });
  renderRankSummary({
    market_total_rank,
    market_total_universe_size,
    industry_total_rank,
    industry_total_universe_size,
  });

  // ── Radar charts ────────────────────────────────────────────────────────
  const mRawDim = {};
  const iRawDim = {};
  for (const dim of Object.keys(DIM_NAMES)) {
    const w = _dimWeight(dim);
    mRawDim[dim] = w > 0 ? (dim_scores[dim] || 0) / w : 0;
    iRawDim[dim] = w > 0 ? (ind_dim_scores[dim] || 0) / w : 0;
  }

  drawRadar("radar-market", mRawDim, mTotal, MARKET_COLOR, MARKET_COLOR);
  drawRadar("radar-industry", iRawDim, iTotal, INDUSTRY_COLOR, INDUSTRY_COLOR);

  // ── Dim cards ───────────────────────────────────────────────────────────
  renderDimCards("dim-cards-market", mRawDim, DIM_COLORS);
  renderDimCards("dim-cards-industry", iRawDim, DIM_COLORS_INDUSTRY);

  // ── Sub-table ───────────────────────────────────────────────────────────
  // sd (score_data) contains the flat sub_indicators dict from the snapshot
  renderSubTable(
    sd || {},
    ind_sub_indicators || {},
    raw_sub_indicators || {},
    prev_raw_sub_indicators || {},
    industry_raw_sub_indicator_avgs || {},
    result.sub_indicator_diagnostics || sub_indicator_diagnostics || {},
  );
}

// ── API ─────────────────────────────────────────────────────────────────────
async function fetchScore(market, symbol) {
  const url = `/api/stock-score?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function fetchStockSuggestions(query) {
  const url = `/api/search/stocks?q=${encodeURIComponent(query)}&limit=10`;
  const r = await fetch(url);
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload.results || [];
}

async function fetchStockProfile(symbol) {
  const url = `/api/stock-profile?symbol=${encodeURIComponent(symbol)}`;
  const r = await fetch(url);
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload.profile || null;
}

async function fetchReportHistory(market, symbol) {
  const url = `/api/stock-score-report-history?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`;
  const r = await fetch(url);
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload;
}

async function fetchAiFinancialReport(market, symbol) {
  const url = `/api/stock-score-ai-report?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`;
  const r = await fetch(url);
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload;
}

async function fetchIndustryPeerBenchmark(market, symbol, subKey) {
  const url = `/api/stock-score-industry-peers?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}&sub_key=${encodeURIComponent(subKey)}`;
  const r = await fetch(url);
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload;
}

async function fetchIndustryTotalPeerBenchmark(market, symbol) {
  const url = `/api/stock-score-industry-total-peers?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`;
  const r = await fetch(url);
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload;
}

async function fetchSubdiagExplanation(market, symbol, subKey) {
  const url = `/api/stock-score-subdiag-explanation?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}&sub_key=${encodeURIComponent(subKey)}`;
  const r = await fetch(url);
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload;
}

async function fetchDataUpdateStatus() {
  const r = await fetch('/api/data-update-status');
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload;
}

async function fetchDataUpdateRun() {
  const r = await fetch('/api/data-update-run', { method: 'POST' });
  const payload = await r.json();
  if (!r.ok || !payload.ok) throw new Error(payload.error?.message || `HTTP ${r.status}`);
  return payload;
}

function normalizeMarket(code) {
  if (!code) return null;
  const s = String(code).trim();
  if (s.startsWith("6") || s.startsWith("5") || s.startsWith("9")) return "sh";
  if (s.startsWith("0") || s.startsWith("3")) return "sz";
  if (s.startsWith("4") || s.startsWith("8")) return "bj";
  return null;
}

// ── Search ───────────────────────────────────────────────────────────────────
const stockInputEl = document.getElementById("stock-input");
const stockDropdownEl = document.getElementById("stock-dropdown");
const financialDetailToggleEl = document.getElementById("financial-detail-toggle");
const industryScorePeerTriggerEl = document.querySelector(".industry-score-peer-trigger");
const industryPeerDialogEl = document.getElementById("industry-peer-dialog");
const industryPeerStatusEl = document.getElementById("industry-peer-status");
const industryScorePeerDialogEl = document.getElementById("industry-score-peer-dialog");
const industryScorePeerStatusEl = document.getElementById("industry-score-peer-status");
const searchState = {
  timer: null,
  requestId: 0,
  selectedStock: null,
  suggestions: [],
  recentSearches: [],
  dropdownMode: "suggestions",
  currentStock: null,
  expandedSubDiagKey: null,
  industryPeerRequestId: 0,
  industryScorePeerRequestId: 0,
};

function toStockIdentity(row) {
  if (!row?.market || !row?.symbol) return "";
  return `${String(row.market).toLowerCase()}:${String(row.symbol).trim()}`;
}

function loadRecentStockSearches() {
  try {
    const raw = localStorage.getItem(RECENT_STOCK_SEARCHES_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((row) => row && row.market && row.symbol)
      .map((row) => ({
        market: String(row.market).toLowerCase(),
        symbol: String(row.symbol).trim(),
        stock_name: String(row.stock_name || row.name || row.symbol).trim(),
      }))
      .slice(0, MAX_RECENT_STOCK_SEARCHES);
  } catch {
    return [];
  }
}

function saveRecentStockSearch(stock) {
  if (!stock?.market || !stock?.symbol) return;
  const normalized = {
    market: String(stock.market).toLowerCase(),
    symbol: String(stock.symbol).trim(),
    stock_name: String(stock.stock_name || stock.name || stock.symbol).trim(),
  };
  const identity = toStockIdentity(normalized);
  const nextItems = [
    normalized,
    ...loadRecentStockSearches().filter((row) => toStockIdentity(row) !== identity),
  ].slice(0, MAX_RECENT_STOCK_SEARCHES);
  searchState.recentSearches = nextItems;
  try {
    localStorage.setItem(RECENT_STOCK_SEARCHES_STORAGE_KEY, JSON.stringify(nextItems));
  } catch {
    // Ignore quota/privacy errors and keep in-memory recent list usable.
  }
}

function renderRecentStockSearches() {
  const items = loadRecentStockSearches().slice(0, MAX_RECENT_STOCK_SEARCHES);
  searchState.recentSearches = items;
  searchState.dropdownMode = "recent-search";
  searchState.suggestions = [];
  if (!items.length) {
    stockDropdownEl.innerHTML = '<div class="search-option empty recent-search">暂无最近搜索</div>';
    stockDropdownEl.classList.add("visible");
    return;
  }

  stockDropdownEl.innerHTML = items.map((row, index) => (
    `<button type="button" class="search-option recent-search" data-index="${index}" data-source="recent-search">
      <span class="search-option-main">${row.stock_name}</span>
      <span class="search-option-meta">recent-search · ${row.market.toUpperCase()} · ${row.symbol}</span>
    </button>`
  )).join("");
  stockDropdownEl.classList.add("visible");
}

function renderDataUpdateStatus(payload) {
  const el = document.getElementById('stock-score-data-update-info');
  if (!el) return;
  const financial = payload?.financial_snapshot || {};
  const industry = payload?.industry_valuation || {};
  const latestUpdatedAt = payload?.latest_updated_at || financial.updated_at || industry.updated_at || '暂无';
  const financialDate = financial.updated_at || '暂无';
  const financialPeriod = financial.report_date || '未知期次';
  const industryDate = industry.updated_at || '暂无';
  el.textContent = [
    `最新更新：${latestUpdatedAt}`,
    `财务快照 ${financialPeriod} · ${financialDate}`,
    `行业估值快照 · ${industryDate}`,
  ].join('\n');
  el.classList.remove('muted');
}

async function refreshDataUpdateStatus() {
  const payload = await fetchDataUpdateStatus();
  renderDataUpdateStatus(payload);
  return payload;
}

function rerenderCurrentSubdiagTable() {
  if (!searchState.currentStock?.scoreResult) return;
  renderSubTable(
    searchState.currentStock.scoreResult.score_data || {},
    searchState.currentStock.scoreResult.ind_sub_indicators || {},
    searchState.currentStock.scoreResult.raw_sub_indicators || {},
    searchState.currentStock.scoreResult.prev_raw_sub_indicators || {},
    searchState.currentStock.scoreResult.industry_raw_sub_indicator_avgs || {},
    searchState.currentStock.scoreResult.sub_indicator_diagnostics || {},
  );
}

function currentStockIdentity() {
  if (!searchState.currentStock?.market || !searchState.currentStock?.symbol) return null;
  return `${searchState.currentStock.market}:${searchState.currentStock.symbol}`;
}

function isCurrentStockIdentity(identity) {
  return Boolean(identity) && identity === currentStockIdentity();
}

function setSubdiagExplanationState(subKey, nextState) {
  if (!searchState.currentStock) return;
  if (!searchState.currentStock.subdiagExplanations) {
    searchState.currentStock.subdiagExplanations = {};
  }
  searchState.currentStock.subdiagExplanations[subKey] = normalizeSubdiagExplanationState(nextState);
}

function renderSuggestions(results) {
  searchState.dropdownMode = "suggestions";
  searchState.suggestions = results;
  if (!results.length) {
    stockDropdownEl.innerHTML = '<div class="search-option empty">未找到匹配股票</div>';
    stockDropdownEl.classList.add("visible");
    return;
  }

  stockDropdownEl.innerHTML = results.map((row, index) => (
    `<button type="button" class="search-option" data-index="${index}">
      <span class="search-option-main">${row.stock_name}</span>
      <span class="search-option-meta">${row.market.toUpperCase()} · ${row.symbol}</span>
    </button>`
  )).join("");
  stockDropdownEl.classList.add("visible");
}

function hideSuggestions() {
  stockDropdownEl.classList.remove("visible");
}

function applySuggestion(row) {
  if (!row) return;
  searchState.selectedStock = row;
  stockInputEl.value = `${row.stock_name} (${row.symbol})`;
  hideSuggestions();
  doSearch(row);
}

async function loadSuggestions(query) {
  const trimmed = query.trim();
  const requestId = ++searchState.requestId;
  if (!trimmed) {
    renderRecentStockSearches();
    return;
  }
  try {
    const results = await fetchStockSuggestions(trimmed);
    if (requestId !== searchState.requestId) return;
    renderSuggestions(results.slice(0, 10));
  } catch (err) {
    if (requestId !== searchState.requestId) return;
    stockDropdownEl.innerHTML = '<div class="search-option empty">搜索失败</div>';
    stockDropdownEl.classList.add("visible");
  }
}

document.getElementById("search-btn").addEventListener("click", () => doSearch());
document.getElementById('stock-score-data-update-btn').addEventListener('click', async () => {
  const infoEl = document.getElementById('stock-score-data-update-info');
  const buttonEl = document.getElementById('stock-score-data-update-btn');
  if (infoEl) infoEl.textContent = '正在全量更新数据...';
  if (buttonEl) buttonEl.disabled = true;
  try {
    const payload = await fetchDataUpdateRun();
    renderDataUpdateStatus(payload.data_update_status || payload);
  } catch (error) {
    if (infoEl) infoEl.textContent = `全量更新失败: ${error.message}`;
  } finally {
    if (buttonEl) buttonEl.disabled = false;
  }
});
stockInputEl.addEventListener("input", e => {
  const value = e.target.value;
  if (searchState.selectedStock) {
    const selectedLabel = `${searchState.selectedStock.stock_name} (${searchState.selectedStock.symbol})`;
    if (value !== selectedLabel) searchState.selectedStock = null;
  }
  window.clearTimeout(searchState.timer);
  searchState.timer = window.setTimeout(() => {
    loadSuggestions(value);
  }, SEARCH_DEBOUNCE_MS);
});
stockInputEl.addEventListener("focus", () => {
  renderRecentStockSearches();
});
stockInputEl.addEventListener("click", () => {
  renderRecentStockSearches();
});
stockInputEl.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    if (searchState.selectedStock) {
      doSearch(searchState.selectedStock);
    } else if (searchState.suggestions.length === 1) {
      applySuggestion(searchState.suggestions[0]);
    } else {
      doSearch();
    }
    hideSuggestions();
  }
});
stockDropdownEl.addEventListener("click", e => {
  const option = e.target.closest(".search-option[data-index]");
  if (!option) return;
  const index = Number(option.dataset.index);
  const list = option.dataset.source === "recent-search"
    ? searchState.recentSearches
    : searchState.suggestions;
  applySuggestion(list[index]);
});
document.getElementById("sub-tbody").addEventListener("click", e => {
  const trigger = e.target.closest("[data-subdiag-action][data-subdiag-key]");
  if (!trigger) return;

  const { subdiagAction, subdiagKey } = trigger.dataset;
  if (subdiagAction === "toggle") {
    searchState.expandedSubDiagKey = searchState.expandedSubDiagKey === subdiagKey ? null : subdiagKey;
    rerenderCurrentSubdiagTable();
    return;
  }

  if (subdiagAction === "explain") {
    if (!searchState.currentStock?.market || !searchState.currentStock?.symbol) {
      return;
    }
    const { market, symbol } = searchState.currentStock;
    const stockIdentity = currentStockIdentity();
    setSubdiagExplanationState(subdiagKey, { status: "loading" });
    rerenderCurrentSubdiagTable();
    fetchSubdiagExplanation(market, symbol, subdiagKey)
      .then((payload) => {
        if (!isCurrentStockIdentity(stockIdentity)) return;
        setSubdiagExplanationState(subdiagKey, payload.explanation || { status: "ready" });
        rerenderCurrentSubdiagTable();
      })
      .catch((err) => {
        if (!isCurrentStockIdentity(stockIdentity)) return;
        setSubdiagExplanationState(subdiagKey, {
          status: "error",
          error: `生成失败: ${err.message}`,
        });
        rerenderCurrentSubdiagTable();
      });
    return;
  }

  if (subdiagAction === "industry-peer") {
    if (!searchState.currentStock?.market || !searchState.currentStock?.symbol) {
      return;
    }
    const { market, symbol } = searchState.currentStock;
    const stockIdentity = currentStockIdentity();
    const requestId = ++searchState.industryPeerRequestId;
    document.getElementById("industry-peer-title").textContent = `${SUB_META[subdiagKey]?.name || subdiagKey} 同业对照`;
    industryPeerStatusEl.textContent = "正在加载同业样本...";
    document.getElementById("industry-peer-tbody").innerHTML = "";
    openIndustryPeerDialog();
    fetchIndustryPeerBenchmark(market, symbol, subdiagKey)
      .then((payload) => {
        if (requestId !== searchState.industryPeerRequestId || !isCurrentStockIdentity(stockIdentity)) return;
        renderIndustryPeerDialog(payload);
        openIndustryPeerDialog();
      })
      .catch((err) => {
        if (requestId !== searchState.industryPeerRequestId || !isCurrentStockIdentity(stockIdentity)) return;
        industryPeerStatusEl.textContent = `加载失败: ${err.message}`;
        document.getElementById("industry-peer-tbody").innerHTML = "";
        openIndustryPeerDialog();
      });
  }
});
document.getElementById("industry-peer-close").addEventListener("click", () => closeIndustryPeerDialog());
industryPeerDialogEl.addEventListener("click", (e) => {
  if (e.target === industryPeerDialogEl) closeIndustryPeerDialog();
});
industryScorePeerTriggerEl.addEventListener("click", () => {
  if (!searchState.currentStock?.market || !searchState.currentStock?.symbol) {
    return;
  }
  const { market, symbol } = searchState.currentStock;
  const stockIdentity = currentStockIdentity();
  const requestId = ++searchState.industryScorePeerRequestId;
  document.getElementById("industry-score-peer-title").textContent = "行业总分同业对照";
  industryScorePeerStatusEl.textContent = "正在加载行业总分同业样本...";
  document.getElementById("industry-score-peer-tbody").innerHTML = "";
  openIndustryScorePeerDialog();
  fetchIndustryTotalPeerBenchmark(market, symbol)
    .then((payload) => {
      if (requestId !== searchState.industryScorePeerRequestId || !isCurrentStockIdentity(stockIdentity)) return;
      renderIndustryScorePeerDialog(payload);
      openIndustryScorePeerDialog();
    })
    .catch((err) => {
      if (requestId !== searchState.industryScorePeerRequestId || !isCurrentStockIdentity(stockIdentity)) return;
      industryScorePeerStatusEl.textContent = `加载失败: ${err.message}`;
      document.getElementById("industry-score-peer-tbody").innerHTML = "";
      openIndustryScorePeerDialog();
    });
});
document.getElementById("industry-score-peer-close").addEventListener("click", () => closeIndustryScorePeerDialog());
industryScorePeerDialogEl.addEventListener("click", (e) => {
  if (e.target === industryScorePeerDialogEl) closeIndustryScorePeerDialog();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !industryPeerDialogEl.hidden) {
    closeIndustryPeerDialog();
  }
  if (e.key === "Escape" && !industryScorePeerDialogEl.hidden) {
    closeIndustryScorePeerDialog();
  }
});
document.addEventListener("click", e => {
  if (!e.target.closest(".search-input-wrap")) {
    hideSuggestions();
  }
});
document.getElementById("ai-report-btn").addEventListener("click", async () => {
  if (!searchState.currentStock?.market || !searchState.currentStock?.symbol) {
    setAiReportStatus("请先查询股票后再生成分析", true);
    return;
  }

  setAiReportLoading(true);
  resetAiFinancialReport("AI 正在解读最新一期财报，并优先对比上年同期...");
  try {
    const payload = await fetchAiFinancialReport(searchState.currentStock.market, searchState.currentStock.symbol);
    renderAiFinancialReport(payload.analysis || null);
    renderAiReportRawTable(payload.reports);
    toggleAiReportRawData(Array.isArray(payload.reports) && payload.reports.length > 0);
    searchState.currentStock.aiReportReady = true;
    const latestPeriod = payload.latest_period_label ? formatPeriod(payload.latest_period_label) : "";
    const latestReport = payload.latest_report?.report_date || "";
    const latestLabel = [latestPeriod, latestReport].filter(Boolean).join(" · ");
    setAiReportStatus(`已完成 ${payload.stock_name || searchState.currentStock.symbol} 的AI财报解读${latestLabel ? `（${latestLabel}）` : ""}`);
  } catch (err) {
    console.error(err);
    searchState.currentStock.aiReportReady = false;
    resetAiFinancialReport("AI财报解读生成失败");
    setAiReportStatus(`AI财报解读生成失败: ${err.message}`, true);
  } finally {
    setAiReportLoading(false);
    updateAiReportButtons();
  }
});

document.getElementById("ai-report-copy-btn").addEventListener("click", async () => {
  if (!searchState.currentStock?.aiReportReady) {
    setAiReportStatus("请先生成AI财报解读后再复制", true);
    return;
  }

  const text = buildAiReportSummaryText();
  if (!text) {
    setAiReportStatus("当前没有可复制的AI财报摘要", true);
    return;
  }

  try {
    await copyTextWithFallback(text);
    setAiReportStatus("已复制AI财报摘要");
  } catch (err) {
    setAiReportStatus(`复制失败: ${err.message}`, true);
  }
});

async function doSearch(selectedRow = null) {
  const input = stockInputEl.value.trim();
  if (!input) return;

  let market = null, symbol = null;
  if (selectedRow) {
    market = selectedRow.market;
    symbol = selectedRow.symbol;
  } else if (searchState.selectedStock) {
    market = searchState.selectedStock.market;
    symbol = searchState.selectedStock.symbol;
  } else {
    const parts = input.split(":");
    if (parts.length === 2) {
      market = parts[0].trim();
      symbol = parts[1].trim();
    } else {
      symbol = input.replace(/[^\d]/g, "");
      market = normalizeMarket(symbol);
    }
  }

  if ((!market || !symbol) && searchState.suggestions.length) {
    const fallback = searchState.suggestions[0];
    market = fallback.market;
    symbol = fallback.symbol;
    searchState.selectedStock = fallback;
    stockInputEl.value = `${fallback.stock_name} (${fallback.symbol})`;
  }

  if (!market || !symbol) {
    document.getElementById("loading-msg").textContent = "无法识别股票代码，请输入如 600519 或 sh:600519";
    document.getElementById("loading-msg").style.display = "block";
    document.getElementById("score-header").classList.remove("visible");
    searchState.currentStock = null;
    resetAiFinancialReport("查询股票后可生成分析");
    renderScoreMethodology(null);
    updateAiReportButtons();
    return;
  }

  document.getElementById("loading-msg").textContent = "加载中...";
  document.getElementById("loading-msg").style.display = "block";
  document.getElementById("score-header").classList.remove("visible");
  resetProfileSummary();
  searchState.currentStock = null;
  searchState.expandedSubDiagKey = null;
  searchState.industryPeerRequestId += 1;
  searchState.industryScorePeerRequestId += 1;
  closeIndustryPeerDialog();
  closeIndustryScorePeerDialog();
  industryPeerStatusEl.textContent = INDUSTRY_PEER_STATUS_PLACEHOLDER;
  document.getElementById("industry-peer-title").textContent = "行业同业对照";
  document.getElementById("industry-peer-tbody").innerHTML = "";
  industryScorePeerStatusEl.textContent = INDUSTRY_SCORE_PEER_STATUS_PLACEHOLDER;
  document.getElementById("industry-score-peer-title").textContent = "行业总分同业对照";
  document.getElementById("industry-score-peer-tbody").innerHTML = "";
  resetAiFinancialReport("查询完成后可生成分析");
  renderScoreMethodology(null);
  hideSuggestions();
  updateAiReportButtons();

  try {
    const shouldLoadFinancialDetail = Boolean(financialDetailToggleEl?.checked);
    const [result, profile, reportHistoryPayload] = await Promise.all([
      fetchScore(market, symbol),
      fetchStockProfile(symbol).catch(() => null),
      shouldLoadFinancialDetail ? fetchReportHistory(market, symbol).catch(() => null) : Promise.resolve(null),
    ]);
    renderScore(result);
    renderProfileSummary(profile);
    searchState.currentStock = {
      market,
      symbol,
      stock_name: searchState.selectedStock?.stock_name || result?.stock_name || symbol,
      scoreResult: result,
      aiReportReady: false,
      subdiagExplanations: {},
    };
    saveRecentStockSearch(searchState.currentStock);
    const reportHistory = reportHistoryPayload || {};
    renderAiFinancialReport(null);
    if (shouldLoadFinancialDetail) {
      renderAiReportRawTable(reportHistory.reports || []);
      toggleAiReportRawData(Array.isArray(reportHistory.reports) && reportHistory.reports.length > 0);
      if (reportHistory.latest_report || reportHistory.latest_period_label) {
        const latestPeriod = reportHistory.latest_period_label ? formatPeriod(reportHistory.latest_period_label) : "";
        const latestReport = reportHistory.latest_report?.report_date || "";
        const latestLabel = [latestPeriod, latestReport].filter(Boolean).join(" · ");
        setAiReportStatus(`已加载最近3年报告期数据${latestLabel ? `（最新：${latestLabel}）` : ""}，可继续生成AI解读`);
      } else {
        setAiReportStatus("未加载到最近3年报告期数据，可继续生成AI解读", true);
      }
    } else {
      renderAiReportRawTable([]);
      toggleAiReportRawData(false);
      setAiReportStatus("财务明细未加载，可勾选后重新查询；也可直接生成AI解读");
    }
    updateAiReportButtons();
  } catch (err) {
    console.error(err);
    document.getElementById("loading-msg").textContent = "加载失败: " + err.message;
    resetProfileSummary();
    searchState.currentStock = null;
    resetAiFinancialReport("查询股票后可生成分析");
    updateAiReportButtons();
  }
}

// ── Init ─────────────────────────────────────────────────────────────────────
document.getElementById("loading-msg").style.display = "block";
document.getElementById("loading-msg").textContent = "输入股票代码查询财务评分";
document.getElementById("score-header").classList.remove("visible");
resetProfileSummary();
resetAiFinancialReport();
renderScoreMethodology(null);
updateAiReportButtons();
refreshDataUpdateStatus().catch((error) => {
  const infoEl = document.getElementById('stock-score-data-update-info');
  if (infoEl) infoEl.textContent = `最新更新读取失败: ${error.message}`;
});
