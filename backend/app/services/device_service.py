from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlmodel import Session, select

from app.csv_export import CsvColumn, export_columns_csv
from app.csv_import import (
    ImportResult,
    ImportRowResult,
    effective_header_width,
    ensure_row_width,
    parse_csv,
    read_cell,
    resolve_header_positions,
)
from app.models.device import (
    Camera,
    CameraLens,
    Lens,
    Microphone,
    Recorder,
    RecorderMicrophone,
    Sensor,
)
from app.models.media import License
from app.repositories import device_repository
from app.schemas.device import (
    CameraCreate,
    CameraLensCreate,
    CameraLensInfo,
    CameraListItem,
    CameraPublic,
    CameraUpdate,
    LensCreate,
    LensListItem,
    LensPublic,
    LensUpdate,
    LicensePublic,
    MicrophoneCreate,
    MicrophoneListItem,
    MicrophonePublic,
    MicrophoneUpdate,
    RecorderCreate,
    RecorderListItem,
    RecorderMicrophoneCreate,
    RecorderMicrophoneInfo,
    RecorderPublic,
    RecorderUpdate,
    SensorPublic,
    SensorUpdate,
)


def _import_rows(
    text: str,
    header_to_field: list[tuple[str, str]],
    factory: Callable[..., Any],
    export_columns: list[CsvColumn] | None = None,
) -> tuple[ImportResult, list[tuple[int, Any]]]:
    # CSV headers use the display labels shown in the settings list and are
    # matched by name, so exported files (whose columns are reordered or carry
    # extra display-only columns) can be re-imported directly.
    field_headers = {field: display for display, field in header_to_field}
    fields = [field for _, field in header_to_field]
    ignored_headers = _export_extra_headers(export_columns, header_to_field)
    report = ImportResult()
    try:
        parsed = parse_csv(text)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        return report.finalize(), []
    if not parsed:
        report.global_errors.append("CSV file is empty")
        return report.finalize(), []
    header, *data_rows = parsed
    try:
        width = effective_header_width(header)
        positions = resolve_header_positions(header, field_headers, fields, ignored_headers)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        report.reject_data_rows(data_rows, str(exc.detail))
        return report.finalize(), []
    rows: list[tuple[int, Any]] = []
    for row_number, row in enumerate(data_rows, start=2):
        if not row or not any(value.strip() for value in row):
            report.rows.append(ImportRowResult(row_number=row_number, status="skipped", reason="Blank row"))
            continue
        try:
            ensure_row_width(row, row_number, width)
        except HTTPException as exc:
            report.rows.append(ImportRowResult(row_number=row_number, status="failed", reason=str(exc.detail)))
            continue
        # Blank cells (e.g. exported NULL numeric values) must become None so
        # optional int fields do not fail parsing on the empty string.
        payload = {field: (read_cell(row, positions, field) or None) for field in fields}
        try:
            rows.append((row_number, factory(**payload)))
            report.rows.append(ImportRowResult(row_number=row_number, status="succeeded"))
        except ValidationError as exc:
            detail = exc.errors()[0]
            report.rows.append(ImportRowResult(row_number=row_number, status="failed", field=str(detail["loc"][-1]), reason=str(detail["msg"])))
    return report.finalize(), rows


def _export_extra_headers(
    export_columns: list[CsvColumn] | None,
    header_to_field: list[tuple[str, str]],
) -> list[str]:
    """Export-only display columns tolerated (ignored) on import."""
    if not export_columns:
        return []
    template = {display for display, _ in header_to_field}
    return [column.header for column in export_columns if column.header not in template]


def _normalized_name(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail="name is required")
    return value.strip()


def _validate_device_names(session: Session, model: type, rows: list[tuple[int, Any]], label: str, report: ImportResult) -> list[Any]:
    # Bulk-load existing records once so exact duplicates can be distinguished
    # from conflicting records that reuse the same unique name.
    existing = {
        item.name.strip().casefold(): item
        for item in session.exec(select(model)).all()
        if isinstance(item.name, str) and item.name.strip()
    }
    seen: dict[str, dict[str, Any]] = {}
    accepted: list[Any] = []
    row_results = {item.row_number: item for item in report.rows}
    for row_number, row in rows:
        result = row_results[row_number]
        try:
            name = _normalized_name(getattr(row, "name", None))
        except HTTPException as exc:
            result.status, result.field, result.reason = "failed", "name", str(exc.detail)
            continue
        row.name = name
        key = name.casefold()
        values = row.model_dump()
        values["name"] = key
        if key in seen:
            if seen[key] == values:
                result.status, result.field, result.reason = "skipped", "name", f"Duplicate {label} name in file"
            else:
                result.status, result.field, result.reason = "failed", "name", f"{label.capitalize()} name conflicts with another row"
            continue
        seen[key] = values
        existing_item = existing.get(key)
        if existing_item is not None:
            exact_duplicate = all(
                (
                    str(getattr(existing_item, field, "")).strip().casefold()
                    if field == "name"
                    else getattr(existing_item, field, None)
                ) == value
                for field, value in values.items()
            )
            if exact_duplicate:
                result.status, result.field, result.reason = "skipped", "name", f"{label.capitalize()} name already exists"
            else:
                result.status, result.field, result.reason = "failed", "name", f"{label.capitalize()} name conflicts with an existing record"
            continue
        accepted.append(row)
    return accepted


def _import_devices(session: Session, text: str, header_to_field: list[tuple[str, str]], factory: Callable[..., Any], export_columns: list[CsvColumn], model: type, label: str, *, dry_run: bool = False) -> ImportResult:
    report, parsed_rows = _import_rows(
        text,
        header_to_field, factory, export_columns,
    )
    if report.global_errors or report.failed:
        if not dry_run:
            report.reject_candidates()
        return report
    rows = _validate_device_names(session, model, parsed_rows, label, report)
    report.finalize()
    if report.failed:
        if not dry_run:
            report.reject_candidates()
        return report
    if dry_run:
        return report.finalize()
    session.add_all([model(**row.model_dump()) for row in rows])
    session.commit()
    report.committed = True
    return report.finalize()


def import_recorders_csv(session: Session, text: str, *, dry_run: bool = False) -> ImportResult:
    return _import_devices(session, text, [("name", "name"), ("version", "version"), ("brand", "brand")], RecorderCreate, _RECORDER_EXPORT_COLUMNS, Recorder, "recorder", dry_run=dry_run)


def import_microphones_csv(session: Session, text: str, *, dry_run: bool = False) -> ImportResult:
    return _import_devices(session, text,
        [
            ("name", "name"),
            ("microphone_element", "microphone_element"),
            ("sensitivity", "sensitivity"),
            ("signal_to_noise_ratio", "signal_to_noise_ratio"),
        ],
        MicrophoneCreate, _MICROPHONE_EXPORT_COLUMNS, Microphone, "microphone", dry_run=dry_run)


def import_cameras_csv(session: Session, text: str, *, dry_run: bool = False) -> ImportResult:
    return _import_devices(session, text, [("name", "name"), ("version", "version"), ("brand", "brand")], CameraCreate, _CAMERA_EXPORT_COLUMNS, Camera, "camera", dry_run=dry_run)


def import_lenses_csv(session: Session, text: str, *, dry_run: bool = False) -> ImportResult:
    return _import_devices(session, text,
        [
            ("name", "name"),
            ("focal_length", "focal_length"),
            ("max_aperture", "max_aperture"),
            ("brand", "brand"),
        ],
        LensCreate, _LENS_EXPORT_COLUMNS, Lens, "lens", dry_run=dry_run)


def list_licenses(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[LicensePublic], int]:
    items, total = device_repository.get_licenses(session, page, page_size, filters, order_by, order_dir)
    return [LicensePublic.model_validate(item, from_attributes=True) for item in items], total


_LICENSE_EXPORT_COLUMNS = [
    CsvColumn("license_id"),
    CsvColumn("name"),
    CsvColumn("link"),
]


def export_licenses_csv(
    session: Session,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> str:
    items, _ = list_licenses(
        session, page=1, page_size=100000, filters=filters, order_by=order_by, order_dir=order_dir
    )
    return export_columns_csv(_LICENSE_EXPORT_COLUMNS, items)


def get_license(session: Session, license_id: int) -> LicensePublic:
    obj = device_repository.get_license_by_id(session, license_id)
    if not obj:
        raise HTTPException(status_code=404, detail="License not found")
    return LicensePublic.model_validate(obj, from_attributes=True)


def create_license(session: Session, name: str, link: str) -> LicensePublic:
    name = _normalized_name(name)
    if device_repository.has_normalized_name(session, License, name):
        raise HTTPException(status_code=409, detail="License name already exists")
    obj = device_repository.create_license(session, name, link)
    return LicensePublic.model_validate(obj, from_attributes=True)


def update_license(session: Session, license_id: int, name: str | None, link: str | None) -> LicensePublic:
    obj = device_repository.get_license_by_id(session, license_id)
    if not obj:
        raise HTTPException(status_code=404, detail="License not found")
    if name is not None:
        name = _normalized_name(name)
        if device_repository.has_normalized_name(session, License, name, license_id):
            raise HTTPException(status_code=409, detail="License name already exists")
    obj = device_repository.update_license(session, obj, name, link)
    return LicensePublic.model_validate(obj, from_attributes=True)


def delete_license(session: Session, license_id: int) -> None:
    obj = device_repository.get_license_by_id(session, license_id)
    if not obj:
        raise HTTPException(status_code=404, detail="License not found")
    if device_repository.is_license_in_use(session, license_id):
        raise HTTPException(status_code=400, detail="Cannot delete license: it is referenced by media records")
    device_repository.delete_license(session, obj)



def _build_recorder_public(recorder: Recorder, recorder_microphones: list[RecorderMicrophone]) -> RecorderPublic:
    mics = [
        RecorderMicrophoneInfo(
            microphone_id=rm.microphone_id,
            name=rm.microphone.name if rm.microphone else None,
            notes=rm.notes,
        )
        for rm in recorder_microphones
    ]
    return RecorderPublic(
        recorder_id=recorder.recorder_id,
        uuid=recorder.uuid,
        name=recorder.name,
        version=recorder.version,
        brand=recorder.brand,
        microphones=mics,
    )


def list_recorders(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[RecorderListItem], int]:
    rows, total = device_repository.get_recorders(session, page, page_size, filters, order_by, order_dir)
    items = [
        RecorderListItem(
            recorder_id=r.recorder_id,
            uuid=r.uuid,
            name=r.name,
            version=r.version,
            brand=r.brand,
            microphone_count=cnt,
        )
        for r, cnt in rows
    ]
    return items, total


_RECORDER_EXPORT_COLUMNS = [
    CsvColumn("recorder_id"), CsvColumn("uuid"),
    CsvColumn("name"), CsvColumn("version"), CsvColumn("brand"),
    CsvColumn("microphone_names"),
]

def export_recorders_csv(
    session: Session,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> str:
    items, _ = list_recorders(
        session, page=1, page_size=100000, filters=filters, order_by=order_by, order_dir=order_dir
    )
    export_rows = []
    for item in items:
        detail = get_recorder(session, item.recorder_id)
        export_rows.append(
            {
                **item.model_dump(mode="json"),
                "microphone_names": _format_linked_microphones(detail.microphones),
            }
        )
    return export_columns_csv(_RECORDER_EXPORT_COLUMNS, export_rows)


def _format_linked_microphones(microphones: list[RecorderMicrophoneInfo]) -> str:
    parts: list[str] = []
    for microphone in microphones:
        label = microphone.name or f"Microphone #{microphone.microphone_id}"
        if microphone.notes:
            label = f"{label} ({microphone.notes})"
        parts.append(label)
    return "; ".join(parts)



def get_recorder(session: Session, recorder_id: int) -> RecorderPublic:
    obj = device_repository.get_recorder_by_id(session, recorder_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Recorder not found")
    rms = device_repository.get_recorder_microphones(session, recorder_id)
    return _build_recorder_public(obj, rms)


def create_recorder(
    session: Session, name: str | None, version: str | None, brand: str | None
) -> None:
    name = _normalized_name(name)
    if device_repository.has_normalized_name(session, Recorder, name):
        raise HTTPException(status_code=409, detail="Recorder name already exists")
    device_repository.create_recorder(session, name, version, brand)


def update_recorder(
    session: Session, recorder_id: int, body: RecorderUpdate
) -> None:
    obj = device_repository.get_recorder_by_id(session, recorder_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Recorder not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = _normalized_name(changes["name"])
        if device_repository.has_normalized_name(session, Recorder, changes["name"], recorder_id):
            raise HTTPException(status_code=409, detail="Recorder name already exists")
    device_repository.update_recorder(session, obj, changes)


def delete_recorder(session: Session, recorder_id: int) -> None:
    obj = device_repository.get_recorder_by_id(session, recorder_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Recorder not found")
    if device_repository.is_recorder_in_use(session, recorder_id):
        raise HTTPException(status_code=400, detail="Cannot delete recorder: it is referenced by sensor records")
    device_repository.delete_recorder(session, obj)


def add_recorder_microphone(
    session: Session, recorder_id: int, data: RecorderMicrophoneCreate
) -> None:
    recorder = device_repository.get_recorder_by_id(session, recorder_id)
    if not recorder:
        raise HTTPException(status_code=404, detail="Recorder not found")
    microphone = device_repository.get_microphone_by_id(session, data.microphone_id)
    if not microphone:
        raise HTTPException(status_code=404, detail="Microphone not found")
    existing = device_repository.get_recorder_microphone(session, recorder_id, data.microphone_id)
    if existing:
        raise HTTPException(status_code=400, detail="This microphone is already associated with the recorder")
    device_repository.add_recorder_microphone(session, recorder_id, data.microphone_id, data.notes)


def remove_recorder_microphone(session: Session, recorder_id: int, microphone_id: int) -> None:
    obj = device_repository.get_recorder_microphone(session, recorder_id, microphone_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Association not found")
    device_repository.remove_recorder_microphone(session, obj)



def list_microphones(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[MicrophoneListItem], int]:
    rows, total = device_repository.get_microphones(session, page, page_size, filters, order_by, order_dir)
    items = [
        MicrophoneListItem(
            microphone_id=microphone.microphone_id,
            uuid=microphone.uuid,
            name=microphone.name,
            microphone_element=microphone.microphone_element,
            sensitivity=microphone.sensitivity,
            signal_to_noise_ratio=microphone.signal_to_noise_ratio,
        )
        for microphone in rows
    ]
    return items, total


_MICROPHONE_EXPORT_COLUMNS = [
    CsvColumn("microphone_id"), CsvColumn("uuid"),
    CsvColumn("name"), CsvColumn("microphone_element"),
    CsvColumn("sensitivity"), CsvColumn("signal_to_noise_ratio"),
]

def export_microphones_csv(
    session: Session,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> str:
    items, _ = list_microphones(
        session, page=1, page_size=100000, filters=filters, order_by=order_by, order_dir=order_dir
    )
    return export_columns_csv(_MICROPHONE_EXPORT_COLUMNS, items)



def get_microphone(session: Session, microphone_id: int) -> MicrophonePublic:
    obj = device_repository.get_microphone_by_id(session, microphone_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Microphone not found")
    return MicrophonePublic(
        microphone_id=obj.microphone_id,
        uuid=obj.uuid,
        name=obj.name,
        microphone_element=obj.microphone_element,
        sensitivity=obj.sensitivity,
        signal_to_noise_ratio=obj.signal_to_noise_ratio,
    )


def create_microphone(
    session: Session, name: str | None, microphone_element: str | None,
    sensitivity: int | None, signal_to_noise_ratio: int | None
) -> None:
    name = _normalized_name(name)
    if device_repository.has_normalized_name(session, Microphone, name):
        raise HTTPException(status_code=409, detail="Microphone name already exists")
    device_repository.create_microphone(
        session, name, microphone_element, sensitivity, signal_to_noise_ratio
    )


def update_microphone(
    session: Session, microphone_id: int, body: MicrophoneUpdate
) -> None:
    obj = device_repository.get_microphone_by_id(session, microphone_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Microphone not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = _normalized_name(changes["name"])
        if device_repository.has_normalized_name(session, Microphone, changes["name"], microphone_id):
            raise HTTPException(status_code=409, detail="Microphone name already exists")
    device_repository.update_microphone(session, obj, changes)


def delete_microphone(session: Session, microphone_id: int) -> None:
    obj = device_repository.get_microphone_by_id(session, microphone_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Microphone not found")
    if device_repository.is_microphone_in_use(session, microphone_id):
        raise HTTPException(status_code=400, detail="Cannot delete microphone: it is referenced by sensor records")
    device_repository.delete_microphone(session, obj)



def _build_camera_public(camera: Camera, camera_lenses: list[CameraLens]) -> CameraPublic:
    lenses = [
        CameraLensInfo(
            lens_id=cl.lens_id,
            name=cl.lens.name if cl.lens else None,
            notes=cl.notes,
        )
        for cl in camera_lenses
    ]
    return CameraPublic(
        camera_id=camera.camera_id,
        uuid=camera.uuid,
        name=camera.name,
        version=camera.version,
        brand=camera.brand,
        lenses=lenses,
    )


def list_cameras(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[CameraListItem], int]:
    rows, total = device_repository.get_cameras(session, page, page_size, filters, order_by, order_dir)
    items = [
        CameraListItem(
            camera_id=c.camera_id,
            uuid=c.uuid,
            name=c.name,
            version=c.version,
            brand=c.brand,
            lens_count=cnt,
        )
        for c, cnt in rows
    ]
    return items, total


_CAMERA_EXPORT_COLUMNS = [
    CsvColumn("camera_id"), CsvColumn("uuid"),
    CsvColumn("name"), CsvColumn("version"), CsvColumn("brand"),
]

def export_cameras_csv(
    session: Session,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> str:
    items, _ = list_cameras(
        session, page=1, page_size=100000, filters=filters, order_by=order_by, order_dir=order_dir
    )
    return export_columns_csv(_CAMERA_EXPORT_COLUMNS, items)


def get_camera(session: Session, camera_id: int) -> CameraPublic:
    obj = device_repository.get_camera_by_id(session, camera_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Camera not found")
    cls = device_repository.get_camera_lenses(session, camera_id)
    return _build_camera_public(obj, cls)


def create_camera(
    session: Session, name: str | None, version: str | None, brand: str | None
) -> None:
    name = _normalized_name(name)
    if device_repository.has_normalized_name(session, Camera, name):
        raise HTTPException(status_code=409, detail="Camera name already exists")
    device_repository.create_camera(session, name, version, brand)


def update_camera(
    session: Session, camera_id: int, body: CameraUpdate
) -> None:
    obj = device_repository.get_camera_by_id(session, camera_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Camera not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = _normalized_name(changes["name"])
        if device_repository.has_normalized_name(session, Camera, changes["name"], camera_id):
            raise HTTPException(status_code=409, detail="Camera name already exists")
    device_repository.update_camera(session, obj, changes)


def delete_camera(session: Session, camera_id: int) -> None:
    obj = device_repository.get_camera_by_id(session, camera_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Camera not found")
    if device_repository.is_camera_in_use(session, camera_id):
        raise HTTPException(status_code=400, detail="Cannot delete camera: it is referenced by sensor records")
    device_repository.delete_camera(session, obj)


def add_camera_lens(session: Session, camera_id: int, data: CameraLensCreate) -> None:
    camera = device_repository.get_camera_by_id(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    lens = device_repository.get_lens_by_id(session, data.lens_id)
    if not lens:
        raise HTTPException(status_code=404, detail="Lens not found")
    existing = device_repository.get_camera_lens(session, camera_id, data.lens_id)
    if existing:
        raise HTTPException(status_code=400, detail="This lens is already associated with the camera")
    device_repository.add_camera_lens(session, camera_id, data.lens_id, data.notes)


def remove_camera_lens(session: Session, camera_id: int, lens_id: int) -> None:
    obj = device_repository.get_camera_lens(session, camera_id, lens_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Association not found")
    device_repository.remove_camera_lens(session, obj)



def list_lenses(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[LensListItem], int]:
    rows, total = device_repository.get_lenses(session, page, page_size, filters, order_by, order_dir)
    items = [
        LensListItem(
            lens_id=lens.lens_id,
            uuid=lens.uuid,
            name=lens.name,
            focal_length=lens.focal_length,
            max_aperture=lens.max_aperture,
            brand=lens.brand,
        )
        for lens in rows
    ]
    return items, total


_LENS_EXPORT_COLUMNS = [
    CsvColumn("lens_id"), CsvColumn("uuid"), CsvColumn("name"),
    CsvColumn("focal_length"), CsvColumn("max_aperture"),
    CsvColumn("brand"),
]

def export_lenses_csv(
    session: Session,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> str:
    items, _ = list_lenses(
        session, page=1, page_size=100000, filters=filters, order_by=order_by, order_dir=order_dir
    )
    return export_columns_csv(_LENS_EXPORT_COLUMNS, items)



def get_lens(session: Session, lens_id: int) -> LensPublic:
    obj = device_repository.get_lens_by_id(session, lens_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Lens not found")
    return LensPublic(
        lens_id=obj.lens_id,
        uuid=obj.uuid,
        name=obj.name,
        focal_length=obj.focal_length,
        max_aperture=obj.max_aperture,
        brand=obj.brand,
    )


def create_lens(
    session: Session, name: str | None, focal_length: str | None,
    max_aperture: str | None, brand: str | None
) -> None:
    name = _normalized_name(name)
    if device_repository.has_normalized_name(session, Lens, name):
        raise HTTPException(status_code=409, detail="Lens name already exists")
    device_repository.create_lens(session, name, focal_length, max_aperture, brand)


def update_lens(
    session: Session, lens_id: int, body: LensUpdate
) -> None:
    obj = device_repository.get_lens_by_id(session, lens_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Lens not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        changes["name"] = _normalized_name(changes["name"])
        if device_repository.has_normalized_name(session, Lens, changes["name"], lens_id):
            raise HTTPException(status_code=409, detail="Lens name already exists")
    device_repository.update_lens(session, obj, changes)


def delete_lens(session: Session, lens_id: int) -> None:
    obj = device_repository.get_lens_by_id(session, lens_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Lens not found")
    if device_repository.is_lens_in_use(session, lens_id):
        raise HTTPException(status_code=400, detail="Cannot delete lens: it is referenced by sensor records")
    device_repository.delete_lens(session, obj)



def _build_sensor_public(row: tuple) -> SensorPublic:
    (
        sensor,
        recorder_name,
        microphone_name,
        camera_name,
        lens_name,
    ) = row
    return SensorPublic(
        sensor_id=sensor.sensor_id,
        uuid=sensor.uuid,
        name=sensor.name,
        sensor_type=sensor.sensor_type,
        recorder_id=sensor.recorder_id,
        recorder_name=recorder_name,
        microphone_id=sensor.microphone_id,
        microphone_name=microphone_name,
        camera_id=sensor.camera_id,
        camera_name=camera_name,
        lens_id=sensor.lens_id,
        lens_name=lens_name,
        description=sensor.description,
        serial_number=sensor.serial_number,
        creation_date=sensor.creation_date,
    )


def list_sensors(
    session: Session,
    page: int,
    page_size: int,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> tuple[list[SensorPublic], int]:
    rows, total = device_repository.get_sensors(session, page, page_size, filters, order_by, order_dir)
    return [_build_sensor_public(row) for row in rows], total


_SENSOR_EXPORT_COLUMNS = [
    CsvColumn("sensor_id"), CsvColumn("uuid"), CsvColumn("name"),
    CsvColumn("serial_number"), CsvColumn("sensor_type"), CsvColumn("recorder_id"),
    CsvColumn("recorder_name"), CsvColumn("microphone_id"),
    CsvColumn("microphone_name"), CsvColumn("camera_id"),
    CsvColumn("camera_name"), CsvColumn("lens_id"),
    CsvColumn("lens_name"), CsvColumn("description"),
    CsvColumn("creation_date"),
]


def export_sensors_csv(
    session: Session,
    filters: dict | None = None,
    order_by: str = "name",
    order_dir: str = "asc",
) -> str:
    items, _ = list_sensors(
        session, page=1, page_size=100000, filters=filters, order_by=order_by, order_dir=order_dir
    )
    return export_columns_csv(_SENSOR_EXPORT_COLUMNS, items)


def get_sensor(session: Session, sensor_id: int) -> SensorPublic:
    row = device_repository.get_sensor_by_id(session, sensor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Sensor not found")
    return _build_sensor_public(row)


def _validate_sensor_device_refs(
    session: Session,
    recorder_id: int | None,
    microphone_id: int | None,
    camera_id: int | None,
    lens_id: int | None,
) -> None:
    if recorder_id and not device_repository.get_recorder_by_id(session, recorder_id):
        raise HTTPException(status_code=404, detail=f"Recorder {recorder_id} not found")
    if microphone_id and not device_repository.get_microphone_by_id(session, microphone_id):
        raise HTTPException(status_code=404, detail=f"Microphone {microphone_id} not found")
    if camera_id and not device_repository.get_camera_by_id(session, camera_id):
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    if lens_id and not device_repository.get_lens_by_id(session, lens_id):
        raise HTTPException(status_code=404, detail=f"Lens {lens_id} not found")


def _validate_sensor_type_constraint(
    sensor_type: str,
    recorder_id: int | None,
    microphone_id: int | None,
    camera_id: int | None,
    lens_id: int | None,
) -> None:
    """Validate audio/photo device combination to match DB check constraint."""
    if sensor_type == "audio":
        if not recorder_id or not microphone_id:
            raise HTTPException(
                status_code=422,
                detail="Audio sensor requires both recorder_id and microphone_id"
            )
        if camera_id or lens_id:
            raise HTTPException(
                status_code=422,
                detail="Audio sensor must not have camera_id or lens_id"
            )
    elif sensor_type == "photo":
        if not camera_id or not lens_id:
            raise HTTPException(
                status_code=422,
                detail="Photo sensor requires both camera_id and lens_id"
            )
        if recorder_id or microphone_id:
            raise HTTPException(
                status_code=422,
                detail="Photo sensor must not have recorder_id or microphone_id"
            )


def create_sensor(
    session: Session,
    name: str,
    sensor_type: str,
    recorder_id: int | None,
    microphone_id: int | None,
    camera_id: int | None,
    lens_id: int | None,
    description: str | None,
    serial_number: str | None = None,
) -> None:
    name = _normalized_name(name)
    if device_repository.has_normalized_name(session, Sensor, name):
        raise HTTPException(status_code=409, detail="Sensor name already exists")
    _validate_sensor_device_refs(session, recorder_id, microphone_id, camera_id, lens_id)
    _validate_sensor_type_constraint(
        sensor_type,
        recorder_id,
        microphone_id,
        camera_id,
        lens_id,
    )
    if sensor_type == "photo" and camera_id is not None and lens_id is not None:
        device_repository.ensure_camera_lens(session, camera_id, lens_id)
    if sensor_type == "audio" and recorder_id is not None and microphone_id is not None:
        device_repository.ensure_recorder_microphone(session, recorder_id, microphone_id)
    device_repository.create_sensor(
        session, name, sensor_type, recorder_id, microphone_id, camera_id, lens_id,
        description, serial_number,
    )


def update_sensor(session: Session, sensor_id: int, body: SensorUpdate) -> None:
    row = device_repository.get_sensor_by_id(session, sensor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Sensor not found")
    sensor = row[0]

    fields = body.model_fields_set
    if "name" in fields:
        body.name = _normalized_name(body.name)
        if device_repository.has_normalized_name(session, Sensor, body.name, sensor_id):
            raise HTTPException(status_code=409, detail="Sensor name already exists")
    # Validate FK existence only for non-null values that were explicitly provided
    _validate_sensor_device_refs(
        session,
        body.recorder_id if ("recorder_id" in fields and body.recorder_id is not None) else None,
        body.microphone_id if ("microphone_id" in fields and body.microphone_id is not None) else None,
        body.camera_id if ("camera_id" in fields and body.camera_id is not None) else None,
        body.lens_id if ("lens_id" in fields and body.lens_id is not None) else None,
    )

    # Effective device combination after applying the update
    effective_type = body.sensor_type if "sensor_type" in fields else sensor.sensor_type
    effective_recorder = body.recorder_id if "recorder_id" in fields else sensor.recorder_id
    effective_mic = body.microphone_id if "microphone_id" in fields else sensor.microphone_id
    effective_camera = body.camera_id if "camera_id" in fields else sensor.camera_id
    effective_lens = body.lens_id if "lens_id" in fields else sensor.lens_id
    _validate_sensor_type_constraint(
        effective_type,
        effective_recorder,
        effective_mic,
        effective_camera,
        effective_lens,
    )

    if effective_type == "photo" and effective_camera is not None and effective_lens is not None:
        device_repository.ensure_camera_lens(session, effective_camera, effective_lens)
    if (
        effective_type == "audio"
        and effective_recorder is not None
        and effective_mic is not None
    ):
        device_repository.ensure_recorder_microphone(session, effective_recorder, effective_mic)

    # Pass only explicitly-set fields so null means "clear" and omitted means "keep"
    device_repository.update_sensor(
        session,
        sensor,
        body.model_dump(include=fields),
    )


def delete_sensor(session: Session, sensor_id: int) -> None:
    row = device_repository.get_sensor_by_id(session, sensor_id)
    if not row:
        raise HTTPException(status_code=404, detail="Sensor not found")
    sensor = row[0]
    if device_repository.is_sensor_in_use(session, sensor_id):
        raise HTTPException(status_code=400, detail="Cannot delete sensor: it is referenced by media records")
    device_repository.delete_sensor(session, sensor)
