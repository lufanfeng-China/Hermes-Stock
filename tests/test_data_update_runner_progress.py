import unittest
from types import SimpleNamespace
from unittest import mock

from app.pipeline import runner
from app.pipeline.state import DATA_UPDATE_JOB_STATE, _update_data_update_job_state


class DataUpdateRunnerProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_state = dict(DATA_UPDATE_JOB_STATE)

    def tearDown(self) -> None:
        with runner.DATA_UPDATE_JOB_STATE_LOCK:
            DATA_UPDATE_JOB_STATE.clear()
            DATA_UPDATE_JOB_STATE.update(self._old_state)

    def test_quiet_step_is_published_before_it_produces_stdout(self) -> None:
        observed = []

        def run_quiet_command(step_name, command, progress_callback=None):
            observed.append(dict(DATA_UPDATE_JOB_STATE))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(runner, "_latest_trading_day_for_refresh", return_value=None),
            mock.patch.object(runner, "_data_update_commands", return_value=[("refresh_rps_daily", ["mock"])]),
            mock.patch.object(runner, "_run_data_update_command", side_effect=run_quiet_command),
            mock.patch.object(runner, "clear_runtime_data_caches"),
            mock.patch.object(runner._load_rps_history_dataset, "cache_clear"),
            mock.patch.object(runner._load_rps_trading_days, "cache_clear"),
            mock.patch.object(runner._load_stock_rps_history_dataset, "cache_clear"),
        ):
            runner.run_full_data_update(progress_callback=lambda *_: None)

        self.assertEqual(1, len(observed))
        self.assertEqual("refresh_rps_daily", observed[0]["current_step"])
        self.assertEqual("当前步骤：refresh_rps_daily 正在运行...", observed[0]["current_progress_text"])
        self.assertIsNone(observed[0]["progress_index"])
        self.assertIsNone(observed[0]["progress_total"])

    def test_peer_snapshot_failure_does_not_block_technical_tasks(self) -> None:
        calls = []

        def run_command(step_name, command, progress_callback=None):
            calls.append(step_name)
            return SimpleNamespace(returncode=1 if step_name == "build_industry_metric_snapshot" else 0, stdout="", stderr="peer build failed")

        with (
            mock.patch.object(runner, "_latest_trading_day_for_refresh", return_value=None),
            mock.patch.object(runner, "_data_update_commands", return_value=[
                ("build_industry_metric_snapshot", ["peer"]),
                ("refresh_rps_daily", ["rps"]),
                ("rebuild_macd_signals", ["macd"]),
            ]),
            mock.patch.object(runner, "_run_data_update_command", side_effect=run_command),
            mock.patch.object(runner, "clear_runtime_data_caches"),
            mock.patch.object(runner._load_rps_history_dataset, "cache_clear"),
            mock.patch.object(runner._load_rps_trading_days, "cache_clear"),
            mock.patch.object(runner._load_stock_rps_history_dataset, "cache_clear"),
        ):
            result = runner.run_full_data_update()

        self.assertEqual(calls, ["build_industry_metric_snapshot", "refresh_rps_daily", "rebuild_macd_signals"])
        self.assertFalse(result["steps"][0]["ok"])
        self.assertTrue(result["steps"][1]["ok"])
        self.assertTrue(result["steps"][2]["ok"])

    def test_industry_metric_snapshot_is_an_independent_data_update_command(self) -> None:
        from app.pipeline.commands import _data_update_commands

        commands = dict(_data_update_commands(trading_day=None))

        self.assertIn("build_industry_metric_snapshot", commands)
        self.assertEqual(
            "/home/lufanfeng/Project-Hermes-Stock/scripts/build_industry_metric_snapshot.py",
            commands["build_industry_metric_snapshot"][1],
        )
