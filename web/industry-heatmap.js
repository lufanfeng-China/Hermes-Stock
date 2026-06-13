(function () {
  const utils = window.IndustryHeatmapUtils;
  const statusEl = document.querySelector("#heatmap-status");
  const metaEl = document.querySelector("#heatmap-meta");
  const summaryEl = document.querySelector("#heatmap-summary");
  const headerRowEl = document.querySelector("#heatmap-header-row");
  const bodyEl = document.querySelector("#heatmap-body");
  const legendScaleEl = document.querySelector("#heatmap-legend-scale");
  const cacheStatusEl = document.querySelector("#heatmap-cache-status");
  const refreshButtonEl = document.querySelector("#heatmap-refresh");
  const tableWrapEl = document.querySelector(".heatmap-table-wrap");
  const tableEl = document.querySelector(".heatmap-table");
  let latestTradingDays = [];

  function formatPct(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return "--";
    }
    return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
  }

  function buildLegend() {
    for (let step = -5; step <= 5; step += 1) {
      const swatch = document.createElement("span");
      swatch.className = "legend-swatch";
      swatch.style.background = utils.pctToHeatColor(step);
      swatch.title = `${step}%`;
      legendScaleEl.appendChild(swatch);
    }
  }

  function renderHeader(tradingDays) {
    const staleCells = headerRowEl.querySelectorAll(".heatmap-date, .heatmap-rps20");
    for (const cell of staleCells) {
      cell.remove();
    }
    // RPS20 column
    const rpsTh = document.createElement("th");
    rpsTh.className = "heatmap-rps20";
    rpsTh.scope = "col";
    rpsTh.textContent = "RPS20";
    rpsTh.title = "行业平均RPS20";
    headerRowEl.appendChild(rpsTh);
    // Date columns
    for (const day of tradingDays) {
      const cell = document.createElement("th");
      const label = document.createElement("span");
      cell.className = "heatmap-date";
      cell.scope = "col";
      label.className = "heatmap-date-label";
      label.textContent = utils.formatHeatmapDateLabel(day);
      cell.appendChild(label);
      cell.title = day;
      headerRowEl.appendChild(cell);
    }
  }

  function renderRows(rows) {
    bodyEl.innerHTML = "";
    for (const row of rows) {
      const tr = document.createElement("tr");

      const industryCell = document.createElement("th");
      industryCell.className = "heatmap-industry";
      industryCell.scope = "row";
      industryCell.textContent = row.industry_level_2_name;
      tr.appendChild(industryCell);

      // RPS20 cell
      const rpsTd = document.createElement("td");
      rpsTd.className = "heatmap-rps20-cell";
      const rpsVal = row.rps20 != null ? Number(row.rps20) : null;
      rpsTd.textContent = rpsVal != null ? rpsVal.toFixed(1) : "—";
      rpsTd.title = `${row.industry_level_2_name} 平均RPS20: ${rpsTd.textContent}`;
      tr.appendChild(rpsTd);

      for (const cell of row.cells) {
        const td = document.createElement("td");
        const value = typeof cell.pct_change === "number" ? cell.pct_change : null;
        td.className = "heatmap-cell";
        td.style.background = value === null ? "rgba(127, 153, 170, 0.12)" : utils.pctToHeatColor(value);
        td.style.color = value === null ? "var(--muted)" : Math.abs(utils.clampHeatValue(value)) >= 2.5 ? "#f7fbff" : "#12202b";
        td.textContent = utils.getHeatmapCellText(value);
        td.title = `${row.industry_level_2_name}\\n${cell.trading_day}\\nChange: ${formatPct(value)}\\nStocks: ${cell.stock_count}`;
        tr.appendChild(td);
      }

      bodyEl.appendChild(tr);
    }
  }

  function formatCacheStatus(cacheMeta) {
    if (!cacheMeta || typeof cacheMeta !== "object") {
      return "Cache: unavailable";
    }
    const status = typeof cacheMeta.status === "string" ? cacheMeta.status : "unknown";
    const path = typeof cacheMeta.path === "string" ? cacheMeta.path : "n/a";
    return `Cache: ${status} · ${path}`;
  }

  function buildHeatmapUrl({ refresh = false } = {}) {
    const url = new URL("/api/industry-heatmap", window.location.href);
    if (refresh) {
      url.searchParams.set("refresh", "1");
    }
    return url.toString();
  }

  function applyResponsiveLayout(tradingDays) {
    if (!tableWrapEl || !tableEl) {
      return;
    }
    const cornerCell = document.querySelector(".heatmap-corner");
    const frozenColumnWidth = Math.ceil(cornerCell?.getBoundingClientRect().width || 110);
    const layout = utils.computeHeatmapLayout({
      containerWidth: tableWrapEl.clientWidth,
      frozenColumnWidth,
      totalColumns: tradingDays.length,
      maxVisibleColumns: 50,
    });
    tableEl.style.setProperty("--heatmap-frozen-column-width", `${frozenColumnWidth}px`);
    tableEl.style.setProperty("--heatmap-cell-size", `${layout.cellSize}px`);
    tableEl.style.width = `${layout.tableWidth}px`;
    tableWrapEl.style.overflowX = layout.needsHorizontalScroll ? "auto" : "hidden";
  }

  async function loadHeatmap({ refresh = false } = {}) {
    statusEl.textContent = refresh ? "Refreshing industry heatmap cache..." : "Loading second-level industry heatmap...";
    if (cacheStatusEl) {
      cacheStatusEl.textContent = refresh ? "Cache: refreshing…" : "Cache: loading…";
    }
    if (refreshButtonEl) {
      refreshButtonEl.disabled = true;
      refreshButtonEl.textContent = refresh ? "Refreshing…" : "Refresh Cache";
    }
    try {
      const response = await fetch(buildHeatmapUrl({ refresh }));
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error && payload.error.message ? payload.error.message : "Heatmap request failed");
      }

      latestTradingDays = payload.trading_days || [];
      // Sort rows by latest trading day pct_change descending
      const rows = payload.rows || [];
      rows.sort((a, b) => {
        const aVal = (a.cells && a.cells[0] && a.cells[0].pct_change != null) ? a.cells[0].pct_change : -Infinity;
        const bVal = (b.cells && b.cells[0] && b.cells[0].pct_change != null) ? b.cells[0].pct_change : -Infinity;
        return bVal - aVal;
      });
      renderHeader(latestTradingDays);
      renderRows(rows);
      applyResponsiveLayout(latestTradingDays);

      const tradingDays = latestTradingDays;
      const newestDay = tradingDays[0] || "--";
      const oldestDay = tradingDays[tradingDays.length - 1] || "--";
      metaEl.textContent = `${payload.selected_industries.length} industries · ${tradingDays.length} YTD sessions`;
      summaryEl.textContent = payload.meta && payload.meta.description ? payload.meta.description : "";
      statusEl.textContent = `YTD range ${newestDay} to ${oldestDay} (newest to oldest)`;
      if (cacheStatusEl) {
        cacheStatusEl.textContent = formatCacheStatus(payload.meta && payload.meta.cache ? payload.meta.cache : null);
      }
    } catch (error) {
      bodyEl.innerHTML = '<tr><td colspan="99" class="heatmap-error">Heatmap unavailable.</td></tr>';
      metaEl.textContent = "Request failed";
      summaryEl.textContent = error instanceof Error ? error.message : String(error);
      statusEl.textContent = "Unable to load industry heatmap.";
      if (cacheStatusEl) {
        cacheStatusEl.textContent = "Cache: unavailable";
      }
    } finally {
      if (refreshButtonEl) {
        refreshButtonEl.disabled = false;
        refreshButtonEl.textContent = "Refresh Cache";
      }
    }
  }

  buildLegend();
  loadHeatmap();
  if (refreshButtonEl) {
    refreshButtonEl.addEventListener("click", () => loadHeatmap({ refresh: true }));
  }
  window.addEventListener("resize", () => applyResponsiveLayout(latestTradingDays));
})();
