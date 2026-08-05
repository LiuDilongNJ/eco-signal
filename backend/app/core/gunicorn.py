from __future__ import annotations

import os


def child_exit(_server, worker) -> None:
    metrics_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR")
    if not metrics_dir:
        return
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
