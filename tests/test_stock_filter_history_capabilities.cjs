const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const capabilities = require(path.join(root, 'web/stock-filter-history-capabilities.js'));
const html = fs.readFileSync(path.join(root, 'web/stock-filter.html'), 'utf8');
const js = fs.readFileSync(path.join(root, 'web/stock-filter.js'), 'utf8');

const formHtml = html.split('<form id="filter-form"', 2)[1].split('</form>', 1)[0];
const names = [...formHtml.matchAll(/\bname="([^"]+)"/g)].map((m) => m[1]);
const uniqueNames = [...new Set(names)];
const classified = Object.keys(capabilities.fieldCapabilities).sort();
assert.deepEqual(classified, uniqueNames.sort(), '每个筛选字段都必须有历史能力分类，不能遗漏或保留幽灵字段');

const latestOnly = new Set(capabilities.latestOnlyFields);
for (const name of [
  'industry_l2_codes', 'industry_temperature_levels', 'concept_codes', 'concept_temperature_levels',
  'rps_total_min', 'return_n_days', 'change_days_n', 'limit_up_n_days', 'eps_ratio_5y_min',
  'total_market_cap_max', 'free_float_market_cap_max', 'niche_leader', 'composite_total_min',
  'trend_weekly', 'trend_monthly', 'macd_cross', 'golden_cross', 'ma_alignment',
  'mrs_score_min', 'down_market_total_excess_pp_20_max',
]) assert(latestOnly.has(name), `${name} 应为仅最新日期`);

for (const name of [
  'price_min', 'return_1d_min', 'volume_ratio_5_min', 'ma20_distance_pct_max',
  'price_percentile_5y_min', 'turnover_percentile_1y_max', 'pe_ttm_min',
  'pe_percentile_5y_max', 'ps_ttm_min', 'annual_total_min', 'quarterly_total_min',
  'trend_daily', 'wyckoff_type', 'swing_state',
]) assert.equal(capabilities.fieldCapabilities[name], 'historical', `${name} 不应误禁用`);
assert.equal(capabilities.fieldCapabilities.stock_scope, 'partial');
assert.deepEqual(new Set(capabilities.latestOnlySorts), new Set([
  'rps_total', 'mrs_score', 'excess_return_20_pp', 'total_market_cap', 'eps_ratio_5y',
]));

function mockField(name, value, type = 'text') {
  function classList() { const values = new Set(); return {add(v){values.add(v);}, remove(v){values.delete(v);}, contains(v){return values.has(v);}}; }
  const label = {title: '', dataset: {}, classList: classList(), removeAttribute(key) { if (key === 'title') this.title = ''; }};
  return {name, value, type, disabled: false, checked: true, title: '', dataset: {},
    classList: classList(), closest() { return label; }, removeAttribute(key) { if (key === 'title') this.title = ''; }, label};
}
const latest = mockField('rps_total_min', '360');
const supported = mockField('annual_total_min', '60');
const form = {elements: {rps_total_min: latest, annual_total_min: supported}};
const disabled = capabilities.applyHistoricalFieldState(form, true);
assert.deepEqual(disabled, ['rps_total_min']);
assert.equal(latest.disabled, true); assert.equal(latest.value, '');
assert.match(latest.label.title, /仅支持最新日期/);
assert.equal(latest.label.classList.contains('history-disabled-field'), true);
assert.equal(latest.label.dataset.historyBadge, '历史不可用');
assert.equal(supported.disabled, false); assert.equal(supported.value, '60');
capabilities.applyHistoricalFieldState(form, false);
assert.equal(latest.disabled, false); assert.equal(latest.label.title, '');
assert.equal(latest.label.classList.contains('history-disabled-field'), false);

const readonly = mockField('rps_total_min', '360');
Object.defineProperty(readonly, 'dataset', {value: {}, writable: false});
Object.defineProperty(readonly.label, 'dataset', {value: {}, writable: false});
assert.doesNotThrow(() => capabilities.applyHistoricalFieldState({elements: {rps_total_min: readonly}}, true));
assert.equal(readonly.disabled, true);

assert(html.includes('/stock-filter-history-capabilities.js?'));
assert(html.indexOf('/stock-filter-history-capabilities.js?') < html.indexOf('/stock-filter.js?'));
assert(js.includes('capabilities.applyHistoricalFieldState'));
assert(js.includes("option.value === 'csi300'"));
assert(js.includes('selectedIndustryCodes.clear()'));
assert(js.includes('applyHistoricalSortState'));
console.log('stock-filter historical capability tests passed');
