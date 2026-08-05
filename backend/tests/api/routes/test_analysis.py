"""Tests for AI analysis API endpoints."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_task_publisher
from app.main import app
from app.models.media import AudioSetting, Media
from app.models.system import Queue
from app.models.user import User, Role

# Shared fixtures

# Build an admin role object so permission_service.is_admin() resolves correctly
mock_admin_role = Role(role_id=1, name="Administrator")

mock_user = User(
    user_id=1,
    username="testuser",
    name="Test User",
    email="test@example.com",
    password="hashed",
    active=True,
    role_id=1,
)
mock_user.role = mock_admin_role

mock_session = MagicMock()


def _mock_refresh(obj):
    """Simulate DB autoincrement on refresh."""
    if isinstance(obj, Queue) and obj.queue_id is None:
        obj.queue_id = 1


mock_session.refresh.side_effect = _mock_refresh
mock_session.exec.return_value.all.return_value = []
mock_session.exec.return_value.first.return_value = None


def override_get_db():
    try:
        yield mock_session
    finally:
        pass


def override_get_current_user():
    return mock_user


@pytest.fixture(autouse=True)
def reset_mocks(monkeypatch: pytest.MonkeyPatch):
    """Reset session mock state before each test."""
    mock_session.reset_mock()
    mock_session.refresh.side_effect = _mock_refresh
    mock_session.exec.return_value.all.return_value = []
    mock_session.exec.return_value.first.return_value = None
    monkeypatch.setattr(
        "app.services.analysis_service.AnalysisService._resolve_audio_path",
        lambda _self, _session, _media, media_id: f"/tmp/media-{media_id}.wav",
    )


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_redis():
    pool = AsyncMock()
    pool.enqueue_task = AsyncMock()
    pool.close = AsyncMock()
    pool.aclose = AsyncMock()

    async def override_get_task_publisher():
        yield pool

    app.dependency_overrides[get_task_publisher] = override_get_task_publisher
    yield pool
    app.dependency_overrides.pop(get_task_publisher, None)


def _make_media(uploader_id: int = 1) -> Media:
    """Create a mock Media object."""
    m = Media(
        media_id=10,
        uploader_id=uploader_id,
        media_type="audio",
        filename="test.wav",
        directory=1,
        audio_setting_id=1,
    )
    m.audio_setting = AudioSetting(audio_setting_id=1, sampling_rate_hz=48000, duration_s=10)
    return m


# POST /analysis-jobs tests

class TestRunAnalysis:
    """Tests for POST /api/v1/analysis-jobs."""

    def _post(self, client, payload: dict):
        payload = {"project_id": 1, **payload}
        return client.post("/api/v1/analysis-jobs", json=payload)

    def test_birdnet_only(self, client, mock_redis):
        """Submitting only BirdNET queues exactly one task."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "birdnet": {
                "min_conf": 0.5,
                "overlap": 0.0,
                "sensitivity": 1.0,
                "sf_thresh": 0.0001,
                "max_freq": 15000,
                "locale": "zh",
                "top_n": 3,
            },
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["queued"]) == 1
        assert data["queued"][0]["status"] == "pending"
        assert len(data["failed"]) == 0
        assert mock_redis.enqueue_task.call_count == 1
        assert mock_redis.enqueue_task.call_args[0][0] == "analyze_birdnet"
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert "birdnet_version" not in kwargs
        assert kwargs["sf_thresh"] == 0.0001
        assert kwargs["locale"] == "zh"
        assert kwargs["min_frequency"] == 1
        assert kwargs["top_n"] == 3
        assert "batch_size" not in kwargs

    @pytest.mark.parametrize(
        "removed_field",
        ["batch_size", "birdnet_version", "min_confidence", "min_frequency", "max_frequency"],
    )
    def test_birdnet_rejects_removed_parameters(self, client, removed_field):
        resp = self._post(client, {"media_ids": [10], "birdnet": {removed_field: 1}})
        assert resp.status_code == 422

    def test_birdnet_custom_parameters_are_forwarded(self, client, mock_redis):
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "birdnet": {"min_freq": 500, "top_n": 3}}
        resp = self._post(client, payload)
        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["min_frequency"] == 500
        assert kwargs["top_n"] == 3

    def test_batdetect_only(self, client, mock_redis):
        """Submitting only BatDetect2 queues exactly one task."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "batdetect": {
                "detection_threshold": 0.5,
            },
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["queued"]) == 1
        assert len(data["failed"]) == 0
        assert mock_redis.enqueue_task.call_args[0][0] == "analyze_batdetect"
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["detection_threshold"] == 0.5
        assert kwargs["chunk_size"] == 2

    def test_batdetect_custom_parameters_are_forwarded(self, client, mock_redis):
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "batdetect": {
                "chunk_size": 5,
            },
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["chunk_size"] == 5

    def test_batdetect_rejects_removed_nms_merge(self, client):
        resp = self._post(client, {
            "media_ids": [10],
            "batdetect": {"nms_merge": False},
        })
        assert resp.status_code == 422

    def test_both_models(self, client, mock_redis):
        """Submitting both models queues two tasks."""
        mock_session.get.return_value = _make_media()

        # Queue refresh needs to return incrementing IDs
        call_count = {"n": 0}
        def multi_refresh(obj):
            if isinstance(obj, Queue) and obj.queue_id is None:
                call_count["n"] += 1
                obj.queue_id = call_count["n"]
        mock_session.refresh.side_effect = multi_refresh

        payload = {
            "media_ids": [10],
            "birdnet": {"min_conf": 0.5},
            "batdetect": {"detection_threshold": 0.4},
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["queued"]) == 2
        assert mock_redis.enqueue_task.call_count == 2

    def test_no_model_selected_returns_400(self, client, mock_redis):
        """If no model is selected, return 400."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10]}
        resp = self._post(client, payload)
        assert resp.status_code == 400

    def test_invalid_media_id_returns_failed_item(self, client, mock_redis):
        """If a media ID does not exist, return it in failed items."""
        mock_session.get.return_value = None  # media not found
        payload = {"media_ids": [9999], "birdnet": {}}
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["queued"] == []
        assert data["failed"][0]["media_id"] == 9999

    def test_birdnet_confidence_out_of_range_returns_422(self, client, mock_redis):
        """min_conf must be between 0 and 1."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "birdnet": {"min_conf": 2.0},  # invalid
        }
        resp = self._post(client, payload)
        assert resp.status_code == 422

    def test_birdnet_overlap_out_of_range_returns_422(self, client, mock_redis):
        """overlap must be <= 2.9."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "birdnet": {"overlap": 3.5}}
        resp = self._post(client, payload)
        assert resp.status_code == 422

    def test_birdnet_sensitivity_out_of_range_returns_422(self, client, mock_redis):
        """sensitivity must be in [0.5, 1.5]."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "birdnet": {"sensitivity": 2.0}}
        resp = self._post(client, payload)
        assert resp.status_code == 422

    def test_birdnet_max_frequency_out_of_range_returns_422(self, client, mock_redis):
        """max_freq must be non-negative."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "birdnet": {"max_freq": -1}}
        resp = self._post(client, payload)
        assert resp.status_code == 422

    def test_batdetect_threshold_out_of_range_returns_422(self, client, mock_redis):
        """detection_threshold must be between 0 and 1."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "batdetect": {"detection_threshold": 1.5}}
        resp = self._post(client, payload)
        assert resp.status_code == 422

    def test_merge_params_passed_to_birdnet(self, client, mock_redis):
        """Merge parameters are forwarded to the BirdNET enqueue call."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "birdnet": {"min_conf": 0.5},
            "merge": {"is_merged": True, "max_gap": 2.5, "keep_merged": True},
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["merge_enabled"] is True
        assert kwargs["merge_max_gap"] == 2.5
        assert kwargs["merge_keep_only"] is True

    @pytest.mark.parametrize("unsupported_field", ["enabled", "keep_merged_only"])
    def test_merge_rejects_unsupported_parameters(self, client, unsupported_field):
        payload = {
            "media_ids": [10],
            "birdnet": {},
            "merge": {unsupported_field: True},
        }

        resp = self._post(client, payload)

        assert resp.status_code == 422

    def test_birdnet_week_is_resolved_from_media_datetime(self, client, mock_redis):
        """BirdNET week should come from media metadata, not the request body."""
        media = _make_media()
        media.date_time = datetime(2026, 5, 20, 12, 0, 0)
        mock_session.get.return_value = media
        payload = {
            "media_ids": [10],
            "birdnet": {"min_conf": 0.5},
        }
        resp = self._post(client, payload)

        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["week"] == 21

    def test_birdnet_rejects_request_geo_time_overrides(self, client, mock_redis):
        """lat, lon, and week are backend-derived media metadata."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "birdnet": {"min_conf": 0.5, "lat": 11.1, "lon": 22.2, "week": 10},
        }
        resp = self._post(client, payload)

        assert resp.status_code == 422

    @patch("app.services.analysis_service.site_repository")
    def test_birdnet_falls_back_to_site_manual_coordinates(self, mock_site_repo, client, mock_redis):
        """When request coordinates are absent, BirdNET should use site cached coordinates."""
        media = _make_media()
        media.site_id = 7
        media.date_time = None
        mock_session.get.return_value = media
        mock_site_repo.resolve_analysis_coordinates.return_value = (120.25, 30.75)
        payload = {"media_ids": [10], "birdnet": {"min_conf": 0.5}}

        resp = self._post(client, payload)

        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["lat"] == 30.75
        assert kwargs["lon"] == 120.25

    @patch("app.services.analysis_service.site_repository")
    def test_birdnet_missing_site_coordinates_disables_geo_filter(self, mock_site_repo, client, mock_redis):
        """If no request or site coordinates exist, BirdNET should skip geo filtering."""
        media = _make_media()
        media.site_id = 7
        media.date_time = None
        mock_session.get.return_value = media
        mock_site_repo.resolve_analysis_coordinates.return_value = (None, None)
        payload = {"media_ids": [10], "birdnet": {"min_conf": 0.5}}

        resp = self._post(client, payload)

        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["lat"] is None
        assert kwargs["lon"] is None

    def test_birdnet_max_frequency_defaults_to_media_nyquist(self, client, mock_redis):
        """BirdNET annotation bounds default to the media Nyquist frequency."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "birdnet": {
                "min_conf": 0.5,
            },
        }
        resp = self._post(client, payload)

        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["max_frequency"] == 24000

    def test_birdnet_max_frequency_allows_values_above_15000_within_nyquist(self, client, mock_redis):
        """BirdNET annotation bounds may exceed 15000 Hz when the media supports it."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "birdnet": {
                "min_conf": 0.5,
                "max_freq": 22050,
            },
        }
        resp = self._post(client, payload)

        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["max_frequency"] == 22050

    def test_birdnet_inverted_frequency_range_returns_422(self, client, mock_redis):
        """BirdNET minimum frequency must be lower than maximum frequency."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "birdnet": {
                "min_freq": 1000,
                "max_freq": 1000,
            },
        }
        resp = self._post(client, payload)

        assert resp.status_code == 422
        mock_redis.enqueue_task.assert_not_called()

    def test_birdnet_frequency_above_media_nyquist_returns_422(self, client, mock_redis):
        """BirdNET frequency bounds cannot exceed the media Nyquist frequency."""
        media = _make_media()
        media.audio_setting.sampling_rate_hz = 16000
        mock_session.get.return_value = media
        payload = {
            "media_ids": [10],
            "birdnet": {
                "max_freq": 10000,
            },
        }

        resp = self._post(client, payload)

        assert resp.status_code == 422
        mock_redis.enqueue_task.assert_not_called()

    def test_redis_failure_goes_to_failed(self, client, mock_redis):
        """When Redis enqueue fails, the model is listed in failed."""
        mock_session.get.return_value = _make_media()
        mock_redis.enqueue_task.side_effect = Exception("RabbitMQ connection error")
        payload = {"media_ids": [10], "birdnet": {"min_conf": 0.5}}
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["queued"]) == 0
        assert len(data["failed"]) == 1
        assert data["failed"][0]["model"] == "birdnet"


# insects-specific route tests

class TestInsectsRoute:
    """Tests for insects-base-cnn10-96k-t specific route behavior."""

    def _post(self, client, payload: dict):
        payload = {"project_id": 1, **payload}
        return client.post("/api/v1/analysis-jobs", json=payload)

    def test_insects_only_queues_one_task(self, client, mock_redis):
        """Submitting only insects model queues exactly one task."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "insects": {
                "window_size": 4.0,
                "stride_length": 4.0,
            },
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["queued"]) == 1
        assert data["queued"][0]["status"] == "pending"
        assert len(data["failed"]) == 0
        assert mock_redis.enqueue_task.call_count == 1
        assert mock_redis.enqueue_task.call_args[0][0] == "analyze_insects"

    def test_insects_params_forwarded_to_redis(self, client, mock_redis):
        """window_size, stride_length and max_freq are forwarded as kwargs to publisher.enqueue_task."""
        mock_session.get.return_value = _make_media()
        payload = {
            "media_ids": [10],
            "insects": {"window_size": 6.0, "stride_length": 3.0, "max_freq": 22050},
            "merge": {"is_merged": True, "max_gap": 2.0, "keep_merged": False},
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["window_size"] == 6.0
        assert kwargs["stride_length"] == 3.0
        assert kwargs["max_freq"] == 22050
        assert kwargs["merge_enabled"] is True
        assert kwargs["merge_max_gap"] == 2.0
        assert kwargs["merge_keep_only"] is False

    def test_insects_max_freq_default_uses_media_nyquist(self, client, mock_redis):
        """When max_freq is omitted, media Nyquist is forwarded to the worker."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "insects": {"window_size": 4.0, "stride_length": 4.0}}
        resp = self._post(client, payload)
        assert resp.status_code == 200
        kwargs = mock_redis.enqueue_task.call_args[1]
        assert kwargs["max_freq"] == 24000

    def test_all_three_models_submit_three_tasks(self, client, mock_redis):
        """Submitting birdnet + batdetect + insects queues three separate tasks."""
        mock_session.get.return_value = _make_media()

        call_count = {"n": 0}
        def multi_refresh(obj):
            if isinstance(obj, Queue) and obj.queue_id is None:
                call_count["n"] += 1
                obj.queue_id = call_count["n"]
        mock_session.refresh.side_effect = multi_refresh

        payload = {
            "media_ids": [10],
            "birdnet": {"min_conf": 0.5},
            "batdetect": {"detection_threshold": 0.4},
            "insects": {"window_size": 4.0, "stride_length": 4.0},
        }
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["queued"]) == 3
        assert mock_redis.enqueue_task.call_count == 3

        task_names = [call.args[0] for call in mock_redis.enqueue_task.call_args_list]
        assert "analyze_birdnet" in task_names
        assert "analyze_batdetect" in task_names
        assert "analyze_insects" in task_names

    def test_insects_message_in_response(self, client, mock_redis):
        """Response message for insects task mentions the model name."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "insects": {}}
        resp = self._post(client, payload)
        assert resp.status_code == 200
        queued = resp.json()["data"]["queued"]
        assert len(queued) == 1
        assert "insects" in queued[0]["message"].lower()

    def test_insects_window_size_out_of_range_returns_422(self, client, mock_redis):
        """window_size must be >= 0.5."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "insects": {"window_size": 0.1}}
        resp = self._post(client, payload)
        assert resp.status_code == 422

    def test_insects_stride_length_out_of_range_returns_422(self, client, mock_redis):
        """stride_length must be <= 30."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "insects": {"stride_length": 50.0}}
        resp = self._post(client, payload)
        assert resp.status_code == 422

    def test_insects_rejects_removed_stride_size(self, client, mock_redis):
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10], "insects": {"stride_size": 4.0}}
        resp = self._post(client, payload)
        assert resp.status_code == 422

    def test_insects_redis_failure_goes_to_failed(self, client, mock_redis):
        """When Redis enqueue fails for insects, it is listed in failed."""
        mock_session.get.return_value = _make_media()
        mock_redis.enqueue_task.side_effect = Exception("RabbitMQ down")
        payload = {"media_ids": [10], "insects": {}}
        resp = self._post(client, payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["queued"]) == 0
        assert len(data["failed"]) == 1
        assert data["failed"][0]["model"] == "insects"

    def test_no_model_still_returns_400_with_insects_in_message(self, client, mock_redis):
        """Error message now includes 'insects' as a valid model choice."""
        mock_session.get.return_value = _make_media()
        payload = {"media_ids": [10]}
        resp = self._post(client, payload)
        assert resp.status_code == 400
        body = resp.json()
        # FastAPI may return the detail either in 'detail' or 'message' field
        detail_str = str(body.get("detail") or body.get("message") or "")
        assert "insects" in detail_str.lower()

"""Integration scenarios for analysis API routes."""
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_task_publisher
from app.main import app
from app.models import (
    AudioSetting,
    Collection,
    Media,
    MediaCollection,
    Permission,
    Project,
    ProjectCollection,
    Role,
    User,
    UserPermission,
)


@pytest.fixture(autouse=True)
def resolve_analysis_audio_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.analysis_service.AnalysisService._resolve_audio_path",
        lambda _self, _session, _media, media_id: f"/tmp/media-{media_id}.wav",
    )


@pytest.fixture
def setup_analysis_scenario_data(db: Session):
    admin_role = db.exec(select(Role).where(Role.name == "Administrator")).first()
    if not admin_role:
        admin_role = Role(name="Administrator")
        db.add(admin_role)

    role_name = "Analysis_Tester_Scenario_" + str(datetime.now().timestamp())
    user_role = Role(name=role_name)
    db.add(user_role)
    db.flush()

    admin = User(username="admin_analysis_scn", role_id=admin_role.role_id, email="analysis-admin@example.com", password="p", name="Admin")
    user = User(username="user_analysis_scn", role_id=user_role.role_id, email="analysis-user@example.com", password="p", name="User")
    db.add_all([admin, user])
    db.flush()

    col = Collection(name="An Col F Z", creator_id=user.user_id)
    db.add(col)
    db.flush()
    project = Project(name="An Project F Z", creator_id=user.user_id, url="https://analysis-extra.example")
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))
    db.flush()

    aset = AudioSetting(sampling_rate_hz=48000, bit_depth=16, channel_num=1, duration_s=10)
    db.add(aset)
    db.flush()

    media = Media(
        name="An Media F Z",
        uploader_id=user.user_id,
        creator_id=user.user_id,
        media_type="audio",
        audio_setting_id=aset.audio_setting_id,
        filename="rec.wav",
        directory=1
    )
    db.add(media)
    db.flush()
    db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
    db.flush()

    return {"admin": admin, "user": user, "media": media, "collection": col, "project": project}


@pytest.fixture
def analysis_scenario_client(db: Session):
    """Use the transaction-backed session for integration scenarios in this module."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestAnalysisRouteScenarios:
    """Integration scenarios that exercise database-backed authorization."""

    def test_run_analysis_redis_error(self, analysis_scenario_client: TestClient, db: Session, setup_analysis_scenario_data):
        user = setup_analysis_scenario_data["user"]
        media = setup_analysis_scenario_data["media"]

        mock_redis = AsyncMock()
        mock_redis.enqueue_task.side_effect = Exception("RabbitMQ Down")

        async def override_redis():
            yield mock_redis

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_task_publisher] = override_redis
        try:
            response = analysis_scenario_client.post(
                "/api/v1/analysis-jobs",
                json={"project_id": setup_analysis_scenario_data["project"].project_id, "media_ids": [media.media_id], "birdnet": {}}
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]["failed"]) == 1
            assert "RabbitMQ Down" in data["data"]["failed"][0]["reason"]
        finally:
            app.dependency_overrides = {}

    def test_run_acoustic_indices_no_permission(self, analysis_scenario_client: TestClient, db: Session, setup_analysis_scenario_data):
        u2 = User(username="u_np_z", role_id=setup_analysis_scenario_data["user"].role_id, email="unpz@e.com", password="p", name="U")
        db.add(u2)
        db.flush()

        col = setup_analysis_scenario_data["collection"]
        media = setup_analysis_scenario_data["media"]
        project = setup_analysis_scenario_data["project"]

        perm_read = db.exec(select(Permission).where(Permission.name == "audio:read")).first()
        if not perm_read:
            perm_read = Permission(name="audio:read", resource_type="audio", action="read")
            db.add(perm_read)
            db.flush()
        db.add(UserPermission(user_id=u2.user_id, project_id=project.project_id, collection_id=col.collection_id, permission_id=perm_read.permission_id))
        db.flush()

        app.dependency_overrides[get_current_user] = lambda: u2
        try:
            response = analysis_scenario_client.post(
                "/api/v1/acoustic-index-jobs",
                json={
                    "project_id": project.project_id,
                    "media_ids": [media.media_id],
                    "indices": [{"index_id": 1, "params": {}}],
                }
            )
            assert response.status_code == 200
            failed = response.json()["data"]["failed"]
            assert failed[0]["media_id"] == media.media_id
            assert "collection:write permission required" in failed[0]["reason"]
        finally:
            app.dependency_overrides = {}

    def test_run_analysis_invalid_params(self, analysis_scenario_client: TestClient, db: Session, setup_analysis_scenario_data):
        user = setup_analysis_scenario_data["user"]
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            response = analysis_scenario_client.post(
                "/api/v1/analysis-jobs",
                json={
                    "project_id": setup_analysis_scenario_data["project"].project_id,
                    "media_ids": [setup_analysis_scenario_data["media"].media_id],
                },
            )
            assert response.status_code == 400

            response = analysis_scenario_client.post(
                "/api/v1/acoustic-index-jobs",
                json={
                    "project_id": setup_analysis_scenario_data["project"].project_id,
                    "media_ids": [setup_analysis_scenario_data["media"].media_id],
                    "indices": [],
                },
            )
            assert response.status_code == 422
        finally:
            app.dependency_overrides = {}

    def test_run_acoustic_indices_redis_error(self, analysis_scenario_client: TestClient, db: Session, setup_analysis_scenario_data):
        user = setup_analysis_scenario_data["user"]
        media = setup_analysis_scenario_data["media"]
        mock_redis = AsyncMock()
        mock_redis.enqueue_task.side_effect = Exception("RabbitMQ Error Index")

        async def override_redis():
            yield mock_redis

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_task_publisher] = override_redis
        try:
            response = analysis_scenario_client.post(
                "/api/v1/acoustic-index-jobs",
                json={
                    "project_id": setup_analysis_scenario_data["project"].project_id,
                    "media_ids": [media.media_id],
                    "indices": [
                        {"index_id": 1, "params": {}},
                        {"index_id": 2, "params": {}},
                    ],
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]["failed"]) == 2
        finally:
            app.dependency_overrides = {}
