from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.project import ProjectCollection


def resolve_collection_project_id(
    session: Session,
    collection_id: int,
    project_id: int | None,
) -> int:
    """Resolve and validate the project path for a collection-scoped operation."""
    if project_id is not None:
        linked = session.exec(
            select(ProjectCollection).where(
                ProjectCollection.project_id == project_id,
                ProjectCollection.collection_id == collection_id,
            )
        ).first()
        if not linked:
            raise HTTPException(
                status_code=400,
                detail="collection_id does not belong to the given project_id",
            )
        return project_id

    project_ids = list(session.exec(
        select(ProjectCollection.project_id).where(
            ProjectCollection.collection_id == collection_id,
        )
    ).all())
    if len(project_ids) == 1:
        return project_ids[0]
    raise HTTPException(
        status_code=400,
        detail="project_id is required when collection belongs to multiple projects",
    )
