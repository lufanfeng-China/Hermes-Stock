import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "web"
STYLES_CSS = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")


class RealtimeScreenerPageTests(unittest.TestCase):
    def test_realtime_screener_page_contains_scenario_editor_monitor_results_and_kline(self) -> None:
        html = (WEB_ROOT / "realtime-screener.html").read_text(encoding="utf-8")

        self.assertIn("实时选股", html)
        self.assertIn('id="realtime-scenario-select"', html)
        self.assertIn('value="tail_session"', html)
        self.assertIn("尾盘选股", html)
        self.assertIn('id="realtime-load-scenario"', html)
        self.assertIn('id="realtime-condition-form"', html)
        self.assertIn('hidden', html.split('id="realtime-condition-form"', 1)[1].split('>', 1)[0])
        self.assertIn('id="realtime-refresh-seconds"', html)
        self.assertIn('value="30"', html)
        self.assertIn('id="realtime-start-monitor"', html)
        self.assertIn('id="realtime-stop-monitor"', html)
        self.assertIn('id="realtime-status"', html)
        self.assertIn('id="realtime-results-tbody"', html)
        self.assertIn('id="realtime-match-count"', html)
        self.assertIn('src="/realtime-screener.js?v=', html)
        self.assertNotIn("<th>命中条件</th>", html)
        for header in ("行业信息", "行业内总分", "行业排名"):
            self.assertIn(f"<th>{header}</th>", html)

        for field in (
            'name="gain_min_pct"',
            'name="gain_max_pct"',
            'name="limit_up_lookback_days"',
            'name="min_volume_ratio"',
            'name="max_market_cap_yi"',
            'name="turnover_min_pct"',
            'name="turnover_max_pct"',
            'name="intraday_above_vwap"',
            'name="intraday_above_vwap_min_ratio_pct"',
            'name="intraday_vwap_max_breach_pct"',
            'name="current_above_open"',
            'name="enable_gain_pct"',
            'name="enable_limit_up_lookback_days"',
            'name="enable_min_volume_ratio"',
            'name="enable_max_market_cap_yi"',
            'name="enable_turnover_pct"',
            'name="enable_intraday_above_vwap"',
            'name="enable_current_above_open"',
        ):
            self.assertIn(field, html)

        for label in (
            "涨幅 3% - 5%",
            "20天内有过涨停",
            "量比 > 1.4",
            "市值 < 200亿",
            "换手率 5% - 10%",
            "大部分时间在均价线上方",
            "允许短暂跌破不超过 0.3%",
            "当前价高于开盘价",
        ):
            self.assertIn(label, html)

    def test_realtime_screener_kline_copies_stock_screener_chart_shell(self) -> None:
        html = (WEB_ROOT / "realtime-screener.html").read_text(encoding="utf-8")

        self.assertIn('id="realtime-kline-section" class="kline-section terminal-panel hidden"', html)
        self.assertIn('class="kline-header terminal-panel-header"', html)
        self.assertIn('class="kline-controls"', html)
        self.assertIn('id="realtime-preset-controls" class="zoom-controls"', html)
        self.assertIn('id="realtime-kline-range-label" class="kline-range-label"', html)
        self.assertIn('class="kline-chart-wrap"', html)
        self.assertIn('id="realtime-kline-svg" class="kline-svg"', html)
        for preset, label in (("20", "20D"), ("60", "60D"), ("120", "120D"), ("250", "250D"), ("-1", "ALL")):
            self.assertIn(f'data-preset="{preset}"', html)
            self.assertIn(label, html)

    def test_realtime_screener_script_uses_scenarios_monitor_api_and_kline_chart(self) -> None:
        script = (WEB_ROOT / "realtime-screener.js").read_text(encoding="utf-8")

        self.assertIn("REALTIME_SCENARIOS", script)
        self.assertIn("tail_session", script)
        self.assertIn("loadScenario", script)
        self.assertIn("collectConditionPayload", script)
        self.assertIn("startRealtimeMonitor", script)
        self.assertIn("stopRealtimeMonitor", script)
        self.assertIn("setInterval", script)
        self.assertIn("/api/realtime-screener", script)
        self.assertIn("/api/stock-kline", script)
        self.assertIn("/api/stock-rps-history", script)
        self.assertIn("KlineChart", script)
        self.assertIn("currentKlinePreset = 60", script)
        self.assertIn("limit=300", script)
        self.assertIn("data-preset", script)
        self.assertIn("loadRealtimeKline", script)
        self.assertIn("setConditionFormLocked", script)
        self.assertIn("conditionForm.hidden = false", script)
        self.assertIn("conditionForm.hidden", script)
        self.assertIn("enable_min_volume_ratio", script)
        self.assertIn("industry_level_1", script)
        self.assertIn("industry_level_2", script)
        self.assertIn("industry_total_score", script)
        self.assertIn("industry_total_rank", script)
        self.assertNotIn("row.matched_conditions", script)

    def test_navigation_links_to_realtime_screener(self) -> None:
        for filename in ("stock-score.html", "stock-screener.html", "rps-pool.html"):
            html = (WEB_ROOT / filename).read_text(encoding="utf-8")
            self.assertIn('/realtime-screener.html', html)
            self.assertIn('实时选股', html)

    def test_realtime_screener_styles_are_terminal_dashboard_aligned(self) -> None:
        self.assertIn(".realtime-screener-shell", STYLES_CSS)
        self.assertIn(".realtime-condition-grid", STYLES_CSS)
        self.assertIn(".realtime-results-wrap", STYLES_CSS)
        self.assertIn(".realtime-row", STYLES_CSS)


if __name__ == "__main__":
    unittest.main()
