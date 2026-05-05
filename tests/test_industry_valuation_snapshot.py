import unittest


class IndustryValuationSnapshotTests(unittest.TestCase):
    def test_build_industry_day_snapshot_filters_invalid_members_and_counts_exclusions(self) -> None:
        from app.relative_valuation.industry_snapshot import build_industry_day_snapshot

        base_valid_members = [
            {
                "market": "sh",
                "symbol": f"6000{i:02d}",
                "free_float_market_cap": 100.0 + i,
                "ttm_net_profit": 10.0 + i,
                "ttm_revenue": 50.0 + i,
                "book_value_per_share": 2.0,
                "listed_days": 300,
                "is_suspended": False,
            }
            for i in range(10)
        ]
        members = base_valid_members + [
            {
                "market": "sh",
                "symbol": "600900",
                "free_float_market_cap": 90.0,
                "ttm_net_profit": -2.0,
                "ttm_revenue": 40.0,
                "book_value_per_share": 1.5,
                "listed_days": 600,
                "is_suspended": False,
            },
            {
                "market": "sh",
                "symbol": "600901",
                "free_float_market_cap": 95.0,
                "ttm_net_profit": 8.0,
                "ttm_revenue": 42.0,
                "book_value_per_share": -0.3,
                "listed_days": 600,
                "is_suspended": False,
            },
            {
                "market": "sh",
                "symbol": "600902",
                "free_float_market_cap": 96.0,
                "ttm_net_profit": 9.0,
                "ttm_revenue": 45.0,
                "book_value_per_share": 1.1,
                "listed_days": 30,
                "is_suspended": False,
            },
            {
                "market": "sh",
                "symbol": "600903",
                "free_float_market_cap": 97.0,
                "ttm_net_profit": 7.0,
                "ttm_revenue": 39.0,
                "book_value_per_share": 1.4,
                "listed_days": 700,
                "is_suspended": True,
            },
        ]

        snapshot = build_industry_day_snapshot(
            trading_day="2026-04-30",
            industry_level_1_name="家电",
            industry_level_2_code="X2401",
            industry_level_2_name="白色家电",
            members=members,
            historical_weighted_pe_series=[8.0, 12.0, 16.0],
        )

        self.assertEqual(14, snapshot["total_member_count"])
        self.assertEqual(10, snapshot["valid_member_count"])
        self.assertEqual(1, snapshot["loss_count"])
        self.assertEqual(1, snapshot["invalid_book_value_count"])
        self.assertEqual(1, snapshot["new_listing_filtered_count"])
        self.assertEqual(1, snapshot["suspended_filtered_count"])
        self.assertEqual("ok", snapshot["sample_status"])

    def test_build_industry_day_snapshot_computes_weighted_pe_ps_and_dynamic_threshold(self) -> None:
        from app.relative_valuation.industry_snapshot import build_industry_day_snapshot

        members = [
            {
                "market": "sz",
                "symbol": f"0000{i:02d}",
                "free_float_market_cap": float(cap),
                "ttm_net_profit": float(profit),
                "ttm_revenue": float(revenue),
                "book_value_per_share": 3.0,
                "listed_days": 600,
                "is_suspended": False,
            }
            for i, (cap, profit, revenue) in enumerate(
                [
                    (100, 10, 50),
                    (120, 12, 60),
                    (80, 8, 40),
                    (110, 11, 55),
                    (90, 9, 45),
                    (130, 13, 65),
                    (70, 7, 35),
                    (140, 14, 70),
                    (60, 6, 30),
                    (100, 10, 50),
                ]
            )
        ]

        snapshot = build_industry_day_snapshot(
            trading_day="2026-04-30",
            industry_level_1_name="有色",
            industry_level_2_code="X1401",
            industry_level_2_name="工业金属",
            members=members,
            historical_weighted_pe_series=[8.0, 10.0, 12.0, 14.0],
        )

        self.assertAlmostEqual(10.0, snapshot["weighted_pe_ttm"], places=6)
        self.assertAlmostEqual(2.0, snapshot["weighted_ps_ttm"], places=6)
        self.assertAlmostEqual(50.0, snapshot["pe_invalid_threshold"], places=6)

    def test_build_industry_day_snapshot_prefers_total_market_cap_for_main_weighted_valuation(self) -> None:
        from app.relative_valuation.industry_snapshot import build_industry_day_snapshot

        members = [
            {
                "market": "sz",
                "symbol": f"0021{i:02d}",
                "free_float_market_cap": 30.0,
                "total_market_cap": 50.0,
                "ttm_net_profit": 5.0,
                "ttm_revenue": 25.0,
                "book_value_per_share": 3.0,
                "listed_days": 600,
                "is_suspended": False,
            }
            for i in range(10)
        ]

        snapshot = build_industry_day_snapshot(
            trading_day="2026-04-30",
            industry_level_1_name="有色",
            industry_level_2_code="X1401",
            industry_level_2_name="工业金属",
            members=members,
            historical_weighted_pe_series=[8.0, 10.0, 12.0, 14.0],
        )

        self.assertAlmostEqual(10.0, snapshot["weighted_pe_ttm"], places=6)
        self.assertAlmostEqual(2.0, snapshot["weighted_ps_ttm"], places=6)
        self.assertAlmostEqual(6.0, snapshot["free_float_weighted_pe_ttm"], places=6)
        self.assertAlmostEqual(1.2, snapshot["free_float_weighted_ps_ttm"], places=6)

    def test_build_industry_day_snapshot_marks_sample_insufficient_when_valid_count_below_threshold(self) -> None:
        from app.relative_valuation.industry_snapshot import build_industry_day_snapshot

        members = [
            {
                "market": "sz",
                "symbol": f"3000{i:02d}",
                "free_float_market_cap": 50.0 + i,
                "ttm_net_profit": 5.0 + i,
                "ttm_revenue": 20.0 + i,
                "book_value_per_share": 1.5,
                "listed_days": 500,
                "is_suspended": False,
            }
            for i in range(9)
        ]

        snapshot = build_industry_day_snapshot(
            trading_day="2026-04-30",
            industry_level_1_name="通信",
            industry_level_2_code="X7101",
            industry_level_2_name="通信设备",
            members=members,
            historical_weighted_pe_series=[15.0, 18.0],
        )

        self.assertEqual("insufficient", snapshot["sample_status"])
        self.assertIsNone(snapshot["temperature_percentile_since_2022"])
        self.assertIsNone(snapshot["temperature_label"])

    def test_build_industry_day_snapshot_computes_temperature_percentile_since_2022(self) -> None:
        from app.relative_valuation.industry_snapshot import build_industry_day_snapshot

        members = [
            {
                "market": "sh",
                "symbol": f"6880{i:02d}",
                "free_float_market_cap": float(cap),
                "ttm_net_profit": float(profit),
                "ttm_revenue": 100.0,
                "book_value_per_share": 4.0,
                "listed_days": 800,
                "is_suspended": False,
            }
            for i, (cap, profit) in enumerate(
                [(200, 10), (220, 11), (240, 12), (260, 13), (280, 14), (300, 15), (320, 16), (340, 17), (360, 18), (380, 19)]
            )
        ]

        snapshot = build_industry_day_snapshot(
            trading_day="2026-04-30",
            industry_level_1_name="电子",
            industry_level_2_code="X3401",
            industry_level_2_name="半导体",
            members=members,
            historical_weighted_pe_series=[12.0, 16.0, 24.0, 28.0],
        )

        self.assertAlmostEqual(75.0, snapshot["temperature_percentile_since_2022"], places=6)
        self.assertEqual("行业偏热", snapshot["temperature_label"])
