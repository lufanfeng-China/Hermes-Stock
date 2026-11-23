const test = require('node:test');
const assert = require('node:assert/strict');
const charts = require('../web/quarterly-financial-chart.js');

const metricKeys = [
  'basic_eps_cumulative', 'revenue_cumulative_verified', 'net_profit',
  'ex_net_profit', 'ocf', 'capex', 'free_cf',
];

function report(period, values = {}) {
  return { period, metrics: Object.fromEntries(metricKeys.map((key) => [key, values[key] ?? null])) };
}

function fullYear(year, multiplier = 1) {
  return [
    report(`${year}Q1`, { net_profit: 10 * multiplier }),
    report(`${year}Q2`, { net_profit: 25 * multiplier }),
    report(`${year}Q3`, { net_profit: 45 * multiplier }),
    report(`${year}A`, { net_profit: 70 * multiplier }),
  ];
}

test('metric order contains all seven screenshot indicators', () => {
  assert.deepEqual(charts.METRICS.map((item) => item.key), metricKeys);
  assert.deepEqual(charts.METRICS.map((item) => item.label),
    ['每股收益', '营业收入', '归母净利润', '扣归净利润', '经营现金流金额', '资本开支', '自由现金流']);
});

test('uses the last five complete years plus disclosed quarters in the current year', () => {
  const reports = [];
  for (let year = 2020; year <= 2025; year += 1) reports.push(...fullYear(year));
  reports.push(report('2026Q1', { net_profit: 5 }), report('2026Q2', { net_profit: 12 }), report('2026Q3', { net_profit: 18 }));
  const series = charts.buildQuarterSeries({ reports }, 'net_profit');
  assert.deepEqual(series.groups.map((group) => group.year), [2021, 2022, 2023, 2024, 2025, 2026]);
  assert.deepEqual(series.groups.at(-1).quarters, [1, 2, 3]);
  assert.equal(series.groups.at(-1).current, true);
});

test('shows all complete-year history when fewer than five years exist', () => {
  const reports = [...fullYear(2023), ...fullYear(2024), ...fullYear(2025), report('2026Q1', { net_profit: 8 })];
  const series = charts.buildQuarterSeries({ reports }, 'net_profit');
  assert.deepEqual(series.groups.map((group) => group.year), [2023, 2024, 2025, 2026]);
});

test('converts cumulative flows to standalone quarters without bridging a missing adjacent period', () => {
  const complete = charts.buildQuarterSeries({ reports: [
    report('2025Q1', { net_profit: 10e8 }), report('2025Q2', { net_profit: 25e8 }),
    report('2025Q3', { net_profit: 45e8 }), report('2025A', { net_profit: 70e8 }),
  ] }, 'net_profit');
  assert.deepEqual(complete.entries.map((entry) => entry.value), [10, 15, 20, 25]);

  const missing = charts.buildQuarterSeries({ reports: [
    report('2025Q2', { net_profit: 25e8 }), report('2025Q3', { net_profit: 45e8 }), report('2025A', { net_profit: 70e8 }),
  ] }, 'net_profit');
  assert.deepEqual(missing.entries.map((entry) => entry.value), [null, null, 20, 25]);
});

test('svg keeps positive red, negative green and marks the current year as latest', () => {
  const payload = { reports: [
    report('2025Q1', { free_cf: 2e8 }), report('2025Q2', { free_cf: 1e8 }),
    report('2025Q3', { free_cf: 3e8 }), report('2025A', { free_cf: 2e8 }),
    report('2026Q1', { free_cf: 4e8 }),
  ] };
  const rendered = charts.renderQuarterMetric(payload, 'free_cf');
  assert.match(rendered.svg, /fill="#f26b76"/);
  assert.match(rendered.svg, /fill="#3bd0a8"/);
  assert.match(rendered.svg, /2026 · 最新/);
  assert.match(rendered.ariaLabel, /自由现金流单季度/);
});
