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
    DataUpdateStepError,
)
from app.pipeline.commands import _data_update_commands, _latest_trading_day_for_refresh, clear_runtime_data_caches

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
            raise DataUpdateStepError(
                step_name,
                f'{step_name} 数据更新已停止或失败（exit code {result.returncode}）',
                returncode=result.returncode,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )

    clear_runtime_data_caches()
    _load_rps_history_dataset.cache_clear()
    return {
        'ok': True,
        'steps': steps,
        'data_update_status': load_data_update_status(),
    }


def _run_data_update_worker(retry_failed: bool = False) -> None:
    try:
        result = run_full_data_update(progress_callback=_record_data_update_progress, retry_failed=retry_failed)
        status_payload = result.get('data_update_status') if isinstance(result, dict) else {}
        _update_data_update_job_state(
            status='succeeded',
            running=False,
            can_retry_failed=False,
            finished_at=_format_timestamp(time.time()),
            current_progress_text='数据更新完成',
            data_update_status=status_payload,
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
    payload = load_data_update_status()
    payload['started'] = True
    return payload


# Imported at bottom to avoid circular import
def _clear_rps_cache():
    from app.data.rps_history import _load_rps_history_dataset
    _load_rps_history_dataset.cache_clear()
