from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    Collection,
    Media,
    MediaCollection,
    Project,
    SiteCollection,
    User,
)
from app.models.collection import CollectionContributor
from app.models.effective_permission import UserEffectivePermission
from app.models.project import ProjectCollection, ProjectContributor
from app.repositories import permission_repository
from app.services import permission_service
from app.schemas.project_overview import (
    OverviewContributor,
    OverviewStats,
    ProjectOverviewResponse,
)

_ANNOTATION_MEDIA_ID_CHUNK_SIZE = 10_000
_OVERVIEW_MEDIA_TYPES = ("audio", "photo")


def _resolve_overview_collection_ids(
    session: Session,
    current_user: User | None,
    project_id: int,
) -> list[int] | None:
    """
    Resolve accessible collection IDs for project overview stats.
    Returns None if unrestricted (Admin or project:write manager).
    Returns list of collection IDs if restricted to accessible collections.
    """
    if permission_service.is_admin(current_user):
        return None

    if current_user and permission_service.has_resource_permission(
        session, current_user, "project", "write", project_id=project_id
    ):
        return None

    accessible_ids: set[int] = set()
    if current_user and current_user.user_id:
        accessible_ids.update(
            permission_repository.get_accessible_project_collection_ids(
                session,
                current_user.user_id,
                project_id,
                resource_type="collection",
                action="read",
            )
        )

    project = session.get(Project, project_id)
    if project and project.public:
        public_stmt = (
            select(Collection.collection_id)
            .join(ProjectCollection, ProjectCollection.collection_id == Collection.collection_id)
            .where(
                ProjectCollection.project_id == project_id,
                Collection.public_access.is_(True),
            )
        )
        accessible_ids.update(session.scalars(public_stmt).all())

    return sorted({int(cid) for cid in accessible_ids})


def get_project_summary(
    session: Session,
    project_id: int,
    collection_id: int | None = None,
    current_user: User | None = None,
) -> ProjectOverviewResponse:
    if collection_id is not None:
        return _collection_summary(session, collection_id)
    return _project_summary(session, project_id, current_user=current_user)


def _project_summary(
    session: Session,
    project_id: int,
    current_user: User | None = None,
) -> ProjectOverviewResponse:
    project = session.get(Project, project_id)
    accessible_collection_ids = _resolve_overview_collection_ids(
        session, current_user, project_id
    )

    if accessible_collection_ids is not None and len(accessible_collection_ids) == 0:
        stats = OverviewStats(
            users=0,
            collections_or_projects=0,
            audios=0,
            photos=0,
            annotations=0,
            sites=0,
        )
    else:
        if accessible_collection_ids is None:
            project_collections = (
                select(ProjectCollection.collection_id)
                .where(ProjectCollection.project_id == project_id)
                .cte("project_collections")
            )
            col_filter = MediaCollection.collection_id.in_(
                select(project_collections.c.collection_id)
            )
            site_filter = SiteCollection.collection_id.in_(
                select(project_collections.c.collection_id)
            )
            users_count = (
                session.scalar(
                    select(func.count(func.distinct(UserEffectivePermission.user_id))).where(
                        UserEffectivePermission.project_id == project_id
                    )
                )
                or 0
            )
            collections_count = (
                session.scalar(select(func.count()).select_from(project_collections)) or 0
            )
        else:
            col_filter = MediaCollection.collection_id.in_(accessible_collection_ids)
            site_filter = SiteCollection.collection_id.in_(accessible_collection_ids)
            users_count = (
                session.scalar(
                    select(func.count(func.distinct(UserEffectivePermission.user_id))).where(
                        UserEffectivePermission.project_id == project_id,
                        UserEffectivePermission.collection_id.in_(accessible_collection_ids),
                    )
                )
                or 0
            )
            collections_count = len(accessible_collection_ids)

        project_media_rows = session.exec(
            select(Media.media_id, Media.media_type)
            .select_from(MediaCollection)
            .join(Media, Media.media_id == MediaCollection.media_id)
            .where(
                col_filter,
                Media.media_type.in_(_OVERVIEW_MEDIA_TYPES),
                Media.is_metadata.is_(False),
            )
            .distinct()
        ).all()
        audio_media_count = sum(1 for row in project_media_rows if row.media_type == "audio")
        photos_count = sum(1 for row in project_media_rows if row.media_type == "photo")

        media_ids = [row.media_id for row in project_media_rows]
        annotations_count = 0
        for start in range(0, len(media_ids), _ANNOTATION_MEDIA_ID_CHUNK_SIZE):
            chunk = media_ids[start : start + _ANNOTATION_MEDIA_ID_CHUNK_SIZE]
            annotations_count += (
                session.scalar(
                    select(func.count(Annotation.annotation_id)).where(
                        Annotation.media_id.in_(chunk)
                    )
                )
                or 0
            )

        sites_count = (
            session.scalar(
                select(func.count(func.distinct(SiteCollection.site_id)))
                .select_from(SiteCollection)
                .where(site_filter)
            )
            or 0
        )

        stats = OverviewStats(
            users=users_count,
            collections_or_projects=int(collections_count),
            audios=audio_media_count,
            photos=photos_count,
            annotations=annotations_count,
            sites=int(sites_count),
        )

    # contributors: creator first, then project contributors
    creator_id = project.creator_id if project else None
    contributors: list[OverviewContributor] = []
    if creator_id is not None:
        creator = session.get(User, creator_id)
        if creator:
            contributors.append(
                OverviewContributor(
                    user_id=creator.user_id,
                    name=creator.name or "",
                    email=creator.email or "",
                    orcid=creator.orcid,
                    contribution_role="PROJECT CREATOR",
                )
            )

    contrib_stmt = (
        select(
            User.user_id,
            User.name,
            User.email,
            User.orcid,
            ProjectContributor.contribution_role,
        )
        .join(ProjectContributor, User.user_id == ProjectContributor.user_id)
        .where(ProjectContributor.project_id == project_id)
        .where(User.user_id != creator_id if creator_id is not None else True)
        .order_by(User.name)
    )
    contrib_rows = session.exec(contrib_stmt).all()
    contributors.extend(
        OverviewContributor(
            user_id=row.user_id,
            name=row.name or "",
            email=row.email or "",
            orcid=row.orcid,
            contribution_role=row.contribution_role,
        )
        for row in contrib_rows
    )

    return ProjectOverviewResponse(
        stats=stats,
        contributors=contributors,
    )


def _collection_summary(session: Session, collection_id: int) -> ProjectOverviewResponse:
    """Build overview data scoped to a collection."""
    collection = session.get(Collection, collection_id)

    # projects that contain this collection
    # Use the existing repository method to avoid Row-vs-scalar issues
    project_ids = permission_repository.get_project_ids_for_collection(session, collection_id)
    projects_count = len(project_ids)

    # users: distinct users who have any permission on this collection
    users_count = session.scalar(
        select(func.count(func.distinct(UserEffectivePermission.user_id))).where(
            UserEffectivePermission.collection_id == collection_id
        )
    ) or 0

    # audio media (exclude metadata records)
    audio_media_count = session.scalar(
        select(func.count(func.distinct(MediaCollection.media_id)))
        .select_from(MediaCollection)
        .join(Media, Media.media_id == MediaCollection.media_id)
        .where(
            MediaCollection.collection_id == collection_id,
            Media.media_type == "audio",
            Media.is_metadata.is_(False),
        )
    ) or 0

    # photo media
    photos_count = session.scalar(
        select(func.count(func.distinct(MediaCollection.media_id)))
        .select_from(MediaCollection)
        .join(Media, Media.media_id == MediaCollection.media_id)
        .where(
            MediaCollection.collection_id == collection_id,
            Media.media_type == "photo",
        )
    ) or 0

    # annotations
    annotations_count = session.scalar(
        select(func.count(func.distinct(Annotation.annotation_id)))
        .join(MediaCollection, Annotation.media_id == MediaCollection.media_id)
        .where(MediaCollection.collection_id == collection_id)
    ) or 0

    # sites
    sites_count = session.scalar(
        select(func.count(func.distinct(SiteCollection.site_id))).where(
            SiteCollection.collection_id == collection_id
        )
    ) or 0

    stats = OverviewStats(
        users=users_count,
        collections_or_projects=projects_count,
        audios=audio_media_count,
        photos=photos_count,
        annotations=annotations_count,
        sites=sites_count,
    )

    # contributors: creator first, then collection contributors
    creator_id = collection.creator_id if collection else None
    contributors: list[OverviewContributor] = []
    if creator_id is not None:
        creator = session.get(User, creator_id)
        if creator:
            contributors.append(
                OverviewContributor(
                    user_id=creator.user_id,
                    name=creator.name or "",
                    email=creator.email or "",
                    orcid=creator.orcid,
                    contribution_role="COLLECTION CREATOR",
                )
            )

    contrib_stmt = (
        select(
            User.user_id,
            User.name,
            User.email,
            User.orcid,
            CollectionContributor.contribution_role,
        )
        .join(CollectionContributor, User.user_id == CollectionContributor.user_id)
        .where(CollectionContributor.collection_id == collection_id)
        .where(User.user_id != creator_id if creator_id is not None else True)
        .order_by(User.name)
    )
    contrib_rows = session.exec(contrib_stmt).all()
    contributors.extend(
        OverviewContributor(
            user_id=row.user_id,
            name=row.name or "",
            email=row.email or "",
            orcid=row.orcid,
            contribution_role=row.contribution_role,
        )
        for row in contrib_rows
    )

    return ProjectOverviewResponse(
        stats=stats,
        contributors=contributors,
    )
