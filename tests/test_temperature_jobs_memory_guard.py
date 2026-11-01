"""窗口并发的内存闸门 + runner 并行时的并发上限。"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.pipeline import runner

ROOT = Path(__file__).resolve().parents[1]


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_concept_temperature", ROOT / "scripts" / "build_concept_temperature.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_jobs_follow_available_memory_not_just_cpu_count():
    builder = _builder()
    with patch.object(builder, "_available_memory_mb", return_value=6000):
        assert builder.default_jobs(5, frames_mb=600) >= 2
    with patch.object(builder, "_available_memory_mb", return_value=2200):
        assert builder.default_jobs(5, frames_mb=900) == 1      # 放不下两个 1.15GB 的子进程
    with patch.object(builder, "_available_memory_mb", return_value=None):
        assert builder.default_jobs(5, frames_mb=100) == 1      # 读不到内存就串行


def test_jobs_never_exceed_cpu_or_window_caps():
    builder = _builder()
    with patch.object(builder, "_available_memory_mb", return_value=64_000):
        assert builder.default_jobs(5, frames_mb=100) <= 5
        assert builder.default_jobs(2, frames_mb=100) == 2


def test_two_parallel_temperature_builds_are_limited_to_two_window_processes():
    unit = [("build_concept_temperature", ["python", "build_concept_temperature.py"]),
            ("build_industry_temperature", ["python", "build_concept_temperature.py", "--scope", "industry"])]
    captured = []

    def _fake(step_name, command, progress_callback=None):
        captured.append((step_name, command))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(runner, "_run_data_update_command", side_effect=_fake):
        runner._run_parallel_unit(unit)

    for step_name, command in captured:
        assert step_name in runner.TEMPERATURE_TASKS
        assert command[-2:] == ["--jobs", str(runner.TEMPERATURE_JOBS_WHEN_PARALLEL)]


def test_commands_that_already_carry_jobs_are_not_double_flagged():
    unit = [("build_concept_temperature", ["python", "x.py", "--jobs", "3"])]
    seen = []

    def _fake(step_name, command, progress_callback=None):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(runner, "_run_data_update_command", side_effect=_fake):
        runner._run_parallel_unit(unit)
    assert seen[0].count("--jobs") == 1


def test_non_temperature_tasks_are_untouched():
    unit = [("refresh_rps_daily", ["python", "refresh.py"])]
    seen = []

    def _fake(step_name, command, progress_callback=None):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(runner, "_run_data_update_command", side_effect=_fake):
        runner._run_parallel_unit(unit)
    assert seen[0] == ["python", "refresh.py"]
