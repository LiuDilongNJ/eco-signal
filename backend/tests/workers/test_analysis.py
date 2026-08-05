"""Unit tests for AI analysis worker tasks."""
from unittest.mock import MagicMock, patch

import pytest

from app.models.system import Queue


# Helpers

def _make_queue(queue_id: int = 1, user_id: int = 1) -> MagicMock:
    q = MagicMock(spec=Queue)
    q.queue_id = queue_id
    q.user_id = user_id
    q.status = 0
    return q


class TestAnalysisCompletionMessage:
    """Tests for queue completion message formatting."""

    def test_formats_acoustic_index_results(self):
        from app.workers.tasks.analysis import _format_analysis_completion_message

        message = _format_analysis_completion_message(
            {"stored_count": 6, "AEI": "0.10742321535386061"}
        )

        assert message == "AEI: 0.10742321535386061"

    def test_formats_unmatched_species_suffix(self):
        from app.workers.tasks.analysis import _format_analysis_completion_message

        message = _format_analysis_completion_message(
            {
                "analysis_message_model": "BirdNET v2.4",
                "detection_count": 122,
                "annotation_count": 122,
                "unmatched_species_count": 6,
                "unmatched_species": ["Engine", "Cryptopezus nattereri"],
            }
        )

        assert message == (
            "BirdNET v2.4 found 122 detections. 122 tags were inserted."
            "(6 tags with unmatched species: Engine, Cryptopezus nattereri inserted into comments)"
        )

    def test_formats_zero_detection_message(self):
        from app.workers.tasks.analysis import _format_analysis_completion_message

        message = _format_analysis_completion_message(
            {
                "analysis_message_model": "insects-base-cnn10-96k-t",
                "detection_count": 0,
                "annotation_count": 0,
                "unmatched_species_count": 0,
                "unmatched_species": [],
            }
        )

        assert message == "insects-base-cnn10-96k-t found 0 detections. 0 tags were inserted."

    def test_updates_annotation_count_after_merge(self):
        from app.workers.tasks.analysis import _update_annotation_count_after_merge

        result = {"annotation_count": 5}
        _update_annotation_count_after_merge(result, 2, keep_merged_only=False)
        assert result["annotation_count"] == 7

        result = {"annotation_count": 5}
        _update_annotation_count_after_merge(result, 2, keep_merged_only=True)
        assert result["annotation_count"] == 2


# analyze_birdnet worker

@pytest.mark.anyio
class TestAnalyzeBirdnetWorker:
    """Tests for the analyze_birdnet ARQ task."""

    async def test_cancelled_task_marks_queue_error(self):
        """Cancelled ARQ tasks should not leave queue rows stuck in running."""
        import asyncio

        from app.workers.tasks.analysis import _run_with_queue

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.asyncio.to_thread", side_effect=asyncio.CancelledError):
                with pytest.raises(asyncio.CancelledError):
                    await _run_with_queue("BirdNET", 1, MagicMock())

        assert mock_queue.status == 3
        assert mock_queue.error == "BirdNET task cancelled by worker shutdown"
        assert mock_queue.stop_time is not None
        mock_session.commit.assert_called_once()

    async def test_passes_new_params_to_service(self):
        """Worker passes BirdNET parameters to the service."""
        from app.workers.tasks.analysis import analyze_birdnet

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_birdnet.return_value = {
            "detection_count": 3,
            "annotation_count": 3,
            "unmatched_species": [],
            "analysis_message_model": "BirdNET v2.4",
            "unmatched_species_count": 0,
        }

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service), \
                 patch("app.workers.tasks.analysis.cache_analysis_queue_message") as mock_cache:
                result = await analyze_birdnet(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                    min_confidence=0.4,
                    overlap=1.5,
                    sensitivity=1.2,
                    min_frequency=1,
                    max_frequency=12000,
                    week=12,
                    locale="zh",
                    top_n=3,
                )

        mock_service.analyze_and_store_birdnet.assert_called_once()
        call_kwargs = mock_service.analyze_and_store_birdnet.call_args[1]
        assert call_kwargs["min_confidence"] == 0.4
        assert call_kwargs["min_frequency"] == 1
        assert call_kwargs["max_frequency"] == 12000
        assert "birdnet_version" not in call_kwargs
        assert call_kwargs["locale"] == "zh"
        assert call_kwargs["top_n"] == 3
        assert "batch_size" not in call_kwargs
        assert result["status"] == "completed"
        assert result["message"] == "BirdNET v2.4 found 3 detections. 3 tags were inserted."
        mock_cache.assert_called_once_with(1, result["message"])

    async def test_cache_failure_does_not_fail_queue(self):
        """Redis cache issues should not prevent the analysis queue from completing."""
        from app.workers.tasks.analysis import analyze_birdnet

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_birdnet.return_value = {
            "detection_count": 1,
            "annotation_count": 1,
            "unmatched_species": [],
            "unmatched_species_count": 0,
            "analysis_message_model": "BirdNET v2.4",
        }

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service), \
                 patch("app.workers.tasks.analysis.cache_analysis_queue_message", side_effect=RuntimeError("redis down")):
                result = await analyze_birdnet(ctx={}, queue_id=1, audio_path="/tmp/test.wav", media_id=10)

        assert result["status"] == "completed"
        assert mock_queue.status == 2
        assert "message" not in result

    async def test_merge_called_when_enabled(self):
        """When merge_enabled=True, merge_annotations() is called after analysis."""
        from app.workers.tasks.analysis import analyze_birdnet

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_birdnet.return_value = {
            "detection_count": 5,
            "annotation_count": 5,
            "annotation_ids": [101, 102, 103],
            "unmatched_species": [],
            "unmatched_species_count": 0,
            "analysis_message_model": "BirdNET v2.4",
        }
        mock_service.birdnet.version = "2.4"
        mock_service.merge_annotations.return_value = 1

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service), \
                 patch("app.workers.tasks.analysis.cache_analysis_queue_message") as mock_cache:
                result = await analyze_birdnet(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                    merge_enabled=True,
                    merge_max_gap=2.0,
                    merge_keep_only=False,
                )

        mock_service.merge_annotations.assert_called_once()
        assert mock_service.merge_annotations.call_args.kwargs["annotation_ids"] == [101, 102, 103]
        assert result["annotation_count"] == 6
        assert result["message"] == "BirdNET v2.4 found 5 detections. 6 tags were inserted."
        mock_cache.assert_called_once_with(1, result["message"])

    async def test_merge_skipped_when_disabled(self):
        """When merge_enabled=False, merge_annotations() is NOT called."""
        from app.workers.tasks.analysis import analyze_birdnet

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_birdnet.return_value = {
            "detection_count": 3,
            "annotation_count": 3,
            "unmatched_species": [],
        }

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                await analyze_birdnet(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                    merge_enabled=False,
                )

        mock_service.merge_annotations.assert_not_called()


# analyze_batdetect worker

@pytest.mark.anyio
class TestAnalyzeBatdetectWorker:
    """Tests for the analyze_batdetect ARQ task."""

    async def test_passes_detection_parameters(self):
        """Worker passes BatDetect parameters to the service."""
        from app.workers.tasks.analysis import analyze_batdetect

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_batdetect.return_value = {
            "detection_count": 2,
            "annotation_count": 2,
            "unmatched_species": [],
        }

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                result = await analyze_batdetect(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                    detection_threshold=0.4,
                    chunk_size=5,
                )

        assert result["status"] == "completed"
        call_kwargs = mock_service.analyze_and_store_batdetect.call_args.kwargs
        assert call_kwargs["detection_threshold"] == 0.4
        assert call_kwargs["chunk_size"] == 5

    async def test_merge_called_when_enabled(self):
        """Batdetect merge is triggered when merge_enabled=True."""
        from app.workers.tasks.analysis import analyze_batdetect

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_batdetect.return_value = {
            "detection_count": 4,
            "annotation_count": 4,
            "annotation_ids": [201, 202],
            "unmatched_species": [],
        }
        mock_service.batdetect.version = "0.1.2"

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                await analyze_batdetect(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                    merge_enabled=True,
                    merge_max_gap=1.0,
                    merge_keep_only=True,
                )

        mock_service.merge_annotations.assert_called_once()
        assert mock_service.merge_annotations.call_args.kwargs["annotation_ids"] == [201, 202]


# analyze_insects worker

@pytest.mark.anyio
class TestAnalyzeInsectsWorker:
    """Tests for the analyze_insects ARQ task."""

    async def test_passes_window_and_stride_to_service(self):
        """Worker passes window_size, stride_length and max_freq to the service."""
        from app.workers.tasks.analysis import analyze_insects

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_insects.return_value = {
            "detection_count": 5,
            "annotation_count": 5,
            "unmatched_species": [],
        }

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                result = await analyze_insects(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                    window_size=6.0,
                    stride_length=3.0,
                    max_freq=22050,
                )

        assert result["status"] == "completed"
        call_kwargs = mock_service.analyze_and_store_insects.call_args[1]
        assert call_kwargs["window_size"] == 6.0
        assert call_kwargs["stride_length"] == 3.0
        assert call_kwargs["max_freq"] == 22050

    async def test_merge_called_when_enabled(self):
        """When merge_enabled=True, merge_annotations() is called after insects analysis."""
        from app.workers.tasks.analysis import analyze_insects

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_insects.return_value = {
            "detection_count": 3,
            "annotation_count": 3,
            "annotation_ids": [301, 302, 303],
            "unmatched_species": [],
        }
        mock_service.insects.version = "0.5.1"

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                await analyze_insects(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                    merge_enabled=True,
                    merge_max_gap=1.5,
                    merge_keep_only=True,
                )

        mock_service.merge_annotations.assert_called_once()
        assert mock_service.merge_annotations.call_args.kwargs["annotation_ids"] == [301, 302, 303]

    async def test_merge_skipped_when_no_detections(self):
        """merge_annotations is NOT called when there are 0 detections."""
        from app.workers.tasks.analysis import analyze_insects

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_insects.return_value = {
            "detection_count": 0,
            "annotation_count": 0,
            "unmatched_species": [],
        }

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                await analyze_insects(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                    merge_enabled=True,
                )

        mock_service.merge_annotations.assert_not_called()

    async def test_error_sets_queue_status_to_error(self):
        """When analyze_and_store_insects raises, queue status is set to 3 (error)."""
        from app.workers.tasks.analysis import analyze_insects

        mock_session = MagicMock()
        mock_queue = _make_queue()
        mock_session.get.return_value = mock_queue

        mock_service = MagicMock()
        mock_service.analyze_and_store_insects.side_effect = RuntimeError("autrainer crashed")

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            with patch("app.workers.tasks.analysis.analysis_service", mock_service):
                result = await analyze_insects(
                    ctx={},
                    queue_id=1,
                    audio_path="/tmp/test.wav",
                    media_id=10,
                )

        assert mock_queue.status == 3
        assert "autrainer crashed" in mock_queue.error
        assert "error" in result

    async def test_queue_not_found_returns_error(self):
        """When queue_id does not exist, returns error dict immediately."""
        from app.workers.tasks.analysis import analyze_insects

        mock_session = MagicMock()
        mock_session.get.return_value = None  # queue not found

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await analyze_insects(
                ctx={},
                queue_id=999,
                audio_path="/tmp/test.wav",
                media_id=10,
            )

        assert result == {"error": "Queue not found"}


# ModelDownloadError → ARQ Retry

@pytest.mark.anyio
class TestModelDownloadErrorRetry:
    """Tests that ModelDownloadError triggers ARQ Retry instead of marking queue as error."""

    async def _setup_session(self, queue):
        """Helper: create a mock session that returns the given queue."""
        mock_session = MagicMock()
        mock_session.get.return_value = queue
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        return mock_session

    async def test_birdnet_model_download_error_raises_retry(self):
        """ModelDownloadError in analyze_birdnet triggers TaskRetryError and resets queue status to 0."""
        from app.ai.exceptions import ModelDownloadError
        from app.workers.exceptions import TaskRetryError
        from app.workers.tasks.analysis import analyze_birdnet

        queue = _make_queue()
        mock_session = await self._setup_session(queue)

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            with patch(
                "app.workers.tasks.analysis.analysis_service",
            ) as mock_service:
                mock_service.analyze_and_store_birdnet.side_effect = ModelDownloadError("BirdNET model download failed")
                with pytest.raises(TaskRetryError):
                    await analyze_birdnet(ctx={}, queue_id=1, audio_path="/tmp/test.wav", media_id=10)

        # Queue should be reset to pending (0) so the next attempt works correctly
        assert queue.status == 0

    async def test_batdetect_model_download_error_raises_retry(self):
        """ModelDownloadError in analyze_batdetect triggers TaskRetryError."""
        from app.ai.exceptions import ModelDownloadError
        from app.workers.exceptions import TaskRetryError
        from app.workers.tasks.analysis import analyze_batdetect

        queue = _make_queue()
        mock_session = await self._setup_session(queue)

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            with patch(
                "app.workers.tasks.analysis.analysis_service",
            ) as mock_service:
                mock_service.analyze_and_store_batdetect.side_effect = ModelDownloadError("batdetect2 download timed out")
                with pytest.raises(TaskRetryError):
                    await analyze_batdetect(ctx={}, queue_id=1, audio_path="/tmp/test.wav", media_id=10)

        assert queue.status == 0

    async def test_insects_model_download_error_raises_retry(self):
        """ModelDownloadError in analyze_insects triggers TaskRetryError."""
        from app.ai.exceptions import ModelDownloadError
        from app.workers.exceptions import TaskRetryError
        from app.workers.tasks.analysis import analyze_insects

        queue = _make_queue()
        mock_session = await self._setup_session(queue)

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            with patch(
                "app.workers.tasks.analysis.analysis_service",
            ) as mock_service:
                mock_service.analyze_and_store_insects.side_effect = ModelDownloadError("autrainer model download timed out")
                with pytest.raises(TaskRetryError):
                    await analyze_insects(ctx={}, queue_id=1, audio_path="/tmp/test.wav", media_id=10)

        assert queue.status == 0

    async def test_birdnet_non_download_error_marks_queue_as_error(self):
        """A non-ModelDownloadError in analyze_birdnet still marks queue as error (status=3)."""
        from app.workers.tasks.analysis import analyze_birdnet

        queue = _make_queue()
        mock_session = await self._setup_session(queue)

        with patch("app.workers.tasks.analysis.Session", return_value=mock_session):
            with patch(
                "app.workers.tasks.analysis.analysis_service",
            ) as mock_service:
                mock_service.analyze_and_store_birdnet.side_effect = RuntimeError("audio file corrupted")
                result = await analyze_birdnet(ctx={}, queue_id=1, audio_path="/tmp/test.wav", media_id=10)

        assert queue.status == 3
        assert "audio file corrupted" in queue.error
        assert "error" in result
