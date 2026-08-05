from unittest.mock import MagicMock

from app.models import User
from app.services import task_service


def test_export_tasks_forwards_scope_and_sorting(monkeypatch) -> None:
    session = MagicMock()
    current_user = User(user_id=7, username="task-export-user", role_id=1)
    calls: dict[str, object] = {}

    def fake_resolve_collection_project_id(
        received_session,
        collection_id: int,
        project_id: int,
    ) -> int:
        calls["validation"] = (received_session, collection_id, project_id)
        return project_id

    def fake_list_tasks(**kwargs):
        calls["list_tasks"] = kwargs
        return 0, []

    monkeypatch.setattr(
        task_service.permission_service,
        "resolve_collection_project_id",
        fake_resolve_collection_project_id,
    )
    monkeypatch.setattr(task_service, "list_tasks", fake_list_tasks)

    csv_data = task_service.export_tasks(
        session=session,
        current_user=current_user,
        project_id=12,
        collection_id=34,
        order_by="status",
        order_dir="desc",
    )

    assert calls["validation"] == (session, 34, 12)
    assert calls["list_tasks"] == {
        "session": session,
        "current_user": current_user,
        "skip": 0,
        "limit": 1_000_000,
        "project_id": 12,
        "collection_id": 34,
        "order_by": "status",
        "order_dir": "desc",
    }
    assert csv_data.startswith("task_id,type,media_name,media_type")
