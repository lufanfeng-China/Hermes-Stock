from __future__ import annotations

import unittest

import pandas as pd


class MarketRelativeStrengthTests(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        # Both securities have 251+ QFQ bars.  In the final 20 sessions, A
        # gains +0.1% daily while B falls -2.0% daily: daily equal-weight
        # benchmark is negative, so A must register a positive anti-fall edge.
        dates = pd.bdate_range("2025-01-01", periods=271)
        rows = []
        for market, symbol, daily_return in (("sh", "600001", 0.001), ("sz", "000001", -0.02)):
            close = 10.0
            for index, date in enumerate(dates):
                if index >= 251:
                    close *= 1.0 + daily_return
                rows.append({"date": date, "market": market, "symbol": symbol, "close": close})
        return pd.DataFrame(rows)

    def test_builds_qfq_daily_equal_weight_benchmark_and_auditable_excess(self) -> None:
        from app.market_relative_strength import build_market_relative_strength

        payload = build_market_relative_strength(self._frame(), min_eligible_universe=2)
        stock = payload["stocks"]["sh:600001"]

        self.assertEqual("tdx_export_qfq", stock["price_basis"])
        self.assertEqual("all_a_daily_equal_weight_rps_universe", stock["benchmark_method"])
        self.assertGreater(stock["mrs_score"], 70)
        self.assertGreater(stock["excess_return_20_pp"], 0)
        self.assertEqual(20, stock["down_market_days_20"])
        self.assertEqual(20, stock["down_market_outperform_days_20"])
        self.assertEqual(100.0, stock["down_market_win_rate_20"])
        self.assertGreater(stock["down_market_total_excess_pp_20"], 0)
        self.assertAlmostEqual(stock["down_market_total_excess_pp_20"], sum(item["excess_return_pp"] for item in stock["down_market_detail_20"]), places=3)
        detail = stock["down_market_detail_20"]
        self.assertEqual(20, len(detail))
        self.assertEqual(sorted(item["date"] for item in detail), [item["date"] for item in detail])
        self.assertTrue(all(item["market_return_pct"] < 0 for item in detail))
        self.assertTrue(all(item["stock_return_pct"] > 0 for item in detail))
        self.assertTrue(all(item["excess_return_pp"] > 0 for item in detail))

    def test_marks_antifall_as_insufficient_when_fewer_than_five_down_days(self) -> None:
        from app.market_relative_strength import build_market_relative_strength

        frame = self._frame()
        # Make the broad benchmark non-negative in 16 of the final 20 days.
        mask = (frame["symbol"] == "000001") & (frame["date"] >= frame["date"].max() - pd.Timedelta(days=21))
        frame.loc[mask, "close"] = 10.0
        payload = build_market_relative_strength(frame, min_eligible_universe=2)

        self.assertLess(payload["stocks"]["sh:600001"]["down_market_days_20"], 5)
        self.assertEqual("sample_insufficient", payload["stocks"]["sh:600001"]["anti_fall_status"])

    def test_classifies_conflict_between_long_term_mrs_and_recent_er20(self) -> None:
        from app.market_relative_strength import classify_relative_strength_state

        self.assertEqual("high_level_weakening", classify_relative_strength_state(82, -0.1))
        self.assertEqual("low_level_strengthening", classify_relative_strength_state(40, 0.1))
        self.assertEqual("trend_aligned", classify_relative_strength_state(82, 1.0))

    def test_reloads_published_snapshot_after_rebuild_without_restart(self) -> None:
        """A daily rebuild must be visible to a running server (no restart)."""
        import json
        import tempfile
        import time
        from pathlib import Path
        from unittest import mock

        import app.market_relative_strength as module

        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "market_relative_strength_current.json"

            def publish(as_of: str) -> None:
                snapshot.write_text(json.dumps({"as_of_date": as_of, "stocks": {"sh:600519": {"symbol": "600519"}}}), encoding="utf-8")
                # Guarantee a distinct mtime even on coarse-grained filesystems.
                stamp = time.time() + (1 if as_of.endswith("17") else 0)
                import os
                os.utime(snapshot, (stamp, stamp))

            with mock.patch.object(module, "CURRENT_SNAPSHOT", snapshot):
                publish("2026-11-16")
                self.assertEqual("2026-11-16", module.load_current_snapshot()["as_of_date"])
                # Cached read: same file identity keeps the cached payload.
                self.assertEqual("2026-11-16", module.load_current_snapshot()["as_of_date"])
                publish("2026-11-17")
                self.assertEqual("2026-11-17", module.load_current_snapshot()["as_of_date"])
                self.assertEqual("2026-11-17", module.stock_response("SH", "600519")["as_of_date"])

    def test_missing_snapshot_returns_empty_mapping(self) -> None:
        from pathlib import Path
        from unittest import mock

        import app.market_relative_strength as module

        with mock.patch.object(module, "CURRENT_SNAPSHOT", Path("/nonexistent/mrs.json")):
            self.assertEqual({}, module.load_current_snapshot())


if __name__ == "__main__":
    unittest.main()
