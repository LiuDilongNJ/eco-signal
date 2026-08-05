from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.ai.acoustic_indices.analyzer import AcousticIndexAnalyzer
from app.ai.legacy_runtime.bin import getMaad
from app.api.deps import get_current_user, get_db, get_task_publisher
from app.main import app
from app.models.index import IndexType
from app.models.media import Media
from app.models.system import Queue
from app.models.user import Role, User
from app.services.analysis_service import AnalysisService

mock_admin_role = Role(role_id=1, name="Administrator")
mock_admin = User(
    user_id=1,
    username="admin",
    name="Admin",
    email="admin@example.com",
    password="hashed",
    active=True,
    role_id=1,
)
mock_admin.role = mock_admin_role

mock_session = MagicMock()
mock_media = Media(
    media_id=1,
    media_type="audio",
    filename="test.wav",
    directory="2024/01/01",
    audio_setting_id=1,
    uploader_id=1,
)


def _mock_refresh(obj):
    if isinstance(obj, Queue) and obj.queue_id is None:
        obj.queue_id = 99


mock_session.refresh.side_effect = _mock_refresh


def override_get_db():
    try:
        yield mock_session
    finally:
        pass


def override_get_current_user_admin():
    return mock_admin


@pytest.fixture(autouse=True)
def reset_mocks(monkeypatch: pytest.MonkeyPatch):
    mock_session.reset_mock()
    mock_session.refresh.side_effect = _mock_refresh
    mock_session.execute.return_value.scalar_one.return_value = 777
    mock_session.exec.return_value.all.return_value = []
    mock_session.exec.return_value.first.return_value = None
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user_admin
    monkeypatch.setattr(
        "app.services.analysis_service.AnalysisService._resolve_audio_path",
        lambda _self, _session, _media, media_id: f"/tmp/media-{media_id}.wav",
    )
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


client = TestClient(app)

INDICES_RUN_URL = "/api/v1/acoustic-index-jobs"
INDICES_PREVIEW_URL = "/api/v1/acoustic-index-previews"
INDEX_LOGS_URL = "/api/v1/index-logs"


def test_get_index_types_returns_metadata():
    mock_session.exec.return_value.all.return_value = [
        IndexType(
            index_id=1,
            name="soundscape_index",
            description="NDSI",
            param=[
                {"key": "flim_bioPh", "default": "1000,10000", "value_type": "string"},
                {"key": "R_compatible", "default": "soundecology", "value_type": "string"},
            ],
            url="https://example.com",
        )
    ]

    response = client.get("/api/v1/index-types")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload[0]["name"] == "soundscape_index"
    assert payload[0]["parameters"] == [
        {"key": "flim_bioPh", "default": "1000,10000", "value_type": "string"},
        {"key": "R_compatible", "default": "soundecology", "value_type": "string"},
    ]

def test_run_acoustic_indices_requires_indices():
    mock_session.get.return_value = mock_media

    response = client.post(INDICES_RUN_URL, json={"project_id": 1, "media_ids": [1], "indices": []})

    assert response.status_code == 422


def test_run_acoustic_indices_media_not_found_returns_failed_item():
    mock_session.get.return_value = None

    response = client.post(
        INDICES_RUN_URL,
        json={"project_id": 1, "media_ids": [9999], "indices": [{"index_id": 1, "params": {}}]},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["queued"] == []
    assert data["failed"][0]["media_id"] == 9999


def test_run_acoustic_indices_single_index_returns_queued():
    mock_redis = AsyncMock()
    mock_redis.enqueue_task = AsyncMock()
    mock_redis.aclose = AsyncMock()

    async def override_redis():
        yield mock_redis

    app.dependency_overrides[get_task_publisher] = override_redis
    try:
        mock_session.get.return_value = mock_media
        mock_session.exec.return_value.first.side_effect = [
            IndexType(index_id=1, name="temporal_median", param=[
                {"key": "mode", "default": "fast", "value_type": "string"},
                {"key": "Nt", "default": 512, "value_type": "number"},
            ]),
        ]

        response = client.post(
            INDICES_RUN_URL,
            json={
                "project_id": 1,
                "media_ids": [1],
                "selection": {
                    "min_time": 1.5,
                    "max_time": 6.0,
                    "min_frequency": 100,
                    "max_frequency": 8000,
                },
                "channel": "right",
                "indices": [{"index_id": 1, "params": {"Nt": 1024}}],
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["queued"]) == 1
        assert data["queued"][0]["type"] == "temporal_median"
        call_kwargs = mock_redis.enqueue_task.call_args.kwargs
        assert call_kwargs["index_id"] == 1
        assert call_kwargs["index_name"] == "temporal_median"
        assert call_kwargs["params"] == {"mode": "fast", "Nt": 1024}
        assert call_kwargs["channel"] == "right"
        assert call_kwargs["min_time"] == 1.5
        assert call_kwargs["max_time"] == 6.0
        assert call_kwargs["min_frequency"] == 100
        assert call_kwargs["max_frequency"] == 8000
        assert call_kwargs["log_id"] == 777
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)


def test_preview_acoustic_index_returns_result_without_writing_log(monkeypatch):
    mock_session.get.return_value = mock_media
    mock_session.exec.return_value.first.side_effect = [
        IndexType(
            index_id=1,
            name="acoustic_evenness_index",
            param=[{"key": "max_freq", "default": 10000, "value_type": "number"}],
        ),
    ]
    monkeypatch.setattr(
        "app.services.analysis_service.AnalysisService._get_media_context",
        lambda _self, _session, _media: {"duration_s": 510, "nyquist_hz": 24000, "channel_num": 1},
    )

    with patch(
        "app.services.analysis_service.prepare_acoustic_selection",
        side_effect=lambda path, **_kwargs: Path("/tmp/media-1-selection.wav"),
    ) as mock_prepare, patch(
        "app.services.analysis_service.index_log_repository",
    ) as mock_log_repo, patch.object(
        AcousticIndexAnalyzer,
        "run_index",
        return_value={"AEI": 0.10742321535386061},
    ) as mock_run, patch.object(
        AcousticIndexAnalyzer,
        "get_version",
        return_value="1.5.2",
    ):
        response = client.post(
            INDICES_PREVIEW_URL,
            json={
                "project_id": 1,
                "media_id": 1,
                "selection": {
                    "min_time": 0,
                    "max_time": 510,
                    "min_frequency": 0,
                    "max_frequency": 24000,
                    "filter_enabled": False,
                },
                "channel": "mono",
                "index_id": 1,
                "params": {},
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["index_name"] == "acoustic_evenness_index"
    assert data["results"] == {"AEI": 0.10742321535386061}
    assert data["save_payload"]["params"] == {"Channel": "Mono"}
    assert data["save_payload"]["results"] == {"AEI": 0.10742321535386061}
    assert data["save_payload"]["min_frequency"] == "1"
    mock_prepare.assert_called_once()
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["params"] == {"max_freq": 10000}
    mock_log_repo.create_from_results.assert_not_called()


def test_create_index_log_saves_confirmed_preview_payload():
    mock_session.get.return_value = mock_media
    mock_session.exec.return_value.first.side_effect = [
        IndexType(index_id=1, name="acoustic_evenness_index", param=[]),
    ]

    with patch("app.services.analysis_service.index_log_repository") as mock_log_repo:
        mock_log_repo.reserve_log_id.return_value = 888
        mock_log_repo.create_from_results.return_value = 2

        response = client.post(
            INDEX_LOGS_URL,
            json={
                "project_id": 1,
                "media_id": 1,
                "index_id": 1,
                "version": "1.5.2",
                "min_time": "0",
                "max_time": "510",
                "min_frequency": "1",
                "max_frequency": "24000",
                "params": {"Channel": "Mono"},
                "results": {"AEI": 0.10742321535386061},
            },
        )

    assert response.status_code == 200
    assert response.json()["data"] == {"log_id": 888, "stored_count": 2}
    mock_log_repo.create_from_results.assert_called_once_with(
        mock_session,
        media_id=1,
        user_id=1,
        index_id=1,
        version="1.5.2",
        results={"AEI": 0.10742321535386061},
        params={"Channel": "Mono"},
        output_first=False,
        min_time="0",
        max_time="510",
        min_frequency="1",
        max_frequency="24000",
        log_id=888,
    )


def test_run_acoustic_analysis_reuses_acoustic_index_endpoint():
    mock_redis = AsyncMock()
    mock_redis.enqueue_task = AsyncMock()
    mock_redis.aclose = AsyncMock()

    async def override_redis():
        yield mock_redis

    app.dependency_overrides[get_task_publisher] = override_redis
    try:
        mock_session.get.return_value = mock_media

        response = client.post(
            INDICES_RUN_URL,
            json={
                "project_id": 1,
                "media_ids": [1],
                "selection": {
                    "min_time": 1.5,
                    "max_time": 6.0,
                    "min_frequency": 0,
                    "max_frequency": 8000,
                    "filter_enabled": True,
                },
                "channel": "right",
                "indices": [{"analysis_type": "max_frequency", "params": {}}],
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["queued"][0]["type"] == "max_frequency"
        call_args = mock_redis.enqueue_task.call_args
        assert call_args.args[0] == "analyze_acoustic_index"
        call_kwargs = call_args.kwargs
        assert call_kwargs["index_id"] is None
        assert call_kwargs["index_name"] == "max_frequency"
        assert call_kwargs["params"] == {}
        assert call_kwargs["min_frequency"] == 1
        assert call_kwargs["filter_enabled"] is True
        assert call_kwargs["log_id"] is None
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)


def test_run_rejects_removed_spectrogram_local_max_type(client):
    response = client.post(
        INDICES_RUN_URL,
        json={
            "project_id": 1,
            "media_ids": [1],
            "selection": {
                "min_time": 0,
                "max_time": 1,
                "min_frequency": 100,
                "max_frequency": 8000,
            },
            "indices": [{"analysis_type": "spectrogram_local_max", "params": {}}],
        },
    )

    assert response.status_code == 422


def test_run_template_matching_requires_zoomed_time_window(monkeypatch):
    mock_redis = AsyncMock()
    mock_redis.enqueue_task = AsyncMock()
    mock_redis.aclose = AsyncMock()

    async def override_redis():
        yield mock_redis

    monkeypatch.setattr(
        "app.services.analysis_service.AnalysisService._get_media_context",
        lambda _self, _session, _media: {"duration_s": 510, "nyquist_hz": 24000, "channel_num": 1},
    )
    app.dependency_overrides[get_task_publisher] = override_redis
    try:
        mock_session.get.return_value = mock_media

        response = client.post(
            INDICES_RUN_URL,
            json={
                "project_id": 1,
                "media_ids": [1],
                "selection": {
                    "min_time": 0,
                    "max_time": 510,
                    "min_frequency": 1,
                    "max_frequency": 24000,
                },
                "channel": "mono",
                "indices": [{"analysis_type": "template_matching", "params": {"peak_th": 0.5}}],
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["queued"] == []
        assert data["failed"][0]["analysis_type"] == "template_matching"
        assert data["failed"][0]["reason"] == "Please zoom in before executing."
        mock_redis.enqueue_task.assert_not_called()
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)


def test_run_template_matching_allows_zoomed_time_window(monkeypatch):
    mock_redis = AsyncMock()
    mock_redis.enqueue_task = AsyncMock()
    mock_redis.aclose = AsyncMock()

    async def override_redis():
        yield mock_redis

    monkeypatch.setattr(
        "app.services.analysis_service.AnalysisService._get_media_context",
        lambda _self, _session, _media: {"duration_s": 510, "nyquist_hz": 24000, "channel_num": 1},
    )
    app.dependency_overrides[get_task_publisher] = override_redis
    try:
        mock_session.get.return_value = mock_media

        response = client.post(
            INDICES_RUN_URL,
            json={
                "project_id": 1,
                "media_ids": [1],
                "selection": {
                    "min_time": 10,
                    "max_time": 20,
                    "min_frequency": 1,
                    "max_frequency": 24000,
                },
                "channel": "mono",
                "indices": [{"analysis_type": "template_matching", "params": {"peak_th": 0.5}}],
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["failed"] == []
        assert data["queued"][0]["type"] == "template_matching"
        call_kwargs = mock_redis.enqueue_task.call_args.kwargs
        assert call_kwargs["index_id"] is None
        assert call_kwargs["index_name"] == "template_matching"
        assert call_kwargs["min_time"] == 10
        assert call_kwargs["max_time"] == 20
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)


def test_run_acoustic_indices_valid_batch_shares_log_id():
    mock_redis = AsyncMock()
    mock_redis.enqueue_task = AsyncMock()
    mock_redis.aclose = AsyncMock()

    async def override_redis():
        yield mock_redis

    app.dependency_overrides[get_task_publisher] = override_redis
    try:
        mock_session.get.return_value = mock_media
        mock_session.exec.return_value.first.side_effect = [
            IndexType(index_id=1, name="acoustic_complexity_index", param=[]),
            IndexType(index_id=2, name="soundscape_index", param=[
                {"key": "R_compatible", "default": "soundecology", "value_type": "string"},
            ]),
        ]

        response = client.post(
            INDICES_RUN_URL,
            json={
                "project_id": 1,
                "media_ids": [1],
                "indices": [
                    {"index_id": 1, "params": {}},
                    {"index_id": 2, "params": {}},
                ],
            },
        )

        assert response.status_code == 200
        assert mock_session.execute.return_value.scalar_one.call_count == 1
        calls = mock_redis.enqueue_task.call_args_list
        assert len(calls) == 2
        assert {call.kwargs["log_id"] for call in calls} == {777}
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)


def test_run_acoustic_indices_multiple_indices_include_unknown_failure():
    mock_redis = AsyncMock()
    mock_redis.enqueue_task = AsyncMock()
    mock_redis.aclose = AsyncMock()

    async def override_redis():
        yield mock_redis

    app.dependency_overrides[get_task_publisher] = override_redis
    try:
        mock_session.get.return_value = mock_media
        mock_session.exec.return_value.first.side_effect = [
            IndexType(index_id=1, name="acoustic_complexity_index", param=[]),
            None,
        ]

        response = client.post(
            INDICES_RUN_URL,
            json={
                "project_id": 1,
                "media_ids": [1],
                "indices": [
                    {"index_id": 1, "params": {}},
                    {"index_id": 99, "params": {}},
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["queued"]) == 1
        assert data["failed"] == [{"media_id": 1, "index_id": 99, "reason": "Unknown acoustic index"}]
    finally:
        app.dependency_overrides.pop(get_task_publisher, None)


class TestAcousticIndexAnalyzer:
    """Unit tests for AcousticIndexAnalyzer using CLI subprocess mocks."""

    def test_run_index_returns_expected_keys(self):
        completed = MagicMock(returncode=0, stdout="ACI_sum?256.0\n", stderr="")
        with patch("app.ai.acoustic_indices.analyzer.run_cancellable_process", return_value=completed) as mock_run:
            analyzer = AcousticIndexAnalyzer()
            result = analyzer.run_index(
                Path("/fake/test.wav"),
                index_name="acoustic_complexity_index",
                params={},
                min_time=2,
                max_time=8,
                min_frequency=100,
                max_frequency=9000,
            )

        assert result == {"ACI_sum": "256.0"}
        cmd = mock_run.call_args.args[0]
        assert cmd[1] == str(AcousticIndexAnalyzer.GET_MAAD_SCRIPT)
        assert cmd[cmd.index("-f") + 1] == "/fake/test.wav"
        assert cmd[cmd.index("--it") + 1] == "acoustic_complexity_index"
        assert cmd[cmd.index("--mint") + 1] == "2"
        assert cmd[cmd.index("--maxt") + 1] == "8"
        assert cmd[cmd.index("--minf") + 1] == "100"
        assert cmd[cmd.index("--maxf") + 1] == "9000"
        assert "--pa" not in cmd

    def test_run_index_preserves_flac_input_path(self):
        completed = MagicMock(returncode=0, stdout="ACI_sum?256.0\n", stderr="")
        with patch("app.ai.acoustic_indices.analyzer.run_cancellable_process", return_value=completed) as mock_run:
            analyzer = AcousticIndexAnalyzer()
            analyzer.run_index(Path("/fake/test.flac"), index_name="acoustic_complexity_index")

        cmd = mock_run.call_args.args[0]
        assert cmd[cmd.index("-f") + 1] == "/fake/test.flac"

    def test_run_index_preserves_wav_input_path(self):
        completed = MagicMock(returncode=0, stdout="ACI_sum?256.0\n", stderr="")
        with patch("app.ai.acoustic_indices.analyzer.run_cancellable_process", return_value=completed) as mock_run:
            analyzer = AcousticIndexAnalyzer()
            analyzer.run_index(Path("/fake/test.wav"), index_name="acoustic_complexity_index")

        cmd = mock_run.call_args.args[0]
        assert cmd[cmd.index("-f") + 1] == "/fake/test.wav"

    def test_get_maad_loads_passed_flac_path_without_wav_suffix(self):
        with patch.object(getMaad.sf, "read", return_value=(getMaad.numpy.array([0.0, 0.1]), 48000)) as mock_read, patch.object(
            getMaad.maad.sound,
            "spectrogram",
            return_value=("Sxx", "tn", "fn", "ext"),
        ), patch.object(getMaad.maad.features, "acoustic_complexity_index", return_value=(None, None, 256.0)):
            getMaad.getMaad("/fake/test.flac", "acoustic_complexity_index", None, "left", None, None, None, None)

        mock_read.assert_called_once_with("/fake/test.flac", always_2d=False)

    def test_get_maad_keeps_wav_on_maad_loader(self):
        with patch.object(getMaad.maad.sound, "load", return_value=(getMaad.numpy.array([0.0, 0.1]), 48000)) as mock_load, patch.object(
            getMaad.maad.sound,
            "spectrogram",
            return_value=("Sxx", "tn", "fn", "ext"),
        ), patch.object(getMaad.maad.features, "acoustic_complexity_index", return_value=(None, None, 256.0)):
            getMaad.getMaad("/fake/test.wav", "acoustic_complexity_index", None, "left", None, None, None, None)

        mock_load.assert_called_once_with("/fake/test.wav", channel="left")

    def test_template_matching_loads_passed_audio_path(self):
        with patch.object(getMaad.sf, "read", return_value=(getMaad.numpy.array([0.0, 0.1]), 48000)) as mock_read, patch.object(
            getMaad.sound,
            "spectrogram",
            return_value=("Sxx", "tn", "fn", "ext"),
        ), patch.object(getMaad.maad.rois, "template_matching", return_value=("xcorrcoef", "rois")):
            getMaad.getMaad(
                "/fake/template.flac",
                "template_matching",
                "peak_th?0.5",
                "left",
                0,
                1,
                100,
                1000,
            )

        mock_read.assert_any_call("/fake/template.flac", always_2d=False)

    def test_max_frequency_uses_full_power_spectrogram_and_integer_output(self, capsys):
        with patch.object(
            getMaad.maad.sound,
            "load",
            return_value=(getMaad.numpy.array([0.0, 0.1]), 48000),
        ), patch.object(
            getMaad.maad.sound,
            "spectrogram",
            return_value=(
                getMaad.numpy.array([[1.0, 9.0], [3.0, 2.0]]),
                getMaad.numpy.array([0.25, 0.75]),
                getMaad.numpy.array([609.375, 1242.1875]),
                "ext",
            ),
        ) as mock_spectrogram:
            getMaad.getMaad(
                "/fake/test.wav",
                "max_frequency",
                None,
                "left",
                0,
                1,
                100,
                8000,
            )

        mock_spectrogram.assert_called_once()
        spectrogram_args = mock_spectrogram.call_args.args
        getMaad.numpy.testing.assert_array_equal(
            spectrogram_args[0],
            getMaad.numpy.array([0.0, 0.1]),
        )
        assert spectrogram_args[1] == 48000
        assert mock_spectrogram.call_args.kwargs == {}
        assert capsys.readouterr().out.strip() == "609"

    def test_number_of_peaks_accepts_serialized_none_params(self):
        with patch.object(getMaad.sf, "read", return_value=(getMaad.numpy.array([0.0, 0.1]), 48000)), patch.object(
            getMaad.maad.sound,
            "spectrogram",
            return_value=("Sxx", "tn", "fn", "ext"),
        ), patch.object(getMaad.maad.features, "number_of_peaks", return_value=7) as mock_number_of_peaks:
            getMaad.getMaad(
                "/fake/test.flac",
                "number_of_peaks",
                "min_peak_val?None@prominence?None",
                "mono",
                0,
                510,
                1,
                24000,
            )

        assert mock_number_of_peaks.call_args.kwargs["min_peak_val"] is None
        assert mock_number_of_peaks.call_args.kwargs["prominence"] is None

    def test_run_index_serializes_params(self):
        completed = MagicMock(returncode=0, stdout="NDSI?0.1\n", stderr="")
        with patch("app.ai.acoustic_indices.analyzer.run_cancellable_process", return_value=completed) as mock_run:
            analyzer = AcousticIndexAnalyzer()
            analyzer.run_index(
                Path("/fake/test.wav"),
                index_name="soundscape_index",
                params={"flim_bioPh": "1000,10000", "rejectDuration": None},
            )

        cmd = mock_run.call_args.args[0]
        assert cmd[cmd.index("--pa") + 1] == "flim_bioPh?1000,10000@rejectDuration?None"

    def test_run_index_uses_requested_channel(self):
        completed = MagicMock(returncode=0, stdout="med?4.0\n", stderr="")
        with patch("app.ai.acoustic_indices.analyzer.run_cancellable_process", return_value=completed) as mock_run:
            analyzer = AcousticIndexAnalyzer()
            analyzer.run_index(Path("/fake/test.wav"), index_name="temporal_median", channel="mono")

        cmd = mock_run.call_args.args[0]
        assert cmd[cmd.index("--ch") + 1] == "mono"

    def test_cli_failure_raises_runtime_error(self):
        completed = MagicMock(returncode=1, stdout="", stderr="boom")
        with patch("app.ai.acoustic_indices.analyzer.run_cancellable_process", return_value=completed):
            analyzer = AcousticIndexAnalyzer()
            with pytest.raises(RuntimeError, match="Acoustic index CLI failed"):
                analyzer.run_index(Path("/fake/test.wav"), index_name="soundscape_index", channel="right")


class TestAnalysisServiceAcousticIndex:
    """Unit tests for AnalysisService acoustic index store methods."""

    def _make_service(self):
        return AnalysisService()

    def test_analyze_and_store_acoustic_index_calls_repository(self):
        session = MagicMock()

        with patch("app.services.analysis_service.index_log_repository") as mock_log_repo, patch(
            "app.services.analysis_service.prepare_acoustic_selection",
            side_effect=lambda path, **_kwargs: path,
        ), patch.object(
            __import__("app.ai.acoustic_indices.analyzer", fromlist=["AcousticIndexAnalyzer"]).AcousticIndexAnalyzer,
            "run_index",
            return_value={"ACI_sum": 300.0},
        ), patch.object(
            __import__("app.ai.acoustic_indices.analyzer", fromlist=["AcousticIndexAnalyzer"]).AcousticIndexAnalyzer,
            "get_version",
            return_value="1.5.0",
        ):
            mock_log_repo.create_from_results.return_value = 3

            service = self._make_service()
            result = service.analyze_and_store_acoustic_index(
                session=session,
                audio_path=Path("/fake/test.wav"),
                media_id=1,
                user_id=1,
                index_type_name="temporal_median",
                index_id=1,
                params={"Nt": 512},
            )

            assert result["stored_count"] == 3
            assert "ACI_sum" in result
            mock_log_repo.create_from_results.assert_called_once()
