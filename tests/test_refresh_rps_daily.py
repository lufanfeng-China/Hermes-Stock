import importlib.util
from pathlib import Path
import unittest

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "refresh_rps_daily.py"


def load_refresh_module():
    spec = importlib.util.spec_from_file_location("refresh_rps_daily", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qfq_frame(days: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"close": list(range(1, len(days) + 1))}, index=pd.to_datetime(days))


class RefreshRpsDailyTests(unittest.TestCase):
    def test_rejects_refresh_when_qfq_does_not_cover_latest_raw_day(self) -> None:
        refresh = load_refresh_module()
        with self.assertRaisesRegex(refresh.QfqCoverageError, r"QFQ export data is stale.*2026-09-24.*2026-07-31"):
            refresh.require_qfq_covers_raw("2026-09-24", "2026-07-31")

    def test_declared_reference_calendar_must_be_fresh(self) -> None:
        refresh = load_refresh_module()
        days = pd.date_range("2025-01-01", periods=253, freq="B")
        qfq_series = {
            ("sh", "601600"): qfq_frame(days[:-1].strftime("%Y-%m-%d").tolist()),
            ("sz", "000001"): qfq_frame(days[-251:].strftime("%Y-%m-%d").tolist()),
        }
        with self.assertRaisesRegex(refresh.QfqCoverageError, r"reference QFQ calendar.*601600.*stale"):
            refresh.reference_qfq_calendar(qfq_series, "601600", days[-1].date().isoformat())

    def test_rejects_target_day_with_insufficient_eligible_qfq_universe(self) -> None:
        refresh = load_refresh_module()
        dates = pd.date_range("2025-01-01", periods=251, freq="B").strftime("%Y-%m-%d").tolist()
        series = {("sh", "601600"): qfq_frame(dates)}
        with self.assertRaisesRegex(refresh.QfqCoverageError, r"eligible universe.*at least 2"):
            refresh.compute_rps_rows(series, 1, dates)

    def test_daily_pipeline_uses_single_rps_refresh_command(self) -> None:
        from app.pipeline.commands import _data_update_commands
        commands = dict(_data_update_commands(trading_day=None))
        self.assertIn("refresh_rps_daily", commands)
        self.assertNotIn("build_rps_history", commands)
        self.assertNotIn("update_rps_current", commands)
        self.assertTrue(commands["refresh_rps_daily"][1].endswith("scripts/refresh_rps_daily.py"))


if __name__ == "__main__":
    unittest.main()
