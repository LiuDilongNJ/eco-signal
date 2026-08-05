import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api import middleware as operation_log_middleware_module
from app.core.config import settings
from app.models.operation_log import OperationLog
from app.models.user import User


@pytest.mark.skip(reason="Middleware background task uses explicit Session(engine) causing pytest transaction isolation issues")
def test_get_operation_logs_success(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # Trigger some action that creates a log
    create_data = {
        "name": "Project For Log Testing",
        "description": "Just testing",
        "public": True,
        "active": True,
    }
    r = client.post(
        f"{settings.API_V1_STR}/projects",
        headers=superuser_token_headers,
        json=create_data,
    )
    assert r.status_code == 201

    # Wait for background tasks (FastAPI TestClient runs them synchronously, so it should be immediate)
    
    import time
    time.sleep(1)
    
    # Read logs
    r = client.get(
        f"{settings.API_V1_STR}/system/operation-logs?action=create&resource_type=projects",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.json()}"
    data = r.json()
    assert data["code"] == 0
    assert isinstance(data["data"], list)
    
    logs = data["data"]
    r_all = client.get(
        f"{settings.API_V1_STR}/system/operation-logs",
        headers=superuser_token_headers,
    )
    print("ALL LOGS:", r_all.json())

    assert len(logs) > 0
    # Check if the log for the project we just created exists
    found = False
    for log in logs:
        if log["description"] == f"Created projects":
            found = True
            break
            
    assert found is True


def test_get_operation_logs_forbidden(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/system/operation-logs",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.json()}"


def test_get_operation_logs_supports_column_filters(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    admin = db.exec(select(User).where(User.username == settings.FIRST_SUPERUSER)).one()
    target = OperationLog(
        user_id=admin.user_id,
        action="update",
        resource_type="projects",
        description="Column filter target description",
        status_code=204,
    )
    other = OperationLog(
        user_id=admin.user_id,
        action="delete",
        resource_type="projects",
        description="Other operation log row",
        status_code=500,
    )
    db.add(target)
    db.add(other)
    db.commit()
    db.refresh(target)

    r = client.get(
        f"{settings.API_V1_STR}/system/operation-logs"
        f"?log_id={target.log_id}"
        f"&username={admin.username}"
        f"&description=target description"
        f"&status_code=204",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200, r.json()
    data = r.json()
    assert data["code"] == 0
    assert data["page_info"]["total"] == 1
    assert data["data"][0]["log_id"] == target.log_id
    assert data["data"][0]["status_code"] == 204


def test_get_operation_logs_supports_fuzzy_filters(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    admin = db.exec(select(User).where(User.username == settings.FIRST_SUPERUSER)).one()
    target = OperationLog(
        user_id=admin.user_id,
        action="batch-update",
        resource_type="project_members",
        description="Fuzzy operation log target",
        status_code=204,
    )
    other = OperationLog(
        user_id=admin.user_id,
        action="delete",
        resource_type="users",
        description="Other fuzzy operation log row",
        status_code=500,
    )
    db.add(target)
    db.add(other)
    db.commit()
    db.refresh(target)

    r = client.get(
        f"{settings.API_V1_STR}/system/operation-logs"
        f"?action=update"
        f"&resource_type=project"
        f"&status_code=20"
        f"&description=Fuzzy operation log target",
        headers=superuser_token_headers,
    )

    assert r.status_code == 200, r.json()
    rows = [item for item in r.json()["data"] if item["log_id"] in {target.log_id, other.log_id}]
    assert [item["log_id"] for item in rows] == [target.log_id]


def test_get_operation_logs_supports_sorting_by_username_and_status_code(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    aaa = User(
        username="aaa_log_sort",
        name="AAA Log Sort",
        email="aaa_log_sort@example.com",
        password="password123",
        active=True,
        role_id=1,
    )
    zzz = User(
        username="zzz_log_sort",
        name="ZZZ Log Sort",
        email="zzz_log_sort@example.com",
        password="password123",
        active=True,
        role_id=1,
    )
    db.add(aaa)
    db.add(zzz)
    db.commit()
    db.refresh(aaa)
    db.refresh(zzz)

    low = OperationLog(
        user_id=zzz.user_id,
        action="update",
        resource_type="projects",
        description="sorting test low",
        status_code=201,
    )
    high = OperationLog(
        user_id=aaa.user_id,
        action="update",
        resource_type="projects",
        description="sorting test high",
        status_code=500,
    )
    db.add(low)
    db.add(high)
    db.commit()
    db.refresh(low)
    db.refresh(high)

    r_user = client.get(
        f"{settings.API_V1_STR}/system/operation-logs"
        f"?description=sorting test"
        f"&order_by=username&order_dir=asc&page_size=100",
        headers=superuser_token_headers,
    )
    assert r_user.status_code == 200, r_user.json()
    user_rows = [item for item in r_user.json()["data"] if item["log_id"] in {low.log_id, high.log_id}]
    assert {item["log_id"] for item in user_rows} == {low.log_id, high.log_id}
    assert user_rows[0]["username"] == "aaa_log_sort"
    assert user_rows[1]["username"] == "zzz_log_sort"

    r_status = client.get(
        f"{settings.API_V1_STR}/system/operation-logs"
        f"?description=sorting test"
        f"&order_by=status_code&order_dir=desc&page_size=100",
        headers=superuser_token_headers,
    )
    assert r_status.status_code == 200, r_status.json()
    status_rows = [item for item in r_status.json()["data"] if item["log_id"] in {low.log_id, high.log_id}]
    assert {item["log_id"] for item in status_rows} == {low.log_id, high.log_id}
    assert status_rows[0]["status_code"] == 500
    assert status_rows[1]["status_code"] == 201


def test_get_operation_logs_defaults_to_log_id_asc(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    admin = db.exec(select(User).where(User.username == settings.FIRST_SUPERUSER)).one()
    first = OperationLog(
        user_id=admin.user_id,
        action="update",
        resource_type="projects",
        description="default log order test first",
        status_code=201,
    )
    second = OperationLog(
        user_id=admin.user_id,
        action="update",
        resource_type="projects",
        description="default log order test second",
        status_code=202,
    )
    db.add(first)
    db.add(second)
    db.commit()
    db.refresh(first)
    db.refresh(second)

    r = client.get(
        f"{settings.API_V1_STR}/system/operation-logs"
        f"?description=default log order test&page_size=100",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200, r.json()
    rows = [item for item in r.json()["data"] if item["log_id"] in {first.log_id, second.log_id}]
    assert [item["log_id"] for item in rows] == [first.log_id, second.log_id]


def test_operation_log_middleware_captures_json_payload(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_save_operation_log(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        operation_log_middleware_module,
        "_save_operation_log",
        fake_save_operation_log,
    )

    create_data = {
        "name": "Project Payload Capture",
        "description": "Payload middleware test",
        "public": True,
        "active": True,
    }
    r = client.post(
        f"{settings.API_V1_STR}/projects",
        headers=superuser_token_headers,
        json=create_data,
    )

    assert r.status_code == 201, r.json()
    assert captured["action"] == "create"
    assert captured["resource_type"] == "projects"
    assert captured["payload"] == create_data

