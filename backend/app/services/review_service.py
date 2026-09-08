from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.csv_export import CsvColumn, export_columns_csv
from app.models.annotation import Annotation, AnnotationReview
from app.models.user import User
from app.repositories import permission_repository, review_repository
from app.repositories.task_repository import task_repository
from app.schemas.review import ReviewCreate, ReviewRead
from app.services import authorization_service, permission_service
from app.services.authorization_policy import AuthorizationAction

_REVIEW_EXPORT_COLUMNS = [
    CsvColumn("annotation_id"), CsvColumn("media_name"), CsvColumn("media_type"),
    CsvColumn("reviewer_name"), CsvColumn("reviewer_id"),
    CsvColumn("status_name"), CsvColumn("taxon_name"),
    CsvColumn("note"), CsvColumn("creation_date"),
]


def _get_review_read_collection_scopes(
    session: Session, user: User, project_id: int | None
) -> list[tuple[int, int]] | None:
    """Get project-local collection scopes where the user has review:read access.

    Returns None for admin (no filtering needed).
    """
    if permission_service.is_admin(user):
        return None

    return permission_repository.get_accessible_collection_scopes(
        session,
        user_id=user.user_id,
        resource_type="review",
        action="read", project_id=project_id,
    )


def _get_review_own_collection_scopes(
    session: Session, user: User, project_id: int | None
) -> list[tuple[int, int]] | None:
    if permission_service.is_admin(user):
        return None
    return permission_repository.get_accessible_collection_scopes(
        session, user_id=user.user_id, resource_type="review", action="read_own", project_id=project_id
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
    project_id = filters.get("project_id")
    review_scopes = _get_review_read_collection_scopes(session, user, project_id)
    own_review_scopes = _get_review_own_collection_scopes(session, user, project_id)

    items, total = review_repository.list_reviews(
        session=session,
        accessible_collection_scopes=review_scopes,
        own_collection_scopes=own_review_scopes,
        current_user_id=user.user_id,
        is_admin=admin,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )
    annotation_ids = {int(item["annotation_id"]) for item in items}
    annotation_media = dict(
        session.exec(
            select(Annotation.annotation_id, Annotation.media_id).where(
                Annotation.annotation_id.in_(annotation_ids)
            )
        ).all()
    ) if annotation_ids else {}
    media_collections = authorization_service.media_collection_map(
        session, set(annotation_media.values()), project_id
    )
    authz = authorization_service.evaluator(session, user, project_id)
    data = []
    for item in items:
        linked_ids = media_collections.get(annotation_media.get(item["annotation_id"]), set())
        payload = dict(item)
        payload["capabilities"] = authz.review_capabilities(
            linked_ids, reviewer_id=item["reviewer_id"]
        )
        data.append(ReviewRead.model_validate(payload).model_dump(mode="json"))
    return data, total


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
    project_id = filters.get("project_id")
    review_scopes = _get_review_read_collection_scopes(session, user, project_id)
    own_review_scopes = _get_review_own_collection_scopes(session, user, project_id)

    return review_repository.get_review_export_data(
        session=session,
        accessible_collection_scopes=review_scopes,
        own_collection_scopes=own_review_scopes,
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
    *,
    commit: bool = True,
) -> None:
    """Create a new annotation review and mark the annotation task as reviewed."""
    validate_review_create(session, user, data)

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

    task_repository.mark_annotation_task_reviewed(session=session, annotation_id=data.annotation_id, assignee_id=user.user_id)
    if commit:
        session.commit()
    else:
        session.flush()


def validate_review_create(session: Session, user: User, data: ReviewCreate) -> None:
    """Validate review creation without persisting it."""
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

        authorization_service.evaluator(session, user, data.project_id).require(
            AuthorizationAction.ANNOTATION_CREATE_REVIEW,
            authorization_service.AuthorizationSubject(frozenset(collection_ids)),
            detail="Not enough permissions to create a review",
        )

    existing = review_repository.get_review(session, data.annotation_id, user.user_id)
    if existing:
        raise HTTPException(status_code=409, detail="Review already exists for this annotation by this user")



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

        authorization_service.evaluator(session, user, project_id).require(
            AuthorizationAction.REVIEW_EDIT,
            authorization_service.AuthorizationSubject(
                frozenset(collection_ids), owner_id=review.reviewer_id
            ),
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

        authorization_service.evaluator(session, user, project_id).require(
            AuthorizationAction.REVIEW_DELETE,
            authorization_service.AuthorizationSubject(
                frozenset(collection_ids), owner_id=review.reviewer_id
            ),
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
