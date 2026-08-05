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
from app.schemas.project_overview import (
    OverviewContributor,
    OverviewStats,
    ProjectOverviewResponse,
)

_ANNOTATION_MEDIA_ID_CHUNK_SIZE = 10_000
_OVERVIEW_MEDIA_TYPES = ("audio", "photo")


def get_project_summary(
    session: Session,
    project_id: int,
    collection_id: int | None = None,
) -> ProjectOverviewResponse:
    if collection_id is not None:
        return _collection_summary(session, collection_id)
    return _project_summary(session, project_id)


def _project_summary(session: Session, project_id: int) -> ProjectOverviewResponse:
    project = session.get(Project, project_id)

    users_count = session.scalar(
        select(func.count(func.distinct(UserEffectivePermission.user_id))).where(
            UserEffectivePermission.project_id == project_id
        )
    ) or 0

    project_collections = (
        select(ProjectCollection.collection_id)
        .where(ProjectCollection.project_id == project_id)
        .cte("project_collections")
    )

    collections_count = session.scalar(
        select(func.count()).select_from(project_collections)
    ) or 0

    project_media_rows = session.exec(
        select(Media.media_id, Media.media_type)
        .select_from(MediaCollection)
        .join(Media, Media.media_id == MediaCollection.media_id)
        .where(
            MediaCollection.collection_id.in_(select(project_collections.c.collection_id)),
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
        chunk = media_ids[start:start + _ANNOTATION_MEDIA_ID_CHUNK_SIZE]
        annotations_count += session.scalar(
            select(func.count(Annotation.annotation_id)).where(
                Annotation.media_id.in_(chunk)
            )
        ) or 0

    sites_count = session.scalar(
        select(func.count(func.distinct(SiteCollection.site_id)))
        .select_from(SiteCollection)
        .where(
            SiteCollection.collection_id.in_(select(project_collections.c.collection_id))
        )
    ) or 0

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
