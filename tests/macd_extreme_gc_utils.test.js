const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  calculatePositionFilterStats,
  calculateHistoryFilterStats,
  getMacdBacktestSummary,
} = require("../web/macd-extreme-gc-utils.js");

test("calculatePositionFilterStats sums filtered holding P&L and calculates return from invested cost", () => {
  const stats = calculatePositionFilterStats([
    { total_cost: 10_000, current_value: 12_000 },
    { total_cost: 5_000, current_value: 4_000 },
  ]);

  assert.deepEqual(stats, {
    pnl: 1_000,
    cost: 15_000,
    pnlPct: 1000 / 15000 * 100,
  });
});

test("calculateHistoryFilterStats sums realized P&L and averages calendar holding days", () => {
  const stats = calculateHistoryFilterStats([
    { buy_cost: 10_000, pnl: 2_000, entry_date: "2026-01-02", date: "2026-01-12" },
    { buy_cost: 5_000, pnl: -500, entry_date: "2026-01-10", date: "2026-01-15" },
  ]);

  assert.deepEqual(stats, {
    pnl: 1_500,
    cost: 15_000,
    pnlPct: 10,
    averageHoldingDays: 7.5,
  });
});

test("filter stats safely handle an empty filtered list and incomplete history dates", () => {
  assert.deepEqual(calculatePositionFilterStats([]), { pnl: 0, cost: 0, pnlPct: 0 });
  assert.deepEqual(
    calculateHistoryFilterStats([{ buy_cost: 5000, pnl: 300, entry_date: "bad", date: "2026-01-02" }]),
    { pnl: 300, cost: 5000, pnlPct: 6, averageHoldingDays: null }
  );
});

test("getMacdBacktestSummary exposes the verified QFQ-signal strict-MTM comparison", () => {
  const summary = getMacdBacktestSummary();

  assert.equal(summary.asOf, "2026-07-24");
  assert.equal(summary.method, "QFQ 信号 + 原始价成交/严格 MTM");
  assert.equal(summary.entryRule, "NDIF<-1% + MACD金叉 + MA10上升");
  assert.deepEqual(summary.rows.map((row) => [row.capital, row.finalEquity, row.totalReturnPct]), [
    [3_000_000, 13_309_694.57, 343.66],
    [6_000_000, 26_264_974.92, 337.75],
    [10_000_000, 34_634_445.73, 246.34],
  ]);
  assert.equal(summary.rows[0].executed, 2533);
  assert.equal(summary.rows[2].executed, 4486);
});

test("MACD page exposes unfiltered MTM summary and a clickable strategy plan", () => {
  const project = path.resolve(__dirname, "..");
  const html = fs.readFileSync(path.join(project, "web/macd-extreme-gc.html"), "utf8");
  const script = fs.readFileSync(path.join(project, "web/macd-extreme-gc.js"), "utf8");

  assert.match(html, /id="gc-backtest-summary"[^>]*>总结<\/button>/);
  assert.match(html, /id="gc-plan-title"[^>]*role="button"/);
  assert.match(script, /function showBacktestSummary\(\)/);
  assert.match(script, /gc-backtest-summary[\s\S]*addEventListener\('click', showBacktestSummary\)/);
  assert.match(script, /function showStrategyPlan\(\)/);
  assert.match(script, /gc-plan-title[\s\S]*addEventListener\('click', showStrategyPlan\)/);
  assert.match(script, /开仓 5 年价格分位仅用于页面筛选和观察，不参与任何交易条件/);
  assert.doesNotMatch(script, /开仓日5年价格分位 < 50%/);
  assert.match(script, /showMonthlyMtmTrend\(\)/);
  assert.match(script, /总权益 = 持仓市值 \+ 闲置资金/);
  assert.match(html, /macd-extreme-gc-trend-utils\.js/);
  assert.doesNotMatch(script, /月度趋势/);
});
