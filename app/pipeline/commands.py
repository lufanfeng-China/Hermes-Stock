"""Commands for the daily-data update workbench."""
import importlib
import subprocess
import sys
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from threading import Thread

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"
TONGDAXIN_DIR = "/home/lufanfeng/tdx_data"
DERIVED_FINAL_DIR = PROJECT_ROOT / "data" / "derived" / "datasets" / "final"
DEFAULT_SYMBOL = "601600"



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


@lru_cache(maxsize=1)
def _latest_minute_trading_day() -> str | None:
    """Return the newest locally available 1-minute date for the archive symbol.

    Daily snapshots can be newer than the locally synced minute files.  The
    archive requires complete minute bars, so it must not run ahead of this
    source.
    """
    script = (
        'from mootdx.reader import Reader; '
        f'r=Reader.factory(market="std", tdxdir=r"{TONGDAXIN_DIR}"); '
        f'f=r.minute(symbol="{DEFAULT_SYMBOL}", suffix=1); '
        'print(f.index.max().date().isoformat() if not f.empty else "")'
    )
    try:
        result = subprocess.run(
            [TONGDAXIN_PYTHON, '-c', script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        latest_day = result.stdout.strip()
        return latest_day if result.returncode == 0 and latest_day else None
    except (OSError, subprocess.SubprocessError):
        return None


def archive_daily_is_ready(trading_day: str | None) -> bool:
    """Whether local minute data covers the day requested by archive_daily."""
    latest_minute_day = _latest_minute_trading_day()
    return bool(trading_day and latest_minute_day and latest_minute_day >= trading_day)


def clear_runtime_data_caches() -> None:
    module_names = [
        'app.search.index',
        'app.stock_filter',
        'app.market_relative_strength',
        'app.relative_valuation.data_loader',
        'app.relative_valuation.history',
        'app.financial.reports',
        'app.financial.health_peer_snapshot',
        'app.undervaluation.service',
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
        return [
            ('build_industry_metric_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_industry_metric_snapshot.py')]),
            (
                'build_industry_relative_valuation_snapshot',
                [
                    TONGDAXIN_PYTHON,
                    str(PROJECT_ROOT / 'scripts/build_industry_relative_valuation_snapshot.py'),
                    '--reuse-existing-complete',
                ],
            ),
            ('build_good_stock_financial_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_good_stock_financial_snapshot.py')]),
            ('build_good_stock_undervaluation_current', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_good_stock_undervaluation_current.py')]),
            ('build_stock_filter_pe_percentile_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_filter_pe_percentile_snapshot.py')]),
            ('build_stock_filter_turnover_percentile_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_filter_turnover_percentile_snapshot.py')]),
            ('build_stock_filter_fundamental_history', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_filter_fundamental_history.py'), '--latest-trading-day']),
            # 慢任务失败时只重跑自身；重试子集也保持与全量链一致的末尾顺序。
            ('build_swing_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_swing_snapshot.py')]),
            ('build_swing_state_runs', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_swing_state_runs.py')]),
            ('build_concept_temperature', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_concept_temperature.py')]),
            ('build_industry_temperature', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_concept_temperature.py'), '--scope', 'industry']),
            ('build_wyckoff_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_wyckoff_snapshot.py')]),
        ]
    commands: list[tuple[str, list[str]]] = [
        # The workbench deliberately excludes archive_daily: that legacy archive
        # builds 1-minute/15-minute artifacts for a single symbol, while current
        # production indicators are daily-bar and financial-data based.
        ('sync_tdx_qfq_exports', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/sync_tdx_qfq_exports.py')]),
        # 行业归属（通达信 tdxhy.cfg → 申万二级行业）必须早于行业温度、行业指标与
        # 筛选页行业列，否则这些产物会用上一次的行业划分。解析只要几秒。
        (
            'refresh_industry_membership',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/parse_industry_dataset.py')]
            + (['--trading-day', trading_day] if trading_day else []),
        ),
        ('build_stock_filter_qfq_daily', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_filter_qfq_daily.py')]),
        # Derived once during data maintenance so /api/stock-filter never groups 12M daily rows.
        ('build_stock_filter_market_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_filter_market_snapshot.py')]),
        ('build_market_relative_strength', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_market_relative_strength.py')]),
        ('update_financial_ts', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/update_financial_ts.py')]),
        # 股票筛选页的当季健康直接读这份快照。它必须紧跟财报仓库更新重建，否则
        # 新披露的季报永远进不了页面（曾经整整一季停在 2026Q2）。每只股票各自
        # 取最近一期已披露季报，季报缺失不影响是否入库。
        ('build_strict_financial_health_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_strict_financial_health_snapshot.py')]),
        ('build_financial_health_peer_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_financial_health_peer_snapshot.py')]),
        ('build_financial_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_financial_snapshot_from_warehouse.py'), 'latest']),
        # Snapshot-only source for stock-analysis industry peer dialogs.  It is
        # independently runnable/retryable and never blocks technical tasks.
        ('build_industry_metric_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_industry_metric_snapshot.py')]),
        ('build_industry_relative_valuation_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_industry_relative_valuation_snapshot.py')]),
        # Independent local-only good-stock publications; never overwrite legacy financial rankings.
        ('build_good_stock_financial_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_good_stock_financial_snapshot.py')]),
        ('build_good_stock_undervaluation_current', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_good_stock_undervaluation_current.py')]),
        # Incrementally recompute from the last published RPS day through the current QFQ day.
        ('refresh_rps_daily', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/refresh_rps_daily.py')]),
        # 原始日线 + 最新已披露财报构建自身每日 PE 分位；QFQ/RPS 与原始价日期不一致时拒绝发布。
        ('build_stock_filter_pe_percentile_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_filter_pe_percentile_snapshot.py')]),
        # 股本缺证时只使用交易日已公告财报；全市场换手率分位单独发布、失败不覆盖旧值。
        ('build_stock_filter_turnover_percentile_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_filter_turnover_percentile_snapshot.py')]),
        # PIT 当日文件在财报、前复权行情及换手输入就绪后发布；脚本在启动时校验源日期，
        # 已发布同版本日期则复用，不使用链首可能过期的 trading_day。
        ('build_stock_filter_fundamental_history', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_stock_filter_fundamental_history.py'), '--latest-trading-day']),
        (
            'rebuild_macd_signals',
            [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_macd_signals.py'),
             '--tdxdir', TONGDAXIN_DIR],
        ),
        # 已确认峰谷因果式v5独立快照；不更改旧生命周期分类器，筛选仅读同日完整发布。
        ('build_swing_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_swing_snapshot.py')]),
        # 同日v5结构状态的连续区间证据；从刚发布的完整波峰波谷快照取日期，
        # 不得沿用链首日期；失败独立重试，不现场扫描筛选请求。
        ('build_swing_state_runs', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_swing_state_runs.py')]),
        # 概念温度快照：读通达信 概念板块.txt + QFQ 日线，逐窗口(3/5/10/20/60)算温度、
        # 连续天数与热度序列。单次 10-40 分钟，故排在流水线尾段：只写
        # dataset_concept_temperature_current.json，没有任何后续任务读它，
        # 失败不影响前面每一步，可单独重跑。
        ('build_concept_temperature', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_concept_temperature.py')]),
        # 行业温度与概念温度同一算法、不同成分来源（申万二级行业）。同样排在尾段,
        # 产物只被行业榜单读取,失败不影响前面每一步,可单独重跑。
        ('build_industry_temperature', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_concept_temperature.py'), '--scope', 'industry']),
        # 全市场前复权威科夫事件只写独立的版本化快照；完成其他产物后最后运行，
        # 避免耗时扫描阻断上游；失败可单独重试。
        ('build_wyckoff_snapshot', [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/build_wyckoff_snapshot.py')]),
        # Optional: Kronos AI prediction (CPU ~10s/stock, 5000 stocks ~14 hours)
        # Uncomment to enable daily AI prediction rebuild:
        # (
        #     'rebuild_kronos_prediction',
        #     [TONGDAXIN_PYTHON, str(PROJECT_ROOT / 'scripts/predict_kronos.py'),
        #      '--tdxdir', TONGDAXIN_DIR],
        # ),
    ]
    return commands

