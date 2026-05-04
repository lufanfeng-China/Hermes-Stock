import unittest


class RelativeValuationPercentileTests(unittest.TestCase):
    def test_compute_empirical_percentile_uses_rank_order_instead_of_extreme_scaling(self) -> None:
        from app.relative_valuation.percentiles import compute_empirical_percentile

        values = [8.0, 12.0, 18.0, 26.0, 44.0]

        self.assertAlmostEqual(20.0, compute_empirical_percentile(8.0, values), places=6)
        self.assertAlmostEqual(60.0, compute_empirical_percentile(18.0, values), places=6)
        self.assertAlmostEqual(100.0, compute_empirical_percentile(44.0, values), places=6)

    def test_compute_empirical_percentile_handles_duplicates_stably(self) -> None:
        from app.relative_valuation.percentiles import compute_empirical_percentile

        values = [10.0, 10.0, 20.0, 30.0]

        self.assertAlmostEqual(37.5, compute_empirical_percentile(10.0, values), places=6)
        self.assertAlmostEqual(75.0, compute_empirical_percentile(20.0, values), places=6)

    def test_compute_empirical_percentile_returns_none_for_empty_input(self) -> None:
        from app.relative_valuation.percentiles import compute_empirical_percentile

        self.assertIsNone(compute_empirical_percentile(12.0, []))

    def test_compute_empirical_percentile_returns_full_rank_for_singleton(self) -> None:
        from app.relative_valuation.percentiles import compute_empirical_percentile

        self.assertEqual(100.0, compute_empirical_percentile(15.0, [15.0]))

    def test_compute_empirical_percentile_supports_value_not_present_in_sample(self) -> None:
        from app.relative_valuation.percentiles import compute_empirical_percentile

        values = [12.0, 18.0, 24.0, 36.0]

        self.assertAlmostEqual(75.0, compute_empirical_percentile(24.0, values), places=6)
        self.assertAlmostEqual(75.0, compute_empirical_percentile(20.0, values), places=6)

    def test_should_warn_non_linear_high_percentile_risk(self) -> None:
        from app.relative_valuation.percentiles import should_warn_non_linear_high_percentile_risk

        self.assertFalse(should_warn_non_linear_high_percentile_risk(None))
        self.assertFalse(should_warn_non_linear_high_percentile_risk(79.99))
        self.assertTrue(should_warn_non_linear_high_percentile_risk(80.01))
