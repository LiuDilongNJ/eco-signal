from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session

from app.csv_export import CsvColumn, export_columns_csv
from app.models.annotation import Annotation, AnnotationReview
from app.models.user import User
from app.repositories import permission_repository, review_repository
from app.repositories.task_repository import task_repository
from app.schemas.review import ReviewCreate, ReviewRead
from app.services import permission_service

_REVIEW_EXPORT_COLUMNS = [
    CsvColumn("annotation_id"), CsvColumn("media_name"), CsvColumn("media_type"),
    CsvColumn("reviewer_name"), CsvColumn("reviewer_id"),
    CsvColumn("status_name"), CsvColumn("taxon_name"),
    CsvColumn("note"), CsvColumn("creation_date"),
]
from app.services.permission_service import (
    has_resource_permission_on_any_collection_path,
)


def _get_review_read_collection_scopes(session: Session, user: User) -> list[tuple[int, int]] | None:
    """Get project-local collection scopes where the user has review:read access.

    Returns None for admin (no filtering needed).
    """
    if permission_service.is_admin(user):
        return None

    return permission_repository.get_accessible_collection_scopes(
        session,
        user_id=user.user_id,
        resource_type="review",
        action="read"
    )


def list_reviews(
    session: Session,
    user: User,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "creation_date",
    order_dir: str = "desc",
    **filters,
) -> tuple[list[dict[str, Any]], int]:
    """Get paginated list of reviews.

    Permission: review:read → all reviews in those project-local collection scopes,
    otherwise → only own reviews (reviewer_id = user_id).
    """
    admin = permission_service.is_admin(user)
    review_scopes = _get_review_read_collection_scopes(session, user)

    items, total = review_repository.list_reviews(
        session=session,
        accessible_collection_scopes=review_scopes,
        current_user_id=user.user_id,
        is_admin=admin,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )
    return [ReviewRead.model_validate(item).model_dump(mode="json") for item in items], total


def get_review_export_data(
    session: Session,
    user: User,
    order_by: str = "creation_date",
    order_dir: str = "desc",
    **filters,
) -> list[dict]:
    """Get all matching reviews for export.

    Permission: same as list_reviews.
    """
    admin = permission_service.is_admin(user)
    review_scopes = _get_review_read_collection_scopes(session, user)

    return review_repository.get_review_export_data(
        session=session,
        accessible_collection_scopes=review_scopes,
        current_user_id=user.user_id,
        is_admin=admin,
        order_by=order_by,
        order_dir=order_dir,
        **filters
    )


def export_review_csv(
    session: Session,
    user: User,
    order_by: str = "creation_date",
    order_dir: str = "desc",
    **filters,
) -> str:
    """Export matching reviews using the same fields as the list API."""
    items = get_review_export_data(
        session=session,
        user=user,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )
    return export_columns_csv(_REVIEW_EXPORT_COLUMNS, items)


def create_review(
    session: Session,
    user: User,
    data: ReviewCreate,
) -> None:
    """Create a new annotation review and mark the annotation task as reviewed."""
    annotation = session.get(Annotation, data.annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")

    if not permission_service.is_admin(user):
        collection_ids = review_repository.get_review_project_collection_ids(
            session, data.annotation_id, data.project_id
        )
        if not collection_ids:
            raise HTTPException(
                status_code=404,
                detail="Collection not found for this annotation in the given project",
            )

        if not has_resource_permission_on_any_collection_path(
            session,
            user,
            collection_ids,
            "review",
            "write",
            project_id=data.project_id,
        ):
            raise HTTPException(
                status_code=403,
                detail="Not enough permissions to create a review",
            )

    existing = review_repository.get_review(session, data.annotation_id, user.user_id)
    if existing:
        raise HTTPException(status_code=409, detail="Review already exists for this annotation by this user")

    review = AnnotationReview(
        annotation_id=data.annotation_id,
        reviewer_id=user.user_id,
        annotation_review_status_id=data.annotation_review_status_id,
        taxon_id=data.taxon_id,
        note=data.note,
        creation_date=datetime.now(UTC),
    )
    session.add(review)
    session.flush()

    task_repository.mark_annotation_task_reviewed(
        session=session,
        annotation_id=data.annotation_id,
        assignee_id=user.user_id,
    )
    session.commit()


def update_review(
    session: Session,
    user: User,
    project_id: int,
    annotation_id: int,
    reviewer_id: int,
    update_data: dict[str, Any],
) -> None:
    """Update a review, validating permissions, and mark the annotation task as reviewed."""
    review = review_repository.get_review(session, annotation_id, reviewer_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    if not permission_service.is_admin(user):
        collection_ids = review_repository.get_review_project_collection_ids(
            session, annotation_id, project_id
        )
        if not collection_ids:
            raise HTTPException(
                status_code=404,
                detail="Collection not found for this annotation in the given project",
            )

        if not has_resource_permission_on_any_collection_path(
            session,
            user,
            collection_ids,
            "review",
            "write",
            project_id=project_id,
        ):
            raise HTTPException(
                status_code=403,
                detail="Not enough permissions to edit this review",
            )

    review_repository.update(session, db_obj=review, obj_in=update_data)

    task_repository.mark_annotation_task_reviewed(
        session=session,
        annotation_id=annotation_id,
        assignee_id=reviewer_id,
    )
    session.commit()


def delete_review(
    session: Session,
    user: User,
    project_id: int,
    annotation_id: int,
    reviewer_id: int,
) -> None:
    """Delete a review and revert the annotation task back to assigned."""
    review = review_repository.get_review(session, annotation_id, reviewer_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    # Admin bypasses project-scope checks and can delete by review identity directly.
    if not permission_service.is_admin(user):
        collection_ids = review_repository.get_review_project_collection_ids(
            session, annotation_id, project_id
        )
        if not collection_ids:
            raise HTTPException(
                status_code=404,
                detail="Collection not found for this annotation in the given project",
            )

        can_delete = (
            reviewer_id == user.user_id
            or has_resource_permission_on_any_collection_path(
                session,
                user,
                collection_ids,
                "review",
                "write",
                project_id=project_id,
            )
        )
        if not can_delete:
            raise HTTPException(
                status_code=403,
                detail="Not enough permissions to delete this review",
            )

    session.delete(review)
    session.flush()

    task_repository.mark_annotation_task_assigned(
        session=session,
        annotation_id=annotation_id,
        assignee_id=reviewer_id,
    )
    session.commit()
