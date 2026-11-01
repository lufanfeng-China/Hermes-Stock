"""数据更新：概念温度与行业温度并行执行（内存不足时自动回退串行）。"""
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.pipeline import runner


def _commands():
    return runner._data_update_commands("2026-10-30")


def test_two_temperature_builds_share_one_parallel_unit():
    with patch.object(runner, "_available_memory_mb", return_value=6000):
        units = runner._build_units(_commands())
    assert len(units) == 16                     # 17 个任务合成 16 个执行单元
    assert [name for name, _ in units[-1]] == ["build_concept_temperature", "build_industry_temperature"]
    # 除最后一组外都是单任务单元，顺序与命令表一致
    assert [unit[0][0] for unit in units[:-1]] == [name for name, _ in _commands()][:-2]


def test_low_memory_falls_back_to_sequential():
    with patch.object(runner, "_available_memory_mb", return_value=runner.PARALLEL_MIN_AVAILABLE_MB - 1):
        units = runner._build_units(_commands())
    assert len(units) == 17
    assert all(len(unit) == 1 for unit in units)


def test_unreadable_memory_info_means_sequential():
    with patch.object(runner, "_available_memory_mb", return_value=None):
        assert runner._can_parallelize() is False
        assert len(runner._build_units(_commands())) == 17


def _fake_run(delays, returncodes=None):
    returncodes = returncodes or {}

    def _run(step_name, command, progress_callback=None):
        time.sleep(delays.get(step_name, 0))
        return SimpleNamespace(returncode=returncodes.get(step_name, 0), stdout=f"{step_name} ok", stderr="")

    return _run


def test_group_runs_concurrently_and_records_both_steps():
    unit = [("build_concept_temperature", ["x"]), ("build_industry_temperature", ["y"])]
    calls = _fake_run({name: 1.5 for name, _ in unit})

    started = time.monotonic()
    with patch.object(runner, "_run_data_update_command", side_effect=calls):
        steps = runner._run_parallel_unit(unit)
    elapsed = time.monotonic() - started

    assert elapsed < 2.5, f"两个 1.5 秒任务耗时 {elapsed:.2f}s，说明没有并行"
    assert [step["name"] for step in steps] == [name for name, _ in unit]
    assert all(step["ok"] and step["parallel"] for step in steps)


def test_one_failure_does_not_cancel_the_sibling():
    unit = [("build_concept_temperature", ["x"]), ("build_industry_temperature", ["y"])]
    calls = _fake_run({}, returncodes={"build_industry_temperature": 1})

    with patch.object(runner, "_run_data_update_command", side_effect=calls):
        steps = runner._run_parallel_unit(unit)

    by_name = {step["name"]: step for step in steps}
    assert by_name["build_concept_temperature"]["ok"] is True
    assert by_name["build_industry_temperature"]["ok"] is False
    assert by_name["build_industry_temperature"]["returncode"] == 1


def test_exception_in_one_task_is_recorded_as_failure():
    import subprocess

    unit = [("build_concept_temperature", ["x"]), ("build_industry_temperature", ["y"])]

    def _run(step_name, command, progress_callback=None):
        if step_name == "build_industry_temperature":
            raise subprocess.TimeoutExpired(cmd=command, timeout=3600)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with patch.object(runner, "_run_data_update_command", side_effect=_run):
        steps = runner._run_parallel_unit(unit)

    by_name = {step["name"]: step for step in steps}
    assert by_name["build_concept_temperature"]["ok"] is True
    assert by_name["build_industry_temperature"]["ok"] is False
    assert "timed out" in by_name["build_industry_temperature"]["stderr_tail"]
