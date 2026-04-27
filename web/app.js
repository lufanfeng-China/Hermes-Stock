const DEFAULT_SYMBOL = "601600";
const PRESET_WINDOWS = [20, 60, 120];
const MIN_WINDOW = 10;
const DEFAULT_VOLUME_MA_WINDOW = 50;
const CHART_WIDTH = 640;
const CHART_HEIGHT = 220;
const CHART_PADDING = { top: 18, right: 68, bottom: 34, left: 16 };
const SERIES_CONFIG = [
  {
    svgId: "#close-chart",
    summaryId: "#close-summary",
    valueKey: "close",
    color: "#7ce0c3",
    tooltipLabel: "Close",
    isVolume: false,
  },
  {
    svgId: "#open-chart",
    summaryId: "#open-summary",
    metricIdPrefix: "open-15m",
    valueKey: "open_15m_volume",
    color: "#52b3ff",
    tooltipLabel: "Open 15m",
    isVolume: true,
  },
  {
    svgId: "#window-chart",
    summaryId: "#window-summary",
    metricIdPrefix: "window",
    valueKey: "window_1430_1445_volume",
    color: "#f6c26b",
    tooltipLabel: "14:30-14:45",
    isVolume: true,
  },
];

const {
  clamp,
  resolveViewport,
  zoomViewport,
  panViewport,
  deriveWindowSelection,
  scaleVolumeMillions,
  computeMovingAverageSeries,
} = window.StockViewport;
const { formatAuxiliaryBucketLabel } = window.ProfileUtils;

const form = document.querySelector("#symbol-form");
const symbolInput = document.querySelector("#symbol-input");
const statusEl = document.querySelector("#status");
const stockSearchForm = document.querySelector("#stock-search-form");
const stockSearchInput = document.querySelector("#stock-search-input");
const stockSearchMetaEl = document.querySelector("#stock-search-meta");
const stockSearchResultsEl = document.querySelector("#stock-search-results");
const conceptSearchForm = document.querySelector("#concept-search-form");
const conceptSearchInput = document.querySelector("#concept-search-input");
const conceptSearchMetaEl = document.querySelector("#concept-search-meta");
const conceptSearchResultsEl = document.querySelector("#concept-search-results");
const profileTitleEl = document.querySelector("#profile-title");
const profileMetaEl = document.querySelector("#profile-meta");
const profileSymbolEl = document.querySelector("#profile-symbol");
const profileNameEl = document.querySelector("#profile-name");
const profileInitialsEl = document.querySelector("#profile-initials");
const profileIndustryEl = document.querySelector("#profile-industry");
const profileConceptCountEl = document.querySelector("#profile-concept-count");
const profileConceptsEl = document.querySelector("#profile-concepts");
const zoomControlsEl = document.querySelector("#zoom-controls");
const zoomButtons = Array.from(document.querySelectorAll(".zoom-button"));
const windowSliderEl = document.querySelector("#window-slider");
const windowCaptionEl = document.querySelector("#window-caption");
const volumeMaWindowEl = document.querySelector("#volume-ma-window");

const dashboardState = {
  payload: null,
  profile: null,
  visibleWindow: 120,
  windowStart: 0,
  hoveredIndex: null,
  dragState: null,
  volumeMaWindow: DEFAULT_VOLUME_MA_WINDOW,
};
const searchState = {
  stockRequestId: 0,
  conceptRequestId: 0,
  stockTimer: null,
  conceptTimer: null,
};

const charts = SERIES_CONFIG.map((config) => {
  const svg = document.querySelector(config.svgId);
  const card = svg.closest(".chart-card");
  const tooltip = card.querySelector(".chart-tooltip");
  return { ...config, svg, card, tooltip };
});

function formatNumber(value) {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function formatIntegerNumber(value) {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatVolumeMillions(value) {
  return `${formatNumber(scaleVolumeMillions(value))} M`;
}

function formatSeriesValue(chart, value) {
  return chart.isVolume ? formatVolumeMillions(value) : formatNumber(value);
}

function getDisplayValue(chart, value) {
  return chart.isVolume ? scaleVolumeMillions(value) : value;
}

function formatShortDate(value) {
  if (!value) {
    return "-";
  }
  const [year, month, day] = value.split("-");
  return `${year.slice(2)}/${month}/${day}`;
}

function formatLongDate(value) {
  if (!value) {
    return "-";
  }
  const [year, month, day] = value.split("-");
  return `${year}/${month}/${day}`;
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function setSearchMeta(element, message, isError = false) {
  element.textContent = message;
  element.classList.toggle("error", isError);
}

function setMetric(idPrefix, value, meta) {
  const chart = charts.find((item) => item.metricIdPrefix === idPrefix);
  document.querySelector(`#${idPrefix}-value`).textContent = chart ? formatSeriesValue(chart, value) : formatNumber(value);
  document.querySelector(`#${idPrefix}-meta`).textContent = meta;
}

function setSummary(id, chart, latest, series, movingAverage) {
  const first = series[0];
  const delta = latest - first;
  const sign = delta >= 0 ? "+" : "-";
  const summaryParts = [
    `${formatSeriesValue(chart, latest)}  ${sign}${formatSeriesValue(chart, Math.abs(delta))}`,
  ];
  if (chart.isVolume && Number.isFinite(movingAverage)) {
    summaryParts.push(`MA${dashboardState.volumeMaWindow} ${formatSeriesValue(chart, movingAverage)}`);
  }
  document.querySelector(id).textContent = summaryParts.join(" · ");
}

function getViewport(totalCount) {
  return resolveViewport(totalCount, dashboardState.visibleWindow, dashboardState.windowStart);
}

function setViewportFromResolved(nextViewport) {
  if (!dashboardState.payload) {
    return;
  }

  const totalCount = dashboardState.payload.history.length;
  if (nextViewport.size >= totalCount) {
    dashboardState.visibleWindow = "all";
    dashboardState.windowStart = 0;
    return;
  }

  dashboardState.visibleWindow = nextViewport.size;
  dashboardState.windowStart = nextViewport.start;
}

function syncWindowControls(history) {
  const totalCount = history.length;
  const viewport = getViewport(totalCount);

  dashboardState.windowStart = viewport.start;
  dashboardState.visibleWindow = deriveWindowSelection(viewport, PRESET_WINDOWS) ?? viewport.size;

  zoomButtons.forEach((button) => {
    const value = button.dataset.window === "all" ? "all" : Number(button.dataset.window);
    button.classList.toggle("active", value === dashboardState.visibleWindow);
  });

  const canPan = !viewport.isAll && totalCount > viewport.size;
  windowSliderEl.disabled = !canPan;
  windowSliderEl.min = "0";
  windowSliderEl.max = String(viewport.maxStart);
  windowSliderEl.value = String(viewport.start);

  const firstDay = history[viewport.start]?.trading_day;
  const lastDay = history[Math.max(viewport.end - 1, 0)]?.trading_day;
  windowCaptionEl.textContent = `${formatShortDate(firstDay)} -> ${formatShortDate(lastDay)} · ${viewport.size}/${totalCount} sessions`;
}

function buildTicks(min, max, count) {
  if (count <= 1 || min === max) {
    return [min];
  }

  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, index) => min + step * index);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function isChartSupportedMarket(market) {
  return market === "sh" || market === "sz";
}

function renderStockSearchResults(results, query) {
  if (!query.trim()) {
    stockSearchResultsEl.innerHTML = '<p class="result-empty">Enter a code, Chinese name, or initials.</p>';
    return;
  }
  if (!results.length) {
    stockSearchResultsEl.innerHTML = '<p class="result-empty">No matching stocks.</p>';
    return;
  }

  stockSearchResultsEl.innerHTML = results
    .map((row) => {
      const supported = isChartSupportedMarket(row.market);
      return `
        <button
          type="button"
          class="result-row stock-result-row"
          data-symbol="${escapeHtml(row.symbol)}"
          data-market="${escapeHtml(row.market)}"
          ${supported ? "" : 'disabled aria-disabled="true"'}
        >
          <span class="result-main">
            <strong>${escapeHtml(row.symbol)}</strong>
            <span>${escapeHtml(row.stock_name)}</span>
          </span>
          <span class="result-side">
            <span>${escapeHtml(row.market.toUpperCase())}</span>
            <span>${escapeHtml((row.name_initials || "").toUpperCase())}</span>
          </span>
        </button>
      `;
    })
    .join("");
}

function renderConceptSearchResults(results, query) {
  if (!query.trim()) {
    conceptSearchResultsEl.innerHTML = '<p class="result-empty">Search a concept to inspect member stocks.</p>';
    return;
  }
  if (!results.length) {
    conceptSearchResultsEl.innerHTML = '<p class="result-empty">No matching concepts.</p>';
    return;
  }

  conceptSearchResultsEl.innerHTML = results
    .map(
      (concept) => `
        <section class="concept-result-card">
          <div class="concept-result-header">
            <div>
              <h3>${escapeHtml(concept.concept_name)}</h3>
              <p>${escapeHtml(concept.concept_id)}</p>
            </div>
            <span class="concept-count">${escapeHtml(String(concept.member_count))} members</span>
          </div>
          <div class="concept-member-list">
            ${concept.members
              .map((member) => {
                const supported = isChartSupportedMarket(member.market);
                return `
                  <button
                    type="button"
                    class="result-row concept-member-row"
                    data-symbol="${escapeHtml(member.symbol)}"
                    data-market="${escapeHtml(member.market)}"
                    ${supported ? "" : 'disabled aria-disabled="true"'}
                  >
                    <span class="result-main">
                      <strong>${escapeHtml(member.symbol)}</strong>
                      <span>${escapeHtml(member.stock_name || "-")}</span>
                    </span>
                    <span class="result-side result-side-wide">
                      <span>${escapeHtml(member.market.toUpperCase())}</span>
                      <span>${escapeHtml(member.industry_display || "-")}</span>
                    </span>
                  </button>
                `;
              })
              .join("")}
          </div>
        </section>
      `
    )
    .join("");
}

function renderStockProfile(profile) {
  if (!profile) {
    profileTitleEl.textContent = "Awaiting stock load";
    profileMetaEl.textContent = "Industry and concepts appear after a stock loads.";
    profileSymbolEl.textContent = "-";
    profileNameEl.textContent = "-";
    profileInitialsEl.textContent = "-";
    profileIndustryEl.textContent = "-";
    profileConceptCountEl.textContent = "0";
    profileConceptsEl.innerHTML = '<span class="result-empty">No concepts loaded.</span>';
    return;
  }

  profileTitleEl.textContent = `${profile.stock_name || "-"} · ${profile.symbol || "-"}`;
  profileMetaEl.textContent = `${(profile.market || "-").toUpperCase()} market profile`;
  profileSymbolEl.textContent = profile.symbol || "-";
  profileNameEl.textContent = profile.stock_name || "-";
  profileInitialsEl.textContent = (profile.name_initials || "-").toUpperCase();
  profileIndustryEl.textContent = profile.industry_display || "-";
  profileConceptCountEl.textContent = String(profile.concept_count || 0);
  const coreConcepts = Array.isArray(profile.core_concepts)
    ? profile.core_concepts
    : Array.isArray(profile.concepts)
      ? profile.concepts
      : [];
  const auxiliaryGroups = profile.auxiliary_concepts && typeof profile.auxiliary_concepts === "object"
    ? Object.entries(profile.auxiliary_concepts).filter(([, concepts]) => Array.isArray(concepts) && concepts.length)
    : [];
  if (!coreConcepts.length && !auxiliaryGroups.length) {
    profileConceptsEl.innerHTML = '<span class="result-empty">No concepts tagged for this stock.</span>';
    return;
  }
  const coreMarkup = coreConcepts.length
    ? `
      <div class="tag-list">
        ${coreConcepts
          .map((concept) => `<span class="concept-tag">${escapeHtml(concept.concept_name || "-")}</span>`)
          .join("")}
      </div>
    `
    : '<span class="result-empty">No core concepts for default display.</span>';
  const auxiliaryMarkup = auxiliaryGroups.length
    ? `
      <section class="profile-auxiliary">
        <div class="profile-auxiliary-header">
          <span class="profile-label">More tags</span>
        </div>
        <div class="profile-auxiliary-groups">
          ${auxiliaryGroups
            .map(
              ([bucket, concepts]) => `
                <div class="auxiliary-group">
                  <span class="auxiliary-group-label">${escapeHtml(formatAuxiliaryBucketLabel(bucket))}</span>
                  <div class="tag-list">
                    ${concepts
                      .map((concept) => `<span class="concept-tag concept-tag-aux">${escapeHtml(concept.concept_name || "-")}</span>`)
                      .join("")}
                  </div>
                </div>
              `
            )
            .join("")}
        </div>
      </section>
    `
    : "";
  profileConceptsEl.innerHTML = `${coreMarkup}${auxiliaryMarkup}`;
}

async function fetchJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error?.message || "Request failed");
  }
  return payload;
}

async function performStockSearch(query) {
  const trimmed = query.trim();
  const requestId = ++searchState.stockRequestId;
  if (!trimmed) {
    setSearchMeta(stockSearchMetaEl, "TNF-backed local search");
    renderStockSearchResults([], "");
    return;
  }

  setSearchMeta(stockSearchMetaEl, `Searching ${trimmed}...`);
  try {
    const payload = await fetchJson(`/api/search/stocks?q=${encodeURIComponent(trimmed)}&limit=12`);
    if (requestId !== searchState.stockRequestId) {
      return;
    }
    setSearchMeta(stockSearchMetaEl, `${payload.count} stock matches`);
    renderStockSearchResults(payload.results, trimmed);
  } catch (error) {
    if (requestId !== searchState.stockRequestId) {
      return;
    }
    setSearchMeta(stockSearchMetaEl, error.message, true);
    stockSearchResultsEl.innerHTML = '<p class="result-empty">Search failed.</p>';
  }
}

async function performConceptSearch(query) {
  const trimmed = query.trim();
  const requestId = ++searchState.conceptRequestId;
  if (!trimmed) {
    setSearchMeta(conceptSearchMetaEl, "Derived dataset search");
    renderConceptSearchResults([], "");
    return;
  }

  setSearchMeta(conceptSearchMetaEl, `Searching ${trimmed}...`);
  try {
    const payload = await fetchJson(`/api/search/concepts?q=${encodeURIComponent(trimmed)}&limit=8`);
    if (requestId !== searchState.conceptRequestId) {
      return;
    }
    setSearchMeta(conceptSearchMetaEl, `${payload.count} concept matches`);
    renderConceptSearchResults(payload.results, trimmed);
  } catch (error) {
    if (requestId !== searchState.conceptRequestId) {
      return;
    }
    setSearchMeta(conceptSearchMetaEl, error.message, true);
    conceptSearchResultsEl.innerHTML = '<p class="result-empty">Search failed.</p>';
  }
}

function queueSearch(kind, query) {
  const timerKey = kind === "stock" ? "stockTimer" : "conceptTimer";
  window.clearTimeout(searchState[timerKey]);
  searchState[timerKey] = window.setTimeout(() => {
    if (kind === "stock") {
      performStockSearch(query);
    } else {
      performConceptSearch(query);
    }
  }, 160);
}

function getRelativePoint(svg, event) {
  const rect = svg.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
    width: rect.width || 1,
    height: rect.height || 1,
  };
}

function updateHoverFromEvent(event, svg) {
  if (!dashboardState.payload) {
    return;
  }

  const viewport = getViewport(dashboardState.payload.history.length);
  const { x, width } = getRelativePoint(svg, event);
  const plotWidth = width - CHART_PADDING.left - CHART_PADDING.right;
  const normalized = clamp((x - CHART_PADDING.left) / Math.max(plotWidth, 1), 0, 1);
  const localIndex = Math.round(normalized * Math.max(viewport.size - 1, 0));
  dashboardState.hoveredIndex = viewport.start + localIndex;
  renderDashboard();
}

function clearHover() {
  if (dashboardState.hoveredIndex === null) {
    return;
  }
  dashboardState.hoveredIndex = null;
  renderDashboard();
}

function renderChart(chart, rows, viewport, history, movingAverageRows) {
  const { svg, tooltip, valueKey, color, tooltipLabel } = chart;
  const width = CHART_WIDTH;
  const height = CHART_HEIGHT;
  const plotWidth = width - CHART_PADDING.left - CHART_PADDING.right;
  const plotHeight = height - CHART_PADDING.top - CHART_PADDING.bottom;
  const baseY = height - CHART_PADDING.bottom;
  const values = rows.map((row) => getDisplayValue(chart, row[valueKey]));
  const movingAverageValues = (movingAverageRows || []).map((value) =>
    value === null ? null : getDisplayValue(chart, value)
  );

  if (!rows.length) {
    svg.innerHTML = "";
    tooltip.hidden = true;
    return;
  }

  const domainValues = values.concat(movingAverageValues.filter((value) => Number.isFinite(value)));
  const min = Math.min(...domainValues);
  const max = Math.max(...domainValues);
  const paddedMinBase = min === max ? min * 0.98 : min - (max - min) * 0.08;
  const paddedMin = chart.isVolume ? Math.max(0, paddedMinBase) : paddedMinBase;
  const paddedMax = min === max ? max * 1.02 || 1 : max + (max - min) * 0.08;
  const valueRange = paddedMax - paddedMin || 1;
  const stepX = rows.length === 1 ? 0 : plotWidth / (rows.length - 1);
  const getX = (index) => CHART_PADDING.left + stepX * index;
  const getY = (value) => CHART_PADDING.top + plotHeight - ((value - paddedMin) / valueRange) * plotHeight;
  const points = values.map((value, index) => `${getX(index)},${getY(value)}`);
  const movingAveragePoints = movingAverageValues
    .map((value, index) => (value === null ? null : `${getX(index)},${getY(value)}`))
    .filter(Boolean);
  const areaPoints = [
    `${CHART_PADDING.left},${baseY}`,
    ...points,
    `${CHART_PADDING.left + plotWidth},${baseY}`,
  ].join(" ");

  const yTicks = buildTicks(paddedMin, paddedMax, 5);
  const xTickCount = Math.max(2, Math.min(6, rows.length));
  const xTickIndexes = Array.from({ length: xTickCount }, (_, index) => {
    if (xTickCount === 1) {
      return 0;
    }
    return Math.round((index * (rows.length - 1)) / (xTickCount - 1));
  }).filter((value, index, source) => source.indexOf(value) === index);

  const yGrid = yTicks.map((tick) => {
    const y = getY(tick);
    return `
      <line class="grid-line" x1="${CHART_PADDING.left}" y1="${y}" x2="${width - CHART_PADDING.right}" y2="${y}"></line>
      <text class="axis-label axis-label-y" x="${width - CHART_PADDING.right + 10}" y="${y + 4}">${chart.isVolume ? `${formatIntegerNumber(tick)} M` : formatIntegerNumber(tick)}</text>
    `;
  }).join("");

  const xGrid = xTickIndexes.map((index) => {
    const x = getX(index);
    return `
      <line class="grid-line grid-line-vertical" x1="${x}" y1="${CHART_PADDING.top}" x2="${x}" y2="${baseY}"></line>
      <text class="axis-label axis-label-x" x="${x}" y="${height - 10}" text-anchor="middle">${formatShortDate(rows[index].trading_day)}</text>
    `;
  }).join("");

  const localHoverIndex =
    dashboardState.hoveredIndex === null ? null : dashboardState.hoveredIndex - viewport.start;
  const hoverActive = localHoverIndex !== null && localHoverIndex >= 0 && localHoverIndex < rows.length;
  const hoverRow = hoverActive ? rows[localHoverIndex] : null;
  const hoverX = hoverActive ? getX(localHoverIndex) : 0;
  const hoverValue = hoverActive ? getDisplayValue(chart, hoverRow[valueKey]) : 0;
  const hoverY = hoverActive ? getY(hoverValue) : 0;
  const hoverMovingAverageRaw = hoverActive && movingAverageRows ? movingAverageRows[localHoverIndex] : null;

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = `
    <rect class="chart-frame" x="${CHART_PADDING.left}" y="${CHART_PADDING.top}" width="${plotWidth}" height="${plotHeight}" rx="8"></rect>
    ${yGrid}
    ${xGrid}
    <line class="axis-line" x1="${CHART_PADDING.left}" y1="${baseY}" x2="${width - CHART_PADDING.right}" y2="${baseY}"></line>
    <polyline points="${areaPoints}" fill="${color}20" stroke="none"></polyline>
    <polyline points="${points.join(" ")}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"></polyline>
    ${
      chart.isVolume && movingAveragePoints.length
        ? `<polyline class="ma-line" points="${movingAveragePoints.join(" ")}" fill="none" stroke="${color}" stroke-width="1.5" stroke-dasharray="6 5" stroke-linejoin="round" stroke-linecap="round"></polyline>`
        : ""
    }
    <circle class="latest-dot" cx="${getX(rows.length - 1)}" cy="${getY(values.at(-1))}" r="3.5" fill="${color}"></circle>
    ${
      hoverActive
        ? `
          <line class="crosshair-line" x1="${hoverX}" y1="${CHART_PADDING.top}" x2="${hoverX}" y2="${baseY}"></line>
          <line class="crosshair-line" x1="${CHART_PADDING.left}" y1="${hoverY}" x2="${width - CHART_PADDING.right}" y2="${hoverY}"></line>
          <circle class="hover-dot" cx="${hoverX}" cy="${hoverY}" r="4" fill="${color}"></circle>
        `
        : ""
    }
  `;

  if (hoverActive) {
    const tooltipLeft = clamp((hoverX / width) * 100, 12, 84);
    tooltip.hidden = false;
    tooltip.style.left = `${tooltipLeft}%`;
    tooltip.innerHTML = `
      <div class="tooltip-date">${escapeHtml(formatLongDate(hoverRow.trading_day))}</div>
      <div class="tooltip-value"><span>${escapeHtml(tooltipLabel)}</span><strong>${escapeHtml(formatSeriesValue(chart, hoverRow[valueKey]))}</strong></div>
      ${
        chart.isVolume
          ? `<div class="tooltip-value tooltip-value-ma"><span>${escapeHtml(`MA${dashboardState.volumeMaWindow}`)}</span><strong>${escapeHtml(
              hoverMovingAverageRaw === null ? "-" : formatSeriesValue(chart, hoverMovingAverageRaw)
            )}</strong></div>`
          : ""
      }
    `;
  } else {
    tooltip.hidden = true;
  }

  svg.classList.toggle("is-pannable", !viewport.isAll && history.length > viewport.size);
}

function renderDashboard() {
  const payload = dashboardState.payload;
  if (!payload) {
    return;
  }

  const history = payload.history;
  const latest = payload.latest_metrics;
  const viewport = getViewport(history.length);
  const visibleRows = history.slice(viewport.start, viewport.end);
  const openMovingAverage = computeMovingAverageSeries(
    history.map((row) => row.open_15m_volume),
    dashboardState.volumeMaWindow
  );
  const windowMovingAverage = computeMovingAverageSeries(
    history.map((row) => row.window_1430_1445_volume),
    dashboardState.volumeMaWindow
  );
  const movingAverageByKey = {
    open_15m_volume: openMovingAverage,
    window_1430_1445_volume: windowMovingAverage,
  };

  if (dashboardState.hoveredIndex !== null) {
    dashboardState.hoveredIndex = clamp(dashboardState.hoveredIndex, viewport.start, viewport.end - 1);
  }

  setMetric(
    "open-15m",
    latest.open_15m_volume,
    `${payload.latest_trading_day} · ${latest.open_15m_bar_count} bars`
  );
  setMetric(
    "window",
    latest.window_1430_1445_volume,
    `${payload.latest_trading_day} · ${latest.window_1430_1445_bar_count} bars`
  );

  const closeSeries = history.map((row) => row.close);
  const openSeries = history.map((row) => row.open_15m_volume);
  const windowSeries = history.map((row) => row.window_1430_1445_volume);

  setSummary("#close-summary", charts[0], closeSeries.at(-1), closeSeries);
  setSummary("#open-summary", charts[1], openSeries.at(-1), openSeries, openMovingAverage.at(-1));
  setSummary("#window-summary", charts[2], windowSeries.at(-1), windowSeries, windowMovingAverage.at(-1));

  syncWindowControls(history);
  charts.forEach((chart) =>
    renderChart(
      chart,
      visibleRows,
      viewport,
      history,
      chart.isVolume ? movingAverageByKey[chart.valueKey].slice(viewport.start, viewport.end) : null
    )
  );

  setStatus(
    `${payload.market.toUpperCase()} ${payload.symbol} · ${history.length} trading days ending ${payload.latest_trading_day} · viewing ${visibleRows.length}`
  );
}

async function loadSymbol(symbol) {
  setStatus(`Loading ${symbol}…`);
  try {
    const [payload, profilePayload] = await Promise.all([
      fetchJson(`/api/stock-window-volume?symbol=${encodeURIComponent(symbol)}`),
      fetchJson(`/api/stock-profile?symbol=${encodeURIComponent(symbol)}`),
    ]);

    dashboardState.payload = payload;
    dashboardState.profile = profilePayload.profile;
    dashboardState.hoveredIndex = null;
    dashboardState.dragState = null;

    if (payload.history.length >= 120) {
      dashboardState.visibleWindow = 120;
      dashboardState.windowStart = Math.max(0, payload.history.length - 120);
    } else {
      dashboardState.visibleWindow = "all";
      dashboardState.windowStart = 0;
    }

    renderStockProfile(dashboardState.profile);
    renderDashboard();
    symbolInput.value = symbol;
  } catch (error) {
    renderStockProfile(dashboardState.profile);
    setStatus(`Load failed: ${error.message}`, true);
  }
}

function applyWheelZoom(event) {
  if (!dashboardState.payload) {
    return;
  }

  event.preventDefault();
  const history = dashboardState.payload.history;
  const totalCount = history.length;
  const currentViewport = getViewport(totalCount);
  const currentSize = currentViewport.size || totalCount;
  const zoomFactor = event.deltaY < 0 ? 0.85 : 1.15;
  const proposedSize = clamp(Math.round(currentSize * zoomFactor), MIN_WINDOW, totalCount);
  if (proposedSize === currentSize && !currentViewport.isAll) {
    return;
  }

  const { x, width } = getRelativePoint(event.currentTarget, event);
  const plotWidth = width - CHART_PADDING.left - CHART_PADDING.right;
  const anchorRatio = clamp((x - CHART_PADDING.left) / Math.max(plotWidth, 1), 0, 1);
  const nextViewport = zoomViewport({
    totalCount,
    viewport: currentViewport,
    nextSize: proposedSize,
    anchorRatio,
  });

  setViewportFromResolved(nextViewport);
  renderDashboard();
}

function beginDrag(event) {
  if (!dashboardState.payload) {
    return;
  }

  const viewport = getViewport(dashboardState.payload.history.length);
  if (viewport.isAll) {
    return;
  }

  dashboardState.dragState = {
    pointerId: event.pointerId,
    startClientX: event.clientX,
    startWindowStart: viewport.start,
  };
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.classList.add("is-dragging");
}

function updateDrag(event) {
  if (!dashboardState.payload || !dashboardState.dragState) {
    return;
  }

  const viewport = getViewport(dashboardState.payload.history.length);
  const rect = event.currentTarget.getBoundingClientRect();
  const plotWidth = rect.width - CHART_PADDING.left - CHART_PADDING.right;
  const deltaX = event.clientX - dashboardState.dragState.startClientX;
  const deltaPoints = (-deltaX / Math.max(plotWidth, 1)) * viewport.size;
  const nextViewport = panViewport({
    totalCount: dashboardState.payload.history.length,
    viewport: { start: dashboardState.dragState.startWindowStart, size: viewport.size },
    deltaPoints,
  });

  setViewportFromResolved(nextViewport);
  updateHoverFromEvent(event, event.currentTarget);
}

function endDrag(event) {
  if (!dashboardState.dragState) {
    return;
  }

  event.currentTarget.classList.remove("is-dragging");
  if (event.currentTarget.hasPointerCapture?.(dashboardState.dragState.pointerId)) {
    event.currentTarget.releasePointerCapture(dashboardState.dragState.pointerId);
  }
  dashboardState.dragState = null;
}

zoomControlsEl.addEventListener("click", (event) => {
  const button = event.target.closest(".zoom-button");
  if (!button || !dashboardState.payload) {
    return;
  }

  const totalCount = dashboardState.payload.history.length;
  const nextWindow = button.dataset.window === "all" ? "all" : Number(button.dataset.window);
  const currentViewport = getViewport(totalCount);
  const currentEnd = currentViewport.end;

  dashboardState.visibleWindow = nextWindow;
  dashboardState.windowStart =
    nextWindow === "all" ? 0 : Math.max(0, currentEnd - Math.min(nextWindow, totalCount));
  renderDashboard();
});

windowSliderEl.addEventListener("input", () => {
  if (!dashboardState.payload || dashboardState.visibleWindow === "all") {
    return;
  }
  dashboardState.windowStart = Number(windowSliderEl.value);
  renderDashboard();
});

volumeMaWindowEl.value = String(DEFAULT_VOLUME_MA_WINDOW);
volumeMaWindowEl.addEventListener("input", () => {
  const nextValue = Number(volumeMaWindowEl.value);
  if (!Number.isInteger(nextValue) || nextValue < 1) {
    return;
  }
  dashboardState.volumeMaWindow = nextValue;
  if (dashboardState.payload) {
    renderDashboard();
  }
});
volumeMaWindowEl.addEventListener("change", () => {
  if (!Number.isInteger(Number(volumeMaWindowEl.value)) || Number(volumeMaWindowEl.value) < 1) {
    volumeMaWindowEl.value = String(dashboardState.volumeMaWindow);
  }
});

charts.forEach((chart) => {
  chart.svg.addEventListener("wheel", applyWheelZoom, { passive: false });
  chart.svg.addEventListener("pointerdown", beginDrag);
  chart.svg.addEventListener("pointermove", (event) => {
    if (dashboardState.dragState) {
      updateDrag(event);
      return;
    }
    updateHoverFromEvent(event, chart.svg);
  });
  chart.svg.addEventListener("pointerleave", () => {
    if (!dashboardState.dragState) {
      clearHover();
    }
  });
  chart.svg.addEventListener("pointerup", endDrag);
  chart.svg.addEventListener("pointercancel", endDrag);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const symbol = symbolInput.value.trim() || DEFAULT_SYMBOL;
  loadSymbol(symbol);
});

stockSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  performStockSearch(stockSearchInput.value);
});

stockSearchInput.addEventListener("input", () => {
  queueSearch("stock", stockSearchInput.value);
});

stockSearchResultsEl.addEventListener("click", (event) => {
  const row = event.target.closest(".stock-result-row");
  if (!row || row.disabled) {
    return;
  }
  loadSymbol(row.dataset.symbol || DEFAULT_SYMBOL);
});

conceptSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  performConceptSearch(conceptSearchInput.value);
});

conceptSearchInput.addEventListener("input", () => {
  queueSearch("concept", conceptSearchInput.value);
});

conceptSearchResultsEl.addEventListener("click", (event) => {
  const row = event.target.closest(".concept-member-row");
  if (!row || row.disabled) {
    return;
  }
  loadSymbol(row.dataset.symbol || DEFAULT_SYMBOL);
});

renderStockSearchResults([], "");
renderConceptSearchResults([], "");
renderStockProfile(null);
loadSymbol(DEFAULT_SYMBOL);
