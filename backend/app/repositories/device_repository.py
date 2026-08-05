from typing import Any

from sqlalchemy import case
from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, select

from app.models.device import (
    Camera,
    CameraLens,
    Lens,
    Microphone,
    Recorder,
    RecorderMicrophone,
    Sensor,
)
from app.models.media import License, Media
from app.repositories.query_helpers import (
    FilterOp,
    FilterSpec,
    apply_filters,
    apply_ordering,
    apply_pagination,
)


def has_normalized_name(
    session: Session,
    model: type[Recorder] | type[Microphone] | type[Camera] | type[Lens] | type[Sensor] | type[License],
    name: str,
    exclude_id: int | None = None,
) -> bool:
    """Return whether a device of the same type already has this name."""
    primary_key = {
        Recorder: Recorder.recorder_id,
        Microphone: Microphone.microphone_id,
        Camera: Camera.camera_id,
        Lens: Lens.lens_id,
        Sensor: Sensor.sensor_id,
        License: License.license_id,
    }[model]
    stmt = select(func.count()).select_from(model).where(
        func.lower(func.trim(model.name)) == name.casefold()
    )
    if exclude_id is not None:
        stmt = stmt.where(primary_key != exclude_id)
    return session.exec(stmt).one() > 0


def get_normalized_names(
    session: Session,
    model: type[Recorder] | type[Microphone] | type[Camera] | type[Lens] | type[Sensor] | type[License],
) -> set[str]:
    """Return all normalized (lower/trim) device names for bulk duplicate checks."""
    stmt = select(func.lower(func.trim(model.name)))
    return set(session.exec(stmt).all())

_MICROPHONE_FILTER_SPECS: list[FilterSpec] = [
    ("microphone_id",         Microphone.microphone_id,         FilterOp.EQ),
    ("uuid",                  Microphone.uuid,                  FilterOp.EQ),
    ("name",                  Microphone.name,                  FilterOp.LIKE),
    ("microphone_element",    Microphone.microphone_element,    FilterOp.LIKE),
    ("sensitivity",           Microphone.sensitivity,           FilterOp.RANGE),
    ("signal_to_noise_ratio", Microphone.signal_to_noise_ratio, FilterOp.RANGE),
]

_MICROPHONE_SORT_FIELDS: dict[str, Any] = {
    "microphone_id":         Microphone.microphone_id,
    "uuid":                  Microphone.uuid,
    "name":                  Microphone.name,
    "microphone_element":    Microphone.microphone_element,
    "sensitivity":           Microphone.sensitivity,
    "signal_to_noise_ratio": Microphone.signal_to_noise_ratio,
}

_SENSOR_IS_DEFAULT = case(
    (Sensor.sensor_type == "audio", RecorderMicrophone.is_default),
    (Sensor.sensor_type == "photo", CameraLens.is_default),
    else_=None,
)

_SENSOR_FILTER_SPECS: list[FilterSpec] = [
    ("sensor_id",     Sensor.sensor_id,     FilterOp.EQ),
    ("uuid",          Sensor.uuid,          FilterOp.EQ),
    ("name",          Sensor.name,          FilterOp.LIKE),
    ("description",   Sensor.description,   FilterOp.LIKE),
    ("sensor_type",   Sensor.sensor_type,   FilterOp.LIKE),
    ("recorder_id",   Sensor.recorder_id,   FilterOp.EQ),
    ("microphone_id", Sensor.microphone_id, FilterOp.EQ),
    ("camera_id",     Sensor.camera_id,     FilterOp.EQ),
    ("lens_id",       Sensor.lens_id,       FilterOp.EQ),
    ("recorder_name",   Recorder.name,     FilterOp.LIKE),
    ("microphone_name", Microphone.name,   FilterOp.LIKE),
    ("camera_name",     Camera.name,       FilterOp.LIKE),
    ("lens_name",       Lens.name,         FilterOp.LIKE),
    ("creation_date", Sensor.creation_date, FilterOp.DATE_RANGE),
]

_SENSOR_SORT_FIELDS: dict[str, Any] = {
    "sensor_id":        Sensor.sensor_id,
    "uuid":             Sensor.uuid,
    "name":             Sensor.name,
    "sensor_type":      Sensor.sensor_type,
    "recorder_name":    Recorder.name,
    "microphone_name":  Microphone.name,
    "camera_name":      Camera.name,
    "lens_name":        Lens.name,
    "creation_date":    Sensor.creation_date,
}

_CAMERA_FILTER_SPECS: list[FilterSpec] = [
    ("camera_id", Camera.camera_id, FilterOp.EQ),
    ("uuid",      Camera.uuid,      FilterOp.EQ),
    ("name",    Camera.name,    FilterOp.LIKE),
    ("version", Camera.version, FilterOp.LIKE),
    ("brand",   Camera.brand,   FilterOp.LIKE),
]

_CAMERA_SORT_FIELDS: dict[str, Any] = {
    "camera_id": Camera.camera_id,
    "uuid":      Camera.uuid,
    "name":    Camera.name,
    "version": Camera.version,
    "brand":   Camera.brand,
}

_LENS_FILTER_SPECS: list[FilterSpec] = [
    ("lens_id",      Lens.lens_id,      FilterOp.EQ),
    ("uuid",         Lens.uuid,         FilterOp.EQ),
    ("name",         Lens.name,         FilterOp.LIKE),
    ("focal_length", Lens.focal_length, FilterOp.LIKE),
    ("max_aperture", Lens.max_aperture, FilterOp.LIKE),
    ("brand",        Lens.brand,        FilterOp.LIKE),
]

_LENS_SORT_FIELDS: dict[str, Any] = {
    "lens_id":      Lens.lens_id,
    "uuid":         Lens.uuid,
    "name":         Lens.name,
    "focal_length": Lens.focal_length,
    "max_aperture": Lens.max_aperture,
    "brand":        Lens.brand,
}

_LICENSE_FILTER_SPECS: list[FilterSpec] = [
    ("license_id", License.license_id, FilterOp.EQ),
    ("name", License.name, FilterOp.LIKE),
    ("link", License.link, FilterOp.LIKE),
]

_LICENSE_SORT_FIELDS: dict[str, Any] = {
    "license_id": License.license_id,
    "name": License.name,
    "link": License.link,
}

_RECORDER_FILTER_SPECS: list[FilterSpec] = [
    ("recorder_id", Recorder.recorder_id, FilterOp.EQ),
    ("uuid",        Recorder.uuid,        FilterOp.EQ),
    ("name",    Recorder.name,    FilterOp.LIKE),
    ("version", Recorder.version, FilterOp.LIKE),
    ("brand",   Recorder.brand,   FilterOp.LIKE),
]

_RECORDER_SORT_FIELDS: dict[str, Any] = {
    "recorder_id": Recorder.recorder_id,
    "uuid":        Recorder.uuid,
    "name":    Recorder.name,
    "version": Recorder.version,
    "brand":   Recorder.brand,
}


def get_licenses(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[License], int]:
    filters = filters or {}
    count_stmt = apply_filters(select(func.count()).select_from(License), filters, _LICENSE_FILTER_SPECS)
    total = session.exec(count_stmt).one()
    stmt = apply_filters(select(License), filters, _LICENSE_FILTER_SPECS)
    stmt = apply_ordering(stmt, order_by, order_dir, _LICENSE_SORT_FIELDS, License.name, License.license_id)
    stmt = apply_pagination(stmt, page, page_size)
    items = session.exec(stmt).all()
    return list(items), total


def get_license_by_id(session: Session, license_id: int) -> License | None:
    return session.get(License, license_id)


def create_license(session: Session, name: str, link: str) -> License:
    obj = License(name=name, link=link)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def update_license(session: Session, obj: License, name: str | None, link: str | None) -> License:
    if name is not None:
        obj.name = name
    if link is not None:
        obj.link = link
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def is_license_in_use(session: Session, license_id: int) -> bool:
    count = session.exec(
        select(func.count()).select_from(Media).where(Media.license_id == license_id)
    ).one()
    return count > 0


def delete_license(session: Session, obj: License) -> None:
    session.delete(obj)
    session.commit()



def get_recorders(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[tuple[Recorder, int]], int]:
    filters = filters or {}
    subq = (
        select(RecorderMicrophone.recorder_id, func.count().label("cnt"))
        .group_by(RecorderMicrophone.recorder_id)
        .subquery()
    )
    count_base = (
        select(Recorder.recorder_id)
        .outerjoin(subq, Recorder.recorder_id == subq.c.recorder_id)
    )
    count_base = apply_filters(count_base, filters, _RECORDER_FILTER_SPECS)
    if filters.get("microphone_count") is not None:
        count_base = count_base.where(func.coalesce(subq.c.cnt, 0) == filters["microphone_count"])
    total = session.exec(select(func.count()).select_from(count_base.subquery())).one()

    stmt = (
        select(Recorder, func.coalesce(subq.c.cnt, 0).label("microphone_count"))
        .outerjoin(subq, Recorder.recorder_id == subq.c.recorder_id)
    )
    stmt = apply_filters(stmt, filters, _RECORDER_FILTER_SPECS)
    if filters.get("microphone_count") is not None:
        stmt = stmt.where(func.coalesce(subq.c.cnt, 0) == filters["microphone_count"])
    recorder_sort_fields = {
        **_RECORDER_SORT_FIELDS,
        "microphone_count": func.coalesce(subq.c.cnt, 0),
    }
    stmt = apply_ordering(stmt, order_by, order_dir, recorder_sort_fields, Recorder.name, Recorder.recorder_id)
    stmt = apply_pagination(stmt, page, page_size)
    rows = session.exec(stmt).all()
    return list(rows), total


def get_recorder_by_id(session: Session, recorder_id: int) -> Recorder | None:
    return session.get(Recorder, recorder_id)


def create_recorder(session: Session, name: str | None, version: str | None, brand: str | None) -> Recorder:
    obj = Recorder(name=name, version=version, brand=brand)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def update_recorder(
    session: Session, obj: Recorder, update_data: dict[str, Any]
) -> Recorder:
    for field, value in update_data.items():
        setattr(obj, field, value)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def is_recorder_in_use(session: Session, recorder_id: int) -> bool:
    sensor_count = session.exec(
        select(func.count()).select_from(Sensor).where(Sensor.recorder_id == recorder_id)
    ).one()
    return sensor_count > 0


def delete_recorder(session: Session, obj: Recorder) -> None:
    session.delete(obj)
    session.commit()


def get_recorder_microphones(session: Session, recorder_id: int) -> list[RecorderMicrophone]:
    stmt = (
        select(RecorderMicrophone)
        .options(selectinload(RecorderMicrophone.microphone))
        .where(RecorderMicrophone.recorder_id == recorder_id)
        .order_by(RecorderMicrophone.microphone_id)
    )
    return list(session.exec(stmt).all())


def get_microphone_recorders(session: Session, microphone_id: int) -> list[RecorderMicrophone]:
    stmt = (
        select(RecorderMicrophone)
        .options(selectinload(RecorderMicrophone.recorder))
        .where(RecorderMicrophone.microphone_id == microphone_id)
        .order_by(RecorderMicrophone.recorder_id)
    )
    return list(session.exec(stmt).all())


def get_recorder_microphone(session: Session, recorder_id: int, microphone_id: int) -> RecorderMicrophone | None:
    return session.get(RecorderMicrophone, (recorder_id, microphone_id))


def ensure_recorder_microphone(
    session: Session,
    recorder_id: int,
    microphone_id: int,
    is_default: bool | None = None,
) -> RecorderMicrophone:
    """Stage a recorder-microphone association and optionally update its default flag."""
    existing = get_recorder_microphone(session, recorder_id, microphone_id)
    if existing:
        if is_default is True:
            _clear_recorder_default_microphones(session, recorder_id)
            existing.is_default = True
            session.add(existing)
        elif is_default is False:
            existing.is_default = False
            session.add(existing)
        return existing

    if is_default is True:
        _clear_recorder_default_microphones(session, recorder_id)
    obj = RecorderMicrophone(
        recorder_id=recorder_id,
        microphone_id=microphone_id,
        is_default=is_default is True,
        notes=None,
    )
    session.add(obj)
    return obj


def _clear_recorder_default_microphones(session: Session, recorder_id: int) -> None:
    """Clear the current default before assigning a new one for a recorder."""
    session.exec(
        select(Recorder.recorder_id)
        .where(Recorder.recorder_id == recorder_id)
        .with_for_update()
    ).one()
    stmt = select(RecorderMicrophone).where(
        RecorderMicrophone.recorder_id == recorder_id,
        RecorderMicrophone.is_default.is_(True),
    )
    for association in session.exec(stmt).all():
        association.is_default = False
        session.add(association)


def add_recorder_microphone(
    session: Session, recorder_id: int, microphone_id: int,
    is_default: bool | None, notes: str | None
) -> RecorderMicrophone:
    obj = ensure_recorder_microphone(session, recorder_id, microphone_id, is_default)
    obj.notes = notes
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def remove_recorder_microphone(session: Session, obj: RecorderMicrophone) -> None:
    session.delete(obj)
    session.commit()



def get_microphones(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[tuple[Microphone, int]], int]:
    filters = filters or {}
    subq = (
        select(RecorderMicrophone.microphone_id, func.count().label("cnt"))
        .group_by(RecorderMicrophone.microphone_id)
        .subquery()
    )
    recorder_count_col = func.coalesce(subq.c.cnt, 0)
    base_stmt = (
        select(Microphone, recorder_count_col.label("recorder_count"))
        .outerjoin(subq, Microphone.microphone_id == subq.c.microphone_id)
    )

    if filters.get("recorder_id") is not None:
        linked_microphone_ids = select(RecorderMicrophone.microphone_id).where(
            RecorderMicrophone.recorder_id == filters["recorder_id"]
        ).distinct()
        base_stmt = base_stmt.where(Microphone.microphone_id.in_(linked_microphone_ids))

    base_stmt = apply_filters(base_stmt, filters, _MICROPHONE_FILTER_SPECS)
    if filters.get("recorder_count") is not None:
        base_stmt = base_stmt.where(recorder_count_col == filters["recorder_count"])

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = session.exec(count_stmt).one()

    microphone_sort_fields = {
        **_MICROPHONE_SORT_FIELDS,
        "recorder_count": recorder_count_col,
    }
    stmt = apply_ordering(
        base_stmt,
        order_by,
        order_dir,
        microphone_sort_fields,
        Microphone.name,
        Microphone.microphone_id,
    )
    stmt = apply_pagination(stmt, page, page_size)
    rows = session.exec(stmt).all()
    return list(rows), total


def get_microphone_by_id(session: Session, microphone_id: int) -> Microphone | None:
    return session.get(Microphone, microphone_id)


def create_microphone(
    session: Session,
    name: str | None,
    microphone_element: str | None,
    sensitivity: int | None,
    signal_to_noise_ratio: int | None
) -> Microphone:
    obj = Microphone(
        name=name,
        microphone_element=microphone_element,
        sensitivity=sensitivity,
        signal_to_noise_ratio=signal_to_noise_ratio
    )
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def update_microphone(
    session: Session, obj: Microphone, update_data: dict[str, Any]
) -> Microphone:
    for field, value in update_data.items():
        setattr(obj, field, value)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def is_microphone_in_use(session: Session, microphone_id: int) -> bool:
    sensor_count = session.exec(
        select(func.count()).select_from(Sensor).where(Sensor.microphone_id == microphone_id)
    ).one()
    return sensor_count > 0


def delete_microphone(session: Session, obj: Microphone) -> None:
    session.delete(obj)
    session.commit()



def get_cameras(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[tuple[Camera, int]], int]:
    filters = filters or {}

    subq = (
        select(CameraLens.camera_id, func.count().label("cnt"))
        .group_by(CameraLens.camera_id)
        .subquery()
    )
    lens_count_col = func.coalesce(subq.c.cnt, 0)
    base_stmt = (
        select(Camera, func.coalesce(subq.c.cnt, 0).label("lens_count"))
        .outerjoin(subq, Camera.camera_id == subq.c.camera_id)
    )
    base_stmt = apply_filters(base_stmt, filters, _CAMERA_FILTER_SPECS)
    if filters.get("lens_count") is not None:
        base_stmt = base_stmt.where(lens_count_col == filters["lens_count"])

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = session.exec(count_stmt).one()

    stmt = base_stmt
    camera_sort_fields = {
        **_CAMERA_SORT_FIELDS,
        "lens_count": lens_count_col,
    }
    stmt = apply_ordering(stmt, order_by, order_dir, camera_sort_fields, Camera.name, Camera.camera_id)
    stmt = apply_pagination(stmt, page, page_size)
    rows = session.exec(stmt).all()
    return list(rows), total


def get_camera_by_id(session: Session, camera_id: int) -> Camera | None:
    return session.get(Camera, camera_id)


def create_camera(session: Session, name: str | None, version: str | None, brand: str | None) -> Camera:
    obj = Camera(name=name, version=version, brand=brand)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def update_camera(
    session: Session, obj: Camera, update_data: dict[str, Any]
) -> Camera:
    for field, value in update_data.items():
        setattr(obj, field, value)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def is_camera_in_use(session: Session, camera_id: int) -> bool:
    sensor_count = session.exec(
        select(func.count()).select_from(Sensor).where(Sensor.camera_id == camera_id)
    ).one()
    return sensor_count > 0


def delete_camera(session: Session, obj: Camera) -> None:
    session.delete(obj)
    session.commit()


def get_camera_lenses(session: Session, camera_id: int) -> list[CameraLens]:
    stmt = (
        select(CameraLens)
        .options(selectinload(CameraLens.lens))
        .where(CameraLens.camera_id == camera_id)
        .order_by(CameraLens.lens_id)
    )
    return list(session.exec(stmt).all())


def get_lens_cameras(session: Session, lens_id: int) -> list[CameraLens]:
    stmt = (
        select(CameraLens)
        .options(selectinload(CameraLens.camera))
        .where(CameraLens.lens_id == lens_id)
        .order_by(CameraLens.camera_id)
    )
    return list(session.exec(stmt).all())


def get_camera_lens(session: Session, camera_id: int, lens_id: int) -> CameraLens | None:
    return session.get(CameraLens, (camera_id, lens_id))


def ensure_camera_lens(
    session: Session,
    camera_id: int,
    lens_id: int,
    is_default: bool | None = None,
) -> CameraLens:
    """Stage a camera-lens association and optionally update its default flag."""
    existing = get_camera_lens(session, camera_id, lens_id)
    if existing:
        if is_default is True:
            _clear_camera_default_lenses(session, camera_id)
            existing.is_default = True
            session.add(existing)
        elif is_default is False:
            existing.is_default = False
            session.add(existing)
        return existing

    if is_default is True:
        _clear_camera_default_lenses(session, camera_id)
    obj = CameraLens(
        camera_id=camera_id,
        lens_id=lens_id,
        is_default=is_default is True,
        notes=None,
    )
    session.add(obj)
    return obj


def _clear_camera_default_lenses(session: Session, camera_id: int) -> None:
    """Clear the current default before assigning a new one for a camera."""
    session.exec(
        select(Camera.camera_id)
        .where(Camera.camera_id == camera_id)
        .with_for_update()
    ).one()
    stmt = select(CameraLens).where(
        CameraLens.camera_id == camera_id,
        CameraLens.is_default.is_(True),
    )
    for association in session.exec(stmt).all():
        association.is_default = False
        session.add(association)


def add_camera_lens(
    session: Session, camera_id: int, lens_id: int,
    is_default: bool | None, notes: str | None
) -> CameraLens:
    obj = ensure_camera_lens(session, camera_id, lens_id, is_default)
    obj.notes = notes
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def remove_camera_lens(session: Session, obj: CameraLens) -> None:
    session.delete(obj)
    session.commit()



def get_lenses(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[tuple[Lens, int]], int]:
    filters = filters or {}
    subq = (
        select(CameraLens.lens_id, func.count().label("cnt"))
        .group_by(CameraLens.lens_id)
        .subquery()
    )
    camera_count_col = func.coalesce(subq.c.cnt, 0)
    base_stmt = (
        select(Lens, camera_count_col.label("camera_count"))
        .outerjoin(subq, Lens.lens_id == subq.c.lens_id)
    )
    base_stmt = apply_filters(base_stmt, filters, _LENS_FILTER_SPECS)
    if filters.get("camera_count") is not None:
        base_stmt = base_stmt.where(camera_count_col == filters["camera_count"])

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = session.exec(count_stmt).one()
    lens_sort_fields = {
        **_LENS_SORT_FIELDS,
        "camera_count": camera_count_col,
    }
    stmt = apply_ordering(
        base_stmt,
        order_by,
        order_dir,
        lens_sort_fields,
        Lens.name,
        Lens.lens_id,
    )
    stmt = apply_pagination(stmt, page, page_size)
    rows = session.exec(stmt).all()
    return list(rows), total


def get_lens_by_id(session: Session, lens_id: int) -> Lens | None:
    return session.get(Lens, lens_id)


def create_lens(
    session: Session,
    name: str | None,
    focal_length: str | None,
    max_aperture: str | None,
    brand: str | None
) -> Lens:
    obj = Lens(name=name, focal_length=focal_length, max_aperture=max_aperture, brand=brand)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def update_lens(
    session: Session, obj: Lens, update_data: dict[str, Any]
) -> Lens:
    for field, value in update_data.items():
        setattr(obj, field, value)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def is_lens_in_use(session: Session, lens_id: int) -> bool:
    sensor_count = session.exec(
        select(func.count()).select_from(Sensor).where(Sensor.lens_id == lens_id)
    ).one()
    return sensor_count > 0


def delete_lens(session: Session, obj: Lens) -> None:
    session.delete(obj)
    session.commit()



def get_sensors(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[tuple], int]:
    """Return sensors with device names joined."""
    filters = filters or {}
    base_stmt = (
        select(
            Sensor,
            Recorder.name.label("recorder_name"),
            Microphone.name.label("microphone_name"),
            Camera.name.label("camera_name"),
            Lens.name.label("lens_name"),
            _SENSOR_IS_DEFAULT.label("is_default"),
        )
        .outerjoin(Recorder, Sensor.recorder_id == Recorder.recorder_id)
        .outerjoin(Microphone, Sensor.microphone_id == Microphone.microphone_id)
        .outerjoin(Camera, Sensor.camera_id == Camera.camera_id)
        .outerjoin(Lens, Sensor.lens_id == Lens.lens_id)
        .outerjoin(
            CameraLens,
            (Sensor.camera_id == CameraLens.camera_id)
            & (Sensor.lens_id == CameraLens.lens_id),
        )
        .outerjoin(
            RecorderMicrophone,
            (Sensor.recorder_id == RecorderMicrophone.recorder_id)
            & (Sensor.microphone_id == RecorderMicrophone.microphone_id),
        )
    )
    base_stmt = apply_filters(base_stmt, filters, _SENSOR_FILTER_SPECS)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total = session.exec(count_stmt).one()

    stmt = base_stmt
    stmt = apply_ordering(stmt, order_by, order_dir, _SENSOR_SORT_FIELDS, Sensor.name, Sensor.sensor_id)
    stmt = apply_pagination(stmt, page, page_size)
    rows = session.exec(stmt).all()
    return list(rows), total


def get_sensor_by_id(session: Session, sensor_id: int) -> tuple | None:
    """Return sensor with device names joined."""
    row = session.exec(
        select(
            Sensor,
            Recorder.name.label("recorder_name"),
            Microphone.name.label("microphone_name"),
            Camera.name.label("camera_name"),
            Lens.name.label("lens_name"),
            _SENSOR_IS_DEFAULT.label("is_default"),
        )
        .outerjoin(Recorder, Sensor.recorder_id == Recorder.recorder_id)
        .outerjoin(Microphone, Sensor.microphone_id == Microphone.microphone_id)
        .outerjoin(Camera, Sensor.camera_id == Camera.camera_id)
        .outerjoin(Lens, Sensor.lens_id == Lens.lens_id)
        .outerjoin(
            CameraLens,
            (Sensor.camera_id == CameraLens.camera_id)
            & (Sensor.lens_id == CameraLens.lens_id),
        )
        .outerjoin(
            RecorderMicrophone,
            (Sensor.recorder_id == RecorderMicrophone.recorder_id)
            & (Sensor.microphone_id == RecorderMicrophone.microphone_id),
        )
        .where(Sensor.sensor_id == sensor_id)
    ).first()
    return row


def create_sensor(
    session: Session,
    name: str,
    sensor_type: str,
    recorder_id: int | None,
    microphone_id: int | None,
    camera_id: int | None,
    lens_id: int | None,
    description: str | None,
) -> Sensor:
    obj = Sensor(
        name=name,
        sensor_type=sensor_type,
        recorder_id=recorder_id,
        microphone_id=microphone_id,
        camera_id=camera_id,
        lens_id=lens_id,
        description=description,
    )
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def update_sensor(session: Session, obj: Sensor, update_dict: dict) -> Sensor:
    """Apply only the fields present in update_dict; None values explicitly clear the column."""
    for key, value in update_dict.items():
        setattr(obj, key, value)
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def is_sensor_in_use(session: Session, sensor_id: int) -> bool:
    count = session.exec(
        select(func.count()).select_from(Media).where(Media.sensor_id == sensor_id)
    ).one()
    return count > 0


def delete_sensor(session: Session, obj: Sensor) -> None:
    session.delete(obj)
    session.commit()
