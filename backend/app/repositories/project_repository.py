from typing import Any, Sequence

from sqlalchemy import union
from sqlalchemy.orm import load_only, selectinload
from sqlmodel import Session, delete, func, select

from app.models import (
    Collection,
    Project,
    ProjectCollection,
    ProjectContributor,
    User,
)
from app.models.effective_permission import UserEffectivePermission
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
)
from app.schemas import ProjectCreate, ProjectUpdate

# Declarative filter specs.
# Special filter: collection_id requires a JOIN, handled manually.
_FILTER_SPECS: list[FilterSpec] = [
    # Exact matches
    ("project_id", Project.project_id, FilterOp.EQ),
    ("uuid",       Project.uuid,       FilterOp.EQ),
    ("creator_id", Project.creator_id, FilterOp.EQ),
    ("public",     Project.public,     FilterOp.EQ),
    ("active",     Project.active,     FilterOp.EQ),
    # Fuzzy matches
    ("name", Project.name, FilterOp.LIKE),
    ("url",  Project.url,  FilterOp.LIKE),
    ("doi",  Project.doi,  FilterOp.LIKE),
    # Date range
    ("creation_date", Project.creation_date, FilterOp.DATE_RANGE),
]

_SORT_FIELDS: dict[str, Any] = {
    "name":          Project.name,
    "project_id":    Project.project_id,
    "uuid":          Project.uuid,
    "url":           Project.url,
    "doi":           Project.doi,
    "creator_name":  User.name,
    "creator_id":    Project.creator_id,
    "creation_date": Project.creation_date,
    "public":        Project.public,
    "active":        Project.active,
}


class ProjectRepository(BaseRepository[Project, ProjectCreate, ProjectUpdate]):
    """
    Repository for Project entity operations.
    """
    
    def __init__(self):
        super().__init__(Project)

    def get_accessible_projects(
        self,
        session: Session,
        user_id: int | None,
        *,
        skip: int = 0,
        limit: int | None = 100,
        order_by: str = "project_id",
        order_dir: str = "asc",
        **kwargs
    ) -> Sequence[Project]:
        """
        Get projects accessible to user with search and sorting support.
        """

        if user_id is None:
            statement = select(Project).where(
                Project.public == True, Project.active == True
            )
        else:
            accessible_subquery = self._build_accessible_project_ids_subquery(user_id)
            statement = select(Project).where(
                Project.project_id.in_(accessible_subquery),
                Project.active == True
            )
        
        # Apply search filter
        statement = self._apply_filters(statement, **kwargs)
        
        # Apply ordering
        statement = self._apply_ordering(statement, order_by, order_dir)
        
        return session.exec(statement.offset(skip).limit(limit)).all()
    
    def _apply_filters(self, statement, **filters):
        """Apply filters to a statement."""
        if filters.get("project_ids") is not None:
            statement = statement.where(Project.project_id.in_(filters["project_ids"]))

        # Special: collection_id requires a join with ProjectCollection
        if filters.get("collection_id") is not None:
            statement = statement.join(
                ProjectCollection,
                ProjectCollection.project_id == Project.project_id,
            ).where(ProjectCollection.collection_id == filters["collection_id"])

        if filters.get("creator_name"):
            statement = statement.outerjoin(User, Project.creator_id == User.user_id)
            statement = statement.where(User.name.ilike(f"%{filters['creator_name']}%"))

        # Standard declarative filters
        statement = apply_filters(statement, filters, _FILTER_SPECS)
        return statement

    def _apply_ordering(self, statement, order_by: str, order_dir: str):
        """Apply ordering to a statement."""
        if order_by == "creator_name":
            statement = statement.outerjoin(User, Project.creator_id == User.user_id)
        return apply_ordering(statement, order_by, order_dir, _SORT_FIELDS, Project.name)
    
    def _build_accessible_project_ids_subquery(self, user_id: int):
        """Build a subquery for accessible project IDs.

        A project is visible if:
        1. It is public and active
        2. User has any permission scoped directly to the project
           (project:read is guaranteed to exist in user_permission when the user
           has any collection or sub-resource permission under that project)
        """
        public_query = select(Project.project_id).where(
            Project.public == True, Project.active == True
        )

        effective_project_query = (
            select(UserEffectivePermission.project_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.project_id.is_not(None),
            )
        )

        return union(public_query, effective_project_query)

    def _build_manageable_project_ids_subquery(self, user_id: int):
        """
        Build a subquery for project IDs manageable by the user.

        A project is manageable if user has:
        1. project-scoped project:write permission
        2. write access on any collection under that project (expanded via view)
        """
        project_write_query = (
            select(UserEffectivePermission.project_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project",
                UserEffectivePermission.resource_type == "project",
                UserEffectivePermission.action == "write",
            )
        )

        collection_write_query = (
            select(UserEffectivePermission.project_id)
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project_collection",
                UserEffectivePermission.resource_type == "collection",
                UserEffectivePermission.action == "write",
            )
        )

        return union(project_write_query, collection_write_query)

    def _build_manageable_project_collection_scopes_subquery(self, user_id: int):
        """
        Build project-local collection scopes manageable by the user.

        The effective permission view expands project:write to every collection in
        that project, while keeping collection:write scoped to that single
        project-collection path.
        """
        return (
            select(
                UserEffectivePermission.project_id,
                UserEffectivePermission.collection_id,
            )
            .where(
                UserEffectivePermission.user_id == user_id,
                UserEffectivePermission.scope_type == "project_collection",
                UserEffectivePermission.resource_type == "collection",
                UserEffectivePermission.action == "write",
            )
            .distinct()
        )
    
    def get_multi_filtered(
        self,
        session: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        order_by: str = "name",
        order_dir: str = "asc",
        **kwargs
    ) -> Sequence[Project]:
        """Get all projects with search and filter (for admin use)."""
        statement = select(Project)
        statement = self._apply_filters(statement, **kwargs)
        statement = self._apply_ordering(statement, order_by, order_dir)
        # creator is read during ProjectPublic serialization; eager-load it to
        # avoid per-row lazy loads.
        statement = statement.options(selectinload(Project.creator))
        return session.exec(statement.offset(skip).limit(limit)).all()
    
    def count_filtered(
        self,
        session: Session,
        **kwargs
    ) -> int:
        """Count all projects with optional filters (for admin use)."""
        statement = select(func.count()).select_from(Project)
        statement = self._apply_filters(statement, **kwargs)
        
        return session.exec(statement).one()

    def get_project_collection_ids(self, session: Session, project_id: int) -> list[int]:
        """Get all collection IDs associated with a project."""
        statement = select(ProjectCollection.collection_id).where(
            ProjectCollection.project_id == project_id
        )
        return list(session.exec(statement).all())

    def get_with_relations(self, session: Session, project_id: int) -> Project | None:
        """Get a project with related entities preloaded (creator).

        Uses selectinload to avoid N+1 queries and DetachedInstanceError.
        """
        statement = (
            select(Project)
            .where(Project.project_id == project_id)
            .options(
                selectinload(Project.creator),
            )
        )
        return session.exec(statement).first()

    def get_by_normalized_name(
        self,
        session: Session,
        *,
        normalized_name: str,
        exclude_project_id: int | None = None,
    ) -> Project | None:
        """Get a project by normalized name (lower + trim), optionally excluding one project."""
        statement = select(Project).where(
            func.lower(func.trim(Project.name)) == normalized_name
        )
        if exclude_project_id is not None:
            statement = statement.where(Project.project_id != exclude_project_id)
        return session.exec(statement).first()

    def get_active_projects_for_cards(
        self,
        session: Session,
        *,
        name: str | None = None,
    ) -> Sequence[Project]:
        """Get all active projects for card display with required relations preloaded."""
        statement = (
            select(Project)
            .options(
                load_only(
                    Project.project_id,
                    Project.name,
                    Project.description,
                    Project.description_short,
                    Project.doi,
                    Project.picture_id,
                    Project.url,
                    Project.public,
                    Project.active,
                ),
                selectinload(Project.creator),
                selectinload(Project.contributors).selectinload(ProjectContributor.user),
            )
            .where(Project.active == True)
        )

        if name:
            statement = statement.where(Project.name.ilike(f"%{name}%"))

        statement = statement.order_by(Project.project_id.asc())
        return session.exec(statement).all()

    def get_accessible_project_ids_for_user(self, session: Session, user_id: int) -> set[int]:
        """Return project IDs the user can access."""
        accessible_subquery = self._build_accessible_project_ids_subquery(user_id)
        accessible_alias = accessible_subquery.subquery()
        rows = session.exec(select(accessible_alias.c.project_id)).all()
        return {row for row in rows if row is not None}

    def get_manageable_project_collection_rows(
        self,
        session: Session,
        *,
        user_id: int | None = None,
        exclude_project_id: int | None = None,
        collection_name: str | None = None,
        project_name: str | None = None,
    ) -> list[tuple[int, str, int, str]]:
        """
        Get project-collection rows for manageable projects.

        Returns tuples:
            (project_id, project_name, collection_id, collection_name)
        """
        statement = (
            select(
                Project.project_id,
                Project.name,
                Collection.collection_id,
                Collection.name,
            )
            .join(ProjectCollection, ProjectCollection.project_id == Project.project_id)
            .join(Collection, Collection.collection_id == ProjectCollection.collection_id)
        )

        if user_id is not None:
            manageable_scopes = self._build_manageable_project_collection_scopes_subquery(
                user_id
            ).subquery()
            statement = statement.join(
                manageable_scopes,
                (
                    (manageable_scopes.c.project_id == ProjectCollection.project_id)
                    & (
                        manageable_scopes.c.collection_id
                        == ProjectCollection.collection_id
                    )
                ),
            )

        if exclude_project_id is not None:
            statement = statement.where(Project.project_id != exclude_project_id)

        if collection_name:
            statement = statement.where(Collection.name.ilike(f"%{collection_name}%"))

        if project_name:
            statement = statement.where(Project.name.ilike(f"%{project_name}%"))

        statement = statement.order_by(Project.name.asc(), Collection.name.asc())
        return list(session.exec(statement).all())

    def get_unassigned_collections(
        self,
        session: Session,
        *,
        collection_ids: list[int] | None = None,
        name: str | None = None,
    ) -> Sequence[Collection]:
        """
        Get collections not linked to any project.
        """
        statement = (
            select(Collection)
            .outerjoin(
                ProjectCollection,
                ProjectCollection.collection_id == Collection.collection_id,
            )
            .where(ProjectCollection.project_id.is_(None))
        )

        if collection_ids is not None:
            if not collection_ids:
                return []
            statement = statement.where(Collection.collection_id.in_(collection_ids))

        if name:
            statement = statement.where(Collection.name.ilike(f"%{name}%"))

        statement = statement.order_by(Collection.name.asc())
        return session.exec(statement).all()

    def add_project_collections(
        self,
        session: Session,
        *,
        project_id: int,
        collection_ids: list[int],
    ) -> None:
        """
        Add project-collection links in batch.
        """
        for collection_id in collection_ids:
            session.add(
                ProjectCollection(
                    project_id=project_id,
                    collection_id=collection_id,
                )
            )

    def remove_project_collections(
        self,
        session: Session,
        *,
        project_id: int,
        collection_ids: list[int],
    ) -> None:
        """
        Remove project-collection links in batch.
        """
        if not collection_ids:
            return
        statement = delete(ProjectCollection).where(
            ProjectCollection.project_id == project_id,
            ProjectCollection.collection_id.in_(collection_ids),
        )
        session.exec(statement)


# Singleton instance
project_repository = ProjectRepository()
