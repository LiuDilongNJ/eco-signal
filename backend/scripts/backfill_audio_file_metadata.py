"""Populate missing audio file metadata without modifying stored audio files."""

import argparse
import multiprocessing as mp
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Ensure backend root is in sys.path for app module imports
backend_dir = str(Path(__file__).resolve().parents[1])
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlmodel import Session, select

from app.audio_metadata import (
    build_audio_file_metadata,
    extract_audio_tags,
    optimal_worker_count,
    probe_audio,
)
from app.core.db import engine
from app.media_paths import resolve_existing_audio_media_path
from app.models import AudioSetting, Media, MediaCollection


def _probe_and_extract_tags(path_str: str, filename: str) -> tuple[dict[str, Any] | None, list[str]]:
    path = Path(path_str)
    try:
        stored = probe_audio(path)
        tags, warnings = extract_audio_tags(path)
        warnings.append("Source file details are unavailable for this existing recording")
        file_metadata = build_audio_file_metadata(
            source_filename=filename,
            target_filename=filename,
            source_probe=stored,
            stored_probe=stored,
            tags=tags,
            warnings=warnings,
        )
        return file_metadata, warnings
    except Exception:
        return None, []


def backfill_metadata(batch_size: int = 500) -> Counter[str]:
    """Extract current file facts in parallel batches."""
    counts: Counter[str] = Counter()
    worker_count = optimal_worker_count()

    with Session(engine) as session:
        # Fetch targets: (media_id, audio_setting_id, directory, filename, collection_id)
        stmt = (
            select(
                Media.media_id,
                Media.audio_setting_id,
                Media.directory,
                Media.filename,
                MediaCollection.collection_id,
            )
            .join(AudioSetting, AudioSetting.audio_setting_id == Media.audio_setting_id)
            .join(MediaCollection, MediaCollection.media_id == Media.media_id, isouter=True)
            .where(
                Media.media_type == "audio",
                Media.is_metadata.is_(False),
                AudioSetting.file_metadata.is_(None),
            )
        )
        rows = session.exec(stmt).all()
        if not rows:
            return counts

        # Resolve paths
        items_to_process: list[tuple[int, str, str]] = []  # (audio_setting_id, path_str, filename)
        for _, audio_setting_id, directory, filename, collection_id in rows:
            if not filename or not audio_setting_id:
                continue
            path = resolve_existing_audio_media_path(collection_id or "", directory or "", filename)
            if path is None or not path.exists():
                counts["missing"] += 1
                continue
            items_to_process.append((audio_setting_id, str(path), filename))

        if not items_to_process:
            return counts

        # Process worker tasks
        pending_updates: list[tuple[int, dict[str, Any]]] = []

        def _apply_result(setting_id: int, file_meta: dict[str, Any] | None) -> None:
            if file_meta is not None:
                pending_updates.append((setting_id, file_meta))
                counts["success"] += 1
                if not file_meta.get("tags"):
                    counts["no_tags"] += 1
            else:
                counts["parse_failed"] += 1

        def _flush_batch() -> None:
            if not pending_updates:
                return
            for s_id, meta in pending_updates:
                setting = session.get(AudioSetting, s_id)
                if setting:
                    setting.file_metadata = meta
                    session.add(setting)
            session.commit()
            pending_updates.clear()

        if worker_count <= 1:
            for s_id, p_str, fname in items_to_process:
                meta, _ = _probe_and_extract_tags(p_str, fname)
                _apply_result(s_id, meta)
                if len(pending_updates) >= batch_size:
                    _flush_batch()
        else:
            tasks = [(p_str, fname) for _, p_str, fname in items_to_process]
            with mp.Pool(processes=worker_count) as pool:
                for idx, (meta, _) in enumerate(pool.starmap(_probe_and_extract_tags, tasks, chunksize=32)):
                    s_id = items_to_process[idx][0]
                    _apply_result(s_id, meta)
                    if len(pending_updates) >= batch_size:
                        _flush_batch()

        _flush_batch()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill audio file metadata")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size for commits")
    args = parser.parse_args()

    counts = backfill_metadata(batch_size=args.batch_size)
    print(" ".join(f"{key}={value}" for key, value in sorted(counts.items())))


if __name__ == "__main__":
    main()
