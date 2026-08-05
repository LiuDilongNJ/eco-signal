from typing import Any, Sequence

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models.annotation import Annotation, AnnotationReview, AnnotationReviewStatus
from app.models.media import Media, MediaCollection
from app.models.project import ProjectCollection
from app.models.taxon import Taxon
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)

_FILTER_SPECS: list[FilterSpec] = [
    ("annotation_id", AnnotationReview.annotation_id,                       FilterOp.EQ),
    ("reviewer_id",   AnnotationReview.reviewer_id,                         FilterOp.EQ),
    ("status_id",     AnnotationReview.annotation_review_status_id,         FilterOp.EQ),
    ("taxon_id",      AnnotationReview.taxon_id,                            FilterOp.EQ),
    ("media_name",    Media.filename,                                       FilterOp.LIKE),
    ("media_type",    Media.media_type,                                     FilterOp.EQ),
    ("note",          AnnotationReview.note,                                FilterOp.LIKE),
    ("creation_date", AnnotationReview.creation_date,                       FilterOp.DATE_RANGE),
]

_SORT_FIELDS: dict[str, Any] = {
    "annotation_id": AnnotationReview.annotation_id,
    "media_name":    Media.filename,
    "media_type":    Media.media_type,
    "reviewer_name": User.username,
    "status_name":   AnnotationReviewStatus.name,
    "taxon_name":    Taxon.cached_scientific_name,
    "note":          AnnotationReview.note,
    "creation_date": AnnotationReview.creation_date,
}


def _review_taxon_name_clause(raw_value: str):
    search_term = f"%{raw_value}%"
    return sa.or_(
        Taxon.cached_scientific_name.ilike(search_term),
        Taxon.cached_common_name.ilike(search_term),
    )


class ReviewRepository(BaseRepository[AnnotationReview, Any, Any]):
    """Review repository."""

    def __init__(self):
        super().__init__(AnnotationReview)

    def _build_list_query(
        self,
        accessible_collection_ids: list[int] | None = None,
        accessible_collection_scopes: list[tuple[int, int]] | None = None,
        current_user_id: int | None = None,
        is_admin: bool = False,
        filters: dict | None = None,
    ):
        """Build the base select statement for reviews list/export.

        Permission logic:
        - Admin: no restrictions
        - accessible_collection_ids provided: show all reviews in those collections,
          PLUS reviews where reviewer_id = current_user_id in other collections
        - No accessible collections: only show reviews where reviewer_id = current_user_id
        """
        if filters is None:
            filters = {}

        stmt = (
            select(
                AnnotationReview,
                Media.filename.label("media_name"),
                Media.media_type.label("media_type"),
                User.name.label("reviewer_name"),
                AnnotationReviewStatus.name.label("status_name"),
                Taxon.cached_scientific_name.label("taxon_name")
            )
            .join(Annotation, AnnotationReview.annotation_id == Annotation.annotation_id)
            .join(Media, Annotation.media_id == Media.media_id)
            .join(MediaCollection, Media.media_id == MediaCollection.media_id)
            .join(ProjectCollection, ProjectCollection.collection_id == MediaCollection.collection_id)
            .join(User, AnnotationReview.reviewer_id == User.user_id)
            .join(AnnotationReviewStatus, AnnotationReview.annotation_review_status_id == AnnotationReviewStatus.annotation_review_status_id)
            .outerjoin(Taxon, AnnotationReview.taxon_id == Taxon.taxon_id)
        )

        # Permission filter: review:read scope → all, otherwise → own reviews only
        if not is_admin:
            conditions = []
            if accessible_collection_scopes:
                scope_conditions = [
                    sa.and_(
                        ProjectCollection.project_id == project_id,
                        MediaCollection.collection_id == collection_id,
                    )
                    for project_id, collection_id in accessible_collection_scopes
                ]
                conditions.append(sa.or_(*scope_conditions))
            elif accessible_collection_ids:
                conditions.append(MediaCollection.collection_id.in_(accessible_collection_ids))
            if current_user_id is not None:
                conditions.append(AnnotationReview.reviewer_id == current_user_id)
            if conditions:
                stmt = stmt.where(sa.or_(*conditions))
            else:
                stmt = stmt.where(sa.false())

        # Standard declarative filters
        stmt = apply_filters(stmt, filters, _FILTER_SPECS)

        if filters.get("reviewer_name"):
            stmt = stmt.where(User.username.ilike(f"%{filters['reviewer_name']}%"))
        if filters.get("status_name"):
            stmt = stmt.where(AnnotationReviewStatus.name.ilike(f"%{filters['status_name']}%"))
        if filters.get("taxon_name"):
            stmt = stmt.where(_review_taxon_name_clause(filters["taxon_name"]))

        # project_id is a relationship-path filter and must be applied explicitly.
        if filters.get("project_id") is not None:
            stmt = stmt.where(ProjectCollection.project_id == filters["project_id"])
        if filters.get("collection_id") is not None:
            stmt = stmt.where(MediaCollection.collection_id == filters["collection_id"])
        return stmt

    def list_reviews(
        self,
        session: Session,
        accessible_collection_ids: list[int] | None = None,
        accessible_collection_scopes: list[tuple[int, int]] | None = None,
        current_user_id: int | None = None,
        is_admin: bool = False,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "creation_date",
        order_dir: str = "desc",
        **filters,
    ) -> tuple[Sequence[Any], int]:
        """Get paginated list of reviews."""
        if not is_admin and not accessible_collection_ids and current_user_id is None:
            return [], 0

        stmt = self._build_list_query(
            accessible_collection_ids=accessible_collection_ids,
            accessible_collection_scopes=accessible_collection_scopes,
            current_user_id=current_user_id,
            is_admin=is_admin,
            filters=filters,
        )

        # Count total matched before grouping/ordering.
        # Use subquery columns to avoid cartesian products when warning-as-error is enabled.
        base_subquery = stmt.subquery()
        distinct_reviews = (
            select(base_subquery.c.annotation_id, base_subquery.c.reviewer_id)
            .distinct()
            .subquery()
        )
        count_stmt = select(func.count()).select_from(distinct_reviews)
        total_count = session.exec(count_stmt).one()

        # Ordering + pagination
        stmt = apply_ordering(stmt, order_by, order_dir, _SORT_FIELDS, AnnotationReview.creation_date)
        # Due to MediaCollection JOIN, we might get duplicate reviews if media is in multiple accessible collections.
        stmt = apply_pagination(stmt, page, page_size)

        results = session.exec(stmt).unique().all()

        # Format results
        formatted_results = []
        for row in results:
            review, media_name, media_type, reviewer_name, status_name, taxon_name = row
            review_dict = review.model_dump()
            review_dict.update({
                "media_name": media_name,
                "media_type": media_type,
                "reviewer_name": reviewer_name,
                "status_name": status_name,
                "taxon_name": taxon_name,
            })
            formatted_results.append(review_dict)

        return formatted_results, total_count

    def get_review_export_data(
        self,
        session: Session,
        accessible_collection_ids: list[int] | None = None,
        accessible_collection_scopes: list[tuple[int, int]] | None = None,
        current_user_id: int | None = None,
        is_admin: bool = False,
        order_by: str = "creation_date",
        order_dir: str = "desc",
        **filters,
    ) -> list[dict]:
        """Get all matching reviews for export (no pagination)."""
        if not is_admin and not accessible_collection_ids and current_user_id is None:
            return []

        stmt = self._build_list_query(
            accessible_collection_ids=accessible_collection_ids,
            accessible_collection_scopes=accessible_collection_scopes,
            current_user_id=current_user_id,
            is_admin=is_admin,
            filters=filters,
        )

        stmt = apply_ordering(stmt, order_by, order_dir, _SORT_FIELDS, AnnotationReview.creation_date)

        results = session.exec(stmt).unique().all()

        formatted_results = []
        for row in results:
            review, media_name, media_type, reviewer_name, status_name, taxon_name = row
            review_dict = review.model_dump()
            review_dict.update({
                "media_name": media_name,
                "media_type": media_type,
                "reviewer_name": reviewer_name,
                "status_name": status_name,
                "taxon_name": taxon_name,
            })
            formatted_results.append(review_dict)

        return formatted_results

    def get_review(self, session: Session, annotation_id: int, reviewer_id: int) -> AnnotationReview | None:
        """Get a single review by id."""
        stmt = select(AnnotationReview).where(
            AnnotationReview.annotation_id == annotation_id,
            AnnotationReview.reviewer_id == reviewer_id
        )
        return session.exec(stmt).first()

    def get_review_project_collection_ids(
        self,
        session: Session,
        annotation_id: int,
        project_id: int,
    ) -> list[int]:
        """Get collection IDs for an annotation's media within one project scope."""
        stmt = (
            select(MediaCollection.collection_id)
            .join(Annotation, Annotation.media_id == MediaCollection.media_id)
            .join(
                ProjectCollection,
                ProjectCollection.collection_id == MediaCollection.collection_id,
            )
            .where(
                Annotation.annotation_id == annotation_id,
                ProjectCollection.project_id == project_id,
            )
        )
        return list(session.exec(stmt).all())


review_repository = ReviewRepository()
