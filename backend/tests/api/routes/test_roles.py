"""角色路由测试。 / Roles routes tests."""
from fastapi.testclient import TestClient

from app.core.config import settings


def test_list_access_roles(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    """测试获取系统访问角色及权限列表。 / Test listing access roles and their permissions."""
    response = client.get(
        f"{settings.API_V1_STR}/roles",
        params={"kind": "access"},
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    roles = data["data"]
    role_map = {r["code"]: r for r in roles}

    # Verify standard access roles exist
    for expected_code in ("viewer", "annotator", "reviewer", "manager", "custom"):
        assert expected_code in role_map, f"Missing access role {expected_code}"

    # Verify Annotator permissions match specification (read media/sites, write own annotations/reviews)
    annotator = role_map["annotator"]
    assert "project:read" in annotator["project_permissions"]
    assert "media:read" in annotator["project_permissions"]
    assert "site:read" in annotator["project_permissions"]
    assert "annotation:read" in annotator["project_permissions"]
    assert "annotation:write_own" in annotator["project_permissions"]
    assert "review:read" in annotator["project_permissions"]
    assert "review:write_own" in annotator["project_permissions"]

    assert "collection:read" in annotator["collection_permissions"]
    assert "media:read" in annotator["collection_permissions"]
    assert "site:read" in annotator["collection_permissions"]
    assert "annotation:read" in annotator["collection_permissions"]
    assert "annotation:write_own" in annotator["collection_permissions"]
    assert "review:read" in annotator["collection_permissions"]
    assert "review:write_own" in annotator["collection_permissions"]

    # Verify Reviewer permissions
    reviewer = role_map["reviewer"]
    assert "review:write_own" in reviewer["project_permissions"]
    assert "annotation:read" in reviewer["project_permissions"]

    # Verify Manager permissions
    manager = role_map["manager"]
    assert manager["project_permissions"] == ["project:write"]
    assert manager["collection_permissions"] == ["collection:write"]


def test_list_access_roles_invalid_kind(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    """测试非 access 类型的 kind 返回空列表。 / Test non-access kind returns empty list."""
    response = client.get(
        f"{settings.API_V1_STR}/roles",
        params={"kind": "other"},
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert data["data"] == []


def test_list_access_roles_unauthenticated(client: TestClient) -> None:
    """测试未登录用户无法获取角色列表。 / Test unauthenticated user cannot access roles."""
    response = client.get(f"{settings.API_V1_STR}/roles", params={"kind": "access"})
    assert response.status_code == 401
