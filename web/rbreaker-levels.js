(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RBreakerLevels = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const LEVEL_META = [
    ['b_break', '突破买入价', '突破区', 'up'],
    ['s_setup', '观察卖出价', '观察区', 'watch'],
    ['s_enter', '反转卖出价', '反转区', 'down'],
    ['b_enter', '反转买入价', '反转区', 'up'],
    ['b_setup', '观察买入价', '观察区', 'watch'],
    ['s_break', '突破卖出价', '突破区', 'down'],
  ];

  function finitePositive(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) throw new TypeError('R-Breaker OHLC must be positive finite numbers');
    return number;
  }

  function calculateRBreakerLevels(row) {
    const high = finitePositive(row?.high);
    const low = finitePositive(row?.low);
    const close = finitePositive(row?.close);
    if (high < low) throw new RangeError('R-Breaker high must not be below low');
    if (close < low || close > high) throw new RangeError('R-Breaker close must lie between low and high');
    const pivot = (high + low + close) / 3;
    return {
      pivot,
      b_break: high + 2 * (pivot - low),
      s_setup: pivot + (high - low),
      s_enter: 2 * pivot - low,
      b_enter: 2 * pivot - high,
      b_setup: pivot - (high - low),
      s_break: low - 2 * (high - pivot),
    };
  }

  function orderedRBreakerLevels(levels) {
    return LEVEL_META.map(([key, label, group, tone]) => ({ key, label, group, tone, value: Number(levels?.[key]) }));
  }

  return { calculateRBreakerLevels, orderedRBreakerLevels };
}));
