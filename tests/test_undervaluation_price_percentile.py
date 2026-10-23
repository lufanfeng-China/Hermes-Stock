import unittest
from unittest.mock import patch


class PricePercentileEvidenceTests(unittest.TestCase):
    def test_five_year_coverage_is_labeled_as_five_year_percentile(self):
        from app.undervaluation.price_evidence import summarize_price_percentile

        result = summarize_price_percentile({
            "price_percentile_5y": 55.6,
            "price_band_5y": "中",
            "trading_days": 1211,
            "window_start": "2021-10-22",
            "window_end": "2026-10-22",
            "history_years": 5.0,
            "history_scope": "five_year",
            "price_basis": "tdx_export_qfq",
        })

        self.assertEqual(55.6, result["percentile"])
        self.assertEqual("五年分位", result["label"])
        self.assertEqual("five_year", result["scope"])
        self.assertEqual("tdx_export_qfq", result["basis"])

    def test_shorter_listing_history_is_labeled_as_available_history_percentile(self):
        from app.undervaluation.price_evidence import summarize_price_percentile

        result = summarize_price_percentile({
            "price_percentile_5y": 21.4,
            "price_band_5y": "低",
            "trading_days": 483,
            "window_start": "2024-11-01",
            "window_end": "2026-10-22",
            "history_years": 1.97,
            "history_scope": "available_history",
            "price_basis": "tdx_export_qfq",
        })

        self.assertEqual(21.4, result["percentile"])
        self.assertEqual("历史分位（2.0年）", result["label"])
        self.assertEqual("available_history", result["scope"])
        self.assertEqual(1.97, result["history_years"])

    def test_missing_price_evidence_remains_explicitly_unavailable(self):
        from app.undervaluation.price_evidence import summarize_price_percentile

        self.assertEqual(
            {"percentile": None, "label": "—", "scope": "unavailable", "history_years": None, "basis": None},
            summarize_price_percentile(None),
        )

    def test_all_market_list_exposes_price_percentile_and_history_label(self):
        from app.undervaluation import service

        snapshot = {
            "built_at": "2026-10-22T00:00:00+00:00",
            "stocks": [{
                "market": "sz", "symbol": "301283", "stock_name": "样本股",
                "industry_level_2_name": "化学制品",
                "quality": {"annual_score": 96, "status": "QUALITY_ELIGIBLE"},
                "margin": {"status": "HAS_MARGIN"},
                "quadrant": {"quadrant": "QUALITY_ELIGIBLE_HAS_MARGIN"},
                "industry": {}, "own_history": {}, "quarterly_momentum": {},
            }],
        }
        price_records = {
            "301283": {
                "price_percentile_5y": 21.4,
                "history_scope": "available_history",
                "history_years": 1.97,
                "price_basis": "tdx_export_qfq",
            }
        }
        with patch.object(service, "_current_diagnosis_snapshot", return_value=snapshot), patch.object(
            service, "_load_price_percentile_records", return_value=price_records
        ):
            row = service.load_current_diagnosis_list()["rows"][0]

        self.assertEqual(21.4, row["price_percentile"])
        self.assertEqual("历史分位（2.0年）", row["price_percentile_label"])
        self.assertEqual("available_history", row["price_percentile_scope"])
        self.assertEqual("tdx_export_qfq", row["price_percentile_basis"])

    def test_good_stock_list_renders_auditable_price_percentile_column(self):
        from pathlib import Path

        js = (Path(__file__).resolve().parent.parent / "web" / "good-stock-undervaluation.js").read_text(encoding="utf-8")
        self.assertIn("股价分位", js)
        self.assertIn("r.price_percentile", js)
        self.assertIn("r.price_percentile_label", js)
