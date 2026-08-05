from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PIL import Image
from sqlmodel import Session

from app.media_paths import logical_preview_image_path, media_root
from app.models import Media
from app.models.media import Preview
from app.spectrogram import (
    DETAIL_DEFAULT_FFT_SIZE,
    generate_player_spectrogram,
    generate_thumbnail,
)

PLAYER_SPECTROGRAM_TYPE = "spectrogram"


@dataclass
class PreviewGenerationResult:
    created_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return len(self.created_paths)


def generate_photo_thumbnail(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        image.seek(0)
        image.thumbnail((640, 640))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.save(target, format="PNG", optimize=True)


def _available_preview_path(target: Path, media: Media) -> Path:
    if not target.exists():
        return target
    return target.with_name(f"{target.stem}__{media.uuid}{target.suffix}")


def _promote_part(part: Path, target: Path) -> None:
    try:
        os.link(part, target)
    finally:
        part.unlink(missing_ok=True)


def _write_preview_bytes(
    target: Path,
    payload: bytes,
    media: Media,
    *,
    atomic: bool,
) -> Path:
    if not atomic:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return target
    target = _available_preview_path(target, media)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.{uuid4().hex}.part")
    part.write_bytes(payload)
    _promote_part(part, target)
    return target


def _write_photo_preview(
    source: Path,
    target: Path,
    media: Media,
    generator: Callable[[Path, Path], None],
    *,
    atomic: bool,
) -> Path:
    if not atomic:
        target.parent.mkdir(parents=True, exist_ok=True)
        generator(source, target)
        return target
    target = _available_preview_path(target, media)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.{uuid4().hex}.part")
    try:
        generator(source, part)
        _promote_part(part, target)
    finally:
        part.unlink(missing_ok=True)
    return target


def generate_media_previews(
    session: Session,
    *,
    media: Media,
    collection_id: int,
    source_path: Path,
    thumbnail_generator: Callable[..., bytes] = generate_thumbnail,
    player_generator: Callable[..., bytes] = generate_player_spectrogram,
    photo_generator: Callable[[Path, Path], None] = generate_photo_thumbnail,
    atomic: bool = True,
) -> PreviewGenerationResult:
    result = PreviewGenerationResult()
    directory = media.directory or ""
    storage_filename = media.filename or source_path.name

    if media.media_type == "audio":
        channel_num = media.audio_setting.channel_num if media.audio_setting else 1
        sampling_rate = media.audio_setting.sampling_rate_hz if media.audio_setting else 44100
        try:
            thumbnail = thumbnail_generator(
                audio_path=str(source_path),
                channel_num=channel_num or 1,
                sampling_rate=sampling_rate,
            )
            target = source_path.parent / f"{Path(storage_filename).stem}_thumbnail.png"
            created = _write_preview_bytes(target, thumbnail, media, atomic=atomic)
            result.created_paths.append(created)
            session.add(Preview(media_id=media.media_id, filename=created.name, type="thumbnail"))
        except Exception as exc:
            result.warnings.append(f"Audio thumbnail generation failed: {exc}")

        try:
            player = player_generator(
                str(source_path),
                channel_num=channel_num or 1,
                fft_size=DETAIL_DEFAULT_FFT_SIZE,
            )
            target = media_root() / logical_preview_image_path(
                collection_id,
                directory,
                f"{Path(storage_filename).stem}_player_s.png",
            )
            created = _write_preview_bytes(target, player, media, atomic=atomic)
            result.created_paths.append(created)
            session.add(
                Preview(
                    media_id=media.media_id,
                    filename=created.name,
                    type=PLAYER_SPECTROGRAM_TYPE,
                )
            )
        except Exception as exc:
            result.warnings.append(f"Audio player spectrogram generation failed: {exc}")
    elif media.media_type == "photo":
        try:
            target = media_root() / logical_preview_image_path(
                collection_id,
                directory,
                f"{Path(storage_filename).stem}_thumbnail.png",
            )
            created = _write_photo_preview(
                source_path,
                target,
                media,
                photo_generator,
                atomic=atomic,
            )
            result.created_paths.append(created)
            session.add(Preview(media_id=media.media_id, filename=created.name, type="thumbnail"))
        except Exception as exc:
            result.warnings.append(f"Photo thumbnail generation failed: {exc}")
    return result
