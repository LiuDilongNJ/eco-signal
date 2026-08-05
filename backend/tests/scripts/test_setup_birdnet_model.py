import multiprocessing
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.setup_birdnet_model import (
    ModelSetupError,
    main,
    model_setup_lock,
    prepare_birdnet_model,
)


def _record_lock_interval(model_dir: str, events: multiprocessing.Queue) -> None:
    with model_setup_lock(Path(model_dir)):
        events.put(("start", time.monotonic()))
        time.sleep(0.15)
        events.put(("end", time.monotonic()))


def test_prepare_birdnet_model_skips_download_when_files_are_complete(tmp_path: Path) -> None:
    check_model = Mock(return_value=True)
    download_model = Mock()

    downloaded = prepare_birdnet_model(
        tmp_path,
        check_model=check_model,
        download_model=download_model,
    )

    assert downloaded is False
    check_model.assert_called_once_with()
    download_model.assert_not_called()


def test_prepare_birdnet_model_downloads_missing_files(tmp_path: Path) -> None:
    check_model = Mock(side_effect=[False, True])
    download_model = Mock()

    downloaded = prepare_birdnet_model(
        tmp_path,
        check_model=check_model,
        download_model=download_model,
    )

    assert downloaded is True
    download_model.assert_called_once_with()


def test_prepare_birdnet_model_replaces_incomplete_files(tmp_path: Path) -> None:
    check_model = Mock(side_effect=[False, False, True])
    download_model = Mock()
    sleep = Mock()

    downloaded = prepare_birdnet_model(
        tmp_path,
        check_model=check_model,
        download_model=download_model,
        sleep=sleep,
    )

    assert downloaded is True
    assert download_model.call_count == 2
    sleep.assert_called_once_with(5.0)


def test_prepare_birdnet_model_raises_after_download_failures(tmp_path: Path) -> None:
    check_model = Mock(return_value=False)
    download_model = Mock(side_effect=OSError("network unavailable"))
    sleep = Mock()

    with pytest.raises(ModelSetupError, match="could not be prepared"):
        prepare_birdnet_model(
            tmp_path,
            check_model=check_model,
            download_model=download_model,
            sleep=sleep,
        )

    assert download_model.call_count == 3
    assert sleep.call_args_list[0].args == (5.0,)
    assert sleep.call_args_list[1].args == (10.0,)


def test_main_returns_nonzero_when_model_preparation_fails() -> None:
    with patch(
        "scripts.setup_birdnet_model.prepare_birdnet_model",
        side_effect=ModelSetupError("preparation failed"),
    ):
        assert main() == 1


def test_model_setup_lock_serializes_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    events = context.Queue()
    processes = [
        context.Process(target=_record_lock_interval, args=(str(tmp_path), events))
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=5)

    assert all(process.exitcode == 0 for process in processes)
    recorded = [events.get(timeout=1) for _ in range(4)]

    assert [event for event, _ in recorded] == ["start", "end", "start", "end"]
