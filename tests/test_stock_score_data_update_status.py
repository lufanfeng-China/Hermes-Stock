import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StockScoreDataUpdateStatusContractTests(unittest.TestCase):
    def test_dashboard_script_registers_data_update_status_route_and_handler(self) -> None:
        script = (PROJECT_ROOT / 'scripts' / 'serve_stock_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('if parsed.path == "/api/data-update-status":', script)
        self.assertIn('self.handle_data_update_status(parsed.query)', script)
        self.assertIn('def handle_data_update_status(self, query: str) -> None:', script)

    def test_dashboard_script_registers_data_update_run_post_route_and_handler(self) -> None:
        script = (PROJECT_ROOT / 'scripts' / 'serve_stock_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('def do_POST(self) -> None:', script)
        self.assertIn('if parsed.path == "/api/data-update-run":', script)
        self.assertIn('self.handle_data_update_run()', script)
        self.assertIn('def handle_data_update_run(self) -> None:', script)
        self.assertIn('run_full_data_update', script)
        self.assertIn('_is_allowed_local_origin', script)
        self.assertIn("self.headers.get('Referer')", script)
        self.assertIn('forbidden_origin', script)
        self.assertIn('scripts/update_financial_ts.py', script)
        self.assertIn('scripts/build_financial_snapshot_from_warehouse.py', script)
        self.assertIn('scripts/build_industry_relative_valuation_snapshot.py', script)
        self.assertIn('if parsed.path == "/api/data-update-retry":', script)
        self.assertIn('self.handle_data_update_retry()', script)
        self.assertIn('data_update_job', script)

    def test_dashboard_script_uses_stock_score_page_as_root_homepage(self) -> None:
        script = (PROJECT_ROOT / 'scripts' / 'serve_stock_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('if parsed.path == "/":', script)
        self.assertIn('self.serve_static("stock-score.html")', script)

    def test_dashboard_script_exposes_financial_snapshot_and_industry_valuation_dates(self) -> None:
        script = (PROJECT_ROOT / 'scripts' / 'serve_stock_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('financial_snapshot', script)
        self.assertIn('industry_valuation', script)
        self.assertIn('updated_at', script)
        self.assertIn('report_date', script)
        self.assertIn('latest_updated_at', script)
        self.assertIn('member_valuation_row_count', script)
        self.assertIn('member_valuation_industry_count', script)
        self.assertIn('complete_member_valuation_industry_count', script)

    def test_data_update_failure_message_does_not_embed_full_stdout_progress_log(self) -> None:
        import scripts.serve_stock_dashboard as server

        long_progress_log = "\n".join(
            ["开始构建行业相对估值快照（含同业估值表 member_valuation_rows），共 127 个二级行业"]
            + [f"[{index}/127] 行业{index} 完成：member_valuation_rows=10，percentile_samples=20" for index in range(1, 40)]
        )
        failed_result = SimpleNamespace(returncode=-15, stdout=long_progress_log, stderr="")
        ok_result = SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with (
            mock.patch.object(server, "_latest_trading_day_for_refresh", return_value=None),
            mock.patch.object(server.subprocess, "run", side_effect=[ok_result, ok_result, failed_result]),
        ):
            with self.assertRaises(server.DataUpdateStepError) as ctx:
                server.run_full_data_update()

        message = str(ctx.exception)
        self.assertIn("build_industry_relative_valuation_snapshot", message)
        self.assertIn("exit code -15", message)
        self.assertLess(len(message), 180)
        self.assertNotIn("[1/127]", message)
        self.assertNotIn("[39/127]", message)
        self.assertIn("[39/127]", ctx.exception.stdout_tail)
        self.assertLessEqual(len(ctx.exception.stdout_tail.splitlines()), 8)

    def test_data_update_timeout_message_is_concise(self) -> None:
        import scripts.serve_stock_dashboard as server

        timeout_exc = subprocess.TimeoutExpired(cmd=["mock"], timeout=1800)
        ok_result = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        with (
            mock.patch.object(server, "_latest_trading_day_for_refresh", return_value=None),
            mock.patch.object(server.subprocess, "run", side_effect=[ok_result, ok_result, timeout_exc]),
        ):
            with self.assertRaises(server.DataUpdateStepError) as ctx:
                server.run_full_data_update()

        self.assertIn("build_industry_relative_valuation_snapshot", str(ctx.exception))
        self.assertIn("超时", str(ctx.exception))
        self.assertLess(len(str(ctx.exception)), 180)

    def test_parse_data_update_progress_line_reports_current_industry(self) -> None:
        import scripts.serve_stock_dashboard as server

        progress = server.parse_data_update_progress_line("[24/127] 农用化工 开始构建...")

        self.assertEqual(24, progress["progress_index"])
        self.assertEqual(127, progress["progress_total"])
        self.assertEqual("农用化工", progress["current_industry"])
        self.assertEqual("当前进度：[24/127] 农用化工 正在构建...", progress["current_progress_text"])

    def test_retry_failed_job_command_reuses_existing_complete_industry_snapshots(self) -> None:
        import scripts.serve_stock_dashboard as server

        commands = server._data_update_commands(trading_day=None, retry_failed=True)

        self.assertEqual(["build_industry_relative_valuation_snapshot"], [name for name, _ in commands])
        self.assertIn("--reuse-existing-complete", commands[0][1])
