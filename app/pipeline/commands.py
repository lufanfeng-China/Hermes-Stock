"""Data update commands and orchestration."""
import importlib
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from threading import Thread

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/mnt/c/new_tdx64"
DERIVED_FINAL_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
STOCK_SCREENER_STRATEGY_DATASET = DERIVED_FINAL_DIR / "dataset_stock_screener_strategies_current.json"
STOCK_RPS_CURRENT_DATASET = DERIVED_FINAL_DIR / "dataset_stock_rps_current.json"
DEFAULT_SYMBOL = "601600"

def ensure_stock_screener_strategy_dataset(strategy: str) -> None:
    """Build the stock-screener strategy dataset on demand when a preset needs it."""
    strategy = str(strategy or "").strip()
    if strategy not in {"rps_first", "ma_cross", "washout", "rps_climb", "blowup_stall", "blowup_break"}:
        return
    dataset_is_current = (
        STOCK_SCREENER_STRATEGY_DATASET.exists()
        and (
            not STOCK_RPS_CURRENT_DATASET.exists()
            or STOCK_SCREENER_STRATEGY_DATASET.stat().st_mtime >= STOCK_RPS_CURRENT_DATASET.stat().st_mtime
        )
    )
    dataset_has_strategy = False
    if STOCK_SCREENER_STRATEGY_DATASET.exists():
        try:
            payload = json.loads(STOCK_SCREENER_STRATEGY_DATASET.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("rows", [])
            dataset_has_strategy = any(str(row.get("strategy", "")).strip() == strategy for row in rows if isinstance(row, dict))
        except Exception:
            dataset_has_strategy = False
    if dataset_is_current and dataset_has_strategy:
        return
    result = subprocess.run(
        [
            TONGDAXIN_PYTHON,
            str(PROJECT_ROOT / "scripts" / "build_stock_screener_strategies.py"),
            "--strategy",
            strategy,
            "--tdxdir",
            TONGDAXIN_DIR,
            "--output",
            str(STOCK_SCREENER_STRATEGY_DATASET),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(_tail_lines(result.stderr or result.stdout or "strategy build failed"))
    load_stock_screener_strategy_rows.cache_clear()



def _latest_trading_day_for_refresh() -> str | None:
    try:
        search_index = importlib.import_module('app.search.index')
        snapshot = search_index._load_latest_daily_snapshot('sh', DEFAULT_SYMBOL)
        trading_day = str(snapshot.get('trading_day') or '').strip()
        if trading_day:
            return trading_day
    except Exception:
        return None
    return None


def clear_runtime_data_caches() -> None:
    module_names = [
        'app.search.index',
        'app.relative_valuation.data_loader',
        'app.relative_valuation.history',
    ]
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            cache_clear = getattr(attr, 'cache_clear', None)
            if callable(cache_clear):
                try:
                    cache_clear()
                except Exception:
                    continue



def _data_update_commands(trading_day: str | None, retry_failed: bool = False) -> list[tuple[str, list[str]]]:
    if retry_failed:
        return [(
            'build_industry_relative_valuation_snapshot',
            [
                TONGDAXIN_PYTHON,
                str(PROJECT_ROOT / 'scripts/build_industry_relative_valuation_snapshot.py'),
                '--reuse-existing-complete',
            ],
        )]
    commands: list[tuple[str, list[str]]] = []
    today = datetime.now().strftime('%Y-%m-%d')
    # Skip archive_daily when trading day is today — minute data may not yet be synced
    if trading_day and trading_day != today:
        commands.append((
            'archive_daily',
            [
                TONGDAXIN_PYTHON,
                str(PROJECT_ROOT / 'scripts/archive_daily.py'),
                '--trading-day',
                trading_day,
                '--force-rerun',
                '--rerun-reason',
                'manual-dashboard-refresh',
            ],
        ))
    commands.extend([
        ('update_financial_ts', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/update_financial_ts.py')]),
        ('build_financial_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_financial_snapshot_from_warehouse.py'), 'latest']),
        ('build_industry_relative_valuation_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_industry_relative_valuation_snapshot.py')]),
        (
            'build_rps_history',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_rps_history.py'), '--ndays', '120'],
        ),
        (
            'update_rps_current',
            [TONGDAXIN_PYTHON, '-c',
             'import json, sys;'
             'from pathlib import Path;'
             f'hist_path = Path(r\"{DERIVED_FINAL_DIR}/dataset_stock_rps_history.json\");'
             f'curr_path = Path(r\"{DERIVED_FINAL_DIR}/dataset_stock_rps_current.json\");'
             'all_rows = json.loads(hist_path.read_text(encoding=\"utf-8\"));'
             'latest = max(r[\"trading_day\"] for r in all_rows if r.get(\"trading_day\"));'
             'current = [r for r in all_rows if r.get(\"trading_day\") == latest];'
             'curr_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding=\"utf-8\");'
             f'print(f\"RPS current updated to {{latest}} ({{len(current)}} rows)\")'],
        ),
        (
            'rebuild_screener_first',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'rps_first', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_ma_cross',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'ma_cross', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_washout',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'washout', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_rps_climb',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'rps_climb', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_blowup_stall',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'blowup_stall', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        (
            'rebuild_screener_blowup_break',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_screener_strategies.py'),
             '--strategy', 'blowup_break', '--tdxdir', TONGDAXIN_DIR,
             '--output', str(STOCK_SCREENER_STRATEGY_DATASET)],
        ),
        # Optional: Kronos AI prediction (CPU ~10s/stock, 5000 stocks ~14 hours)
        # Uncomment to enable daily AI prediction rebuild:
        # (
        #     'rebuild_kronos_prediction',
        #     [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/predict_kronos.py'),
        #      '--tdxdir', TONGDAXIN_DIR],
        # ),
    ])
    return commands

