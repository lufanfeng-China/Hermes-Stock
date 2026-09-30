import importlib.util
from pathlib import Path
import subprocess
import unittest

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "research_pre_surge_confirmation_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("research_pre_surge_confirmation_v1", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreSurgeConfirmationResearchTests(unittest.TestCase):
    def test_confirmation_signal_uses_prior_high_only_and_labels_future_high(self) -> None:
        research = load_module()
        dates = pd.bdate_range("2025-01-01", periods=100)
        close = np.full(100, 9.0)
        close[50:70] = np.linspace(9.6, 10.0, 20)
        close[70] = 10.9
        close[71:91] = np.linspace(11.0, 14.0, 20)
        frame = pd.DataFrame(
            {
                "open": np.full(100, 10.0),
                "high": np.full(100, 10.1),
                "low": np.full(100, 9.9),
                "close": close,
                "volume": np.full(100, 100.0),
            },
            index=dates,
        )
        frame.loc[dates[70], ["open", "high", "low", "close", "volume"]] = [10.0, 11.1, 9.9, 10.9, 200.0]
        frame.loc[dates[71:91], "high"] = np.linspace(11.1, 14.3, 20)

        rows = research.compute_confirmation_rows(frame, symbol="000001", start_day="2025-01-01")
        row = next(item for item in rows if item["trading_day"] == "2025-04-09")

        self.assertGreater(row["prior_20_high"], 10.0)
        self.assertEqual(row["prior_20_high"], 10.1)
        self.assertGreaterEqual(row["future_20_max_return"], 0.29)
        self.assertTrue(row["is_surge_30pct"])

    def test_future_label_excludes_signal_day(self) -> None:
        research = load_module()
        dates = pd.bdate_range("2025-01-01", periods=91)
        close = np.full(91, 9.0)
        close[50:70] = np.linspace(9.6, 10.0, 20)
        close[70] = 10.9
        frame = pd.DataFrame(
            {"open": 10.0, "high": 10.1, "low": 9.9, "close": close, "volume": 100.0}, index=dates
        )
        frame.loc[dates[70], ["open", "high", "low", "close", "volume"]] = [10.0, 11.0, 9.9, 10.9, 200.0]
        frame.loc[dates[71:91] if len(dates) > 91 else dates[71:], "high"] = 10.5

        rows = research.compute_confirmation_rows(frame, symbol="000001", start_day="2025-01-01")
        row = next(item for item in rows if item["trading_day"] == "2025-04-09")
        self.assertLess(row["future_20_max_return"], 0.30)
        self.assertFalse(row["is_surge_30pct"])
    def test_compact_pb20_rule_has_strict_boundaries(self) -> None:
        research = load_module()
        frame = pd.DataFrame(
            {
                "breakout_pct": [0.0200, 0.0201, 0.0201, 0.0201, 0.06],
                "ma20_gap": [0.40, 0.34, 0.3501, 0.3501, 0.36],
                "volume_ratio": [1.20, 1.20, 0.80, 0.8001, 1.70],
                "body_ratio": [0.80, 0.80, 0.80, 0.60, 0.6001],
            }
        )
        self.assertEqual(research.compact_pb20_mask(frame).tolist(), [False, False, False, False, True])

    def test_pb20_export_keeps_first_breakout_without_volume_confirmation(self) -> None:
        research = load_module()
        dates = pd.bdate_range("2025-01-01", periods=91)
        close = np.full(91, 9.0)
        close[50:70] = np.linspace(9.6, 10.0, 20)
        close[70] = 10.9
        signal = pd.DataFrame(
            {"open": 10.0, "high": 10.1, "low": 9.9, "close": close, "volume": 100.0}, index=dates
        )
        signal.loc[dates[70], ["open", "high", "low", "close", "volume"]] = [10.0, 11.1, 9.9, 10.9, 120.0]
        raw = signal.copy()
        raw.loc[dates[71:91], "high"] = 14.0

        rows = research.compute_pb20_rows(signal, "000001", "2025-01-01", raw_frame=raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["trading_day"], "2025-04-09")
        self.assertLess(rows[0]["volume_ratio"], 1.5)

    def test_breakout_is_first_cross_not_each_day_above_prior_high(self) -> None:
        research = load_module()
        close = pd.Series([9.8, 10.1, 10.3, 9.9, 10.2])
        prior_high = pd.Series([10.0, 10.0, 10.0, 10.0, 10.0])
        self.assertEqual(research.first_breakout_cross(close, prior_high).tolist(), [False, True, False, False, True])

    def test_funnel_reports_incremental_stages_with_raw_outcomes(self) -> None:
        research = load_module()
        dates = pd.bdate_range("2025-01-01", periods=91)
        close = np.full(91, 9.0)
        close[50:70] = np.linspace(9.6, 10.0, 20)
        close[70] = 10.9
        signal = pd.DataFrame(
            {"open": 10.0, "high": 10.1, "low": 9.9, "close": close, "volume": 100.0}, index=dates
        )
        signal.loc[dates[70], ["open", "high", "low", "close", "volume"]] = [10.0, 11.1, 9.9, 10.9, 200.0]
        raw = signal.copy()
        raw.loc[dates[71:91], "high"] = 14.0

        funnel = research.compute_funnel_counts(signal, raw_frame=raw, start_day="2025-01-01")
        self.assertGreater(funnel["trend_background"]["candidates"], 0)
        self.assertGreaterEqual(funnel["trend_background"]["candidates"], funnel["breakout"]["candidates"])
        self.assertGreaterEqual(funnel["breakout"]["candidates"], funnel["strong_candle"]["candidates"])
        self.assertEqual(funnel["volume_confirmed"]["candidates"], 1)
        self.assertEqual(funnel["volume_confirmed"]["surges"], 1)

    def test_raw_t_plus_one_label_overrides_qfq_return_label(self) -> None:
        research = load_module()
        dates = pd.bdate_range("2025-01-01", periods=91)
        close = np.full(91, 9.0)
        close[50:70] = np.linspace(9.6, 10.0, 20)
        close[70] = 10.9
        signal = pd.DataFrame(
            {"open": 10.0, "high": 10.1, "low": 9.9, "close": close, "volume": 100.0}, index=dates
        )
        signal.loc[dates[70], ["open", "high", "low", "close", "volume"]] = [10.0, 11.1, 9.9, 10.9, 200.0]
        signal.loc[dates[71:91], "high"] = 14.3
        raw = signal.copy()
        raw.loc[dates[71], "open"] = 20.0
        raw.loc[dates[71:91], "high"] = 22.0

        rows = research.compute_confirmation_rows(signal, symbol="000001", start_day="2025-01-01", raw_frame=raw)
        row = next(item for item in rows if item["trading_day"] == "2025-04-09")
        self.assertEqual(row["entry_open_raw"], 20.0)
        self.assertLess(row["future_20_max_return"], 0.30)
        self.assertFalse(row["is_surge_30pct"])

    def test_script_runs_directly_from_outside_project(self) -> None:
        result = subprocess.run(
            [str(Path.home() / ".venvs/moontdx-china-stock-data/bin/python"), str(SCRIPT_PATH), "--help"],
            cwd="/tmp",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no-lookahead", result.stdout)


if __name__ == "__main__":
    unittest.main()
