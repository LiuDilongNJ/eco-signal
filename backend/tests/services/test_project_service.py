"""Tests for project_service name uniqueness conflict handling."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.services import project_service


class DummyProjectIn:
    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self):
        return self._payload.copy()


class DummyProjectUpdateIn:
    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self, *, exclude_unset: bool = False):
        return self._payload.copy()


class DummyUser:
    def __init__(self, user_id: int = 1):
        self.user_id = user_id


def test_create_project_integrityerror_converted_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent unique-index collision should be converted to HTTP 409."""
    session = Mock()
    session.commit.side_effect = IntegrityError("INSERT", {}, Exception("duplicate key"))

    monkeypatch.setattr(project_service.project_repository, "get_by_normalized_name", lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as exc_info:
        project_service.create_project(
            session,
            DummyProjectIn({"name": "New Project", "url": "https://example.com"}),
            DummyUser(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Project with same name already exists"
    session.rollback.assert_called_once()


def test_update_project_integrityerror_converted_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent unique-index collision during update should be converted to HTTP 409."""
    session = Mock()
    fake_project = Mock()

    monkeypatch.setattr(project_service.project_repository, "get", lambda *args, **kwargs: fake_project)
    monkeypatch.setattr(project_service.project_repository, "get_by_normalized_name", lambda *args, **kwargs: None)

    def _raise_integrity(*args, **kwargs):
        raise IntegrityError("UPDATE", {}, Exception("duplicate key"))

    monkeypatch.setattr(project_service.project_repository, "update", _raise_integrity)

    with pytest.raises(HTTPException) as exc_info:
        project_service.update_project(
            session,
            1,
            DummyProjectUpdateIn({"name": "Changed"}),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Project with same name already exists"
    session.rollback.assert_called_once()
