"""Unit tests for AI analysis worker tasks."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.enums import QueueStatus
from app.models.system import Queue
from app.workers.tasks.analysis import (
    analyze_acoustic_index,
    analyze_batdetect,
    analyze_birdnet,
)


@pytest.mark.anyio
class TestAnalysisTasksAdditional:
    """Tests for analysis worker queue lifecycle and error handling."""

    async def test_analyze_birdnet_queue_not_found(self):
        mock_session = MagicMock()
        mock_session.get.return_value = None

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            result = await analyze_birdnet(ctx={}, queue_id=999, audio_path="test.wav")

        assert result == {"error": "Queue not found"}

    async def test_analyze_birdnet_no_media_id(self):
        mock_session = MagicMock()
        queue = MagicMock(spec=Queue, queue_id=1, user_id=1, status=QueueStatus.RUNNING)
        mock_session.get.return_value = queue

        mock_service = MagicMock()
        mock_service.birdnet.analyze.return_value = [{"species": "S1", "confidence": 0.9}]

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                result = await analyze_birdnet(ctx={}, queue_id=1, audio_path="test.wav", media_id=None)

        assert result["status"] == "completed"
        assert result["detection_count"] == 1
        assert result["annotation_count"] == 0

    async def test_analyze_birdnet_error(self):
        mock_session = MagicMock()
        queue = MagicMock(spec=Queue, queue_id=1, user_id=1, status=QueueStatus.RUNNING)
        mock_session.get.return_value = queue

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.analysis.analysis_service") as mock_service:
                mock_service.analyze_and_store_birdnet.side_effect = Exception("Crash")
                result = await analyze_birdnet(ctx={}, queue_id=1, audio_path="test.wav", media_id=1)

        assert "error" in result
        assert queue.status == 3
        assert "Crash" in queue.error

    async def test_analyze_batdetect_queue_not_found(self):
        mock_session = MagicMock()
        mock_session.get.return_value = None

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            result = await analyze_batdetect(ctx={}, queue_id=999, audio_path="test.wav", media_id=10)

        assert result == {"error": "Queue not found"}

    async def test_analyze_batdetect_error(self):
        mock_session = MagicMock()
        queue = MagicMock(spec=Queue, queue_id=1, user_id=1, status=QueueStatus.RUNNING)
        mock_session.get.return_value = queue

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.analysis.analysis_service") as mock_service:
                mock_service.analyze_and_store_batdetect.side_effect = Exception("Crash")
                result = await analyze_batdetect(ctx={}, queue_id=1, audio_path="test.wav", media_id=10)

        assert "error" in result
        assert queue.status == 3

    async def test_analyze_acoustic_index_success(self):
        mock_session = MagicMock()
        queue = MagicMock(spec=Queue, queue_id=1, user_id=1)
        mock_session.get.return_value = queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_acoustic_index.return_value = {"stored_count": 5, "ACI_sum": 123}

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                result = await analyze_acoustic_index(
                    ctx={},
                    queue_id=1,
                    audio_path="test.wav",
                    media_id=10,
                    index_id=3,
                    index_name="temporal_median",
                    params={"Nt": 512},
                    channel="right",
                    min_time=1,
                    max_time=5,
                    min_frequency=100,
                    max_frequency=9000,
                    log_id=1234,
                )

        assert result["status"] == "completed"
        assert result["stored_count"] == 5
        assert queue.status == 2
        assert mock_service.analyze_and_store_acoustic_index.call_args.kwargs["channel"] == "right"
        assert mock_service.analyze_and_store_acoustic_index.call_args.kwargs["min_time"] == 1
        assert mock_service.analyze_and_store_acoustic_index.call_args.kwargs["max_time"] == 5
        assert mock_service.analyze_and_store_acoustic_index.call_args.kwargs["min_frequency"] == 100
        assert mock_service.analyze_and_store_acoustic_index.call_args.kwargs["max_frequency"] == 9000
        assert mock_service.analyze_and_store_acoustic_index.call_args.kwargs["log_id"] == 1234
        assert mock_service.analyze_and_store_acoustic_index.call_args.kwargs["index_type_name"] == "temporal_median"

    async def test_analyze_acoustic_index_dispatches_acoustic_analysis(self):
        mock_session = MagicMock()
        queue = MagicMock(spec=Queue, queue_id=1, user_id=1)
        mock_session.get.return_value = queue

        mock_service = MagicMock()
        mock_service.analyze_acoustic_selection.return_value = {
            "stored_count": 1,
            "Frequency of maximum energy": "609",
        }

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                result = await analyze_acoustic_index(
                    ctx={},
                    queue_id=1,
                    audio_path="test.flac",
                    media_id=10,
                    index_id=None,
                    index_name="max_frequency",
                    params={},
                    channel="mono",
                    min_time=1,
                    max_time=5,
                    min_frequency=1,
                    max_frequency=9000,
                    filter_enabled=True,
                )

        assert result["status"] == "completed"
        assert result["Frequency of maximum energy"] == "609"
        assert result["message"] == "Frequency of maximum energy: 609"
        mock_service.analyze_and_store_acoustic_index.assert_not_called()
        kwargs = mock_service.analyze_acoustic_selection.call_args.kwargs
        assert kwargs["analysis_type"] == "max_frequency"
        assert kwargs["audio_path"] == Path("test.flac")
        assert kwargs["filter_enabled"] is True

    async def test_analyze_acoustic_index_queue_not_found(self):
        mock_session = MagicMock()
        mock_session.get.return_value = None

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            result = await analyze_acoustic_index(
                ctx={},
                queue_id=999,
                audio_path="test.wav",
                media_id=10,
                index_id=1,
                index_name="acoustic_complexity_index",
            )

        assert result == {"error": "Queue not found"}

    async def test_analyze_acoustic_index_error(self):
        mock_session = MagicMock()
        queue = MagicMock(spec=Queue, queue_id=1, user_id=1, status=QueueStatus.RUNNING)
        mock_session.get.return_value = queue

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("app.workers.tasks.analysis.analysis_service") as mock_service:
                mock_service.analyze_and_store_acoustic_index.side_effect = Exception("Crash")
                result = await analyze_acoustic_index(
                    ctx={},
                    queue_id=1,
                    audio_path="test.wav",
                    media_id=10,
                    index_id=2,
                    index_name="soundscape_index",
                )

        assert "error" in result
        assert queue.status == 3
