"""Integration tests for analysis API routes."""
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_current_user, get_task_publisher
from app.main import app
from app.models import (
    User, Role, Project, ProjectCollection, Collection, Media, MediaCollection, AudioSetting, UserPermission, Permission
)


@pytest.fixture(autouse=True)
def resolve_analysis_audio_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.analysis_service.AnalysisService._resolve_audio_path",
        lambda _self, _session, _media, media_id: f"/tmp/media-{media_id}.wav",
    )


@pytest.fixture
def setup_analysis_data(db: Session):
    # Setup Roles
    admin_role = db.exec(select(Role).where(Role.name == "Administrator")).first()
    if not admin_role:
        admin_role = Role(name="Administrator")
        db.add(admin_role)
    
    role_name = "Analysis_Tester_X_" + str(datetime.now().timestamp())
    user_role = Role(name=role_name)
    db.add(user_role)
    db.flush()
    
    admin = User(username="admin_an_z", role_id=admin_role.role_id, email="aanz@e.com", password="p", name="Admin")
    user = User(username="user_an_z", role_id=user_role.role_id, email="uanz@e.com", password="p", name="User")
    db.add_all([admin, user])
    db.flush()
    
    col = Collection(name="An Col Z", creator_id=user.user_id)
    db.add(col)
    db.flush()
    project = Project(name="An Project Z", creator_id=user.user_id, url="https://analysis.example")
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))
    db.flush()
    
    aset = AudioSetting(sampling_rate_hz=48000, bit_depth=16, channel_num=1, duration_s=10)
    db.add(aset)
    db.flush()
    
    media = Media(
        name="An Media Z", 
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
    
    # Permissions
    p_write = db.exec(select(Permission).where(Permission.name == "index_log:write")).first()
    if not p_write:
        p_write = Permission(name="index_log:write", resource_type="index_log", action="write")
        db.add(p_write)
        db.flush()
    
    return {"admin": admin, "user": user, "media": media, "collection": col, "project": project}


class TestAnalysisRoutes:
    """Tests for analysis API endpoints."""

    def test_run_analysis_all_models(self, client: TestClient, db: Session, setup_analysis_data):
        user = setup_analysis_data["user"]
        media = setup_analysis_data["media"]
        project = setup_analysis_data["project"]
        mock_redis = AsyncMock()

        async def override_redis():
            yield mock_redis

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_task_publisher] = override_redis
        try:
            response = client.post(
                "/api/v1/analysis-jobs",
                json={
                    "project_id": project.project_id,
                    "media_ids": [media.media_id],
                    "birdnet": {},
                    "batdetect": {},
                    "insects": {}
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]["queued"]) == 3
        finally:
            app.dependency_overrides = {}

    def test_run_acoustic_indices_success(self, client: TestClient, db: Session, setup_analysis_data):
        user = setup_analysis_data["user"]
        media = setup_analysis_data["media"]
        col = setup_analysis_data["collection"]
        project = setup_analysis_data["project"]

        perm = db.exec(select(Permission).where(Permission.name == "index_log:write")).first()
        db.add(UserPermission(user_id=user.user_id, project_id=project.project_id, collection_id=col.collection_id, permission_id=perm.permission_id))
        db.flush()

        mock_redis = AsyncMock()

        async def override_redis():
            yield mock_redis

        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_task_publisher] = override_redis
        try:
            response = client.post(
                "/api/v1/acoustic-index-jobs",
                json={
                    "project_id": project.project_id,
                    "media_ids": [media.media_id],
                    "indices": [
                        {"index_id": 1, "params": {}},
                        {"index_id": 2, "params": {}},
                    ],
                }
            )
            assert response.status_code == 200
        finally:
            app.dependency_overrides = {}

    def test_run_analysis_no_media_access(self, client: TestClient, db: Session, setup_analysis_data):
        other_user = User(username="other_y", role_id=setup_analysis_data["user"].role_id, email="oyy@e.com", password="p", name="O")
        db.add(other_user)
        db.flush()

        app.dependency_overrides[get_current_user] = lambda: other_user
        try:
            response = client.post(
                "/api/v1/analysis-jobs",
                json={
                    "project_id": setup_analysis_data["project"].project_id,
                    "media_ids": [setup_analysis_data["media"].media_id],
                    "birdnet": {},
                },
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["queued"] == []
            assert data["failed"][0]["media_id"] == setup_analysis_data["media"].media_id
        finally:
            app.dependency_overrides = {}

    def test_run_analysis_admin(self, client: TestClient, db: Session, setup_analysis_data):
        admin = setup_analysis_data["admin"]
        media = setup_analysis_data["media"]
        mock_redis = AsyncMock()

        async def override_redis():
            yield mock_redis

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_task_publisher] = override_redis
        try:
            response = client.post(
                "/api/v1/analysis-jobs",
                json={"project_id": setup_analysis_data["project"].project_id, "media_ids": [media.media_id], "birdnet": {}},
            )
            assert response.status_code == 200
        finally:
            app.dependency_overrides = {}

    def test_run_analysis_not_found(self, client: TestClient, setup_analysis_data):
        app.dependency_overrides[get_current_user] = lambda: setup_analysis_data["admin"]
        try:
            response = client.post(
                "/api/v1/analysis-jobs",
                json={"project_id": setup_analysis_data["project"].project_id, "media_ids": [99999], "birdnet": {}},
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["queued"] == []
            assert data["failed"][0]["media_id"] == 99999
        finally:
            app.dependency_overrides = {}
