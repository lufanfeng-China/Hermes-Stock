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

def _run_data_update_command(
    step_name: str,
    command: list[str],
    progress_callback=None,
) -> SimpleNamespace:
    if progress_callback is None:
        return subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=1800,
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
        returncode = process.wait(timeout=1800)
    except Exception:
        process.kill()
        raise
    return SimpleNamespace(returncode=returncode, stdout="".join(stdout_lines), stderr=stderr_text)


def run_full_data_update(progress_callback=None, retry_failed: bool = False) -> dict[str, object]:
    trading_day = _latest_trading_day_for_refresh()
    steps: list[dict[str, object]] = []
    commands = _data_update_commands(trading_day, retry_failed=retry_failed)

    for step_name, command in commands:
        # A command may stay quiet for minutes (notably full-market RPS).  Publish
        # the step at launch instead of waiting for a parseable stdout line, so the
        # UI never remains pinned to the previous completed step.
        _update_data_update_job_state(
            current_step=step_name,
            current_industry=None,
            progress_index=None,
            progress_total=None,
            current_progress_text=f"当前步骤：{step_name} 正在运行...",
            last_line="",
        )
        try:
            result = _run_data_update_command(step_name, command, progress_callback=progress_callback)
        except subprocess.TimeoutExpired as exc:
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
        if result.returncode != 0:
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
        'ok': True,
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
        _update_data_update_job_state(
            status='succeeded',
            running=False,
            can_retry_failed=False,
            finished_at=_format_timestamp(time.time()),
            current_progress_text='数据更新完成',
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
