(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.StockFilterHistoryCapabilities = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var groups = {
    historical: [
      'as_of_date', 'preset',
      'price_min', 'price_max', 'return_1d_min', 'return_1d_max',
      'volume_ratio_5_min', 'volume_ratio_5_max',
      'ma5_distance_pct_min', 'ma5_distance_pct_max',
      'ma10_distance_pct_min', 'ma10_distance_pct_max',
      'ma20_distance_pct_min', 'ma20_distance_pct_max',
      'price_percentile_5y_min', 'price_percentile_5y_max',
      'turnover_percentile_1y_min', 'turnover_percentile_1y_max',
      'pe_ttm_min', 'pe_ttm_max', 'pe_percentile_5y_min', 'pe_percentile_5y_max',
      'ps_ttm_min', 'ps_ttm_max',
      'annual_total_min', 'annual_total_max',
      'annual_growth_quality_min', 'annual_growth_quality_max',
      'annual_profitability_min', 'annual_profitability_max',
      'annual_cash_quality_min', 'annual_cash_quality_max',
      'annual_working_capital_min', 'annual_working_capital_max',
      'annual_reinvestment_min', 'annual_reinvestment_max',
      'annual_financial_risk_min', 'annual_financial_risk_max',
      'quarterly_total_min', 'quarterly_total_max',
      'quarterly_growth_min', 'quarterly_growth_max',
      'quarterly_profitability_min', 'quarterly_profitability_max',
      'quarterly_cash_min', 'quarterly_cash_max',
      'quarterly_working_capital_min', 'quarterly_working_capital_max',
      'quarterly_reinvestment_min', 'quarterly_reinvestment_max',
      'quarterly_financial_risk_min', 'quarterly_financial_risk_max',
      'trend_daily', 'wyckoff_type', 'wyckoff_status', 'wyckoff_since',
      'swing_state', 'swing_entry_only', 'swing_entry_days',
      'swing_tendency', 'swing_star', 'swing_observation'
    ],
    partial: ['stock_scope'],
    latest_only: [
      'industry_l2_codes', 'industry_temperature_levels', 'concept_codes', 'concept_temperature_levels',
      'rps_20_min', 'rps_20_max', 'rps_50_min', 'rps_50_max',
      'rps_120_min', 'rps_120_max', 'rps_250_min', 'rps_250_max',
      'rps_total_min', 'rps_total_max',
      'return_n_days', 'return_n_pct_min', 'return_n_pct_max',
      'change_days_n', 'up_days_min', 'up_days_max', 'down_days_min', 'down_days_max',
      'limit_up_n_days', 'eps_ratio_5y_min', 'eps_ratio_5y_max',
      'total_market_cap_min', 'total_market_cap_max',
      'free_float_market_cap_min', 'free_float_market_cap_max',
      'niche_leader', 'composite_total_min', 'composite_total_max',
      'trend_weekly', 'trend_monthly',
      'macd_cross', 'golden_cross', 'ma_alignment',
      'ma_alignment_days_min', 'ma_alignment_days_max',
      'mrs_score_min', 'mrs_score_max',
      'excess_return_5_pp_min', 'excess_return_5_pp_max',
      'excess_return_20_pp_min', 'excess_return_20_pp_max',
      'down_market_win_rate_20_min', 'down_market_win_rate_20_max',
      'down_market_total_excess_pp_20_min', 'down_market_total_excess_pp_20_max'
    ]
  };

  var fieldCapabilities = {};
  Object.keys(groups).forEach(function (capability) {
    groups[capability].forEach(function (name) {
      if (fieldCapabilities[name]) throw new Error('duplicate history capability: ' + name);
      fieldCapabilities[name] = capability;
    });
  });

  var latestOnlyFields = groups.latest_only.slice();
  var latestOnlySorts = ['rps_total', 'mrs_score', 'excess_return_20_pp', 'total_market_cap', 'eps_ratio_5y'];
  var genericReason = '该条件仅支持最新日期；历史快照没有同日可审计数据。';
  var reasons = {
    industry_l2_codes: '二级行业成员使用当前成分，仅支持最新日期。',
    industry_temperature_levels: '行业温度使用当前成分与当前温度快照，仅支持最新日期。',
    concept_codes: '概念成员使用当前通达信映射，仅支持最新日期。',
    concept_temperature_levels: '概念温度使用当前成分与当前温度快照，仅支持最新日期。'
  };

  function clearField(field) {
    if (!field) return;
    if (field.type === 'checkbox' || field.type === 'radio') field.checked = false;
    else if (field.multiple && field.options) {
      Array.prototype.forEach.call(field.options, function (option) { option.selected = false; });
    } else field.value = '';
  }

  function ownerFor(field) {
    return field && typeof field.closest === 'function'
      ? (field.closest('.filter-field') || field.closest('label') || field)
      : field;
  }

  function setReason(field, reason) {
    var owner = ownerFor(field);
    if (owner && owner.classList) owner.classList.add('history-disabled-field');
    if (owner && owner.dataset) owner.dataset.historyBadge = '历史不可用';
    [field, owner].forEach(function (target) {
      if (!target) return;
      if (target.dataset.historyOriginalTitle === undefined) target.dataset.historyOriginalTitle = target.title || '';
      target.title = reason;
    });
  }

  function restoreReason(field) {
    var owner = ownerFor(field);
    if (owner && owner.classList) owner.classList.remove('history-disabled-field');
    if (owner && owner.dataset) delete owner.dataset.historyBadge;
    [field, owner].forEach(function (target) {
      if (!target || !target.dataset || target.dataset.historyOriginalTitle === undefined) return;
      target.title = target.dataset.historyOriginalTitle;
      delete target.dataset.historyOriginalTitle;
      if (!target.title && typeof target.removeAttribute === 'function') target.removeAttribute('title');
    });
  }

  function applyHistoricalFieldState(form, historical) {
    var disabled = [];
    latestOnlyFields.forEach(function (name) {
      var field = form && form.elements ? form.elements[name] : null;
      if (!field) return;
      if (historical) {
        if (field.dataset.historyPreviousDisabled === undefined) {
          field.dataset.historyPreviousDisabled = field.disabled ? '1' : '0';
        }
        clearField(field);
        field.disabled = true;
        field.dataset.historyDisabled = '1';
        setReason(field, reasons[name] || genericReason);
        disabled.push(name);
      } else if (field.dataset.historyDisabled === '1') {
        field.disabled = field.dataset.historyPreviousDisabled === '1';
        delete field.dataset.historyPreviousDisabled;
        delete field.dataset.historyDisabled;
        restoreReason(field);
      }
    });
    return disabled;
  }

  function applyHistoricalSortState(select, historical) {
    if (!select || !select.options) return;
    var unsupported = new Set(latestOnlySorts);
    Array.prototype.forEach.call(select.options, function (option) {
      option.disabled = historical && unsupported.has(option.value);
      option.title = option.disabled ? '该排序仅支持最新日期。' : '';
    });
    if (historical) {
      if (unsupported.has(select.value)) {
        select.dataset.latestSort = select.value;
        select.value = 'annual_total';
      }
      select.title = '历史日期仅提供同日可审计字段排序。';
    } else {
      if (select.dataset.latestSort) {
        select.value = select.dataset.latestSort;
        delete select.dataset.latestSort;
      }
      select.title = '';
    }
  }

  return {
    fieldCapabilities: fieldCapabilities,
    latestOnlyFields: latestOnlyFields,
    latestOnlySorts: latestOnlySorts,
    applyHistoricalFieldState: applyHistoricalFieldState,
    applyHistoricalSortState: applyHistoricalSortState
  };
}));
