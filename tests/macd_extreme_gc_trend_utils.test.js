const test = require("node:test");
const assert = require("node:assert/strict");

const { buildMonthlyLineGeometry } = require("../web/macd-extreme-gc-trend-utils.js");

test("buildMonthlyLineGeometry produces a finite path and preserves monthly endpoints", () => {
  const rows = [
    { month: "2026-01", equity: 100, cash: 60, market_value: 40 },
    { month: "2026-02", equity: 120, cash: 70, market_value: 50 },
    { month: "2026-03", equity: 110, cash: 55, market_value: 55 },
  ];
  const chart = buildMonthlyLineGeometry(rows, "equity", { width: 300, height: 120, pad: 20 });

  assert.equal(chart.points.length, 3);
  assert.equal(chart.points[0].x, 20);
  assert.equal(chart.points.at(-1).x, 280);
  assert.match(chart.path, /^M 20\.00 /);
  assert.match(chart.path, /L 280\.00 /);
  assert.equal(chart.latest.value, 110);
  assert.ok(Number.isFinite(chart.min));
  assert.ok(Number.isFinite(chart.max));
});
