import unittest


class ConceptTemperatureTests(unittest.TestCase):
    def test_parse_tongdaxin_mapping_uses_gb18030_and_deduplicates_members(self):
        from app.concept_temperature import parse_tdx_concept_mapping

        rows = parse_tdx_concept_mapping(
            "880001\t人工智能\t000001\t平安银行\n"
            "880001\t人工智能\t000001\t平安银行\n"
            "880002\t机器人概念\t600001\t邯郸钢铁\n"
        )
        self.assertEqual(
            [
                {"concept_code": "880001", "concept_name": "人工智能", "symbol": "000001", "stock_name": "平安银行"},
                {"concept_code": "880002", "concept_name": "机器人概念", "symbol": "600001", "stock_name": "邯郸钢铁"},
            ],
            rows,
        )

    def test_temperature_requires_broad_strength_for_level_five(self):
        import pandas as pd
        from app.concept_temperature import build_temperature_rows

        dates = pd.date_range("2026-01-01", periods=31, freq="B")
        def bars(start, end, volume=100):
            close = list(pd.Series(range(31), index=dates) * 0 + start)
            close[-1] = end
            return pd.DataFrame({"close": close, "volume": [volume] * 31}, index=dates)

        mapping = [
            {"concept_code": "1", "concept_name": "广泛上涨", "symbol": "000001", "stock_name": "甲"},
            {"concept_code": "1", "concept_name": "广泛上涨", "symbol": "000002", "stock_name": "乙"},
            {"concept_code": "2", "concept_name": "单股暴涨", "symbol": "000003", "stock_name": "丙"},
            {"concept_code": "2", "concept_name": "单股暴涨", "symbol": "000004", "stock_name": "丁"},
        ]
        frames = {
            "000001": bars(10, 13), "000002": bars(10, 12),
            "000003": bars(10, 16), "000004": bars(10, 9),
        }
        rows, members = build_temperature_rows(mapping, frames, window=20, min_members=2)
        broad = next(row for row in rows if row["concept_name"] == "广泛上涨")
        narrow = next(row for row in rows if row["concept_name"] == "单股暴涨")
        self.assertGreater(broad["breadth_pct"], narrow["breadth_pct"])
        self.assertGreater(broad["heat_score"], narrow["heat_score"])
        self.assertLessEqual(narrow["temperature"], 3)
        self.assertEqual(["000001", "000002"], [row["symbol"] for row in members["1"]])

    def test_insufficient_members_are_not_labelled_cold(self):
        import pandas as pd
        from app.concept_temperature import build_temperature_rows

        dates = pd.date_range("2026-01-01", periods=31, freq="B")
        frame = pd.DataFrame({"close": [10] * 30 + [12], "volume": [100] * 31}, index=dates)
        rows, _ = build_temperature_rows(
            [{"concept_code": "1", "concept_name": "数据不足", "symbol": "000001", "stock_name": "甲"}],
            {"000001": frame}, window=20, min_members=2,
        )
        self.assertEqual("数据不足", rows[0]["temperature_label"])
        self.assertIsNone(rows[0]["temperature"])


if __name__ == "__main__":
    unittest.main()
