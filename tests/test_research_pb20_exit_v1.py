import importlib.util
from pathlib import Path
import sys
import unittest

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "research_pb20_exit_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pb20_exit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def bars(rows):
    frame = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"])
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index("date")


class PB20ExitSimulationTests(unittest.TestCase):
    def test_stop_uses_stop_price_when_daily_low_breaches_stop(self):
        exit_research = load_module()
        frame = bars([
            ("2025-01-02", 100, 106, 95, 103),
            ("2025-01-03", 103, 104, 91, 93),
            ("2025-01-06", 94, 95, 92, 94),
        ])
        result = exit_research.simulate_trade(frame, entry_index=0, hold_days=2, stop_pct=0.08, target_pct=0.20)
        self.assertEqual(result["reason"], "hard_stop")
        self.assertEqual(result["exit_date"], "2025-01-03")
        self.assertAlmostEqual(result["exit_price_raw"], 92.0)

    def test_ambiguous_same_bar_stop_and_target_uses_conservative_stop(self):
        exit_research = load_module()
        frame = bars([
            ("2025-01-02", 100, 125, 90, 115),
            ("2025-01-03", 115, 116, 114, 115),
        ])
        result = exit_research.simulate_trade(frame, entry_index=0, hold_days=1, stop_pct=0.08, target_pct=0.20)
        self.assertEqual(result["reason"], "ambiguous_stop_first")
        self.assertAlmostEqual(result["exit_price_raw"], 92.0)

    def test_target_uses_target_price_when_high_reaches_target(self):
        exit_research = load_module()
        frame = bars([
            ("2025-01-02", 100, 121, 99, 118),
            ("2025-01-03", 117, 118, 115, 116),
        ])
        result = exit_research.simulate_trade(frame, entry_index=0, hold_days=1, stop_pct=0.08, target_pct=0.20)
        self.assertEqual(result["reason"], "take_profit")
        self.assertAlmostEqual(result["exit_price_raw"], 120.0)

    def test_time_exit_executes_at_next_open_after_completed_hold_window(self):
        exit_research = load_module()
        frame = bars([
            ("2025-01-02", 100, 105, 98, 103),
            ("2025-01-03", 104, 106, 101, 105),
            ("2025-01-06", 110, 111, 108, 109),
        ])
        result = exit_research.simulate_trade(frame, entry_index=0, hold_days=2, stop_pct=0.08, target_pct=0.20)
        self.assertEqual(result["reason"], "time_exit_next_open")
        self.assertEqual(result["exit_date"], "2025-01-06")
        self.assertAlmostEqual(result["exit_price_raw"], 110.0)


if __name__ == "__main__":
    unittest.main()
