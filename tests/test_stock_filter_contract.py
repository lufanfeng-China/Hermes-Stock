import unittest

from app.stock_filter import PAGE_SIZE, filter_response


class StockFilterContractTest(unittest.TestCase):
    def test_page_size_is_fixed_to_fifty(self):
        result = filter_response({"page_size": ["51"]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_filter")

    def test_invalid_range_is_rejected(self):
        result = filter_response({"rps_total_min": ["300"], "rps_total_max": ["100"]})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_filter")

    def test_contract_constant(self):
        self.assertEqual(PAGE_SIZE, 50)

    def test_annual_dimension_range_filters_full_market(self):
        result = filter_response({"annual_growth_quality_min": ["1"], "page": ["1"], "page_size": ["50"]})
        self.assertTrue(result["ok"])
        self.assertGreater(result["total_matched"], 0)
        self.assertTrue(all((row["annual_dimensions"].get("growth_quality") or 0) >= 1 for row in result["rows"]))


if __name__ == "__main__":
    unittest.main()
