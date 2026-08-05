"""
migrate_from_biosounds.py - One-time database transfer utility.

Reads source data from MySQL and inserts it into PostgreSQL with the required
structural transformations.

This script is designed to be run INSIDE the backend Docker container via docker compose exec,
which gives it access to both the PostgreSQL server (via service name 'db') and the
host machine's MySQL (via host.docker.internal or a provided host). On Linux,
docker-compose.yml must provide the host-gateway mapping for host.docker.internal.

Usage:
    # Full database transfer; file handling is managed by the shell wrapper.
    docker compose exec backend python scripts/migrate_from_biosounds.py

    # Dry-run: preview changes without writing anything.
    docker compose exec backend python scripts/migrate_from_biosounds.py --dry-run

    # Verify only: check data integrity after transfer.
    docker compose exec backend python scripts/migrate_from_biosounds.py --verify

Environment variables:
    MYSQL_HOST          MySQL host inside the backend container (default: host.docker.internal)
    MYSQL_PORT          MySQL port (default: 13306)
    MYSQL_USER          MySQL user (default: root)
    MYSQL_PASSWORD      MySQL password (default: root)
    MYSQL_DB            MySQL database name (default: biosounds)
    POSTGRES_SERVER     PostgreSQL host (default: db)
    POSTGRES_PORT       PostgreSQL port (default: 5432)
    POSTGRES_USER       PostgreSQL user (default: postgres)
    POSTGRES_PASSWORD   PostgreSQL password (default: postgres)
    POSTGRES_DB         PostgreSQL database name (default: ecosignal)
"""

import argparse
import base64
import json
import logging
import os
import re
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from migration_audit import MigrationAudit, write_audit_workbook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

SITE_GEO_ENRICHMENT_STATS = {
    "resolved_gadm_gid_count": 0,
    "resolved_iho_geometry_count": 0,
    "resolved_location_geometry_count": 0,
    "ambiguous_gadm_count": 0,
    "missing_geo_match_count": 0,
}

TAXON_ENRICHMENT_STATS = {
    "matched_count": 0,
    "ambiguous_taxon_match": 0,
    "missing_taxon_match": 0,
}

DERIVED_MIGRATION_STATS = {
    "site_collection": {"skipped_orphan_count": 0, "deduplicated_count": 0},
    "site_project": {"derived_count": 0, "skipped_orphan_count": 0, "deduplicated_count": 0},
    "recorder_microphone": {"derived_count": 0, "skipped_orphan_count": 0, "deduplicated_count": 0},
    "file_upload": {"skipped_orphan_count": 0, "preserved_null_media_count": 0},
}

ACTIVE_AUDIT: MigrationAudit | None = None
CURRENT_BATCH_SIZE = 1_000


def audit_issue(**kwargs: Any) -> None:
    """Record a row-level issue when migration auditing is enabled."""
    if ACTIVE_AUDIT is not None:
        ACTIVE_AUDIT.record(**kwargs)

# ---------------------------------------------------------------------------
# Database connection helpers
# ---------------------------------------------------------------------------


def get_mysql_conn():
    import pymysql  # type: ignore[import-untyped]

    host = os.getenv("MYSQL_HOST", "host.docker.internal")
    port = int(os.getenv("MYSQL_PORT", "13306"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "root")
    db = os.getenv("MYSQL_DB", "biosounds")
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db,
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
    )


def get_pg_conn():
    import psycopg  # type: ignore[import-untyped]

    host = os.getenv("POSTGRES_SERVER", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    db = os.getenv("POSTGRES_DB", "ecosignal")
    return psycopg.connect(
        f"host={host} port={port} user={user} password={password} dbname={db}",
        autocommit=False,
    )


def get_geo_conn():
    import psycopg  # type: ignore[import-untyped]

    host = os.getenv("GEO_DB_SERVER", "geo_db")
    port = os.getenv("GEO_DB_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    db = os.getenv("GEO_DB_NAME", "geo_db")
    return psycopg.connect(
        f"host={host} port={port} user={user} password={password} dbname={db}",
        autocommit=False,
    )


@contextmanager
def mysql_cursor(conn):
    cur = conn.cursor()
    try:
        yield cur
    finally:
        cur.close()


def fetch_all(mysql_conn, sql: str, params=None) -> list[dict]:
    with mysql_cursor(mysql_conn) as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def iter_mysql_rows(mysql_conn, sql: str, *, batch_size: int | None = None) -> Iterator[dict]:
    """Read source rows with a server-side cursor so large tables stay out of memory."""
    import pymysql  # type: ignore[import-untyped]

    size = batch_size or CURRENT_BATCH_SIZE
    try:
        cur = mysql_conn.cursor(pymysql.cursors.SSDictCursor)
    except TypeError:
        cur = mysql_conn.cursor()
    try:
        cur.execute(sql)
        if not hasattr(cur, "fetchmany"):
            yield from cur.fetchall()
            return
        while rows := cur.fetchmany(size):
            yield from rows
    finally:
        cur.close()


def commit_batch(pg_conn, count: int, dry_run: bool) -> None:
    if not dry_run and count and count % CURRENT_BATCH_SIZE == 0:
        pg_conn.commit()


def decode_blob(value) -> str | None:
    """Decode MySQL LONGBLOB/TEXT bytes to UTF-8 string."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def pg_exec(pg_conn, sql: str, params=None) -> int:
    """Execute a single statement and return rowcount."""
    with pg_conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def safe_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def safe_int(value, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def map_legacy_task_type(task_type: str) -> str:
    """Map source task types to target task types."""
    mapping = {
        "recording": "media",
        "tag": "annotation",
    }
    mapped = mapping.get(str(task_type).strip().lower())
    if mapped is None:
        raise ValueError(f"Unsupported source task type: {task_type}")
    return mapped


def normalize_label_type(value) -> str:
    """Normalize source label type values to the target enum."""
    normalized = str(value).strip().lower() if value is not None else "private"
    if normalized in {"private", "public"}:
        return normalized
    log.warning("Unexpected source label type %r; defaulting to private", value)
    return "private"


def normalize_recording_medium(value: str | None) -> str | None:
    """Normalize known recording media while preserving other source values."""
    if value is None:
        return None
    normalized = value.casefold()
    if normalized == "air":
        return "Air"
    if normalized == "water":
        return "Water"
    return value


def truncate_text(value, max_len: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len]


def normalize_media_path(value) -> str | None:
    if value is None:
        return None
    raw = str(value).replace("\\", "/").strip()
    if not raw:
        return None

    for root in (os.getenv("MEDIA_ROOT", "/app/sounds"), os.getenv("LEGACY_MEDIA_ROOT", "/legacy-media")):
        root = root.replace("\\", "/").rstrip("/")
        if root and raw.startswith(f"{root}/"):
            raw = raw[len(root) + 1 :]
            break

    raw = re.sub(r"/+", "/", raw).lstrip("/")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if ".." in parts:
        raise ValueError(f"Invalid media path: {value}")
    while len(parts) > 1 and parts[0] == "sounds" and parts[1] in {"sounds", "images", "projects", "tmp"}:
        parts = parts[1:]
    return "/".join(parts)


def normalize_preview_filename(value) -> str:
    """Keep preview filename in old-project semantics: basename only."""
    normalized = normalize_media_path(value)
    if not normalized:
        return ""
    return Path(normalized).name


def reset_derived_migration_stats() -> None:
    for group in DERIVED_MIGRATION_STATS.values():
        for key in list(group):
            group[key] = 0


LEGACY_FIELD_COVERAGE_SPEC: list[dict[str, object]] = [
    {
        "name": "recorder->recorder",
        "source_table": "recorder",
        "source_fields": ["recorder_id", "model", "version", "brand", "microphone"],
        "target_table": "recorder",
        "target_fields": ["recorder_id", "name", "version", "brand"],
    },
    {
        "name": "user->user+user_preference",
        "source_table": "user",
        "source_fields": ["user_id", "role_id", "project_id", "username", "password", "name", "orcid", "email", "color", "active", "fft"],
        "target_table": '"user"',
        "target_fields": ["user_id", "role_id", "username", "password", "name", "orcid", "email", "active"],
    },
    {
        "name": "collection->collection+project_collection",
        "source_table": "collection",
        "source_fields": [
            "collection_id", "project_id", "name", "user_id", "doi", "note", "view", "sphere",
            "external_recording_url", "project_url", "public_access", "public_tags", "creation_date",
        ],
        "target_table": "collection",
        "target_fields": [
            "collection_id", "name", "creator_id", "doi", "description", "sphere",
            "external_media_url", "project_url", "public_access", "public_tags", "creation_date",
        ],
    },
    {
        "name": "species->taxon",
        "source_table": "species",
        "source_fields": ["species_id", "binomial", "genus", "family", "taxon_order", "class", "common_name", "level", "source"],
        "target_table": "taxon",
        "target_fields": ["taxon_id", "cached_scientific_name", "cached_common_name", "taxonomy_source", "creation_date"],
    },
    {
        "name": "recording->media/audio_setting/media_collection",
        "source_table": "recording",
        "source_fields": [
            "recording_id", "data_type", "col_id", "directory", "filename", "name", "user_id", "site_id",
            "recorder_id", "microphone_id", "license_id", "type", "medium", "recording_gain",
            "duty_cycle_recording", "duty_cycle_period", "note", "file_date", "file_time", "file_size",
            "md5_hash", "sampling_rate", "bitdepth", "channel_num", "duration", "DOI", "creation_date",
        ],
        "target_table": "media",
        "target_fields": [
            "media_id", "directory", "filename", "name", "creator_id", "uploader_id", "site_id",
            "sensor_id", "license_id", "audio_setting_id", "medium", "duty_cycle_recording",
            "duty_cycle_period", "note", "date_time", "size_b", "md5_hash", "doi", "creation_date",
        ],
    },
    {
        "name": "spectrogram->preview",
        "source_table": "spectrogram",
        "source_fields": ["spectrogram_id", "recording_id", "filename", "type", "max_frequency", "fft"],
        "target_table": "preview",
        "target_fields": ["preview_id", "media_id", "filename", "type", "created_date"],
    },
    {
        "name": "label->label",
        "source_table": "label",
        "source_fields": ["label_id", "name", "creator_id", "type", "creation_date"],
        "target_table": "label",
        "target_fields": ["label_id", "name", "creator_id", "type", "creation_date"],
    },
    {
        "name": "file_upload->file_upload",
        "source_table": "file_upload",
        "source_fields": [
            "file_upload_id", "path", "status", "filename", "name", "doi", "note", "license_id", "date", "time",
            "recording_id", "site_id", "collection_id", "directory", "recorder_id", "microphone_id", "species_id",
            "sound_type_id", "subtype", "rating", "type", "medium", "recording_gain", "user_id", "error", "creation_date",
        ],
        "target_table": "file_upload",
        "target_fields": [
            "file_upload_id", "path", "status", "filename", "name", "media_id", "directory", "uploader_id", "error", "upload_date_time",
        ],
    },
]

DERIVED_FIELD_COVERAGE_SPEC: list[dict[str, object]] = [
    {
        "name": "site_collection+collection->site_project",
        "source_tables": ["site_collection", "collection"],
        "derived_fields": ["site_id", "project_id"],
        "target_table": "site_project",
        "target_fields": ["site_id", "project_id"],
    },
    {
        "name": "recording->recorder_microphone",
        "source_tables": ["recording"],
        "derived_fields": ["recorder_id", "microphone_id", "is_default", "notes"],
        "target_table": "recorder_microphone",
        "target_fields": ["recorder_id", "microphone_id", "is_default", "notes"],
    },
]

LEGACY_FIELD_MAP: dict[str, dict[str, str | None]] = {
    "recorder->recorder": {
        "recorder_id": "recorder.recorder_id",
        "model": "recorder.name",
        "version": "recorder.version",
        "brand": "recorder.brand",
        "microphone": None,
    },
    "user->user+user_preference": {
        "user_id": '"user.user_id',
        "role_id": '"user.role_id',
        "project_id": None,
        "username": '"user.username',
        "password": '"user.password',
        "name": '"user.name',
        "orcid": '"user.orcid',
        "email": '"user.email',
        "color": '"user.color',
        "active": '"user.active',
        "fft": "user_preference.fft",
    },
    "collection->collection+project_collection": {
        "collection_id": "collection.collection_id",
        "project_id": "project_collection.project_id",
        "name": "collection.name",
        "user_id": "collection.creator_id",
        "doi": "collection.doi",
        "note": "collection.description",
        "view": None,
        "sphere": "collection.sphere",
        "external_recording_url": "collection.external_media_url",
        "project_url": "collection.project_url",
        "public_access": "collection.public_access",
        "public_tags": "collection.public_tags",
        "creation_date": "collection.creation_date",
    },
    "species->taxon": {
        "species_id": "taxon.taxon_id",
        "binomial": "taxon.cached_scientific_name",
        "genus": None,
        "family": None,
        "taxon_order": None,
        "class": None,
        "common_name": "taxon.cached_common_name",
        "level": None,
        "source": "taxon.taxonomy_source",
    },
    "recording->media/audio_setting/media_collection": {
        "recording_id": "media.media_id",
        "data_type": None,
        "col_id": "media_collection.collection_id",
        "directory": "media.directory",
        "filename": "media.filename",
        "name": "media.name",
        "user_id": "media.creator_id",
        "site_id": "media.site_id",
        "recorder_id": "sensor.recorder_id",
        "microphone_id": "sensor.microphone_id",
        "license_id": "media.license_id",
        "type": None,
        "medium": "media.medium",
        "recording_gain": "audio_setting.recording_gain_db",
        "duty_cycle_recording": "media.duty_cycle_recording",
        "duty_cycle_period": "media.duty_cycle_period",
        "note": "media.note",
        "file_date": "media.date_time",
        "file_time": "media.date_time",
        "file_size": "media.size_b",
        "md5_hash": "media.md5_hash",
        "DOI": "media.doi",
        "sampling_rate": "audio_setting.sampling_rate_hz",
        "bitdepth": "audio_setting.bit_depth",
        "channel_num": "audio_setting.channel_num",
        "duration": "audio_setting.duration_s",
        "creation_date": "media.creation_date",
    },
    "spectrogram->preview": {
        "spectrogram_id": "preview.preview_id",
        "recording_id": "preview.media_id",
        "filename": "preview.filename",
        "type": "preview.type",
        "max_frequency": None,
        "fft": None,
    },
    "label->label": {
        "label_id": "label.label_id",
        "name": "label.name",
        "creator_id": "label.creator_id",
        "type": "label.type",
        "creation_date": "label.creation_date",
    },
    "file_upload->file_upload": {
        "file_upload_id": "file_upload.file_upload_id",
        "path": "file_upload.path",
        "status": "file_upload.status",
        "filename": "file_upload.filename",
        "name": "file_upload.name",
        "doi": None,
        "note": None,
        "license_id": None,
        "date": "file_upload.upload_date_time",
        "time": "file_upload.upload_date_time",
        "recording_id": "file_upload.media_id",
        "site_id": None,
        "collection_id": None,
        "directory": "file_upload.directory",
        "recorder_id": None,
        "microphone_id": None,
        "species_id": None,
        "sound_type_id": None,
        "subtype": None,
        "rating": None,
        "type": None,
        "medium": None,
        "recording_gain": None,
        "user_id": "file_upload.uploader_id",
        "error": "file_upload.error",
        "creation_date": "file_upload.upload_date_time",
    },
}


def parse_legacy_date_time(file_date_val, file_time_val) -> datetime | None:
    if file_date_val in (None, ""):
        return None

    parsed_date: date | None = None
    parsed_time: time = time(0, 0, 0)

    if isinstance(file_date_val, datetime):
        parsed_date = file_date_val.date()
    elif isinstance(file_date_val, date):
        parsed_date = file_date_val
    else:
        date_text = str(file_date_val).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                parsed_date = datetime.strptime(date_text, fmt).date()
                break
            except ValueError:
                continue
        if parsed_date is None:
            return None

    if file_time_val not in (None, ""):
        if isinstance(file_time_val, datetime):
            parsed_time = file_time_val.time()
        elif isinstance(file_time_val, time):
            parsed_time = file_time_val
        else:
            time_text = str(file_time_val).strip()
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    parsed_time = datetime.strptime(time_text, fmt).time()
                    break
                except ValueError:
                    continue

    return datetime.combine(parsed_date, parsed_time)


def normalize_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def reset_enrichment_stats() -> None:
    for stats in (SITE_GEO_ENRICHMENT_STATS, TAXON_ENRICHMENT_STATS):
        for key in stats:
            stats[key] = 0


def pg_fetchall(conn, sql: str, params=None) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def pg_fetchone(conn, sql: str, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def _normalize_datetime_for_compare(value):
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def values_equivalent(old_val, new_val) -> bool:
    if isinstance(old_val, datetime) and isinstance(new_val, datetime):
        return _normalize_datetime_for_compare(old_val) == _normalize_datetime_for_compare(new_val)
    return old_val == new_val


def _lookup_gadm0_by_name(geo_conn, gadm0: str) -> tuple[str | None, str | None, str]:
    rows = pg_fetchall(
        geo_conn,
        """
        SELECT "COUNTRY", "GID_0"
        FROM adm_0
        WHERE lower("COUNTRY") = lower(%s)
        LIMIT 2
        """,
        (gadm0,),
    )
    if not rows:
        return None, None, "missing"
    if len(rows) > 1:
        return None, None, "ambiguous"
    return rows[0][0], rows[0][1], "ok"


def _lookup_gadm1_by_name(geo_conn, gadm0_gid: str, gadm1: str) -> tuple[str | None, str | None, str]:
    rows = pg_fetchall(
        geo_conn,
        """
        SELECT "NAME_1", "GID_1"
        FROM adm_1
        WHERE "GID_0" = %s
          AND lower("NAME_1") = lower(%s)
        LIMIT 2
        """,
        (gadm0_gid, gadm1),
    )
    if not rows:
        return None, None, "missing"
    if len(rows) > 1:
        return None, None, "ambiguous"
    return rows[0][0], rows[0][1], "ok"


def _lookup_gadm2_by_name(
    geo_conn,
    gadm0_gid: str,
    gadm1_gid: str | None,
    gadm2: str,
) -> tuple[str | None, str | None, str, str | None]:
    params: list[Any] = [gadm0_gid, gadm2]
    extra = ""
    if gadm1_gid:
        extra = ' AND "GID_1" = %s'
        params.append(gadm1_gid)
    rows = pg_fetchall(
        geo_conn,
        f"""
        SELECT "NAME_2", "GID_2", "GID_1"
        FROM adm_2
        WHERE "GID_0" = %s
          AND lower("NAME_2") = lower(%s)
          {extra}
        LIMIT 2
        """,
        tuple(params),
    )
    if not rows:
        return None, None, "missing", None
    if len(rows) > 1:
        return None, None, "ambiguous", None
    return rows[0][0], rows[0][1], "ok", rows[0][2]


def _lookup_gadm1_from_gid(geo_conn, gadm1_gid: str) -> tuple[str | None, str | None]:
    row = pg_fetchone(
        geo_conn,
        """
        SELECT "NAME_1", "GID_1"
        FROM adm_1
        WHERE "GID_1" = %s
        LIMIT 1
        """,
        (gadm1_gid,),
    )
    if not row:
        return None, None
    return row[0], row[1]


def _lookup_iho_by_name(geo_conn, iho_name: str) -> tuple[str | None, int | None, str]:
    rows = pg_fetchall(
        geo_conn,
        """
        SELECT id, name
        FROM iho_sea_area
        WHERE lower(name) = lower(%s)
        LIMIT 2
        """,
        (iho_name,),
    )
    if not rows:
        return None, None, "missing"
    if len(rows) > 1:
        return None, None, "ambiguous"
    return rows[0][1], rows[0][0], "ok"


def _fetch_geometry_ewkt(geo_conn, source: str, value) -> str | None:
    if source == "gadm2":
        sql = """
            SELECT ST_AsEWKT(ST_SimplifyPreserveTopology(d.geom, 0.01))
            FROM adm_2,
                 LATERAL ST_Dump(geometry) AS d(path, geom)
            WHERE "GID_2" = %s
            ORDER BY ST_Area(d.geom::geography) DESC
            LIMIT 1
        """
    elif source == "gadm1":
        sql = """
            SELECT ST_AsEWKT(ST_SimplifyPreserveTopology(d.geom, 0.01))
            FROM adm_1,
                 LATERAL ST_Dump(geometry) AS d(path, geom)
            WHERE "GID_1" = %s
            ORDER BY ST_Area(d.geom::geography) DESC
            LIMIT 1
        """
    elif source == "gadm0":
        sql = """
            SELECT ST_AsEWKT(ST_SimplifyPreserveTopology(d.geom, 0.01))
            FROM adm_0,
                 LATERAL ST_Dump(geometry) AS d(path, geom)
            WHERE "GID_0" = %s
            ORDER BY ST_Area(d.geom::geography) DESC
            LIMIT 1
        """
    else:
        sql = """
            SELECT ST_AsEWKT(ST_SimplifyPreserveTopology(d.geom, 0.01))
            FROM iho_sea_area,
                 LATERAL ST_Dump(geometry) AS d(path, geom)
            WHERE id = %s
            ORDER BY ST_Area(d.geom::geography) DESC
            LIMIT 1
        """
    row = pg_fetchone(geo_conn, sql, (value,))
    return row[0] if row else None


def resolve_site_enrichment(
    geo_conn,
    *,
    gadm0: str | None,
    gadm1: str | None,
    gadm2: str | None,
    iho: str | None,
) -> dict[str, Any]:
    result = {
        "gadm0": normalize_text(gadm0),
        "gadm1": normalize_text(gadm1),
        "gadm2": normalize_text(gadm2),
        "gadm0_gid": None,
        "gadm1_gid": None,
        "gadm2_gid": None,
        "iho": normalize_text(iho),
        "location_wkt": None,
        "location_iho_wkt": None,
    }

    if not geo_conn:
        return result

    if result["gadm0"]:
        g0_name, g0_gid, status = _lookup_gadm0_by_name(geo_conn, result["gadm0"])
        if status == "ambiguous":
            SITE_GEO_ENRICHMENT_STATS["ambiguous_gadm_count"] += 1
        elif status == "missing":
            SITE_GEO_ENRICHMENT_STATS["missing_geo_match_count"] += 1
        else:
            result["gadm0"] = g0_name
            result["gadm0_gid"] = g0_gid
            SITE_GEO_ENRICHMENT_STATS["resolved_gadm_gid_count"] += 1

    if result["gadm0_gid"] and result["gadm1"]:
        g1_name, g1_gid, status = _lookup_gadm1_by_name(geo_conn, result["gadm0_gid"], result["gadm1"])
        if status == "ambiguous":
            SITE_GEO_ENRICHMENT_STATS["ambiguous_gadm_count"] += 1
        elif status == "missing":
            SITE_GEO_ENRICHMENT_STATS["missing_geo_match_count"] += 1
        else:
            result["gadm1"] = g1_name
            result["gadm1_gid"] = g1_gid
            SITE_GEO_ENRICHMENT_STATS["resolved_gadm_gid_count"] += 1

    if result["gadm0_gid"] and result["gadm2"]:
        g2_name, g2_gid, status, inferred_g1_gid = _lookup_gadm2_by_name(
            geo_conn,
            result["gadm0_gid"],
            result["gadm1_gid"],
            result["gadm2"],
        )
        if status == "ambiguous":
            SITE_GEO_ENRICHMENT_STATS["ambiguous_gadm_count"] += 1
        elif status == "missing":
            SITE_GEO_ENRICHMENT_STATS["missing_geo_match_count"] += 1
        else:
            result["gadm2"] = g2_name
            result["gadm2_gid"] = g2_gid
            SITE_GEO_ENRICHMENT_STATS["resolved_gadm_gid_count"] += 1
            if result["gadm1_gid"] is None and inferred_g1_gid:
                g1_name, g1_gid = _lookup_gadm1_from_gid(geo_conn, inferred_g1_gid)
                result["gadm1"] = g1_name
                result["gadm1_gid"] = g1_gid

    if result["gadm2_gid"]:
        result["location_wkt"] = _fetch_geometry_ewkt(geo_conn, "gadm2", result["gadm2_gid"])
    elif result["gadm1_gid"]:
        result["location_wkt"] = _fetch_geometry_ewkt(geo_conn, "gadm1", result["gadm1_gid"])
    elif result["gadm0_gid"]:
        result["location_wkt"] = _fetch_geometry_ewkt(geo_conn, "gadm0", result["gadm0_gid"])
    if result["location_wkt"]:
        SITE_GEO_ENRICHMENT_STATS["resolved_location_geometry_count"] += 1

    if result["iho"]:
        iho_name, iho_id, status = _lookup_iho_by_name(geo_conn, result["iho"])
        if status == "missing":
            SITE_GEO_ENRICHMENT_STATS["missing_geo_match_count"] += 1
        elif status == "ok" and iho_id is not None:
            result["iho"] = iho_name
            result["location_iho_wkt"] = _fetch_geometry_ewkt(geo_conn, "iho", iho_id)
            if result["location_iho_wkt"]:
                SITE_GEO_ENRICHMENT_STATS["resolved_iho_geometry_count"] += 1

    return result


def _detect_remote_taxon_table(geo_conn) -> str:
    for table_name in ("col_xr_taxon_species", "geo_col_xr_taxon_species"):
        row = pg_fetchone(
            geo_conn,
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        if row:
            return table_name
    raise RuntimeError("XR taxon dictionary table is unavailable")


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[idx: idx + size] for idx in range(0, len(values), size)]


def _query_taxon_match_by_name(
    geo_conn,
    table_name: str,
    rank: str,
    value: str,
) -> list[dict[str, Any]]:
    rank_sql = {
        "species": """
            SELECT col_species_id, col_genus_id, col_family_id, col_order_id, col_class_id,
                   cached_scientific_name, cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(cached_scientific_name) = lower(%s)
            GROUP BY col_species_id, col_genus_id, col_family_id, col_order_id, col_class_id,
                     cached_scientific_name, cached_common_name
            LIMIT 2
        """,
        "genus": """
            SELECT NULL AS col_species_id, col_genus_id, col_family_id, col_order_id, col_class_id,
                   col_genus_name AS cached_scientific_name, NULL AS cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(col_genus_name) = lower(%s)
            GROUP BY col_genus_id, col_family_id, col_order_id, col_class_id, col_genus_name
            LIMIT 2
        """,
        "family": """
            SELECT NULL AS col_species_id, NULL AS col_genus_id, col_family_id, col_order_id, col_class_id,
                   col_family_name AS cached_scientific_name, NULL AS cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(col_family_name) = lower(%s)
            GROUP BY col_family_id, col_order_id, col_class_id, col_family_name
            LIMIT 2
        """,
        "order": """
            SELECT NULL AS col_species_id, NULL AS col_genus_id, NULL AS col_family_id, col_order_id, col_class_id,
                   col_order_name AS cached_scientific_name, NULL AS cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(col_order_name) = lower(%s)
            GROUP BY col_order_id, col_class_id, col_order_name
            LIMIT 2
        """,
        "class": """
            SELECT NULL AS col_species_id, NULL AS col_genus_id, NULL AS col_family_id, NULL AS col_order_id, col_class_id,
                   col_class_name AS cached_scientific_name, NULL AS cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(col_class_name) = lower(%s)
            GROUP BY col_class_id, col_class_name
            LIMIT 2
        """,
    }
    rows = pg_fetchall(geo_conn, rank_sql[rank].format(table=table_name), (value,))
    keys = (
        "col_species_id",
        "col_genus_id",
        "col_family_id",
        "col_order_id",
        "col_class_id",
        "cached_scientific_name",
        "cached_common_name",
        "taxonomy_source",
        "imported_at",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _query_taxon_matches_by_names(
    geo_conn,
    table_name: str,
    rank: str,
    values: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not values:
        return {}

    rank_sql = {
        "species": """
            SELECT lower(cached_scientific_name) AS match_key,
                   col_species_id, col_genus_id, col_family_id, col_order_id, col_class_id,
                   cached_scientific_name, cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(cached_scientific_name) = ANY(%s)
            GROUP BY lower(cached_scientific_name), col_species_id, col_genus_id, col_family_id, col_order_id, col_class_id,
                     cached_scientific_name, cached_common_name
        """,
        "genus": """
            SELECT lower(col_genus_name) AS match_key,
                   NULL AS col_species_id, col_genus_id, col_family_id, col_order_id, col_class_id,
                   col_genus_name AS cached_scientific_name, NULL AS cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(col_genus_name) = ANY(%s)
            GROUP BY lower(col_genus_name), col_genus_id, col_family_id, col_order_id, col_class_id, col_genus_name
        """,
        "family": """
            SELECT lower(col_family_name) AS match_key,
                   NULL AS col_species_id, NULL AS col_genus_id, col_family_id, col_order_id, col_class_id,
                   col_family_name AS cached_scientific_name, NULL AS cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(col_family_name) = ANY(%s)
            GROUP BY lower(col_family_name), col_family_id, col_order_id, col_class_id, col_family_name
        """,
        "order": """
            SELECT lower(col_order_name) AS match_key,
                   NULL AS col_species_id, NULL AS col_genus_id, NULL AS col_family_id, col_order_id, col_class_id,
                   col_order_name AS cached_scientific_name, NULL AS cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(col_order_name) = ANY(%s)
            GROUP BY lower(col_order_name), col_order_id, col_class_id, col_order_name
        """,
        "class": """
            SELECT lower(col_class_name) AS match_key,
                   NULL AS col_species_id, NULL AS col_genus_id, NULL AS col_family_id, NULL AS col_order_id, col_class_id,
                   col_class_name AS cached_scientific_name, NULL AS cached_common_name,
                   COALESCE(MAX(taxonomy_source), 'CatalogueOfLife-XR') AS taxonomy_source,
                   MAX(imported_at) AS imported_at
            FROM {table}
            WHERE lower(col_class_name) = ANY(%s)
            GROUP BY lower(col_class_name), col_class_id, col_class_name
        """,
    }
    keys = (
        "match_key",
        "col_species_id",
        "col_genus_id",
        "col_family_id",
        "col_order_id",
        "col_class_id",
        "cached_scientific_name",
        "cached_common_name",
        "taxonomy_source",
        "imported_at",
    )
    mapping: dict[str, list[dict[str, Any]]] = {}
    for batch in _chunked(sorted(set(values)), 500):
        rows = pg_fetchall(geo_conn, rank_sql[rank].format(table=table_name), (batch,))
        for row in rows:
            row_dict = dict(zip(keys, row, strict=True))
            match_key = row_dict.pop("match_key")
            mapping.setdefault(match_key, []).append(row_dict)
    return mapping


def build_taxon_lookup_cache(geo_conn, species_rows: list[dict[str, Any]], table_name: str | None = None) -> dict[str, dict[str, list[dict[str, Any]]]]:
    if not geo_conn:
        return {}
    remote_table = table_name or _detect_remote_taxon_table(geo_conn)
    rank_value_getters = {
        "species": lambda row: normalize_text(row.get("binomial")),
        "genus": lambda row: normalize_text(row.get("genus")),
        "family": lambda row: normalize_text(row.get("family")),
        "order": lambda row: normalize_text(row.get("taxon_order")),
        "class": lambda row: normalize_text(row.get("class")),
    }
    cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for rank, getter in rank_value_getters.items():
        normalized_values = [
            value.lower()
            for value in (getter(row) for row in species_rows)
            if value
        ]
        cache[rank] = _query_taxon_matches_by_names(geo_conn, remote_table, rank, normalized_values)
    return cache


def _select_unique_taxon_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    unique_rows = {
        (
            row.get("col_species_id"),
            row.get("col_genus_id"),
            row.get("col_family_id"),
            row.get("col_order_id"),
            row.get("col_class_id"),
            row.get("cached_scientific_name"),
            row.get("cached_common_name"),
            row.get("taxonomy_source"),
        )
        for row in rows
    }
    if len(unique_rows) != 1:
        return None
    return rows[0]


def _lookup_cached_taxon_row(
    lookup_cache: dict[str, dict[str, list[dict[str, Any]]]] | None,
    rank: str,
    value: str | None,
) -> dict[str, Any] | None:
    if lookup_cache is None:
        return None
    normalized = normalize_text(value)
    if not normalized:
        return None
    return _select_unique_taxon_row(lookup_cache.get(rank, {}).get(normalized.lower(), []))


def _fill_taxon_hierarchy_gaps(
    matched_row: dict[str, Any],
    *,
    genus: str | None,
    family: str | None,
    taxon_order: str | None,
    taxon_class: str | None,
    lookup_cache: dict[str, dict[str, list[dict[str, Any]]]] | None,
) -> dict[str, Any]:
    enriched = dict(matched_row)
    supplemental_lookups = (
        ("genus", "col_genus_id", genus),
        ("family", "col_family_id", family),
        ("order", "col_order_id", taxon_order),
        ("class", "col_class_id", taxon_class),
    )
    for rank, field, source_value in supplemental_lookups:
        if enriched.get(field):
            continue
        supplemental = _lookup_cached_taxon_row(lookup_cache, rank, source_value)
        if supplemental is None:
            continue
        for target_field in ("col_genus_id", "col_family_id", "col_order_id", "col_class_id"):
            if not enriched.get(target_field) and supplemental.get(target_field):
                enriched[target_field] = supplemental.get(target_field)
        if not enriched.get("taxonomy_source") and supplemental.get("taxonomy_source"):
            enriched["taxonomy_source"] = supplemental.get("taxonomy_source")
        if not enriched.get("imported_at") and supplemental.get("imported_at"):
            enriched["imported_at"] = supplemental.get("imported_at")
    return enriched


def resolve_taxon_enrichment(
    geo_conn,
    *,
    binomial: str | None,
    genus: str | None,
    family: str | None,
    taxon_order: str | None,
    taxon_class: str | None,
    common_name: str | None,
    source: str | None,
    lookup_cache: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    remote_table: str | None = None,
) -> dict[str, Any]:
    fallback = {
        "col_species_id": None,
        "col_genus_id": None,
        "col_family_id": None,
        "col_order_id": None,
        "col_class_id": None,
        "cached_scientific_name": normalize_text(binomial),
        "cached_common_name": normalize_text(common_name),
        "taxonomy_source": normalize_text(source) or "CatalogueOfLife",
        "last_synced": None,
    }
    if not geo_conn:
        TAXON_ENRICHMENT_STATS["missing_taxon_match"] += 1
        return fallback

    rank_candidates = [
        ("species", normalize_text(binomial)),
        ("genus", normalize_text(genus)),
        ("family", normalize_text(family)),
        ("order", normalize_text(taxon_order)),
        ("class", normalize_text(taxon_class)),
    ]
    for rank, value in rank_candidates:
        if not value:
            continue
        if lookup_cache is not None:
            rows = lookup_cache.get(rank, {}).get(value.lower(), [])
        else:
            table_name = remote_table or _detect_remote_taxon_table(geo_conn)
            rows = _query_taxon_match_by_name(geo_conn, table_name, rank, value)
        if not rows:
            continue
        if len(rows) > 1:
            TAXON_ENRICHMENT_STATS["ambiguous_taxon_match"] += 1
            return fallback
        row = _fill_taxon_hierarchy_gaps(
            rows[0],
            genus=genus,
            family=family,
            taxon_order=taxon_order,
            taxon_class=taxon_class,
            lookup_cache=lookup_cache,
        )
        TAXON_ENRICHMENT_STATS["matched_count"] += 1
        matched_scientific_name = (
            row.get("cached_scientific_name")
            if rank == "species"
            else fallback["cached_scientific_name"]
        )
        return {
            "col_species_id": row.get("col_species_id"),
            "col_genus_id": row.get("col_genus_id"),
            "col_family_id": row.get("col_family_id"),
            "col_order_id": row.get("col_order_id"),
            "col_class_id": row.get("col_class_id"),
            "cached_scientific_name": matched_scientific_name or fallback["cached_scientific_name"],
            "cached_common_name": fallback["cached_common_name"] or row.get("cached_common_name"),
            "taxonomy_source": row.get("taxonomy_source") or "CatalogueOfLife-XR",
            "last_synced": row.get("imported_at") or now_utc(),
        }

    TAXON_ENRICHMENT_STATS["missing_taxon_match"] += 1
    return fallback


RESET_TRUNCATE_TABLES = [
    "task",
    "annotation_review",
    "annotation",
    "preview",
    "media_collection",
    "media",
    "audio_setting",
    "photo_setting",
    "file_upload",
    "index_log",
    "label_media",
    "label",
    "news",
    "queue",
    "site_project",
    "site_collection",
    "project_collection",
    "project_contributor",
    "collection_contributor",
    "collection_taxon",
    "operation_log",
    "user_permission",
    "user_preference",
    '"user"',
    "project",
    "collection",
    "site",
    "taxon",
    "sensor",
    "microphone",
    "recorder",
    "license",
    "role",
    "iucn_get",
    "sound_classification",
    "taxon_sound_type",
    "annotation_review_status",
    "index_type",
    "model",
]


def target_has_business_data(pg_conn) -> bool:
    tables = ("project", "collection", "site", "media", "annotation", "preview", "user_permission")
    with pg_conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            if cur.fetchone()[0] > 0:
                return True
    return False


def reset_target_data(pg_conn) -> None:
    with pg_conn.cursor() as cur:
        for table in RESET_TRUNCATE_TABLES:
            cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")  # noqa: S608
    log.info("Target business data cleared.")


# ---------------------------------------------------------------------------
# Phase 1: Base / reference data (simple direct copies)
# ---------------------------------------------------------------------------


def migrate_roles(mysql_conn, pg_conn, dry_run: bool) -> int:
    rows = fetch_all(mysql_conn, "SELECT role_id, name FROM role")
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                "INSERT INTO role (role_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (r["role_id"], r["name"]),
            )
        count += 1
    return count


def migrate_licenses(mysql_conn, pg_conn, dry_run: bool) -> int:
    rows = fetch_all(mysql_conn, "SELECT license_id, name, link FROM license")
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                "INSERT INTO license (license_id, name, link) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (r["license_id"], r["name"], r["link"]),
            )
        count += 1
    return count


def migrate_iucn_get(mysql_conn, pg_conn, dry_run: bool) -> int:
    rows = fetch_all(mysql_conn, "SELECT iucn_get_id, pid, name, level FROM iucn_get")
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                "INSERT INTO iucn_get (iucn_get_id, pid, name, level) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (r["iucn_get_id"], r["pid"], r["name"], r["level"]),
            )
        count += 1
    return count


def migrate_recorders(mysql_conn, pg_conn, dry_run: bool) -> int:
    # Old recorder has a 'microphone' varchar column that doesn't exist in new schema
    rows = iter_mysql_rows(
        mysql_conn, "SELECT recorder_id, model, version, brand FROM recorder"
    )
    count = 0
    for r in rows:
        if not dry_run:
            new_uuid = uuid.uuid4()
            pg_exec(
                pg_conn,
                "INSERT INTO recorder (recorder_id, uuid, name, version, brand) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (r["recorder_id"], new_uuid, r["model"], r["version"], r["brand"]),
            )
        count += 1
    return count


def migrate_microphones(mysql_conn, pg_conn, dry_run: bool) -> int:
    rows = fetch_all(
        mysql_conn,
        "SELECT microphone_id, name, microphone_element, sensitivity, signal_to_noise_ratio FROM microphone",
    )
    count = 0
    for r in rows:
        if not dry_run:
            new_uuid = uuid.uuid4()
            pg_exec(
                pg_conn,
                """INSERT INTO microphone (microphone_id, uuid, name, microphone_element, sensitivity, signal_to_noise_ratio)
                   VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (
                    r["microphone_id"],
                    new_uuid,
                    r["name"],
                    r["microphone_element"],
                    r["sensitivity"],
                    r["signal_to_noise_ratio"],
                ),
            )
        count += 1
    return count


def migrate_sound_classification(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: sound → New: sound_classification"""
    rows = fetch_all(
        mysql_conn, "SELECT sound_id, soundscape_component, sound_type FROM sound"
    )
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                "INSERT INTO sound_classification (sound_id, soundscape_component, sound_type) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (r["sound_id"], r["soundscape_component"], r["sound_type"]),
            )
        count += 1
    return count


def migrate_taxon_sound_type(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: sound_type → New: taxon_sound_type"""
    rows = fetch_all(
        mysql_conn,
        "SELECT sound_type_id, name, taxon_class, taxon_order FROM sound_type",
    )
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                "INSERT INTO taxon_sound_type (taxon_sound_type_id, name, taxon_class, taxon_order) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    r["sound_type_id"],
                    r["name"],
                    r["taxon_class"],
                    r["taxon_order"],
                ),
            )
        count += 1
    return count


def migrate_annotation_review_status(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: tag_review_status → New: annotation_review_status"""
    rows = fetch_all(
        mysql_conn,
        "SELECT tag_review_status_id, name FROM tag_review_status",
    )
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                "INSERT INTO annotation_review_status (annotation_review_status_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (r["tag_review_status_id"], r["name"]),
            )
        count += 1
    return count


def _infer_index_param_value_type(value: str | None) -> str:
    if value in {None, "", "None"}:
        return "string"
    if value in {"True", "False", "true", "false"}:
        return "boolean"
    try:
        float(value)
    except (TypeError, ValueError):
        return "string"
    return "number"


def _parse_index_param_string(raw_param: str | None) -> str:
    if not raw_param:
        return "[]"

    parameters: list[dict[str, Any]] = []
    for part in raw_param.split("!"):
        if "|" not in part:
            continue
        key, default = part.split("|", 1)
        default = default.removeprefix("default: ").strip()
        value_type = _infer_index_param_value_type(default)
        if default == "None":
            parsed_default: Any = None
        elif value_type == "boolean":
            parsed_default = default.lower() == "true"
        elif value_type == "number":
            parsed_default = float(default) if any(token in default.lower() for token in (".", "e")) else int(default)
        else:
            parsed_default = default
        parameters.append({"key": key, "default": parsed_default, "value_type": value_type})
    return json.dumps(parameters)


def migrate_index_type(mysql_conn, pg_conn, dry_run: bool) -> int:
    """param changes from varchar → structured JSON array."""
    rows = fetch_all(
        mysql_conn,
        "SELECT index_id, name, param, description, URL FROM index_type",
    )
    count = 0
    for r in rows:
        param_val = _parse_index_param_string(r["param"])

        if not dry_run:
            pg_exec(
                pg_conn,
                "INSERT INTO index_type (index_id, name, param, description, url) VALUES (%s, %s, %s::json, %s, %s) ON CONFLICT DO NOTHING",
                (r["index_id"], r["name"], param_val, r["description"], r["URL"]),
            )
        count += 1
    return count


def migrate_models(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: models (tf_model_id) → New: model (model_id)"""
    rows = fetch_all(
        mysql_conn,
        "SELECT tf_model_id, name, tf_model_path, labels_path, source_URL, description, parameter FROM models",
    )
    count = 0
    for r in rows:
        param_val = decode_blob(r["parameter"])
        if param_val and isinstance(param_val, str):
            try:
                json.loads(param_val)
            except (json.JSONDecodeError, ValueError):
                param_val = json.dumps({"raw": param_val})
        elif not param_val:
            param_val = None

        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO model (model_id, name, model_path, labels_path, source_url, description, parameter)
                   VALUES (%s, %s, %s, %s, %s, %s, %s::json)
                   ON CONFLICT DO NOTHING""",
                (
                    r["tf_model_id"],
                    r["name"],
                    r["tf_model_path"],
                    r["labels_path"],
                    r["source_URL"],
                    decode_blob(r["description"]),
                    param_val,
                ),
            )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Phase 2: Core entities
# ---------------------------------------------------------------------------


def migrate_users(mysql_conn, pg_conn, dry_run: bool) -> int:
    """user → user + user_preference; fft is moved to user_preference."""
    rows = fetch_all(
        mysql_conn,
        "SELECT user_id, role_id, username, password, name, orcid, email, color, active, fft FROM user",
    )
    seen_usernames: set[str] = set()
    count = 0
    for r in rows:
        username = (r["username"] or "").strip()
        if not username:
            username = f"user_{r['user_id']}"

        if username in seen_usernames:
            base = username[:14]
            username = f"{base}_{r['user_id']}"
            log.warning(
                "Duplicate source username detected; remapped user_id=%s username=%s",
                r["user_id"],
                username,
            )
            audit_issue(
                source_table="user", source_id=r["user_id"], target_table='"user"', target_id=r["user_id"],
                issue_type="field_mismatch", severity="warning", field_name="username",
                source_value=r["username"], target_value=username,
                reason="Duplicate source username was remapped to satisfy the target uniqueness constraint.",
                recommended_action="Review the remapped username before granting user access.",
            )
        seen_usernames.add(username)

        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO "user" (user_id, role_id, username, password, name, orcid, email, color, active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["user_id"],
                    r["role_id"],
                    username,
                    r["password"],
                    r["name"],
                    r["orcid"],
                    r["email"],
                    truncate_text(r.get("color"), 7) or "#FFFFFF",
                    safe_bool(r["active"]),
                ),
            )
            # Create user_preference with fft value
            pg_exec(
                pg_conn,
                """INSERT INTO user_preference (user_id, fft, theme, language, timezone, notifications_enabled, updated_date)
                   VALUES (%s, %s, 'light', 'en', 'UTC', true, %s)
                   ON CONFLICT DO NOTHING""",
                (r["user_id"], safe_int(r["fft"], 512), now_utc()),
            )
        count += 1
    return count


def migrate_projects(mysql_conn, pg_conn, dry_run: bool) -> int:
    rows = fetch_all(
        mysql_conn,
        "SELECT project_id, name, creator_id, url, picture_id, description, description_short, public, active, creation_date FROM project",
    )
    count = 0
    for r in rows:
        if not dry_run:
            new_uuid = uuid.uuid4()
            pg_exec(
                pg_conn,
                """INSERT INTO project (project_id, uuid, name, creator_id, url, picture_id, description, description_short, public, active, creation_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["project_id"],
                    new_uuid,
                    r["name"],
                    r["creator_id"],
                    r["url"],
                    r["picture_id"],
                    decode_blob(r["description"]),
                    decode_blob(r["description_short"]),
                    safe_bool(r["public"]),
                    safe_bool(r["active"]),
                    r["creation_date"],
                ),
            )
        count += 1
    return count


def migrate_collections(mysql_conn, pg_conn, dry_run: bool) -> int:
    """collection → collection + project_collection"""
    rows = fetch_all(
        mysql_conn,
        """SELECT collection_id, project_id, name, user_id, doi, note,
                  sphere, external_recording_url, project_url,
                  public_access, public_tags, creation_date
           FROM collection""",
    )
    count = 0
    for r in rows:
        if not dry_run:
            new_uuid = uuid.uuid4()
            pg_exec(
                pg_conn,
                """INSERT INTO collection (collection_id, uuid, name, creator_id, doi, description, sphere,
                          external_media_url, project_url, public_access, public_tags, creation_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["collection_id"],
                    new_uuid,
                    r["name"],
                    r["user_id"],
                    r["doi"] or None,
                    r["note"],
                    r["sphere"],
                    r["external_recording_url"],
                    r["project_url"],
                    safe_bool(r["public_access"]),
                    safe_bool(r["public_tags"]),
                    r["creation_date"],
                ),
            )
            # Create project_collection association
            pg_exec(
                pg_conn,
                """INSERT INTO project_collection (project_id, collection_id, added_date)
                   VALUES (%s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (r["project_id"], r["collection_id"], r["creation_date"]),
            )
        count += 1
    return count


def migrate_sites(mysql_conn, pg_conn, dry_run: bool, geo_conn=None) -> int:
    rows = fetch_all(
        mysql_conn,
        """SELECT site_id, user_id, name,
                  longitude_WGS84_dd_dddd, latitude_WGS84_dd_dddd,
                  topography_m, freshwater_depth_m,
                  gadm0, gadm1, gadm2, iho,
                  realm_id, biome_id, functional_type_id,
                  creation_date_time
           FROM site""",
    )
    count = 0
    for r in rows:
        geo_meta = resolve_site_enrichment(
            geo_conn,
            gadm0=r["gadm0"],
            gadm1=r["gadm1"],
            gadm2=r["gadm2"],
            iho=r["iho"],
        )
        if r["gadm0"] and geo_conn and geo_meta["gadm0_gid"] is None:
            audit_issue(
                source_table="site", source_id=r["site_id"], target_table="site",
                issue_type="enrichment_unresolved", severity="warning", field_name="gadm0",
                source_value=r["gadm0"],
                reason="The administrative geography could not be resolved to a target geographic identifier.",
                recommended_action="Correct the geographic name or add an approved geographic match.",
            )
        if r["iho"] and geo_conn and geo_meta["location_iho_wkt"] is None:
            audit_issue(
                source_table="site", source_id=r["site_id"], target_table="site",
                issue_type="enrichment_unresolved", severity="warning", field_name="iho",
                source_value=r["iho"],
                reason="The marine geographic area could not be resolved to target geometry.",
                recommended_action="Correct the marine area name or add an approved geographic match.",
            )
        if not dry_run:
            new_uuid = uuid.uuid4()
            lon = r["longitude_WGS84_dd_dddd"]
            lat = r["latitude_WGS84_dd_dddd"]
            realm_id = safe_int(r["realm_id"])
            biome_id = safe_int(r["biome_id"])
            functional_type_id = safe_int(r["functional_type_id"])
            # Source data may store 0 for optional FK fields; normalize to NULL.
            if realm_id is not None and realm_id <= 0:
                realm_id = None
            if biome_id is not None and biome_id <= 0:
                biome_id = None
            if functional_type_id is not None and functional_type_id <= 0:
                functional_type_id = None
            pg_exec(
                pg_conn,
                """INSERT INTO site (site_id, uuid, creator_id, name, location, longitude, latitude,
                          topography_m, freshwater_depth_m,
                          gadm0, gadm1, gadm2, iho, gadm0_gid, gadm1_gid, gadm2_gid, location_iho,
                          realm_id, biome_id, functional_type_id, creation_date)
                   VALUES (%s, %s, %s, %s, %s::geometry, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::geometry, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["site_id"],
                    new_uuid,
                    r["user_id"],
                    r["name"],
                    geo_meta["location_wkt"],
                    lon,
                    lat,
                    r["topography_m"],
                    r["freshwater_depth_m"],
                    geo_meta["gadm0"],
                    geo_meta["gadm1"],
                    geo_meta["gadm2"],
                    geo_meta["iho"],
                    geo_meta["gadm0_gid"],
                    geo_meta["gadm1_gid"],
                    geo_meta["gadm2_gid"],
                    geo_meta["location_iho_wkt"],
                    realm_id,
                    biome_id,
                    functional_type_id,
                    r["creation_date_time"],
                ),
            )
        count += 1
    return count


def migrate_site_collections(mysql_conn, pg_conn, dry_run: bool) -> int:
    rows = fetch_all(
        mysql_conn, "SELECT site_id, collection_id FROM site_collection"
    )
    valid_site_ids: set[int] = set()
    valid_collection_ids: set[int] = set()
    if not dry_run:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT site_id FROM site")
            valid_site_ids = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT collection_id FROM collection")
            valid_collection_ids = {row[0] for row in cur.fetchall()}
    count = 0
    skipped_orphans = 0
    deduplicated = 0
    for r in rows:
        if not dry_run:
            site_id = safe_int(r["site_id"])
            collection_id = safe_int(r["collection_id"])
            if (
                site_id is None
                or collection_id is None
                or site_id not in valid_site_ids
                or collection_id not in valid_collection_ids
            ):
                skipped_orphans += 1
                audit_issue(
                    source_table="site_collection", source_id=f"{site_id}:{collection_id}", target_table="site_collection",
                    issue_type="invalid_reference", severity="error", field_name="site_id,collection_id",
                    source_value=f"{site_id}:{collection_id}",
                    reason="The site or collection does not exist in the target, so the relation was skipped.",
                    recommended_action="Restore the missing parent record and migrate this relation again.",
                )
                continue
            inserted = pg_exec(
                pg_conn,
                "INSERT INTO site_collection (site_id, collection_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (site_id, collection_id),
            )
            if inserted == 0:
                deduplicated += 1
                audit_issue(
                    source_table="site_collection", source_id=f"{site_id}:{collection_id}", target_table="site_collection",
                    issue_type="migration_conflict", severity="warning", field_name="site_id,collection_id",
                    source_value=f"{site_id}:{collection_id}",
                    reason="The target relation already existed, so the source relation was not inserted.",
                    recommended_action="Compare the existing relation with the source before deciding whether to repair it.",
                )
        count += 1
    DERIVED_MIGRATION_STATS["site_collection"]["skipped_orphan_count"] = skipped_orphans
    DERIVED_MIGRATION_STATS["site_collection"]["deduplicated_count"] = deduplicated
    if skipped_orphans:
        log.warning("Skipped %s orphan site_collection rows", skipped_orphans)
    if deduplicated:
        log.info("Deduplicated %s repeated site_collection rows", deduplicated)
    return count


def migrate_site_projects(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Derive site_project from source site_collection and collection.project_id."""
    rows = fetch_all(
        mysql_conn,
        """
        SELECT DISTINCT sc.site_id, c.project_id
        FROM site_collection sc
        JOIN collection c ON c.collection_id = sc.collection_id
        WHERE sc.site_id IS NOT NULL
          AND c.project_id IS NOT NULL
        """,
    )
    valid_site_ids: set[int] = set()
    valid_project_ids: set[int] = set()
    if not dry_run:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT site_id FROM site")
            valid_site_ids = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT project_id FROM project")
            valid_project_ids = {row[0] for row in cur.fetchall()}
    count = 0
    skipped_orphans = 0
    deduplicated = 0
    for r in rows:
        site_id = safe_int(r["site_id"])
        project_id = safe_int(r["project_id"])
        if not dry_run:
            if (
                site_id is None
                or project_id is None
                or site_id not in valid_site_ids
                or project_id not in valid_project_ids
            ):
                skipped_orphans += 1
                continue
            inserted = pg_exec(
                pg_conn,
                "INSERT INTO site_project (site_id, project_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (site_id, project_id),
            )
            if inserted == 0:
                deduplicated += 1
        count += 1
    DERIVED_MIGRATION_STATS["site_project"]["derived_count"] = count
    DERIVED_MIGRATION_STATS["site_project"]["skipped_orphan_count"] = skipped_orphans
    DERIVED_MIGRATION_STATS["site_project"]["deduplicated_count"] = deduplicated
    if skipped_orphans:
        log.warning("Skipped %s orphan site_project rows", skipped_orphans)
    if deduplicated:
        log.info("Deduplicated %s repeated site_project rows", deduplicated)
    return count


def migrate_taxon(mysql_conn, pg_conn, dry_run: bool, geo_conn=None) -> int:
    """Old: species → New: taxon"""
    rows = fetch_all(
        mysql_conn,
        "SELECT species_id, binomial, genus, family, taxon_order, class, common_name, source FROM species",
    )
    remote_table = _detect_remote_taxon_table(geo_conn) if geo_conn else None
    lookup_cache = build_taxon_lookup_cache(geo_conn, rows, table_name=remote_table) if geo_conn else None
    count = 0
    for r in rows:
        taxon_meta = resolve_taxon_enrichment(
            geo_conn,
            binomial=r["binomial"],
            genus=r["genus"],
            family=r["family"],
            taxon_order=r["taxon_order"],
            taxon_class=r["class"],
            common_name=r["common_name"],
            source=r["source"],
            lookup_cache=lookup_cache,
            remote_table=remote_table,
        )
        if r["binomial"] and geo_conn and taxon_meta["col_species_id"] is None:
            audit_issue(
                source_table="species", source_id=r["species_id"], target_table="taxon",
                issue_type="enrichment_unresolved", severity="warning", field_name="binomial",
                source_value=r["binomial"],
                reason="The source taxon could not be resolved to a unique target taxonomy record.",
                recommended_action="Correct the scientific name or resolve the taxonomy match before rerunning migration.",
            )
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO taxon (taxon_id, col_species_id, col_genus_id, col_family_id, col_order_id, col_class_id,
                          cached_scientific_name, cached_common_name, taxonomy_source, last_synced, creation_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["species_id"],
                    taxon_meta["col_species_id"],
                    taxon_meta["col_genus_id"],
                    taxon_meta["col_family_id"],
                    taxon_meta["col_order_id"],
                    taxon_meta["col_class_id"],
                    taxon_meta["cached_scientific_name"],
                    taxon_meta["cached_common_name"],
                    taxon_meta["taxonomy_source"],
                    taxon_meta["last_synced"],
                    now_utc(),
                ),
            )
        count += 1
    return count


def migrate_recorder_microphones(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Derive recorder_microphone compatibility rows from source recordings."""
    rows = fetch_all(
        mysql_conn,
        """
        SELECT recorder_id, microphone_id, COUNT(*) AS usage_count
        FROM recording
        WHERE recorder_id IS NOT NULL
          AND microphone_id IS NOT NULL
          AND recorder_id > 0
          AND microphone_id > 0
        GROUP BY recorder_id, microphone_id
        ORDER BY recorder_id, usage_count DESC, microphone_id ASC
        """,
    )
    valid_recorder_ids: set[int] = set()
    valid_microphone_ids: set[int] = set()
    if not dry_run:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT recorder_id FROM recorder")
            valid_recorder_ids = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT microphone_id FROM microphone")
            valid_microphone_ids = {row[0] for row in cur.fetchall()}

    top_microphone_by_recorder: dict[int, int] = {}
    for row in rows:
        rec_id = safe_int(row["recorder_id"])
        mic_id = safe_int(row["microphone_id"])
        if rec_id is None or mic_id is None or rec_id in top_microphone_by_recorder:
            continue
        top_microphone_by_recorder[rec_id] = mic_id

    count = 0
    skipped_orphans = 0
    deduplicated = 0
    for row in rows:
        rec_id = safe_int(row["recorder_id"])
        mic_id = safe_int(row["microphone_id"])
        if not dry_run:
            if (
                rec_id is None
                or mic_id is None
                or rec_id not in valid_recorder_ids
                or mic_id not in valid_microphone_ids
            ):
                skipped_orphans += 1
                continue
            inserted = pg_exec(
                pg_conn,
                """
                INSERT INTO recorder_microphone (recorder_id, microphone_id, is_default, notes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (rec_id, mic_id, mic_id == top_microphone_by_recorder.get(rec_id), None),
            )
            if inserted == 0:
                deduplicated += 1
        count += 1

    DERIVED_MIGRATION_STATS["recorder_microphone"]["derived_count"] = count
    DERIVED_MIGRATION_STATS["recorder_microphone"]["skipped_orphan_count"] = skipped_orphans
    DERIVED_MIGRATION_STATS["recorder_microphone"]["deduplicated_count"] = deduplicated
    if skipped_orphans:
        log.warning("Skipped %s orphan recorder_microphone rows", skipped_orphans)
    if deduplicated:
        log.info("Deduplicated %s repeated recorder_microphone rows", deduplicated)
    return count


def _build_audio_sensor_name(
    recorder_id: int,
    microphone_id: int,
    recorder_name: object,
    microphone_name: object,
) -> str:
    """Return a bounded display name for an audio device combination."""
    recorder_label = str(recorder_name).strip() if recorder_name is not None else ""
    microphone_label = str(microphone_name).strip() if microphone_name is not None else ""
    if not recorder_label:
        recorder_label = f"recorder_{recorder_id}"
    if not microphone_label:
        microphone_label = f"microphone_{microphone_id}"
    return f"{recorder_label}_{microphone_label}"[:255]


def migrate_sensors(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Create audio sensor records for recorder and microphone combinations."""
    combos = fetch_all(
        mysql_conn,
        """SELECT DISTINCT recording.recorder_id, recording.microphone_id,
                  recorder.model AS recorder_name, microphone.name AS microphone_name
           FROM recording
           INNER JOIN recorder ON recorder.recorder_id = recording.recorder_id
           INNER JOIN microphone ON microphone.microphone_id = recording.microphone_id
           WHERE recording.recorder_id IS NOT NULL
             AND recording.microphone_id IS NOT NULL
             AND recording.recorder_id > 0
             AND recording.microphone_id > 0""",
    )
    count = 0
    for r in combos:
        if not dry_run:
            new_uuid = uuid.uuid4()
            rec_id = safe_int(r["recorder_id"])
            mic_id = safe_int(r["microphone_id"])
            if rec_id is not None and rec_id <= 0:
                rec_id = None
            if mic_id is not None and mic_id <= 0:
                mic_id = None
            if rec_id is None or mic_id is None:
                continue
            sensor_name = _build_audio_sensor_name(
                rec_id,
                mic_id,
                r.get("recorder_name"),
                r.get("microphone_name"),
            )
            pg_exec(
                pg_conn,
                """INSERT INTO sensor (uuid, name, sensor_type, recorder_id, microphone_id, creation_date)
                   VALUES (%s, %s, 'audio', %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    new_uuid,
                    sensor_name,
                    rec_id,
                    mic_id,
                    now_utc(),
                ),
            )
        count += 1
    return count


def _get_sensor_id_map(pg_conn) -> dict[tuple, int]:
    """Return mapping of (recorder_id, microphone_id) → sensor_id from PG."""
    with pg_conn.cursor() as cur:
        cur.execute("SELECT sensor_id, recorder_id, microphone_id FROM sensor WHERE sensor_type = 'audio'")
        return {(row[1], row[2]): row[0] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Phase 3: Associations & sub-resources
# ---------------------------------------------------------------------------


def migrate_recordings(mysql_conn, pg_conn, dry_run: bool) -> int:
    """recording → audio_setting + media + media_collection"""
    rows = iter_mysql_rows(
        mysql_conn,
        """SELECT recording_id, data_type, col_id, directory, filename, name,
                  user_id, site_id, recorder_id, microphone_id, license_id,
                  type, medium, recording_gain, duty_cycle_recording, duty_cycle_period,
                  note, file_date, file_time, file_size, md5_hash,
                  sampling_rate, bitdepth, channel_num, duration, DOI, creation_date
           FROM recording""",
    )
    sensor_map = {} if dry_run else _get_sensor_id_map(pg_conn)
    valid_user_ids: set[int] = set()
    valid_site_ids: set[int] = set()
    valid_license_ids: set[int] = set()
    valid_collection_ids: set[int] = set()
    if not dry_run:
        with pg_conn.cursor() as cur:
            cur.execute('SELECT user_id FROM "user"')
            valid_user_ids = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT site_id FROM site")
            valid_site_ids = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT license_id FROM license")
            valid_license_ids = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT collection_id FROM collection")
            valid_collection_ids = {row[0] for row in cur.fetchall()}
    count = 0
    skipped_media_collections = 0
    skipped_unknown_data_types = 0
    for r in rows:
        # Merge source date and time safely across MySQL adapter return types.
        date_time = parse_legacy_date_time(r["file_date"], r["file_time"])

        if r["data_type"] == "audio data":
            media_type = "audio"
            is_metadata_flag = False
        elif r["data_type"] == "meta-data":
            media_type = "audio"
            is_metadata_flag = True
        else:
            skipped_unknown_data_types += 1
            log.warning(
                "Skipping recording_id=%s with unsupported data_type=%r",
                r["recording_id"],
                r["data_type"],
            )
            audit_issue(
                source_table="recording", source_id=r["recording_id"], target_table="media",
                issue_type="unsupported_value", severity="error", field_name="data_type",
                source_value=r["data_type"],
                reason="The source recording data type has no target media mapping.",
                recommended_action="Correct the source data type or add an approved target mapping before rerunning migration.",
            )
            continue

        rec_id = safe_int(r["recorder_id"])
        mic_id = safe_int(r["microphone_id"])
        if rec_id is not None and rec_id <= 0:
            rec_id = None
        if mic_id is not None and mic_id <= 0:
            mic_id = None
        sensor_id = sensor_map.get((rec_id, mic_id))

        creator_id = safe_int(r["user_id"])
        if creator_id not in valid_user_ids:
            creator_id = None
        uploader_id = creator_id

        site_id = safe_int(r["site_id"])
        if site_id not in valid_site_ids:
            site_id = None

        license_id = safe_int(r["license_id"])
        if license_id not in valid_license_ids:
            license_id = None

        if not dry_run:
            audio_setting_id = None
            if media_type == "audio":
                # Keep a 1:1 mapping so audio files and metadata-only recordings
                # preserve their technical audio attributes.
                audio_setting_id = r["recording_id"]
                pg_exec(
                    pg_conn,
                    """INSERT INTO audio_setting (audio_setting_id, sampling_rate_hz, bit_depth, channel_num,
                              duration_s, recording_gain_db, creation_date)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (
                        r["recording_id"],
                        safe_int(r["sampling_rate"], 44100),
                        safe_int(r["bitdepth"]),
                        safe_int(r["channel_num"]),
                        safe_float(r["duration"], 0.0),
                        safe_int(r["recording_gain"]),
                        r["creation_date"] or now_utc(),
                    ),
                )
            # Create media record (media_id = recording_id)
            new_uuid = uuid.uuid4()
            media_inserted = pg_exec(
                pg_conn,
                """INSERT INTO media (media_id, uuid, media_type, is_metadata, directory, filename, name,
                          creator_id, uploader_id, site_id, sensor_id, license_id,
                          audio_setting_id, date_time, size_b, md5_hash, doi,
                          duty_cycle_recording, duty_cycle_period, note, medium, creation_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["recording_id"],
                    new_uuid,
                    media_type,
                    is_metadata_flag,
                    r["directory"],
                    r["filename"],
                    r["name"],
                    creator_id,
                    uploader_id,
                    site_id,
                    sensor_id,
                    license_id,
                    audio_setting_id,
                    date_time,
                    safe_int(r["file_size"]),
                    r["md5_hash"],
                    r["DOI"],
                    r["duty_cycle_recording"],
                    r["duty_cycle_period"],
                    r["note"],
                    normalize_recording_medium(r["medium"]),
                    r["creation_date"] or now_utc(),
                ),
            )
            if media_inserted == 0:
                audit_issue(
                    source_table="recording", source_id=r["recording_id"], target_table="media",
                    target_id=r["recording_id"], issue_type="migration_conflict", severity="warning",
                    reason="The target media primary key already existed, so the source row was not inserted.",
                    recommended_action="Compare the existing target media row with the source before deciding whether to repair it.",
                )
            # Create media_collection association (col_id → collection_id)
            collection_id = safe_int(r["col_id"])
            added_by = safe_int(r["user_id"])
            if (
                collection_id in valid_collection_ids
                and added_by in valid_user_ids
            ):
                pg_exec(
                    pg_conn,
                    """INSERT INTO media_collection (media_id, collection_id, added_by, added_date)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (
                        r["recording_id"],
                        collection_id,
                        added_by,
                        r["creation_date"] or now_utc(),
                    ),
                )
            else:
                skipped_media_collections += 1
                audit_issue(
                    source_table="recording", source_id=r["recording_id"], target_table="media_collection",
                    issue_type="invalid_reference", severity="error", field_name="col_id,user_id",
                    source_value=f"collection_id={collection_id}, user_id={added_by}",
                    reason="The recording was migrated but its collection relation could not be created.",
                    recommended_action="Restore the referenced collection and user, then migrate the relation again.",
                )
        count += 1
        commit_batch(pg_conn, count, dry_run)
    if skipped_media_collections:
        log.warning("Skipped %s orphan media_collection rows", skipped_media_collections)
    if skipped_unknown_data_types:
        log.warning("Skipped %s recordings with unsupported data_type", skipped_unknown_data_types)
    return count


def _mysql_column_names(mysql_conn, table_name: str) -> set[str]:
    rows = iter_mysql_rows(
        mysql_conn,
        """SELECT COLUMN_NAME
           FROM information_schema.columns
           WHERE table_schema = DATABASE() AND table_name = %s""",
        (table_name,),
    )
    return {row["COLUMN_NAME"] for row in rows}


def _pg_column_names(pg_conn, table_name: str) -> set[str]:
    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT column_name
               FROM information_schema.columns
               WHERE table_schema='public' AND table_name=%s""",
            (table_name.replace('"', ""),),
        )
        return {row[0] for row in cur.fetchall()}


def _mysql_null_count(mysql_conn, table_name: str, column_name: str) -> int:
    with mysql_cursor(mysql_conn) as cur:
        try:
            cur.execute(
                f"SELECT COUNT(*) AS c FROM `{table_name}` WHERE `{column_name}` IS NULL OR `{column_name}` = ''"  # noqa: S608
            )
        except Exception:
            cur.execute(
                f"SELECT COUNT(*) AS c FROM `{table_name}` WHERE `{column_name}` IS NULL"  # noqa: S608
            )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def print_field_coverage_report(mysql_conn, pg_conn) -> None:
    log.info("=" * 60)
    log.info("FIELD COVERAGE REPORT")
    log.info("=" * 60)
    for spec in LEGACY_FIELD_COVERAGE_SPEC:
        source_table = spec["source_table"]
        source_fields = list(spec["source_fields"])
        target_table = spec["target_table"]
        target_fields = set(spec["target_fields"])
        mysql_cols = _mysql_column_names(mysql_conn, source_table)
        pg_cols = _pg_column_names(pg_conn, target_table)

        mapping = LEGACY_FIELD_MAP[spec["name"]]
        mapped_count = 0
        unmapped_fields: list[str] = []
        existing_source = [f for f in source_fields if f in mysql_cols]
        for field in existing_source:
            target_ref = mapping.get(field)
            if not target_ref:
                unmapped_fields.append(field)
                continue
            target_col = target_ref.split(".", 1)[1]
            if target_col in pg_cols or "." in target_ref and target_ref.split(".", 1)[0] != target_table.replace('"', ""):
                mapped_count += 1
            else:
                unmapped_fields.append(field)
        null_source_count = sum(_mysql_null_count(mysql_conn, source_table, col) for col in existing_source)

        log.info(
            "  %-42s mapped=%2d unmapped=%2d null_source=%4d",
            spec["name"],
            mapped_count,
            len(unmapped_fields),
            null_source_count,
        )
        if unmapped_fields:
            detail = ", ".join(sorted(unmapped_fields))
            log.info("    deprecated_by_target_design: %s", detail)
        log.info("    direct_mapped=%d filtered_invalid_source=%d", mapped_count, null_source_count)
    for spec in DERIVED_FIELD_COVERAGE_SPEC:
        pg_cols = _pg_column_names(pg_conn, spec["target_table"])
        derived_fields = list(spec["derived_fields"])
        target_fields = set(spec["target_fields"])
        derived_mapped = sum(1 for field in derived_fields if field in target_fields and field in pg_cols or field == "notes")
        log.info(
            "  %-42s derived_mapped=%2d target_fields=%2d",
            spec["name"],
            derived_mapped,
            len(target_fields),
        )
    log.info("=" * 60)


def compare_media_sample(mysql_conn, pg_conn, media_id: int) -> None:
    legacy_rows = fetch_all(
        mysql_conn,
        """SELECT recording_id, data_type, directory, filename, name, user_id, site_id, license_id, medium,
                  duty_cycle_recording, duty_cycle_period, note, file_date, file_time, file_size, md5_hash, DOI
           FROM recording
           WHERE recording_id = %s""",
        (media_id,),
    )
    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT media_id, media_type, is_metadata, audio_setting_id, directory, filename, name, creator_id, site_id, license_id, medium,
                      duty_cycle_recording, duty_cycle_period, note, date_time, size_b, md5_hash, doi
               FROM media
               WHERE media_id = %s""",
            (media_id,),
        )
        new_row = cur.fetchone()

    if not legacy_rows:
        log.warning("Sample compare: no source recording found for media_id=%s", media_id)
        return
    if not new_row:
        log.warning("Sample compare: no target media found for media_id=%s", media_id)
        return

    old = legacy_rows[0]
    expected_dt = parse_legacy_date_time(old["file_date"], old["file_time"])
    expected_is_metadata = old["data_type"] == "meta-data"
    expected_audio_setting_id = old["recording_id"]
    checks = [
        ("media_type", "audio", new_row[1]),
        ("is_metadata", expected_is_metadata, new_row[2]),
        ("audio_setting_id", expected_audio_setting_id, new_row[3]),
        ("directory", old["directory"], new_row[4]),
        ("filename", old["filename"], new_row[5]),
        ("name", old["name"], new_row[6]),
        ("creator_id", safe_int(old["user_id"]), new_row[7]),
        ("site_id", safe_int(old["site_id"]), new_row[8]),
        ("license_id", safe_int(old["license_id"]), new_row[9]),
        ("medium", normalize_recording_medium(old["medium"]), new_row[10]),
        ("duty_cycle_recording", old["duty_cycle_recording"], new_row[11]),
        ("duty_cycle_period", old["duty_cycle_period"], new_row[12]),
        ("note", old["note"], new_row[13]),
        ("date_time", expected_dt, new_row[14]),
        ("size_b", safe_int(old["file_size"]), new_row[15]),
        ("md5_hash", old["md5_hash"], new_row[16]),
        ("doi", old["DOI"], new_row[17]),
    ]
    log.info("=" * 60)
    log.info("MEDIA SAMPLE COMPARE (media_id=%s)", media_id)
    mismatches = 0
    for field, old_val, new_val in checks:
        ok = values_equivalent(old_val, new_val)
        if not ok:
            mismatches += 1
        log.info("  %-20s old=%r new=%r [%s]", field, old_val, new_val, "OK" if ok else "DIFF")
    log.info("  summary: checked=%d mismatches=%d", len(checks), mismatches)
    log.info("=" * 60)


def migrate_spectrograms(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: spectrogram → New: preview"""
    # Normalize old type names to new ones
    TYPE_MAP = {
        "spectrogram": "spectrogram",
        "spectrogram-small": "spectrogram",
        "spectrogram-large": "spectrogram",
        "spectrogram-player": "spectrogram",
        "waveform": "waveform",
        "waveform-small": "waveform",
        "waveform-large": "waveform",
    }
    rows = iter_mysql_rows(
        mysql_conn,
        "SELECT spectrogram_id, recording_id, filename, type FROM spectrogram",
    )
    count = 0
    for r in rows:
        new_type = TYPE_MAP.get(r["type"], "spectrogram")
        preview_filename = normalize_preview_filename(r["filename"])
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO preview (preview_id, media_id, filename, type, created_date)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["spectrogram_id"],
                    r["recording_id"],
                    preview_filename,
                    new_type,
                    now_utc(),
                ),
            )
        count += 1
        commit_batch(pg_conn, count, dry_run)
    return count


def repair_preview_filenames(pg_conn, dry_run: bool = False) -> dict[str, int]:
    """
    Normalize preview.filename to basename for existing target data.

    Returns counters:
      updated / unchanged / skipped / ambiguous
    """
    stats = {"updated": 0, "unchanged": 0, "skipped": 0, "ambiguous": 0}
    with pg_conn.cursor() as cur:
        cur.execute("SELECT preview_id, filename FROM preview")
        rows = cur.fetchall()

    for preview_id, filename in rows:
        normalized = normalize_preview_filename(filename)
        if not normalized:
            stats["skipped"] += 1
            continue
        if str(filename) == normalized:
            stats["unchanged"] += 1
            continue
        if not dry_run:
            pg_exec(
                pg_conn,
                "UPDATE preview SET filename=%s WHERE preview_id=%s",
                (normalized, preview_id),
            )
        stats["updated"] += 1
    return stats


def migrate_annotations(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: tag → New: annotation"""
    rows = iter_mysql_rows(
        mysql_conn,
        """SELECT tag_id, sound_id, recording_id, user_id, creator_type, confidence,
                  min_time, max_time, min_freq, max_freq, species_id,
                  uncertain, sound_distance_m, distance_not_estimable,
                  individuals, animal_sound_type, reference_call, comments, creation_date
           FROM tag""",
    )
    count = 0
    for r in rows:
        individual_num = safe_int(r["individuals"], 1)
        if individual_num is None or individual_num < 1:
            individual_num = 1
        creator_type = truncate_text(r["creator_type"] or "user", 128) or "user"
        animal_sound_type = truncate_text(r["animal_sound_type"], 128)
        comments = truncate_text(r["comments"], 500)
        if not dry_run:
            new_uuid = uuid.uuid4()
            pg_exec(
                pg_conn,
                """INSERT INTO annotation (annotation_id, uuid, sound_id, media_id, creator_id,
                          creator_type, confidence, min_x, max_x, min_y, max_y,
                          taxon_id, uncertain, sound_distance_m, distance_not_estimable,
                          individual_num, animal_sound_type, reference, comments, creation_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["tag_id"],
                    new_uuid,
                    r["sound_id"],
                    r["recording_id"],
                    r["user_id"],
                    creator_type,
                    r["confidence"],
                    r["min_time"],
                    r["max_time"],
                    r["min_freq"],
                    r["max_freq"],
                    r["species_id"],
                    safe_bool(r["uncertain"]) if r["uncertain"] is not None else None,
                    r["sound_distance_m"],
                    safe_bool(r["distance_not_estimable"]) if r["distance_not_estimable"] is not None else None,
                    individual_num,
                    animal_sound_type,
                    safe_bool(r["reference_call"]) if r["reference_call"] is not None else None,
                    comments,
                    r["creation_date"] or now_utc(),
                ),
            )
        count += 1
        commit_batch(pg_conn, count, dry_run)
    return count


def migrate_annotation_reviews(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: tag_review → New: annotation_review"""
    rows = iter_mysql_rows(
        mysql_conn,
        """SELECT tag_id, user_id, tag_review_status_id, species_id, note, creation_date
           FROM tag_review""",
    )
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO annotation_review (annotation_id, reviewer_id, annotation_review_status_id,
                          taxon_id, note, creation_date)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["tag_id"],
                    r["user_id"],
                    r["tag_review_status_id"],
                    r["species_id"],
                    r["note"],
                    r["creation_date"] or now_utc(),
                ),
            )
        count += 1
    return count


def migrate_labels(mysql_conn, pg_conn, dry_run: bool) -> int:
    rows = fetch_all(
        mysql_conn,
        "SELECT label_id, name, creator_id, type, creation_date FROM label",
    )
    count = 0
    for r in rows:
        label_type = normalize_label_type(r.get("type"))
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO label (label_id, name, creator_id, type, creation_date)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (label_id) DO UPDATE
                   SET name = EXCLUDED.name,
                       creator_id = EXCLUDED.creator_id,
                       type = EXCLUDED.type,
                       creation_date = EXCLUDED.creation_date""",
                (
                    r["label_id"],
                    r["name"],
                    r["creator_id"] if r["creator_id"] and r["creator_id"] > 0 else None,
                    label_type,
                    r["creation_date"] or now_utc(),
                ),
            )
        count += 1
    return count


def migrate_label_media(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: label_association → New: label_media"""
    rows = iter_mysql_rows(
        mysql_conn,
        "SELECT recording_id, user_id, label_id FROM label_association",
    )
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO label_media (media_id, user_id, label_id)
                   VALUES (%s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (r["recording_id"], r["user_id"], r["label_id"]),
            )
        count += 1
        commit_batch(pg_conn, count, dry_run)
    return count


def migrate_index_log(mysql_conn, pg_conn, dry_run: bool) -> int:
    """recording_id → media_id"""
    rows = iter_mysql_rows(
        mysql_conn,
        """SELECT log_id, recording_id, user_id, index_id, version,
                  min_time, max_time, min_frequency, max_frequency,
                  variable_type, variable_order, variable_name, variable_value, creation_date
           FROM index_log""",
    )
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO index_log (log_id, media_id, user_id, index_id, version,
                          min_time, max_time, min_frequency, max_frequency,
                          variable_type, variable_order, variable_name, variable_value, creation_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["log_id"],
                    r["recording_id"],
                    r["user_id"],
                    r["index_id"],
                    r["version"],
                    r["min_time"],
                    r["max_time"],
                    r["min_frequency"],
                    r["max_frequency"],
                    r["variable_type"],
                    r["variable_order"],
                    r["variable_name"],
                    r["variable_value"],
                    r["creation_date"] or now_utc(),
                ),
            )
        count += 1
        commit_batch(pg_conn, count, dry_run)
    return count


def migrate_file_upload(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Migrate file_upload records. New schema is simpler."""
    rows = fetch_all(
        mysql_conn,
        """SELECT file_upload_id, path, status, filename, name,
                  user_id, recording_id, directory, error, creation_date
           FROM file_upload""",
    )
    valid_user_ids: set[int] = set()
    valid_media_ids: set[int] = set()
    if not dry_run:
        with pg_conn.cursor() as cur:
            cur.execute('SELECT user_id FROM "user"')
            valid_user_ids = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT media_id FROM media")
            valid_media_ids = {row[0] for row in cur.fetchall()}
    count = 0
    skipped_orphans = 0
    preserved_null_media = 0
    for r in rows:
        if not dry_run:
            uploader_id = safe_int(r["user_id"])
            media_id = safe_int(r["recording_id"])
            if uploader_id not in valid_user_ids:
                skipped_orphans += 1
                audit_issue(
                    source_table="file_upload", source_id=r["file_upload_id"], target_table="file_upload",
                    issue_type="invalid_reference", severity="error", field_name="user_id",
                    source_value=r["user_id"],
                    reason="The upload was skipped because its uploader does not exist in the target.",
                    recommended_action="Restore the uploader or assign an approved replacement before rerunning migration.",
                )
                continue
            if media_id not in valid_media_ids:
                media_id = None
                preserved_null_media += 1
                audit_issue(
                    source_table="file_upload", source_id=r["file_upload_id"], target_table="file_upload",
                    issue_type="invalid_reference", severity="warning", field_name="recording_id",
                    source_value=r["recording_id"], target_value=None,
                    reason="The upload was retained without a media relation because its recording is absent.",
                    recommended_action="Restore the media record and link this upload after migration.",
                )
            pg_exec(
                pg_conn,
                """INSERT INTO file_upload (file_upload_id, path, status, filename, name,
                          uploader_id, media_id, directory, error, upload_date_time)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["file_upload_id"],
                    normalize_media_path(r["path"]),
                    r["status"],
                    r["filename"],
                    r["name"],
                    uploader_id,
                    media_id,
                    r["directory"],
                    decode_blob(r["error"]),
                    r["creation_date"] or now_utc(),
                ),
            )
        count += 1
    DERIVED_MIGRATION_STATS["file_upload"]["skipped_orphan_count"] = skipped_orphans
    DERIVED_MIGRATION_STATS["file_upload"]["preserved_null_media_count"] = preserved_null_media
    if skipped_orphans:
        log.warning("Skipped %s orphan file_upload rows", skipped_orphans)
    if preserved_null_media:
        log.info("Preserved %s file_upload rows with NULL media_id", preserved_null_media)
    return count


def migrate_news(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old news has no writer_id; prefer a real Administrator account in PG."""
    rows = fetch_all(
        mysql_conn,
        "SELECT news_id, title, content, creation_date FROM news",
    )
    if not rows:
        return 0

    admin_id = 1
    if not dry_run:
        with pg_conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.user_id
                FROM "user" u
                JOIN role r ON r.role_id = u.role_id
                WHERE lower(r.name) = lower(%s)
                ORDER BY u.user_id ASC
                LIMIT 1
                """,
                ("Administrator",),
            )
            result = cur.fetchone()
            if not result:
                raise RuntimeError("Cannot migrate news: no Administrator user exists in target DB")
            admin_id = result[0]

    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO news (news_id, title, content, writer_id, creation_date)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["news_id"],
                    r["title"],
                    decode_blob(r["content"]) or "",
                    admin_id,
                    r["creation_date"] or now_utc(),
                ),
            )
        count += 1
    return count


def map_legacy_queue_status(status: Any, *, queue_id: int | None = None) -> int:
    """Map source queue statuses to the target queue enum."""
    status_map = {
        2: 0,   # pending -> pending
        0: 1,   # ongoing -> running
        1: 2,   # finished -> completed
        -1: 3,  # failed -> error
        -2: 3,  # cancelled -> error
    }
    normalized = safe_int(status)
    if normalized in status_map:
        return status_map[normalized]

    log.warning(
        "Unknown source queue status; defaulting to error "
        "(queue_id=%s, status=%r)",
        queue_id,
        status,
    )
    audit_issue(
        source_table="queue", source_id=queue_id or "unknown", target_table="queue", target_id=queue_id,
        issue_type="unsupported_value", severity="warning", field_name="status", source_value=status, target_value=3,
        reason="The unknown source queue status was mapped to the target error status.",
        recommended_action="Review the source status and correct the target queue state if needed.",
    )
    return 3


def migrate_queue(mysql_conn, pg_conn, dry_run: bool) -> int:
    rows = fetch_all(
        mysql_conn,
        """SELECT queue_id, type, user_id, completed, total, status,
                  start_time, stop_time, error, warning
           FROM queue""",
    )
    count = 0
    for r in rows:
        status = map_legacy_queue_status(r["status"], queue_id=r["queue_id"])
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO queue (queue_id, type, user_id, completed, total, status,
                          start_time, stop_time, error, warning)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["queue_id"],
                    r["type"],
                    r["user_id"],
                    r["completed"],
                    r["total"],
                    status,
                    r["start_time"],
                    r["stop_time"],
                    decode_blob(r["error"]),
                    decode_blob(r["warning"]),
                ),
            )
        count += 1
    return count


def migrate_tasks(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Old: recording/tag -> new media/annotation task types."""
    rows = fetch_all(
        mysql_conn,
        """SELECT task_id, type, recording_id, tag_id, assigner_id, assignee_id,
                  status, comment, datetime
           FROM task""",
    )
    count = 0
    for r in rows:
        mapped_type = map_legacy_task_type(r["type"])
        if not dry_run:
            pg_exec(
                pg_conn,
                """INSERT INTO task (task_id, type, media_id, annotation_id, assigner_id, assignee_id,
                          status, comment, datetime)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (
                    r["task_id"],
                    mapped_type,
                    r["recording_id"],
                    r["tag_id"],
                    r["assigner_id"],
                    r["assignee_id"],
                    r["status"],
                    r["comment"],
                    r["datetime"],
                ),
            )
        count += 1
    return count


def migrate_settings(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Merge source settings into target defaults, preferring source values on conflicts."""
    rows = fetch_all(mysql_conn, "SELECT name, value FROM setting")
    count = 0
    for r in rows:
        if not dry_run:
            pg_exec(
                pg_conn,
                """
                INSERT INTO setting (name, value) VALUES (%s, %s)
                ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value
                """,
                (r["name"], r["value"]),
            )
        count += 1
    return count


def _normalize_network_url(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    normalized = value.rstrip("/")
    return normalized or None


def _decode_legacy_api_url(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    encoded = str(raw_value).strip()
    if not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8").strip()
    except Exception:  # noqa: BLE001
        return None
    return _normalize_network_url(decoded)


def _same_coordinate(left: Any, right: Any) -> bool:
    if left in (None, ""):
        return True
    if right in (None, ""):
        return False
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return False


def _resolve_local_network_url(
    *,
    explicit_app_url: Any,
    stored_app_url: Any,
    host_url: Any,
    server_name: Any,
    latitude: Any,
    longitude: Any,
    nodes: list[dict[str, Any]],
) -> tuple[str | None, str]:
    """Resolve the source instance URL without guessing between ambiguous nodes."""
    explicit = _normalize_network_url(explicit_app_url)
    if explicit_app_url not in (None, "") and explicit is None:
        raise ValueError("LEGACY_APP_URL must be a valid http:// or https:// URL")
    if explicit:
        return explicit, "explicit/config APP_URL"

    stored = _normalize_network_url(stored_app_url)
    if stored_app_url not in (None, "") and stored is None:
        raise ValueError("Source setting app_url must be a valid http:// or https:// URL")
    if stored:
        return stored, "source setting app_url"

    normalized_host = _normalize_network_url(host_url)
    normalized_name = str(server_name or "").strip()
    has_identity = bool(normalized_name or latitude not in (None, "") or longitude not in (None, ""))
    if not has_identity and not nodes:
        return None, "no source federation configuration"

    candidates: list[dict[str, Any]] = []
    for node in nodes:
        node_url = _normalize_network_url(node.get("app_url"))
        if not node_url:
            continue
        if normalized_name and str(node.get("name") or "").strip() != normalized_name:
            continue
        if not _same_coordinate(latitude, node.get("latitude")):
            continue
        if not _same_coordinate(longitude, node.get("longitude")):
            continue
        candidates.append({**node, "app_url": node_url})

    host_matches = [item for item in candidates if item["app_url"] == normalized_host]
    if len(host_matches) == 1:
        return host_matches[0]["app_url"], "unique identity match equal to HOST_URL"
    if len(candidates) == 1:
        return candidates[0]["app_url"], "unique server name/coordinate match"

    candidate_urls = ", ".join(sorted(item["app_url"] for item in candidates)) or "none"
    raise RuntimeError(
        "Cannot safely identify the source local federation node "
        f"(candidates: {candidate_urls}). Re-run with --legacy-app-url <url>."
    )


def _legacy_network_inputs(
    settings: dict[str, Any], nodes: list[dict[str, Any]]
) -> tuple[str | None, str, str | None, str]:
    explicit_app_url = os.getenv("LEGACY_APP_URL")
    configured_host_url = os.getenv("LEGACY_HOST_URL") or settings.get("host_url")
    host_url = _normalize_network_url(configured_host_url)
    if configured_host_url not in (None, "") and host_url is None:
        raise ValueError("LEGACY_HOST_URL must be a valid http:// or https:// URL")
    app_url, source = _resolve_local_network_url(
        explicit_app_url=explicit_app_url,
        stored_app_url=settings.get("app_url"),
        host_url=host_url,
        server_name=settings.get("server_name"),
        latitude=settings.get("latitude"),
        longitude=settings.get("longitude"),
        nodes=nodes,
    )
    return app_url, source, host_url, str(settings.get("server_name") or "").strip()


def _upsert_local_network_node(
    pg_conn,
    *,
    app_url: str,
    server_name: str,
    latitude: Any,
    longitude: Any,
    shared: bool,
) -> None:
    now = datetime.now(UTC)
    pg_exec(
        pg_conn,
        "UPDATE network_node SET is_local = FALSE WHERE is_local = TRUE AND app_url <> %s",
        (app_url,),
    )
    pg_exec(
        pg_conn,
        """
        INSERT INTO network_node (
            app_url, name, latitude, longitude, is_local, shared,
            stat_users, stat_projects, stat_collections, stat_audios,
            stat_photos, stat_videos, stat_annotations, stat_sites,
            last_synced_at, created_at
        )
        VALUES (%s, %s, %s, %s, TRUE, %s, 0, 0, 0, 0, 0, 0, 0, 0, %s, %s)
        ON CONFLICT (app_url) DO UPDATE
        SET name = EXCLUDED.name,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            is_local = TRUE,
            shared = EXCLUDED.shared
        """,
        (
            app_url,
            server_name or app_url,
            latitude,
            longitude,
            shared,
            now,
            now,
        ),
    )


def _write_network_host_url(pg_conn, host_url: str | None) -> None:
    if host_url is None:
        return
    pg_exec(
        pg_conn,
        """
        INSERT INTO setting (name, value) VALUES ('network_host_url', %s)
        ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value
        """,
        (host_url,),
    )


def migrate_network_federation(mysql_conn, pg_conn, dry_run: bool) -> int:
    """Map source API and settings data into network_node rows."""
    legacy_settings = {
        str(row["name"]): row["value"]
        for row in fetch_all(mysql_conn, "SELECT name, value FROM setting")
    }
    local_server_name = (legacy_settings.get("server_name") or "").strip()
    local_latitude = legacy_settings.get("latitude")
    local_longitude = legacy_settings.get("longitude")
    local_shared = int(legacy_settings.get("shared") or 0) == 1

    rows = fetch_all(
        mysql_conn,
        """SELECT api_id, api, server_name, longitude, latitude, shared, last_updated
           FROM api
           ORDER BY api_id""",
    )

    chosen_by_url: dict[str, dict[str, Any]] = {}
    migrated_count = 0
    for row in rows:
        if int(row.get("shared") or 0) != 1:
            continue

        app_url = _decode_legacy_api_url(row.get("api"))
        if not app_url:
            log.warning("Skipping source API row with invalid encoded URL: api_id=%s", row.get("api_id"))
            audit_issue(
                source_table="api", source_id=row.get("api_id"), target_table="network_node",
                issue_type="unsupported_value", severity="error", field_name="api", source_value=row.get("api"),
                reason="The source network URL is invalid and was skipped.",
                recommended_action="Correct the source URL and rerun the federation migration.",
            )
            continue

        server_name = (row.get("server_name") or "").strip() or app_url
        existing = chosen_by_url.get(app_url)
        if existing is None:
            chosen_by_url[app_url] = {
                "app_url": app_url,
                "name": server_name,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "last_updated": row.get("last_updated"),
            }
            continue

        current_ts = row.get("last_updated")
        existing_ts = existing.get("last_updated")
        if existing_ts is None or (current_ts is not None and current_ts >= existing_ts):
            chosen_by_url[app_url] = {
                "app_url": app_url,
                "name": server_name,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "last_updated": current_ts,
            }

    local_app_url, local_source, host_url, local_server_name = _legacy_network_inputs(
        legacy_settings, list(chosen_by_url.values())
    )
    log.info(
        "Local federation resolution: app_url=%s source=%s host_url=%s",
        local_app_url or "<not configured>",
        local_source,
        host_url or "<not configured>",
    )

    for item in chosen_by_url.values():
        migrated_count += 1
        if dry_run:
            continue
        created_at = item["last_updated"] or datetime.now(UTC)
        last_synced_at = created_at
        pg_exec(
            pg_conn,
            """
            INSERT INTO network_node (
                app_url, name, latitude, longitude, is_local, shared,
                stat_users, stat_projects, stat_collections, stat_audios,
                stat_photos, stat_videos, stat_annotations, stat_sites,
                last_synced_at, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (app_url) DO UPDATE
            SET name = EXCLUDED.name,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                shared = EXCLUDED.shared,
                stat_users = EXCLUDED.stat_users,
                stat_projects = EXCLUDED.stat_projects,
                stat_collections = EXCLUDED.stat_collections,
                stat_audios = EXCLUDED.stat_audios,
                stat_photos = EXCLUDED.stat_photos,
                stat_videos = EXCLUDED.stat_videos,
                stat_annotations = EXCLUDED.stat_annotations,
                stat_sites = EXCLUDED.stat_sites,
                last_synced_at = EXCLUDED.last_synced_at
            WHERE network_node.is_local = FALSE
            """,
            (
                item["app_url"],
                item["name"],
                item["latitude"],
                item["longitude"],
                False,
                True,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                last_synced_at,
                created_at,
            ),
        )

    if local_app_url:
        migrated_count += 1
        if not dry_run:
            _upsert_local_network_node(
                pg_conn,
                app_url=local_app_url,
                server_name=local_server_name,
                latitude=local_latitude,
                longitude=local_longitude,
                shared=local_shared,
            )
            _write_network_host_url(pg_conn, host_url)

    return migrated_count


def _pg_fetch_dicts(pg_conn, sql: str, params=None) -> list[dict[str, Any]]:
    with pg_conn.cursor() as cur:
        cur.execute(sql, params or ())
        columns = [column.name for column in cur.description]
        return [dict(zip(columns, row, strict=True)) for row in cur.fetchall()]


def repair_network_federation(pg_conn, dry_run: bool) -> dict[str, Any]:
    """Repair federation configuration in an initialized PostgreSQL database."""
    setting_rows = _pg_fetch_dicts(
        pg_conn,
        """
        SELECT name, value
        FROM setting
        WHERE name IN (
            'server_name', 'app_url', 'host_url', 'network_host_url',
            'latitude', 'longitude', 'shared'
        )
        """,
    )
    settings = {row["name"]: row["value"] for row in setting_rows}
    if not os.getenv("LEGACY_HOST_URL") and settings.get("network_host_url"):
        settings["host_url"] = settings["network_host_url"]

    nodes = _pg_fetch_dicts(
        pg_conn,
        """
        SELECT app_url, name, latitude, longitude, is_local, shared
        FROM network_node
        ORDER BY node_id
        """,
    )
    app_url, source, host_url, server_name = _legacy_network_inputs(settings, nodes)
    if not app_url:
        raise RuntimeError(
            "No source federation configuration was found. "
            "Provide --legacy-app-url <url> to initialize the local node."
        )

    candidate = next((node for node in nodes if node["app_url"] == app_url), None)
    latitude = settings.get("latitude")
    longitude = settings.get("longitude")
    shared = safe_bool(settings.get("shared")) or False
    changes = {
        "app_url": app_url,
        "source": source,
        "host_url": host_url,
        "server_name": server_name or app_url,
        "latitude": latitude,
        "longitude": longitude,
        "shared": shared,
        "existing_role": "local" if candidate and candidate["is_local"] else "remote" if candidate else "missing",
        "dry_run": dry_run,
    }
    log.info("Federation repair plan: %s", json.dumps(changes, ensure_ascii=False, default=str))

    if not dry_run:
        _upsert_local_network_node(
            pg_conn,
            app_url=app_url,
            server_name=server_name,
            latitude=latitude,
            longitude=longitude,
            shared=shared,
        )
        _write_network_host_url(pg_conn, host_url)
    return changes


def verify_network_federation_state(
    pg_conn, *, expected_host_url: str | None = None, require_local: bool = True
) -> list[str]:
    """Return federation integrity errors for transfer and repair workflows."""
    errors: list[str] = []
    rows = _pg_fetch_dicts(
        pg_conn,
        """
        SELECT app_url, name, is_local
        FROM network_node
        WHERE is_local = TRUE
        ORDER BY node_id
        """,
    )
    if require_local and len(rows) != 1:
        errors.append(f"expected exactly one local network node, found {len(rows)}")
    elif len(rows) > 1:
        errors.append(f"expected at most one local network node, found {len(rows)}")
    if rows and _normalize_network_url(rows[0].get("app_url")) is None:
        errors.append("local network node has an invalid app_url")

    duplicates = _pg_fetch_dicts(
        pg_conn,
        """
        SELECT app_url, COUNT(*) AS count
        FROM network_node
        GROUP BY app_url
        HAVING COUNT(*) > 1
        """,
    )
    if duplicates:
        errors.append(f"found {len(duplicates)} duplicated network app_url values")

    if expected_host_url is not None:
        host_rows = _pg_fetch_dicts(
            pg_conn,
            "SELECT name, value FROM setting WHERE name = 'network_host_url'",
        )
        actual_host_url = host_rows[0]["value"] if host_rows else None
        if _normalize_network_url(actual_host_url) != _normalize_network_url(expected_host_url):
            errors.append(
                f"network_host_url mismatch: expected {expected_host_url!r}, found {actual_host_url!r}"
            )
    return errors


OLD_PERMISSION_GRANTS: dict[int, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # Old permission_id: 1=View, 2=Review, 3=Access, 4=Manage.
    1: (("project:read",), ("collection:read",)),
    2: (("project:read",), ("collection:read", "review:write")),
    3: (("project:read",), ("collection:read", "annotation:write")),
    4: (("project:read",), ("collection:write",)),
}


def _permission_grant_rows(row: dict) -> list[tuple[int, int, int | None, str]]:
    project_id = row.get("project_id")
    collection_id = row.get("collection_id")
    grant_names = OLD_PERMISSION_GRANTS.get(row.get("permission_id"))
    if project_id is None or collection_id is None or not grant_names:
        return []

    project_permissions, collection_permissions = grant_names
    grants: list[tuple[int, int, int | None, str]] = []
    for permission_name in project_permissions:
        grants.append((row["user_id"], project_id, None, permission_name))
    for permission_name in collection_permissions:
        grants.append((row["user_id"], project_id, collection_id, permission_name))
    return grants


def _fetch_permission_id_map(pg_conn, required_names: set[str]) -> dict[str, int]:
    with pg_conn.cursor() as cur:
        cur.execute("SELECT permission_id, name FROM permission")
        permission_map = {row[1]: row[0] for row in cur.fetchall()}
    missing = sorted(required_names - set(permission_map))
    if missing:
        raise RuntimeError(f"Missing required permissions in target DB: {', '.join(missing)}")
    return permission_map


def _project_collection_link_exists(pg_conn, project_id: int, collection_id: int) -> bool:
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM project_collection WHERE project_id = %s AND collection_id = %s",
            (project_id, collection_id),
        )
        return cur.fetchone() is not None


def _full_project_collection_write_scopes(pg_conn) -> list[tuple[int, int]]:
    """
    Return user/project pairs that match the source project-manager semantics.

    A user is considered a project manager when they have
    Manage permission on every collection in a project.
    """
    with pg_conn.cursor() as cur:
        cur.execute(
            """WITH project_collection_counts AS (
                   SELECT project_id, COUNT(DISTINCT collection_id) AS total_collections
                   FROM project_collection
                   GROUP BY project_id
               ),
               user_write_counts AS (
                   SELECT up.user_id, up.project_id, COUNT(DISTINCT up.collection_id) AS write_collections
                   FROM user_permission up
                   JOIN permission p ON p.permission_id = up.permission_id
                   WHERE p.name = 'collection:write'
                     AND up.collection_id IS NOT NULL
                   GROUP BY up.user_id, up.project_id
               )
               SELECT uw.user_id, uw.project_id
               FROM user_write_counts uw
               JOIN project_collection_counts pc
                 ON pc.project_id = uw.project_id
                AND pc.total_collections = uw.write_collections
               WHERE NOT EXISTS (
                   SELECT 1
                   FROM user_permission project_write
                   JOIN permission project_permission
                     ON project_permission.permission_id = project_write.permission_id
                   WHERE project_write.user_id = uw.user_id
                     AND project_write.project_id = uw.project_id
                     AND project_write.collection_id IS NULL
                     AND project_permission.name = 'project:write'
               )"""
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def grant_project_write_for_full_project_managers(pg_conn, dry_run: bool) -> int:
    """
    Promote full-project Manage coverage to project:write.

    The per-collection Manage rows are still kept as collection:write so the
    The target permission graph preserves both fine-grained and project-level use.
    """
    candidates = _full_project_collection_write_scopes(pg_conn)
    if dry_run:
        return len(candidates)
    if not candidates:
        return 0

    permission_map = _fetch_permission_id_map(pg_conn, {"project:write"})
    project_write_id = permission_map["project:write"]
    for user_id, project_id in candidates:
        pg_exec(
            pg_conn,
            """INSERT INTO user_permission (user_id, permission_id, project_id, collection_id)
               VALUES (%s, %s, %s, NULL)
               ON CONFLICT DO NOTHING""",
            (user_id, project_write_id, project_id),
        )
    return len(candidates)


def migrate_user_permissions(mysql_conn, pg_conn, dry_run: bool) -> int:
    """
    Map old collection-level permissions to current explicit permission storage.

    Old: (user_id, collection_id, permission_id)
    New: project-scoped base permission plus project+collection scoped grants.
    """
    required_permission_names = {
        permission_name
        for project_names, collection_names in OLD_PERMISSION_GRANTS.values()
        for permission_name in (*project_names, *collection_names)
    }

    rows = fetch_all(
        mysql_conn,
        """SELECT up.user_id, up.collection_id, up.permission_id, c.project_id
           FROM user_permission up
           LEFT JOIN collection c ON c.collection_id = up.collection_id""",
    )
    if not rows:
        return 0

    pg_perm_map: dict[str, int] = {}
    if not dry_run:
        pg_perm_map = _fetch_permission_id_map(pg_conn, required_permission_names)

    count = 0
    for r in rows:
        grant_rows = _permission_grant_rows(r)
        if not grant_rows:
            log.warning(
                "Skipping source permission with missing project/collection or unmapped permission: %s",
                r,
            )
            audit_issue(
                source_table="user_permission", source_id=f"{r['user_id']}:{r['collection_id']}:{r['permission_id']}",
                target_table="user_permission", issue_type="invalid_reference", severity="error",
                field_name="collection_id,permission_id", source_value=r,
                reason="The permission has no valid project/collection scope or permission mapping.",
                recommended_action="Restore the collection path and use a supported permission before rerunning migration.",
            )
            continue

        project_id = r["project_id"]
        collection_id = r["collection_id"]
        if not dry_run and not _project_collection_link_exists(pg_conn, project_id, collection_id):
            log.warning(
                "Skipping source permission for an unlinked project and collection path: user_id=%s project_id=%s collection_id=%s",
                r["user_id"],
                project_id,
                collection_id,
            )
            audit_issue(
                source_table="user_permission", source_id=f"{r['user_id']}:{collection_id}:{r['permission_id']}",
                target_table="user_permission", issue_type="invalid_reference", severity="error",
                field_name="project_id,collection_id", source_value=f"{project_id}:{collection_id}",
                reason="The permission scope has no corresponding project-collection relation.",
                recommended_action="Restore the project-collection relation before rerunning migration.",
            )
            continue

        if not dry_run:
            for user_id, grant_project_id, grant_collection_id, permission_name in grant_rows:
                new_perm_id = pg_perm_map[permission_name]
                pg_exec(
                    pg_conn,
                    """INSERT INTO user_permission (user_id, permission_id, project_id, collection_id)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (user_id, new_perm_id, grant_project_id, grant_collection_id),
                )
        count += 1
    if not dry_run:
        project_write_count = grant_project_write_for_full_project_managers(pg_conn, dry_run=False)
        if project_write_count:
            log.info(
                "Granted project:write to %d full-project managers",
                project_write_count,
            )
    return count


def verify_user_permission_migration(mysql_conn, pg_conn) -> list[str]:
    errors: list[str] = []

    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM user_permission WHERE project_id IS NULL")
        null_project_count = cur.fetchone()[0]
    if null_project_count:
        errors.append(f"user_permission rows with NULL project_id: {null_project_count}")

    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*)
               FROM user_permission up
               LEFT JOIN project_collection pc
                 ON pc.project_id = up.project_id
                AND pc.collection_id = up.collection_id
               WHERE up.collection_id IS NOT NULL
                 AND pc.collection_id IS NULL"""
        )
        broken_scope_count = cur.fetchone()[0]
    if broken_scope_count:
        errors.append(f"user_permission rows without project_collection scope: {broken_scope_count}")

    legacy_rows = fetch_all(
        mysql_conn,
        """SELECT up.user_id, up.collection_id, up.permission_id, c.project_id
           FROM user_permission up
           LEFT JOIN collection c ON c.collection_id = up.collection_id""",
    )
    has_valid_legacy_permission = False
    for row in legacy_rows:
        grant_rows = _permission_grant_rows(row)
        if not grant_rows:
            continue
        has_valid_legacy_permission = True
        with pg_conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*)
                   FROM user_permission up
                   JOIN permission p ON p.permission_id = up.permission_id
                   WHERE up.user_id = %s
                     AND up.project_id = %s
                     AND up.collection_id = %s""",
                (row["user_id"], row["project_id"], row["collection_id"]),
            )
            collection_grant_count = cur.fetchone()[0]
        if collection_grant_count == 0:
            errors.append(
                "source permission is missing from its target collection scope: "
                f"user_id={row['user_id']} project_id={row['project_id']} collection_id={row['collection_id']}"
            )

    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*)
               FROM user_permission up
               JOIN permission p ON p.permission_id = up.permission_id
               WHERE p.name IN ('review:write', 'annotation:write')
                 AND NOT EXISTS (
                    SELECT 1
                    FROM user_permission cp
                    JOIN permission collection_perm
                      ON collection_perm.permission_id = cp.permission_id
                    WHERE cp.user_id = up.user_id
                      AND cp.project_id = up.project_id
                      AND cp.collection_id = up.collection_id
                      AND collection_perm.name = 'collection:read'
                 )"""
        )
        missing_collection_read = cur.fetchone()[0]
    if missing_collection_read:
        errors.append(
            "review/annotation write rows missing same-scope collection:read: "
            f"{missing_collection_read}"
        )

    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*)
               FROM user_permission up
               JOIN permission p ON p.permission_id = up.permission_id
               WHERE p.name IN ('review:write', 'annotation:write')
                 AND NOT EXISTS (
                    SELECT 1
                    FROM user_permission pp
                    JOIN permission project_perm
                      ON project_perm.permission_id = pp.permission_id
                    WHERE pp.user_id = up.user_id
                      AND pp.project_id = up.project_id
                      AND pp.collection_id IS NULL
                      AND project_perm.name = 'project:read'
                 )"""
        )
        missing_project_read = cur.fetchone()[0]
    if missing_project_read:
        errors.append(
            "review/annotation write rows missing parent project:read: "
            f"{missing_project_read}"
        )

    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*)
               FROM user_effective_permissions uep
               JOIN user_permission up
                 ON up.user_id = uep.user_id
                AND up.project_id = uep.project_id
                AND up.collection_id = uep.collection_id
               JOIN permission p ON p.permission_id = up.permission_id
               WHERE uep.scope_type = 'project_collection'
                 AND p.name IN ('collection:read', 'collection:write', 'review:write', 'annotation:write')"""
        )
        view_count = cur.fetchone()[0]
    if has_valid_legacy_permission and view_count == 0:
        errors.append("user_effective_permissions has no rows for transferred collection permissions")

    with pg_conn.cursor() as cur:
        cur.execute(
            """WITH project_collection_counts AS (
                   SELECT project_id, COUNT(DISTINCT collection_id) AS total_collections
                   FROM project_collection
                   GROUP BY project_id
               ),
               user_write_counts AS (
                   SELECT up.user_id, up.project_id, COUNT(DISTINCT up.collection_id) AS write_collections
                   FROM user_permission up
                   JOIN permission p ON p.permission_id = up.permission_id
                   WHERE p.name = 'collection:write'
                     AND up.collection_id IS NOT NULL
                   GROUP BY up.user_id, up.project_id
               )
               SELECT COUNT(*)
               FROM user_write_counts uw
               JOIN project_collection_counts pc
                 ON pc.project_id = uw.project_id
                AND pc.total_collections = uw.write_collections
               WHERE NOT EXISTS (
                   SELECT 1
                   FROM user_permission project_write
                   JOIN permission project_permission
                     ON project_permission.permission_id = project_write.permission_id
                   WHERE project_write.user_id = uw.user_id
                     AND project_write.project_id = uw.project_id
                     AND project_write.collection_id IS NULL
                     AND project_permission.name = 'project:write'
               )"""
        )
        missing_project_write_count = cur.fetchone()[0]
    if missing_project_write_count:
        errors.append(
            "full-project collection:write managers missing project:write: "
            f"{missing_project_write_count}"
        )

    return errors


def verify_recording_media_migration(pg_conn) -> list[str]:
    errors: list[str] = []

    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*)
               FROM media
               WHERE is_metadata = TRUE
                 AND audio_setting_id IS NULL"""
        )
        metadata_without_audio_setting = cur.fetchone()[0]
    if metadata_without_audio_setting:
        errors.append(
            "is_metadata media rows missing audio_setting_id: "
            f"{metadata_without_audio_setting}"
        )

    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*)
               FROM media
               WHERE is_metadata = TRUE
                 AND photo_setting_id IS NOT NULL"""
        )
        metadata_with_photo_setting = cur.fetchone()[0]
    if metadata_with_photo_setting:
        errors.append(
            "is_metadata media rows should not have photo_setting_id: "
            f"{metadata_with_photo_setting}"
        )

    with pg_conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*)
               FROM media
               WHERE media_type = 'audio'
                 AND is_metadata = FALSE
                 AND audio_setting_id IS NULL"""
        )
        audio_without_audio_setting = cur.fetchone()[0]
    if audio_without_audio_setting:
        errors.append(
            "audio media rows missing audio_setting_id: "
            f"{audio_without_audio_setting}"
        )

    return errors


def analysis_audio_candidates(filename: str | None) -> list[str]:
    """Return WAV/FLAC analysis candidates using the backend AI resolver order."""
    if not filename:
        return []
    raw = str(filename).strip()
    if not raw:
        return []
    path = Path(raw)
    stem = path.stem
    suffix = path.suffix.lower()
    if suffix == ".wav":
        candidates = [raw, f"{stem}.flac"]
    elif suffix == ".flac":
        candidates = [raw, f"{stem}.wav"]
    else:
        candidates = [f"{stem}.wav", f"{stem}.flac"]
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def verify_analysis_audio_files(pg_conn) -> dict[str, int]:
    """Check whether audio rows can resolve to a WAV or FLAC file."""
    media_root = Path(os.getenv("MEDIA_ROOT", "/app/sounds"))
    stats = {
        "checked": 0,
        "database_file_exists": 0,
        "same_stem_wav_exists": 0,
        "same_stem_flac_exists": 0,
        "source_file_missing": 0,
        "non_wav_with_wav_derivative": 0,
        "analysis_resolvable": 0,
        "missing": 0,
        "preview_checked": 0,
        "preview_file_exists": 0,
        "preview_file_missing": 0,
    }
    missing_examples: list[str] = []
    source_missing_examples: list[str] = []
    preview_missing_examples: list[str] = []

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.media_id, COALESCE(mc.collection_id, m.audio_setting_id) AS path_root,
                   m.directory, m.filename
            FROM media m
            LEFT JOIN LATERAL (
                SELECT collection_id
                FROM media_collection
                WHERE media_id = m.media_id
                ORDER BY added_date ASC
                LIMIT 1
            ) mc ON TRUE
            WHERE m.media_type = 'audio'
              AND m.is_metadata = FALSE
              AND m.filename IS NOT NULL
            """
        )
        rows = cur.fetchall()

    for media_id, path_root, directory, filename in rows:
        stats["checked"] += 1
        base = media_root / "sounds" / str(path_root) / str(directory)
        raw_path = base / str(filename)
        stem = Path(str(filename)).stem
        wav_path = base / f"{stem}.wav"
        flac_path = base / f"{stem}.flac"

        if raw_path.exists():
            stats["database_file_exists"] += 1
        else:
            stats["source_file_missing"] += 1
            audit_issue(
                source_table="recording", source_id=media_id, target_table="media", target_id=media_id,
                issue_type="file_missing", severity="warning", field_name="filename", source_value=filename,
                reason="The original source filename is absent even though an analysis candidate may exist.",
                recommended_action="Restore the original source file if source-file coverage is required.",
            )
            if len(source_missing_examples) < 10:
                source_missing_examples.append(
                    f"media_id={media_id} expected_original={raw_path}"
                )
        if wav_path.exists():
            stats["same_stem_wav_exists"] += 1
        if flac_path.exists():
            stats["same_stem_flac_exists"] += 1
        if Path(str(filename)).suffix.lower() != ".wav" and wav_path.exists():
            stats["non_wav_with_wav_derivative"] += 1

        resolved = None
        for candidate in analysis_audio_candidates(str(filename)):
            candidate_path = base / candidate
            if candidate_path.exists():
                resolved = candidate_path
                break

        if resolved is not None:
            stats["analysis_resolvable"] += 1
        else:
            stats["missing"] += 1
            audit_issue(
                source_table="recording", source_id=media_id, target_table="media", target_id=media_id,
                issue_type="file_missing", severity="error", field_name="filename", source_value=filename,
                reason="No WAV or FLAC file can be resolved for the migrated audio record.",
                recommended_action="Restore a supported audio file in the expected media directory.",
            )
            if len(missing_examples) < 10:
                missing_examples.append(
                    f"media_id={media_id} expected={base / str(filename)}"
                )

    log.info(
        "  Analysis audio files          checked=%d db_file=%d wav=%d flac=%d resolvable=%d missing=%d",
        stats["checked"],
        stats["database_file_exists"],
        stats["same_stem_wav_exists"],
        stats["same_stem_flac_exists"],
        stats["analysis_resolvable"],
        stats["missing"],
    )
    log.info(
        "  Audio source file coverage    original_missing=%d non_wav_with_wav=%d",
        stats["source_file_missing"],
        stats["non_wav_with_wav_derivative"],
    )
    for example in missing_examples:
        log.warning("  Missing analysis audio example: %s", example)
    for example in source_missing_examples:
        log.warning("  Missing audio source example: %s", example)

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.preview_id, COALESCE(mc.collection_id, m.audio_setting_id) AS path_root,
                   m.directory, p.filename
            FROM preview p
            JOIN media m ON m.media_id = p.media_id
            LEFT JOIN LATERAL (
                SELECT collection_id
                FROM media_collection
                WHERE media_id = m.media_id
                ORDER BY added_date ASC
                LIMIT 1
            ) mc ON TRUE
            WHERE m.media_type = 'audio'
              AND m.is_metadata = FALSE
              AND p.filename IS NOT NULL
            """
        )
        preview_rows = cur.fetchall()

    for preview_id, path_root, directory, filename in preview_rows:
        stats["preview_checked"] += 1
        preview_path = media_root / "images" / str(path_root) / str(directory) / str(filename)
        if preview_path.exists():
            stats["preview_file_exists"] += 1
        else:
            stats["preview_file_missing"] += 1
            audit_issue(
                source_table="spectrogram", source_id=preview_id, target_table="preview", target_id=preview_id,
                issue_type="file_missing", severity="warning", field_name="filename", source_value=filename,
                reason="The migrated preview file is absent from the expected image directory.",
                recommended_action="Restore the preview file or regenerate it from the migrated audio.",
            )
            if len(preview_missing_examples) < 10:
                preview_missing_examples.append(
                    f"preview_id={preview_id} expected={preview_path}"
                )

    log.info(
        "  Preview files                 checked=%d exists=%d missing=%d",
        stats["preview_checked"],
        stats["preview_file_exists"],
        stats["preview_file_missing"],
    )
    for example in preview_missing_examples:
        log.warning("  Missing preview file example: %s", example)
    return stats


def assert_user_permission_migration(mysql_conn, pg_conn) -> None:
    errors = verify_user_permission_migration(mysql_conn, pg_conn)
    if errors:
        for error in errors:
            log.error("Permission verification failed: %s", error)
        raise RuntimeError("Permission transfer verification failed")


# ---------------------------------------------------------------------------
# Phase 5a: Reset PostgreSQL sequences
# ---------------------------------------------------------------------------

SEQUENCE_TARGETS = [
    ("role", "role_id"),
    ("license", "license_id"),
    ("iucn_get", "iucn_get_id"),
    ("recorder", "recorder_id"),
    ("microphone", "microphone_id"),
    ("sensor", "sensor_id"),
    ("sound_classification", "sound_id"),
    ("taxon_sound_type", "taxon_sound_type_id"),
    ("annotation_review_status", "annotation_review_status_id"),
    ("index_type", "index_id"),
    ("model", "model_id"),
    ('"user"', "user_id"),
    ("project", "project_id"),
    ("collection", "collection_id"),
    ("site", "site_id"),
    ("taxon", "taxon_id"),
    ("audio_setting", "audio_setting_id"),
    ("media", "media_id"),
    ("preview", "preview_id"),
    ("annotation", "annotation_id"),
    ("label", "label_id"),
    ("index_log", "log_id"),
    ("file_upload", "file_upload_id"),
    ("news", "news_id"),
    ("queue", "queue_id"),
    ("task", "task_id"),
    ("user_permission", "id"),
]


def reset_sequences(pg_conn) -> None:
    for table, col in SEQUENCE_TARGETS:
        try:
            with pg_conn.cursor() as cur:
                cur.execute(f"SELECT MAX({col}) FROM {table}")  # noqa: S608
                result = cur.fetchone()
                max_val = result[0] if result and result[0] is not None else 0
                next_val = max_val + 1
                cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table.replace('"', ""), col))
                seq = cur.fetchone()[0]
                if not seq:
                    log.info("  No sequence attached to %s.%s, skipping", table, col)
                    continue
                cur.execute(f"SELECT setval('{seq}', %s, false)", (next_val,))
            log.info("  Reset %s → %d", seq, next_val)
        except Exception as e:
            log.warning("  Could not reset %s.%s: %s", table, col, e)
            pg_conn.rollback()


# ---------------------------------------------------------------------------
# Phase 5b: Verification
# ---------------------------------------------------------------------------

VERIFICATION_CHECKS = [
    # (description, mysql_sql, pg_sql)
    ("users", "SELECT COUNT(*) FROM user", 'SELECT COUNT(*) FROM "user"'),
    ("projects", "SELECT COUNT(*) FROM project", "SELECT COUNT(*) FROM project"),
    ("collections", "SELECT COUNT(*) FROM collection", "SELECT COUNT(*) FROM collection"),
    ("sites", "SELECT COUNT(*) FROM site", "SELECT COUNT(*) FROM site"),
    ("recordings→media", "SELECT COUNT(*) FROM recording", "SELECT COUNT(*) FROM media"),
    ("tags→annotations", "SELECT COUNT(*) FROM tag", "SELECT COUNT(*) FROM annotation"),
    ("spectrograms→previews", "SELECT COUNT(*) FROM spectrogram", "SELECT COUNT(*) FROM preview"),
    ("label_assoc→label_media", "SELECT COUNT(*) FROM label_association", "SELECT COUNT(*) FROM label_media"),
    ("index_log", "SELECT COUNT(*) FROM index_log", "SELECT COUNT(*) FROM index_log"),
    ("project_collection", "SELECT COUNT(*) FROM collection WHERE project_id IS NOT NULL", "SELECT COUNT(*) FROM project_collection"),
    ("site_collection", "SELECT COUNT(*) FROM site_collection", "SELECT COUNT(*) FROM site_collection"),
    ("annotation_review", "SELECT COUNT(*) FROM tag_review", "SELECT COUNT(*) FROM annotation_review"),
]

SOURCE_TARGET_AUDIT_SPECS = [
    ("user", "user_id", '"user"', "user_id"),
    ("project", "project_id", "project", "project_id"),
    ("collection", "collection_id", "collection", "collection_id"),
    ("site", "site_id", "site", "site_id"),
    ("recording", "recording_id", "media", "media_id"),
    ("spectrogram", "spectrogram_id", "preview", "preview_id"),
    ("tag", "tag_id", "annotation", "annotation_id"),
    ("label", "label_id", "label", "label_id"),
    ("index_log", "log_id", "index_log", "log_id"),
    ("file_upload", "file_upload_id", "file_upload", "file_upload_id"),
    ("queue", "queue_id", "queue", "queue_id"),
    ("task", "task_id", "task", "task_id"),
]


def audit_missing_target_rows(mysql_conn, pg_conn) -> None:
    """Find source rows whose target primary-key row is absent after migration."""
    for source_table, source_pk, target_table, target_pk in SOURCE_TARGET_AUDIT_SPECS:
        source_rows = iter_mysql_rows(mysql_conn, f"SELECT {source_pk} FROM {source_table}")  # noqa: S608
        for row in source_rows:
            source_id = row[source_pk]
            with pg_conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM {target_table} WHERE {target_pk} = %s", (source_id,))  # noqa: S608
                target_exists = cur.fetchone() is not None
            if not target_exists:
                audit_issue(
                    source_table=source_table, source_id=source_id, target_table=target_table,
                    issue_type="not_migrated", severity="error",
                    reason="The source primary-key row has no corresponding target row after migration.",
                    recommended_action="Inspect the source row and migration error, then migrate it again.",
                )


def audit_recording_field_mismatches(mysql_conn, pg_conn) -> None:
    """Compare the direct recording-to-media fields using current conversion rules."""
    rows = iter_mysql_rows(
        mysql_conn,
        """SELECT recording_id, directory, filename, name, medium, duty_cycle_recording,
                  duty_cycle_period, note, file_date, file_time, file_size, md5_hash, DOI
           FROM recording""",
    )
    for row in rows:
        with pg_conn.cursor() as cur:
            cur.execute(
                """SELECT directory, filename, name, medium, duty_cycle_recording,
                          duty_cycle_period, note, date_time, size_b, md5_hash, doi
                   FROM media WHERE media_id = %s""",
                (row["recording_id"],),
            )
            target = cur.fetchone()
        if target is None:
            continue
        expected = {
            "directory": row["directory"], "filename": row["filename"], "name": row["name"],
            "medium": normalize_recording_medium(row["medium"]),
            "duty_cycle_recording": row["duty_cycle_recording"], "duty_cycle_period": row["duty_cycle_period"],
            "note": row["note"], "date_time": parse_legacy_date_time(row["file_date"], row["file_time"]),
            "size_b": safe_int(row["file_size"]), "md5_hash": row["md5_hash"], "doi": row["DOI"],
        }
        for (field_name, source_value), target_value in zip(expected.items(), target, strict=True):
            if not values_equivalent(source_value, target_value):
                audit_issue(
                    source_table="recording", source_id=row["recording_id"], target_table="media",
                    target_id=row["recording_id"], issue_type="field_mismatch", severity="error",
                    field_name=field_name, source_value=source_value, target_value=target_value,
                    reason="The target value differs from the value expected by the current migration rule.",
                    recommended_action="Correct the target value or update the approved migration mapping.",
                )


def run_row_level_audit(mysql_conn, pg_conn) -> None:
    audit_missing_target_rows(mysql_conn, pg_conn)
    audit_recording_field_mismatches(mysql_conn, pg_conn)
    _audit_derived_relations(mysql_conn, pg_conn)
    _audit_unresolved_enrichment(pg_conn)


def _audit_derived_relations(mysql_conn, pg_conn) -> None:
    """Audit source relations that are represented as derived target relations."""
    source_relations = fetch_all(mysql_conn, "SELECT site_id, collection_id FROM site_collection")
    with pg_conn.cursor() as cur:
        cur.execute("SELECT site_id, collection_id FROM site_collection")
        target_relations = {tuple(map(str, row)) for row in cur.fetchall()}
    for row in source_relations:
        relation = (str(row["site_id"]), str(row["collection_id"]))
        if relation not in target_relations:
            audit_issue(
                source_table="site_collection", source_id=":".join(relation), target_table="site_collection",
                issue_type="derived_relation_missing", severity="error", field_name="site_id,collection_id",
                source_value=":".join(relation),
                reason="The source site-collection relation is absent from the target.",
                recommended_action="Restore its parent records and migrate the relation again.",
            )


def _audit_unresolved_enrichment(pg_conn) -> None:
    with pg_conn.cursor() as cur:
        cur.execute("SELECT site_id, gadm0 FROM site WHERE gadm0_gid IS NOT NULL AND location IS NULL")
        unresolved_sites = cur.fetchall()
        cur.execute(
            """SELECT taxon_id, cached_scientific_name
               FROM taxon
               WHERE col_species_id IS NOT NULL
                 AND (col_genus_id IS NULL OR col_family_id IS NULL OR col_order_id IS NULL OR col_class_id IS NULL)"""
        )
        incomplete_taxa = cur.fetchall()
    for site_id, gadm0 in unresolved_sites:
        audit_issue(
            source_table="site", source_id=site_id, target_table="site", target_id=site_id,
            issue_type="enrichment_unresolved", severity="warning", field_name="location",
            source_value=gadm0,
            reason="The target geographic identifier exists but its location geometry is missing.",
            recommended_action="Complete the geographic enrichment and regenerate the site location.",
        )
    for taxon_id, scientific_name in incomplete_taxa:
        audit_issue(
            source_table="species", source_id=taxon_id, target_table="taxon", target_id=taxon_id,
            issue_type="enrichment_unresolved", severity="warning", field_name="col_*_id",
            source_value=scientific_name,
            reason="The target taxonomy hierarchy is incomplete.",
            recommended_action="Resolve the taxonomy match and complete the hierarchy fields.",
        )


def run_verification(mysql_conn, pg_conn) -> bool:
    log.info("=" * 60)
    log.info("VERIFICATION REPORT")
    log.info("=" * 60)
    all_ok = True
    for desc, mysql_sql, pg_sql in VERIFICATION_CHECKS:
        with mysql_cursor(mysql_conn) as cur:
            cur.execute(mysql_sql)
            mysql_count = cur.fetchone()
            mysql_count = list(mysql_count.values())[0] if mysql_count else 0
        with pg_conn.cursor() as cur:
            cur.execute(pg_sql)
            pg_count = cur.fetchone()[0]
        ok = mysql_count == pg_count
        status = "OK" if ok else "MISMATCH"
        if not ok:
            all_ok = False
        log.info("  %-30s  MySQL=%4d  PG=%4d  [%s]", desc, mysql_count, pg_count, status)

    # Check for broken FK references (media → user)
    try:
        with pg_conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM media m
                WHERE m.creator_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM "user" u WHERE u.user_id = m.creator_id)
            """)
            broken_fk = cur.fetchone()[0]
            if broken_fk > 0:
                log.warning("  Broken FK media→user: %d records", broken_fk)
                all_ok = False
            else:
                log.info("  %-30s  [OK]", "FK media→user integrity")
    except Exception as e:
        log.warning("  FK check failed: %s", e)

    try:
        with pg_conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM media_collection mc
                WHERE NOT EXISTS (SELECT 1 FROM media m WHERE m.media_id = mc.media_id)
                   OR NOT EXISTS (SELECT 1 FROM collection c WHERE c.collection_id = mc.collection_id)
            """)
            broken_links = cur.fetchone()[0]
            if broken_links > 0:
                log.warning("  Broken media_collection links: %d records", broken_links)
                all_ok = False
            else:
                log.info("  %-30s  [OK]", "media_collection integrity")
    except Exception as e:
        log.warning("  media_collection FK check failed: %s", e)

    try:
        recording_media_errors = verify_recording_media_migration(pg_conn)
        if recording_media_errors:
            for error in recording_media_errors:
                log.warning("  Recording/media transfer: %s", error)
            all_ok = False
        else:
            log.info("  %-30s  [OK]", "recording/media transfer integrity")
    except Exception as e:
        log.warning("  Recording/media transfer check failed: %s", e)
        all_ok = False

    try:
        audio_file_stats = verify_analysis_audio_files(pg_conn)
        if audio_file_stats["missing"]:
            all_ok = False
    except Exception as e:
        log.warning("  Analysis audio file check failed: %s", e)
        all_ok = False

    try:
        permission_errors = verify_user_permission_migration(mysql_conn, pg_conn)
        if permission_errors:
            for error in permission_errors:
                log.warning("  Permission transfer: %s", error)
            all_ok = False
        else:
            log.info("  %-30s  [OK]", "permission transfer integrity")
    except Exception as e:
        log.warning("  Permission transfer check failed: %s", e)
        all_ok = False

    try:
        legacy_rows = fetch_all(
            mysql_conn,
            """SELECT api_id, api, server_name, longitude, latitude, shared, last_updated
               FROM api
               ORDER BY api_id""",
        )
        expected_urls: dict[str, dict[str, Any]] = {}
        for row in legacy_rows:
            if int(row.get("shared") or 0) != 1:
                continue
            app_url = _decode_legacy_api_url(row.get("api"))
            if not app_url:
                continue
            existing = expected_urls.get(app_url)
            if existing is None:
                expected_urls[app_url] = row
                continue
            current_ts = row.get("last_updated")
            existing_ts = existing.get("last_updated")
            if existing_ts is None or (current_ts is not None and current_ts >= existing_ts):
                expected_urls[app_url] = row

        legacy_settings = {
            str(row["name"]): row["value"]
            for row in fetch_all(mysql_conn, "SELECT name, value FROM setting")
        }
        resolver_nodes = [
            {
                "app_url": app_url,
                "name": row.get("server_name"),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
            }
            for app_url, row in expected_urls.items()
        ]
        local_app_url, _source, expected_host_url, _server_name = _legacy_network_inputs(
            legacy_settings, resolver_nodes
        )
        expected_remote_urls = set(expected_urls) - ({local_app_url} if local_app_url else set())

        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM network_node WHERE is_local = FALSE")
            actual_remote_nodes = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM network_node WHERE app_url IS NULL OR app_url = ''")
            empty_urls = cur.fetchone()[0]
            cur.execute(
                """SELECT COUNT(*)
                   FROM (
                     SELECT app_url
                     FROM network_node
                     GROUP BY app_url
                     HAVING COUNT(*) > 1
                   ) duplicated"""
            )
            duplicate_urls = cur.fetchone()[0]
            cur.execute(
                """SELECT COUNT(*)
                   FROM network_node
                   WHERE is_local = FALSE
                     AND (
                       stat_users <> 0 OR stat_projects <> 0 OR stat_collections <> 0 OR stat_audios <> 0
                       OR stat_photos <> 0 OR stat_videos <> 0 OR stat_annotations <> 0 OR stat_sites <> 0
                     )"""
            )
            non_zero_stats = cur.fetchone()[0]
            cur.execute(
                """SELECT COUNT(*)
                   FROM network_node
                   WHERE is_local = FALSE
                     AND last_synced_at IS NULL"""
            )
            missing_synced_at = cur.fetchone()[0]
        if actual_remote_nodes != len(expected_remote_urls):
            log.warning(
                "  Network federation remote nodes: expected=%s actual=%s",
                len(expected_remote_urls),
                actual_remote_nodes,
            )
            all_ok = False
        else:
            log.info("  %-30s  [OK]", "network federation remote count")
        if empty_urls:
            log.warning("  Network federation: %s remote nodes have empty app_url", empty_urls)
            all_ok = False
        if duplicate_urls:
            log.warning("  Network federation: %s duplicated app_url values", duplicate_urls)
            all_ok = False
        if non_zero_stats:
            log.warning("  Network federation: %s transferred remote nodes have non-zero stats", non_zero_stats)
            all_ok = False
        if any(row.get("last_updated") is not None for row in expected_urls.values()) and missing_synced_at:
            log.warning("  Network federation: %s transferred remote nodes missing last_synced_at", missing_synced_at)
            all_ok = False
        elif not empty_urls and not duplicate_urls and not non_zero_stats and not missing_synced_at:
            log.info("  %-30s  [OK]", "network federation integrity")

        state_errors = verify_network_federation_state(
            pg_conn,
            expected_host_url=expected_host_url,
            require_local=local_app_url is not None,
        )
        if state_errors:
            for error in state_errors:
                log.warning("  Network federation: %s", error)
            all_ok = False
        else:
            log.info("  %-30s  [OK]", "network federation local node")
    except Exception as e:
        log.warning("  Network federation check failed: %s", e)
        all_ok = False

    try:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM site WHERE gadm0_gid IS NOT NULL AND location IS NULL")
            site_missing_location = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM site WHERE iho IS NOT NULL AND location_iho IS NULL")
            site_missing_iho = cur.fetchone()[0]
        if site_missing_location:
            log.warning("  Site geo enrichment: %s rows have gadm0_gid but no location", site_missing_location)
            all_ok = False
        else:
            log.info("  %-30s  [OK]", "site location enrichment")
        if site_missing_iho:
            log.warning("  Site geo enrichment: %s rows have iho but no location_iho", site_missing_iho)
            all_ok = False
        else:
            log.info("  %-30s  [OK]", "site IHO enrichment")
    except Exception as e:
        log.warning("  Site enrichment check failed: %s", e)
        all_ok = False

    try:
        with pg_conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM taxon
                WHERE col_species_id IS NOT NULL
                  AND (col_genus_id IS NULL OR col_family_id IS NULL OR col_order_id IS NULL OR col_class_id IS NULL OR last_synced IS NULL)
                """
            )
            taxon_incomplete = cur.fetchone()[0]
        if taxon_incomplete:
            log.warning("  Taxon enrichment: %s rows have incomplete col_* chain", taxon_incomplete)
            all_ok = False
        else:
            log.info("  %-30s  [OK]", "taxon XR enrichment")
    except Exception as e:
        log.warning("  Taxon enrichment check failed: %s", e)
        all_ok = False

    try:
        with mysql_cursor(mysql_conn) as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM (
                    SELECT DISTINCT sc.site_id, c.project_id
                    FROM site_collection sc
                    JOIN collection c ON c.collection_id = sc.collection_id
                    WHERE sc.site_id IS NOT NULL
                      AND c.project_id IS NOT NULL
                ) derived_rows
                """
            )
            expected_site_projects = cur.fetchone()["c"]
        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM site_project")
            actual_site_projects = cur.fetchone()[0]
        if expected_site_projects != actual_site_projects:
            log.warning(
                "  Site project derivation: expected=%s actual=%s [design_delta_expected]",
                expected_site_projects,
                actual_site_projects,
            )
        else:
            log.info("  %-30s  [OK]", "site_project derivation")
    except Exception as e:
        log.warning("  site_project check failed: %s", e)
        all_ok = False

    try:
        with mysql_cursor(mysql_conn) as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS c
                FROM (
                    SELECT DISTINCT recorder_id, microphone_id
                    FROM recording
                    WHERE recorder_id IS NOT NULL
                      AND microphone_id IS NOT NULL
                      AND recorder_id > 0
                      AND microphone_id > 0
                ) derived_rows
                """
            )
            expected_rm = cur.fetchone()["c"]
        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM recorder_microphone")
            actual_rm = cur.fetchone()[0]
        if expected_rm != actual_rm:
            log.warning(
                "  Recorder microphone derivation: expected=%s actual=%s [design_delta_expected]",
                expected_rm,
                actual_rm,
            )
        else:
            log.info("  %-30s  [OK]", "recorder_microphone derivation")
    except Exception as e:
        log.warning("  recorder_microphone check failed: %s", e)
        all_ok = False

    try:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM file_upload WHERE media_id IS NULL")
            null_media_uploads = cur.fetchone()[0]
        log.info("  %-30s  preserved_null_media=%d", "file_upload semantic state", null_media_uploads)
    except Exception as e:
        log.warning("  file_upload semantic check failed: %s", e)
        all_ok = False

    log.info("=" * 60)
    return all_ok


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def _write_audit_report(audit: MigrationAudit, audit_report: Path) -> None:
    if write_audit_workbook(audit, audit_report):
        log.info("Migration audit report written: %s (%d issues)", audit_report, audit.count)
    else:
        log.info("Migration audit found no row-level issues; no workbook was created.")


def run_migration(
    dry_run: bool = False,
    reset_target: bool = False,
    audit_report: Path | None = None,
    batch_size: int = 1_000,
) -> None:
    global ACTIVE_AUDIT, CURRENT_BATCH_SIZE
    audit = MigrationAudit()
    ACTIVE_AUDIT = audit
    CURRENT_BATCH_SIZE = batch_size
    log.info("Connecting to MySQL (%s:%s/%s)...",
             os.getenv("MYSQL_HOST", "host.docker.internal"),
             os.getenv("MYSQL_PORT", "13306"),
             os.getenv("MYSQL_DB", "biosounds"))
    mysql_conn = get_mysql_conn()

    log.info("Connecting to PostgreSQL (%s:%s/%s)...",
             os.getenv("POSTGRES_SERVER", "db"),
             os.getenv("POSTGRES_PORT", "5432"),
             os.getenv("POSTGRES_DB", "ecosignal"))
    pg_conn = get_pg_conn()
    log.info("Connecting to Geo DB (%s:%s/%s)...",
             os.getenv("GEO_DB_SERVER", "geo_db"),
             os.getenv("GEO_DB_PORT", "5432"),
             os.getenv("GEO_DB_NAME", "geo_db"))
    geo_conn = get_geo_conn()
    reset_enrichment_stats()
    reset_derived_migration_stats()

    if dry_run:
        log.info("DRY-RUN mode: no data will be written to PostgreSQL")

    try:
        if target_has_business_data(pg_conn):
            if not reset_target:
                raise RuntimeError("Target PostgreSQL already contains business data. Re-run with --reset-target.")
            if dry_run:
                log.info("DRY-RUN: target reset requested but not executed.")
            else:
                log.info("--- Resetting target business data ---")
                reset_target_data(pg_conn)
                pg_conn.commit()

        # ---- Phase 1: Base / reference data ----
        log.info("--- Phase 1: Base / reference data ---")
        steps = [
            ("roles", migrate_roles),
            ("licenses", migrate_licenses),
            ("iucn_get", migrate_iucn_get),
            ("recorders", migrate_recorders),
            ("microphones", migrate_microphones),
            ("sound_classification", migrate_sound_classification),
            ("taxon_sound_type", migrate_taxon_sound_type),
            ("annotation_review_status", migrate_annotation_review_status),
            ("index_type", migrate_index_type),
            ("models", migrate_models),
        ]
        for name, fn in steps:
            count = fn(mysql_conn, pg_conn, dry_run)
            log.info("  %-35s  %4d rows", name, count)
        if not dry_run:
            pg_conn.commit()
            log.info("Phase 1 committed.")

        # ---- Phase 2: Core entities ----
        log.info("--- Phase 2: Core entities ---")
        steps2 = [
            ("users + preferences", migrate_users),
            ("sites", lambda my, pg, dry: migrate_sites(my, pg, dry, geo_conn=geo_conn)),
            ("projects", migrate_projects),
            ("collections + project_collection", migrate_collections),
            ("site_collections", migrate_site_collections),
            ("site_projects (derived)", migrate_site_projects),
            ("taxon (species)", lambda my, pg, dry: migrate_taxon(my, pg, dry, geo_conn=geo_conn)),
            ("recorder_microphones (derived)", migrate_recorder_microphones),
            ("sensors", migrate_sensors),
        ]
        for name, fn in steps2:
            count = fn(mysql_conn, pg_conn, dry_run)
            log.info("  %-35s  %4d rows", name, count)
        if not dry_run:
            pg_conn.commit()
            log.info("Phase 2 committed.")

        # ---- Phase 3: Associations & sub-resources ----
        log.info("--- Phase 3: Associations & sub-resources ---")
        steps3 = [
            ("recordings→audio_setting+media", migrate_recordings),
            ("spectrograms→preview", migrate_spectrograms),
            ("tags→annotation", migrate_annotations),
            ("tag_reviews→annotation_review", migrate_annotation_reviews),
            ("labels", migrate_labels),
            ("label_media", migrate_label_media),
            ("index_log", migrate_index_log),
            ("file_upload", migrate_file_upload),
            ("news", migrate_news),
            ("queue", migrate_queue),
            ("tasks", migrate_tasks),
            ("settings", migrate_settings),
            ("network_federation", migrate_network_federation),
            ("user_permissions", migrate_user_permissions),
        ]
        for name, fn in steps3:
            count = fn(mysql_conn, pg_conn, dry_run)
            log.info("  %-35s  %4d rows", name, count)
        if not dry_run:
            pg_conn.commit()
            log.info("Phase 3 committed.")
            log.info(
                "Site geo enrichment: gadm_gid=%d iho_geometry=%d location_geometry=%d ambiguous_gadm=%d missing_match=%d",
                SITE_GEO_ENRICHMENT_STATS["resolved_gadm_gid_count"],
                SITE_GEO_ENRICHMENT_STATS["resolved_iho_geometry_count"],
                SITE_GEO_ENRICHMENT_STATS["resolved_location_geometry_count"],
                SITE_GEO_ENRICHMENT_STATS["ambiguous_gadm_count"],
                SITE_GEO_ENRICHMENT_STATS["missing_geo_match_count"],
            )
            log.info(
                "Taxon XR enrichment: matched=%d ambiguous=%d missing=%d",
                TAXON_ENRICHMENT_STATS["matched_count"],
                TAXON_ENRICHMENT_STATS["ambiguous_taxon_match"],
                TAXON_ENRICHMENT_STATS["missing_taxon_match"],
            )
            log.info(
                "Derived relations: site_collection(skipped=%d dedup=%d) site_project(derived=%d skipped=%d dedup=%d) "
                "recorder_microphone(derived=%d skipped=%d dedup=%d) file_upload(skipped=%d null_media=%d)",
                DERIVED_MIGRATION_STATS["site_collection"]["skipped_orphan_count"],
                DERIVED_MIGRATION_STATS["site_collection"]["deduplicated_count"],
                DERIVED_MIGRATION_STATS["site_project"]["derived_count"],
                DERIVED_MIGRATION_STATS["site_project"]["skipped_orphan_count"],
                DERIVED_MIGRATION_STATS["site_project"]["deduplicated_count"],
                DERIVED_MIGRATION_STATS["recorder_microphone"]["derived_count"],
                DERIVED_MIGRATION_STATS["recorder_microphone"]["skipped_orphan_count"],
                DERIVED_MIGRATION_STATS["recorder_microphone"]["deduplicated_count"],
                DERIVED_MIGRATION_STATS["file_upload"]["skipped_orphan_count"],
                DERIVED_MIGRATION_STATS["file_upload"]["preserved_null_media_count"],
            )

        # ---- Phase 5a: Reset sequences ----
        if not dry_run:
            log.info("--- Phase 5a: Reset PostgreSQL sequences ---")
            reset_sequences(pg_conn)
            pg_conn.commit()
            log.info("Sequences reset and committed.")

        log.info("Data transfer completed successfully.")

    except Exception as e:
        log.exception("Data transfer failed: %s", e)
        pg_conn.rollback()
        sys.exit(1)
    finally:
        mysql_conn.close()
        pg_conn.close()
        geo_conn.close()
        if audit_report is not None:
            _write_audit_report(audit, audit_report)
        ACTIVE_AUDIT = None


def run_verify_only(audit_report: Path | None = None, deep_audit: bool = False) -> None:
    global ACTIVE_AUDIT
    audit = MigrationAudit()
    ACTIVE_AUDIT = audit
    log.info("Connecting to databases for verification...")
    mysql_conn = get_mysql_conn()
    pg_conn = get_pg_conn()
    try:
        ok = run_verification(mysql_conn, pg_conn)
        if deep_audit:
            run_row_level_audit(mysql_conn, pg_conn)
        if audit.count:
            ok = False
        if not ok:
            log.warning("Verification found mismatches.")
            sys.exit(2)
        else:
            log.info("All verification checks passed.")
    finally:
        mysql_conn.close()
        pg_conn.close()
        if audit_report is not None:
            _write_audit_report(audit, audit_report)
        ACTIVE_AUDIT = None


def run_network_federation_repair(dry_run: bool) -> None:
    log.info("Connecting to PostgreSQL for federation repair...")
    pg_conn = get_pg_conn()
    try:
        changes = repair_network_federation(pg_conn, dry_run=dry_run)
        if dry_run:
            pg_conn.rollback()
            log.info("Federation repair dry-run completed; no data was changed.")
            return

        errors = verify_network_federation_state(
            pg_conn,
            expected_host_url=changes["host_url"],
            require_local=True,
        )
        if errors:
            pg_conn.rollback()
            for error in errors:
                log.error("Federation repair verification failed: %s", error)
            raise RuntimeError("Federation repair verification failed; transaction rolled back")
        pg_conn.commit()
        log.info("Federation repair completed and verified successfully.")
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        pg_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transfer data from the configured MySQL source to PostgreSQL"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the transfer without writing to PostgreSQL",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only run verification checks without transferring data",
    )
    parser.add_argument(
        "--reset-target",
        action="store_true",
        help="Clear target business data before transfer",
    )
    parser.add_argument(
        "--repair-preview-filenames",
        action="store_true",
        help="Normalize existing preview.filename values to basename only",
    )
    parser.add_argument(
        "--repair-network-federation",
        action="store_true",
        help="Repair only the local federation node and host URL",
    )
    parser.add_argument(
        "--report-field-coverage",
        action="store_true",
        help="Print source-to-target field coverage stats and unmapped fields",
    )
    parser.add_argument(
        "--compare-media-id",
        type=int,
        help="Compare one target media sample against source recording fields",
    )
    parser.add_argument(
        "--audit-report",
        type=Path,
        default=Path("/tmp/migration-audit.xlsx"),
        help="Write row-level migration issues to this XLSX path.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1_000,
        help="Number of source rows to stream and commit per batch.",
    )
    parser.add_argument(
        "--deep-audit",
        action="store_true",
        help="Run the slower row-by-row source-to-target audit with bounded memory.",
    )
    args = parser.parse_args()

    if args.report_field_coverage:
        mysql_conn = get_mysql_conn()
        pg_conn = get_pg_conn()
        try:
            print_field_coverage_report(mysql_conn, pg_conn)
        finally:
            mysql_conn.close()
            pg_conn.close()
    elif args.compare_media_id is not None:
        mysql_conn = get_mysql_conn()
        pg_conn = get_pg_conn()
        try:
            compare_media_sample(mysql_conn, pg_conn, args.compare_media_id)
        finally:
            mysql_conn.close()
            pg_conn.close()
    elif args.verify:
        run_verify_only(audit_report=args.audit_report, deep_audit=args.deep_audit)
    elif args.repair_network_federation:
        run_network_federation_repair(dry_run=args.dry_run)
    elif args.repair_preview_filenames:
        pg_conn = get_pg_conn()
        try:
            stats = repair_preview_filenames(pg_conn, dry_run=args.dry_run)
            if not args.dry_run:
                pg_conn.commit()
            log.info(
                "Preview filename repair finished: updated=%d unchanged=%d skipped=%d ambiguous=%d dry_run=%s",
                stats["updated"],
                stats["unchanged"],
                stats["skipped"],
                stats["ambiguous"],
                args.dry_run,
            )
        finally:
            pg_conn.close()
    else:
        if args.batch_size < 1:
            parser.error("--batch-size must be greater than zero")
        run_migration(
            dry_run=args.dry_run,
            reset_target=args.reset_target,
            audit_report=args.audit_report,
            batch_size=args.batch_size,
        )
        if not args.dry_run:
            log.info("--- Phase 5b: Verification ---")
            mysql_conn = get_mysql_conn()
            pg_conn = get_pg_conn()
            try:
                run_verification(mysql_conn, pg_conn)
            finally:
                mysql_conn.close()
                pg_conn.close()


if __name__ == "__main__":
    main()
