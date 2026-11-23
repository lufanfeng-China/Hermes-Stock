const test = require('node:test');
const assert = require('node:assert/strict');
const tones = require('../web/overview-card-tones.js');

test('valuation and price percentiles use low-is-cheap direction', () => {
  assert.equal(tones.valuationPercentile(0), 'strong');
  assert.equal(tones.valuationPercentile(20), 'strong');
  assert.equal(tones.valuationPercentile(20.01), '');
  assert.equal(tones.valuationPercentile(80), '');
  assert.equal(tones.valuationPercentile(80.01), 'watch');
  assert.equal(tones.valuationPercentile(95), 'watch');
  assert.equal(tones.valuationPercentile(95.01), 'risk');
  assert.equal(tones.valuationPercentile(null), '');
});

test('RPS card tone follows MRS thresholds, not individual RPS rows', () => {
  assert.equal(tones.mrs(85), 'strong');
  assert.equal(tones.mrs(70), 'strong');
  assert.equal(tones.mrs(69.99), '');
  assert.equal(tones.mrs(45), '');
  assert.equal(tones.mrs(44.99), 'watch');
  assert.equal(tones.mrs(30), 'watch');
  assert.equal(tones.mrs(29.99), 'risk');
  assert.equal(tones.mrs('—'), '');
});

test('ER card tone follows ER20 sign', () => {
  assert.equal(tones.er20(0.01), 'strong');
  assert.equal(tones.er20(0), '');
  assert.equal(tones.er20(-0.01), 'risk');
  assert.equal(tones.er20(undefined), '');
});

test('industry temperature distinguishes cold, constructive and overheated', () => {
  assert.equal(tones.temperature(0), 'risk');
  assert.equal(tones.temperature(1), 'risk');
  assert.equal(tones.temperature(2), '');
  assert.equal(tones.temperature(3), 'strong');
  assert.equal(tones.temperature(4), 'strong');
  assert.equal(tones.temperature(5), 'watch');
  assert.equal(tones.temperature(6), '');
});

test('anti-fall tone requires available evidence and uses win-rate bands', () => {
  assert.equal(tones.antiFall(100, 'available'), 'strong');
  assert.equal(tones.antiFall(60, 'available'), 'strong');
  assert.equal(tones.antiFall(59.99, 'available'), '');
  assert.equal(tones.antiFall(40, 'available'), '');
  assert.equal(tones.antiFall(39.99, 'available'), 'watch');
  assert.equal(tones.antiFall(20, 'available'), 'watch');
  assert.equal(tones.antiFall(19.99, 'available'), 'risk');
  assert.equal(tones.antiFall(100, 'sample_insufficient'), '');
  assert.equal(tones.antiFall(null, 'available'), '');
});
