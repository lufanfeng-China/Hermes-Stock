"""Regression contract for retired dashboard features."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class RetiredFeatureContractTests(unittest.TestCase):
    def test_retired_feature_assets_are_not_shipped(self) -> None:
        retired_assets = (
            "rps-pool.html",
            "rps-pool.js",
            "stock-screener.html",
            "stock-screener-v2.html",
            "stock-screener-v2.css",
            "stock-screener.js",
            "macd-extreme-gc.html",
            "macd-extreme-gc.js",
            "macd-extreme-gc-utils.js",
            "macd-extreme-gc-trend-utils.js",
            "realtime-screener.html",
            "realtime-screener.js",
        )
        for asset in retired_assets:
            self.assertFalse((WEB / asset).exists(), asset)

    def test_navigation_and_server_do_not_expose_retired_features(self) -> None:
        navigation = (WEB / "nav.js").read_text(encoding="utf-8")
        handler = (ROOT / "app" / "handler.py").read_text(encoding="utf-8")
        for token in (
            "rps-pool",
            "stock-screener",
            "macd-extreme-gc",
            "极值金叉",
            "realtime-screener",
        ):
            self.assertNotIn(token, navigation, token)
        for token in (
            'parsed.path == "/api/stock-screener"',
            'parsed.path == "/api/macd-extreme-gc"',
            'parsed.path == "/api/realtime-screener"',
            "handle_stock_screener",
            "handle_macd_gc",
            "handle_realtime_screener",
            "from app.search.macd_gc import",
        ):
            self.assertNotIn(token, handler, token)

    def test_lifecycle_13_state_pipeline_is_retired(self) -> None:
        """13 状态生命周期模型已被 A/B/C/D 取代：模块、脚本、接口都不许再上线。

        退役原因：B2 在区间上半叫「探底回升」、B3 在 MA60 下行叫「回踩确认」，
        且 1 日段占比 30%+；替换为四阶段打分后这些口径失效。
        """
        retired_files = (
            "app/stage_classify_series.py",
            "app/stage_history_store.py",
            "scripts/build_stage_history.py",
            "scripts/report_stage_history_stats.py",
            "scripts/spotcheck_stage_samples.py",
            "scripts/export_stock_stage_timeline.py",
            "scripts/check_stage_series_parity.py",
        )
        for relative in retired_files:
            self.assertFalse((ROOT / relative).exists(), relative)

        server = (ROOT / "app" / "handler.py").read_text(encoding="utf-8")
        for route in ('"/api/stage-classify"', '"/api/stage-history-series"'):
            self.assertNotIn(route, server, f"{route} 必须随旧模型退役")

        page = (ROOT / "web" / "stock-analysis.js").read_text(encoding="utf-8")
        self.assertNotIn("/api/stage-classify", page)
        self.assertNotIn("/api/stage-history-series", page)
        self.assertIn("/api/regime-history-series", page)

    def test_screener_strategy_builder_is_not_shipped(self) -> None:
        self.assertFalse((ROOT / "scripts" / "build_stock_screener_strategies.py").exists())

    def test_retired_financial_score_and_concept_analysis_pages_are_not_shipped(self) -> None:
        handler = (ROOT / "app" / "handler.py").read_text(encoding="utf-8")
        navigation = (WEB / "nav.js").read_text(encoding="utf-8")
        index = (WEB / "index.html").read_text(encoding="utf-8")
        for asset in ("stock-score.html", "stock-score.js", "concept-analysis.html"):
            self.assertFalse((WEB / asset).exists(), asset)
        for token in ("stock-score.html", "财务评分", "concept-analysis.html", "概念分析"):
            self.assertNotIn(token, navigation, token)
        self.assertNotIn("stock-score.html", index)
        self.assertIn('self.serve_static("stock-analysis.html")', handler)


if __name__ == "__main__":
    unittest.main()
