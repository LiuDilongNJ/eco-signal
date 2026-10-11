from unittest.mock import MagicMock

from app.models import User
from app.models.annotation import Annotation
from app.repositories.task_repository import TaskNavigationAccess
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
        task_service.access_scope_service,
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


def test_navigation_uses_current_coordinates_after_task_review(monkeypatch):
    session = MagicMock()
    annotation = Annotation(annotation_id=9, media_id=4, creator_id=7, min_x=8, max_x=9, min_y=0, max_y=1)
    access = TaskNavigationAccess(project_id=2, user_id=7)
    query = MagicMock(return_value=(None, {"task_id": 12, "project_id": 2, "collection_id": 3,
                                           "media_id": 5, "media_type": "photo", "annotation_id": 11}))
    monkeypatch.setattr(task_service.task_repository, "get_navigation_items", query)
    result = task_service.get_navigation_items(session, access, 4, annotation)
    assert result.previous is None
    assert result.next.annotation_id == 11
    query.assert_called_once_with(session, access, 4, annotation)
