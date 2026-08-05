"""Reusable FastAPI query dependencies."""
from datetime import datetime
from typing import Any

from fastapi import Query
from fastapi.params import Param

from app.utils import parse_range, parse_uuid


def _resolve_query_value(value: Any) -> Any:
    """Unwrap FastAPI Param defaults when instantiating dependencies in tests."""
    if isinstance(value, Param):
        return value.default
    return value


class MediaFilterQueryParams:
    """Shared query dependency for audio/media list style filters."""

    def __init__(
        self,
        search: str | None = Query(default=None, description="搜索文件名、名称、媒介、备注 / Search in filename, name, medium, note"),
        name: str | None = Query(default=None, description="通过名称筛选（模糊） / Filter by name (fuzzy)"),
        filename: str | None = Query(default=None, description="通过文件名筛选（模糊） / Filter by filename (fuzzy)"),
        uuid: str | None = Query(default=None, description="通过 UUID 筛选（精确） / Filter by UUID (exact)"),
        media_type: str | None = Query(default=None, description="通过媒体类型筛选（精确：audio/photo） / Filter by media type (exact: audio/photo)"),
        type: str | None = Query(default=None, description="通过文件类型文本筛选 metadata/file/true/false / Filter by file type alias metadata/file/true/false"),
        site_id: int | None = Query(default=None, description="通过站点 ID 筛选 / Filter by Site ID"),
        site_name: str | None = Query(default=None, description="通过站点名称模糊筛选（大小写不敏感） / Fuzzy filter by site name (case-insensitive)"),
        sensor_id: int | None = Query(default=None, description="通过传感器 ID 筛选 / Filter by Sensor ID"),
        sensor_name: str | None = Query(default=None, description="通过传感器名称模糊筛选（大小写不敏感） / Fuzzy filter by sensor name (case-insensitive)"),
        medium: str | None = Query(default=None, description="通过媒介筛选（模糊） / Filter by medium (fuzzy)"),
        sampling_rate_hz: str | None = Query(default=None, description="采样率区间 min,max / Sample rate range min,max"),
        bit_depth: str | None = Query(default=None, description="位深区间 min,max / Bit depth range min,max"),
        channel_num: str | None = Query(default=None, description="声道数区间 min,max / Channels range min,max"),
        duration_s: str | None = Query(default=None, description="时长区间(s) min,max / Duration range (s) min,max"),
        size_b: str | None = Query(default=None, description="文件大小区间 min,max / Size range (bytes) min,max"),
        recording_gain_db: str | None = Query(default=None, description="增益区间(dB) min,max / Gain range (dB) min,max"),
        exposure_ms: str | None = Query(default=None, description="曝光时间区间(ms) min,max / Exposure range (ms) min,max"),
        aperture: str | None = Query(default=None, description="光圈区间 min,max / Aperture range min,max"),
        iso: str | None = Query(default=None, description="ISO 区间 min,max / ISO range min,max"),
        duty_cycle_period: str | None = Query(default=None, description="录制周期区间(s) min,max / Duty period range (s) min,max"),
        duty_cycle_recording: str | None = Query(default=None, description="录制时长区间(s) min,max / Duty cycle recording range min,max"),
        license_id: int | None = Query(default=None, description="通过许可证 ID 筛选 / Filter by License ID"),
        license_name: str | None = Query(default=None, description="通过许可证名称模糊筛选（大小写不敏感） / Fuzzy filter by license name (case-insensitive)"),
        doi: str | None = Query(default=None, description="通过 DOI 筛选（模糊） / Filter by DOI (fuzzy)"),
        note: str | None = Query(default=None, description="通过备注筛选（模糊） / Filter by note (fuzzy)"),
        uploader_id: int | None = Query(default=None, description="通过上传者 ID 筛选 / Filter by Uploader ID"),
        uploader_name: str | None = Query(default=None, description="通过上传者名称模糊筛选（大小写不敏感） / Fuzzy filter by uploader name (case-insensitive)"),
        creator_id: int | None = Query(default=None, description="通过创建者 ID 筛选 / Filter by Creator ID"),
        creator_name: str | None = Query(default=None, description="通过创建者名称模糊筛选（大小写不敏感） / Fuzzy filter by creator name (case-insensitive)"),
        creation_date_from: datetime | None = Query(default=None, description="从创建日期筛选 / Filter by creation date (from)"),
        creation_date_to: datetime | None = Query(default=None, description="至创建日期筛选 / Filter by creation date (to)"),
        label_id: int | None = Query(default=None, description="通过标签 ID 筛选（精确） / Filter by label ID (exact)"),
        label_name: str | None = Query(default=None, description="通过标签名称模糊筛选（大小写不敏感） / Fuzzy filter by label name (case-insensitive)"),
        media_id: int | None = Query(default=None, description="按媒体 ID 精确筛选 / Filter by media ID (exact)"),
        date_time_from: datetime | None = Query(default=None, description="录制时间起 / Recording time from"),
        date_time_to: datetime | None = Query(default=None, description="录制时间止 / Recording time to"),
        is_metadata: bool | None = Query(default=None, description="按是否为元数据筛选 / Filter by metadata flag"),
    ) -> None:
        raw_values = {
            "search": search,
            "name": name,
            "filename": filename,
            "uuid": uuid,
            "media_type": media_type,
            "site_id": site_id,
            "site_name": site_name,
            "sensor_id": sensor_id,
            "sensor_name": sensor_name,
            "type": type,
            "medium": medium,
            "sampling_rate_hz": sampling_rate_hz,
            "bit_depth": bit_depth,
            "channel_num": channel_num,
            "duration_s": duration_s,
            "size_b": size_b,
            "recording_gain_db": recording_gain_db,
            "exposure_ms": exposure_ms,
            "aperture": aperture,
            "iso": iso,
            "duty_cycle_period": duty_cycle_period,
            "duty_cycle_recording": duty_cycle_recording,
            "license_id": license_id,
            "license_name": license_name,
            "doi": doi,
            "note": note,
            "uploader_id": uploader_id,
            "uploader_name": uploader_name,
            "creator_id": creator_id,
            "creator_name": creator_name,
            "creation_date_from": creation_date_from,
            "creation_date_to": creation_date_to,
            "label_id": label_id,
            "label_name": label_name,
            "media_id": media_id,
            "date_time_from": date_time_from,
            "date_time_to": date_time_to,
            "is_metadata": is_metadata,
        }
        for field, value in raw_values.items():
            setattr(self, field, _resolve_query_value(value))

    def to_filter_dict(self, include_site_filter: bool = True) -> dict[str, Any]:
        """Normalize media-style query params into repository/service filters."""
        sr_min, sr_max = parse_range(self.sampling_rate_hz)
        bd_min, bd_max = parse_range(self.bit_depth)
        ch_min, ch_max = parse_range(self.channel_num)
        dur_min, dur_max = parse_range(self.duration_s)
        size_min, size_max = parse_range(self.size_b)
        gain_min, gain_max = parse_range(self.recording_gain_db)
        exposure_ms_min, exposure_ms_max = parse_range(self.exposure_ms)
        aperture_min, aperture_max = parse_range(self.aperture)
        iso_min, iso_max = parse_range(self.iso)
        duty_recording_min, duty_recording_max = parse_range(
            self.duty_cycle_recording
        )
        duty_period_min, duty_period_max = parse_range(self.duty_cycle_period)

        filters = {
            "search": self.search,
            "name": self.name,
            "filename": self.filename,
            "uuid": parse_uuid(self.uuid),
            "media_type": self.media_type,
            "site_id": self.site_id if include_site_filter else None,
            "site_name": self.site_name if include_site_filter else None,
            "sensor_id": self.sensor_id,
            "sensor_name": self.sensor_name,
            "type": self.type,
            "medium": self.medium,
            "sampling_rate_hz_min": sr_min,
            "sampling_rate_hz_max": sr_max,
            "bit_depth_min": bd_min,
            "bit_depth_max": bd_max,
            "channel_num_min": ch_min,
            "channel_num_max": ch_max,
            "duration_s_min": dur_min,
            "duration_s_max": dur_max,
            "size_b_min": size_min,
            "size_b_max": size_max,
            "recording_gain_db_min": gain_min,
            "recording_gain_db_max": gain_max,
            "exposure_ms_min": exposure_ms_min,
            "exposure_ms_max": exposure_ms_max,
            "aperture_min": aperture_min,
            "aperture_max": aperture_max,
            "iso_min": iso_min,
            "iso_max": iso_max,
            "duty_cycle_recording_min": duty_recording_min,
            "duty_cycle_recording_max": duty_recording_max,
            "duty_cycle_period_min": duty_period_min,
            "duty_cycle_period_max": duty_period_max,
            "license_id": self.license_id,
            "license_name": self.license_name,
            "doi": self.doi,
            "note": self.note,
            "uploader_id": self.uploader_id,
            "uploader_name": self.uploader_name,
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "creation_date_from": self.creation_date_from,
            "creation_date_to": self.creation_date_to,
            "label_id": self.label_id,
            "label_name": self.label_name,
            "media_id": self.media_id,
            "date_time_from": self.date_time_from,
            "date_time_to": self.date_time_to,
            "is_metadata": self.is_metadata,
        }
        # is_metadata is a bool so we must keep False values; use explicit None check
        return {key: value for key, value in filters.items() if value is not None}
