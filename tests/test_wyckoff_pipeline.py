"""Wyckoff snapshot must be a real, retryable daily product, not a ghost plan item."""
from app.handler import DATA_UPDATE_TASK_PLAN
from app.pipeline.commands import _data_update_commands
from app.pipeline.runner import _task_timeout


def test_wyckoff_daily_command_follows_qfq_sync_and_is_retryable():
    commands = _data_update_commands(trading_day='2026-10-30')
    ids = [name for name, _ in commands]
    assert ids.index('sync_tdx_qfq_exports') < ids.index('build_wyckoff_snapshot')
    assert ids.index('build_stock_filter_market_snapshot') < ids.index('build_wyckoff_snapshot')
    assert ids[-1] == 'build_wyckoff_snapshot'
    assert ids.index('build_swing_state_runs') < ids.index('build_wyckoff_snapshot')
    assert ids.index('build_industry_temperature') < ids.index('build_wyckoff_snapshot')
    retry_ids = [name for name, _ in _data_update_commands(trading_day='2026-10-30', retry_failed=True)]
    assert retry_ids[-1] == 'build_wyckoff_snapshot'
    # The chain's initial day can be older than the QFQ sync performed earlier in
    # this same run. The builder must select its day from the validated sync manifest.
    full = dict(commands)['build_wyckoff_snapshot']
    retry = dict(_data_update_commands(trading_day='2026-10-30', retry_failed=True))['build_wyckoff_snapshot']
    assert full == retry
    assert '--trading-day' not in full


def test_wyckoff_plan_matches_commands_and_slow_builder_timeout():
    planned = [task['id'] for task in DATA_UPDATE_TASK_PLAN]
    commands = [name for name, _ in _data_update_commands(trading_day='2026-10-30')]
    assert planned == commands
    assert _task_timeout('build_wyckoff_snapshot') >= 3600
