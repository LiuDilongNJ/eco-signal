#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

try:
    import psycopg
except ImportError:
    psycopg = None  # type: ignore[assignment]

# Ensure backend root is in sys.path for app module imports
backend_dir = str(Path(__file__).resolve().parents[1])
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.audio_metadata import (
    build_audio_file_metadata,
    compute_file_md5,
    extract_audio_tags,
    missing_audio_tag_names,
    optimal_worker_count,
    probe_audio,
    transcode_to_flac,
)

# Compatibility aliases
_probe_audio = probe_audio
_extract_audio_tags = extract_audio_tags


def format_size(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def format_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


def scan_tree(source: Path) -> tuple[list[Path], list[Path], list[Path], int]:
    directories: list[Path] = []
    files: list[Path] = []
    links: list[Path] = []
    total_bytes = 0

    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            links.append(path)
        elif path.is_dir():
            directories.append(path)
        elif path.is_file():
            files.append(path)
            total_bytes += path.stat().st_size
        else:
            raise ValueError(f"Unsupported source entry: {path}")
    return directories, files, links, total_bytes


@dataclass
class AudioTask:
    source_path: str
    target_path: str
    relative_path: str
    source_filename: str
    target_filename: str
    convert_wav: bool
    extract_metadata: bool
    media_id: int | None = None
    audio_setting_id: int | None = None
    source_size: int = 0
    skip_transcode: bool = False


@dataclass
class AudioResult:
    source_path: str
    target_path: str
    relative_path: str
    target_filename: str
    status: str  # "converted", "copied", "skipped", "failed"
    source_bytes: int
    target_bytes: int
    media_id: int | None = None
    audio_setting_id: int | None = None
    md5_hash: str | None = None
    file_metadata: dict[str, Any] | None = None
    probed: dict[str, Any] | None = None
    error: str | None = None


def _process_audio_worker(task: AudioTask) -> AudioResult:
    src = Path(task.source_path)
    dst = Path(task.target_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if task.skip_transcode:
        # File is already converted at destination; probe destination for metadata update
        try:
            stored_probe = probe_audio(dst) if task.extract_metadata else {}
            stored_tags, warnings = extract_audio_tags(dst) if task.extract_metadata else ({}, [])
            md5_val = compute_file_md5(dst)
            target_size = dst.stat().st_size
            file_meta = None
            if task.extract_metadata:
                file_meta = build_audio_file_metadata(
                    source_filename=task.source_filename,
                    target_filename=task.target_filename,
                    source_probe=stored_probe,
                    stored_probe=stored_probe,
                    tags=stored_tags,
                    warnings=warnings,
                )
            return AudioResult(
                source_path=task.source_path,
                target_path=task.target_path,
                relative_path=task.relative_path,
                target_filename=task.target_filename,
                status="skipped",
                source_bytes=task.source_size,
                target_bytes=target_size,
                media_id=task.media_id,
                audio_setting_id=task.audio_setting_id,
                md5_hash=md5_val,
                file_metadata=file_meta,
                probed=stored_probe,
            )
        except Exception as exc:
            return AudioResult(
                source_path=task.source_path,
                target_path=task.target_path,
                relative_path=task.relative_path,
                target_filename=task.target_filename,
                status="failed",
                source_bytes=task.source_size,
                target_bytes=0,
                media_id=task.media_id,
                audio_setting_id=task.audio_setting_id,
                error=f"Metadata probe on existing target failed: {exc}",
            )

    is_wav = src.suffix.lower() == ".wav"
    should_convert = is_wav and task.convert_wav

    if should_convert:
        temp_target = dst.with_name(f".{dst.name}.tmp.{os.getpid()}_{time.time_ns()}.flac")
        try:
            source_probe = probe_audio(src) if task.extract_metadata else {}
            source_tags, warnings = extract_audio_tags(src) if task.extract_metadata else ({}, [])

            transcode_to_flac(src, temp_target)

            stored_probe = probe_audio(temp_target) if task.extract_metadata else {}
            target_size = temp_target.stat().st_size
            md5_val = compute_file_md5(temp_target)

            if task.extract_metadata and source_tags:
                stored_tags, _ = extract_audio_tags(temp_target)
                missing = missing_audio_tag_names(source_tags, stored_tags)
                if missing:
                    warnings.append("Embedded metadata was not retained for: " + ", ".join(missing))

            temp_target.replace(dst)
            if task.target_filename != task.source_filename:
                old_src_in_dst = dst.with_name(task.source_filename)
                if old_src_in_dst.exists() and old_src_in_dst.resolve() != src.resolve():
                    old_src_in_dst.unlink(missing_ok=True)
            try:
                shutil.copystat(src, dst)
            except OSError:
                pass

            file_meta = None
            if task.extract_metadata:
                file_meta = build_audio_file_metadata(
                    source_filename=task.source_filename,
                    target_filename=task.target_filename,
                    source_probe=source_probe,
                    stored_probe={**stored_probe, "container": "flac"},
                    tags=source_tags,
                    warnings=warnings,
                )

            return AudioResult(
                source_path=task.source_path,
                target_path=task.target_path,
                relative_path=task.relative_path,
                target_filename=task.target_filename,
                status="converted",
                source_bytes=task.source_size,
                target_bytes=target_size,
                media_id=task.media_id,
                audio_setting_id=task.audio_setting_id,
                md5_hash=md5_val,
                file_metadata=file_meta,
                probed=stored_probe,
            )
        except Exception as exc:
            temp_target.unlink(missing_ok=True)
            # Fallback: copy source file as-is so data is not lost
            fallback_dst = dst.with_name(task.source_filename)
            try:
                shutil.copy2(src, fallback_dst)
            except Exception:
                pass
            return AudioResult(
                source_path=task.source_path,
                target_path=str(fallback_dst),
                relative_path=task.relative_path,
                target_filename=task.source_filename,
                status="failed",
                source_bytes=task.source_size,
                target_bytes=fallback_dst.stat().st_size if fallback_dst.exists() else 0,
                media_id=task.media_id,
                audio_setting_id=task.audio_setting_id,
                error=f"Transcoding failed: {exc}",
            )
    else:
        # Direct stream copy for non-WAV audio or when conversion is not requested
        temp_target = dst.with_name(f".{dst.name}.tmp.{os.getpid()}_{time.time_ns()}")
        try:
            source_probe = probe_audio(src) if task.extract_metadata else {}
            source_tags, warnings = extract_audio_tags(src) if task.extract_metadata else ({}, [])

            hasher = hashlib.md5()
            total_read = 0
            with src.open("rb") as s_in, temp_target.open("wb") as d_out:
                while chunk := s_in.read(1024 * 1024):
                    hasher.update(chunk)
                    d_out.write(chunk)
                    total_read += len(chunk)

            temp_target.replace(dst)
            try:
                shutil.copystat(src, dst)
            except OSError:
                pass

            file_meta = None
            if task.extract_metadata and source_probe:
                file_meta = build_audio_file_metadata(
                    source_filename=task.source_filename,
                    target_filename=task.target_filename,
                    source_probe=source_probe,
                    stored_probe=source_probe,
                    tags=source_tags,
                    warnings=warnings,
                )

            return AudioResult(
                source_path=task.source_path,
                target_path=task.target_path,
                relative_path=task.relative_path,
                target_filename=task.target_filename,
                status="copied",
                source_bytes=task.source_size,
                target_bytes=total_read,
                media_id=task.media_id,
                audio_setting_id=task.audio_setting_id,
                md5_hash=hasher.hexdigest(),
                file_metadata=file_meta,
                probed=source_probe,
            )
        except Exception as exc:
            temp_target.unlink(missing_ok=True)
            return AudioResult(
                source_path=task.source_path,
                target_path=task.target_path,
                relative_path=task.relative_path,
                target_filename=task.target_filename,
                status="failed",
                source_bytes=task.source_size,
                target_bytes=0,
                media_id=task.media_id,
                audio_setting_id=task.audio_setting_id,
                error=f"Copy/probe failed: {exc}",
            )


class DatabaseSync:
    def __init__(self, db_params: dict[str, Any], batch_size: int = 500) -> None:
        self.db_params = db_params
        self.batch_size = batch_size
        self.conn = None
        self.media_updates: list[tuple[str, int, str | None, int]] = []
        self.setting_updates: list[tuple[str, int | None, int | None, int | None, float | None, int]] = []
        self.total_media_synced = 0
        self.total_settings_synced = 0

    def connect(self) -> bool:
        if psycopg is None:
            return False
        try:
            self.conn = psycopg.connect(
                host=self.db_params.get("host", "localhost"),
                port=int(self.db_params.get("port", 5432)),
                user=self.db_params.get("user", "postgres"),
                password=self.db_params.get("password", ""),
                dbname=self.db_params.get("dbname", "ecosignal"),
            )
            return True
        except Exception as exc:
            print(f"Warning: Database connection failed: {exc}", file=sys.stderr)
            self.conn = None
            return False

    def add(self, result: AudioResult) -> None:
        if not self.conn:
            return
        if result.media_id:
            self.media_updates.append((
                result.target_filename,
                result.target_bytes,
                result.md5_hash,
                result.media_id,
            ))
        if result.audio_setting_id and result.file_metadata:
            probed = result.probed or {}
            self.setting_updates.append((
                json.dumps(result.file_metadata),
                probed.get("sampling_rate_hz"),
                probed.get("bit_depth"),
                probed.get("channel_num"),
                probed.get("duration_s"),
                result.audio_setting_id,
            ))
        if len(self.media_updates) >= self.batch_size or len(self.setting_updates) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.conn:
            return
        with self.conn.cursor() as cur:
            if self.media_updates:
                cur.executemany(
                    """
                    UPDATE media
                    SET filename = %s, size_b = %s, md5_hash = %s
                    WHERE media_id = %s
                    """,
                    self.media_updates,
                )
                self.total_media_synced += len(self.media_updates)
                self.media_updates.clear()
            if self.setting_updates:
                cur.executemany(
                    """
                    UPDATE audio_setting
                    SET file_metadata = %s::json,
                        sampling_rate_hz = COALESCE(NULLIF(%s, 0), sampling_rate_hz),
                        bit_depth = COALESCE(%s, bit_depth),
                        channel_num = COALESCE(%s, channel_num),
                        duration_s = COALESCE(NULLIF(%s, 0), duration_s)
                    WHERE audio_setting_id = %s
                    """,
                    self.setting_updates,
                )
                self.total_settings_synced += len(self.setting_updates)
                self.setting_updates.clear()
        self.conn.commit()

    def close(self) -> None:
        if self.conn:
            try:
                self.flush()
                self.conn.close()
            except Exception:
                pass
            self.conn = None


class AuditLogger:
    def __init__(self, audit_path: Path | None) -> None:
        self.audit_path = audit_path
        self.handle = None
        self.writer = None
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.audit_path.open("w", newline="", encoding="utf-8")
            self.writer = csv.writer(self.handle)
            self.writer.writerow([
                "timestamp", "source_file", "target_file", "status", "source_bytes", "target_bytes",
                "media_id", "error_message"
            ])
            self.handle.flush()

    def record(self, result: AudioResult) -> None:
        if self.writer and self.handle:
            self.writer.writerow([
                datetime.now(timezone.utc).isoformat(),
                result.source_path,
                result.target_path,
                result.status,
                result.source_bytes,
                result.target_bytes,
                result.media_id or "",
                result.error or "",
            ])
            self.handle.flush()

    def close(self) -> None:
        if self.handle:
            try:
                self.handle.close()
            except Exception:
                pass
            self.handle = None


class ProgressReporter:
    def __init__(self, label: str, total_files: int, total_bytes: int, stream: TextIO, clock) -> None:
        self.label = label
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.stream = stream
        self.clock = clock
        self.started_at = clock()
        self.last_report_at = self.started_at
        self.last_percent = -1
        self.files = 0
        self.bytes = 0
        self.converted_count = 0
        self.copied_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.target_bytes_written = 0
        self.interactive = stream.isatty()

    def advance(self, byte_count: int) -> None:
        self.bytes += byte_count
        if self.bytes >= self.total_bytes:
            return
        now = self.clock()
        percent = 100 if self.total_bytes == 0 else int(self.bytes * 100 / self.total_bytes)
        should_report = self.interactive and now - self.last_report_at >= 1
        should_report = should_report or (not self.interactive and (percent >= self.last_percent + 5 or now - self.last_report_at >= 30))
        if should_report:
            self.report(now, final=False)

    def complete_file(self) -> None:
        self.files += 1

    def record_result(self, result: AudioResult) -> None:
        self.files += 1
        self.bytes += result.source_bytes
        self.target_bytes_written += result.target_bytes
        if result.status == "converted":
            self.converted_count += 1
        elif result.status == "copied":
            self.copied_count += 1
        elif result.status == "skipped":
            self.skipped_count += 1
        elif result.status == "failed":
            self.failed_count += 1

        now = self.clock()
        percent = 100 if self.total_bytes == 0 else int(self.bytes * 100 / self.total_bytes)
        should_report = self.interactive and now - self.last_report_at >= 1
        should_report = should_report or (not self.interactive and (percent >= self.last_percent + 5 or now - self.last_report_at >= 30))
        if should_report:
            self.report(now, final=False)

    def report(self, now: float, final: bool) -> None:
        elapsed = max(now - self.started_at, 0.001)
        percent = 100 if self.total_bytes == 0 else min(100, self.bytes * 100 / self.total_bytes)
        speed = self.bytes / elapsed
        remaining = 0 if speed == 0 else max(self.total_bytes - self.bytes, 0) / speed

        extra_info = ""
        if self.converted_count > 0 or self.skipped_count > 0:
            saved_bytes = max(0, self.bytes - self.target_bytes_written)
            saved_pct = (saved_bytes * 100 / self.bytes) if self.bytes > 0 else 0
            extra_info = f", saved {format_size(saved_bytes)} ({saved_pct:.1f}%)"

        line = (
            f"{self.label}: {self.files}/{self.total_files} files, "
            f"{format_size(self.bytes)}/{format_size(self.total_bytes)} ({percent:.1f}%), "
            f"{format_size(round(speed))}/s{extra_info}, elapsed {format_duration(elapsed)}, ETA {format_duration(remaining)}"
        )
        if self.interactive and not final:
            print(f"\r{line}", end="", file=self.stream, flush=True)
        else:
            print(line, file=self.stream, flush=True)
        self.last_report_at = now
        self.last_percent = int(percent)


def clear_directory(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in destination.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def is_compatible_audio_format(source_ext: str, db_filename: str) -> bool:
    s_ext = source_ext.lower()
    d_ext = Path(db_filename).suffix.lower()
    if s_ext == d_ext:
        return True
    if s_ext == ".wav" and d_ext == ".flac":
        return True
    if s_ext == ".flac" and d_ext == ".wav":
        return True
    return False


def fetch_audio_media_index(conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT m.media_id, m.audio_setting_id, m.directory, m.filename, mc.collection_id,
                   (a.file_metadata IS NOT NULL) AS has_metadata
            FROM media m
            LEFT JOIN media_collection mc ON mc.media_id = m.media_id
            LEFT JOIN audio_setting a ON a.audio_setting_id = m.audio_setting_id
            WHERE m.media_type = 'audio' AND m.is_metadata = FALSE
        """)
        rows = cur.fetchall()

    by_full_key: dict[tuple[str, str, str], tuple[int, int | None, bool, str]] = {}
    by_stem_key: dict[tuple[str, str, str], tuple[int, int | None, bool, str]] = {}
    by_dir_file: dict[tuple[str, str], tuple[int, int | None, bool, str]] = {}
    by_filename: dict[str, tuple[int, int | None, bool, str]] = {}

    for media_id, setting_id, directory, filename, collection_id, has_metadata in rows:
        if not filename:
            continue
        fname_lower = filename.strip().lower()
        stem_lower = Path(fname_lower).stem
        dir_str = str(directory or "")
        col_str = str(collection_id or "")

        val = (media_id, setting_id, bool(has_metadata), filename)
        if col_str:
            by_full_key[(col_str, dir_str, fname_lower)] = val
            if fname_lower.endswith(".wav") or fname_lower.endswith(".flac"):
                by_stem_key[(col_str, dir_str, stem_lower)] = val
        if dir_str:
            by_dir_file[(dir_str, fname_lower)] = val
        by_filename[fname_lower] = val

    return {
        "by_full_key": by_full_key,
        "by_stem_key": by_stem_key,
        "by_dir_file": by_dir_file,
        "by_filename": by_filename,
    }


def copy_tree(
    source: Path,
    destination: Path,
    label: str,
    stream: TextIO = sys.stdout,
    clock=time.monotonic,
    convert_wav: bool = False,
    extract_metadata: bool = False,
    resume: bool = False,
    db_config: dict[str, Any] | None = None,
    audit_report: Path | None = None,
) -> None:
    if not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")

    print(f"Scanning {label}...", file=stream, flush=True)
    directories, files, links, total_bytes = scan_tree(source)
    reporter = ProgressReporter(label, len(files), total_bytes, stream, clock)

    if not resume:
        clear_directory(destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)

    for directory in directories:
        target = destination / directory.relative_to(source)
        target.mkdir(parents=True, exist_ok=True)

    db_sync = DatabaseSync(db_config or {}) if db_config else None
    db_connected = db_sync.connect() if db_sync else False
    db_index = fetch_audio_media_index(db_sync.conn) if (db_sync and db_connected) else None
    audit_logger = AuditLogger(audit_report)

    audio_extensions = {".wav", ".flac", ".mp3", ".ogg"}
    audio_tasks: list[AudioTask] = []
    plain_files: list[Path] = []

    expected_target_files: set[Path] = set()

    for source_file in files:
        rel_path = source_file.relative_to(source)
        ext = source_file.suffix.lower()

        if ext in audio_extensions and (convert_wav or extract_metadata):
            target_ext = ".flac" if (ext == ".wav" and convert_wav) else source_file.suffix
            target_filename = f"{source_file.stem}{target_ext}"
            target_file = destination / rel_path.parent / target_filename

            # DB match lookup
            media_id = None
            audio_setting_id = None
            has_metadata = False
            db_filename = None

            if db_index:
                parts = rel_path.parts
                # Check path structure: collection_id/directory/filename
                match = None
                if len(parts) >= 3:
                    candidate = db_index["by_full_key"].get((parts[0], parts[1], source_file.name.lower()))
                    if candidate and is_compatible_audio_format(ext, candidate[3]):
                        match = candidate
                    if not match and ext in {".wav", ".flac"}:
                        candidate = db_index["by_stem_key"].get((parts[0], parts[1], source_file.stem.lower()))
                        if candidate and is_compatible_audio_format(ext, candidate[3]):
                            match = candidate
                if not match and len(parts) >= 2:
                    candidate = db_index["by_dir_file"].get((parts[-2], source_file.name.lower()))
                    if candidate and is_compatible_audio_format(ext, candidate[3]):
                        match = candidate
                if not match:
                    candidate = db_index["by_filename"].get(source_file.name.lower())
                    if candidate and is_compatible_audio_format(ext, candidate[3]):
                        match = candidate

                if match:
                    media_id, audio_setting_id, has_metadata, db_filename = match

            skip_transcode = False
            if resume and target_file.exists() and target_file.stat().st_size > 0:
                if target_filename != source_file.name:
                    old_in_target = target_file.with_name(source_file.name)
                    if old_in_target.exists() and old_in_target.resolve() != source_file.resolve():
                        old_in_target.unlink(missing_ok=True)
                expected_target_files.add(target_file.resolve())

                if db_connected and media_id:
                    if has_metadata and db_filename == target_filename:
                        # Fully completed in earlier run
                        result = AudioResult(
                            source_path=str(source_file),
                            target_path=str(target_file),
                            relative_path=str(rel_path),
                            target_filename=target_filename,
                            status="skipped",
                            source_bytes=source_file.stat().st_size,
                            target_bytes=target_file.stat().st_size,
                            media_id=media_id,
                            audio_setting_id=audio_setting_id,
                        )
                        audit_logger.record(result)
                        reporter.record_result(result)
                        continue
                    else:
                        # File converted but DB needs update
                        skip_transcode = True
                else:
                    # No DB connection or unmapped file, file exists -> skip
                    result = AudioResult(
                        source_path=str(source_file),
                        target_path=str(target_file),
                        relative_path=str(rel_path),
                        target_filename=target_filename,
                        status="skipped",
                        source_bytes=source_file.stat().st_size,
                        target_bytes=target_file.stat().st_size,
                        media_id=media_id,
                        audio_setting_id=audio_setting_id,
                    )
                    audit_logger.record(result)
                    reporter.record_result(result)
                    continue

            audio_tasks.append(AudioTask(
                source_path=str(source_file),
                target_path=str(target_file),
                relative_path=str(rel_path),
                source_filename=source_file.name,
                target_filename=target_filename,
                convert_wav=convert_wav,
                extract_metadata=extract_metadata,
                media_id=media_id,
                audio_setting_id=audio_setting_id,
                source_size=source_file.stat().st_size,
                skip_transcode=skip_transcode,
            ))
        else:
            target = destination / rel_path
            expected_target_files.add(target.resolve())
            if resume and target.exists() and target.stat().st_size == source_file.stat().st_size:
                reporter.files += 1
                reporter.bytes += source_file.stat().st_size
                continue
            plain_files.append(source_file)

    # Process plain files
    for source_file in plain_files:
        target = destination / source_file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source_file.open("rb") as source_handle, target.open("wb") as target_handle:
            while chunk := source_handle.read(1024 * 1024):
                target_handle.write(chunk)
                reporter.advance(len(chunk))
        try:
            shutil.copystat(source_file, target)
        except OSError:
            pass
        reporter.complete_file()

    # Process audio tasks with worker pool
    if audio_tasks:
        task_map = {t.source_path: t for t in audio_tasks}
        worker_count = optimal_worker_count()
        if worker_count <= 1:
            for task in audio_tasks:
                res = _process_audio_worker(task)
                expected_target_files.add(Path(res.target_path).resolve())
                if res.status == "converted":
                    orig_task = task_map.get(res.source_path)
                    if orig_task and orig_task.source_filename != res.target_filename:
                        old_f = Path(res.target_path).with_name(orig_task.source_filename)
                        if old_f.exists() and old_f.resolve() != Path(orig_task.source_path).resolve():
                            old_f.unlink(missing_ok=True)
                if db_sync:
                    db_sync.add(res)
                audit_logger.record(res)
                reporter.record_result(res)
        else:
            with mp.Pool(processes=worker_count) as pool:
                for res in pool.imap_unordered(_process_audio_worker, audio_tasks, chunksize=16):
                    expected_target_files.add(Path(res.target_path).resolve())
                    if res.status == "converted":
                        orig_task = task_map.get(res.source_path)
                        if orig_task and orig_task.source_filename != res.target_filename:
                            old_f = Path(res.target_path).with_name(orig_task.source_filename)
                            if old_f.exists() and old_f.resolve() != Path(orig_task.source_path).resolve():
                                old_f.unlink(missing_ok=True)
                    if db_sync:
                        db_sync.add(res)
                    audit_logger.record(res)
                    reporter.record_result(res)

    if db_sync:
        db_sync.close()
    audit_logger.close()

    # Process symlinks
    for source_link in links:
        target = destination / source_link.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        link_target = os.readlink(source_link)
        if convert_wav and link_target.lower().endswith(".wav"):
            link_target = f"{link_target[:-4]}.flac"
        if target.is_symlink() or target.exists():
            target.unlink()
        os.symlink(link_target, target)
        expected_target_files.add(target.resolve())

    # Prune extraneous files and empty directories in destination
    audit_resolved = audit_report.resolve() if audit_report else None
    for item in list(destination.rglob("*")):
        if item.is_file() or item.is_symlink():
            item_res = item.resolve()
            if item_res != audit_resolved and item_res not in expected_target_files:
                item.unlink(missing_ok=True)

    for item in sorted(destination.rglob("*"), reverse=True):
        if item.is_dir() and not any(item.iterdir()):
            try:
                item.rmdir()
            except OSError:
                pass

    for directory in reversed(directories):
        try:
            shutil.copystat(directory, destination / directory.relative_to(source))
        except OSError:
            pass

    reporter.report(clock(), final=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="High-performance media tree migration and transcoding")
    parser.add_argument("--source", type=Path, required=True, help="Source directory")
    parser.add_argument("--destination", type=Path, required=True, help="Destination directory")
    parser.add_argument("--label", required=True, help="Label for progress reporting")
    parser.add_argument("--convert-wav", action="store_true", default=False, help="Convert WAV files to FLAC")
    parser.add_argument("--extract-metadata", action="store_true", default=False, help="Extract audio metadata")
    parser.add_argument("--resume", action="store_true", default=False, help="Resume from existing destination files")
    parser.add_argument("--audit-report", type=Path, default=None, help="Path for audit report CSV")
    parser.add_argument("--db-host", default=os.getenv("POSTGRES_SERVER", "localhost"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")))
    parser.add_argument("--db-user", default=os.getenv("POSTGRES_USER", "postgres"))
    parser.add_argument("--db-password", default=os.getenv("POSTGRES_PASSWORD", ""))
    parser.add_argument("--db-name", default=os.getenv("POSTGRES_DB", "ecosignal"))
    args = parser.parse_args()

    db_config = None
    if args.db_host and args.db_user:
        db_config = {
            "host": args.db_host,
            "port": args.db_port,
            "user": args.db_user,
            "password": args.db_password,
            "dbname": args.db_name,
        }

    copy_tree(
        source=args.source,
        destination=args.destination,
        label=args.label,
        convert_wav=args.convert_wav,
        extract_metadata=args.extract_metadata,
        resume=args.resume,
        db_config=db_config,
        audit_report=args.audit_report,
    )


if __name__ == "__main__":
    main()
