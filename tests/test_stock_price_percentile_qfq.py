from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd


def _qfq_frame(closes: list[float], start: str = "2019-01-01") -> pd.DataFrame:
    index = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1000.0] * len(closes), "amount": [1.0e6] * len(closes)},
        index=index,
    )


class PricePercentileQfqTests(unittest.TestCase):
    """The 5-year price percentile must be QFQ-only and match the valuation card."""

    def _frame(self) -> pd.DataFrame:
        # 1500 business days ending 2026-11-17, rising then flat:
        # the raw (unadjusted) series would give a much lower percentile.
        return _qfq_frame([100.0] * 1000 + [100.0 + i for i in range(500)])

    def _compute(self, frame, published, years: int = 5):
        import app.tdx.percentile as module

        with mock.patch.object(module, "load_tdx_qfq_daily", return_value=frame), \
             mock.patch.object(module, "price_position", return_value=published):
            return module.compute_stock_price_percentile("sh", "688019", years=years)

    def _published(self, frame: pd.DataFrame, value: float = 91.8) -> dict:
        as_of = str(frame.index[-1].date())
        return {"ok": True, "price_percentile": value, "scope": "five_year",
                "price_basis": "tdx_export_qfq", "as_of_date": as_of,
                "window_start": str((frame.index[-1] - pd.DateOffset(years=5)).date()),
                "window_end": as_of, "sample_count": 1305}

    def test_reuses_published_qfq_snapshot_when_aligned(self) -> None:
        frame = self._frame()
        payload = self._compute(frame, self._published(frame))

        self.assertTrue(payload["ok"])
        self.assertEqual("tdx_export_qfq", payload["price_basis"])
        self.assertEqual("published_qfq_snapshot", payload["percentile_source"])
        self.assertEqual(91.8, payload["price_percentile"])
        self.assertEqual("five_year", payload["scope"])
        self.assertEqual(str(frame.index[-1].date()), payload["as_of_date"])

    def test_recomputes_from_qfq_export_when_snapshot_is_stale(self) -> None:
        frame = self._frame()
        published = self._published(frame)
        published["as_of_date"] = "2026-10-19"          # older published day
        payload = self._compute(frame, published)

        window = frame.loc[frame.index >= frame.index[-1] - pd.DateOffset(years=5), "close"]
        expected = round(float((window <= window.iloc[-1]).sum()) / len(window) * 100, 2)
        self.assertEqual("qfq_export_recomputed", payload["percentile_source"])
        self.assertEqual(expected, payload["price_percentile"])
        self.assertEqual("2026-10-19", payload["snapshot_as_of_date"])
        self.assertEqual(str(frame.index[-1].date()), payload["as_of_date"])

    def test_never_uses_raw_price_fields(self) -> None:
        frame = self._frame()
        payload = self._compute(frame, {"ok": False})

        # QFQ closes start at 100 and end at 599 -> latest is the window maximum.
        self.assertEqual("tdx_export_qfq", payload["price_basis"])
        self.assertEqual(100.0, payload["price_percentile"])
        self.assertEqual("极高", payload["price_band"])
        self.assertEqual(100.0, payload["price_min"])
        self.assertEqual(599.0, payload["price_max"])

    def test_missing_qfq_export_raises_instead_of_falling_back(self) -> None:
        import app.tdx.percentile as module

        with mock.patch.object(module, "load_tdx_qfq_daily", side_effect=FileNotFoundError("no export")):
            with self.assertRaises(FileNotFoundError):
                module.compute_stock_price_percentile("sh", "688019")

    def test_short_history_is_labelled_scope_since_listing(self) -> None:
        frame = _qfq_frame([10.0 + i * 0.1 for i in range(400)])   # ~1.6 years
        payload = self._compute(frame, {"ok": False})

        self.assertEqual("since_listing", payload["scope"])
        self.assertEqual(400, payload["sample_count"])

    def test_rejects_invalid_symbol_and_market(self) -> None:
        import app.tdx.percentile as module

        with self.assertRaises(ValueError):
            module.compute_stock_price_percentile("sh", "68801")
        with self.assertRaises(ValueError):
            module.compute_stock_price_percentile("hk", "688019")


if __name__ == "__main__":
    unittest.main()
