from __future__ import annotations

import json
from collections.abc import Callable, Hashable
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Field, Session, SQLModel, select

from app.csv_import import (
    ImportResult,
    ImportRowResult,
    effective_header_width,
    ensure_row_width,
    parse_csv,
    read_cell,
    resolve_header_positions,
)
from app.models import Annotation, Media, MediaCollection, Project, ProjectCollection, User
from app.schemas.annotation import AnnotationCreate
from app.schemas.collection import CollectionCreate
from app.schemas.index_log import IndexLogCreateRequest
from app.schemas.project import ProjectCreate
from app.schemas.review import ReviewCreate
from app.schemas.site import SiteCreate
from app.schemas.user import UserCreate
from app.services import (
    analysis_service,
    annotation_service,
    collection_service,
    project_service,
    review_service,
    site_service,
    task_service,
    user_service,
)


class TaskImportRow(SQLModel):
    media_id: int = Field(gt=0)
    type: Literal["media", "annotation"]
    annotation_id: int | None = Field(default=None, gt=0)
    assignee_id: int = Field(gt=0)
    comment: str | None = Field(default=None, max_length=1000)


def _require_media_scope(
    session: Session,
    media_id: int,
    project_id: int,
    collection_id: int,
) -> None:
    scoped_media_id = session.exec(
        select(MediaCollection.media_id)
        .join(
            ProjectCollection,
            ProjectCollection.collection_id == MediaCollection.collection_id,
        )
        .where(
            MediaCollection.media_id == media_id,
            MediaCollection.collection_id == collection_id,
            ProjectCollection.project_id == project_id,
        )
    ).first()
    if scoped_media_id is None:
        raise HTTPException(
            status_code=422,
            detail="Media does not belong to the selected project and collection",
        )


def _annotation_media_id(session: Session, annotation_id: int) -> int:
    media_id = session.exec(
        select(Annotation.media_id).where(Annotation.annotation_id == annotation_id)
    ).first()
    if media_id is None:
        raise HTTPException(status_code=422, detail="Annotation not found")
    return media_id


def _require_annotation_media_type(
    session: Session,
    media_id: int,
    expected_media_type: Literal["audio", "photo"] | None,
) -> None:
    if expected_media_type is None:
        return
    media = session.get(Media, media_id)
    if media is None or media.media_type != expected_media_type:
        actual = media.media_type if media is not None else "unknown"
        raise HTTPException(
            status_code=422,
            detail=(
                f"Media {media_id} is {actual}, but this import requires "
                f"{expected_media_type} media"
            ),
        )


def _parse_json_cell(value: str | None, field: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must contain a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must contain a JSON object")
    return parsed


def _parse_models(
    text: str,
    schema: type[SQLModel],
    *,
    injected: dict[str, Any] | None = None,
    converters: dict[str, Callable[[str | None], Any]] | None = None,
) -> tuple[ImportResult, list[tuple[int, SQLModel]]]:
    injected = injected or {}
    converters = converters or {}
    report = ImportResult()
    try:
        parsed = parse_csv(text)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        return report.finalize(), []
    if not parsed:
        report.global_errors.append("Import file contains no records")
        return report.finalize(), []

    fields = {
        name: field
        for name, field in schema.model_fields.items()
        if name not in injected
    }
    field_headers = {name: name for name in fields}
    required = [
        name
        for name, field in fields.items()
        if field.is_required()
    ]
    header, *data_rows = parsed
    try:
        width = effective_header_width(header)
        positions = resolve_header_positions(header, field_headers, required)
    except HTTPException as exc:
        report.global_errors.append(str(exc.detail))
        report.reject_data_rows(data_rows, str(exc.detail))
        return report.finalize(), []

    valid: list[tuple[int, SQLModel]] = []
    for row_number, row in enumerate(data_rows, start=2):
        if not row or not any(value.strip() for value in row):
            report.rows.append(ImportRowResult(row_number=row_number, status="skipped", reason="Blank row"))
            continue
        try:
            ensure_row_width(row, row_number, width)
            payload: dict[str, Any] = {
                name: (read_cell(row, positions, name) or None)
                for name in fields
                if name in positions
            }
            for name, converter in converters.items():
                if name in payload:
                    payload[name] = converter(payload[name])
            payload.update(injected)
            item = schema.model_validate(payload)
        except HTTPException as exc:
            report.rows.append(ImportRowResult(row_number=row_number, status="failed", reason=str(exc.detail)))
        except (ValidationError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                error = exc.errors()[0]
                field = str(error["loc"][-1])
                reason = str(error["msg"])
            else:
                field = None
                reason = str(exc)
            report.rows.append(ImportRowResult(row_number=row_number, status="failed", field=field, reason=reason))
        else:
            valid.append((row_number, item))
            report.rows.append(ImportRowResult(row_number=row_number, status="succeeded"))
    return report.finalize(), valid


def _execute(
    session: Session,
    report: ImportResult,
    rows: list[tuple[int, SQLModel]],
    writer: Callable[[SQLModel], None],
    *,
    dry_run: bool,
    key: Callable[[SQLModel], Hashable] | None = None,
    preflight: Callable[[SQLModel], None] | None = None,
) -> ImportResult:
    results = {row.row_number: row for row in report.rows}
    if report.global_errors or report.failed:
        if not dry_run:
            report.reject_candidates()
        return report

    accepted: list[tuple[int, SQLModel]] = []
    seen: set[Hashable] = set()
    for row_number, item in rows:
        if key is not None:
            item_key = key(item)
            if item_key in seen:
                result = results[row_number]
                result.status = "skipped"
                result.reason = "Duplicate record in file"
                continue
            seen.add(item_key)

        try:
            if preflight is not None:
                preflight(item)
        except HTTPException as exc:
            result = results[row_number]
            if exc.status_code == 409 or "already exists" in str(exc.detail).lower():
                result.status = "skipped"
            else:
                result.status = "failed"
            result.reason = str(exc.detail)
        except ValueError as exc:
            result = results[row_number]
            result.status = "failed"
            result.reason = str(exc)
        else:
            accepted.append((row_number, item))

    report.finalize()
    if report.failed:
        if not dry_run:
            report.reject_candidates()
        return report
    if dry_run:
        return report.finalize()

    def fail_write(row_number: int, reason: str) -> ImportResult:
        results[row_number].status = "failed"
        results[row_number].reason = reason
        session.rollback()
        report.reject_candidates()
        return report.finalize()

    try:
        for row_number, item in accepted:
            if results[row_number].status != "succeeded":
                continue
            try:
                writer(item)
            except HTTPException as exc:
                return fail_write(row_number, str(exc.detail))
            except IntegrityError:
                return fail_write(row_number, "Record violates a data constraint")
            except ValueError as exc:
                return fail_write(row_number, str(exc))
        session.commit()
    except Exception:
        session.rollback()
        report.global_errors.append("No data was written because the import transaction failed")
        report.reject_candidates()
        return report
    report.committed = True
    return report.finalize()


def import_projects(session: Session, text: str, user: User, *, dry_run: bool) -> ImportResult:
    report, rows = _parse_models(text, ProjectCreate)
    existing = {
        project.name.strip().casefold(): project
        for project in session.exec(select(Project)).all()
        if project.name.strip()
    }
    results = {row.row_number: row for row in report.rows}
    pending: list[tuple[int, SQLModel]] = []
    for row_number, item in rows:
        key = str(item.name).strip().casefold()
        project = existing.get(key)
        if project is None:
            pending.append((row_number, item))
            continue
        values = item.model_dump()
        exact_duplicate = all(
            (
                str(getattr(project, field, "")).strip().casefold()
                if field == "name"
                else getattr(project, field, None)
            )
            == (key if field == "name" else value)
            for field, value in values.items()
        )
        result = results[row_number]
        result.field = "name"
        if exact_duplicate:
            result.status = "skipped"
            result.reason = "Project already exists"
        else:
            result.status = "failed"
            result.reason = "Project name conflicts with an existing record"
    report.finalize()
    return _execute(
        session,
        report,
        pending,
        lambda item: project_service.create_project(session, item, user, commit=False),
        dry_run=dry_run,
        key=lambda item: str(item.name).strip().casefold(),
        preflight=lambda item: project_service.validate_project_create(session, item),
    )


def import_collections(
    session: Session,
    text: str,
    user: User,
    project_id: int,
    *,
    dry_run: bool,
) -> ImportResult:
    report, rows = _parse_models(text, CollectionCreate)
    return _execute(
        session,
        report,
        rows,
        lambda item: collection_service.create_collection(
            session, item, user, project_id, commit=False
        ),
        dry_run=dry_run,
        key=lambda item: str(item.name).strip().casefold(),
        preflight=lambda item: collection_service.validate_collection_create(session, item, project_id),
    )


def import_sites(
    session: Session,
    text: str,
    user: User,
    project_id: int,
    collection_id: int,
    *,
    dry_run: bool,
) -> ImportResult:
    report, rows = _parse_models(
        text,
        SiteCreate,
        injected={"project_id": project_id, "collection_id": collection_id},
    )
    return _execute(
        session,
        report,
        rows,
        lambda item: site_service.create_site(session, item, user, commit=False),
        dry_run=dry_run,
        key=lambda item: str(item.name).strip().casefold(),
        preflight=lambda item: site_service.validate_site_create(session, item, user),
    )


def import_annotations(
    session: Session,
    text: str,
    user: User,
    project_id: int,
    collection_id: int,
    *,
    dry_run: bool,
    expected_media_type: Literal["audio", "photo"] | None = None,
) -> ImportResult:
    report, rows = _parse_models(text, AnnotationCreate, injected={"project_id": project_id})
    return _execute(
        session,
        report,
        rows,
        lambda item: (
            _require_media_scope(
                session, item.media_id, project_id, collection_id
            ),
            _require_annotation_media_type(session, item.media_id, expected_media_type),
            annotation_service.create_annotation(session, user, item, commit=False),
        ),
        dry_run=dry_run,
        key=lambda item: (
            item.media_id,
            item.min_x,
            item.max_x,
            item.min_y,
            item.max_y,
            item.taxon_id,
            item.sound_id,
        ),
        preflight=lambda item: (
            _require_media_scope(session, item.media_id, project_id, collection_id),
            _require_annotation_media_type(session, item.media_id, expected_media_type),
            annotation_service.validate_annotation_create(session, user, item),
        ),
    )


def import_reviews(
    session: Session,
    text: str,
    user: User,
    project_id: int,
    collection_id: int,
    *,
    dry_run: bool,
) -> ImportResult:
    report, rows = _parse_models(text, ReviewCreate, injected={"project_id": project_id})
    return _execute(
        session,
        report,
        rows,
        lambda item: (
            _require_media_scope(
                session,
                _annotation_media_id(session, item.annotation_id),
                project_id,
                collection_id,
            ),
            review_service.create_review(session, user, item, commit=False),
        ),
        dry_run=dry_run,
        key=lambda item: item.annotation_id,
        preflight=lambda item: (
            _require_media_scope(session, _annotation_media_id(session, item.annotation_id), project_id, collection_id),
            review_service.validate_review_create(session, user, item),
        ),
    )


def import_index_logs(
    session: Session,
    text: str,
    user: User,
    project_id: int,
    collection_id: int,
    *,
    dry_run: bool,
) -> ImportResult:
    report, rows = _parse_models(
        text,
        IndexLogCreateRequest,
        injected={"project_id": project_id},
        converters={
            "params": lambda value: _parse_json_cell(value, "params"),
            "results": lambda value: _parse_json_cell(value, "results"),
        },
    )
    return _execute(
        session,
        report,
        rows,
        lambda item: (
            _require_media_scope(
                session, item.media_id, project_id, collection_id
            ),
            analysis_service.analysis_service.save_acoustic_index_preview(
                session, item, user, commit=False
            ),
        ),
        dry_run=dry_run,
        key=lambda item: (item.media_id, item.index_id, item.version, json.dumps(item.results, sort_keys=True)),
        preflight=lambda item: (
            _require_media_scope(
                session, item.media_id, project_id, collection_id
            ),
            analysis_service.analysis_service.validate_acoustic_index_preview(
                session, item, user
            ),
        ),
    )


def import_tasks(
    session: Session,
    text: str,
    user: User,
    project_id: int,
    collection_id: int,
    *,
    dry_run: bool,
) -> ImportResult:
    report, rows = _parse_models(text, TaskImportRow)

    def write(item: SQLModel) -> None:
        task = TaskImportRow.model_validate(item)
        _require_media_scope(session, task.media_id, project_id, collection_id)
        task_service.assign_tasks(
            session,
            task.media_id,
            user,
            task.type,
            [{"user_id": task.assignee_id, "comment": task.comment}],
            [task.annotation_id] if task.annotation_id is not None else None,
            project_id=project_id,
            commit=False,
        )

    return _execute(
        session,
        report,
        rows,
        write,
        dry_run=dry_run,
        key=lambda item: (item.type, item.media_id, item.annotation_id, item.assignee_id),
        preflight=lambda item: (
            _require_media_scope(session, item.media_id, project_id, collection_id),
            task_service.validate_task_assignments(
                session, item.media_id, user, item.type,
                [{"user_id": item.assignee_id, "comment": item.comment}],
                [item.annotation_id] if item.annotation_id is not None else None,
            ),
        ),
    )


def import_users(
    session: Session,
    text: str,
    user: User,
    project_id: int,
    collection_id: int | None,
    *,
    dry_run: bool,
) -> ImportResult:
    report, rows = _parse_models(text, UserCreate)

    usernames: set[str] = set()
    emails: set[str] = set()
    results = {row.row_number: row for row in report.rows}
    filtered: list[tuple[int, SQLModel]] = []
    for row_number, item in rows:
        username = str(item.username).casefold()
        email = str(item.email).casefold()
        if username in usernames or email in emails:
            results[row_number].status = "skipped"
            results[row_number].reason = "Duplicate username or email in file"
            continue
        usernames.add(username)
        emails.add(email)
        filtered.append((row_number, item))
    report.finalize()

    return _execute(
        session,
        report,
        filtered,
        lambda item: user_service.create_user(
            session,
            user,
            item,
            project_id,
            collection_id,
            commit=False,
        ),
        dry_run=dry_run,
        preflight=lambda item: user_service.validate_user_create(
            session, user, item, project_id, collection_id
        ),
    )
