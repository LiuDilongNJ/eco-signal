from sqlmodel import Session, select

from app.models.project import ProjectCollection
from app.repositories.permission_repository import permission_repository


def resolve_project_collection_scope(
    session: Session,
    *,
    project_id: int,
    collection_id: int | None = None,
    user_id: int | None = None,
    resource_type: str = "audio",
    action: str = "read",
    include_public: bool = True,
    is_admin: bool = False,
) -> list[int]:
    """Resolve collection IDs constrained to a single project scope."""
    project_collection_ids = list(
        session.exec(
            select(ProjectCollection.collection_id).where(
                ProjectCollection.project_id == project_id
            )
        ).all()
    )
    if not project_collection_ids:
        return []

    project_collection_set = set(project_collection_ids)
    if collection_id is not None:
        if collection_id not in project_collection_set:
            return []
        project_collection_set = {collection_id}

    if is_admin:
        return sorted(project_collection_set)

    allowed_ids: set[int] = set()
    if user_id is not None:
        allowed_ids.update(
            permission_repository.get_accessible_project_collection_ids(
                session,
                user_id,
                project_id=project_id,
                resource_type=resource_type,
                action=action,
            )
        )

    if include_public and action == "read":
        public_ids = [
            public_collection_id
            for _, public_collection_id in permission_repository.get_public_collection_scopes(
                session,
                project_id=project_id,
            )
        ]
        allowed_ids.update(public_ids)

    return sorted(project_collection_set & allowed_ids)
