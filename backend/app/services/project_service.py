import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, select

logger = logging.getLogger(__name__)

from app.csv_export import CsvColumn, export_columns_csv
from app.media_paths import build_media_public_url, logical_project_media_path
from app.models import Collection, Project, ProjectContributor, User, UserPermission
from app.models.project import ProjectCollection
from app.models.site import SiteProject
from app.repositories import permission_repository, project_repository
from app.repositories.site_repository import site_repository
from app.schemas.project import (
    ProjectCardPublic,
    ProjectCreate,
    ProjectPublic,
    ProjectUpdate,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page
from app.services import permission_service

PROJECT_NAME_CONFLICT_DETAIL = "Project with same name already exists"

_PROJECT_EXPORT_COLUMNS = [
    CsvColumn("project_id"), CsvColumn("uuid"), CsvColumn("name"),
    CsvColumn("url"), CsvColumn("doi"), CsvColumn("creator_name"),
    CsvColumn("creator_id"), CsvColumn("creation_date"),
    CsvColumn("public"), CsvColumn("active"),
]


def _ensure_private_project_can_link_collections(
    session: Session,
    project: Project,
    collection_ids: list[int],
) -> None:
    """Ensure private projects do not link public collections."""
    if project.public or not collection_ids:
        return

    public_collection_ids = sorted(
        session.exec(
            select(Collection.collection_id).where(
                Collection.collection_id.in_(collection_ids),
                Collection.public_access.is_(True),
            )
        ).all()
    )
    if public_collection_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot add public collection(s) to a private project: {public_collection_ids}",
        )


def _normalize_project_name(name: str) -> str:
    """Normalize project name for uniqueness checks (trim + lower)."""
    return name.strip().lower()


def _normalize_project_doi(doi: str | None) -> str | None:
    if doi is None:
        return None
    normalized = doi.strip()
    return normalized or None


def get_projects(
    session: Session,
    user: User | None,
    *,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "project_id",
    order_dir: str = "asc",
    **filters,
) -> PagedApiResponse[list[ProjectPublic]]:
    """
    Get paginated list of projects with search and sorting.
    
    Regular users see accessible projects (public + permission-based).
    Admins automatically see all projects including private/inactive ones.
    
    Filter keys: name, url, project_id, uuid, doi, creator_id,
                 creation_date_from, creation_date_to, public, active
    """
    skip = (page - 1) * page_size

    # Admins automatically see all projects
    if user and permission_service.is_admin(user):
        projects = project_repository.get_multi_filtered(
            session, skip=skip, limit=page_size, order_by=order_by, order_dir=order_dir, **filters
        )
        count = project_repository.count_filtered(session, **filters)
    else:
        manageable_project_ids = (
            permission_repository.get_project_ids_with_write_permission(session, user.user_id)
            if user
            else []
        )
        if not manageable_project_ids:
            return api_page(data=[], total=0, page=page, page_size=page_size)
        filters = {**filters, "project_ids": manageable_project_ids}
        projects = project_repository.get_multi_filtered(
            session, skip=skip, limit=page_size, order_by=order_by, order_dir=order_dir, **filters
        )
        count = project_repository.count_filtered(session, **filters)

    data = []
    for p in projects:
        p_dict = p.model_dump()
        if p.creator:
            p_dict["creator_name"] = p.creator.name
        data.append(ProjectPublic.model_validate(p_dict))
    
    return api_page(data=data, total=count, page=page, page_size=page_size)


def get_project(session: Session, project_id: int, user: User | None) -> Project:
    """
    Get a project by ID with preloaded relations (creator, contributors, collections).

    Public projects are visible to everyone.
    Private projects require project:read permission or admin access.
    """
    # Use lightweight get for permission check first
    project = project_repository.get(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Public projects are visible to everyone
    if not project.public:
        # Anonymous users cannot access private projects
        if not user:
            raise HTTPException(status_code=403, detail="Access denied")

        # Admins have full access
        if not permission_service.is_admin(user):
            # Check RBAC permission: project:read (single query via has_project_permission)
            if not permission_service.has_resource_permission(
                session, user, "project", "read", project_id=project_id
            ):
                raise HTTPException(status_code=403, detail="Access denied")

    # Reload with preloaded relations for response serialization
    return project_repository.get_with_relations(session, project_id)


def create_project(
    session: Session,
    project_in: ProjectCreate,
    creator: User,
    *,
    commit: bool = True,
) -> int:
    """
    Create a new project.
    
    Only admins can create projects.
    """
    payload = project_in.model_dump()
    payload["url"] = payload.get("url") or ""
    payload["doi"] = _normalize_project_doi(payload.get("doi"))

    normalized_name = _normalize_project_name(payload["name"])
    existing = project_repository.get_by_normalized_name(
        session,
        normalized_name=normalized_name,
    )
    if existing:
        raise HTTPException(status_code=409, detail=PROJECT_NAME_CONFLICT_DETAIL)

    project = Project(
        **payload,
        creator_id=creator.user_id
    )
    session.add(project)
    try:
        if commit:
            session.commit()
        else:
            session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=PROJECT_NAME_CONFLICT_DETAIL) from exc
    session.refresh(project)
    return project.project_id


def update_project(
    session: Session,
    project_id: int,
    project_in: ProjectUpdate,
) -> None:
    """
    Update a project.
    
    Requires project:write permission.
    """
    project = project_repository.get(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data: dict[str, Any] = project_in.model_dump(exclude_unset=True)

    if "url" in update_data:
        update_data["url"] = update_data.get("url") or ""

    if "doi" in update_data:
        update_data["doi"] = _normalize_project_doi(update_data.get("doi"))

    if "name" in update_data and update_data["name"] is not None:
        normalized_name = _normalize_project_name(update_data["name"])
        existing = project_repository.get_by_normalized_name(
            session,
            normalized_name=normalized_name,
            exclude_project_id=project_id,
        )
        if existing:
            raise HTTPException(status_code=409, detail=PROJECT_NAME_CONFLICT_DETAIL)

    if update_data.get("public") is False:
        has_public_collections = session.exec(
            select(Collection.collection_id)
            .join(ProjectCollection, ProjectCollection.collection_id == Collection.collection_id)
            .where(
                ProjectCollection.project_id == project_id,
                Collection.public_access == True,
            )
            .limit(1)
        ).first()
        if has_public_collections:
            raise HTTPException(
                status_code=400,
                detail="Cannot make project private while it has public collections",
            )

    try:
        project_repository.update(session, db_obj=project, obj_in=update_data)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=PROJECT_NAME_CONFLICT_DETAIL) from exc


def delete_project(session: Session, project_id: int, user: User) -> ApiResponse:
    """
    Delete a project and its project-scoped relationship rows.

    Only admins can delete projects.
    """
    project = project_repository.get(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not permission_service.is_admin(user):
        raise HTTPException(status_code=403, detail="Only admins can delete projects")

    # Delete dependency rows in FK-safe order.
    session.exec(delete(UserPermission).where(UserPermission.project_id == project_id))
    session.exec(delete(ProjectCollection).where(ProjectCollection.project_id == project_id))
    session.exec(delete(SiteProject).where(SiteProject.project_id == project_id))
    session.exec(delete(ProjectContributor).where(ProjectContributor.project_id == project_id))

    project_repository.delete(session, id=project_id)
    return ApiResponse(message="Project deleted successfully")


def export_projects_csv(
    session: Session,
    user: User,
    *,
    project_id: int | None = None,
    collection_id: int | None = None,
    order_by: str = "project_id",
    order_dir: str = "asc",
) -> str:
    """
    Export project data to CSV format based on user permissions.

    - Admin: exports all projects (or filtered by project_id/collection_id)
    - Regular user: exports accessible projects only (optionally filtered)
    """
    filters = dict(
        project_id=project_id,
        collection_id=collection_id,
    )

    if permission_service.is_admin(user):
        projects = project_repository.get_multi_filtered(
            session,
            skip=0,
            limit=None,
            order_by=order_by,
            order_dir=order_dir,
            **filters,
        )
    else:
        manageable_project_ids = permission_repository.get_project_ids_with_write_permission(
            session, user.user_id
        )
        if not manageable_project_ids:
            projects = []
        else:
            filters["project_ids"] = manageable_project_ids
            projects = project_repository.get_multi_filtered(
                session,
                skip=0,
                limit=None,
                order_by=order_by,
                order_dir=order_dir,
                **filters,
            )

    data = []
    for project in projects:
        project_dict = project.model_dump()
        if project.creator:
            project_dict["creator_name"] = project.creator.name
        data.append(ProjectPublic.model_validate(project_dict))

    return export_columns_csv(_PROJECT_EXPORT_COLUMNS, data)


def get_project_options(session: Session, user: User | None, name: str | None = None) -> list[dict]:
    """
    Get project options for dropdown menus.

    Returns simplified list with only id, name, and can_manage flag.
    - Anonymous users: see public projects, can_manage always False
    - Regular users: see public + accessible projects, can_manage based on write permission
    - Admins: see all projects, can_manage always True
    """
    def _get_simple_options(*, can_manage: bool, public_active_only: bool) -> list[dict]:
        stmt = select(Project.project_id, Project.name)
        if public_active_only:
            stmt = stmt.where(Project.public == True, Project.active == True)
        if name:
            stmt = stmt.where(Project.name.ilike(f"%{name}%"))
        stmt = stmt.order_by(Project.name)
        results = session.exec(stmt).all()
        return [
            {"project_id": project_id, "name": project_name, "can_manage": can_manage}
            for project_id, project_name in results
        ]

    if user is None:
        return _get_simple_options(can_manage=False, public_active_only=True)

    if permission_service.is_admin(user):
        return _get_simple_options(can_manage=True, public_active_only=False)

    # Regular user: public + accessible projects (repository already unions both)
    projects = project_repository.get_accessible_projects(
        session,
        user.user_id,
        skip=0,
        limit=None,
        name=name,
        order_by="name",
        order_dir="asc",
    )

    # Batch the manage checks: two permission queries plus one
    # project-collection mapping query instead of per-project (and
    # per-collection) permission lookups.
    manageable_ids = set(
        permission_repository.get_project_ids_with_write_permission(
            session, user.user_id
        )
    )
    write_collection_ids = set(
        permission_repository.get_collection_ids_with_project_write(
            session, user.user_id
        )
    )
    project_collection_map: dict[int, set[int]] = {}
    pending_ids = [
        p.project_id for p in projects if p.project_id not in manageable_ids
    ]
    if pending_ids and write_collection_ids:
        rows = session.exec(
            select(
                ProjectCollection.project_id, ProjectCollection.collection_id
            ).where(ProjectCollection.project_id.in_(pending_ids))
        ).all()
        for pid, cid in rows:
            project_collection_map.setdefault(pid, set()).add(cid)

    def _can_manage(p: Project) -> bool:
        """
        Check if user can manage the project.

        Covers both project-scoped project:write (step 4) and
        collection-scoped project:write (step 3) via the pre-fetched sets.
        """
        if p.project_id in manageable_ids:
            return True
        return bool(
            project_collection_map.get(p.project_id, set()) & write_collection_ids
        )

    return [
        {
            "project_id": p.project_id,
            "name": p.name,
            "can_manage": _can_manage(p),
        }
        for p in projects
    ]


def get_active_project_cards(
    session: Session,
    user: User | None,
    name: str | None = None,
) -> list[ProjectCardPublic]:
    """Get active projects for card-style list display."""
    is_admin = bool(user and permission_service.is_admin(user))
    accessible_ids: set[int] = set()
    if user and not is_admin:
        accessible_ids = project_repository.get_accessible_project_ids_for_user(session, user.user_id)

    projects = project_repository.get_active_projects_for_cards(session, name=name)

    data: list[ProjectCardPublic] = []
    for p in projects:
        can_access = is_admin or p.public or (user is not None and p.project_id in accessible_ids)
        creator_name = p.creator.name if p.creator else ""
        contributors: list[str] = []
        if creator_name:
            contributors.append(creator_name)

        for contributor in p.contributors:
            if contributor.user and contributor.user.name and contributor.user.name not in contributors:
                contributors.append(contributor.user.name)

        data.append(
            ProjectCardPublic(
                project_id=p.project_id,
                name=p.name,
                public=p.public,
                description=p.description,
                description_short=p.description_short,
                doi=p.doi,
                url=p.url if can_access else "",
                can_access=can_access,
                image_url=build_media_public_url(logical_project_media_path(p.picture_id)) if p.picture_id else "",
                creator=creator_name,
                contributors=contributors,
            )
        )

    return data


def get_project_collection_link_options(
    session: Session,
    project_id: int,
    user: User,
    *,
    name: str | None = None,
    other_project_name: str | None = None,
) -> dict:
    """
    Get grouped collection-link options for a project.

    Grouping:
    1. Current project's collections (selected=true)
    2. Other manageable projects' collections excluding current project collections
    3. Unassigned collections (no project links)
    """
    project = project_repository.get(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    current_collection_ids = set(project_repository.get_project_collection_ids(session, project_id))

    manageable_user_id = None if permission_service.is_admin(user) else user.user_id

    # Current project block
    current_rows = project_repository.get_manageable_project_collection_rows(
        session,
        user_id=manageable_user_id,
        exclude_project_id=None,
        collection_name=name,
        project_name=None,
    )
    current_collections: list[dict] = []
    for pid, _pname, cid, cname in current_rows:
        if pid != project_id:
            continue
        current_collections.append(
            {
                "collection_id": cid,
                "name": cname,
                "selected": True,
            }
        )

    # Other projects block
    other_rows = project_repository.get_manageable_project_collection_rows(
        session,
        user_id=manageable_user_id,
        exclude_project_id=project_id,
        collection_name=name,
        project_name=other_project_name,
    )

    duplicates_map: dict[int, set[int]] = {}
    for pid, _pname, cid, _cname in other_rows:
        if cid in current_collection_ids:
            continue
        duplicates_map.setdefault(cid, set()).add(pid)

    other_projects_map: dict[int, dict] = {}
    for pid, pname, cid, cname in other_rows:
        if cid in current_collection_ids:
            continue
        if pid not in other_projects_map:
            other_projects_map[pid] = {
                "project_id": pid,
                "project_name": pname,
                "collections": [],
            }
        other_projects_map[pid]["collections"].append(
            {
                "collection_id": cid,
                "name": cname,
                "selected": False,
                "duplicate_project_ids": sorted(duplicates_map.get(cid, set())),
            }
        )

    other_projects = list(other_projects_map.values())

    # Unassigned block (not linked to any project), still constrained to manageable scope
    manageable_collection_ids: list[int] | None = None
    if not permission_service.is_admin(user):
        manageable_collection_ids = permission_repository.get_accessible_collection_ids(
            session,
            user.user_id,
            resource_type="collection",
            action="write",
        )

    unassigned = project_repository.get_unassigned_collections(
        session,
        collection_ids=manageable_collection_ids,
        name=name,
    )
    unassigned_collections = [
        {
            "collection_id": c.collection_id,
            "name": c.name,
            "selected": False,
        }
        for c in unassigned
        if c.collection_id not in current_collection_ids
    ]

    return {
        "current_project": {
            "project_id": project.project_id,
            "project_name": project.name,
            "collections": current_collections,
        },
        "other_projects": other_projects,
        "unassigned_collections": unassigned_collections,
    }


def sync_project_collections(
    session: Session,
    project_id: int,
    user: User,
    collection_ids: list[int],
) -> None:
    """
    Fully sync project-collection links for a project.
    """
    project = project_repository.get(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    requested_ids = sorted(set(collection_ids))

    # Validate collection existence up-front for clearer error messages.
    existing_collections = session.exec(
        select(Collection.collection_id).where(Collection.collection_id.in_(requested_ids))
    ).all()
    existing_collection_ids = set(existing_collections)
    missing_ids = sorted(set(requested_ids) - existing_collection_ids)
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Collection(s) not found: {missing_ids}",
        )

    if not permission_service.is_admin(user):
        manageable_ids = set(
            permission_repository.get_accessible_collection_ids(
                session,
                user.user_id,
                resource_type="collection",
                action="write",
            )
        )
        disallowed_ids = sorted(set(requested_ids) - manageable_ids)
        if disallowed_ids:
            raise HTTPException(
                status_code=403,
                detail=f"No write permission on collection(s): {disallowed_ids}",
            )

    existing_ids = set(project_repository.get_project_collection_ids(session, project_id))
    requested_set = set(requested_ids)
    to_add = sorted(requested_set - existing_ids)
    to_remove = sorted(existing_ids - requested_set)

    _ensure_private_project_can_link_collections(session, project, to_add)

    if to_add:
        project_repository.add_project_collections(
            session,
            project_id=project_id,
            collection_ids=to_add,
        )
        site_repository.add_project_linked_sites_to_collections(
            session,
            project_id=project_id,
            collection_ids=to_add,
        )
    if to_remove:
        permission_repository.delete_project_collection_permissions(
            session,
            project_id=project_id,
            collection_ids=to_remove,
        )
        project_repository.remove_project_collections(
            session,
            project_id=project_id,
            collection_ids=to_remove,
        )

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        logger.error("Failed to sync project collections: %s", exc.orig)
        raise HTTPException(
            status_code=400,
            detail="Failed to sync project collections due to a data conflict",
        ) from exc
