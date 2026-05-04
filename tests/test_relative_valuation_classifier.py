import unittest


class RelativeValuationClassifierTests(unittest.TestCase):
    def test_classify_normal_earning_stock_as_a_class(self) -> None:
        from app.relative_valuation.classifier import classify_relative_valuation_stock
        from app.relative_valuation.labels import Classification

        result = classify_relative_valuation_stock(
            ttm_net_profit=12_000_000.0,
            pe_ttm=24.0,
            dynamic_pe_invalid_threshold=60.0,
            ttm_revenue=350_000_000.0,
            revenue_yoy=0.12,
            gross_margin=0.28,
            book_value_per_share=5.4,
            listed_days=800,
        )

        self.assertEqual(Classification.A_NORMAL_EARNING, result.classification)
        self.assertIsNone(result.sub_classification)
        self.assertFalse(result.is_new_listing)

    def test_classify_profitable_but_distorted_stock_as_b_class(self) -> None:
        from app.relative_valuation.classifier import classify_relative_valuation_stock
        from app.relative_valuation.labels import Classification

        result = classify_relative_valuation_stock(
            ttm_net_profit=800_000.0,
            pe_ttm=188.0,
            dynamic_pe_invalid_threshold=50.0,
            ttm_revenue=420_000_000.0,
            revenue_yoy=0.08,
            gross_margin=0.19,
            book_value_per_share=3.2,
            listed_days=1600,
        )

        self.assertEqual(Classification.B_THIN_PROFIT_DISTORTED, result.classification)
        self.assertIsNone(result.sub_classification)

    def test_classify_loss_stock_into_four_subclasses(self) -> None:
        from app.relative_valuation.classifier import classify_relative_valuation_stock
        from app.relative_valuation.labels import Classification, LossSubClassification

        liquidation = classify_relative_valuation_stock(
            ttm_net_profit=-5_000_000.0,
            pe_ttm=None,
            dynamic_pe_invalid_threshold=50.0,
            ttm_revenue=120_000_000.0,
            revenue_yoy=0.05,
            gross_margin=0.18,
            book_value_per_share=-0.2,
            listed_days=1200,
        )
        self.assertEqual(Classification.C_LOSS, liquidation.classification)
        self.assertEqual(LossSubClassification.C4_LIQUIDATION_RISK, liquidation.sub_classification)

        no_revenue = classify_relative_valuation_stock(
            ttm_net_profit=-2_000_000.0,
            pe_ttm=None,
            dynamic_pe_invalid_threshold=50.0,
            ttm_revenue=850_000.0,
            revenue_yoy=0.0,
            gross_margin=0.0,
            book_value_per_share=1.1,
            listed_days=1200,
        )
        self.assertEqual(LossSubClassification.C3_NO_REVENUE_CONCEPT, no_revenue.sub_classification)

        growth_loss = classify_relative_valuation_stock(
            ttm_net_profit=-9_000_000.0,
            pe_ttm=None,
            dynamic_pe_invalid_threshold=50.0,
            ttm_revenue=260_000_000.0,
            revenue_yoy=0.36,
            gross_margin=0.24,
            book_value_per_share=2.8,
            listed_days=1200,
        )
        self.assertEqual(LossSubClassification.C2_GROWTH_LOSS, growth_loss.sub_classification)

        growth_loss_yi = classify_relative_valuation_stock(
            ttm_net_profit=-9.0,
            pe_ttm=None,
            dynamic_pe_invalid_threshold=50.0,
            ttm_revenue=260.0,
            revenue_yoy=0.36,
            gross_margin=0.24,
            book_value_per_share=2.8,
            listed_days=1200,
        )
        self.assertEqual(LossSubClassification.C2_GROWTH_LOSS, growth_loss_yi.sub_classification)

        revenue_loss = classify_relative_valuation_stock(
            ttm_net_profit=-9_000_000.0,
            pe_ttm=None,
            dynamic_pe_invalid_threshold=50.0,
            ttm_revenue=260_000_000.0,
            revenue_yoy=0.06,
            gross_margin=0.09,
            book_value_per_share=2.8,
            listed_days=1200,
        )
        self.assertEqual(LossSubClassification.C1_REVENUE_LOSS, revenue_loss.sub_classification)

    def test_mark_new_listing_and_skip_percentile_eligibility(self) -> None:
        from app.relative_valuation.classifier import classify_relative_valuation_stock
        from app.relative_valuation.labels import Classification

        result = classify_relative_valuation_stock(
            ttm_net_profit=6_000_000.0,
            pe_ttm=22.0,
            dynamic_pe_invalid_threshold=55.0,
            ttm_revenue=180_000_000.0,
            revenue_yoy=0.18,
            gross_margin=0.22,
            book_value_per_share=3.6,
            listed_days=45,
        )

        self.assertTrue(result.is_new_listing)
        self.assertFalse(result.eligible_for_percentile)
        self.assertEqual(Classification.A_NORMAL_EARNING, result.classification)

    def test_labels_map_percentile_and_temperature_bands(self) -> None:
        from app.relative_valuation.labels import classify_percentile_band, classify_temperature_label

        self.assertEqual("低估区间", classify_percentile_band(10.0))
        self.assertEqual("合理偏低", classify_percentile_band(30.0))
        self.assertEqual("合理", classify_percentile_band(50.0))
        self.assertEqual("合理偏高", classify_percentile_band(70.0))
        self.assertEqual("高估区间", classify_percentile_band(90.0))

        self.assertEqual("行业偏冷", classify_temperature_label(20.0))
        self.assertEqual("行业温和", classify_temperature_label(50.0))
        self.assertEqual("行业偏热", classify_temperature_label(75.0))
        self.assertEqual("行业过热", classify_temperature_label(85.0))
