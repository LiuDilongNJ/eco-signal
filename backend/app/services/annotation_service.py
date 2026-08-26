from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from app.csv_export import CsvColumn, export_columns_csv
from app.models.annotation import Annotation
from app.models.media import Media
from app.models.media import MediaCollection
from app.models.project import ProjectCollection
from app.models.user import User
from app.repositories import annotation_repository
from app.repositories.media_repository import media_repository
from app.repositories.permission_repository import permission_repository
from app.repositories.task_repository import task_repository
from app.schemas.annotation import (
    AnnotationCreate,
    AnnotationNavigation,
    AnnotationsPublic,
    AnnotationUpdate,
    AnnotationWithReviews,
)
from app.schemas.review import ReviewRead
from app.services import permission_service


_PHOTO_AUDIO_FIELDS = (
    "sound_id", "animal_sound_type", "sound_distance_m", "distance_not_estimable", "confidence",
)
_PHOTO_ORGANISM_FIELDS = ("taxon_id", "uncertain", "individual_num")


def _normalize_annotation_fields(media_type: str, values: dict) -> dict:
    if media_type == "audio":
        if values.get("sound_id") is None:
            raise HTTPException(status_code=422, detail="Audio annotations require a sound type")
        if values.get("object_type") is not None:
            raise HTTPException(status_code=422, detail="Audio annotations must not define an object type")
        values["object_type"] = None
        if values.get("individual_num") is None:
            values["individual_num"] = 1
        return values

    if media_type != "photo":
        raise HTTPException(status_code=422, detail="Annotations are supported for audio and photo media only")
    object_type = values.get("object_type")
    if object_type not in {"organism", "other"}:
        raise HTTPException(status_code=422, detail="Photo annotations require an object type")
    for field in _PHOTO_AUDIO_FIELDS:
        values[field] = None
    if object_type == "other":
        for field in _PHOTO_ORGANISM_FIELDS:
            values[field] = None
    elif values.get("individual_num") is None:
        values["individual_num"] = 1
    return values


def _validate_annotation_bounds(session: Session, media_id: int, min_x: float, max_x: float, min_y: float, max_y: float) -> None:
    """Validate rectangle coordinates; photo annotations use original-image pixels."""
    if min_x < 0 or min_y < 0 or max_x <= min_x or max_y <= min_y:
        raise HTTPException(status_code=422, detail="Annotation bounds must form a non-empty rectangle")
    media = session.get(Media, media_id)
    if not media or media.media_type != "photo":
        return
    from PIL import Image
    from app.media_paths import logical_photo_media_path, resolve_existing_media_path

    collection_ids = session.exec(
        select(MediaCollection.collection_id).where(MediaCollection.media_id == media_id).order_by(MediaCollection.collection_id)
    ).all()
    if not collection_ids or not media.filename:
        return
    path = resolve_existing_media_path(logical_photo_media_path(collection_ids[0], media.directory or "", media.filename))
    if path is None:
        return
    try:
        with Image.open(path) as image:
            width, height = image.size
    except OSError as exc:
        raise HTTPException(status_code=422, detail="Photo source is unreadable") from exc
    if max_x > width or max_y > height:
        raise HTTPException(status_code=422, detail="Annotation bounds exceed the photo dimensions")

_ANNOTATION_EXPORT_COLUMNS = [
    CsvColumn("annotation_id"), CsvColumn("uuid"),
    CsvColumn("media_name"), CsvColumn("media_type"), CsvColumn("min_x"),
    CsvColumn("max_x"), CsvColumn("min_y"),
    CsvColumn("max_y"), CsvColumn("creator_type"),
    CsvColumn("object_type"), CsvColumn("soundscape_component"), CsvColumn("sound_type"),
    CsvColumn("taxon_scientific_name"), CsvColumn("animal_sound_type"),
    CsvColumn("confidence"), CsvColumn("uncertain"),
    CsvColumn("sound_distance_m"), CsvColumn("distance_not_estimable"),
    CsvColumn("individual_num"), CsvColumn("reference"),
    CsvColumn("comments"), CsvColumn("creator_name"),
    CsvColumn("creator_id"), CsvColumn("creation_date"),
]
from app.services.permission_service import (
    has_resource_permission_on_any_collection_path,
)


def _verify_media_and_get_project_collections(
    session: Session,
    media_id: int,
    project_id: int,
) -> list[int]:
    """Verify media exists and return its collection IDs within one project scope."""
    media = media_repository.get(session, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    if not media.media_collections:
        raise HTTPException(status_code=400, detail="Media does not belong to any collection")

    collection_ids = list(
        session.exec(
            select(MediaCollection.collection_id)
            .join(
                ProjectCollection,
                ProjectCollection.collection_id == MediaCollection.collection_id,
            )
            .where(
                MediaCollection.media_id == media_id,
                ProjectCollection.project_id == project_id,
            )
        ).all()
    )
    if not collection_ids:
        raise HTTPException(status_code=400, detail="Media does not belong to the given project")

    return collection_ids


def _get_annotation_broad_access_ids(
    session: Session,
    user: User,
    project_id: int | None = None,
) -> list[int]:
    """Get collection IDs where user can see ALL annotations (not just their own).

    This includes:
    - Collections where user has annotation:read (includes collection:write / project:write inheritance)
    - Collections where public_tags=True (annotations visible to everyone)
    """
    annotation_access_ids = permission_repository.get_accessible_collection_ids(
        session, user.user_id, resource_type="annotation", action="read", project_id=project_id
    )

    public_tags_ids = [
        collection_id
        for _, collection_id in permission_repository.get_public_collection_scopes(
            session,
            project_id=project_id,
            require_public_tags=True,
        )
    ]

    return list(set(annotation_access_ids) | set(public_tags_ids))


def list_annotations(
    session: Session,
    current_user: User | None,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "annotation_id",
    order_dir: str = "asc",
    **filters,
) -> AnnotationsPublic:
    """
    Get paginated list of annotations.

    Permission:
    - Admin → all annotations
    - annotation:read / collection:write → all annotations in those collections
    - public_tags=True collections → all annotations visible
    - Otherwise → only user's own annotations
    """
    if current_user is None:
        admin = False
        broad_access_ids = [
            collection_id
            for _, collection_id in permission_repository.get_public_collection_scopes(
                session,
                project_id=filters.get("project_id"),
                require_public_tags=True,
            )
        ]
        current_user_id = None
    else:
        admin = permission_service.is_admin(current_user)
        broad_access_ids = (
            _get_annotation_broad_access_ids(session, current_user, project_id=filters.get("project_id"))
            if not admin
            else None
        )
        current_user_id = current_user.user_id

    results, total_count = annotation_repository.list_annotations(
        session=session,
        accessible_collection_ids=broad_access_ids,
        current_user_id=current_user_id,
        is_admin=admin,
        page=page,
        page_size=page_size,
        order_by=order_by,
        order_dir=order_dir,
        **filters,
    )

    ann_ids = [r["annotation_id"] for r in results]
    reviews_map = _get_annotation_reviews_batch(session, ann_ids)
    task_map = (
        task_repository.get_annotation_tasks_for_user(
            session, annotation_ids=ann_ids, user_id=current_user.user_id
        )
        if current_user is not None
        else {}
    )
    for r in results:
        r["reviews"] = [rv.model_dump() for rv in reviews_map.get(r["annotation_id"], [])]
        task = task_map.get(r["annotation_id"])
        r["task"] = {
            "task_id": task.task_id,
            "type": task.type,
            "status": task.status,
            "comment": task.comment,
        } if task else None

    return AnnotationsPublic(data=results, count=total_count)


def get_annotation(
    session: Session,
    current_user: User,
    annotation_id: int,
    project_id: int,
) -> AnnotationWithReviews:
    """
    Get a single annotation by ID with embedded reviews.

    Permission: same as list (admin / annotation:read / public_tags / own annotation).
    """
    result = list_annotations(session, current_user, annotation_id=annotation_id, project_id=project_id)
    if not result.data:
        raise HTTPException(status_code=404, detail="Annotation not found or access denied")

    ann_dict = result.data[0].model_dump()

    # Load reviews for this annotation
    reviews = _get_annotation_reviews(session, annotation_id)
    ann_dict["reviews"] = [r.model_dump() for r in reviews]

    return AnnotationWithReviews(**ann_dict)


def _get_annotation_reviews_batch(session: Session, annotation_ids: list[int]) -> dict[int, list[ReviewRead]]:
    """Batch-load reviews for multiple annotations; returns a map of annotation_id → reviews."""
    if not annotation_ids:
        return {}

    from app.models.annotation import AnnotationReview, AnnotationReviewStatus
    from app.models.taxon import Taxon
    from app.models.user import User as UserModel

    stmt = (
        select(
            AnnotationReview,
            Media.media_type.label("media_type"),
            UserModel.name.label("reviewer_name"),
            AnnotationReviewStatus.name.label("status_name"),
            Taxon.cached_scientific_name.label("taxon_name"),
        )
        .join(Annotation, AnnotationReview.annotation_id == Annotation.annotation_id)
        .join(Media, Annotation.media_id == Media.media_id)
        .outerjoin(UserModel, AnnotationReview.reviewer_id == UserModel.user_id)
        .outerjoin(
            AnnotationReviewStatus,
            AnnotationReview.annotation_review_status_id == AnnotationReviewStatus.annotation_review_status_id,
        )
        .outerjoin(Taxon, AnnotationReview.taxon_id == Taxon.taxon_id)
        .where(AnnotationReview.annotation_id.in_(annotation_ids))
    )
    rows = session.exec(stmt).all()

    result: dict[int, list[ReviewRead]] = {}
    for row in rows:
        review, media_type, reviewer_name, status_name, taxon_name = row
        rv = ReviewRead(
            annotation_id=review.annotation_id,
            reviewer_id=review.reviewer_id,
            annotation_review_status_id=review.annotation_review_status_id,
            taxon_id=review.taxon_id,
            note=review.note,
            creation_date=review.creation_date,
            media_type=media_type,
            reviewer_name=reviewer_name or "",
            status_name=status_name or "",
            taxon_name=taxon_name,
        )
        result.setdefault(review.annotation_id, []).append(rv)
    return result


def _get_annotation_reviews(session: Session, annotation_id: int) -> list[ReviewRead]:
    """Load reviews for a given annotation with reviewer name and status name."""
    from app.models.annotation import AnnotationReview, AnnotationReviewStatus
    from app.models.taxon import Taxon
    from app.models.user import User as UserModel

    stmt = (
        select(
            AnnotationReview,
            Media.media_type.label("media_type"),
            UserModel.name.label("reviewer_name"),
            AnnotationReviewStatus.name.label("status_name"),
            Taxon.cached_scientific_name.label("taxon_name"),
        )
        .join(Annotation, AnnotationReview.annotation_id == Annotation.annotation_id)
        .join(Media, Annotation.media_id == Media.media_id)
        .outerjoin(UserModel, AnnotationReview.reviewer_id == UserModel.user_id)
        .outerjoin(
            AnnotationReviewStatus,
            AnnotationReview.annotation_review_status_id == AnnotationReviewStatus.annotation_review_status_id,
        )
        .outerjoin(Taxon, AnnotationReview.taxon_id == Taxon.taxon_id)
        .where(AnnotationReview.annotation_id == annotation_id)
    )
    rows = session.exec(stmt).all()
    results = []
    for row in rows:
        review, media_type, reviewer_name, status_name, taxon_name = row
        results.append(
            ReviewRead(
                annotation_id=review.annotation_id,
                reviewer_id=review.reviewer_id,
                annotation_review_status_id=review.annotation_review_status_id,
                taxon_id=review.taxon_id,
                note=review.note,
                creation_date=review.creation_date,
                media_type=media_type,
                reviewer_name=reviewer_name or "",
                status_name=status_name or "",
                taxon_name=taxon_name,
            )
        )
    return results


def get_annotation_navigation(
    session: Session,
    current_user: User,
    annotation_id: int,
    media_id: int,
) -> AnnotationNavigation:
    """Return prev/next annotation IDs within the same media, ordered by annotation_id."""
    # Verify the annotation exists and user can access it
    result = list_annotations(session, current_user, annotation_id=annotation_id)
    if not result.data:
        raise HTTPException(status_code=404, detail="Annotation not found or access denied")

    prev_id, next_id = annotation_repository.get_annotation_navigation(
        session, annotation_id=annotation_id, media_id=media_id
    )
    return AnnotationNavigation(prev_annotation_id=prev_id, next_annotation_id=next_id)


def export_annotation_csv(
    session: Session,
    current_user: User,
    order_by: str = "annotation_id",
    order_dir: str = "asc",
    **filters,
) -> str:
    """
    Export annotations matching the filters to CSV format.

    Permission: same as list_annotations.
    """
    admin = permission_service.is_admin(current_user)
    broad_access_ids = (
        _get_annotation_broad_access_ids(session, current_user, project_id=filters.get("project_id"))
        if not admin
        else None
    )

    results, _ = annotation_repository.list_annotations(
        session=session,
        accessible_collection_ids=broad_access_ids,
        current_user_id=current_user.user_id,
        is_admin=admin,
        page=1,
        page_size=1_000_000,
        order_by=order_by,
        order_dir=order_dir,
        include_total=False,
        **filters,
    )
    ann_ids = [r["annotation_id"] for r in results]
    reviews_map = _get_annotation_reviews_batch(session, ann_ids)
    task_map = task_repository.get_annotation_tasks_for_user(
        session, annotation_ids=ann_ids, user_id=current_user.user_id
    )
    for row in results:
        row["reviews"] = [review.model_dump() for review in reviews_map.get(row["annotation_id"], [])]
        task = task_map.get(row["annotation_id"])
        row["task"] = {
            "task_id": task.task_id,
            "type": task.type,
            "status": task.status,
            "comment": task.comment,
        } if task else None

    return export_columns_csv(_ANNOTATION_EXPORT_COLUMNS, results)


def create_annotation(
    session: Session,
    current_user: User,
    data: AnnotationCreate,
    *,
    commit: bool = True,
) -> None:
    """
    Create a new annotation.
    Requires annotation:write on the host media's collection.
    """
    # 1. Verify media exists and get its collection
    collection_ids = _verify_media_and_get_project_collections(session, data.media_id, data.project_id)

    # 2. Check permission
    has_permission = has_resource_permission_on_any_collection_path(
        session,
        current_user,
        collection_ids,
        "annotation",
        "write",
        project_id=data.project_id,
    )
    if not has_permission:
        raise HTTPException(
            status_code=403, 
            detail="You do not have write permission for annotations in this media's collection"
        )

    media = session.get(Media, data.media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")
    payload = _normalize_annotation_fields(media.media_type, data.model_dump())
    _validate_annotation_bounds(session, data.media_id, data.min_x, data.max_x, data.min_y, data.max_y)
        
    # 3. Create annotation
    new_annotation = Annotation(
        media_id=data.media_id,
        min_x=data.min_x,
        max_x=data.max_x,
        min_y=data.min_y,
        max_y=data.max_y,
        sound_id=payload["sound_id"],
        object_type=payload["object_type"],
        reference=payload["reference"],
        comments=payload["comments"],
        taxon_id=payload["taxon_id"],
        uncertain=payload["uncertain"],
        sound_distance_m=payload["sound_distance_m"],
        distance_not_estimable=payload["distance_not_estimable"],
        individual_num=payload["individual_num"],
        creator_id=current_user.user_id,
        creator_type=data.creator_type,
        confidence=payload["confidence"],
        animal_sound_type=payload["animal_sound_type"],
        creation_date=datetime.now(UTC),
    )
    
    annotation_repository.create(session, new_annotation, commit=commit)


def update_annotation(
    session: Session,
    current_user: User,
    project_id: int,
    annotation_id: int,
    data: AnnotationUpdate,
) -> None:
    """
    Update/heal an annotation.
    User can update if:
     - They have annotation:write on the collection
     - OR they are the creator AND have annotation:read on the collection.
    """
    annotation = annotation_repository.get(session, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="Annotation not found")
        
    collection_ids = _verify_media_and_get_project_collections(session, annotation.media_id, project_id)
        
    # Check permissions
    is_creator = (annotation.creator_id == current_user.user_id)
    has_write = has_resource_permission_on_any_collection_path(
        session,
        current_user,
        collection_ids,
        "annotation",
        "write",
        project_id=project_id,
    )
    
    if not has_write:
        if not is_creator:
            raise HTTPException(status_code=403, detail="Not authorized to update this annotation")
        else:
            # Check if creator still has read permission at least
            has_read = has_resource_permission_on_any_collection_path(
                session,
                current_user,
                collection_ids,
                "annotation",
                "read",
                project_id=project_id,
            )
            if not has_read:
                raise HTTPException(status_code=403, detail="Lost read access to this collection")
                
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return
    _validate_annotation_bounds(
        session,
        annotation.media_id,
        update_data.get("min_x", annotation.min_x),
        update_data.get("max_x", annotation.max_x),
        update_data.get("min_y", annotation.min_y),
        update_data.get("max_y", annotation.max_y),
    )
        
    media = session.get(Media, annotation.media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media not found")
    final_values = {
        field: getattr(annotation, field)
        for field in (*_PHOTO_AUDIO_FIELDS, *_PHOTO_ORGANISM_FIELDS, "object_type", "reference", "comments", "sound_id")
    }
    final_values.update(update_data)
    annotation_repository.update(
        session,
        db_obj=annotation,
        obj_in=_normalize_annotation_fields(media.media_type, final_values),
    )


def delete_annotation(
    session: Session,
    current_user: User,
    project_id: int,
    annotation_id: int,
) -> None:
    """
    Delete an annotation entirely.
    User can delete if they have annotation:write on the collection,
    OR if they are the creator.
    """
    annotation = annotation_repository.get(session, annotation_id)
    if not annotation:
        # Idempotent or just ignore
        raise HTTPException(status_code=404, detail="Annotation not found")
        
    collection_ids = _verify_media_and_get_project_collections(session, annotation.media_id, project_id)
    
    is_creator = (annotation.creator_id == current_user.user_id)
    has_write = has_resource_permission_on_any_collection_path(
        session,
        current_user,
        collection_ids,
        "annotation",
        "write",
        project_id=project_id,
    )
    
    if not has_write and not is_creator:
        raise HTTPException(status_code=403, detail="Not authorized to delete this annotation")

    annotation_repository.delete_by_ids(session, [annotation_id])
