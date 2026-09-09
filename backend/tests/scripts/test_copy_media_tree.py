import importlib.util
import io
import os
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "copy_media_tree.py"
SPEC = importlib.util.spec_from_file_location("copy_media_tree", SCRIPT_PATH)
assert SPEC and SPEC.loader
copy_media_tree = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(copy_media_tree)


def test_copy_tree_preserves_files_and_links(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    nested = source / "nested"
    nested.mkdir()
    file_path = nested / "recording.wav"
    file_path.write_bytes(b"audio-bytes")
    file_path.chmod(0o640)
    os.symlink("nested/recording.wav", source / "recording-link.wav")

    destination = tmp_path / "destination"
    stream = io.StringIO()

    copy_media_tree.copy_tree(source, destination, "sounds", stream=stream)

    copied = destination / "nested" / "recording.wav"
    assert copied.read_bytes() == b"audio-bytes"
    assert copied.stat().st_mode & 0o777 == 0o640
    assert (destination / "recording-link.wav").is_symlink()
    assert os.readlink(destination / "recording-link.wav") == "nested/recording.wav"
    output = stream.getvalue()
    assert "Scanning sounds..." in output
    assert "1/1 files" in output
    assert "100.0%" in output
    assert "ETA" in output


def test_copy_tree_replaces_existing_destination_contents(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "new.txt").write_text("new")
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "old.txt").write_text("old")

    copy_media_tree.copy_tree(source, destination, "images", stream=io.StringIO())

    assert (destination / "new.txt").read_text() == "new"
    assert not (destination / "old.txt").exists()


def test_copy_tree_rejects_special_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    os.mkfifo(source / "unsupported")

    with pytest.raises(ValueError, match="Unsupported source entry"):
        copy_media_tree.copy_tree(source, tmp_path / "destination", "projects", stream=io.StringIO())
