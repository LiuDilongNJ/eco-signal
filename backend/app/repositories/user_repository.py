from typing import Any

from sqlalchemy import and_, false, or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select, func

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import Role, User
from app.models.collection import CollectionContributor
from app.models.effective_permission import UserEffectivePermission
from app.models.project import ProjectContributor
from app.repositories.base import BaseRepository
from app.repositories.query_helpers import FilterOp, FilterSpec, apply_filters, apply_ordering, apply_pagination
from app.schemas import UserCreate, UserUpdate

_FILTER_SPECS: list[FilterSpec] = [
    ("user_id",  User.user_id,  FilterOp.EQ),
    ("active",   User.active,   FilterOp.EQ),
    ("username", User.username, FilterOp.LIKE),
    ("name",     User.name,     FilterOp.LIKE),
    ("email",    User.email,    FilterOp.LIKE),
    ("orcid",    User.orcid,    FilterOp.LIKE),
    ("color",    User.color,    FilterOp.LIKE),
]

_SORT_FIELDS: dict[str, Any] = {
    "user_id":  User.user_id,
    "username": User.username,
    "name":     User.name,
    "email":    User.email,
    "orcid":    User.orcid,
    "active":   User.active,
}


class UserRepository(BaseRepository[User, UserCreate, UserUpdate]):
    """
    Repository for User entity operations.
    """
    
    def __init__(self):
        super().__init__(User)
    
    def create(self, session: Session, *, obj_in: UserCreate) -> User:
        """
        Create a new user with hashed password.

        New users are always assigned the normal "User" role; admin
        promotion is handled separately via the role-assignment API.
        
        Args:
            session: Database session
            obj_in: User creation data
        
        Returns:
            Created user
        """
        role = session.exec(select(Role).where(Role.name == "User")).one()
        db_obj = User.model_validate(
            obj_in,
            update={
                "password": get_password_hash(obj_in.password),
                "role_id": role.role_id,
            },
        )
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj
    
    def update(
        self, session: Session, *, db_obj: User, obj_in: UserUpdate
    ) -> User:
        """
        Update a user, handling password hashing if password is changed.
        
        Args:
            session: Database session
            db_obj: Existing user object
            obj_in: User update data
        
        Returns:
            Updated user
        """
        user_data = obj_in.model_dump(exclude_unset=True)
        extra_data = {}
        if "password" in user_data:
            password = user_data["password"]
            hashed = get_password_hash(password)
            extra_data["password"] = hashed
        
        db_obj.sqlmodel_update(user_data, update=extra_data)
        session.add(db_obj)
        session.commit()
        session.refresh(db_obj)
        return db_obj
    
    def get_by_email(self, session: Session, *, email: str) -> User | None:
        """
        Get a user by email address.
        
        Args:
            session: Database session
            email: User email
        
        Returns:
            User if found, None otherwise
        """
        statement = select(User).where(User.email == email)
        return session.exec(statement).first()
    
    def get_by_username(self, session: Session, *, username: str) -> User | None:
        """
        Get a user by username.
        
        Args:
            session: Database session
            username: Username
        
        Returns:
            User if found, None otherwise
        """
        statement = select(User).where(User.username == username)
        return session.exec(statement).first()

    def authenticate_by_username(
        self, session: Session, *, username: str, password: str
    ) -> User | None:
        """
        Authenticate a user by username and password.
        
        Args:
            session: Database session
            username: Username
            password: User password
        
        Returns:
            User if authenticated, None otherwise
        """
        user = self.get_by_username(session=session, username=username)
        if not user:
            return None
        if not verify_password(password, user.password):
            return None
        return user
    
    def _apply_user_filters(self, base_q, count_q, filters: dict):
        """Apply declarative user field filters to both base and count queries."""
        base_q  = apply_filters(base_q,  filters, _FILTER_SPECS)
        count_q = apply_filters(count_q, filters, _FILTER_SPECS)
        return base_q, count_q

    def _apply_user_ordering(self, query, order_by: str, order_dir: str, contributor_col=None):
        """Apply standard ordering and contributor-aware ordering when context exists."""
        if order_by == "contrib" and contributor_col is not None:
            desc = order_dir.lower() == "desc"
            contrib_order = contributor_col.desc() if desc else contributor_col.asc()
            user_id_order = User.user_id.desc() if desc else User.user_id.asc()
            return query.order_by(
                contrib_order,
                user_id_order,
            )

        return apply_ordering(query, order_by, order_dir, _SORT_FIELDS, User.user_id)

    def _project_scope_user_condition(self, project_ids: list[int]):
        if not project_ids:
            return None

        users_in_projects = select(UserEffectivePermission.user_id).where(
            UserEffectivePermission.project_id.in_(project_ids)
        )
        project_managers = (
            select(UserEffectivePermission.user_id)
            .where(
                UserEffectivePermission.project_id.in_(project_ids),
                UserEffectivePermission.scope_type == "project",
                UserEffectivePermission.resource_type == "project",
                UserEffectivePermission.action == "write",
            )
        )
        return User.user_id.in_(users_in_projects) & ~User.user_id.in_(project_managers)

    def _collection_scope_user_condition(self, collection_scopes: list[tuple[int, int]]):
        if not collection_scopes:
            return None

        pair_filters = [
            and_(
                UserEffectivePermission.project_id == project_id,
                UserEffectivePermission.collection_id == collection_id,
            )
            for project_id, collection_id in collection_scopes
        ]
        collection_scope_filter = or_(*pair_filters)
        project_ids = list({project_id for project_id, _ in collection_scopes})

        users_in_collections = select(UserEffectivePermission.user_id).where(
            UserEffectivePermission.scope_type == "project_collection",
            collection_scope_filter,
        )
        collection_managers = (
            select(UserEffectivePermission.user_id)
            .where(
                UserEffectivePermission.scope_type == "project_collection",
                collection_scope_filter,
                UserEffectivePermission.resource_type == "collection",
                UserEffectivePermission.action == "write",
            )
        )
        parent_project_managers = (
            select(UserEffectivePermission.user_id)
            .where(
                UserEffectivePermission.project_id.in_(project_ids),
                UserEffectivePermission.scope_type == "project",
                UserEffectivePermission.resource_type == "project",
                UserEffectivePermission.action == "write",
            )
        )
        return (
            User.user_id.in_(users_in_collections)
            & ~User.user_id.in_(collection_managers)
            & ~User.user_id.in_(parent_project_managers)
        )

    def build_manager_scope_user_condition(
        self,
        project_ids: list[int],
        collection_scopes: list[tuple[int, int]],
    ):
        conditions = [
            condition
            for condition in (
                self._project_scope_user_condition(project_ids),
                self._collection_scope_user_condition(collection_scopes),
            )
            if condition is not None
        ]
        if not conditions:
            return false()
        return and_(User.role_id != 1, or_(*conditions))

    def get_multi_paginated(
        self,
        session: Session,
        *,
        page: int = 1,
        page_size: int = 15,
        user_id: int | None = None,
        username: str | None = None,
        name: str | None = None,
        email: str | None = None,
        orcid: str | None = None,
        color: str | None = None,
        active: bool | None = None,
        project_id: int | None = None,
        collection_id: int | None = None,
        scope: str = "current",
        contribution_role: str | None = None,
        # Data-permission scope: restrict results (None = unrestricted/admin)
        allowed_project_ids: list[int] | None = None,
        allowed_collection_scopes: list[tuple[int, int]] | None = None,
        order_by: str = "user_id",
        order_dir: str = "asc",
        include_total: bool = True
    ) -> dict:
        """
        Get users with pagination, search, and ordering.

        allowed_project_ids / allowed_collection_scopes: when set (non-None list),
        results are restricted to ordinary users within those manageable scopes.
        None means no restriction (admin path).

        Order fields: user_id, username, name, email, orcid, active
        """
        # Contributor context priority: collection_id > project_id.
        use_scope_all = scope == "all"
        ctx_collection_id = collection_id
        ctx_project_id = None if collection_id is not None else project_id
        contributor_col = None

        # Step 1: Build base query with contributor outerjoin (when context exists).
        if ctx_collection_id is not None:
            base_query = select(User, CollectionContributor).outerjoin(
                CollectionContributor,
                (User.user_id == CollectionContributor.user_id)
                & (CollectionContributor.collection_id == ctx_collection_id)
            )
            contributor_col = CollectionContributor.contribution_role
        elif ctx_project_id is not None:
            base_query = select(User, ProjectContributor).outerjoin(
                ProjectContributor,
                (User.user_id == ProjectContributor.user_id)
                & (ProjectContributor.project_id == ctx_project_id)
            )
            contributor_col = ProjectContributor.contribution_role
        else:
            base_query = select(User)

        count_query = select(func.count(User.user_id)).select_from(User)

        # Step 2: Apply data-permission WHERE.
        if allowed_project_ids is None and allowed_collection_scopes is None:
            # Admin path preserves the original scope semantics.
            if not use_scope_all:
                if ctx_collection_id is not None:
                    dp = (
                        User.user_id.in_(
                            select(UserEffectivePermission.user_id).where(
                                UserEffectivePermission.scope_type == "project_collection",
                                UserEffectivePermission.collection_id == ctx_collection_id,
                            )
                        ) | User.role_id.in_(select(Role.role_id).where(Role.name == settings.ADMIN_ROLE_NAME))
                    )
                elif ctx_project_id is not None:
                    dp = (
                        User.user_id.in_(
                            select(UserEffectivePermission.user_id).where(
                                UserEffectivePermission.project_id == ctx_project_id,
                            )
                        ) | User.role_id.in_(select(Role.role_id).where(Role.name == settings.ADMIN_ROLE_NAME))
                    )
                else:
                    dp = None
            else:
                dp = None
        else:
            dp = self.build_manager_scope_user_condition(
                allowed_project_ids or [],
                allowed_collection_scopes or [],
            )
        if dp is not None:
            base_query = base_query.where(dp)
            count_query = count_query.where(dp)

        # Step 3: Apply contribution_role filter when a contributor context is present.
        if contribution_role is not None:
            if ctx_collection_id is not None:
                base_query = base_query.where(CollectionContributor.contribution_role.ilike(f"%{contribution_role}%"))
                count_query = count_query.where(
                    User.user_id.in_(
                        select(CollectionContributor.user_id).where(
                            CollectionContributor.collection_id == ctx_collection_id,
                            CollectionContributor.contribution_role.ilike(f"%{contribution_role}%"),
                        )
                    )
                )
            elif ctx_project_id is not None:
                base_query = base_query.where(ProjectContributor.contribution_role.ilike(f"%{contribution_role}%"))
                count_query = count_query.where(
                    User.user_id.in_(
                        select(ProjectContributor.user_id).where(
                            ProjectContributor.project_id == ctx_project_id,
                            ProjectContributor.contribution_role.ilike(f"%{contribution_role}%"),
                        )
                    )
                )

        # Build filters dict (excluding None values)
        filters = {k: v for k, v in {
            "user_id": user_id, "username": username, "name": name,
            "email": email, "orcid": orcid, "color": color, "active": active,
        }.items() if v is not None}

        # Apply filters to both queries via shared helper
        base_query, count_query = self._apply_user_filters(base_query, count_query, filters)

        # Apply ordering (base_query only; count doesn't need ordering)
        base_query = self._apply_user_ordering(
            base_query,
            order_by,
            order_dir,
            contributor_col=contributor_col,
        )

        # Execute count (skipped for export-style callers)
        count = session.exec(count_query).one() if include_total else 0
        total_pages = (count + page_size - 1) // page_size if count > 0 else 0

        # Execute paginated data (role is read by admin checks during
        # serialization; eager-load it to avoid lazy loads)
        base_query = base_query.options(selectinload(User.role))
        data = list(session.exec(apply_pagination(base_query, page, page_size)).all())

        if not include_total:
            count = len(data)
            total_pages = 1 if count > 0 else 0

        return {
            "data": data,
            "count": count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_creator_candidates(
        self,
        session: Session,
        *,
        project_id: int,
        collection_id: int | None,
        allowed_project_ids: list[int] | None,
        allowed_collection_scopes: list[tuple[int, int]] | None,
    ) -> list[User]:
        """Return scoped Creator candidates plus all system administrators."""
        admin_condition = User.role_id.in_(
            select(Role.role_id).where(Role.name == settings.ADMIN_ROLE_NAME)
        )
        if allowed_project_ids is None and allowed_collection_scopes is None:
            if collection_id is not None:
                scoped_condition = User.user_id.in_(
                    select(UserEffectivePermission.user_id).where(
                        UserEffectivePermission.project_id == project_id,
                        UserEffectivePermission.collection_id == collection_id,
                        UserEffectivePermission.scope_type == "project_collection",
                    )
                )
            else:
                scoped_condition = User.user_id.in_(
                    select(UserEffectivePermission.user_id).where(
                        UserEffectivePermission.project_id == project_id,
                    )
                )
        else:
            scoped_condition = self.build_manager_scope_user_condition(
                allowed_project_ids or [],
                allowed_collection_scopes or [],
            )

        stmt = (
            select(User)
            .where(or_(scoped_condition, admin_condition))
            .options(selectinload(User.role))
            .order_by(User.name.asc(), User.user_id.asc())
        )
        return list(session.exec(stmt).all())


# Singleton instance
user_repository = UserRepository()
