const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/stock-analysis.js'), 'utf8');
function loadRenderer() {
  const nodes = { 'industry-financial-position': {}, 'industry-financial-position-period': {} };
  const context = vm.createContext({ document: { getElementById: id => nodes[id] }, escapeHtml: value => String(value) });
  for (const name of ['metricStatus', 'peerMetricStatus', 'operatingMetricStatus', 'formatIndustryPositionMetric', 'renderIndustryFinancialPosition']) {
    const start = source.indexOf(`  function ${name}(`);
    const end = source.indexOf('\n  }', start) + 4;
    vm.runInContext(source.slice(start, end), context);
  }
  return { nodes, render: position => context.renderIndustryFinancialPosition(position) };
}
function metric(value, percentile) { return { label: '指标', company_value: value, percentile, unit: '%', industry_median: 1, sample_count: 31, status: 'available' }; }
test('company column reuses operating risk gates and direction-adjusted peer states', () => {
  const { nodes, render } = loadRenderer();
  render({ status: 'available', metrics: {
    net_margin: metric(-11.29, 9.7), ocf_to_profit: metric(-0.21, 29),
    debt_ratio: metric(81.39, 12.9), ar_days: metric(257, 12.9), inv_days: metric(183, 35.5),
  } });
  const html = nodes['industry-financial-position'].innerHTML;
  const states = [...html.matchAll(/<td class="industry-position-value ([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(states, ['risk', 'risk', 'watch', 'watch', 'neutral']);
  assert.match(html, /title="亏损"/);
});
test('high peer ranks are strong, low ranks risk, and unavailable values stay unclassified', () => {
  const { nodes, render } = loadRenderer();
  render({ status: 'available', metrics: { ar_days: metric(30, 80), inv_days: metric(300, 5), net_margin: metric(null, null) } });
  const html = nodes['industry-financial-position'].innerHTML;
  const states = [...html.matchAll(/<td class="industry-position-value ([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(states, ['strong', 'risk', 'unavailable']);
  assert.match(html, /title="数据不足">—<\/td>/);
});
