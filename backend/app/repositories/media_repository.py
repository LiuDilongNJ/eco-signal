from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import String, and_, cast, false, func, literal, or_
from sqlalchemy.orm import aliased, load_only, selectinload
from sqlmodel import Session, select

from app.models import (
    AudioSetting,
    Collection,
    IucnGet,
    Label,
    LabelMedia,
    License,
    Media,
    MediaCollection,
    PhotoSetting,
    Preview,
    ProjectCollection,
    Sensor,
    Site,
    User,
)
from app.repositories.base import BaseRepository
from app.repositories.collection_scope import resolve_project_collection_scope
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
)
from app.schemas.media import MediaUpdate


def _add_one_month(dt: datetime) -> datetime:
    """Return the same timestamp on the first valid day of the next month."""
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1)
    return dt.replace(month=dt.month + 1)


def _timeline_site_key(site_id: int | None) -> str:
    return f"site:{site_id}" if site_id is not None else "nogeo"


_FILTER_SPECS: list[FilterSpec] = [
    # Exact matches
    ("uuid", Media.uuid, FilterOp.EQ),
    ("is_metadata", Media.is_metadata, FilterOp.EQ),
    ("site_id", Media.site_id, FilterOp.EQ),
    ("sensor_id", Media.sensor_id, FilterOp.EQ),
    ("license_id", Media.license_id, FilterOp.EQ),
    ("uploader_id", Media.uploader_id, FilterOp.EQ),
    ("creator_id", Media.creator_id, FilterOp.EQ),
    ("media_id", Media.media_id, FilterOp.EQ),
    # media_type is a low-cardinality enum-like column; exact match keeps it sargable.
    ("media_type", Media.media_type, FilterOp.EQ),
    # Fuzzy matches
    ("medium", Media.medium, FilterOp.LIKE),
    ("name", Media.name, FilterOp.LIKE),
    ("filename", Media.filename, FilterOp.LIKE),
    ("doi", Media.doi, FilterOp.LIKE),
    ("note", Media.note, FilterOp.LIKE),
    # Numeric ranges on Media columns
    ("size_b", Media.size_b, FilterOp.RANGE),
    ("duty_cycle_recording", Media.duty_cycle_recording, FilterOp.RANGE),
    ("duty_cycle_period", Media.duty_cycle_period, FilterOp.RANGE),
    # Numeric ranges on AudioSetting (join must be added first in _apply_filters)
    ("sampling_rate_hz", AudioSetting.sampling_rate_hz, FilterOp.RANGE),
    ("bit_depth", AudioSetting.bit_depth, FilterOp.RANGE),
    ("channel_num", AudioSetting.channel_num, FilterOp.RANGE),
    ("duration_s", AudioSetting.duration_s, FilterOp.RANGE),
    ("recording_gain_db", AudioSetting.recording_gain_db, FilterOp.RANGE),
    # Numeric ranges on PhotoSetting (join must be added first in _apply_filters)
    ("exposure_ms", PhotoSetting.exposure_ms, FilterOp.RANGE),
    ("aperture", PhotoSetting.aperture, FilterOp.RANGE),
    ("iso", PhotoSetting.iso, FilterOp.RANGE),
    # Date ranges
    ("creation_date", Media.creation_date, FilterOp.DATE_RANGE),
    ("date_time", Media.date_time, FilterOp.DATE_RANGE),
]

# Keys backed by AudioSetting columns; any of them (as sort key or *_min/*_max
# range filter) requires the AudioSetting join to already be present.
_AUDIO_SETTING_KEYS = {
    "sampling_rate_hz",
    "duration_s",
    "bit_depth",
    "channel_num",
    "recording_gain_db",
}

# Same contract as _AUDIO_SETTING_KEYS but for the PhotoSetting join.
_PHOTO_SETTING_KEYS = {"exposure_ms", "aperture", "iso"}

_SORT_FIELDS = {
    "media_id": Media.media_id,
    "filename": Media.filename,
    "name": Media.name,
    "creation_date": Media.creation_date,
    "date_time": Media.date_time,
    "media_type": Media.media_type,
    "is_metadata": Media.is_metadata,
    "site_id": Media.site_id,
    "sensor_id": Media.sensor_id,
    "medium": Media.medium,
    "size_b": Media.size_b,
    "duty_cycle_recording": Media.duty_cycle_recording,
    "duty_cycle_period": Media.duty_cycle_period,
    "license_id": Media.license_id,
    "doi": Media.doi,
    "uploader_id": Media.uploader_id,
    "creator_id": Media.creator_id,
    "uploader_name": None,  # Handled in _apply_ordering
    "creator_name": None,  # Handled in _apply_ordering
    "license_name": None,  # Handled in _apply_ordering
    "sampling_rate_hz": AudioSetting.sampling_rate_hz,
    "duration_s": AudioSetting.duration_s,
    "bit_depth": AudioSetting.bit_depth,
    "channel_num": AudioSetting.channel_num,
    "recording_gain_db": AudioSetting.recording_gain_db,
    "exposure_ms": PhotoSetting.exposure_ms,
    "aperture": PhotoSetting.aperture,
    "iso": PhotoSetting.iso,
    "note": Media.note,
    "uuid": Media.uuid,
    "site_name": None,  # Handled in _apply_ordering
    "sensor_name": None,  # Handled in _apply_ordering
}


@dataclass(slots=True)
class MediaTimelineRow:
    """Lightweight row for timeline responses."""

    media_id: int
    media_type: str
    is_metadata: bool
    name: str | None
    filename: str | None
    date_time: datetime
    site_id: int | None
    site_key: str
    duty_cycle_recording: int | None
    duty_cycle_period: int | None
    duration_s: float | None
    creator_name: str | None
    site_name: str | None
    realm_name: str | None
    item_count: int = 1
    end_time: datetime | None = None


def _with_media_detail_relations(query):
    query = query.options(selectinload(Media.audio_setting))
    query = query.options(selectinload(Media.photo_setting))
    query = query.options(selectinload(Media.uploader))
    query = query.options(selectinload(Media.creator))
    query = query.options(selectinload(Media.previews))
    query = query.options(
        selectinload(Media.media_collections).selectinload(MediaCollection.collection)
    )
    query = query.options(
        selectinload(Media.label_media).selectinload(LabelMedia.label)
    )
    query = query.options(selectinload(Media.site).selectinload(Site.realm))
    query = query.options(selectinload(Media.site).selectinload(Site.biome))
    query = query.options(
        selectinload(Media.site).selectinload(Site.functional_type)
    )
    query = query.options(selectinload(Media.sensor))
    query = query.options(selectinload(Media.license))
    return query


class MediaRepository(BaseRepository[Media, dict, MediaUpdate]):
    def __init__(self):
        super().__init__(Media)

    def _apply_visibility_scope(
        self,
        session: Session,
        query,
        filters: dict,
        *,
        visibility: Literal["all", "public", "accessible"],
        user_id: int | None = None,
    ):
        filters = dict(filters)
        # Callers may pre-resolve the scope once so list and count share it.
        if filters.get("scoped_collection_ids") is not None:
            return query, filters

        project_id = filters.get("project_id")
        collection_id = filters.get("collection_id")

        if visibility == "all":
            if project_id is not None:
                filters["scoped_collection_ids"] = resolve_project_collection_scope(
                    session,
                    project_id=project_id,
                    collection_id=collection_id,
                    is_admin=True,
                    include_public=False,
                )
            return query, filters

        # Non-admin media listings are always project-scoped at the API layer;
        # deny rather than leak when the scope is missing.
        if project_id is None:
            return query.where(false()), filters

        # user_id is None for anonymous callers, which limits the scope to
        # public collections.
        filters["scoped_collection_ids"] = resolve_project_collection_scope(
            session,
            project_id=project_id,
            collection_id=collection_id,
            user_id=user_id,
            resource_type="audio",
            action="read",
        )
        return query, filters

    def _apply_relation_profile(self, query, relation_profile: str | None):
        # "detail" eager-loads every relation accessed by full MediaPublic
        # serialization so list/export paths stay free of per-row lazy loads.
        if relation_profile == "detail":
            return _with_media_detail_relations(query)
        if relation_profile == "list":
            query = query.options(
                load_only(
                    Media.media_id,
                    Media.directory,
                    Media.filename,
                    Media.name,
                    Media.media_type,
                    Media.site_id,
                    Media.sensor_id,
                    Media.license_id,
                    Media.medium,
                    Media.date_time,
                    Media.size_b,
                    Media.uploader_id,
                    Media.creator_id,
                    Media.audio_setting_id,
                    Media.duty_cycle_recording,
                    Media.note,
                    Media.doi,
                )
            )
            query = query.options(
                selectinload(Media.audio_setting).load_only(
                    AudioSetting.audio_setting_id,
                    AudioSetting.duration_s,
                    AudioSetting.sampling_rate_hz,
                    AudioSetting.bit_depth,
                    AudioSetting.channel_num,
                    AudioSetting.recording_gain_db,
                )
            )
            query = query.options(
                selectinload(Media.photo_setting).load_only(
                    PhotoSetting.photo_setting_id,
                    PhotoSetting.exposure_ms,
                    PhotoSetting.aperture,
                    PhotoSetting.iso,
                )
            )
            query = query.options(
                selectinload(Media.uploader).load_only(User.user_id, User.name)
            )
            query = query.options(
                selectinload(Media.creator).load_only(User.user_id, User.name)
            )
            query = query.options(
                selectinload(Media.previews).load_only(
                    Preview.preview_id,
                    Preview.media_id,
                    Preview.filename,
                    Preview.type,
                )
            )
            query = query.options(
                selectinload(Media.media_collections)
                .load_only(MediaCollection.media_id, MediaCollection.collection_id)
                .selectinload(MediaCollection.collection)
                .load_only(Collection.collection_id, Collection.sphere)
            )
            query = query.options(
                selectinload(Media.label_media)
                .load_only(LabelMedia.media_id, LabelMedia.label_id)
                .selectinload(LabelMedia.label)
                .load_only(Label.label_id, Label.name)
            )
            query = query.options(
                selectinload(Media.site)
                .load_only(
                    Site.site_id,
                    Site.name,
                    Site.topography_m,
                    Site.freshwater_depth_m,
                    Site.realm_id,
                    Site.biome_id,
                    Site.functional_type_id,
                )
                .selectinload(Site.realm)
                .load_only(IucnGet.iucn_get_id, IucnGet.name)
            )
            query = query.options(
                selectinload(Media.site)
                .load_only(
                    Site.site_id,
                    Site.name,
                    Site.topography_m,
                    Site.freshwater_depth_m,
                    Site.realm_id,
                    Site.biome_id,
                    Site.functional_type_id,
                )
                .selectinload(Site.biome)
                .load_only(IucnGet.iucn_get_id, IucnGet.name)
            )
            query = query.options(
                selectinload(Media.site)
                .load_only(
                    Site.site_id,
                    Site.name,
                    Site.topography_m,
                    Site.freshwater_depth_m,
                    Site.realm_id,
                    Site.biome_id,
                    Site.functional_type_id,
                )
                .selectinload(Site.functional_type)
                .load_only(IucnGet.iucn_get_id, IucnGet.name)
            )
            query = query.options(
                selectinload(Media.sensor).load_only(Sensor.sensor_id, Sensor.name)
            )
            return query.options(
                selectinload(Media.license).load_only(
                    License.license_id, License.name
                )
            )
        if relation_profile == "gallery":
            query = query.options(
                load_only(
                    Media.media_id,
                    Media.directory,
                    Media.filename,
                    Media.name,
                    Media.media_type,
                    Media.date_time,
                    Media.size_b,
                    Media.audio_setting_id,
                    Media.duty_cycle_recording,
                    Media.site_id,
                )
            )
            query = query.options(
                selectinload(Media.audio_setting).load_only(
                    AudioSetting.audio_setting_id,
                    AudioSetting.duration_s,
                    AudioSetting.sampling_rate_hz,
                    AudioSetting.bit_depth,
                    AudioSetting.channel_num,
                    AudioSetting.recording_gain_db,
                )
            )
            query = query.options(selectinload(Media.photo_setting))
            query = query.options(
                selectinload(Media.previews).load_only(
                    Preview.preview_id,
                    Preview.media_id,
                    Preview.filename,
                    Preview.type,
                )
            )
            query = query.options(
                selectinload(Media.media_collections)
                .load_only(MediaCollection.media_id, MediaCollection.collection_id)
                .selectinload(MediaCollection.collection)
                .load_only(Collection.collection_id, Collection.sphere)
            )
            query = query.options(
                selectinload(Media.label_media)
                .load_only(LabelMedia.media_id, LabelMedia.label_id)
                .selectinload(LabelMedia.label)
                .load_only(Label.label_id, Label.name)
            )
            return query.options(
                selectinload(Media.site)
                .load_only(Site.site_id, Site.realm_id)
                .selectinload(Site.realm)
                .load_only(IucnGet.iucn_get_id, IucnGet.name)
            )

        return query

    def _build_filtered_query(
        self,
        session: Session,
        *,
        filters: dict,
        visibility: Literal["all", "public", "accessible"] = "all",
        user_id: int | None = None,
        count: bool = False,
        skip: int = 0,
        limit: int | None = 100,
        order_by: str = "media_id",
        order_dir: str = "asc",
        relation_profile: str | None = None,
    ):
        query = (
            select(func.count(Media.media_id.distinct())).select_from(Media)
            if count
            else select(Media)
        )
        query, scoped_filters = self._apply_visibility_scope(
            session,
            query,
            filters,
            visibility=visibility,
            user_id=user_id,
        )
        query = self._apply_filters(
            query, scoped_filters, order_by=None if count else order_by
        )

        if count:
            return query

        query = self._apply_ordering(query, order_by, order_dir)
        query = self._apply_relation_profile(query, relation_profile)
        if limit is not None:
            query = query.offset(skip).limit(limit)
        elif skip:
            query = query.offset(skip)
        return query

    def _apply_browse_search(
        self,
        query,
        term: str,
        view_type: str,
        current_user_id: int | None,
    ):
        search_term = f"%{term}%"
        query = query.outerjoin(Site, Media.site_id == Site.site_id)
        search_clauses = [Media.name.ilike(search_term)]
        if current_user_id is not None:
            search_clauses.append(
                Media.label_media.any(
                    and_(
                        LabelMedia.user_id == current_user_id,
                        LabelMedia.label.has(Label.name.ilike(search_term)),
                    )
                )
            )

        if view_type == "list":
            query = query.outerjoin(Sensor, Media.sensor_id == Sensor.sensor_id)
            query = query.outerjoin(License, Media.license_id == License.license_id)
            search_clauses.extend(
                [
                    Site.name.ilike(search_term),
                    cast(Site.freshwater_depth_m, String).ilike(search_term),
                    cast(Site.topography_m, String).ilike(search_term),
                    Site.realm.has(IucnGet.name.ilike(search_term)),
                    Site.biome.has(IucnGet.name.ilike(search_term)),
                    Site.functional_type.has(IucnGet.name.ilike(search_term)),
                    Media.medium.ilike(search_term),
                    Sensor.name.ilike(search_term),
                    License.name.ilike(search_term),
                    Media.note.ilike(search_term),
                    Media.uploader.has(User.name.ilike(search_term)),
                    Media.creator.has(User.name.ilike(search_term)),
                    Media.doi.ilike(search_term),
                ]
            )

        return query.where(or_(*search_clauses))

    def _apply_filters(self, query, filters: dict, order_by: str = None):
        filters = dict(filters)
        scoped_collection_ids = filters.get("scoped_collection_ids")
        if scoped_collection_ids is not None:
            if not scoped_collection_ids:
                return query.where(false())
            query = query.where(
                Media.media_collections.any(
                    MediaCollection.collection_id.in_(scoped_collection_ids)
                )
            )

        if filters.get("collection_id") and scoped_collection_ids is None:
            query = query.where(
                Media.media_collections.any(
                    MediaCollection.collection_id == filters["collection_id"]
                )
            )

        if filters.get("search"):
            search_term = f"%{filters['search']}%"
            query = query.where(
                or_(
                    Media.filename.ilike(search_term),
                    Media.name.ilike(search_term),
                    Media.medium.ilike(search_term),
                    Media.note.ilike(search_term),
                )
            )

        type_alias = filters.pop("type", None)
        if type_alias is not None:
            normalized_type = str(type_alias).strip().lower()
            if normalized_type in {"metadata", "meta", "true", "1", "yes"}:
                query = query.where(Media.is_metadata.is_(True))
            elif normalized_type in {"file", "false", "0", "no"}:
                query = query.where(Media.is_metadata.is_(False))
            else:
                query = query.where(false())

        if filters.get("browse_search"):
            query = self._apply_browse_search(
                query,
                filters["browse_search"],
                filters.get("browse_view_type", "list"),
                filters.get("browse_label_user_id"),
            )

        media_types = filters.pop("media_types", None)
        if media_types:
            query = query.where(Media.media_type.in_(media_types))

        # AudioSetting outerjoin – must be added before the audio range specs are applied.
        need_audio_join = (
            any(
                f"{k}_min" in filters or f"{k}_max" in filters
                for k in _AUDIO_SETTING_KEYS
            )
            or order_by in _AUDIO_SETTING_KEYS
        )
        if need_audio_join:
            query = query.outerjoin(
                AudioSetting, Media.audio_setting_id == AudioSetting.audio_setting_id
            )

        need_photo_join = (
            any(
                f"{key}_min" in filters or f"{key}_max" in filters
                for key in _PHOTO_SETTING_KEYS
            )
            or order_by in _PHOTO_SETTING_KEYS
        )
        if need_photo_join:
            query = query.outerjoin(
                PhotoSetting, Media.photo_setting_id == PhotoSetting.photo_setting_id
            )

        if filters.get("label_id"):
            label_user_id = filters.get("label_user_id")
            if label_user_id is None:
                return query.where(false())
            query = query.where(
                Media.label_media.any(
                    and_(
                        LabelMedia.user_id == label_user_id,
                        LabelMedia.label_id == filters["label_id"],
                    )
                )
            )

        if filters.get("site_name"):
            query = query.outerjoin(Site, Media.site_id == Site.site_id)
            query = query.where(Site.name.ilike(f"%{filters['site_name']}%"))
        if filters.get("sensor_name"):
            query = query.outerjoin(Sensor, Media.sensor_id == Sensor.sensor_id)
            query = query.where(Sensor.name.ilike(f"%{filters['sensor_name']}%"))
        if filters.get("license_name"):
            query = query.outerjoin(License, Media.license_id == License.license_id)
            query = query.where(License.name.ilike(f"%{filters['license_name']}%"))
        if filters.get("uploader_name"):
            uploader_alias = aliased(User)
            query = query.outerjoin(uploader_alias, Media.uploader_id == uploader_alias.user_id)
            query = query.where(uploader_alias.name.ilike(f"%{filters['uploader_name']}%"))
        if filters.get("creator_name"):
            creator_alias = aliased(User)
            query = query.outerjoin(creator_alias, Media.creator_id == creator_alias.user_id)
            query = query.where(creator_alias.name.ilike(f"%{filters['creator_name']}%"))
        if filters.get("label_name"):
            label_user_id = filters.get("label_user_id")
            if label_user_id is None:
                return query.where(false())
            query = query.where(
                Media.label_media.any(
                    and_(
                        LabelMedia.user_id == label_user_id,
                        LabelMedia.label.has(Label.name.ilike(f"%{filters['label_name']}%")),
                    )
                )
            )

        query = apply_filters(query, filters, _FILTER_SPECS)
        return query

    def _apply_ordering(self, query, order_by: str, order_dir: str):
        if order_by in {"site_name", "sensor_name", "creator_name", "uploader_name", "license_name"}:
            if order_by == "site_name":
                alias = aliased(Site)
                query = query.outerjoin(alias, Media.site_id == alias.site_id)
            elif order_by == "sensor_name":
                alias = aliased(Sensor)
                query = query.outerjoin(alias, Media.sensor_id == alias.sensor_id)
            elif order_by == "license_name":
                alias = aliased(License)
                query = query.outerjoin(alias, Media.license_id == alias.license_id)
            elif order_by == "uploader_name":
                alias = aliased(User)
                query = query.outerjoin(alias, Media.uploader_id == alias.user_id)
            else:
                alias = aliased(User)
                query = query.outerjoin(alias, Media.creator_id == alias.user_id)

            col = alias.name
            desc = order_dir.lower() == "desc"
            return query.order_by(col.desc() if desc else col.asc()).order_by(
                Media.media_id.asc()
            )

        return apply_ordering(
            query,
            order_by,
            order_dir,
            _SORT_FIELDS,
            Media.media_id,
            tie_break_col=Media.media_id,
        )

    def list_filtered(
        self,
        session: Session,
        *,
        visibility: Literal["all", "public", "accessible"] = "all",
        user_id: int | None = None,
        skip: int = 0,
        limit: int | None = 100,
        order_by: str = "media_id",
        order_dir: str = "asc",
        relation_profile: str | None = None,
        **filters,
    ) -> list[Media]:
        query = self._build_filtered_query(
            session,
            filters=filters,
            visibility=visibility,
            user_id=user_id,
            skip=skip,
            limit=limit,
            order_by=order_by,
            order_dir=order_dir,
            relation_profile=relation_profile,
        )
        return list(session.exec(query).all())

    def count_filtered(
        self,
        session: Session,
        *,
        visibility: Literal["all", "public", "accessible"] = "all",
        user_id: int | None = None,
        **filters,
    ) -> int:
        query = self._build_filtered_query(
            session,
            filters=filters,
            visibility=visibility,
            user_id=user_id,
            count=True,
        )
        return session.exec(query).one()

    def list_options_filtered(
        self,
        session: Session,
        *,
        visibility: Literal["all", "public", "accessible"] = "all",
        user_id: int | None = None,
        **filters,
    ) -> list:
        """Column-only projection for dropdown options; no relation loading, no count."""
        query = select(
            Media.media_id, Media.name, Media.filename, Media.media_type
        ).distinct()
        query, scoped_filters = self._apply_visibility_scope(
            session,
            query,
            filters,
            visibility=visibility,
            user_id=user_id,
        )
        query = self._apply_filters(query, scoped_filters)
        query = query.order_by(Media.media_id.asc())
        return list(session.exec(query).all())

    def get_with_detail_relations(
        self, session: Session, media_id: int
    ) -> Media | None:
        query = select(Media).where(Media.media_id == media_id)
        query = _with_media_detail_relations(query)
        return session.exec(query).first()

    def get_preview_by_media_and_type(
        self,
        session: Session,
        media_id: int,
        preview_type: str,
    ) -> Preview | None:
        query = (
            select(Preview)
            .where(
                Preview.media_id == media_id,
                Preview.type == preview_type,
            )
            .order_by(Preview.preview_id.asc())
        )
        return session.exec(query).first()

    def get_media_timeline_media(
        self,
        session: Session,
        *,
        project_id: int,
        collection_id: int | None = None,
        visible_collection_ids: list[int] | None = None,
        site_ids: list[int] | None = None,
        include_metadata: bool = True,
        media_types: list[str] | None = None,
    ) -> list[MediaTimelineRow]:
        """
        Get lightweight timeline media rows for a project.

        Selection:
        - optional media_types filter (None = no type filter)
        - metadata rows are included only when include_metadata=True
        - metadata overview rows are grouped by month
        - only rows with date_time available (required for timeline start)
        """
        rows = self._get_exact_media_timeline_rows(
            session,
            project_id=project_id,
            collection_id=collection_id,
            visible_collection_ids=visible_collection_ids,
            site_ids=site_ids,
            media_types=media_types,
        )

        if include_metadata:
            rows.extend(
                self._get_monthly_metadata_timeline_rows(
                    session,
                    project_id=project_id,
                    collection_id=collection_id,
                    visible_collection_ids=visible_collection_ids,
                    site_ids=site_ids,
                    media_types=media_types,
                )
            )

        return sorted(rows, key=lambda row: (row.name or "", row.media_id))

    def _timeline_scope_exists(
        self,
        *,
        project_id: int,
        collection_id: int | None,
        visible_collection_ids: list[int] | None,
    ):
        scope = (
            select(literal(1))
            .select_from(MediaCollection)
            .join(
                ProjectCollection,
                ProjectCollection.collection_id == MediaCollection.collection_id,
            )
            .where(MediaCollection.media_id == Media.media_id)
            .where(ProjectCollection.project_id == project_id)
        )

        if collection_id is not None:
            scope = scope.where(MediaCollection.collection_id == collection_id)
        elif visible_collection_ids is not None:
            scope = scope.where(MediaCollection.collection_id.in_(visible_collection_ids))

        return scope.exists()

    def _get_exact_media_timeline_rows(
        self,
        session: Session,
        *,
        project_id: int,
        collection_id: int | None,
        visible_collection_ids: list[int] | None,
        site_ids: list[int] | None,
        media_types: list[str] | None = None,
    ) -> list[MediaTimelineRow]:
        if visible_collection_ids is not None and not visible_collection_ids:
            return []

        scope_exists = self._timeline_scope_exists(
            project_id=project_id,
            collection_id=collection_id,
            visible_collection_ids=visible_collection_ids,
        )
        query = (
            select(
                Media.media_id,
                Media.media_type,
                Media.is_metadata,
                Media.name,
                Media.filename,
                Media.date_time,
                Media.site_id,
                Media.duty_cycle_recording,
                Media.duty_cycle_period,
                AudioSetting.duration_s.label("duration_s"),
                User.name.label("creator_name"),
                Site.name.label("site_name"),
                IucnGet.name.label("realm_name"),
            )
            .outerjoin(
                AudioSetting,
                AudioSetting.audio_setting_id == Media.audio_setting_id,
            )
            .outerjoin(User, User.user_id == Media.creator_id)
            .outerjoin(Site, Site.site_id == Media.site_id)
            .outerjoin(IucnGet, IucnGet.iucn_get_id == Site.realm_id)
            .where(Media.is_metadata.is_(False))
            .where(Media.date_time.is_not(None))
            .where(scope_exists)
        )
        if media_types:
            query = query.where(Media.media_type.in_(media_types))

        if site_ids:
            query = query.where(
                or_(Media.site_id.in_(site_ids), Media.site_id.is_(None))
            )

        query = query.order_by(Media.name.asc(), Media.media_id.asc())
        rows = session.exec(query).all()
        return [
            MediaTimelineRow(
                media_id=row.media_id,
                media_type=row.media_type,
                is_metadata=row.is_metadata,
                name=row.name,
                filename=row.filename,
                date_time=row.date_time,
                site_id=row.site_id,
                site_key=_timeline_site_key(row.site_id),
                duty_cycle_recording=row.duty_cycle_recording,
                duty_cycle_period=row.duty_cycle_period,
                duration_s=row.duration_s,
                creator_name=row.creator_name,
                site_name=row.site_name,
                realm_name=row.realm_name,
                item_count=1,
            )
            for row in rows
        ]

    def _get_monthly_metadata_timeline_rows(
        self,
        session: Session,
        *,
        project_id: int,
        collection_id: int | None,
        visible_collection_ids: list[int] | None,
        site_ids: list[int] | None,
        media_types: list[str] | None = None,
    ) -> list[MediaTimelineRow]:
        if visible_collection_ids is not None and not visible_collection_ids:
            return []

        scope_exists = self._timeline_scope_exists(
            project_id=project_id,
            collection_id=collection_id,
            visible_collection_ids=visible_collection_ids,
        )
        month_start = func.date_trunc("month", Media.date_time).label("month_start")
        grouped_query = (
            select(
                func.min(Media.media_id).label("media_id"),
                func.min(Media.name).label("name"),
                month_start,
                Media.media_type.label("media_type"),
                Media.site_id.label("site_id"),
                func.min(Media.creator_id).label("creator_id"),
                func.count(Media.media_id).label("item_count"),
            )
            .where(Media.is_metadata.is_(True))
            .where(Media.date_time.is_not(None))
            .where(scope_exists)
            .group_by(Media.media_type, Media.site_id, month_start)
        )

        if media_types:
            grouped_query = grouped_query.where(Media.media_type.in_(media_types))

        if site_ids:
            grouped_query = grouped_query.where(
                or_(Media.site_id.in_(site_ids), Media.site_id.is_(None))
            )

        grouped = grouped_query.subquery()
        query = (
            select(
                grouped.c.media_id,
                grouped.c.name,
                grouped.c.month_start,
                grouped.c.media_type,
                grouped.c.site_id,
                grouped.c.item_count,
                User.name.label("creator_name"),
                Site.name.label("site_name"),
                IucnGet.name.label("realm_name"),
            )
            .outerjoin(User, User.user_id == grouped.c.creator_id)
            .outerjoin(Site, Site.site_id == grouped.c.site_id)
            .outerjoin(IucnGet, IucnGet.iucn_get_id == Site.realm_id)
            .order_by(grouped.c.name.asc(), grouped.c.media_id.asc())
        )
        rows = session.exec(query).all()
        return [
            MediaTimelineRow(
                media_id=row.media_id,
                media_type=row.media_type,
                is_metadata=True,
                name=f"Metadata ({int(row.item_count)})",
                filename=None,
                date_time=row.month_start,
                site_id=row.site_id,
                site_key=_timeline_site_key(row.site_id),
                duty_cycle_recording=None,
                duty_cycle_period=None,
                duration_s=None,
                creator_name=row.creator_name,
                site_name=row.site_name,
                realm_name=row.realm_name,
                item_count=int(row.item_count),
                end_time=_add_one_month(row.month_start),
            )
            for row in rows
        ]

    def get_media_timeline_detail_media(
        self,
        session: Session,
        *,
        project_id: int,
        collection_id: int | None = None,
        visible_collection_ids: list[int] | None = None,
        site_key: str,
        start_date: datetime,
        end_date: datetime,
        include_metadata: bool = True,
        media_types: list[str] | None = None,
        limit: int = 5000,
    ) -> tuple[list[MediaTimelineRow], bool]:
        """Get exact timeline rows for one site and visible time window."""
        if visible_collection_ids is not None and not visible_collection_ids:
            return [], False

        scope_exists = self._timeline_scope_exists(
            project_id=project_id,
            collection_id=collection_id,
            visible_collection_ids=visible_collection_ids,
        )
        query = (
            select(
                Media.media_id,
                Media.media_type,
                Media.is_metadata,
                Media.name,
                Media.filename,
                Media.date_time,
                Media.site_id,
                Media.duty_cycle_recording,
                Media.duty_cycle_period,
                AudioSetting.duration_s.label("duration_s"),
                User.name.label("creator_name"),
                Site.name.label("site_name"),
                IucnGet.name.label("realm_name"),
            )
            .outerjoin(
                AudioSetting,
                AudioSetting.audio_setting_id == Media.audio_setting_id,
            )
            .outerjoin(User, User.user_id == Media.creator_id)
            .outerjoin(Site, Site.site_id == Media.site_id)
            .outerjoin(IucnGet, IucnGet.iucn_get_id == Site.realm_id)
            .where(or_(Media.is_metadata.is_(False), Media.is_metadata.is_(include_metadata)))
            .where(Media.date_time.is_not(None))
            .where(Media.date_time >= start_date)
            .where(Media.date_time <= end_date)
            .where(scope_exists)
        )
        if media_types:
            query = query.where(Media.media_type.in_(media_types))

        if site_key == "nogeo":
            query = query.where(Media.site_id.is_(None))
        elif site_key.startswith("site:"):
            query = query.where(Media.site_id == int(site_key.removeprefix("site:")))
        else:
            return [], False

        query = query.order_by(Media.date_time.asc(), Media.media_id.asc()).limit(limit + 1)
        rows = session.exec(query).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        return [
            MediaTimelineRow(
                media_id=row.media_id,
                media_type=row.media_type,
                is_metadata=row.is_metadata,
                name=row.name,
                filename=row.filename,
                date_time=row.date_time,
                site_id=row.site_id,
                site_key=_timeline_site_key(row.site_id),
                duty_cycle_recording=row.duty_cycle_recording,
                duty_cycle_period=row.duty_cycle_period,
                duration_s=row.duration_s,
                creator_name=row.creator_name,
                site_name=row.site_name,
                realm_name=row.realm_name,
                item_count=1,
            )
            for row in rows
        ], has_more

    def bind_to_collections(
        self,
        session: Session,
        *,
        media_id: int,
        collection_ids: list[int],
        added_by: int,
    ) -> None:
        """Bind a media record to collections (replaces existing bindings)."""
        existing = session.exec(
            select(MediaCollection).where(MediaCollection.media_id == media_id)
        ).all()
        for media_collection in existing:
            session.delete(media_collection)

        for collection_id in collection_ids:
            session.add(
                MediaCollection(
                    media_id=media_id,
                    collection_id=collection_id,
                    added_by=added_by,
                )
            )
        session.commit()


# Singleton instance
media_repository = MediaRepository()
