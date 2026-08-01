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
      method: "严格现金守恒 MTM",
      entryRule: "NDIF<-1% + MACD金叉 + MA10上升",
      lotCash: 50_000,
      rows: [
        {
          capital: 3_000_000, finalEquity: 12_144_586.37, totalReturnPct: 304.82,
          annualizedReturnPct: 10.08, openPositions: 222, closedPositions: 954,
          executed: 2308, rejectedForCash: 1864,
        },
        {
          capital: 6_000_000, finalEquity: 24_910_440.64, totalReturnPct: 315.17,
          annualizedReturnPct: 10.27, openPositions: 224, closedPositions: 1479,
          executed: 3745, rejectedForCash: 298,
        },
        {
          capital: 10_000_000, finalEquity: 31_265_194.46, totalReturnPct: 212.65,
          annualizedReturnPct: 8.14, openPositions: 223, closedPositions: 1624,
          executed: 4110, rejectedForCash: 7,
        },
      ],
    };
  }

  return { calculatePositionFilterStats, calculateHistoryFilterStats, getMacdBacktestSummary };
});
