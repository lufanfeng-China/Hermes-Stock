import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / 'app'

# The HTTP contract lives in app/handler.py (routes + handler methods); the data
# update command table lives in app/pipeline/commands.py; execution and error
# reporting live in app/pipeline/runner.py and app/pipeline/state.py.
HANDLER_SOURCE = APP_DIR / 'handler.py'
COMMANDS_SOURCE = APP_DIR / 'pipeline' / 'commands.py'


def _source(path: Path) -> str:
    return path.read_text(encoding='utf-8')


class StockScoreDataUpdateStatusContractTests(unittest.TestCase):
    def test_dashboard_script_registers_data_update_status_route_and_handler(self) -> None:
        """Route/handler now live in app/handler.py, not the 36-line launcher."""
        handler = _source(HANDLER_SOURCE)
        self.assertIn('if parsed.path == "/api/data-update-status":', handler)
        self.assertIn('self.handle_data_update_status(parsed.query)', handler)
        self.assertIn('def handle_data_update_status(self, query: str) -> None:', handler)
        self.assertIn('load_data_update_status()', handler)

    def test_dashboard_script_registers_data_update_run_post_route_and_handler(self) -> None:
        """POST routes are in app/handler.py, shell commands in app/pipeline/commands.py."""
        handler = _source(HANDLER_SOURCE)
        commands = _source(COMMANDS_SOURCE)

        self.assertIn('def do_POST(self) -> None:', handler)
        self.assertIn('if parsed.path == "/api/data-update-run":', handler)
        self.assertIn('self.handle_data_update_run()', handler)
        self.assertIn('def handle_data_update_run(self) -> None:', handler)
        self.assertIn('run_full_data_update', handler)
        self.assertIn('_is_allowed_local_origin', handler)
        self.assertIn("self.headers.get('Referer')", handler)
        self.assertIn('forbidden_origin', handler)
        self.assertIn('scripts/update_financial_ts.py', commands)
        self.assertIn('scripts/build_financial_snapshot_from_warehouse.py', commands)
        self.assertIn('scripts/build_industry_relative_valuation_snapshot.py', commands)
        self.assertIn('if parsed.path == "/api/data-update-retry":', handler)
        self.assertIn('self.handle_data_update_retry()', handler)
        self.assertIn('data_update_job', handler)

    def test_dashboard_script_uses_stock_analysis_page_as_root_homepage(self) -> None:
        handler = _source(HANDLER_SOURCE)
        self.assertIn('if parsed.path == "/":', handler)
        self.assertIn('self.serve_static("stock-analysis.html")', handler)

    def test_dashboard_script_exposes_financial_snapshot_and_industry_valuation_dates(self) -> None:
        handler = _source(HANDLER_SOURCE)
        self.assertIn('financial_snapshot', handler)
        self.assertIn('industry_valuation', handler)
        self.assertIn('updated_at', handler)
        self.assertIn('report_date', handler)
        self.assertIn('latest_updated_at', handler)
        self.assertIn('member_valuation_row_count', handler)
        self.assertIn('member_valuation_industry_count', handler)
        self.assertIn('complete_member_valuation_industry_count', handler)

    def test_data_update_failure_message_does_not_embed_full_stdout_progress_log(self) -> None:
        from app.pipeline import runner as pipeline_runner

        long_progress_log = "\n".join(
            ["开始构建行业相对估值快照（含同业估值表 member_valuation_rows），共 127 个二级行业"]
            + [f"[{index}/127] 行业{index} 完成：member_valuation_rows=10，percentile_samples=20" for index in range(1, 40)]
        )
        failed_result = SimpleNamespace(returncode=-15, stdout=long_progress_log, stderr="")
        ok_result = SimpleNamespace(returncode=0, stdout="ok", stderr="")

        def fake_run(command, **kwargs):
            if any('build_industry_relative_valuation_snapshot.py' in str(part) for part in command):
                return failed_result
            return ok_result

        with (
            mock.patch.object(pipeline_runner, "_latest_trading_day_for_refresh", return_value=None),
            mock.patch.object(pipeline_runner.subprocess, "run", side_effect=fake_run),
        ):
            with self.assertRaises(pipeline_runner.DataUpdateStepError) as ctx:
                pipeline_runner.run_full_data_update()

        message = str(ctx.exception)
        self.assertIn("build_industry_relative_valuation_snapshot", message)
        self.assertIn("exit code -15", message)
        self.assertLess(len(message), 180)
        self.assertNotIn("[1/127]", message)
        self.assertNotIn("[39/127]", message)
        self.assertIn("[39/127]", ctx.exception.stdout_tail)
        self.assertLessEqual(len(ctx.exception.stdout_tail.splitlines()), 8)

    def test_data_update_timeout_message_is_concise(self) -> None:
        from app.pipeline import runner as pipeline_runner

        timeout_exc = subprocess.TimeoutExpired(cmd=["mock"], timeout=1800)
        ok_result = SimpleNamespace(returncode=0, stdout="ok", stderr="")

        def fake_run(command, **kwargs):
            if any('build_industry_relative_valuation_snapshot.py' in str(part) for part in command):
                raise timeout_exc
            return ok_result

        with (
            mock.patch.object(pipeline_runner, "_latest_trading_day_for_refresh", return_value=None),
            mock.patch.object(pipeline_runner.subprocess, "run", side_effect=fake_run),
        ):
            with self.assertRaises(pipeline_runner.DataUpdateStepError) as ctx:
                pipeline_runner.run_full_data_update()

        self.assertIn("build_industry_relative_valuation_snapshot", str(ctx.exception))
        self.assertIn("超时", str(ctx.exception))
        self.assertLess(len(str(ctx.exception)), 180)

    def test_parse_data_update_progress_line_reports_current_industry(self) -> None:
        from app.pipeline import state as pipeline_state

        progress = pipeline_state.parse_data_update_progress_line("[24/127] 农用化工 开始构建...")

        self.assertEqual(24, progress["progress_index"])
        self.assertEqual(127, progress["progress_total"])
        self.assertEqual("农用化工", progress["current_industry"])
        self.assertEqual("当前进度：[24/127] 农用化工 正在构建...", progress["current_progress_text"])

    def test_retry_failed_job_command_reuses_existing_complete_industry_snapshots(self) -> None:
        from app.pipeline import commands as pipeline_commands

        commands = pipeline_commands._data_update_commands(trading_day=None, retry_failed=True)

        # The retry subset is replayed only for failed publications; every entry
        # in it is independently retryable and must not re-run downloads.
        self.assertEqual(
            [
                "build_industry_metric_snapshot",
                "build_industry_relative_valuation_snapshot",
                "build_good_stock_financial_snapshot",
                "build_good_stock_undervaluation_current",
            ],
            [name for name, _ in commands],
        )
        valuation_command = dict(commands)["build_industry_relative_valuation_snapshot"]
        self.assertIn("--reuse-existing-complete", valuation_command)
        self.assertTrue(
            valuation_command[1].endswith("scripts/build_industry_relative_valuation_snapshot.py")
        )
