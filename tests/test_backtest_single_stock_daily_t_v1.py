import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backtest_single_stock_daily_t_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("single_stock_t", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SingleStockDailyTTests(unittest.TestCase):
    def test_t_cycle_return_includes_both_sides_cost_and_slippage(self):
        engine = load_module()
        net = engine.t_cycle_net_return(sell_price=110.0, rebuy_price=100.0)
        self.assertGreater(net, 0.0)
        self.assertLess(net, 0.10)

    def test_high_sell_is_cancelled_on_next_open_gap_down_exceeding_3pct(self):
        engine = load_module()
        self.assertTrue(engine.cancel_high_sell_on_gap(open_price=96.9, previous_close=100.0))
        self.assertFalse(engine.cancel_high_sell_on_gap(open_price=97.0, previous_close=100.0))

    def test_rebuy_is_cancelled_on_next_open_gap_up_exceeding_5pct(self):
        engine = load_module()
        self.assertTrue(engine.cancel_rebuy_on_gap(open_price=105.1, previous_close=100.0))
        self.assertFalse(engine.cancel_rebuy_on_gap(open_price=105.0, previous_close=100.0))


if __name__ == "__main__":
    unittest.main()
