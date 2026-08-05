from typing import Any, Sequence

from sqlalchemy import union
from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, select

from app.models import Collection, CollectionTaxon, User
from app.models.effective_permission import UserEffectivePermission
from app.models.project import Project, ProjectCollection
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
)
from app.schemas import CollectionCreate, CollectionUpdate

# Declarative filter specs.
# Special filters:
#   project_id  – resolved via ProjectCollection subquery (IN)
#   taxon       – requires outerjoin + distinct
_FILTER_SPECS: list[FilterSpec] = [
    # Exact matches
    ("collection_id", Collection.collection_id, FilterOp.EQ),
    ("uuid",          Collection.uuid,          FilterOp.EQ),
    ("doi",           Collection.doi,           FilterOp.LIKE),
    ("creator_id",    Collection.creator_id,    FilterOp.EQ),
    ("public_access", Collection.public_access, FilterOp.EQ),
    ("public_tags",   Collection.public_tags,   FilterOp.EQ),
    # Fuzzy matches
    ("name",               Collection.name,               FilterOp.LIKE),
    ("sphere",             Collection.sphere,             FilterOp.LIKE),
    ("project_url",        Collection.project_url,        FilterOp.LIKE),
    ("external_media_url", Collection.external_media_url, FilterOp.LIKE),
    # Date range
    ("creation_date", Collection.creation_date, FilterOp.DATE_RANGE),
]

_SORT_FIELDS: dict[str, Any] = {
    "name":          Collection.name,
    "collection_id": Collection.collection_id,
    "uuid":          Collection.uuid,
    "doi":           Collection.doi,
    "sphere":        Collection.sphere,
    "project_url":   Collection.project_url,
    "external_media_url": Collection.external_media_url,
    "creation_date": Collection.creation_date,
    "public_access": Collection.public_access,
    "public_tags":   Collection.public_tags,
    "creator_id":    Collection.creator_id,
    "creator_name":  User.name,
    "taxon_name":    CollectionTaxon.cached_name,
}


class CollectionRepository(BaseRepository[Collection, CollectionCreate, CollectionUpdate]):
    """
    Repository for Collection entity operations.
    """
    
    def __init__(self):
        super().__init__(Collection)

    def get_accessible_collections(
        self,
        session: Session,
        user_id: int | None,
        *,
        skip: int = 0,
        limit: int | None = 100,
        order_by: str = "collection_id",
        order_dir: str = "asc",
        action: str = "read",
        **filters
    ) -> Sequence[Collection]:
        """
        获取用户可访问的集合，支持搜索和过滤。 / Get collections accessible to user with search and filter support.
        
        包括公开集合和用户拥有权限的私有集合。 / Includes public collections and private collections user has permission on.
        
        Args:
            session: Database session
            user_id: User ID or None for anonymous
            skip: Number of records to skip
            limit: Maximum number of records to return (None for no limit)
            order_by: Sort field
            order_dir: Sort direction (asc/desc)
            action: Action to check for accessibility (read or write)
            filters: filter parameters (project_id, collection_id, name, etc.)
        """

        # Build base query with accessibility filter
        if user_id is None:
            # Anonymous users only see public collections
            statement = select(Collection).where(Collection.public_access == True)
        else:
            accessible_subquery = self._build_accessible_collection_ids_subquery(user_id, action=action)
            statement = select(Collection).where(
                Collection.collection_id.in_(accessible_subquery)
            )
        
        # Apply filters
        statement = self._apply_filters(statement, **filters)
        
        # Apply ordering
        statement = self._apply_ordering(statement, order_by, order_dir)
        
        # Apply pagination
        statement = statement.offset(skip)
        if limit is not None:
            statement = statement.limit(limit)

        # Apply constraints for avoiding N+1 during Pydantic serialization
        statement = statement.options(
            selectinload(Collection.creator),
            selectinload(Collection.taxons),
            selectinload(Collection.project_collections),
        )

        return session.exec(statement).all()

    def get_accessible_collection_options(
        self,
        session: Session,
        user_id: int | None,
        *,
        action: str = "read",
        **filters,
    ) -> list:
        """Column-only projection of accessible collections for dropdown options."""
        statement = select(
            Collection.collection_id, Collection.name, Collection.sphere
        )
        if user_id is None:
            statement = statement.where(Collection.public_access == True)
        else:
            accessible_subquery = self._build_accessible_collection_ids_subquery(
                user_id, action=action
            )
            statement = statement.where(
                Collection.collection_id.in_(accessible_subquery)
            )
        statement = self._apply_filters(statement, **filters)
        statement = statement.order_by(Collection.collection_id.asc())
        return list(session.exec(statement).all())

    def get_with_relations(self, session: Session, collection_id: int) -> Collection | None:
        """Get collection with related creator and taxons preloaded."""
        statement = (
            select(Collection)
            .where(Collection.collection_id == collection_id)
            .options(
                selectinload(Collection.creator),
                selectinload(Collection.taxons),
            )
        )
        return session.exec(statement).first()
    
    def _apply_filters(self, statement, **filters):
        """Apply filters to a statement."""
        # Special: project_id resolved via IN subquery (no direct join needed)
        if filters.get("project_id") is not None:
            project_collections_subquery = (
                select(ProjectCollection.collection_id)
                .where(ProjectCollection.project_id == filters["project_id"])
            )
            statement = statement.where(
                Collection.collection_id.in_(project_collections_subquery)
            )

        # Special: taxon filter requires outerjoin + ilike + distinct
        if filters.get("taxon_name"):
            statement = (
                statement
                .outerjoin(CollectionTaxon, Collection.collection_id == CollectionTaxon.collection_id)
                .where(CollectionTaxon.cached_name.ilike(f"%{filters['taxon_name']}%"))
                .distinct()
            )

        if filters.get("creator_name"):
            statement = (
                statement
                .outerjoin(User, Collection.creator_id == User.user_id)
                .where(User.name.ilike(f"%{filters['creator_name']}%"))
            )

        # Standard declarative filters
        statement = apply_filters(statement, filters, _FILTER_SPECS)
        return statement

    def _apply_ordering(self, statement, order_by: str, order_dir: str):
        """Apply ordering to a statement."""
        # Sorting by joined-table columns requires the join to be present first.
        if order_by == "creator_name":
            statement = statement.outerjoin(User, Collection.creator_id == User.user_id)
        if order_by == "taxon_name":
            statement = statement.outerjoin(
                CollectionTaxon, Collection.collection_id == CollectionTaxon.collection_id
            )
        return apply_ordering(statement, order_by, order_dir, _SORT_FIELDS, Collection.collection_id)
    
    def _build_accessible_collection_ids_subquery(self, user_id: int, action: str = "read"):
        """
        Build a subquery for accessible collection IDs using the permission view.

        The `user_effective_permissions` view handles all inheritance rules:
        - Direct collection permissions
        - Project-level permissions expanded to all linked collections
        - collection:write implies all sub-resource read/write
        - project:write implies all-access on all project collections

        If action is 'read', public collections are also included.
        If action is 'write', only permission-based access is returned (no public).
        """
        perm_query = (
            select(UserEffectivePermission.collection_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project_collection",
                UserEffectivePermission.collection_id.is_not(None),
                UserEffectivePermission.resource_type == "collection",
                UserEffectivePermission.action == action,
            )
        )

        if action == "read":
            public_query = (
                select(Collection.collection_id)
                .join(ProjectCollection, ProjectCollection.collection_id == Collection.collection_id)
                .join(Project, Project.project_id == ProjectCollection.project_id)
                .where(
                    Collection.public_access == True,
                    Project.public == True,
                )
            )
            return union(public_query, perm_query)
        else:
            return perm_query

    def count_accessible_collections(
        self,
        session: Session,
        user_id: int | None,
        action: str = "read",
        **filters
    ) -> int:
        """
        统计用户可访问的集合数，支持可选过滤项。 / Count accessible collections for a user with optional filters.
        """
        
        if user_id is None:
            # Anonymous users only for read access to public records
            if action != "read":
                return 0
            statement = (
                select(func.count(func.distinct(Collection.collection_id)))
                .select_from(Collection)
                .where(Collection.public_access == True)
            )
        else:
            accessible_subquery = self._build_accessible_collection_ids_subquery(user_id, action=action)
            statement = (
                select(func.count(func.distinct(Collection.collection_id)))
                .select_from(Collection)
                .where(Collection.collection_id.in_(accessible_subquery))
            )
        
        # Apply filters
        statement = self._apply_filters(statement, **filters)
        
        return session.exec(statement).one()

    def get_multi_filtered(
        self,
        session: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        order_by: str = "collection_id",
        order_dir: str = "asc",
        **filters
    ) -> Sequence[Collection]:
        """
        Get all collections with search and filter support (for admin use).
        """
        statement = select(Collection)
        
        # Apply filters
        statement = self._apply_filters(statement, **filters)
        
        # Apply ordering
        statement = self._apply_ordering(statement, order_by, order_dir)
        
        # Apply pagination
        statement = statement.offset(skip).limit(limit)
        
        # Avoid N+1 issues when serializing the relationships
        statement = statement.options(
            selectinload(Collection.creator),
            selectinload(Collection.taxons),
            selectinload(Collection.project_collections),
        )
        
        return session.exec(statement).all()
    
    def count_filtered(
        self,
        session: Session,
        **filters
    ) -> int:
        """
        Count all collections with optional filters (for admin use).
        """
        statement = select(func.count(func.distinct(Collection.collection_id))).select_from(Collection)
        
        # Apply filters
        statement = self._apply_filters(statement, **filters)
        
        return session.exec(statement).one()


# Singleton instance
collection_repository = CollectionRepository()
