from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlmodel import Session, func, select

from app.models.annotation import Annotation
from app.models.media import Media, MediaCollection
from app.models.project import ProjectCollection
from app.models.taxon import SoundClassification, Taxon
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)

# Declarative filter specs – covers all standard (EQ / LIKE / RANGE) filters.
# Custom filters (permission logic, join-table columns) are
# handled manually in _build_list_query below.
_FILTER_SPECS: list[FilterSpec] = [
    # Exact matches on Annotation columns
    ("annotation_id",     Annotation.annotation_id,          FilterOp.EQ),
    ("media_id",          Annotation.media_id,               FilterOp.EQ),
    ("taxon_id",          Annotation.taxon_id,               FilterOp.EQ),
    ("creator_id",        Annotation.creator_id,             FilterOp.EQ),
    ("sound_id",          Annotation.sound_id,               FilterOp.EQ),
    ("uuid",              Annotation.uuid,                   FilterOp.EQ),
    ("uncertain",         Annotation.uncertain,              FilterOp.EQ),
    ("distance_not_estimable", Annotation.distance_not_estimable, FilterOp.EQ),
    ("reference",         Annotation.reference,              FilterOp.EQ),
    # Fuzzy matches
    ("creator_type", Annotation.creator_type, FilterOp.LIKE),
    ("animal_sound_type", Annotation.animal_sound_type, FilterOp.LIKE),
    ("soundscape_component", SoundClassification.soundscape_component, FilterOp.LIKE),
    ("media_name", Media.filename,     FilterOp.LIKE),
    ("media_type", Media.media_type,   FilterOp.EQ),
    ("comments",   Annotation.comments, FilterOp.LIKE),
    # Date range (creation_date_from / creation_date_to)
    ("creation_date", Annotation.creation_date, FilterOp.DATE_RANGE),
    # Numeric ranges (*_min / *_max)
    ("confidence",       Annotation.confidence,         FilterOp.RANGE),
    ("sound_distance_m", Annotation.sound_distance_m,   FilterOp.RANGE),
    ("individual_num",   Annotation.individual_num,     FilterOp.RANGE),
    ("min_x",            Annotation.min_x,              FilterOp.RANGE),
    ("max_x",            Annotation.max_x,              FilterOp.RANGE),
    ("min_y",            Annotation.min_y,              FilterOp.RANGE),
    ("max_y",            Annotation.max_y,              FilterOp.RANGE),
]

# Explicit sort-field mapping: frontend column key → ORM column expression.
# The candidate query adds related-table joins only when their sort key is used.
_SORT_FIELDS: dict[str, Any] = {
    "annotation_id":  Annotation.annotation_id,
    "uuid":           Annotation.uuid,
    "media_name":     Media.filename,
    "media_type":     Media.media_type,
    "min_x":          Annotation.min_x,
    "max_x":          Annotation.max_x,
    "min_y":          Annotation.min_y,
    "max_y":          Annotation.max_y,
    "creator_type":   Annotation.creator_type,
    "soundscape_component": SoundClassification.soundscape_component,
    "sound_type":     SoundClassification.sound_type,
    "taxon_name":     func.coalesce(Taxon.cached_scientific_name, Taxon.cached_common_name),
    "animal_sound_type": Annotation.animal_sound_type,
    "confidence":     Annotation.confidence,
    "uncertain":      Annotation.uncertain,
    "distance_not_estimable": Annotation.distance_not_estimable,
    "sound_distance_m": Annotation.sound_distance_m,
    "individual_num": Annotation.individual_num,
    "reference":      Annotation.reference,
    "comments":       Annotation.comments,
    "creator_name":   User.name,
    "creation_date":  Annotation.creation_date,
}


def _taxon_name_clause(raw_value: str):
    search_term = f"%{raw_value}%"
    return sa.or_(
        Taxon.cached_scientific_name.ilike(search_term),
        Taxon.cached_common_name.ilike(search_term),
    )


class AnnotationRepository(BaseRepository[Annotation, Any, Any]):
    """Annotation repository."""
    
    def __init__(self):
        super().__init__(Annotation)
    
    def create(self, session: Session, annotation: Annotation) -> Annotation:
        """Create a single annotation."""
        session.add(annotation)
        session.commit()
        session.refresh(annotation)
        return annotation
    
    def create_batch(
        self,
        session: Session,
        annotations: list[Annotation],
        *,
        commit: bool = True,
    ) -> list[Annotation]:
        """Create annotations in batch."""
        if not annotations:
            return []
        
        session.add_all(annotations)
        if commit:
            session.commit()
        else:
            session.flush()
        
        # Refresh to get generated IDs
        for ann in annotations:
            session.refresh(ann)
        
        return annotations
    
    def get_by_media_id(
        self,
        session: Session,
        media_id: int,
        creator_type: str | None = None,
    ) -> list[Annotation]:
        """Get annotations by media ID."""
        statement = select(Annotation).where(Annotation.media_id == media_id)
        
        if creator_type:
            statement = statement.where(Annotation.creator_type == creator_type)
        
        statement = statement.order_by(Annotation.min_x)
        return list(session.exec(statement).all())

    def find_taxon(
        self,
        session: Session,
        scientific_name: str,
    ) -> "Taxon | None":
        """Find a taxon by scientific name; bridge from XR foreign table when available."""
        normalized_name = " ".join((scientific_name or "").split()).strip()
        if not normalized_name:
            return None

        existing = session.exec(
            select(Taxon).where(func.lower(Taxon.cached_scientific_name) == normalized_name.lower())
        ).first()
        if existing:
            return existing

        if not bool(session.execute(text("SELECT to_regclass('public.geo_col_xr_taxon_species') IS NOT NULL")).scalar_one()):
            return None

        remote = session.execute(
            text(
                """
                SELECT
                  col_species_id,
                  cached_scientific_name,
                  cached_common_name,
                  col_genus_id,
                  col_family_id,
                  col_order_id,
                  col_class_id,
                  taxonomy_source,
                  imported_at
                FROM geo_col_xr_taxon_species
                WHERE lower(cached_scientific_name) = lower(:scientific_name)
                LIMIT 1
                """
            ),
            {"scientific_name": normalized_name},
        ).mappings().first()
        if remote is None:
            return None

        bridged = Taxon(
            col_species_id=remote.get("col_species_id"),
            col_genus_id=remote.get("col_genus_id"),
            col_family_id=remote.get("col_family_id"),
            col_order_id=remote.get("col_order_id"),
            col_class_id=remote.get("col_class_id"),
            cached_scientific_name=remote.get("cached_scientific_name"),
            cached_common_name=remote.get("cached_common_name"),
            taxonomy_source=remote.get("taxonomy_source") or "CatalogueOfLife-XR",
            last_synced=remote.get("imported_at") or datetime.now(UTC),
            creation_date=datetime.now(UTC),
        )
        session.add(bridged)
        session.commit()
        session.refresh(bridged)
        return bridged

    def get_by_media_and_creator_type(
        self,
        session: Session,
        media_id: int,
        creator_type: str,
    ) -> list[Annotation]:
        """Get annotations by media ID and creator type."""
        statement = (
            select(Annotation)
            .where(
                Annotation.media_id == media_id,
                Annotation.creator_type == creator_type,
            )
            .order_by(Annotation.min_x)
        )
        return list(session.exec(statement).all())

    def delete_by_ids(
        self,
        session: Session,
        annotation_ids: list[int],
        *,
        commit: bool = True,
    ) -> int:
        """Delete annotations by their IDs."""
        if not annotation_ids:
            return 0
 
        statement = select(Annotation).where(Annotation.annotation_id.in_(annotation_ids))
        annotations = session.exec(statement).all()
        count = len(annotations)
 
        for ann in annotations:
            session.delete(ann)
 
        if commit:
            session.commit()
        else:
            session.flush()
        return count

    def _build_media_scope_exists(
        self,
        *,
        project_id: int | None = None,
        collection_id: int | None = None,
        collection_ids: list[int] | None = None,
    ):
        """Build a correlated media-scope predicate without duplicating annotations."""
        stmt = (
            select(1)
            .select_from(MediaCollection)
            .where(MediaCollection.media_id == Annotation.media_id)
        )

        if project_id is not None:
            stmt = stmt.join(
                ProjectCollection,
                ProjectCollection.collection_id == MediaCollection.collection_id,
            ).where(ProjectCollection.project_id == project_id)

        if collection_id is not None:
            stmt = stmt.where(MediaCollection.collection_id == collection_id)
        elif collection_ids:
            stmt = stmt.where(MediaCollection.collection_id.in_(collection_ids))

        return sa.exists(stmt)

    def _build_list_candidate_query(
        self,
        accessible_collection_ids: list[int] | None = None,
        current_user_id: int | None = None,
        is_admin: bool = False,
        filters: dict | None = None,
        order_by: str | None = None,
    ):
        """Build the light-weight candidate query used for count and pagination."""
        if filters is None:
            filters = {}

        needs_media_join = (
            bool(filters.get("media_name"))
            or filters.get("media_type") is not None
            or order_by in {"media_name", "media_type"}
        )
        needs_user_join = bool(filters.get("creator_name")) or order_by == "creator_name"
        needs_sound_join = (
            filters.get("soundscape_component") is not None
            or bool(filters.get("sound_type"))
            or order_by in {"soundscape_component", "sound_type"}
        )
        needs_taxon_join = bool(filters.get("taxon_name")) or order_by == "taxon_name"

        stmt = (
            select(
                Annotation.annotation_id.label("annotation_id"),
            )
            .select_from(Annotation)
        )
        if needs_media_join:
            stmt = stmt.join(Media, Annotation.media_id == Media.media_id)
        if needs_sound_join:
            stmt = stmt.outerjoin(SoundClassification, Annotation.sound_id == SoundClassification.sound_id)
        if needs_user_join:
            stmt = stmt.outerjoin(User, Annotation.creator_id == User.user_id)
        if needs_taxon_join:
            stmt = stmt.outerjoin(Taxon, Annotation.taxon_id == Taxon.taxon_id)

        if filters.get("project_id") is not None or filters.get("collection_id") is not None:
            stmt = stmt.where(self._build_media_scope_exists(
                project_id=filters.get("project_id"),
                collection_id=filters.get("collection_id"),
            ))

        # Permission filter
        if not is_admin:
            conditions = []
            if accessible_collection_ids:
                conditions.append(self._build_media_scope_exists(
                    collection_ids=accessible_collection_ids,
                ))
            if current_user_id is not None:
                conditions.append(Annotation.creator_id == current_user_id)
            if conditions:
                stmt = stmt.where(sa.or_(*conditions))
            else:
                stmt = stmt.where(sa.false())

        stmt = apply_filters(stmt, filters, _FILTER_SPECS)

        vt0 = filters.get("viewport_time_start")
        vt1 = filters.get("viewport_time_end")
        if vt0 is not None and vt1 is not None:
            stmt = stmt.where(Annotation.max_x > vt0, Annotation.min_x < vt1)
        vf0 = filters.get("viewport_freq_min")
        vf1 = filters.get("viewport_freq_max")
        if vf0 is not None and vf1 is not None:
            stmt = stmt.where(Annotation.max_y > vf0, Annotation.min_y < vf1)

        if filters.get("creator_name"):
            stmt = stmt.where(User.name.ilike(f"%{filters['creator_name']}%"))
        if filters.get("sound_type"):
            stmt = stmt.where(SoundClassification.sound_type.ilike(f"%{filters['sound_type']}%"))
        if filters.get("taxon_name"):
            stmt = stmt.where(_taxon_name_clause(filters["taxon_name"]))

        return stmt

    def _build_list_detail_query(self, annotation_ids: list[int]):
        """Load the full annotation rows for a page of candidate IDs."""
        if not annotation_ids:
            return None

        order_positions = {annotation_id: idx for idx, annotation_id in enumerate(annotation_ids)}
        order_case = sa.case(order_positions, value=Annotation.annotation_id)

        return (
            select(
                Annotation,
                Media.filename.label("media_name"),
                Media.media_type.label("media_type"),
                Taxon.cached_scientific_name.label("taxon_scientific_name"),
                Taxon.cached_common_name.label("taxon_common_name"),
                SoundClassification.soundscape_component,
                SoundClassification.sound_type,
                User.name.label("creator_name"),
                User.color.label("creator_color"),
            )
            .join(Media, Annotation.media_id == Media.media_id)
            .outerjoin(Taxon, Annotation.taxon_id == Taxon.taxon_id)
            .outerjoin(SoundClassification, Annotation.sound_id == SoundClassification.sound_id)
            .outerjoin(User, Annotation.creator_id == User.user_id)
            .where(Annotation.annotation_id.in_(annotation_ids))
            .order_by(order_case)
        )

    def list_annotations(
        self,
        session: Session,
        accessible_collection_ids: list[int] | None = None,
        current_user_id: int | None = None,
        is_admin: bool = False,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "annotation_id",
        order_dir: str = "asc",
        include_total: bool = True,
        **filters,
    ) -> tuple[list[dict], int]:
        """Get paginated list of annotations with related data."""
        if not is_admin and not accessible_collection_ids and current_user_id is None:
            return [], 0

        candidate_stmt = self._build_list_candidate_query(
            accessible_collection_ids=accessible_collection_ids,
            current_user_id=current_user_id,
            is_admin=is_admin,
            filters=filters,
        )

        total_count = 0
        if include_total:
            count_stmt = select(func.count()).select_from(candidate_stmt.order_by(None).subquery())
            total_count = session.exec(count_stmt).one()

        if (order_by or "annotation_id") == "annotation_id":
            candidate_ids = candidate_stmt.cte("candidate_annotation_ids").prefix_with("MATERIALIZED")
            order_column = (
                candidate_ids.c.annotation_id.desc()
                if order_dir.lower() == "desc"
                else candidate_ids.c.annotation_id.asc()
            )
            page_stmt = select(candidate_ids.c.annotation_id).order_by(order_column)
        else:
            page_stmt = self._build_list_candidate_query(
                accessible_collection_ids=accessible_collection_ids,
                current_user_id=current_user_id,
                is_admin=is_admin,
                filters=filters,
                order_by=order_by,
            )
            page_stmt = apply_ordering(
                page_stmt,
                order_by,
                order_dir,
                _SORT_FIELDS,
                Annotation.annotation_id,
                Annotation.annotation_id,
            )
        page_stmt = apply_pagination(page_stmt, page, page_size)
        annotation_ids = list(session.exec(page_stmt).all())
        detail_stmt = self._build_list_detail_query(annotation_ids)
        results = session.exec(detail_stmt).all() if detail_stmt is not None else []

        rows = [self._format_list_row(row) for row in results]
        return rows, total_count if include_total else len(rows)

    def _format_list_row(self, row) -> dict:
        (
            ann,
            media_name,
            media_type,
            sci_name,
            com_name,
            sc_comp,
            stype,
            creator_name,
            creator_color,
        ) = row
        ann_dict = ann.model_dump()
        ann_dict.update({
            "media_name": media_name,
            "media_type": media_type,
            "taxon_scientific_name": sci_name,
            "taxon_common_name": com_name,
            "soundscape_component": sc_comp,
            "sound_type": stype,
            "creator_name": creator_name,
            "creator_color": creator_color or "#FFFFFF",
        })
        return ann_dict

    def get_annotation_navigation(
        self,
        session: Session,
        annotation_id: int,
        media_id: int,
    ) -> tuple[int | None, int | None]:
        """Return (prev_annotation_id, next_annotation_id) within the same media, ordered by annotation_id."""
        exists = session.exec(
            select(Annotation.annotation_id).where(
                Annotation.media_id == media_id,
                Annotation.annotation_id == annotation_id,
            )
        ).first()
        if exists is None:
            return None, None

        # Adjacent rows only; avoids loading every annotation of the media.
        base = select(Annotation.annotation_id).where(Annotation.media_id == media_id)
        prev_id = session.exec(
            base.where(Annotation.annotation_id < annotation_id)
            .order_by(Annotation.annotation_id.desc())
            .limit(1)
        ).first()
        next_id = session.exec(
            base.where(Annotation.annotation_id > annotation_id)
            .order_by(Annotation.annotation_id.asc())
            .limit(1)
        ).first()
        return prev_id, next_id

# Singleton instance
annotation_repository = AnnotationRepository()
