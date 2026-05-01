import tempfile
import unittest
from pathlib import Path
from unittest import mock


class IndustryHeatmapTests(unittest.TestCase):
    def test_select_year_to_date_trading_days_filters_from_year_start_and_reverses_order(self) -> None:
        from app.industry.heatmap import select_year_to_date_trading_days

        trading_days = [
            "2025-12-31",
            "2026-01-02",
            "2026-02-05",
            "2026-04-24",
        ]

        selected = select_year_to_date_trading_days(trading_days, anchor_day="2026-04-24")

        self.assertEqual(["2026-04-24", "2026-02-05", "2026-01-02"], selected)

    def test_select_default_industries_prefers_largest_second_level_groups(self) -> None:
        from app.industry.heatmap import select_default_industries

        industry_rows = [
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sh", "symbol": "600000"},
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sh", "symbol": "600001"},
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sz", "symbol": "000001"},
            {"industry_level_2_code": "X2", "industry_level_2_name": "行业B", "market": "sh", "symbol": "600002"},
            {"industry_level_2_code": "X2", "industry_level_2_name": "行业B", "market": "sz", "symbol": "000002"},
            {"industry_level_2_code": "X3", "industry_level_2_name": "行业C", "market": "sz", "symbol": "000003"},
            {"industry_level_2_code": "X4", "industry_level_2_name": "行业D", "market": "sz", "symbol": "000004"},
            {"industry_level_2_code": "X5", "industry_level_2_name": "行业E", "market": "sz", "symbol": "000005"},
            {"industry_level_2_code": "X6", "industry_level_2_name": "行业F", "market": "sz", "symbol": "000006"},
        ]

        selected = select_default_industries(industry_rows, limit=5)

        self.assertEqual(
            ["X1", "X2", "X3", "X4", "X5"],
            [item["industry_level_2_code"] for item in selected],
        )
        self.assertEqual(3, selected[0]["member_count"])
        self.assertEqual(2, selected[1]["member_count"])

    def test_select_default_industries_returns_all_groups_when_limit_is_none(self) -> None:
        from app.industry.heatmap import select_default_industries

        industry_rows = [
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sh", "symbol": "600000"},
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sh", "symbol": "600001"},
            {"industry_level_2_code": "X2", "industry_level_2_name": "行业B", "market": "sz", "symbol": "000001"},
            {"industry_level_2_code": "X3", "industry_level_2_name": "行业C", "market": "sz", "symbol": "000002"},
        ]

        selected = select_default_industries(industry_rows, limit=None)

        self.assertEqual(["X1", "X2", "X3"], [item["industry_level_2_code"] for item in selected])

    def test_heatmap_cache_path_uses_all_for_unlimited_limit(self) -> None:
        from app.industry.heatmap import build_heatmap_cache_path

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = build_heatmap_cache_path(
                limit=None,
                lookback_sessions=40,
                cache_dir=Path(tmpdir),
                cache_day="2026-04-27",
                dataset_signature="sig123",
            )

        self.assertEqual("industry_heatmap_2026-04-27_limit-all_lookback-40_sig123.json", cache_path.name)

    def test_heatmap_cache_round_trip_reads_written_payload(self) -> None:
        from app.industry.heatmap import load_cached_heatmap_payload, write_cached_heatmap_payload

        payload = {
            "ok": True,
            "selected_industries": [{"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "member_count": 2}],
            "trading_days": ["2026-04-27"],
            "rows": [],
            "meta": {"description": "cached"},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "heatmap.json"
            write_cached_heatmap_payload(cache_path, payload)
            loaded = load_cached_heatmap_payload(cache_path)

        self.assertEqual(payload, loaded)

    def test_industry_heatmap_response_refresh_cache_bypasses_cached_payload(self) -> None:
        from app.industry import heatmap

        cached_payload = {
            "ok": True,
            "selected_industries": [{"industry_level_2_code": "OLD", "industry_level_2_name": "旧行业", "member_count": 1}],
            "trading_days": ["2026-04-24"],
            "rows": [],
            "meta": {"description": "cached"},
        }
        industry_rows = [
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sh", "symbol": "600000"},
        ]
        stock_returns = {"sh:600000": {"2026-04-24": 1.5}}

        heatmap.industry_heatmap_response.cache_clear()
        try:
            with (
                mock.patch.object(heatmap, "build_heatmap_cache_path", return_value=Path("/tmp/industry_heatmap_cache.json")),
                mock.patch.object(heatmap, "load_cached_heatmap_payload", return_value=cached_payload),
                mock.patch.object(heatmap, "load_industry_rows", return_value=industry_rows),
                mock.patch.object(heatmap, "_fetch_stock_returns", return_value=(["2026-04-24"], stock_returns)),
                mock.patch.object(heatmap, "write_cached_heatmap_payload") as write_cache,
            ):
                payload = heatmap.industry_heatmap_response(limit=1, lookback_sessions=40, refresh_cache=True)
        finally:
            heatmap.industry_heatmap_response.cache_clear()

        self.assertEqual("行业A", payload["selected_industries"][0]["industry_level_2_name"])
        self.assertEqual("refresh_miss", payload["meta"]["cache"]["status"])
        write_cache.assert_called_once()

    def test_build_heatmap_rows_aggregates_equal_weight_daily_returns(self) -> None:
        from app.industry.heatmap import build_heatmap_rows

        selected_industries = [
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "member_count": 2},
            {"industry_level_2_code": "X2", "industry_level_2_name": "行业B", "member_count": 1},
        ]
        industry_rows = [
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sh", "symbol": "600000"},
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sz", "symbol": "000001"},
            {"industry_level_2_code": "X2", "industry_level_2_name": "行业B", "market": "sz", "symbol": "000002"},
        ]
        stock_returns = {
            "sh:600000": {"2026-03-03": 1.0, "2026-03-04": 3.0},
            "sz:000001": {"2026-03-03": 3.0, "2026-03-04": 5.0},
            "sz:000002": {"2026-03-03": -2.0, "2026-03-04": 0.0},
        }
        trading_days = ["2026-03-03", "2026-03-04"]

        rows = build_heatmap_rows(
            selected_industries=selected_industries,
            industry_rows=industry_rows,
            stock_returns=stock_returns,
            trading_days=trading_days,
        )

        self.assertEqual(2, len(rows))
        self.assertEqual("X1", rows[0]["industry_level_2_code"])
        self.assertEqual([2.0, 4.0], [cell["pct_change"] for cell in rows[0]["cells"]])
        self.assertEqual([2, 2], [cell["stock_count"] for cell in rows[0]["cells"]])
        self.assertEqual("X2", rows[1]["industry_level_2_code"])
        self.assertEqual([-2.0, 0.0], [cell["pct_change"] for cell in rows[1]["cells"]])

    def test_build_heatmap_rows_aggregates_daily_volume(self) -> None:
        from app.industry.heatmap import build_heatmap_rows

        selected_industries = [
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "member_count": 2},
        ]
        industry_rows = [
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sh", "symbol": "600000"},
            {"industry_level_2_code": "X1", "industry_level_2_name": "行业A", "market": "sz", "symbol": "000001"},
        ]
        stock_returns = {
            "sh:600000": {"2026-03-03": 1.0, "2026-03-04": 3.0},
            "sz:000001": {"2026-03-03": 3.0, "2026-03-04": 5.0},
        }
        stock_volumes = {
            "sh:600000": {"2026-03-03": 1000.0, "2026-03-04": 1200.0},
            "sz:000001": {"2026-03-03": 4000.0, "2026-03-04": 3500.0},
        }
        trading_days = ["2026-03-03", "2026-03-04"]

        rows = build_heatmap_rows(
            selected_industries=selected_industries,
            industry_rows=industry_rows,
            stock_returns=stock_returns,
            stock_volumes=stock_volumes,
            trading_days=trading_days,
        )

        self.assertEqual([5000.0, 4700.0], [cell["daily_volume"] for cell in rows[0]["cells"]])


if __name__ == "__main__":
    unittest.main()
