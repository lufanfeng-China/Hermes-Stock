"""Retirement and replacement contract for the stock-analysis Wyckoff observation."""
from pathlib import Path

from app.pipeline.commands import _data_update_commands

ROOT = Path(__file__).resolve().parents[1]


def test_abcd_active_surfaces_are_retired():
    handler = (ROOT / 'app/handler.py').read_text(encoding='utf-8')
    page = (ROOT / 'web/stock-analysis.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/stock-analysis.js').read_text(encoding='utf-8')
    for token in ('"/api/regime-classify"', '"/api/regime-history-series"',
                  'def handle_regime_classify', 'def handle_regime_history_series'):
        assert token not in handler
    for token in ('/api/regime-classify', '/api/regime-history-series', 'renderStageTimeline',
                  'renderStage(stage)', 'stageTimeline'):
        assert token not in js
    assert 'A 底部构筑/下跌中继' not in page
    assert 'stage-timeline-section' not in page
    assert 'rebuild_stage_history' not in [name for name, _ in _data_update_commands(trading_day=None)]
    assert 'rebuild_stage_history' not in [name for name, _ in _data_update_commands(trading_day=None, retry_failed=True)]
    for path in ('app/stage_regime.py', 'app/stage_regime_series.py', 'app/regime_history_store.py',
                 'scripts/build_regime_history.py', 'scripts/check_regime_series_parity.py',
                 'scripts/export_regime_timeline.py', 'scripts/report_regime_stats.py'):
        assert not (ROOT / path).exists(), path


def test_wyckoff_observation_is_wired_to_actual_data():
    handler = (ROOT / 'app/handler.py').read_text(encoding='utf-8')
    page = (ROOT / 'web/stock-analysis.html').read_text(encoding='utf-8')
    js = (ROOT / 'web/stock-analysis.js').read_text(encoding='utf-8')
    assert '"/api/wyckoff-observation"' in handler
    assert 'observe_wyckoff(bars)' in handler
    assert 'load_tdx_qfq_daily(symbol)' in handler
    assert 'id="wyckoff-observation"' in page
    assert '/api/wyckoff-observation?market=${encodeURIComponent(stock.market)}&symbol=' in js
    assert 'renderWyckoffObservation' in js
    assert '前复权' in page
    assert '候选' in page and '确认' in page and '失效' in page
