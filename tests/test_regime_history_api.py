"""Contracts for the A/B/C/D regime history store and its endpoint."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from app import handler as app_handler
from app import regime_history_store as store

ITEMS = list(store._ITEMS)


def write_history(path: Path, symbol: str, days: list[str], stages: list[str], scores: list[int]) -> None:
    assert len(days) == len(stages) == len(scores)
    frame = pd.DataFrame({
        "symbol": symbol,
        "trading_day": days,
        "stage": stages,
        "stage_label": [store.STAGE_LABELS[code] for code in stages],
        "score": scores,
        "reason": ["偏低点/量能/结构判定" for _ in days],
        "ma20": [10.0] * len(days),
        "vol_ma5": [1e6] * len(days),
        "vol_ma60": [1.2e6] * len(days),
        "box_high": [12.0] * len(days),
        "box_low": [9.0] * len(days),
        "box_mid": [10.5] * len(days),
        "box_position": [0.5] * len(days),
        "sell_days_15": [1] * len(days),
        "放量滞涨": [False] * len(days),
        "抛售日密集": [False] * len(days),
        **{key: [True] * len(days) for key in ITEMS},
    })
    frame.to_parquet(path, index=False)


class RegimeHistoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "regime.parquet"
        days = [f"2026-01-{day:02d}" for day in range(1, 21)]
        stages = ["A"] * 5 + ["B"] * 3 + ["C"] * 7 + ["D"] * 5
        scores = [1] * 11 + [-1] * 9
        write_history(self.path, "600000", days, stages, scores)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_window_and_rows(self) -> None:
        payload = store.load_regime_series("600000", 12, path=self.path)

        self.assertEqual(12, payload["bars"])
        self.assertEqual(12, payload["window_bars"])
        self.assertEqual("2026-01-09", payload["window_start"])
        self.assertEqual("2026-01-20", payload["as_of"])
        self.assertEqual(60, payload["judgement_lookback_bars"])
        days = [row["trading_day"] for row in payload["rows"]]
        self.assertEqual(sorted(days), days)

    def test_segments_collapse_and_current_is_the_last(self) -> None:
        payload = store.load_regime_series("600000", 12, path=self.path)
        segments = payload["segments"]

        self.assertEqual(sum(segment["trading_days"] for segment in segments), payload["bars"])
        self.assertEqual(segments[-1]["stage"], payload["current"]["stage"])
        # 窗口是 01-09..01-20：C(09-15, 7 天) → D(16-20, 5 天)，当前段是 D
        self.assertEqual("D", payload["current"]["stage"])
        self.assertEqual(5, payload["current"]["trading_days"])
        self.assertEqual(["C", "D"], [segment["stage"] for segment in segments])
        self.assertEqual(7, segments[0]["trading_days"])

    def test_rows_carry_score_items_penalties_and_evidence(self) -> None:
        payload = store.load_regime_series("600000", 5, path=self.path)
        row = payload["rows"][-1]

        self.assertEqual(-1, row["score"])
        self.assertEqual(set(ITEMS), set(row["items"]))
        self.assertIn("放量滞涨", row["penalties"])
        self.assertIn("box_position", row["evidence"])
        self.assertEqual("tdx_export_qfq", payload["price_basis"])
        self.assertEqual("risk", row["tone"])

    def test_unknown_symbol_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            store.load_regime_series("999999", 60, path=self.path)


class RegimeEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "regime.parquet"
        days = [f"2026-02-{day:02d}" for day in range(1, 11)]
        write_history(self.path, "600000", days, ["C"] * 10, [4] * 10)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _call(self, query: str):
        request = Mock()
        with patch.object(store, "DEFAULT_HISTORY", self.path):
            app_handler.StockDashboardHandler.handle_regime_history_series(request, query)
        return request.respond_json.call_args.args

    def test_returns_rows_for_requested_bars(self) -> None:
        status, body = self._call("symbol=600000&bars=5")
        self.assertEqual(200, status)
        self.assertEqual(5, body["bars"])
        self.assertEqual("C", body["current"]["stage"])

    def test_rejects_non_integer_bars(self) -> None:
        status, body = self._call("symbol=600000&bars=abc")
        self.assertEqual(400, status)
        self.assertEqual("invalid_bars", body["error"]["code"])

    def test_missing_symbol_is_404(self) -> None:
        status, body = self._call("symbol=600999")
        self.assertEqual(404, status)
        self.assertEqual("not_found", body["error"]["code"])


if __name__ == "__main__":
    unittest.main()
