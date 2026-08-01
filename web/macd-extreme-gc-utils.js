(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.MacdExtremeGcUtils = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function toFiniteNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
  }

  function calculatePositionFilterStats(positions) {
    const rows = Array.isArray(positions) ? positions : [];
    const cost = rows.reduce((sum, position) => sum + toFiniteNumber(position.total_cost), 0);
    const pnl = rows.reduce(
      (sum, position) => sum + (toFiniteNumber(position.current_value) - toFiniteNumber(position.total_cost)),
      0,
    );
    return { pnl, cost, pnlPct: cost ? pnl / cost * 100 : 0 };
  }

  function calendarDaysBetween(entryDate, exitDate) {
    const entry = new Date(`${entryDate}T00:00:00Z`);
    const exit = new Date(`${exitDate}T00:00:00Z`);
    if (Number.isNaN(entry.getTime()) || Number.isNaN(exit.getTime())) return null;
    return (exit.getTime() - entry.getTime()) / 86400000;
  }

  function calculateHistoryFilterStats(history) {
    const rows = Array.isArray(history) ? history : [];
    const cost = rows.reduce((sum, row) => sum + toFiniteNumber(row.buy_cost), 0);
    const pnl = rows.reduce((sum, row) => sum + toFiniteNumber(row.pnl), 0);
    const holdingDays = rows
      .map((row) => calendarDaysBetween(row.entry_date, row.date))
      .filter((days) => days !== null && days >= 0);
    return {
      pnl,
      cost,
      pnlPct: cost ? pnl / cost * 100 : 0,
      averageHoldingDays: holdingDays.length
        ? holdingDays.reduce((sum, days) => sum + days, 0) / holdingDays.length
        : null,
    };
  }

  function getMacdBacktestSummary() {
    return {
      start: "2012-01-01",
      asOf: "2026-07-24",
      method: "QFQ 信号 + 原始价成交/严格 MTM",
      entryRule: "NDIF<-1% + MACD金叉 + MA10上升",
      lotCash: 50_000,
      rows: [
        {
          capital: 3_000_000, finalEquity: 13_309_694.57, totalReturnPct: 343.66,
          annualizedReturnPct: 11.0, openPositions: 225, closedPositions: 1038,
          executed: 2533, rejectedForCash: 2156,
        },
        {
          capital: 6_000_000, finalEquity: 26_264_974.92, totalReturnPct: 337.75,
          annualizedReturnPct: 10.89, openPositions: 218, closedPositions: 1564,
          executed: 3993, rejectedForCash: 522,
        },
        {
          capital: 10_000_000, finalEquity: 34_634_445.73, totalReturnPct: 246.34,
          annualizedReturnPct: 9.09, openPositions: 217, closedPositions: 1740,
          executed: 4486, rejectedForCash: 19,
        },
      ],
    };
  }

  return { calculatePositionFilterStats, calculateHistoryFilterStats, getMacdBacktestSummary };
});
