"""数据更新：慢任务超时放宽 + 计划页与命令表严格同序。"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_long_builders_get_a_hour_and_everything_else_keeps_thirty_minutes():
    from app.pipeline.runner import DEFAULT_TASK_TIMEOUT, LONG_TASK_TIMEOUTS, _task_timeout

    assert DEFAULT_TASK_TIMEOUT == 1800
    # 温度构建实测 17-25 分钟，30 分钟余量不足
    assert _task_timeout("build_concept_temperature") == 3600
    assert _task_timeout("build_industry_temperature") == 3600
    assert _task_timeout("refresh_rps_daily") == 1800
    assert set(LONG_TASK_TIMEOUTS) == {"build_concept_temperature", "build_industry_temperature"}


def test_runner_uses_the_per_task_timeout_for_both_subprocess_paths():
    source = (ROOT / "app" / "pipeline" / "runner.py").read_text(encoding="utf-8")

    assert "timeout = _task_timeout(step_name)" in source
    assert "timeout=timeout," in source          # subprocess.run 路径
    assert "process.wait(timeout=timeout)" in source
    assert "timeout=1800," not in source         # 不再有硬编码超时


def test_industry_temperature_is_registered_in_chain_and_retry_subset():
    from app.pipeline.commands import _data_update_commands

    chain = _data_update_commands(trading_day="2026-10-30")
    names = [name for name, _ in chain]
    assert "build_industry_temperature" in names
    # 排在概念温度之后：两者都读全套前复权日线，必须落在末尾
    assert names.index("build_industry_temperature") > names.index("build_concept_temperature")
    assert names[-1] == "build_industry_temperature"

    command = dict(chain)["build_industry_temperature"]
    assert "--scope" in command and "industry" in command

    retry = [name for name, _ in _data_update_commands(trading_day=None, retry_failed=True)]
    assert "build_industry_temperature" in retry


def test_plan_catalog_and_command_table_stay_identical():
    from app.pipeline.commands import _data_update_commands
    from app.handler import DATA_UPDATE_TASK_PLAN

    commands = [name for name, _ in _data_update_commands(trading_day="2026-10-30")]
    planned = [task["id"] for task in DATA_UPDATE_TASK_PLAN]
    assert planned == commands, "计划页与命令表的任务或顺序不一致"
    assert "build_market_relative_strength" in planned
