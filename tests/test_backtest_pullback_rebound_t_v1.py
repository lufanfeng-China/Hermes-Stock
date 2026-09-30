import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backtest_pullback_rebound_t_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pullback_rebound_t_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PullbackReboundDailyTTests(unittest.TestCase):
    def test_buy_is_cancelled_only_when_next_open_gaps_above_4pct(self):
        engine = load_module()
        self.assertFalse(engine.cancel_pullback_buy(open_price=104.0, previous_close=100.0))
        self.assertTrue(engine.cancel_pullback_buy(open_price=104.1, previous_close=100.0))

    def test_completed_lot_return_includes_raw_execution_costs(self):
        engine = load_module()
        self.assertGreater(engine.completed_lot_net_return(108.0, 100.0), 0.0)
        self.assertLess(engine.completed_lot_net_return(100.0, 100.0), 0.0)

    def test_qfq_signal_and_raw_entry_return_are_not_mixed(self):
        engine = load_module()
        self.assertFalse(engine.raw_target_reached(raw_close=107.99, raw_entry=100.0))
        self.assertTrue(engine.raw_target_reached(raw_close=108.0, raw_entry=100.0))


if __name__ == "__main__":
    unittest.main()
