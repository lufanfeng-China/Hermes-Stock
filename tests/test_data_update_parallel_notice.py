"""数据更新：并行门槛不足时必须明说改为串行，不静默降级。"""
from pathlib import Path
from unittest.mock import patch

from app.pipeline import runner


def _temperature_tasks():
    return [("build_concept_temperature", ["true"]), ("build_industry_temperature", ["true"])]


def test_low_memory_fallback_is_announced_in_the_job_output():
    appended: list[str] = []
    with patch.object(runner, "_available_memory_mb", return_value=1200), \
         patch.object(runner, "_append_data_update_job_output", side_effect=appended.append), \
         patch.object(runner, "_data_update_commands", return_value=_temperature_tasks()), \
         patch.object(runner, "_run_data_update_command") as run_command:
        from types import SimpleNamespace
        run_command.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        runner.run_full_data_update()

    notice = [line for line in appended if "改为串行" in line]
    assert notice, "内存不足回退串行时没有任何提示"
    assert "1200" in notice[0] and str(runner.PARALLEL_MIN_AVAILABLE_MB) in notice[0]


def test_enough_memory_does_not_announce_a_fallback():
    appended: list[str] = []
    with patch.object(runner, "_available_memory_mb", return_value=7000), \
         patch.object(runner, "_append_data_update_job_output", side_effect=appended.append), \
         patch.object(runner, "_data_update_commands", return_value=[("only_task", ["true"])]), \
         patch.object(runner, "_run_data_update_command") as run_command:
        from types import SimpleNamespace
        run_command.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
        runner.run_full_data_update()

    assert not [line for line in appended if "改为串行" in line]
