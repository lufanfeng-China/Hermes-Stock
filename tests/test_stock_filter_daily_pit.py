"""Daily publication of reusable point-in-time stock-filter snapshots."""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest


def test_daily_pit_is_registered_after_sources_and_retryable():
    from app.handler import DATA_UPDATE_TASK_PLAN
    from app.pipeline.commands import _data_update_commands
    from app.pipeline.runner import _task_timeout

    full = _data_update_commands("2026-11-10")
    ids = [name for name, _ in full]
    task = "build_stock_filter_fundamental_history"
    assert ids == [row["id"] for row in DATA_UPDATE_TASK_PLAN]
    assert ids.index(task) > ids.index("build_stock_filter_market_snapshot")
    assert ids.index(task) > ids.index("update_financial_ts")
    assert ids.index(task) > ids.index("build_stock_filter_turnover_percentile_snapshot")
    assert ids.index(task) < ids.index("build_concept_temperature")
    assert dict(full)[task] == dict(_data_update_commands(None, retry_failed=True))[task]
    assert dict(full)[task][-1] == "--latest-trading-day"
    assert _task_timeout(task) >= 3600


def test_latest_day_requires_raw_qfq_and_market_publications_to_agree():
    from scripts import build_stock_filter_fundamental_history as builder

    with patch("app.pipeline.commands._latest_trading_day_for_refresh", return_value="2026-11-13"), \
         patch("app.pipeline.task_freshness.task_freshness", side_effect=[{"data_date": "2026-11-13"}, {"data_date": "2026-11-13"}]):
        assert builder.resolve_latest_day() == "2026-11-13"
    with patch("app.pipeline.commands._latest_trading_day_for_refresh", return_value="2026-11-13"), \
         patch("app.pipeline.task_freshness.task_freshness", side_effect=[{"data_date": "2026-11-12"}, {"data_date": "2026-11-12"}]):
        with pytest.raises(ValueError, match="2026-11-13"):
            builder.resolve_latest_day()


def test_daily_rerun_reuses_complete_same_date_snapshot_without_scanning_or_touching_lock(tmp_path, monkeypatch, capsys):
    from scripts import build_stock_filter_fundamental_history as builder

    day = '2026-11-13'
    target = tmp_path / f'{day}.json'
    payload = {'schema_version': 'stock-filter-fundamental-history-v7', 'as_of_date': day,
               'financial_information_cutoff': day, 'valuation_price_basis': 'raw_unadjusted_close',
               'stocks': {'sz:000001': {'pe_ttm': 9}}}
    target.write_text(json.dumps(payload), encoding='utf-8')
    locked = tmp_path / f'{day}.building'
    locked.touch()
    monkeypatch.setattr(builder, 'OUT_DIR', tmp_path)
    monkeypatch.setattr(builder, 'resolve_latest_day', lambda: day)
    monkeypatch.setattr('sys.argv', ['build_stock_filter_fundamental_history.py', '--latest-trading-day'])
    with patch.object(builder.pd, 'read_parquet', side_effect=AssertionError('must reuse without scans')):
        builder.main()
    assert 'reused' in capsys.readouterr().out
    assert target.read_text(encoding='utf-8') == json.dumps(payload)
    assert locked.exists()  # a pre-existing lock belongs to another process


def test_old_schema_is_not_accepted_as_reusable(tmp_path):
    from scripts import build_stock_filter_fundamental_history as builder
    day = '2026-11-11'
    file = tmp_path / f'{day}.json'
    file.write_text(json.dumps({'schema_version': 'stock-filter-fundamental-history-v4', 'as_of_date': day, 'stocks': {'sz:000001': {}}}))
    assert not builder.reusable_snapshot(file, day)


def test_on_demand_builder_adopts_only_its_own_lock(tmp_path):
    from app import stock_filter
    with patch.object(stock_filter, 'HISTORICAL_FUNDAMENTALS', tmp_path), \
         patch.object(stock_filter, '_read_json', return_value={}), \
         patch.object(stock_filter.subprocess, 'Popen') as spawned:
        with pytest.raises(ValueError, match='snapshot is building'):
            stock_filter._historical_universe('2026-11-13')
    command = spawned.call_args.args[0]
    assert command[-1] == '--adopt-lock'
    assert (tmp_path / '2026-11-13.building').exists()


def test_plan_date_only_counts_current_schema_published_pit_files(tmp_path):
    from app.pipeline.task_freshness import task_freshness

    folder = tmp_path / 'datasets/final/stock_filter_fundamental_history'
    folder.mkdir(parents=True)
    def save(day, version):
        (folder / f'{day}.json').write_text(json.dumps({
            'schema_version': version, 'as_of_date': day,
            'financial_information_cutoff': day, 'valuation_price_basis': 'raw_unadjusted_close',
            'stocks': {'sz:000001': {}}}), encoding='utf-8')
    save('2026-11-10', 'stock-filter-fundamental-history-v7')
    save('2026-11-11', 'stock-filter-fundamental-history-v4')
    assert task_freshness('build_stock_filter_fundamental_history', tmp_path)['data_date'] == '2026-11-10'
    save('2026-11-12', 'stock-filter-fundamental-history-v7')
    assert task_freshness('build_stock_filter_fundamental_history', tmp_path)['data_date'] == '2026-11-12'
