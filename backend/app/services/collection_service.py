from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, delete, select

from app.csv_export import CsvColumn, export_columns_csv
from app.media_paths import build_media_public_url, logical_project_media_path
from app.models import (
    Collection,
    CollectionContributor,
    CollectionTaxon,
    MediaCollection,
    Project,
    ProjectCollection,
    SiteCollection,
    User,
    UserPermission,
)
from app.repositories import collection_repository, permission_repository
from app.schemas.collection import (
    CollectionCreate,
    CollectionPublic,
    CollectionTaxonResponse,
    CollectionTaxonsSet,
    CollectionUpdate,
    CollectionViewResponse,
)
from app.schemas.response import ApiResponse, PagedApiResponse, api_page
from app.services import permission_service

_COLLECTION_EXPORT_COLUMNS = [
    CsvColumn("collection_id"), CsvColumn("uuid"),
    CsvColumn("name"), CsvColumn("sphere"),
    CsvColumn("project_url"), CsvColumn("external_media_url"),
    CsvColumn("doi"), CsvColumn("creator_name"),
    CsvColumn("creator_id"), CsvColumn("creation_date"),
    CsvColumn("public_access"), CsvColumn("public_tags"),
    CsvColumn("taxon_names", lambda collection: _collection_taxon_names(collection.taxons)),
]


def _collection_taxon_names(taxons: list[object]) -> str:
    """Format collection taxon display names for a single CSV cell."""
    names = sorted(
        {
            taxon.cached_name
            for taxon in taxons
            if getattr(taxon, "cached_name", None)
        }
    )
    return "; ".join(names)


def _ensure_public_collection_allowed_in_projects(session: Session, project_ids: list[int]) -> None:
    """
    Ensure a public collection is only associated with public projects.

    Raises:
        HTTPException: 400 when any associated project is private.
    """
    if not project_ids:
        return

    private_project_ids = list(
        session.exec(
            select(Project.project_id).where(
                Project.project_id.in_(project_ids),
                Project.public == False,
            )
        ).all()
    )
    if private_project_ids:
        raise HTTPException(
            status_code=400,
            detail="Cannot set public_access=true when associated project is private",
        )


def get_collections(
    session: Session,
    user: User | None,
    *,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "collection_id",
    order_dir: str = "asc",
    managed_only: bool = False,
    **filters,
) -> PagedApiResponse[list[CollectionPublic]]:
    """
    获取带搜索和过滤支持的分页集合列表。 / Get paginated list of collections with search and filter support.
    
    - 管理员 (Admins)：自动查看包含私有在内的所有集合 / Admins automatically see all collections
    - 普通用户 (Regular users)：查看公开集合及可访问集合 / Regular users see accessible collections
    - 管理模式 (Managed only)：仅查看拥有写权限的集合 / See collections with write permission only
    
    Filter keys: project_id, collection_id, uuid, name, sphere, project_url,
                 external_media_url, doi, creator_id, creation_date_from,
                 creation_date_to, public_access, public_tags, taxon_name
    """
    skip = (page - 1) * page_size

    # Admins automatically see all collections
    # (Admins manage everything)
    if user and permission_service.is_admin(user):
        collections = collection_repository.get_multi_filtered(
            session, skip=skip, limit=page_size, order_by=order_by, order_dir=order_dir, **filters
        )
        count = collection_repository.count_filtered(session, **filters)
    else:
        # Regular users see accessible collections
        # If managed_only is True, we pass action="write"
        user_id = user.user_id if user else None
        action = "write" if managed_only else "read"
        
        collections = collection_repository.get_accessible_collections(
            session, user_id, skip=skip, limit=page_size, order_by=order_by, 
            order_dir=order_dir, action=action, **filters
        )
        count = collection_repository.count_accessible_collections(
            session, user_id, action=action, **filters
        )
    
    data = []
    for c in collections:
        item = CollectionPublic.model_validate(c)
        item.project_ids = [pc.project_id for pc in c.project_collections]
        item.creator_name = c.creator.name if c.creator else None
        data.append(item)
    return api_page(data=data, total=count, page=page, page_size=page_size)


def get_collection(
    session: Session,
    collection_id: int,
    user: User,
) -> Collection:
    """
    Get a collection by ID.
    
    Requires collection:write permission on any linked project path.
    """
    collection = collection_repository.get(session, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Admins have full access
    if permission_service.is_admin(user):
        return collection

    if permission_service.has_resource_permission_on_any_collection_path(
        session,
        user,
        [collection_id],
        "collection",
        "write",
    ):
        return collection

    raise HTTPException(status_code=403, detail="Access denied")


def get_collection_with_relations(session: Session, collection_id: int) -> Collection:
    """Get a collection by ID with related creator and taxons preloaded."""
    collection = collection_repository.get_with_relations(session, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def build_collection_view_data(project: Project, collection: Collection) -> CollectionViewResponse:
    """Build collection view payload for prototype display."""
    taxon_tags = [t.cached_name for t in collection.taxons if t.cached_name]
    return CollectionViewResponse(
        project_id=project.project_id,
        project_name=project.name or "",
        project_picture_url=(
            build_media_public_url(logical_project_media_path(project.picture_id))
            if project.picture_id
            else ""
        ),
        sphere=collection.sphere or "",
        external_media_url=collection.external_media_url or "",
        project_url=collection.project_url or "",
        collection_id=collection.collection_id,
        collection_name=collection.name or "",
        collection_code=f"col.{collection.collection_id}",
        researcher_name=collection.creator.name if collection.creator and collection.creator.name else "",
        collection_creation_date=collection.creation_date,
        taxon_tags=taxon_tags,
        description=collection.description or "",
    )

def create_collection(
    session: Session,
    collection_in: CollectionCreate,
    creator: User,
    project_id: int,
    *,
    commit: bool = True,
) -> None:
    """
    Create a new collection and associate it with a project.
    
    Requires project:write permission (verified at controller).
    """
    if collection_in.public_access:
        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        _ensure_public_collection_allowed_in_projects(session, [project_id])

    # Add creator_id to the schema data
    collection_data = collection_in.model_dump()
    collection_data["creator_id"] = creator.user_id
    
    # Create Collection instance
    collection = Collection(**collection_data)
    session.add(collection)
    session.flush()  # Get the collection_id before commit
    
    # Create ProjectCollection association
    project_collection = ProjectCollection(
        project_id=project_id,
        collection_id=collection.collection_id
    )
    session.add(project_collection)
    
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(collection)


def update_collection(
    session: Session,
    collection_id: int,
    collection_in: CollectionUpdate,
    user: User
) -> None:
    """
    Update a collection.
    
    Requires collection:write permission.
    """
    collection = collection_repository.get(session, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    if not permission_service.is_admin(user):
        if not permission_service.has_resource_permission_on_any_collection_path(
            session,
            user,
            [collection_id],
            "collection",
            "write",
        ):
            raise HTTPException(status_code=403, detail="Access denied")

    # Update fields
    update_data = collection_in.model_dump(exclude_unset=True)
    if update_data.get("public_access") is True:
        project_ids = permission_repository.get_project_ids_for_collection(session, collection_id)
        _ensure_public_collection_allowed_in_projects(session, project_ids)

    for field, value in update_data.items():
        setattr(collection, field, value)
    
    collection_repository.update(session, db_obj=collection, obj_in=update_data)


def delete_collection(session: Session, collection_id: int, user: User) -> ApiResponse:
    """
    Delete a collection.

    Requires project:write permission on any linked project for non-admin users.
    """
    collection = collection_repository.get(session, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    if not permission_service.is_admin(user):
        project_ids = permission_repository.get_project_ids_for_collection(session, collection_id)
        has_project_write = any(
            permission_service.has_resource_permission(
                session,
                user,
                "project",
                "write",
                project_id=project_id,
            )
            for project_id in project_ids
        )
        if not has_project_write:
            raise HTTPException(status_code=403, detail="Access denied")

    session.exec(delete(UserPermission).where(UserPermission.collection_id == collection_id))
    session.exec(delete(CollectionContributor).where(CollectionContributor.collection_id == collection_id))
    session.exec(delete(CollectionTaxon).where(CollectionTaxon.collection_id == collection_id))
    session.exec(delete(MediaCollection).where(MediaCollection.collection_id == collection_id))
    session.exec(delete(SiteCollection).where(SiteCollection.collection_id == collection_id))
    session.exec(delete(ProjectCollection).where(ProjectCollection.collection_id == collection_id))

    collection_repository.delete(session, id=collection_id)
    return ApiResponse(message="Collection deleted successfully")


def export_collections_csv(
    session: Session,
    user: User,
    project_id: int,
    order_by: str = "collection_id",
    order_dir: str = "asc",
) -> str:
    """
    Export collections to CSV format for a specific project.
    
    Requires project:write permission (verified at controller).
    """
    if permission_service.is_admin(user):
        collections = collection_repository.get_multi_filtered(
            session,
            skip=0,
            limit=None,
            order_by=order_by,
            order_dir=order_dir,
            project_id=project_id,
        )
    else:
        # Get all accessible collections for the project
        collections = collection_repository.get_accessible_collections(
            session,
            user.user_id,
            skip=0,
            limit=None,
            order_by=order_by,
            order_dir=order_dir,
            project_id=project_id,
            action="write",
        )

    data = []
    for collection in collections:
        item = CollectionPublic.model_validate(collection)
        item.project_ids = [pc.project_id for pc in collection.project_collections]
        item.creator_name = collection.creator.name if collection.creator else None
        data.append(item)

    return export_columns_csv(_COLLECTION_EXPORT_COLUMNS, data)


def get_collection_options(
    session: Session, 
    user: User | None, 
    project_id: int | None = None,
    name: str | None = None
) -> list[dict]:
    """
    Get collection options for dropdown menus.
    
    Returns simplified list with only id and name.
    Optionally filtered by project_id and name.
    """
    from app.models.project import Project

    # Anonymous users handling
    if not user:
        if not project_id:
            raise HTTPException(
                status_code=400, 
                detail="project_id is required for unauthenticated requests"
            )
        
        # Check if project exists and is public
        project = session.get(Project, project_id)
        if not project or not project.public:
            return []
            
        # Get public collections for this project (columns only; dropdown
        # options never need full entities or relations)
        rows = collection_repository.get_accessible_collection_options(
            session, None, project_id=project_id, public_access=True, name=name
        )
        return [{"collection_id": r[0], "name": r[1], "sphere": r[2], "can_manage": False} for r in rows]

    # Authenticated users handling
    if permission_service.is_admin(user):
        # Admin sees all collections
        if project_id:
            stmt = (
                select(Collection.collection_id, Collection.name, Collection.sphere)
                .join(ProjectCollection)
                .where(ProjectCollection.project_id == project_id)
            )
        else:
            stmt = select(Collection.collection_id, Collection.name, Collection.sphere)
        
        if name:
            stmt = stmt.where(Collection.name.ilike(f"%{name}%"))
            
        stmt = stmt.order_by(Collection.name)
        results = session.exec(stmt).all()
        return [{"collection_id": r[0], "name": r[1], "sphere": r[2], "can_manage": True} for r in results]
    else:
        # Regular user sees accessible collections (columns only)
        rows = collection_repository.get_accessible_collection_options(
            session, user.user_id, project_id=project_id, name=name
        )

        # Get all collection IDs the user has write access to
        manageable_collection_ids = set(permission_repository.get_accessible_collection_ids(
            session, user.user_id, action="write"
        ))

        return [
            {
                "collection_id": r[0],
                "name": r[1],
                "sphere": r[2],
                "can_manage": r[0] in manageable_collection_ids
            }
            for r in rows
        ]


def list_collection_taxons(
    session: Session,
    collection_id: int,
    _user: User,
) -> list[CollectionTaxonResponse]:
    """
    Get taxons for a specific collection.
    
    Requires read access to the collection (validated at route layer).
    """
    collection = collection_repository.get(session, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    stmt = select(CollectionTaxon).where(CollectionTaxon.collection_id == collection_id)
    taxons = session.exec(stmt).all()

    asserted_ids = {t.asserted_by for t in taxons if t.asserted_by is not None}
    name_map: dict[int, str] = {}
    if asserted_ids:
        rows = session.exec(
            select(User.user_id, User.name).where(User.user_id.in_(asserted_ids))
        ).all()
        name_map = {row[0]: row[1] for row in rows}

    results = []
    for t in taxons:
        response = CollectionTaxonResponse.model_validate(t)
        response.asserted_by_name = name_map.get(t.asserted_by) if t.asserted_by is not None else None
        results.append(response)
    return results


def update_collection_taxons(
    session: Session, 
    collection_id: int, 
    taxons_in: CollectionTaxonsSet, 
    user: User
) -> None:
    """
    Wholesale update of a collection's taxons.
    
    Collection write permission is assumed to be verified at the router level.
    """
    # 1. Verify existence of the collection
    collection = collection_repository.get(session, collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
        
    # 2. Delete all existing taxons for this collection
    session.exec(delete(CollectionTaxon).where(CollectionTaxon.collection_id == collection_id))
    
    # 3. Insert new taxons
    for item in taxons_in.taxons:
        new_taxon = CollectionTaxon(
            collection_id=collection_id,
            col_taxon_id=item.col_taxon_id,
            col_rank=item.col_rank,
            cached_name=item.cached_name,
            notes=item.notes,
            asserted_by=user.user_id,
            asserted_at=datetime.now(UTC)
        )
        session.add(new_taxon)
        
    session.commit()
    session.refresh(collection)
