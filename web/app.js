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

const form = document.querySelector("#symbol-form");
const symbolInput = document.querySelector("#symbol-input");
const statusEl = document.querySelector("#status");
const zoomControlsEl = document.querySelector("#zoom-controls");
const zoomButtons = Array.from(document.querySelectorAll(".zoom-button"));
const windowSliderEl = document.querySelector("#window-slider");
const windowCaptionEl = document.querySelector("#window-caption");
const volumeMaWindowEl = document.querySelector("#volume-ma-window");

const dashboardState = {
  payload: null,
  visibleWindow: 120,
  windowStart: 0,
  hoveredIndex: null,
  dragState: null,
  volumeMaWindow: DEFAULT_VOLUME_MA_WINDOW,
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
  const paddedMin = min === max ? min * 0.98 : min - (max - min) * 0.08;
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
      <text class="axis-label axis-label-y" x="${width - CHART_PADDING.right + 10}" y="${y + 4}">${chart.isVolume ? `${formatNumber(tick)} M` : formatNumber(tick)}</text>
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
    const response = await fetch(`/api/stock-window-volume?symbol=${encodeURIComponent(symbol)}`);
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error?.message || "Request failed");
    }

    dashboardState.payload = payload;
    dashboardState.hoveredIndex = null;
    dashboardState.dragState = null;

    if (payload.history.length >= 120) {
      dashboardState.visibleWindow = 120;
      dashboardState.windowStart = Math.max(0, payload.history.length - 120);
    } else {
      dashboardState.visibleWindow = "all";
      dashboardState.windowStart = 0;
    }

    renderDashboard();
  } catch (error) {
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

loadSymbol(DEFAULT_SYMBOL);
