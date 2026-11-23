const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'stock-analysis.js'), 'utf8');

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `missing ${name}`);
  const brace = source.indexOf('{', start);
  let depth = 0;
  for (let index = brace; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated ${name}`);
}

function presentation(payload) {
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(extractFunction('sectorFinancialPresentation'), sandbox);
  return sandbox.sectorFinancialPresentation(payload);
}

test('bank presentation uses dedicated dimensions and actual report periods', () => {
  const view = presentation({
    financial_model: {code: 'bank', label: '银行模型'},
    financial_update: {status: 'up_to_date', latest_announced_period: '2026Q3', latest_valid_period: '2026Q3', latest_scored_period: '2026Q3'},
    health: {score: 93, periods: ['2021A','2022A','2023A','2024A','2025A'], dimensions: [{code:'asset_quality', title:'资产质量', points:23}]},
    quarterly_monitor: {latest_period:'2026Q3', realtime_score:{score:88, breakdown:[{code:'npl_ratio',title:'不良贷款率',points:15,max_points:15}]}}
  });
  assert.equal(view.isSector, true);
  assert.equal(view.contextText, '银行模型｜年度评分期 2025A｜季度评分期 2026Q3｜数据最新');
  assert.equal(view.currentQuarterlyScore, 88);
  assert.equal(view.statusLabel, '数据最新');
  assert.deepEqual(Array.from(view.annualDimensions, row => row.title), ['资产质量']);
  assert.deepEqual(Array.from(view.quarterlyDimensions, row => row.title), ['不良贷款率']);
  assert.equal(view.hideGenericModules, true);
});

test('pending securities presentation leaves current empty and preserves explicit previous score', () => {
  const view = presentation({
    financial_model: {code: 'securities', label: '证券模型'},
    financial_update: {status:'parse_failed', latest_announced_period:'2026Q3', latest_valid_period:'2026H1', latest_scored_period:'2026H1', using_previous_score:true, previous_quarterly_period:'2026H1', previous_quarterly_score:74},
    health: {score:73, periods:['2021A','2022A','2023A','2024A','2025A'], dimensions:[]},
    quarterly_monitor: {latest_period:'2026H1', realtime_score:{score:74, breakdown:[]}}
  });
  assert.equal(view.currentQuarterlyScore, null);
  assert.equal(view.currentQuarterlyPeriod, '2026Q3');
  assert.equal(view.previousQuarterlyScore, 74);
  assert.equal(view.previousQuarterlyPeriod, '2026H1');
  assert.equal(view.statusLabel, '解析失败');
  assert.match(view.contextText, /证券模型/);
  assert.match(view.contextText, /最新公告 2026Q3/);
  assert.match(view.contextText, /解析失败/);
  assert.match(view.contextText, /上一可信 74\.0（2026H1）/);
});

test('general company presentation keeps existing general-model path', () => {
  const view = presentation({financial_model:{code:'general',label:'通用工商模型'}});
  assert.equal(view.isSector, false);
  assert.equal(view.hideGenericModules, false);
});
