"""Data update runner."""
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from app.pipeline.state import (
    DATA_UPDATE_LOCK, DATA_UPDATE_JOB_STATE, DATA_UPDATE_JOB_STATE_LOCK,
    DATA_UPDATE_OUTPUT_TAIL_LINES, _data_update_job_snapshot, _update_data_update_job_state,
    _append_data_update_job_output, _record_data_update_progress, _tail_lines,
    DataUpdateStepError, _format_timestamp,
)
from app.pipeline.commands import _data_update_commands, _latest_trading_day_for_refresh, clear_runtime_data_caches

from app.data.rps_history import _load_rps_history_dataset, _load_rps_trading_days, _load_stock_rps_history_dataset

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TONGDAXIN_PYTHON = "/home/lufanfeng/.venvs/moontdx-china-stock-data/bin/python"

# 默认单任务超时 30 分钟。温度类构建要读 5,400 只前复权日线并回溯 146 个交易日,
# 实测 17-25 分钟,余量不足以覆盖机器变慢或映射扩张,因此单独放宽到 60 分钟。
DEFAULT_TASK_TIMEOUT = 1800
LONG_TASK_TIMEOUTS = {
    'build_concept_temperature': 3600,
    'build_industry_temperature': 3600,
}


def _task_timeout(step_name: str) -> int:
    return LONG_TASK_TIMEOUTS.get(step_name, DEFAULT_TASK_TIMEOUT)


# 概念温度与行业温度互不依赖（各写各的快照），可以同时跑：两者都要读全套前复权
# 日线，串行约 40 分钟，并行约 25 分钟。
PARALLEL_GROUPS: tuple[tuple[str, ...], ...] = (
    ('build_concept_temperature', 'build_industry_temperature'),
)
# 每个温度构建峰值约 1.8 GB 常驻内存；WSL 总内存 7 GB，留足余量再并行，否则串行。
PARALLEL_MIN_AVAILABLE_MB = 4500


def _available_memory_mb() -> int | None:
    """MemAvailable（MB）；读不到就返回 None，调用方按串行处理。"""
    try:
        with open('/proc/meminfo', encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def _can_parallelize() -> bool:
    available = _available_memory_mb()
    return available is not None and available >= PARALLEL_MIN_AVAILABLE_MB


def _build_units(commands: list[tuple[str, list[str]]]) -> list[list[tuple[str, list[str]]]]:
    """把命令序列切成执行单元：同组任务合成一个并行单元，其余单任务各成一个单元。"""
    available = dict(commands)
    units: list[list[tuple[str, list[str]]]] = []
    consumed: set[str] = set()
    for name, command in commands:
        if name in consumed:
            continue
        group = next((group for group in PARALLEL_GROUPS if name in group), None)
        if (group and name == group[0] and all(member in available for member in group)
                and _can_parallelize()):
            units.append([(member, available[member]) for member in group])
            consumed.update(group)
        else:
            units.append([(name, command)])
    return units


def _run_parallel_unit(unit: list[tuple[str, list[str]]], progress_callback=None) -> list[dict[str, object]]:
    """并行执行一个单元里的所有任务，逐个记录结果；单个失败不影响同组其他任务。"""
    names = [name for name, _ in unit]
    task_states = dict(DATA_UPDATE_JOB_STATE.get('task_states') or {})
    started = _format_timestamp(time.time())
    for name in names:
        task_states[name] = {'status': 'running', 'started_at': started}
    _update_data_update_job_state(
        task_states=task_states,
        current_step=' + '.join(names),
        current_industry=None,
        progress_index=None,
        progress_total=None,
        current_progress_text=f"并行执行：{' / '.join(names)}",
        last_line="",
    )

    results: dict[str, object] = {}

    def _worker(step_name: str, command: list[str]) -> None:
        try:
            results[step_name] = _run_data_update_command(step_name, command, progress_callback=progress_callback)
        except (subprocess.SubprocessError, OSError) as exc:   # 含 TimeoutExpired
            results[step_name] = exc

    threads = [threading.Thread(target=_worker, args=(name, command), daemon=True) for name, command in unit]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    steps: list[dict[str, object]] = []
    for name, _command in unit:
        outcome = results.get(name)
        if isinstance(outcome, BaseException):
            step = {'name': name, 'ok': False, 'returncode': None, 'stdout_tail': '',
                    'stderr_tail': str(outcome), 'parallel': True}
        else:
            step = {'name': name, 'ok': outcome.returncode == 0, 'returncode': outcome.returncode,
                    'stdout_tail': _tail_lines(outcome.stdout), 'stderr_tail': _tail_lines(outcome.stderr),
                    'parallel': True}
        steps.append(step)
        _record_step_result(step)
    return steps


def _run_data_update_command(
    step_name: str,
    command: list[str],
    progress_callback=None,
) -> SimpleNamespace:
    timeout = _task_timeout(step_name)
    if progress_callback is None:
        return subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines: list[str] = []
    stderr_text = ""
    try:
        assert process.stdout is not None
        for line in process.stdout:
            stdout_lines.append(line)
            progress_callback(step_name, line.rstrip('\n'))
        stderr_text = process.stderr.read() if process.stderr is not None else ""
        returncode = process.wait(timeout=timeout)
    except Exception:
        process.kill()
        raise
    return SimpleNamespace(returncode=returncode, stdout="".join(stdout_lines), stderr=stderr_text)


GOOD_STOCK_TASKS = {'build_good_stock_financial_snapshot', 'build_good_stock_undervaluation_current'}


def _record_step_result(step):
    task_states = dict(DATA_UPDATE_JOB_STATE.get('task_states') or {})
    task_states[step['name']] = {
        'status': 'done' if step['ok'] else 'failed',
        'finished_at': _format_timestamp(time.time()),
        **({} if step['ok'] else {'error': step.get('stderr_tail') or step.get('stdout_tail') or '任务失败'}),
    }
    _update_data_update_job_state(task_states=task_states)


def run_full_data_update(progress_callback=None, retry_failed: bool = False) -> dict[str, object]:
    trading_day = _latest_trading_day_for_refresh()
    steps: list[dict[str, object]] = []
    commands = _data_update_commands(trading_day, retry_failed=retry_failed)

    # Legacy retry subset remains intact; good-stock retries only replay its
    # failed publications, not unrelated downloads or already successful work.
    if retry_failed:
        states = DATA_UPDATE_JOB_STATE.get('task_states') or {}
        good_stock_failed = any(states.get(name, {}).get('status') == 'failed' for name in GOOD_STOCK_TASKS)
        commands = [(name, cmd) for name, cmd in commands
                    if states.get(name, {}).get('status') == 'failed'
                    or (name not in GOOD_STOCK_TASKS and not good_stock_failed)]
    financial_failed = False
    planned_groups = [group for group in PARALLEL_GROUPS
                      if all(member in dict(commands) for member in group)]
    if planned_groups and not _can_parallelize():
        available = _available_memory_mb()
        _append_data_update_job_output(
            f"内存余量不足（可用 {available if available is not None else '未知'} MB，"
            f"并行门槛 {PARALLEL_MIN_AVAILABLE_MB} MB），温度构建改为串行执行\n"
        )
    for unit in _build_units(commands):
        if len(unit) > 1:
            steps.extend(_run_parallel_unit(unit, progress_callback=progress_callback))
            continue
        step_name, command = unit[0]
        if step_name == 'build_good_stock_undervaluation_current' and financial_failed:
            step = {'name': step_name, 'ok': False, 'returncode': None,
                    'stderr_tail': '好股专用财报构建失败；保留旧诊断快照，修复后重试', 'stdout_tail': '', 'skipped': True}
            steps.append(step)
            _record_step_result(step)
            continue
        # A command may stay quiet for minutes (notably full-market RPS).  Publish
        # the step at launch instead of waiting for a parseable stdout line, so the
        # UI never remains pinned to the previous completed step.
        task_states = dict(DATA_UPDATE_JOB_STATE.get('task_states') or {})
        task_states[step_name] = {'status': 'running', 'started_at': _format_timestamp(time.time())}
        _update_data_update_job_state(
            task_states=task_states,
            current_step=step_name,
            current_industry=None,
            progress_index=None,
            progress_total=None,
            current_progress_text=f"当前步骤：{step_name} 正在运行...",
            last_line="",
        )
        try:
            result = _run_data_update_command(step_name, command, progress_callback=progress_callback)
        except (subprocess.SubprocessError, OSError) as exc:
            if step_name in GOOD_STOCK_TASKS:
                step = {'name': step_name, 'ok': False, 'returncode': None,
                        'stdout_tail': '', 'stderr_tail': str(exc)}
                steps.append(step)
                _record_step_result(step)
                financial_failed = step_name == 'build_good_stock_financial_snapshot'
                continue
            if not isinstance(exc, subprocess.TimeoutExpired):
                raise
            stdout_tail = _tail_lines(exc.stdout.decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else exc.stdout)
            stderr_tail = _tail_lines(exc.stderr.decode('utf-8', errors='replace') if isinstance(exc.stderr, bytes) else exc.stderr)
            steps.append({
                'name': step_name,
                'command': ' '.join(command),
                'ok': False,
                'returncode': None,
                'stdout_tail': stdout_tail,
                'stderr_tail': stderr_tail,
                'timed_out': True,
            })
            raise DataUpdateStepError(
                step_name,
                f'{step_name} 超时（超过 1800 秒），数据更新已停止或失败',
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            ) from exc
        stdout_tail = _tail_lines(result.stdout)
        stderr_tail = _tail_lines(result.stderr)
        steps.append({
            'name': step_name,
            'command': ' '.join(command),
            'ok': result.returncode == 0,
            'returncode': result.returncode,
            'stdout_tail': stdout_tail,
            'stderr_tail': stderr_tail,
        })
        _record_step_result(steps[-1])
        if result.returncode != 0:
            if step_name in GOOD_STOCK_TASKS:
                financial_failed = step_name == 'build_good_stock_financial_snapshot'
                continue
            # The peer snapshot is a self-contained financial presentation
            # artifact.  Its failure must stay visible and retryable, but must
            # not stop RPS/MACD technical data maintenance.
            if step_name in {'build_industry_metric_snapshot', 'build_financial_health_peer_snapshot'}:
                continue
            raise DataUpdateStepError(
                step_name,
                f'{step_name} 数据更新已停止或失败（exit code {result.returncode}）',
                returncode=result.returncode,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

    clear_runtime_data_caches()
    _load_rps_history_dataset.cache_clear()
    _load_rps_trading_days.cache_clear()
    _load_stock_rps_history_dataset.cache_clear()
    return {
        'ok': all(step['ok'] for step in steps),
        'steps': steps,
    }


def run_data_update_task(task_name: str, progress_callback=None) -> dict[str, object]:
    """Run exactly one declared update command; never replays prior tasks."""
    commands = dict(_data_update_commands(_latest_trading_day_for_refresh()))
    command = commands.get(task_name)
    if command is None:
        raise ValueError(f'unsupported data update task: {task_name}')
    _update_data_update_job_state(current_step=task_name, current_industry=None, progress_index=None, progress_total=None, current_progress_text=f"当前步骤：{task_name} 正在运行...", last_line='')
    result = _run_data_update_command(task_name, command, progress_callback=progress_callback)
    if result.returncode != 0:
        raise DataUpdateStepError(task_name, f'{task_name} 数据更新已停止或失败（exit code {result.returncode}）', returncode=result.returncode, stdout_tail=_tail_lines(result.stdout), stderr_tail=_tail_lines(result.stderr))
    clear_runtime_data_caches()
    _load_rps_history_dataset.cache_clear(); _load_rps_trading_days.cache_clear(); _load_stock_rps_history_dataset.cache_clear()
    return {'ok': True, 'steps': [{'name': task_name, 'ok': True, 'returncode': 0, 'stdout_tail': _tail_lines(result.stdout), 'stderr_tail': _tail_lines(result.stderr)}]}


def _run_data_update_worker(retry_failed: bool = False, task_name: str | None = None) -> None:
    try:
        if task_name:
            result = run_data_update_task(task_name, progress_callback=_record_data_update_progress)
        else:
            result = run_full_data_update(progress_callback=_record_data_update_progress, retry_failed=retry_failed)
        status_payload = result.get('data_update_status') if isinstance(result, dict) else {}
        task_states = dict(DATA_UPDATE_JOB_STATE.get('task_states') or {})
        if task_name:
            task_states[task_name] = {'status': 'done', 'finished_at': _format_timestamp(time.time())}
        else:
            for step in result.get('steps', []):
                name = step.get('name')
                if name:
                    finished = _format_timestamp(time.time())
                    if step.get('ok'):
                        task_states[str(name)] = {'status': 'done', 'finished_at': finished}
                    else:
                        task_states[str(name)] = {
                            'status': 'failed', 'finished_at': finished,
                            'error': _tail_lines(step.get('stderr_tail') or step.get('stdout_tail') or '任务失败'),
                        }
        failed = [step for step in result.get('steps', []) if not step.get('ok')]
        _update_data_update_job_state(
            status='failed' if failed else 'succeeded',
            running=False,
            can_retry_failed=bool(failed),
            finished_at=_format_timestamp(time.time()),
            current_progress_text='部分独立任务失败；其他更新已完成，可重试失败项' if failed else '数据更新完成',
            error='；'.join(str(step.get('name')) for step in failed) or None,
            data_update_status=status_payload,
            task_states=task_states,
        )
    except Exception as exc:
        updates: dict[str, object] = {
            'status': 'failed',
            'running': False,
            'can_retry_failed': True,
            'finished_at': _format_timestamp(time.time()),
            'current_progress_text': '数据更新已停止或失败，可点击“重试失败项”继续',
            'error': str(exc),
        }
        if task_name:
            task_states = dict(DATA_UPDATE_JOB_STATE.get('task_states') or {})
            task_states[task_name] = {'status': 'failed', 'finished_at': _format_timestamp(time.time()), 'error': str(exc)}
            updates['task_states'] = task_states
        if isinstance(exc, DataUpdateStepError):
            updates.update({
                'failed_step': exc.step_name,
                'returncode': exc.returncode,
                'stdout_tail': exc.stdout_tail,
                'stderr_tail': exc.stderr_tail,
            })
        _update_data_update_job_state(**updates)
    finally:
        try:
            DATA_UPDATE_LOCK.release()
        except RuntimeError:
            pass


def start_data_update_job(retry_failed: bool = False) -> dict[str, object]:
    if retry_failed:
        previous = _data_update_job_snapshot()
        if previous.get('mode') == 'single_task' and previous.get('status') == 'failed':
            # Retry only the failed single task; unknown/removed IDs stay rejected.
            return start_data_update_task(str(previous.get('task_name') or ''))
    if not DATA_UPDATE_LOCK.acquire(blocking=False):
        return {'ok': False, 'error': {'code': 'data_update_busy', 'message': '已有数据更新任务在运行中'}}
    now = _format_timestamp(time.time())
    _update_data_update_job_state(
        status='running',
        running=True,
        mode='retry_failed' if retry_failed else 'full',
        can_retry_failed=False,
        started_at=now,
        finished_at=None,
        current_step='init',
        current_industry=None,
        progress_index=None,
        progress_total=None,
        current_progress_text='当前进度：正在准备数据更新...',
        error=None,
        stdout_tail='',
        stderr_tail='',
        stdout_tail_lines=[],
    )
    thread = threading.Thread(target=_run_data_update_worker, kwargs={'retry_failed': retry_failed}, daemon=True)
    thread.start()
    return {'ok': True, 'started': True, 'data_update_job': _data_update_job_snapshot()}


def start_data_update_task(task_name: str) -> dict[str, object]:
    commands = dict(_data_update_commands(_latest_trading_day_for_refresh()))
    if task_name not in commands:
        return {'ok': False, 'error': {'code': 'unsupported_task', 'message': '不支持或当前不可执行的数据更新任务'}}
    if not DATA_UPDATE_LOCK.acquire(blocking=False):
        return {'ok': False, 'error': {'code': 'data_update_busy', 'message': '已有数据更新任务在运行中'}}
    now = _format_timestamp(time.time())
    task_states = dict(DATA_UPDATE_JOB_STATE.get('task_states') or {})
    task_states[task_name] = {'status': 'running', 'started_at': now}
    _update_data_update_job_state(status='running', running=True, mode='single_task', task_name=task_name, can_retry_failed=False, started_at=now, finished_at=None, current_step=task_name, current_progress_text=f'当前步骤：{task_name} 正在准备...', error=None, stdout_tail='', stderr_tail='', stdout_tail_lines=[], task_states=task_states)
    threading.Thread(target=_run_data_update_worker, kwargs={'task_name': task_name}, daemon=True).start()
    return {'ok': True, 'started': True, 'data_update_job': _data_update_job_snapshot()}


# Imported at bottom to avoid circular import
def _clear_rps_cache():
    from app.data.rps_history import _load_rps_history_dataset, _load_rps_trading_days, _load_stock_rps_history_dataset
    _load_rps_history_dataset.cache_clear()
    _load_rps_trading_days.cache_clear()
    _load_stock_rps_history_dataset.cache_clear()
