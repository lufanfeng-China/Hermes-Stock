(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.QuarterlyFinancialChart = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var METRICS = [
    { key: 'basic_eps_cumulative', label: '每股收益', unit: '元/股', basis: '累计基本 EPS 逐季差分 · 未复权', scale: 1 },
    { key: 'revenue_cumulative_verified', label: '营业收入', unit: '亿元', basis: '法定累计营收逐季差分；缺少累计口径时留空', scale: 1e8 },
    { key: 'net_profit', label: '归母净利润', unit: '亿元', basis: '财报累计归母净利润逐季差分', scale: 1e8 },
    { key: 'ex_net_profit', label: '扣归净利润', unit: '亿元', basis: '财报累计扣非归母净利润逐季差分', scale: 1e8 },
    { key: 'ocf', label: '经营现金流金额', unit: '亿元', basis: '累计经营活动现金流净额逐季差分', scale: 1e8 },
    { key: 'capex', label: '资本开支', unit: '亿元', basis: '累计购建长期资产所付现金逐季差分', scale: 1e8 },
    { key: 'free_cf', label: '自由现金流', unit: '亿元', basis: '累计经营现金流减累计资本开支，逐季差分', scale: 1e8 },
  ];
  var METRIC_BY_KEY = Object.fromEntries(METRICS.map(function (item) { return [item.key, item]; }));

  function buildQuarterSeries(payload, metricKey) {
    var metric = METRIC_BY_KEY[metricKey] || METRICS[0];
    var reports = Array.isArray(payload && payload.reports) ? payload.reports : [];
    var byPeriod = new Map(reports.map(function (row) { return [String(row.period || ''), row]; }));
    var annualYears = Array.from(new Set(reports.filter(function (row) {
      return /^\d{4}A$/.test(String(row.period || ''));
    }).map(function (row) { return Number(String(row.period).slice(0, 4)); }))).sort(function (a, b) { return a - b; }).slice(-5);
    var groups = annualYears.map(function (year) { return { year: year, quarters: [1, 2, 3, 4], current: false }; });
    var lastAnnualYear = annualYears.length ? annualYears[annualYears.length - 1] : 0;
    var currentReports = reports.filter(function (row) {
      var period = String(row.period || '');
      return /^\d{4}Q[123]$/.test(period) && Number(period.slice(0, 4)) > lastAnnualYear;
    }).sort(function (a, b) { return String(a.period).localeCompare(String(b.period)); });
    var current = currentReports.length ? currentReports[currentReports.length - 1] : null;
    if (current) {
      var currentPeriod = String(current.period);
      var latestQuarter = Number(currentPeriod.slice(-1));
      groups.push({
        year: Number(currentPeriod.slice(0, 4)),
        quarters: Array.from({ length: latestQuarter }, function (_, index) { return index + 1; }),
        current: true,
      });
    }
    function cumulative(period) {
      var row = byPeriod.get(period);
      var raw = row && row.metrics ? row.metrics[metric.key] : null;
      return raw !== null && raw !== undefined && Number.isFinite(Number(raw)) ? Number(raw) / metric.scale : null;
    }
    var entries = groups.flatMap(function (group, groupIndex) {
      return group.quarters.map(function (quarter) {
        var year = group.year;
        var period = String(year) + (quarter === 4 ? 'A' : 'Q' + quarter);
        var priorPeriod = quarter === 1 ? null : String(year) + 'Q' + (quarter - 1);
        var end = cumulative(period);
        var start = priorPeriod ? cumulative(priorPeriod) : 0;
        return {
          year: year, quarter: quarter, period: String(year) + 'Q' + quarter,
          groupIndex: groupIndex, current: Boolean(group.current),
          value: end === null || start === null ? null : end - start,
        };
      });
    });
    return { metric: metric, groups: groups, entries: entries };
  }

  function renderQuarterMetric(payload, metricKey) {
    var series = buildQuarterSeries(payload, metricKey);
    var metric = series.metric;
    var groups = series.groups;
    var entries = series.entries;
    var values = entries.map(function (entry) { return entry.value; }).filter(function (value) { return value !== null; });
    var emptyMessage = '暂无可用的累计' + metric.label + '，不能拆分单季度；缺失期间不会填零。';
    if (!groups.length || !values.length) {
      return { metric: metric, groups: groups, entries: entries, svg: '', ariaLabel: emptyMessage, emptyMessage: emptyMessage };
    }
    var barWidth = 22, quarterGap = 6, groupGap = 40, groupWidth = 4 * barWidth + 3 * quarterGap;
    var width = 120 + groups.length * groupWidth + Math.max(0, groups.length - 1) * groupGap;
    var top = 30, bottom = 204, plotHeight = bottom - top;
    var low = Math.min.apply(null, [0].concat(values));
    var high = Math.max.apply(null, [0].concat(values));
    var span = Math.max(high - low, 0.01), padding = span * 0.1;
    var min = low - (low < 0 ? padding : high === 0 ? 0.1 : 0);
    var max = high + (high > 0 ? padding : low === 0 ? 0.1 : 0);
    function y(value) { return bottom - (value - min) / (max - min) * plotHeight; }
    var baseline = y(0);
    function formatValue(value) { return value.toFixed(value !== 0 && Math.abs(value) < 0.01 ? 4 : 2) + ' ' + metric.unit; }
    function axisNumber(value) { return value.toFixed(Math.abs(value) < 1 && value !== 0 ? 2 : 1); }
    var axisValues = [min, 0, max].filter(function (value, index, rows) { return index === 0 || value !== rows[index - 1]; });
    var axes = axisValues.map(function (value) {
      return '<line x1="68" y1="' + y(value) + '" x2="' + (width - 16) + '" y2="' + y(value) + '" stroke="' + (value === 0 ? '#5f9aaf' : '#20485a') + '" stroke-dasharray="' + (value === 0 ? '' : '4 5') + '"/>' +
        '<text x="60" y="' + (y(value) + 4) + '" text-anchor="end" fill="#9fbbc9" font-size="11">' + axisNumber(value) + '</text>';
    }).join('');
    var bars = entries.map(function (entry) {
      var x = 76 + entry.groupIndex * (groupWidth + groupGap) + (entry.quarter - 1) * (barWidth + quarterGap);
      var label = '<text x="' + (x + barWidth / 2) + '" y="226" text-anchor="middle" fill="#9fbbc9" font-size="11">Q' + entry.quarter + '</text>';
      if (entry.value === null) return '<title>' + entry.period + '：缺少本季或上季累计' + metric.label + '</title>' + label;
      var endY = y(entry.value), height = Math.max(2, Math.abs(endY - baseline));
      return '<rect x="' + x + '" y="' + (entry.value >= 0 ? baseline - height : baseline) + '" width="' + barWidth + '" height="' + height + '" rx="3" fill="' + (entry.value < 0 ? '#3bd0a8' : '#f26b76') + '"><title>' + entry.period + '：' + formatValue(entry.value) + '（累计差分）</title></rect>' + label;
    }).join('');
    var labels = groups.map(function (group, index) {
      var occupiedWidth = group.quarters.length * barWidth + (group.quarters.length - 1) * quarterGap;
      var center = 76 + index * (groupWidth + groupGap) + occupiedWidth / 2;
      return '<text x="' + center + '" y="254" text-anchor="middle" fill="' + (group.current ? '#ffcb75' : '#e2edf4') + '" font-size="13" font-weight="700">' + group.year + (group.current ? ' · 最新' : '') + '</text>';
    }).join('');
    var ariaLabel = metric.label + '单季度（累计差分，' + metric.unit + '）：' + entries.map(function (entry) {
      return entry.year + '年Q' + entry.quarter + ' ' + (entry.value === null ? '缺失' : formatValue(entry.value));
    }).join('；');
    var svg = '<svg class="quarter-financial-svg" viewBox="0 0 ' + width + ' 270" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="' + ariaLabel + '">' + axes + bars + labels + '</svg>';
    return { metric: metric, groups: groups, entries: entries, svg: svg, ariaLabel: ariaLabel, emptyMessage: '' };
  }

  return { METRICS: METRICS, buildQuarterSeries: buildQuarterSeries, renderQuarterMetric: renderQuarterMetric };
}));
