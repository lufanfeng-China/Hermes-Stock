const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  clampHeatValue,
  computeHeatmapLayout,
  pctToHeatColor,
  formatHeatmapDateLabel,
  getHeatmapCellText,
} = require("../web/industry-heatmap-utils.js");

test("clampHeatValue keeps heatmap values inside [-5, 5]", () => {
  assert.equal(clampHeatValue(7), 5);
  assert.equal(clampHeatValue(-7), -5);
  assert.equal(clampHeatValue(2.3), 2.3);
});

test("pctToHeatColor maps 0 to white and extremes to deep red/green", () => {
  assert.equal(pctToHeatColor(0), "#ffffff");
  assert.equal(pctToHeatColor(5), "#8f1d1d");
  assert.equal(pctToHeatColor(-5), "#0b6b53");
  assert.notEqual(pctToHeatColor(2.5), "#ffffff");
  assert.notEqual(pctToHeatColor(-2.5), "#ffffff");
});

test("formatHeatmapDateLabel formats month-day labels with a dash", () => {
  assert.equal(formatHeatmapDateLabel("2026-02-27"), "02-27");
  assert.equal(formatHeatmapDateLabel("2026-11-03"), "11-03");
});

test("getHeatmapCellText hides numbers and keeps placeholder for empty values", () => {
  assert.equal(getHeatmapCellText(1.23), "");
  assert.equal(getHeatmapCellText(-4.56), "");
  assert.equal(getHeatmapCellText(null), "·");
});

test("computeHeatmapLayout uses at most 30 visible columns before horizontal scrolling", () => {
  const layout = computeHeatmapLayout({
    containerWidth: 1200,
    frozenColumnWidth: 120,
    totalColumns: 74,
    maxVisibleColumns: 50,
  });

  assert.equal(layout.visibleColumns, 50);
  assert.equal(layout.needsHorizontalScroll, true);
  assert.equal(layout.cellSize, 21.6);
  assert.equal(layout.tableWidth, 1718.4);
});

test("computeHeatmapLayout evenly fills available width when total columns do not exceed 50", () => {
  const layout = computeHeatmapLayout({
    containerWidth: 1200,
    frozenColumnWidth: 120,
    totalColumns: 48,
    maxVisibleColumns: 50,
  });

  assert.equal(layout.visibleColumns, 48);
  assert.equal(layout.needsHorizontalScroll, false);
  assert.equal(layout.cellSize, 22.5);
  assert.equal(layout.tableWidth, 1200);
});

test("computeHeatmapLayout defaults to 50 visible columns before scrolling", () => {
  const layout = computeHeatmapLayout({
    containerWidth: 1200,
    frozenColumnWidth: 120,
    totalColumns: 74,
  });

  assert.equal(layout.visibleColumns, 50);
  assert.equal(layout.needsHorizontalScroll, true);
});

test("heatmap styles use larger centered tighter date labels and tighter industry spacing", () => {
  const styles = fs.readFileSync(path.join(__dirname, "../web/styles.css"), "utf8");
  const script = fs.readFileSync(path.join(__dirname, "../web/industry-heatmap.js"), "utf8");
  const html = fs.readFileSync(path.join(__dirname, "../web/industry-heatmap.html"), "utf8");

  assert.match(styles, /--heatmap-frozen-column-width:\s*88px;/);
  assert.match(styles, /font-size:\s*14px;/);
  assert.match(styles, /--heatmap-header-height:\s*calc\(var\(--heatmap-cell-size\) \* 2\.8\);/);
  assert.match(styles, /\.heatmap-date-label\s*\{[\s\S]*bottom:\s*19px;[\s\S]*left:\s*50%;[\s\S]*translateX\(-50%\) rotate\(-90deg\);/);
  assert.match(styles, /\.heatmap-industry\s*\{[\s\S]*padding:\s*4px 2px 4px 0;[\s\S]*text-align:\s*right;/);
  assert.match(styles, /\.heatmap-corner\s*\{[\s\S]*padding:\s*4px 2px 4px 0;[\s\S]*text-align:\s*right;/);
  assert.match(script, /label\.className = "heatmap-date-label";/);
  assert.match(html, /id="heatmap-cache-status"/);
  assert.match(html, /id="heatmap-refresh"/);
  assert.match(script, /const cacheStatusEl = document\.querySelector\("#heatmap-cache-status"\);/);
  assert.match(script, /const refreshButtonEl = document\.querySelector\("#heatmap-refresh"\);/);
  assert.match(script, /searchParams\.set\("refresh", "1"\)/);
});
