"""Contracts for the per-symbol stage timeline endpoint.

The timeline is a read-only view over the published history parquet: ascending
bars, consecutive-day segments, and no lookahead.  The handler must answer with
structured errors instead of raising.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from app import handler as app_handler
from app import stage_history_store


def write_history(path: Path, rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(rows)
    for column in ("ma5", "ma10", "ma20", "ma60", "slope20", "slope60", "slope20_prev",
                   "bias20", "pos_high_60", "pos_low_60", "range_pos_60", "vol_ratio",
                   "high_20", "low_20", "high_60", "low_60"):
        if column not in frame:
            frame[column] = 1.0
    frame.to_parquet(path, index=False)


def day_series(symbol: str, start: str, stages: list[str], region_of: dict[str, str]) -> list[dict[str, object]]:
    days = pd.bdate_range(start, periods=len(stages))
    return [
        {"market": "sh", "symbol": symbol, "trading_day": day.strftime("%Y-%m-%d"),
         "region": region_of[stage], "stage": stage}
        for day, stage in zip(days, stages)
    ]


REGION = {"D2": "down", "B1": "base", "U2": "up", "B2": "base", "U3": "up", "T1": "top"}


class StageHistorySeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "stage_history.parquet"
        rows = day_series("600000", "2026-09-01", ["D2"] * 5 + ["B1"] * 5 + ["U2"] * 3 + ["B2"] + ["U3"] * 2, REGION)
        rows += day_series("000001", "2026-09-01", ["T1"] * 3, REGION)
        write_history(self.path, rows)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_segments_collapse_consecutive_days_and_stay_ascending(self) -> None:
        payload = stage_history_store.load_stage_series("600000", path=self.path)

        self.assertTrue(payload["ok"])
        self.assertEqual("600000", payload["symbol"])
        self.assertEqual(16, payload["bars"])
        days = [row["trading_day"] for row in payload["rows"]]
        self.assertEqual(sorted(days), days)

        self.assertEqual(
            [("D2", 5), ("B1", 5), ("U2", 3), ("B2", 1), ("U3", 2)],
            [(segment["stage"], segment["trading_days"]) for segment in payload["segments"]],
        )
        self.assertEqual("U3", payload["current"]["stage"])
        self.assertTrue(payload["current"]["is_current"])
        self.assertEqual({"down": "下跌区", "base": "底部区", "up": "上升区", "top": "顶部区"},
                         payload["labels"]["regions"])
        self.assertEqual(["B2", "D1"], payload["labels"]["event_stages"])

    def test_event_stage_segment_is_flagged(self) -> None:
        payload = stage_history_store.load_stage_series("600000", path=self.path)
        event_segments = [segment for segment in payload["segments"] if segment["is_event"]]
        self.assertEqual(["B2"], [segment["stage"] for segment in event_segments])
        self.assertEqual(1, event_segments[0]["trading_days"])

    def test_unknown_symbol_and_missing_history_raise(self) -> None:
        with self.assertRaises(KeyError):
            stage_history_store.load_stage_series("999999", path=self.path)
        with self.assertRaises(FileNotFoundError):
            stage_history_store.load_stage_series("600000", path=Path(self.tempdir.name) / "absent.parquet")

    def test_months_window_trims_older_rows(self) -> None:
        long_path = Path(self.tempdir.name) / "long_history.parquet"
        rows = day_series("600000", "2026-01-01", ["U2"] * 120, REGION)
        write_history(long_path, rows)

        full = stage_history_store.load_stage_series("600000", months=12, path=long_path)
        trimmed = stage_history_store.load_stage_series("600000", months=2, path=long_path)

        self.assertEqual(120, full["bars"])
        self.assertLess(trimmed["bars"], full["bars"])
        self.assertEqual(full["as_of"], trimmed["as_of"])
        self.assertGreater(trimmed["window_start"], full["window_start"])

    def test_handler_returns_structured_status_codes(self) -> None:
        handler = Mock()
        with patch.object(stage_history_store, "DEFAULT_HISTORY", self.path):
            app_handler.StockDashboardHandler.handle_stage_history_series(handler, "symbol=600000&months=12")
            status, payload = handler.respond_json.call_args.args
            self.assertEqual(app_handler.HTTPStatus.OK, status)
            self.assertTrue(payload["ok"])
            self.assertEqual("U3", payload["current"]["stage"])

            handler.reset_mock()
            app_handler.StockDashboardHandler.handle_stage_history_series(handler, "symbol=999999")
            status, payload = handler.respond_json.call_args.args
            self.assertEqual(app_handler.HTTPStatus.NOT_FOUND, status)
            self.assertEqual("not_found", payload["error"]["code"])

            handler.reset_mock()
            app_handler.StockDashboardHandler.handle_stage_history_series(handler, "symbol=600000&months=abc")
            status, payload = handler.respond_json.call_args.args
            self.assertEqual(app_handler.HTTPStatus.BAD_REQUEST, status)
            self.assertEqual("invalid_months", payload["error"]["code"])

            handler.reset_mock()
            app_handler.StockDashboardHandler.handle_stage_history_series(handler, "")
            status, payload = handler.respond_json.call_args.args
            self.assertEqual(app_handler.HTTPStatus.BAD_REQUEST, status)
            self.assertEqual("invalid_symbol", payload["error"]["code"])

        handler.reset_mock()
        with patch.object(stage_history_store, "DEFAULT_HISTORY", Path(self.tempdir.name) / "absent.parquet"):
            app_handler.StockDashboardHandler.handle_stage_history_series(handler, "symbol=600000")
            status, payload = handler.respond_json.call_args.args
            self.assertEqual(app_handler.HTTPStatus.SERVICE_UNAVAILABLE, status)
            self.assertEqual("stage_history_missing", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
