import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "backtest_bz_active_gc_pe.py"


def load_rps_pool_helper():
    """Load only the import-safe helper section, not the backtest CLI loop."""
    namespace = {"__file__": str(SCRIPT_PATH), "__name__": "backtest_bz_active_gc_pe_test"}
    source = SCRIPT_PATH.read_text(encoding="utf-8").split("# ── 参数 ──", 1)[0]
    exec(compile(source, str(SCRIPT_PATH), "exec"), namespace)
    return namespace["load_latest_rps_stock_pool"]


class BacktestBzActiveGcPeTests(unittest.TestCase):
    def test_stock_pool_uses_latest_authoritative_parquet_rows(self) -> None:
        load_pool = load_rps_pool_helper()
        with TemporaryDirectory() as temporary_dir:
            parquet = Path(temporary_dir) / "dataset_stock_rps_history.parquet"
            pd.DataFrame([
                {"trading_day": "2026-07-30", "market": "sh", "symbol": "600001"},
                {"trading_day": "2026-07-31", "market": "sh", "symbol": "600001"},
                {"trading_day": "2026-07-31", "market": "sz", "symbol": "000001"},
            ]).to_parquet(parquet, index=False)

            self.assertEqual(load_pool(parquet), ["000001", "600001"])

    def test_backtest_does_not_reference_removed_current_rps_json(self) -> None:
        self.assertNotIn("dataset_stock_rps_current.json", SCRIPT_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
