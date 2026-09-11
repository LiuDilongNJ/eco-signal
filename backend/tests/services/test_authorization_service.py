from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import authorization_service
from app.services.authorization_policy import (
    AUTHORIZATION_POLICIES,
    AuthorizationAction,
)


def _user(user_id: int = 7, role_code: str = "user"):
    return SimpleNamespace(
        user_id=user_id,
        role=SimpleNamespace(code=role_code, name=role_code.title()),
    )


def test_every_business_action_has_one_policy():
    assert set(AUTHORIZATION_POLICIES) == set(AuthorizationAction)


@pytest.mark.parametrize(
    ("action", "grants", "subject", "expected"),
    [
        (
            AuthorizationAction.MEDIA_RUN_AI_MODELS,
            {("media", "read"): {10}},
            authorization_service.AuthorizationSubject(frozenset({10})),
            True,
        ),
        (
            AuthorizationAction.MEDIA_RUN_ACOUSTIC,
            {("media", "read"): {10}},
            authorization_service.AuthorizationSubject(frozenset({10})),
            False,
        ),
        (
            AuthorizationAction.MEDIA_RUN_ACOUSTIC,
            {},
            authorization_service.AuthorizationSubject(frozenset({10}), uploader_id=7),
            True,
        ),
        (
            AuthorizationAction.ANNOTATION_EDIT,
            {("annotation", "write_own"): {10}},
            authorization_service.AuthorizationSubject(frozenset({10}), owner_id=7),
            True,
        ),
        (
            AuthorizationAction.ANNOTATION_EDIT,
            {("annotation", "write_own"): {10}},
            authorization_service.AuthorizationSubject(frozenset({10}), owner_id=8),
            False,
        ),
        (
            AuthorizationAction.REVIEW_EDIT,
            {("review", "write"): {10}},
            authorization_service.AuthorizationSubject(frozenset({10}), owner_id=8),
            True,
        ),
    ],
)
def test_collection_action_matrix(monkeypatch, action, grants, subject, expected):
    def get_grants(_session, _user_id, project_id, resource_type, permission_action):
        assert project_id == 3
        return list(grants.get((resource_type, permission_action), set()))

    monkeypatch.setattr(
        authorization_service.permission_repository,
        "get_accessible_project_collection_ids",
        get_grants,
    )
    authz = authorization_service.evaluator(SimpleNamespace(), _user(), 3)
    assert authz.allows(action, subject) is expected


def test_anonymous_has_no_mutating_or_analysis_capabilities():
    authz = authorization_service.evaluator(SimpleNamespace(), None, 3)
    capabilities = authz.media_capabilities({10}, uploader_id=None)
    assert not any(capabilities.model_dump().values())


def test_admin_bypasses_all_policies(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("administrator authorization must not query grants")

    monkeypatch.setattr(
        authorization_service.permission_repository,
        "get_accessible_project_collection_ids",
        unexpected,
    )
    authz = authorization_service.evaluator(SimpleNamespace(), _user(role_code="administrator"), 3)
    assert all(authz.media_capabilities({10}, uploader_id=99).model_dump().values())


def test_global_collection_scope_uses_all_project_paths(monkeypatch):
    monkeypatch.setattr(
        authorization_service.permission_repository,
        "get_accessible_collection_ids",
        lambda *_args, **_kwargs: [10],
    )
    authz = authorization_service.evaluator(SimpleNamespace(), _user(), None)
    assert authz.allows(
        AuthorizationAction.COLLECTION_EDIT,
        authorization_service.AuthorizationSubject(frozenset({10})),
    )


def test_require_uses_business_action_in_denial():
    authz = authorization_service.evaluator(SimpleNamespace(), None, 3)
    with pytest.raises(HTTPException) as exc:
        authz.require(AuthorizationAction.MEDIA_EDIT)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Permission required: media.edit"
