const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '..', 'web', 'concept-temperature.js');
const source = fs.readFileSync(sourcePath, 'utf8');

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

function renderer() {
  const sandbox = {
    esc: value => String(value == null ? '' : value),
    numberText: (value, digits, suffix) => Number.isFinite(Number(value))
      ? Number(value).toFixed(digits) + (suffix || '') : '—',
    scoreCell: (value, period) => `<span>${value == null ? '—' : value}</span><small>${period || ''}</small>`,
  };
  vm.createContext(sandbox);
  vm.runInContext(extractFunction('quarterlyScoreCell'), sandbox);
  return sandbox.quarterlyScoreCell;
}

test('updated bank shows current score, actual scored period, model and fresh status', () => {
  const html = renderer()({
    financial_model_code: 'bank', financial_model_label: '银行模型',
    financial_update_status: 'up_to_date', financial_latest_announced_period: '2026Q3',
    financial_latest_valid_period: '2026Q3', financial_latest_scored_period: '2026Q3',
    financial_using_previous_score: false, quarterly_total: 88, quarterly_period: '2026Q3',
  });
  assert.match(html, /88\.0/);
  assert.match(html, /2026Q3/);
  assert.match(html, /银行模型/);
  assert.match(html, /数据最新/);
  assert.doesNotMatch(html, /上一可信/);
});

test('pending securities report keeps current score empty and labels previous score separately', () => {
  const html = renderer()({
    financial_model_code: 'securities', financial_model_label: '证券模型',
    financial_update_status: 'parse_failed', financial_latest_announced_period: '2026Q3',
    financial_latest_valid_period: '2026H1', financial_latest_scored_period: '2026H1',
    financial_using_previous_score: true, quarterly_total: 74, quarterly_period: '2026H1',
    financial_previous_quarterly_score: 74, financial_previous_quarterly_period: '2026H1',
  });
  assert.match(html, />—</);
  assert.match(html, /2026Q3/);
  assert.match(html, /证券模型/);
  assert.match(html, /解析失败/);
  assert.match(html, /上一可信 74\.0 · 2026H1/);
  assert.doesNotMatch(html, /<span[^>]*>74\.0<\/span>/);
});
