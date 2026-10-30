"""Focused integration check against the local financial warehouse (no rebuild)."""
import json
from pathlib import Path

import pandas as pd

from app.financial.quarterly_monitor import build_quarterly_financial_monitor
from app.undervaluation.quarterly_momentum import evaluate_quarterly_momentum
from scripts.build_strict_financial_health_snapshot import _report


def test_real_002230_q2_and_q3_loss_direction():
    root = Path(__file__).resolve().parents[1]
    evidence = {}
    for suffix in ('Q2', 'Q3'):
        periods = [f'2025{suffix}', '2025A', f'2026{suffix}']
        reports = [_report(p, pd.read_parquet(root / f'data/derived/financial_ts/by_quarter/{p}.parquet').loc['002230']) for p in periods]
        monitor = build_quarterly_financial_monitor(reports, '计算机')
        result = evaluate_quarterly_momentum(monitor)
        comparison = monitor['profit_comparisons']['ex_net_profit']
        assert comparison['direction'] == 'deteriorating'
        assert result['status'] == 'NOT_IMPROVING'
        assert monitor['dimensions'][0]['status'] == 'watch'
        if suffix == 'Q3':
            assert comparison['previous'] == -337930816
            assert comparison['current'] == -762999232
        evidence[suffix] = {'profit_change': comparison, 'momentum': result}
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
