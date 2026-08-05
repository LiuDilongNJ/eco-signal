from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Mapping, Sequence

from app.core.task_cancellation import CancellationToken

_TERMINATE_GRACE_SECONDS = 5


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)


def run_cancellable_process(
    cmd: Sequence[str],
    *,
    timeout: float,
    cancellation_token: CancellationToken | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    def cancel_process() -> None:
        terminate_process_group(process)
    if cancellation_token is not None:
        cancellation_token.add_callback(cancel_process)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        terminate_process_group(process)
        raise
    finally:
        if cancellation_token is not None:
            cancellation_token.remove_callback(cancel_process)
