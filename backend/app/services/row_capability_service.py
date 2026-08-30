from sqlmodel import Session, select

from app.models.media import MediaCollection
from app.models.project import ProjectCollection
from app.models.user import User
from app.repositories import permission_repository
from app.schemas.capability import RowCapabilities
from app.services import permission_service


def project_collection_ids(
    session: Session,
    user: User | None,
    project_id: int | None,
    resource_type: str,
    action: str = "write",
) -> set[int]:
    """Return project-local collection IDs granted for one operation."""
    if user is None or project_id is None:
        return set()
    if permission_service.is_admin(user):
        return set(permission_repository.get_project_collection_ids(session, project_id))
    return set(
        permission_repository.get_accessible_project_collection_ids(
            session,
            user.user_id,
            project_id,
            resource_type,
            action,
        )
    )


def linked_capabilities(
    linked_collection_ids: set[int],
    *,
    writable_collection_ids: set[int],
    assignable_collection_ids: set[int] | None = None,
    run_analysis: bool | None = None,
) -> RowCapabilities:
    writable = bool(linked_collection_ids & writable_collection_ids)
    assignable = bool(
        linked_collection_ids
        & (assignable_collection_ids if assignable_collection_ids is not None else writable_collection_ids)
    )
    return RowCapabilities(
        edit=writable,
        delete=writable,
        link=writable,
        assign=assignable,
        run_analysis=writable if run_analysis is None else run_analysis,
    )


def media_collection_map(
    session: Session,
    media_ids: set[int],
    project_id: int | None,
) -> dict[int, set[int]]:
    """Load project-local collection links for a page of media records."""
    if not media_ids or project_id is None:
        return {}
    rows = session.exec(
        select(MediaCollection.media_id, MediaCollection.collection_id)
        .join(
            ProjectCollection,
            ProjectCollection.collection_id == MediaCollection.collection_id,
        )
        .where(
            MediaCollection.media_id.in_(media_ids),
            ProjectCollection.project_id == project_id,
        )
        .distinct()
    ).all()
    result: dict[int, set[int]] = {}
    for media_id, collection_id in rows:
        result.setdefault(media_id, set()).add(collection_id)
    return result
