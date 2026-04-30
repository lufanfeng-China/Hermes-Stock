(function (globalScope) {
  const POSITIVE_HEAT = "#8f1d1d";
  const NEGATIVE_HEAT = "#0b6b53";
  const NEUTRAL_HEAT = "#ffffff";

  function clampHeatValue(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return 0;
    }
    return Math.max(-5, Math.min(5, numeric));
  }

  function formatHeatmapDateLabel(value) {
    if (typeof value !== "string" || value.length < 10) {
      return "----";
    }
    return `${value.slice(5, 7)}-${value.slice(8, 10)}`;
  }

  function getHeatmapCellText(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return "·";
    }
    return "";
  }

  function computeHeatmapLayout({
    containerWidth,
    frozenColumnWidth,
    totalColumns,
    maxVisibleColumns = 50,
  }) {
    const safeContainerWidth = Math.max(0, Number(containerWidth) || 0);
    const safeFrozenColumnWidth = Math.max(0, Number(frozenColumnWidth) || 0);
    const safeTotalColumns = Math.max(0, Math.floor(Number(totalColumns) || 0));
    const safeMaxVisibleColumns = Math.max(1, Math.floor(Number(maxVisibleColumns) || 50));
    const visibleColumns = Math.max(1, Math.min(safeTotalColumns || 1, safeMaxVisibleColumns));
    const availableWidth = Math.max(visibleColumns, safeContainerWidth - safeFrozenColumnWidth);
    const cellSize = Math.max(1, availableWidth / visibleColumns);
    const tableWidth = safeFrozenColumnWidth + cellSize * safeTotalColumns;

    return {
      visibleColumns,
      cellSize,
      tableWidth,
      needsHorizontalScroll: safeTotalColumns > safeMaxVisibleColumns,
    };
  }

  function hexToRgb(hex) {
    const normalized = hex.replace("#", "");
    return [
      parseInt(normalized.slice(0, 2), 16),
      parseInt(normalized.slice(2, 4), 16),
      parseInt(normalized.slice(4, 6), 16),
    ];
  }

  function rgbToHex(rgb) {
    return `#${rgb
      .map((channel) => Math.max(0, Math.min(255, Math.round(channel))).toString(16).padStart(2, "0"))
      .join("")}`;
  }

  function mixColor(startHex, endHex, ratio) {
    const start = hexToRgb(startHex);
    const end = hexToRgb(endHex);
    const blended = start.map((channel, index) => channel + (end[index] - channel) * ratio);
    return rgbToHex(blended);
  }

  function pctToHeatColor(value) {
    const pct = clampHeatValue(value);
    if (pct === 0) {
      return NEUTRAL_HEAT;
    }
    if (pct > 0) {
      return mixColor(NEUTRAL_HEAT, POSITIVE_HEAT, pct / 5);
    }
    return mixColor(NEUTRAL_HEAT, NEGATIVE_HEAT, Math.abs(pct) / 5);
  }

  const api = {
    clampHeatValue,
    computeHeatmapLayout,
    formatHeatmapDateLabel,
    getHeatmapCellText,
    pctToHeatColor,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  globalScope.IndustryHeatmapUtils = api;
})(typeof window !== "undefined" ? window : globalThis);
