"""Populate missing audio file metadata without modifying stored audio files."""

from collections import Counter

from sqlmodel import Session, select

from app.core.db import engine
from app.media_paths import resolve_existing_audio_media_path
from app.models import AudioSetting, Media, MediaCollection
from app.services.file_service import file_service


def main() -> None:
    """Extract current file facts; absent source facts are explicitly marked as such."""
    counts: Counter[str] = Counter()
    with Session(engine) as session:
        rows = session.exec(
            select(Media, AudioSetting)
            .join(AudioSetting, AudioSetting.audio_setting_id == Media.audio_setting_id)
            .where(Media.media_type == "audio", Media.is_metadata.is_(False), AudioSetting.file_metadata.is_(None))
        ).all()
        for media, audio_setting in rows:
            link = session.exec(
                select(MediaCollection).where(MediaCollection.media_id == media.media_id).order_by(MediaCollection.collection_id)
            ).first()
            path = resolve_existing_audio_media_path(link.collection_id, media.directory or "", media.filename) if link else None
            if path is None:
                counts["missing"] += 1
                continue
            try:
                stored = file_service._probe_audio(path)
                tags, warnings = file_service._extract_audio_tags(path)
                warnings.append("Source file details are unavailable for this existing recording")
                audio_setting.file_metadata = {
                    "schema_version": 1,
                    "source": {"filename": media.filename, **stored},
                    "stored": {"filename": media.filename, **stored},
                    "tags": tags,
                    "warnings": warnings,
                }
                session.add(audio_setting)
                counts["success"] += 1
                if not tags:
                    counts["no_tags"] += 1
            except Exception:
                counts["parse_failed"] += 1
        session.commit()
    print(" ".join(f"{key}={value}" for key, value in sorted(counts.items())))


if __name__ == "__main__":
    main()
