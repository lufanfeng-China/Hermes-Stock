import sys
import unittest

sys.path.insert(0, "/home/lufanfeng/Project-Hermes-Stock")
from app.search.macd_gc import build_monthly_mtm


class MonthlyMtmHistoryTests(unittest.TestCase):
    def test_uses_last_trading_day_of_each_month_and_preserves_components(self):
        daily = [
            {"date": "2026-01-29", "cash": 90, "market_value": 10, "equity": 100},
            {"date": "2026-01-30", "cash": 80, "market_value": 25, "equity": 105},
            {"date": "2026-02-26", "cash": 70, "market_value": 40, "equity": 110},
            {"date": "2026-02-27", "cash": 60, "market_value": 55, "equity": 115},
        ]

        monthly = build_monthly_mtm(daily)

        self.assertEqual([
            {"month": "2026-01", "cash": 80.0, "market_value": 25.0, "equity": 105.0},
            {"month": "2026-02", "cash": 60.0, "market_value": 55.0, "equity": 115.0},
        ], monthly)


if __name__ == "__main__":
    unittest.main()
