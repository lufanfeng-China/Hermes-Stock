(function (root) {
  'use strict';

  function finite(value) {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function valuationPercentile(value) {
    const number = finite(value);
    if (number === null || number < 0 || number > 100) return '';
    if (number <= 20) return 'strong';
    if (number <= 80) return '';
    if (number <= 95) return 'watch';
    return 'risk';
  }

  function mrs(value) {
    const number = finite(value);
    if (number === null || number < 0 || number > 100) return '';
    if (number >= 70) return 'strong';
    if (number >= 45) return '';
    if (number >= 30) return 'watch';
    return 'risk';
  }

  function er20(value) {
    const number = finite(value);
    if (number === null) return '';
    return number > 0 ? 'strong' : number < 0 ? 'risk' : '';
  }

  function temperature(value) {
    const number = finite(value);
    if (!Number.isInteger(number) || number < 0 || number > 5) return '';
    if (number <= 1) return 'risk';
    if (number === 2) return '';
    if (number <= 4) return 'strong';
    return 'watch';
  }

  function antiFall(value, status) {
    const number = finite(value);
    if (status !== 'available' || number === null || number < 0 || number > 100) return '';
    if (number >= 60) return 'strong';
    if (number >= 40) return '';
    if (number >= 20) return 'watch';
    return 'risk';
  }

  const api = { valuationPercentile, mrs, er20, temperature, antiFall };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OverviewCardTones = api;
}(typeof globalThis !== 'undefined' ? globalThis : this));
