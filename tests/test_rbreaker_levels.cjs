const test = require('node:test');
const assert = require('node:assert/strict');
const { calculateRBreakerLevels, orderedRBreakerLevels } = require('../web/rbreaker-levels.js');

test('TqSdk pivot-point R-Breaker formulas produce the six ordered levels', () => {
  const levels = calculateRBreakerLevels({ high: 12, low: 9, close: 10.5 });
  assert.equal(levels.pivot, 10.5);
  assert.equal(levels.b_break, 15);
  assert.equal(levels.s_setup, 13.5);
  assert.equal(levels.s_enter, 12);
  assert.equal(levels.b_enter, 9);
  assert.equal(levels.b_setup, 7.5);
  assert.equal(levels.s_break, 6);
  assert.deepEqual(
    orderedRBreakerLevels(levels).map((row) => row.key),
    ['b_break', 's_setup', 's_enter', 'b_enter', 'b_setup', 's_break'],
  );
});

test('invalid or non-positive OHLC evidence is rejected', () => {
  assert.throws(() => calculateRBreakerLevels({ high: 0, low: 9, close: 10 }), /positive finite/);
  assert.throws(() => calculateRBreakerLevels({ high: 8, low: 9, close: 8.5 }), /high.*low/);
  assert.throws(() => calculateRBreakerLevels({ high: 12, low: 9, close: 13 }), /close/);
});
