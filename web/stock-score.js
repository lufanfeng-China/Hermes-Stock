// stock-score.js — Financial Score Viewer (dual radar: market + industry)

const SUB_META = {
  roe_ex:           { name: "扣非ROE",        dim: "profitability",  higherBetter: true,  zeroPenalty: true,  unit: "%",  desc: "扣除非经常性损益ROE" },
  net_margin:        { name: "净利率",          dim: "profitability",  higherBetter: true,  zeroPenalty: true,  unit: "%",  desc: "净利润率(非金融)" },
  roe_pct:          { name: "净资产收益率",     dim: "profitability",  higherBetter: true,  zeroPenalty: true,  unit: "%",  desc: "ROE（净资产收益率）" },
  revenue_growth:    { name: "营收增速",         dim: "growth",         higherBetter: true,  zeroPenalty: false, unit: "%",  desc: "营业收入同比" },
  profit_growth:     { name: "净利润增速",        dim: "growth",         higherBetter: true,  zeroPenalty: false, unit: "%",  desc: "净利润同比" },
  ex_profit_growth: { name: "扣非增速",          dim: "growth",         higherBetter: true,  zeroPenalty: false, unit: "%",  desc: "扣非净利润同比" },
  ar_days:          { name: "应收周转天数",      dim: "operating",      higherBetter: false, zeroPenalty: true,  unit: "天", desc: "应收帐款周转天数" },
  inv_days:          { name: "存货周转天数",       dim: "operating",      higherBetter: false, zeroPenalty: true,  unit: "天", desc: "存货周转天数" },
  asset_turn:       { name: "总资产周转率",      dim: "operating",      higherBetter: true,  zeroPenalty: true,  unit: "次", desc: "总资产周转率" },
  ocf_to_profit:    { name: "净现比",             dim: "cashflow",       higherBetter: true,  zeroPenalty: true,  unit: "倍", desc: "经营现金流/净利润" },
  ocf_to_rev:        { name: "现金流/营收",         dim: "cashflow",       higherBetter: true,  zeroPenalty: true,  unit: "%",  desc: "经营现金流/营业收入" },
  free_cf:           { name: "自由现金流",         dim: "cashflow",       higherBetter: true,  zeroPenalty: true,  unit: "元", desc: "经营现金流-资本支出" },
  debt_ratio:        { name: "资产负债率",         dim: "solvency",       higherBetter: false, zeroPenalty: true,  unit: "%",  desc: "资产负债率" },
  current_ratio:     { name: "流动比率",           dim: "solvency",       higherBetter: true,  zeroPenalty: true,  unit: "倍", desc: "流动资产/流动负债" },
  quick_ratio:       { name: "速动比率",           dim: "solvency",       higherBetter: true,  zeroPenalty: true,  unit: "倍", desc: "(流动资产-存货)/流动负债" },
  ar_to_asset:       { name: "应收占比",           dim: "asset_quality",  higherBetter: false, zeroPenalty: true,  unit: "%",  desc: "应收账款/总资产" },
  inv_to_asset:      { name: "存货占比",            dim: "asset_quality",  higherBetter: false, zeroPenalty: true,  unit: "%",  desc: "存货/总资产" },
  goodwill_ratio:    { name: "商誉占比",            dim: "asset_quality",  higherBetter: false, zeroPenalty: true,  unit: "%",  desc: "商誉/总资产" },
  impair_to_rev:     { name: "减值损失率",          dim: "asset_quality",  higherBetter: false, zeroPenalty: true,  unit: "%",  desc: "资产减值损失/营业收入" },
};

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
const RECENT_SEARCHES_STORAGE_KEY = "stock-score-recent-searches";
const RECENT_SEARCHES_LIMIT = 6;
const PROFILE_PLACEHOLDERS = {
  industryL1: "暂无申万一级",
  industryL2: "暂无申万二级",
  concepts: "暂无核心概念",
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

function getRecentSearches() {
  try {
    const raw = localStorage.getItem(RECENT_SEARCHES_STORAGE_KEY);
    const parsed = JSON.parse(raw || "[]");
    return Array.isArray(parsed) ? parsed.filter((item) => item?.market && item?.symbol) : [];
  } catch {
    return [];
  }
}

function setRecentSearches(items) {
  try {
    localStorage.setItem(RECENT_SEARCHES_STORAGE_KEY, JSON.stringify(items));
  } catch {
    // Ignore storage failures to avoid breaking the main search flow.
  }
}

function saveRecentSearch(entry) {
  if (!entry?.market || !entry?.symbol) return;
  const normalized = {
    market: String(entry.market).trim().toLowerCase(),
    symbol: String(entry.symbol).trim(),
    stock_name: String(entry.stock_name || entry.name || entry.symbol).trim(),
  };
  const nextItems = [
    normalized,
    ...getRecentSearches().filter((item) => !(item.market === normalized.market && item.symbol === normalized.symbol)),
  ].slice(0, RECENT_SEARCHES_LIMIT);
  setRecentSearches(nextItems);
  renderRecentSearches();
}

function renderRecentSearches() {
  const container = document.getElementById("recent-searches");
  const items = getRecentSearches();
  if (!items.length) {
    container.innerHTML = '<span class="stock-score-workbench-empty">暂无最近查询</span>';
    return;
  }
  container.innerHTML = items.map((item) => (
    `<button type="button" class="recent-search-chip" data-market="${item.market}" data-symbol="${item.symbol}" data-name="${item.stock_name}">
      ${item.stock_name} · ${item.symbol}
    </button>`
  )).join("");
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

function renderProfileSummary(profile) {
  const coreConcepts = Array.isArray(profile?.core_concepts)
    ? profile.core_concepts
    : Array.isArray(profile?.concepts)
      ? profile.concepts
      : [];
  const conceptText = coreConcepts.length
    ? coreConcepts
      .map((row) => String(row?.concept_name || "").trim())
      .filter(Boolean)
      .slice(0, 4)
      .join(" · ")
    : "";

  const rps20 = formatProfileMetric(profile?.rps_20);
  const rps50 = formatProfileMetric(profile?.rps_50);
  const rps120 = formatProfileMetric(profile?.rps_120);
  const rps250 = formatProfileMetric(profile?.rps_250);
  const industryLevels = resolveIndustryLevels(profile);

  setProfileField("hdr-industry-l1", industryLevels.level1, PROFILE_PLACEHOLDERS.industryL1);
  setProfileField("hdr-industry-l2", industryLevels.level2, PROFILE_PLACEHOLDERS.industryL2);
  setProfileField("hdr-core-concepts", conceptText, PROFILE_PLACEHOLDERS.concepts);
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

function resetProfileSummary() {
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
  if (yoy == null) return "缺少可比上期数据";
  if (yoy === 0) return "与上期基本持平";
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
  const changeSummary = backendDiagnostic?.change?.summary || `当期 ${currentDisplay} / 上期 ${previousDisplay} / 同比 ${formatYoy(yoy)}`;
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
            <div>当期 ${escapeHtml(currentDisplay)} / 上期 ${escapeHtml(previousDisplay)} / 同比 ${yoyBadge}</div>
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

function renderSubTable(scoreData, indSubIndicators, rawSubIndicators, prevRawSubIndicators, subIndicatorDiagnostics = {}) {
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
    const yoy = computeYoy(key, rawVal, prevRawSubIndicators || {});
    const currentDisplay = key === "free_cf" ? formatAmountYi(rawVal) : formatRawValue(key, rawVal);
    const previousDisplay = key === "free_cf" ? formatAmountYi(prevVal) : formatRawValue(key, prevVal);
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
      <td class="sub-period-current">${currentDisplay}</td>
      <td class="sub-period-previous">${previousDisplay}</td>
      <td class="sub-period-yoy"><span class="${yoyClassName(yoy)}">${formatYoy(yoy)}</span></td>
      <td class="sub-score ${scoreColor(val)}" style="color:${MARKET_COLOR};">${val.toFixed(1)}</td>
      <td class="sub-score ${scoreColor(indVal)}" style="color:${INDUSTRY_COLOR};">${indVal.toFixed(1)}</td>
      <td class="sub-rank">${meta.desc}</td>`;
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
  document.getElementById("hdr-total-market").innerHTML =
    `${mTotal.toFixed(1)}<span class="max" style="color:#555577">/100</span>`;
  document.getElementById("hdr-total-industry").innerHTML =
    `${iTotal.toFixed(1)}<span class="max" style="color:#555577">/100</span>`;
  renderScoreMethodology(score_methodology);
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
  renderSubTable(sd || {}, ind_sub_indicators || {}, raw_sub_indicators || {}, prev_raw_sub_indicators || {}, result.sub_indicator_diagnostics || sub_indicator_diagnostics || {});
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

async function fetchSubdiagExplanation(market, symbol, subKey) {
  const url = `/api/stock-score-subdiag-explanation?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}&sub_key=${encodeURIComponent(subKey)}`;
  const r = await fetch(url);
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
const recentSearchesEl = document.getElementById("recent-searches");
const financialDetailToggleEl = document.getElementById("financial-detail-toggle");
const searchState = {
  timer: null,
  requestId: 0,
  selectedStock: null,
  suggestions: [],
  currentStock: null,
  expandedSubDiagKey: null,
};

function rerenderCurrentSubdiagTable() {
  if (!searchState.currentStock?.scoreResult) return;
  renderSubTable(
    searchState.currentStock.scoreResult.score_data || {},
    searchState.currentStock.scoreResult.ind_sub_indicators || {},
    searchState.currentStock.scoreResult.raw_sub_indicators || {},
    searchState.currentStock.scoreResult.prev_raw_sub_indicators || {},
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

function triggerSearchFromEntry(entry) {
  if (!entry?.market || !entry?.symbol) return;
  const row = {
    market: String(entry.market).trim().toLowerCase(),
    symbol: String(entry.symbol).trim(),
    stock_name: String(entry.stock_name || entry.symbol).trim(),
  };
  searchState.selectedStock = row;
  stockInputEl.value = `${row.stock_name} (${row.symbol})`;
  hideSuggestions();
  doSearch(row);
}

async function loadSuggestions(query) {
  const trimmed = query.trim();
  const requestId = ++searchState.requestId;
  if (!trimmed) {
    hideSuggestions();
    searchState.suggestions = [];
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
  if (searchState.suggestions.length) {
    stockDropdownEl.classList.add("visible");
  }
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
  applySuggestion(searchState.suggestions[Number(option.dataset.index)]);
});
recentSearchesEl.addEventListener("click", e => {
  const button = e.target.closest(".recent-search-chip[data-market][data-symbol]");
  if (!button) return;
  triggerSearchFromEntry({
    market: button.dataset.market,
    symbol: button.dataset.symbol,
    stock_name: button.dataset.name,
  });
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
    saveRecentSearch({
      market,
      symbol,
      stock_name: searchState.currentStock.stock_name,
    });
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
renderRecentSearches();
updateAiReportButtons();
