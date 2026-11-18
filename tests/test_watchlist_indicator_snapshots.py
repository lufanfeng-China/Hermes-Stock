"""Watchlist indicators use only audited published snapshots, never live/raw substitutes."""
import json

from app.data import watchlist_indicators


def _save(root, name, payload):
    (root / name).write_text(json.dumps(payload), encoding='utf-8')


def test_watchlist_indicator_snapshots_keep_dates_and_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist_indicators, 'FINAL', tmp_path)
    key = 'sh:603586'
    _save(tmp_path, 'stock_filter_pe_percentile_current.json', {
        'schema_version': 'stock-filter-pe-percentile-v1', 'as_of_date': '2026-11-12',
        'stocks': {key: {'pe_percentile_5y': 90.09, 'pe_percentile_5y_status': 'ok',
                         'pe_percentile_5y_price_date': '2026-11-12', 'pe_percentile_5y_sample_count': 1130}}})
    _save(tmp_path, 'stock_filter_turnover_percentile_current.json', {
        'schema_version': 'stock-filter-turnover-percentile-v2', 'as_of_date': '2026-11-12',
        'stocks': {key: {'turnover_percentile_1y': 88.89, 'turnover_percentile_1y_status': 'ok',
                         'turnover_percentile_1y_as_of': '2026-11-12', 'turnover_percentile_1y_sample_count': 243}}})
    _save(tmp_path, 'market_relative_strength_current.json', {
        'schema_version': 'market-relative-strength-v1', 'price_basis': 'tdx_export_qfq',
        'as_of_date': '2026-11-12', 'stocks': {key: {'mrs_score': 82.67, 'mrs_label': '强势',
                                                   'as_of_date': '2026-11-12'}}})
    _save(tmp_path, 'swing_structure_v8_current.json', {
        'schema_version': 'swing-structure-v8', 'rule_version': watchlist_indicators.SWING_RULE,
        'price_basis': 'tdx_export_qfq', 'completeness': 'complete', 'as_of_date': '2026-11-12',
        'stocks': {key: {'status': 'ok', 'state': '上涨突破', 'last_bar_date': '2026-11-12',
                         'source_sha256': 'digest'}}})
    row = watchlist_indicators.load_watchlist_indicators([{'market': 'sh', 'symbol': '603586'}])[('sh', '603586')]
    assert row['pe_percentile_5y'] == 90.09 and row['pe_percentile_5y_price_date'] == '2026-11-12'
    assert row['turnover_percentile_1y'] == 88.89 and row['turnover_percentile_1y_as_of'] == '2026-11-12'
    assert row['mrs_score'] == 82.67 and row['relative_strength_as_of'] == '2026-11-12'
    assert row['swing_structure']['state'] == '上涨突破'
    assert row['swing_structure']['tendency'] == 'bull' and row['swing_structure_as_of'] == '2026-11-12'


def test_unchanged_publication_is_loaded_once_and_replacement_invalidates_cache(tmp_path, monkeypatch):
    from unittest.mock import patch

    monkeypatch.setattr(watchlist_indicators, 'FINAL', tmp_path)
    name = 'stock_filter_pe_percentile_current.json'
    _save(tmp_path, name, {'schema_version': 'stock-filter-pe-percentile-v1', 'as_of_date': '2026-11-12',
        'stocks': {'sh:600000': {'pe_percentile_5y': 22, 'pe_percentile_5y_status': 'ok',
                                 'pe_percentile_5y_price_date': '2026-11-12'}}})
    stock = [{'market': 'sh', 'symbol': '600000'}]
    with patch.object(watchlist_indicators.json, 'loads', wraps=watchlist_indicators.json.loads) as decode:
        assert watchlist_indicators.load_watchlist_indicators(stock)[('sh', '600000')]['pe_percentile_5y'] == 22
        assert watchlist_indicators.load_watchlist_indicators(stock)[('sh', '600000')]['pe_percentile_5y'] == 22
        assert decode.call_count == 1
    replacement = tmp_path / 'next.json'
    _save(tmp_path, 'next.json', {'schema_version': 'stock-filter-pe-percentile-v1', 'as_of_date': '2026-11-13',
        'stocks': {'sh:600000': {'pe_percentile_5y': 33, 'pe_percentile_5y_status': 'ok',
                                 'pe_percentile_5y_price_date': '2026-11-13'}}})
    replacement.replace(tmp_path / name)
    assert watchlist_indicators.load_watchlist_indicators(stock)[('sh', '600000')]['pe_percentile_5y'] == 33


def test_stale_or_unpublished_indicators_are_unknown_not_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist_indicators, 'FINAL', tmp_path)
    key = 'sz:002864'
    _save(tmp_path, 'stock_filter_pe_percentile_current.json', {
        'schema_version': 'stock-filter-pe-percentile-v1', 'as_of_date': '2026-11-12',
        'stocks': {key: {'pe_percentile_5y': 42.0, 'pe_percentile_5y_status': 'ok',
                         'pe_percentile_5y_price_date': '2026-11-11'}}})
    _save(tmp_path, 'stock_filter_turnover_percentile_current.json', {
        'schema_version': 'old', 'as_of_date': '2026-11-12',
        'stocks': {key: {'turnover_percentile_1y': 80, 'turnover_percentile_1y_as_of': '2026-11-12'}}})
    _save(tmp_path, 'market_relative_strength_current.json', {
        'schema_version': 'market-relative-strength-v1', 'price_basis': 'raw',
        'as_of_date': '2026-11-12', 'stocks': {key: {'mrs_score': 99, 'as_of_date': '2026-11-12'}}})
    _save(tmp_path, 'swing_structure_v8_current.json', {
        'schema_version': 'swing-structure-v8', 'rule_version': watchlist_indicators.SWING_RULE,
        'price_basis': 'tdx_export_qfq', 'completeness': 'complete', 'as_of_date': '2026-11-12',
        'stocks': {key: {'status': 'ok', 'state': '上涨突破', 'last_bar_date': '2026-11-11'}}})
    row = watchlist_indicators.load_watchlist_indicators([{'market': 'sz', 'symbol': '002864'}])[('sz', '002864')]
    assert row['pe_percentile_5y'] is None and row['pe_percentile_5y_status'] == 'stale_snapshot'
    assert row['turnover_percentile_1y'] is None
    assert row['mrs_score'] is None
    assert row['swing_structure']['tendency'] == 'unknown'
    assert row['swing_structure']['status'] == 'stale_qfq'
