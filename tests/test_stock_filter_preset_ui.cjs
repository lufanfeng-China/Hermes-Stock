const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').resolve(__dirname, '../web/stock-filter.js'), 'utf8');

test('preset buttons toggle multiple AND selections and clear them independently', () => {
  const start = source.indexOf('  function setPreset(');
  const end = source.indexOf('  function requestParams(', start);
  const options = ['financial_reversal', 'blowup_break', 'trend_template', 'turnover_high'].map(preset => ({
    dataset: {preset}, active: false, pressed: null,
    classList: {toggle(name, active) { assert.equal(name, 'is-active'); this.owner.active = active; }},
    setAttribute(name, value) { assert.equal(name, 'aria-pressed'); this.pressed = value; },
  }));
  for (const option of options) option.classList.owner = option;
  const presetInput = {value: ''};
  const context = vm.createContext({presetInput, presetOptions: options, Array, Set});
  vm.runInContext(source.slice(start, end), context);
  vm.runInContext("togglePreset('financial_reversal'); togglePreset('blowup_break')", context);
  assert.equal(presetInput.value, 'financial_reversal,blowup_break');
  assert.deepEqual(options.map(option => option.active), [true, true, false, false]);
  assert.deepEqual(options.map(option => option.pressed), ['true', 'true', 'false', 'false']);
  vm.runInContext("togglePreset('financial_reversal')", context);
  assert.equal(presetInput.value, 'blowup_break');
  vm.runInContext("setPreset('')", context);
  assert.equal(presetInput.value, '');
  assert.deepEqual(options.map(option => option.active), [false, false, false, false]);
});

test('preset click does not reset manual filters or the selected historical date', () => {
  const block = source.slice(source.indexOf('  presetOptions.forEach(function (option) {', source.indexOf("form.addEventListener('reset'")), source.indexOf('  function updateHistoricalMode()'));
  assert.ok(block.includes('togglePreset(option.dataset.preset)'));
  assert.ok(!block.includes('form.reset()'));
});

test('rapid selections cannot render an older request after the latest one', () => {
  const block = source.slice(source.indexOf('  async function run(page) {'), source.indexOf('  function bindPresetTooltips()'));
  assert.ok(block.includes('var requestId = ++runSequence'));
  assert.ok(block.includes('if (requestId !== runSequence) return;'));
});
