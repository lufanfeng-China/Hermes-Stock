(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MacdExtremeGcTrendUtils = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function buildMonthlyLineGeometry(rows, key, options = {}) {
    const width = options.width ?? 720;
    const height = options.height ?? 180;
    const pad = options.pad ?? 32;
    const values = rows.map(row => Number(row[key])).filter(Number.isFinite);
    if (!values.length) return { points: [], path: "", min: 0, max: 0, latest: null };

    const rawMin = Math.min(...values);
    const rawMax = Math.max(...values);
    const span = rawMax - rawMin || Math.max(Math.abs(rawMax) * 0.05, 1);
    const min = rawMin - span * 0.08;
    const max = rawMax + span * 0.08;
    const plotWidth = width - pad * 2;
    const plotHeight = height - pad * 2;
    const denominator = Math.max(rows.length - 1, 1);
    const points = rows.map((row, index) => ({
      month: row.month,
      value: Number(row[key]),
      x: pad + plotWidth * index / denominator,
      y: pad + (max - Number(row[key])) / (max - min) * plotHeight,
    }));
    const path = points.map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
    return { points, path, min, max, latest: points.at(-1) };
  }

  return { buildMonthlyLineGeometry };
});
