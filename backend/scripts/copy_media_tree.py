#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from typing import TextIO


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

    def report(self, now: float, final: bool) -> None:
        elapsed = max(now - self.started_at, 0.001)
        percent = 100 if self.total_bytes == 0 else min(100, self.bytes * 100 / self.total_bytes)
        speed = self.bytes / elapsed
        remaining = 0 if speed == 0 else max(self.total_bytes - self.bytes, 0) / speed
        line = (
            f"{self.label}: {self.files}/{self.total_files} files, "
            f"{format_size(self.bytes)}/{format_size(self.total_bytes)} ({percent:.1f}%), "
            f"{format_size(round(speed))}/s, elapsed {format_duration(elapsed)}, ETA {format_duration(remaining)}"
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


def copy_tree(source: Path, destination: Path, label: str, stream: TextIO = sys.stdout, clock=time.monotonic) -> None:
    if not source.is_dir():
        raise ValueError(f"Source directory does not exist: {source}")

    print(f"Scanning {label}...", file=stream, flush=True)
    directories, files, links, total_bytes = scan_tree(source)
    reporter = ProgressReporter(label, len(files), total_bytes, stream, clock)
    clear_directory(destination)

    for directory in directories:
        target = destination / directory.relative_to(source)
        target.mkdir(parents=True, exist_ok=True)

    for source_file in files:
        target = destination / source_file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source_file.open("rb") as source_handle, target.open("wb") as target_handle:
            while chunk := source_handle.read(1024 * 1024):
                target_handle.write(chunk)
                reporter.advance(len(chunk))
        shutil.copystat(source_file, target)
        reporter.complete_file()

    for source_link in links:
        target = destination / source_link.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.readlink(source_link), target)

    for directory in reversed(directories):
        shutil.copystat(directory, destination / directory.relative_to(source))

    reporter.report(clock(), final=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    copy_tree(args.source, args.destination, args.label)


if __name__ == "__main__":
    main()
