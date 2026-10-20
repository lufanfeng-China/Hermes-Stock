import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import handler as app_handler


class DataUpdatePlanTests(unittest.TestCase):
    def test_plan_discloses_peer_snapshot_freshness_coverage_and_published_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            final_dir = Path(directory)
            (final_dir / "financial_snapshot_2026-10-17.json").write_text(json.dumps({"report_date": "2026-09-30"}), encoding="utf-8")
            (final_dir / "dataset_industry_valuation_current.json").write_text("[]", encoding="utf-8")
            (final_dir / "dataset_industry_metric_peers_current.json").write_text(json.dumps({
                "built_at": "2026-10-17T08:30:00Z",
                "partitions": {"行业甲": "partition-a.json", "行业乙": "partition-b.json"},
                "stock_to_industry": {
                    "sh:600000": "行业甲",
                    "sz:000001": "行业乙",
                    "sz:300001": "行业乙",
                },
            }), encoding="utf-8")
            request = Mock()
            with (
                patch.object(app_handler, "DERIVED_FINAL_DIR", final_dir),
                patch.object(app_handler, "_data_update_job_snapshot", return_value={
                    "task_states": {"build_industry_metric_snapshot": {"status": "failed", "error": "peer build failed"}},
                }),
                patch.object(app_handler, "_latest_trading_day_for_refresh", return_value=None),
            ):
                app_handler.StockDashboardHandler.handle_data_update_plan(request)

        status, payload = request.respond_json.call_args.args
        self.assertEqual(app_handler.HTTPStatus.OK, status)
        self.assertIn("build_industry_metric_snapshot", [task["id"] for task in payload["tasks"]])
        peer_snapshot = payload["current_status"]["industry_metric_snapshot"]
        self.assertEqual("2026-10-17T08:30:00Z", peer_snapshot["updated_at"])
        self.assertEqual(2, peer_snapshot["industry_count"])
        self.assertEqual(3, peer_snapshot["member_count"])
        self.assertEqual({"industries": 2, "members": 3}, peer_snapshot["coverage"])
        self.assertEqual("peer build failed", peer_snapshot["error"])
        self.assertTrue(payload["job"]["can_retry_failed"])

    def test_data_update_page_renders_peer_snapshot_freshness_and_retry(self) -> None:
        page = (Path(__file__).parents[1] / "web" / "data-update.html").read_text(encoding="utf-8")

        self.assertIn('id="im-date"', page)
        self.assertIn('id="im-detail"', page)
        self.assertIn('id="im-error"', page)
        self.assertIn("status.industry_metric_snapshot", page)
        button_renderer = page[page.index("function renderButtons"):]
        self.assertLess(button_renderer.index("job.can_retry_failed"), button_renderer.index("job.status === 'succeeded'"))

    def test_retry_failed_commands_include_peer_snapshot_builder(self) -> None:
        from app.pipeline.commands import _data_update_commands

        commands = dict(_data_update_commands(trading_day=None, retry_failed=True))

        self.assertIn("build_industry_metric_snapshot", commands)
        self.assertEqual(
            "/home/lufanfeng/Project-Hermes-Stock/scripts/build_industry_metric_snapshot.py",
            commands["build_industry_metric_snapshot"][1],
        )

    def test_default_pipeline_rebuilds_qfq_daily_before_filter_market_metrics(self) -> None:
        from app.pipeline.commands import _data_update_commands

        ids = [task_id for task_id, _ in _data_update_commands(trading_day=None)]
        self.assertLess(ids.index("build_stock_filter_qfq_daily"), ids.index("build_stock_filter_market_snapshot"))

    def test_default_pipeline_and_plan_exclude_retired_sina_financial_fetch(self) -> None:
        from app.pipeline.commands import _data_update_commands

        commands = dict(_data_update_commands(trading_day=None))
        self.assertNotIn("fetch_financial_online", commands)

        request = Mock()
        with patch.object(app_handler, "_latest_trading_day_for_refresh", return_value=None):
            app_handler.StockDashboardHandler.handle_data_update_plan(request)
        _, payload = request.respond_json.call_args.args
        self.assertNotIn("fetch_financial_online", [task["id"] for task in payload["tasks"]])


if __name__ == "__main__":
    unittest.main()
