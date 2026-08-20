from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_redis_client
from app.main import app
from app.enums import QueueStatus
from app.models.system import Queue
from app.models.user import User
from tests.utils.csv import read_csv_header


@pytest.fixture
def user2(db: Session) -> User:
    """Create a second normal user for testing isolation."""
    user = User(
        username="testuser2",
        name="Test User 2",
        email="test2@example.com",
        password="hashed_password",
        role_id=2,  # User role
        active=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user



@pytest.fixture
def _setup_queues(db: Session, normal_user_token_headers: dict, superuser_token_headers: dict, user2: User):
    """Setup some initial queues in DB for the tests."""
    normal_token = normal_user_token_headers["Authorization"].split(" ")[1]
    normal_payload = pyjwt.decode(normal_token, options={"verify_signature": False})
    normal_user_id = int(normal_payload["sub"])
    
    super_token = superuser_token_headers["Authorization"].split(" ")[1]
    super_payload = pyjwt.decode(super_token, options={"verify_signature": False})
    super_user_id = int(super_payload["sub"])

    now = datetime.now(timezone.utc)
    
    queues = [
        # Normal user queues
        Queue(user_id=normal_user_id, type="birdnet", status=2, completed=10, total=10, start_time=now - timedelta(minutes=10), stop_time=now - timedelta(minutes=5)),
        Queue(user_id=normal_user_id, type="birdnet", status=3, completed=5, total=10, error="BirdNET Crash!", start_time=now - timedelta(minutes=20), stop_time=now - timedelta(minutes=18)),
        Queue(user_id=normal_user_id, type="insects", status=0, completed=0, total=0, warning="Low confidence"),
        
        # Admin user queue
        Queue(user_id=super_user_id, type="aci", status=1, completed=2, total=100, start_time=now),
        
        # User 2 queue
        Queue(user_id=user2.user_id, type="batdetect", status=2, completed=1, total=1, start_time=now - timedelta(hours=1), stop_time=now),
    ]
    
    for q in queues:
        db.add(q)
    db.commit()


def test_list_queues_normal_user_isolation(
    client: TestClient,
    normal_user_token_headers: dict,
    _setup_queues
):
    """Test that a normal user can only see their own queues."""
    r = client.get(f"/api/v1/queues", headers=normal_user_token_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == 0
    assert data["page_info"]["total"] == 3
    # All returned queues should belong to normal_user
    for q in data["data"]:
        assert q["type"] in ["birdnet", "insects"]


def test_list_queues_admin_sees_all(
    client: TestClient,
    superuser_token_headers: dict,
    _setup_queues
):
    """Test that an admin sees all queues across the system."""
    r = client.get(f"/api/v1/queues", headers=superuser_token_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["code"] == 0
    assert data["page_info"]["total"] >= 5


def test_list_queues_admin_filter_by_user(
    client: TestClient,
    superuser_token_headers: dict,
    user2: User,
    _setup_queues
):
    """Test that an admin can filter queues by a specific user_id."""
    r = client.get(f"/api/v1/queues?user_id={user2.user_id}", headers=superuser_token_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["page_info"]["total"] == 1
    assert data["data"][0]["type"] == "batdetect"
    assert data["data"][0]["username"] == "testuser2"


def test_list_queues_filtering(
    client: TestClient,
    normal_user_token_headers: dict,
    _setup_queues,
    db: Session,
):
    """Test various filters for queue endpoint."""
    normal_token = normal_user_token_headers["Authorization"].split(" ")[1]
    normal_payload = pyjwt.decode(normal_token, options={"verify_signature": False})
    normal_user_id = int(normal_payload["sub"])

    error_queue = db.exec(
        select(Queue).where(
            Queue.user_id == normal_user_id,
            Queue.error == "BirdNET Crash!",
        )
    ).first()
    assert error_queue is not None

    # Filter by type
    r = client.get(f"/api/v1/queues?type=insects", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 1

    r = client.get(f"/api/v1/queues?type=insec", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 1

    # Filter by queue_id (exact match)
    r = client.get(f"/api/v1/queues?queue_id={error_queue.queue_id}", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 1
    assert data["data"][0]["queue_id"] == error_queue.queue_id
    
    # Filter by status 'error'
    r = client.get(f"/api/v1/queues?status=error", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 1
    assert data["data"][0]["status"] == "error"

    r = client.get(f"/api/v1/queues?status=err", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 1
    assert data["data"][0]["status"] == "error"

    # Filter by completed range via "min,max"
    r = client.get(f"/api/v1/queues?completed=5,10", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 2
    for q in data["data"]:
        assert 5 <= q["completed"] <= 10

    # Filter by total range via "min,max"
    r = client.get(f"/api/v1/queues?total=10,50", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 2

    # Filter by start_time range
    now_utc = datetime.now(timezone.utc)
    from_time = (now_utc - timedelta(minutes=15)).isoformat()
    to_time = now_utc.isoformat()
    r = client.get(f"/api/v1/queues", params={"start_time_from": from_time, "start_time_to": to_time}, headers=normal_user_token_headers)
    assert r.status_code == 200, r.json()
    data = r.json()
    assert data["page_info"]["total"] == 1
    assert data["data"][0]["completed"] == 10

    # Filter by stop_time range
    stop_from = (now_utc - timedelta(minutes=25)).isoformat()
    stop_to = (now_utc - timedelta(minutes=10)).isoformat()
    r = client.get(f"/api/v1/queues", params={"stop_time_from": stop_from, "stop_time_to": stop_to}, headers=normal_user_token_headers)
    assert r.status_code == 200, r.json()
    data = r.json()
    # The one that stopped between 25 and 10 mins ago is the error one (stopped 18 mins ago)
    assert data["page_info"]["total"] == 1
    assert data["data"][0]["error"] == "BirdNET Crash!"

    # Search error test
    r = client.get(f"/api/v1/queues?search=Crash", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 1
    assert "BirdNET Crash!" in data["data"][0]["error"]

    # Filter by error text
    r = client.get(f"/api/v1/queues?error=Crash", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 1
    assert "BirdNET Crash!" in data["data"][0]["error"]

    # Filter by warning text
    r = client.get(f"/api/v1/queues?warning=confidence", headers=normal_user_token_headers)
    data = r.json()
    assert data["page_info"]["total"] == 1
    assert data["data"][0]["warning"] == "Low confidence"


@pytest.mark.parametrize("status", ["pending", "running", "completed", "error"])
def test_list_queues_supports_public_status_values(
    client: TestClient,
    superuser_token_headers: dict,
    _setup_queues,
    status: str,
):
    """Every status exposed by the frontend maps to a stored queue status."""
    response = client.get(
        "/api/v1/queues",
        params={"status": status},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    queues = response.json()["data"]
    assert queues
    assert all(queue["status"] == status for queue in queues)


def test_warning_queue_status_is_serialized(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict,
):
    token = normal_user_token_headers["Authorization"].split(" ")[1]
    payload = pyjwt.decode(token, options={"verify_signature": False})
    queue = Queue(
        user_id=int(payload["sub"]),
        type="upload",
        status=QueueStatus.WARNING,
        completed=0,
        total=1,
        warning="duplicate.wav was skipped",
    )
    db.add(queue)
    db.commit()

    response = client.get(
        f"/api/v1/queues/{queue.queue_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "warning"
    assert response.json()["data"]["completed"] == 0
    assert response.json()["data"]["total"] == 1


def test_list_queues_sorting(
    client: TestClient,
    normal_user_token_headers: dict,
    _setup_queues
):
    """Test ordering functionality."""
    # Ascending
    r1 = client.get(f"/api/v1/queues?order_by=queue_id&order_dir=asc", headers=normal_user_token_headers)
    ids_asc = [q["queue_id"] for q in r1.json()["data"]]
    assert ids_asc == sorted(ids_asc)
    
    # Descending
    r2 = client.get(f"/api/v1/queues?order_by=queue_id&order_dir=desc", headers=normal_user_token_headers)
    ids_desc = [q["queue_id"] for q in r2.json()["data"]]
    assert ids_desc == sorted(ids_desc, reverse=True)


def test_list_queues_sorting_by_username(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
    user2: User,
    _setup_queues,
):
    """The user column is ordered by username, not user ID."""
    user2.username = "000_queue_user"
    db.add(user2)
    db.commit()
    db.refresh(user2)

    response = client.get(
        "/api/v1/queues?order_by=user&order_dir=asc&page_size=100",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    names = [queue["username"] for queue in response.json()["data"]]
    assert names[0] == "000_queue_user"


def test_get_queue_status_permission_denied(
    client: TestClient,
    normal_user_token_headers: dict,
    user2: User,
    _setup_queues,
    db: Session
):
    """Test normal users cannot fetch other users' queue detail."""
    # Intentionally get user2's queue
    queue = db.exec(select(Queue).where(Queue.user_id == user2.user_id)).first()
    
    r = client.get(f"/api/v1/queues/{queue.queue_id}", headers=normal_user_token_headers)
    assert r.status_code == 403


def test_get_queue_status_admin_can_view_any(
    client: TestClient,
    superuser_token_headers: dict,
    user2: User,
    _setup_queues,
    db: Session
):
    """Test admin users can fetch anyone's queue detail."""
    # Intentionally get user2's queue from admin account
    queue = db.exec(select(Queue).where(Queue.user_id == user2.user_id)).first()
    
    r = client.get(f"/api/v1/queues/{queue.queue_id}", headers=superuser_token_headers)
    assert r.status_code == 200
    assert r.json()["data"]["type"] == "batdetect"


def test_get_queue_status_includes_cached_analysis_message(
    client: TestClient,
    normal_user_token_headers: dict,
    _setup_queues,
    db: Session,
):
    """Queue detail fills the transient analysis completion message from Redis."""
    normal_token = normal_user_token_headers["Authorization"].split(" ")[1]
    normal_payload = pyjwt.decode(normal_token, options={"verify_signature": False})
    normal_user_id = int(normal_payload["sub"])
    queue = db.exec(
        select(Queue).where(
            Queue.user_id == normal_user_id,
            Queue.status == 2,
            Queue.type == "birdnet",
        )
    ).first()
    assert queue is not None

    class FakeRedis:
        async def eval(self, *_args: object) -> int:
            return 1

        async def get(self, key: str):
            assert key == f"analysis:queue-message:{queue.queue_id}"
            return b"BirdNET v2.4 found 10 detections. 10 tags were inserted."

    async def fake_redis_dependency():
        yield FakeRedis()

    app.dependency_overrides[get_redis_client] = fake_redis_dependency
    try:
        response = client.get(f"/api/v1/queues/{queue.queue_id}", headers=normal_user_token_headers)
    finally:
        app.dependency_overrides.pop(get_redis_client, None)

    assert response.status_code == 200
    assert response.json()["data"]["message"] == "BirdNET v2.4 found 10 detections. 10 tags were inserted."


def test_export_queues_csv(
    client: TestClient,
    normal_user_token_headers: dict,
    _setup_queues
):
    """Test exporting queues to CSV formatting."""
    r = client.get("/api/v1/queues/exports", headers=normal_user_token_headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert r.headers["content-disposition"] == (
        'attachment; filename="queue.csv"; '
        "filename*=UTF-8''queue.csv"
    )
    
    content = r.content.decode("utf-8")
    assert content.startswith("\ufeff")
    
    lines = content.strip().split("\r\n")
    if len(lines) == 1 and "\n" in lines[0]:
        lines = content.strip().split("\n")
    # Header + 3 queues for normal user
    assert len(lines) == 4
    assert read_csv_header(lines[0]) == [
        "queue_id", "type", "username", "user_id", "completed", "total",
        "status", "start_time", "stop_time", "error", "warning",
    ]
    assert any("birdnet" in line and "completed" in line for line in lines[1:])


def test_delete_queues_permission(
    client: TestClient,
    normal_user_token_headers: dict,
    superuser_token_headers: dict,
    user2: User,
    _setup_queues,
    db: Session
):
    """Test normal users can only delete their own queues."""
    # Find user2's queue id
    queue = db.exec(select(Queue).where(Queue.user_id == user2.user_id)).first()
    
    # normal user tries to delete user2's queue
    r = client.request(
        "DELETE",
        "/api/v1/queues",
        headers=normal_user_token_headers,
        json={"queue_ids": [queue.queue_id]},
    )
    assert r.status_code == 200
    assert r.json()["data"]["unavailable_ids"] == [queue.queue_id]
    
    # admin tries to delete user2's queue
    r_admin = client.request(
        "DELETE",
        "/api/v1/queues",
        headers=superuser_token_headers,
        json={"queue_ids": [queue.queue_id]},
    )
    assert r_admin.status_code == 200
    assert r_admin.json()["data"]["deleted_ids"] == [queue.queue_id]
    assert db.get(Queue, queue.queue_id) is None


def test_delete_queues_removes_pending_and_terminal_records(
    client: TestClient,
    normal_user_token_headers: dict,
    _setup_queues,
    db: Session
):
    """Pending and terminal queues are deleted immediately."""
    import jwt as pyjwt
    normal_token = normal_user_token_headers["Authorization"].split(" ")[1]
    normal_payload = pyjwt.decode(normal_token, options={"verify_signature": False})
    user_id = int(normal_payload["sub"])
    
    queues = db.exec(select(Queue).where(Queue.user_id == user_id)).all()
    q_pending = next(q for q in queues if q.status == 0)
    q_completed = next(q for q in queues if q.status == 2)
    
    r = client.request(
        "DELETE",
        "/api/v1/queues",
        headers=normal_user_token_headers,
        json={"queue_ids": [q_pending.queue_id, q_completed.queue_id]},
    )
    assert r.status_code == 200
    assert r.json()["data"] == {
        "deleted_ids": [q_pending.queue_id, q_completed.queue_id],
        "cancelling_ids": [],
        "unavailable_ids": [],
    }
    assert r.json()["message"] == "Tasks deleted successfully"
    assert db.get(Queue, q_pending.queue_id) is None
    assert db.get(Queue, q_completed.queue_id) is None


def test_cancel_running_queue_is_idempotent(
    client: TestClient,
    normal_user_token_headers: dict,
    db: Session,
):
    normal_token = normal_user_token_headers["Authorization"].split(" ")[1]
    user_id = int(pyjwt.decode(normal_token, options={"verify_signature": False})["sub"])
    queue = Queue(user_id=user_id, type="birdnet", status=1, completed=0, total=1)
    db.add(queue)
    db.commit()
    db.refresh(queue)

    response = client.request(
        "DELETE",
        "/api/v1/queues",
        headers=normal_user_token_headers,
        json={"queue_ids": [queue.queue_id]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["cancelling_ids"] == [queue.queue_id]

    repeated = client.request(
        "DELETE",
        "/api/v1/queues",
        headers=normal_user_token_headers,
        json={"queue_ids": [queue.queue_id]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"]["cancelling_ids"] == [queue.queue_id]

    db.refresh(queue)
    assert queue.status == 3
    assert queue.error == "Task cancelled by user"
    assert queue.stop_time is None
