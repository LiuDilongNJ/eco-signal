import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.ai.cancellable_process import (
    run_cancellable_process,
    terminate_process_group,
)
from app.core.task_cancellation import (
    TASK_CANCELLED_MESSAGE,
    CancellationToken,
    TaskCancelledError,
)
from app.enums import QueueStatus
from app.workers.cancellation import (
    cancellation_requested,
    finalize_queue_cancellation,
    prepare_queue_for_execution,
)


def test_cancellation_token_notifies_callbacks_once():
    token = CancellationToken()
    callback = MagicMock()
    token.add_callback(callback)

    token.cancel()
    token.cancel()

    callback.assert_called_once_with()
    with pytest.raises(TaskCancelledError):
        token.raise_if_cancelled()


def test_cancellable_process_terminates_when_already_cancelled():
    token = CancellationToken()
    token.cancel()
    process = MagicMock()
    process.communicate.return_value = ("", "")
    process.returncode = -15

    with (
        patch("app.ai.cancellable_process.subprocess.Popen", return_value=process),
        patch("app.ai.cancellable_process.terminate_process_group") as terminate,
        pytest.raises(TaskCancelledError),
    ):
        run_cancellable_process(["worker-cli"], timeout=10, cancellation_token=token)

    terminate.assert_called_once_with(process)


def test_cancellable_process_terminates_on_timeout():
    process = MagicMock()
    process.communicate.side_effect = subprocess.TimeoutExpired("worker-cli", 10)

    with (
        patch("app.ai.cancellable_process.subprocess.Popen", return_value=process),
        patch("app.ai.cancellable_process.terminate_process_group") as terminate,
        pytest.raises(subprocess.TimeoutExpired),
    ):
        run_cancellable_process(["worker-cli"], timeout=10)

    terminate.assert_called_once_with(process)


def test_cancellable_process_returns_completed_result_and_unregisters_callback():
    token = CancellationToken()
    process = MagicMock(returncode=0)
    process.communicate.return_value = ("output", "warning")

    with patch("app.ai.cancellable_process.subprocess.Popen", return_value=process) as popen:
        result = run_cancellable_process(
            ["worker-cli", "--flag"],
            timeout=10,
            cancellation_token=token,
            env={"MODE": "test"},
        )

    assert result.args == ["worker-cli", "--flag"]
    assert result.stdout == "output"
    assert result.stderr == "warning"
    assert result.returncode == 0
    popen.assert_called_once_with(
        ["worker-cli", "--flag"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={"MODE": "test"},
    )
    assert token._callbacks == []


def test_terminate_process_group_escalates_after_grace_period():
    process = MagicMock(pid=123)
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("worker-cli", 5), 0]

    with patch("app.ai.cancellable_process.os.killpg") as killpg:
        terminate_process_group(process)

    assert [call.args for call in killpg.call_args_list] == [
        (123, 15),
        (123, 9),
    ]


def test_terminate_process_group_ignores_finished_or_missing_process():
    finished = MagicMock()
    finished.poll.return_value = 0
    terminate_process_group(finished)

    running = MagicMock(pid=456)
    running.poll.return_value = None
    with patch(
        "app.ai.cancellable_process.os.killpg",
        side_effect=ProcessLookupError,
    ):
        terminate_process_group(running)

    finished.wait.assert_not_called()
    running.wait.assert_not_called()


def _mock_session():
    session = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = session
    session_context.__exit__.return_value = False
    return session, session_context


def test_prepare_queue_for_execution_claims_pending_queue():
    session, session_context = _mock_session()
    session.execute.return_value.rowcount = 1

    with patch("app.workers.cancellation.Session", return_value=session_context):
        assert prepare_queue_for_execution(8) == QueueStatus.RUNNING

    session.commit.assert_called_once_with()
    session.get.assert_not_called()


@pytest.mark.parametrize(
    ("queue", "expected"),
    [
        (None, None),
        (SimpleNamespace(status=QueueStatus.COMPLETED), QueueStatus.COMPLETED),
        (SimpleNamespace(status=-1), None),
    ],
)
def test_prepare_queue_for_execution_returns_existing_status(queue, expected):
    session, session_context = _mock_session()
    session.execute.return_value.rowcount = 0
    session.get.return_value = queue

    with patch("app.workers.cancellation.Session", return_value=session_context):
        assert prepare_queue_for_execution(9) == expected


def test_finalize_queue_cancellation_deletes_cancelled_queue():
    session, session_context = _mock_session()
    queue = SimpleNamespace(error=TASK_CANCELLED_MESSAGE)
    session.get.return_value = queue

    with (
        patch("app.workers.cancellation.Session", return_value=session_context),
        patch("app.workers.cancellation.collection_bundle_export_repository.get_by_queue_ids", return_value=[]),
        patch("app.workers.cancellation.delete_queue_exports") as delete_exports,
    ):
        finalize_queue_cancellation(10)

    delete_exports.assert_called_once_with(session, [])
    session.delete.assert_called_once_with(queue)
    session.commit.assert_called_once_with()


@pytest.mark.parametrize(
    ("queue", "expected"),
    [
        (None, False),
        (SimpleNamespace(status=QueueStatus.ERROR, error="Crash"), False),
        (
            SimpleNamespace(status=QueueStatus.ERROR, error=TASK_CANCELLED_MESSAGE),
            True,
        ),
    ],
)
def test_cancellation_requested_requires_error_status_and_marker(queue, expected):
    session, session_context = _mock_session()
    session.get.return_value = queue

    with patch("app.workers.cancellation.Session", return_value=session_context):
        assert cancellation_requested(11) is expected
