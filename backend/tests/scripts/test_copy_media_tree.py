import importlib.util
import io
import os
import wave
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "copy_media_tree.py"
SPEC = importlib.util.spec_from_file_location("copy_media_tree", SCRIPT_PATH)
assert SPEC and SPEC.loader
copy_media_tree = importlib.util.module_from_spec(SPEC)
import sys
sys.modules["copy_media_tree"] = copy_media_tree
SPEC.loader.exec_module(copy_media_tree)


def _create_wav(path: Path, duration_s: float = 0.2, sample_rate: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        n_frames = int(duration_s * sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


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


def test_copy_tree_converts_wav_to_flac_and_extracts_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    wav_file = source / "10" / "1" / "forest.wav"
    _create_wav(wav_file, duration_s=0.3, sample_rate=48000)

    # Add ID3 tag to WAV
    try:
        from mutagen.id3 import TIT2
        from mutagen.wave import WAVE
        audio = WAVE(str(wav_file))
        audio.add_tags()
        audio.tags.add(TIT2(encoding=3, text="Rainforest 2026"))
        audio.save()
    except Exception:
        pass

    os.symlink("10/1/forest.wav", source / "forest-link.wav")

    destination = tmp_path / "destination"
    stream = io.StringIO()
    audit_report = tmp_path / "audit.csv"

    copy_media_tree.copy_tree(
        source,
        destination,
        "sounds",
        stream=stream,
        convert_wav=True,
        extract_metadata=True,
        audit_report=audit_report,
    )

    # Destination should have .flac, not .wav
    target_flac = destination / "10" / "1" / "forest.flac"
    assert target_flac.exists()
    assert not (destination / "10" / "1" / "forest.wav").exists()
    assert target_flac.stat().st_size > 0

    # Check symlink target updated to .flac
    target_link = destination / "forest-link.wav"
    assert target_link.is_symlink()
    assert os.readlink(target_link) == "10/1/forest.flac"

    # Probe FLAC
    probed = copy_media_tree._probe_audio(target_flac)
    assert probed["codec"] == "flac"
    assert probed["sampling_rate_hz"] == 48000

    # Check audit log written
    assert audit_report.exists()
    content = audit_report.read_text()
    assert "timestamp" in content
    assert "forest.flac" in content


def test_copy_tree_handles_corrupt_wav_gracefully(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    bad_wav = source / "corrupt.wav"
    bad_wav.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt truncated-garbage")

    destination = tmp_path / "destination"
    audit_report = tmp_path / "corrupt_audit.csv"

    copy_media_tree.copy_tree(
        source,
        destination,
        "sounds",
        stream=io.StringIO(),
        convert_wav=True,
        extract_metadata=True,
        audit_report=audit_report,
    )

    # Fallback: source file should be copied so user data isn't lost
    fallback = destination / "corrupt.wav"
    assert fallback.exists()
    assert fallback.read_bytes() == bad_wav.read_bytes()

    # Audit report should reflect failure
    assert audit_report.exists()
    audit_text = audit_report.read_text()
    assert "failed" in audit_text


def test_copy_tree_resumes_without_retranscoding(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    wav_file = source / "sample.wav"
    _create_wav(wav_file, duration_s=0.2)

    destination = tmp_path / "destination"

    # First run
    copy_media_tree.copy_tree(
        source,
        destination,
        "sounds",
        stream=io.StringIO(),
        convert_wav=True,
        extract_metadata=True,
        resume=True,
    )

    target_flac = destination / "sample.flac"
    assert target_flac.exists()
    first_mtime = target_flac.stat().st_mtime_ns

    # Second run with resume=True
    stream = io.StringIO()
    copy_media_tree.copy_tree(
        source,
        destination,
        "sounds",
        stream=stream,
        convert_wav=True,
        extract_metadata=True,
        resume=True,
    )

    # File mtime should be unchanged because it was skipped
    assert target_flac.stat().st_mtime_ns == first_mtime
    output = stream.getvalue()
    assert "1/1 files" in output


def test_copy_tree_multiple_audio_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for i in range(4):
        _create_wav(source / f"clip_{i}.wav", duration_s=0.1)

    destination = tmp_path / "destination"
    stream = io.StringIO()

    copy_media_tree.copy_tree(
        source,
        destination,
        "sounds",
        stream=stream,
        convert_wav=True,
        extract_metadata=True,
    )

    for i in range(4):
        assert (destination / f"clip_{i}.flac").exists()


def test_database_sync_batches_updates() -> None:
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    sync = copy_media_tree.DatabaseSync({"host": "dummy"}, batch_size=2)
    sync.conn = mock_conn

    res1 = copy_media_tree.AudioResult(
        source_path="/src/1.wav",
        target_path="/dst/1.flac",
        relative_path="1.flac",
        target_filename="1.flac",
        status="converted",
        source_bytes=100,
        target_bytes=50,
        media_id=101,
        audio_setting_id=201,
        md5_hash="md5_1",
        file_metadata={"source": {}, "stored": {}},
        probed={"sampling_rate_hz": 44100, "bit_depth": 16, "channel_num": 1, "duration_s": 1.0},
    )
    res2 = copy_media_tree.AudioResult(
        source_path="/src/2.wav",
        target_path="/dst/2.flac",
        relative_path="2.flac",
        target_filename="2.flac",
        status="converted",
        source_bytes=200,
        target_bytes=90,
        media_id=102,
        audio_setting_id=202,
        md5_hash="md5_2",
        file_metadata={"source": {}, "stored": {}},
        probed={"sampling_rate_hz": 48000, "bit_depth": 24, "channel_num": 2, "duration_s": 2.0},
    )

    sync.add(res1)
    # Batch size is 2, not reached yet
    assert mock_cursor.executemany.call_count == 0

    sync.add(res2)
    # Batch size 2 reached, should have executed media and audio_setting updates
    assert mock_cursor.executemany.call_count == 2
    mock_conn.commit.assert_called_once()
    sync.close()


def test_helpers_edge_cases() -> None:
    assert copy_media_tree.format_size(0) == "0.0 B"
    assert "GiB" in copy_media_tree.format_size(1024 * 1024 * 1024 * 5)
    assert copy_media_tree.format_duration(0) == "00:00"
    assert copy_media_tree.format_duration(3665) == "01:01:05"


def test_copy_tree_non_wav_audio_with_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    # First create a real wav, then transcode to FLAC to use as a source non-WAV
    temp_wav = source / "temp.wav"
    _create_wav(temp_wav, duration_s=0.2)
    flac_file = source / "10" / "2" / "already.flac"
    flac_file.parent.mkdir(parents=True, exist_ok=True)
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-i", str(temp_wav), "-c:a", "flac", str(flac_file)], check=True, capture_output=True)
    temp_wav.unlink()

    destination = tmp_path / "destination"
    stream = io.StringIO()

    copy_media_tree.copy_tree(
        source,
        destination,
        "sounds",
        stream=stream,
        convert_wav=True,
        extract_metadata=True,
    )

    copied_flac = destination / "10" / "2" / "already.flac"
    assert copied_flac.exists()
    assert copied_flac.stat().st_size == flac_file.stat().st_size


def test_fetch_audio_media_index_and_db_matching(tmp_path: Path) -> None:
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    # Simulate rows: (media_id, audio_setting_id, directory, filename, collection_id, has_metadata)
    mock_cursor.fetchall.return_value = [
        (101, 201, 2, "bird.wav", 10, False),
        (102, 202, 3, "frog.flac", 10, True),
    ]

    index = copy_media_tree.fetch_audio_media_index(mock_conn)
    assert ("10", "2", "bird.wav") in index["by_full_key"]
    assert ("10", "2", "bird") in index["by_stem_key"]
    assert "bird.wav" in index["by_filename"]

    # Now test copy_tree with mocked DB
    source = tmp_path / "source"
    source.mkdir()
    wav_file = source / "10" / "2" / "bird.wav"
    _create_wav(wav_file, duration_s=0.2)

    destination = tmp_path / "destination"

    mock_sync = MagicMock()
    mock_sync.connect.return_value = True
    mock_sync.conn = mock_conn

    # Patch DatabaseSync in copy_media_tree
    original_db_sync = copy_media_tree.DatabaseSync
    try:
        copy_media_tree.DatabaseSync = MagicMock(return_value=mock_sync)
        copy_media_tree.copy_tree(
            source,
            destination,
            "sounds",
            stream=io.StringIO(),
            convert_wav=True,
            extract_metadata=True,
            db_config={"host": "localhost"},
        )
        assert mock_sync.add.call_count == 1
        res = mock_sync.add.call_args[0][0]
        assert res.media_id == 101
        assert res.audio_setting_id == 201
        assert res.target_filename == "bird.flac"
    finally:
        copy_media_tree.DatabaseSync = original_db_sync


def test_copy_media_tree_cli(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "test.txt").write_text("hello")

    destination = tmp_path / "destination"

    monkeypatch.setattr(
        "sys.argv",
        [
            "copy_media_tree.py",
            "--source", str(source),
            "--destination", str(destination),
            "--label", "images",
        ]
    )
    copy_media_tree.main()
    assert (destination / "test.txt").read_text() == "hello"


def test_database_sync_connect_failure() -> None:
    sync = copy_media_tree.DatabaseSync({"host": "invalid_host_that_does_not_exist", "port": 5432})
    assert sync.connect() is False
    assert sync.conn is None
    sync.flush()  # should not crash
    sync.close()  # should not crash


def test_copy_tree_resume_with_db_scenarios(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    wav_a = source / "10" / "1" / "full_done.wav"
    wav_b = source / "10" / "1" / "file_done_needs_db.wav"
    _create_wav(wav_a, duration_s=0.2)
    _create_wav(wav_b, duration_s=0.2)

    destination = tmp_path / "destination"
    dest_a = destination / "10" / "1" / "full_done.flac"
    dest_b = destination / "10" / "1" / "file_done_needs_db.flac"
    dest_a.parent.mkdir(parents=True, exist_ok=True)
    # Pre-create valid destination FLACs
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-i", str(wav_a), "-c:a", "flac", str(dest_a)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(wav_b), "-c:a", "flac", str(dest_b)], check=True, capture_output=True)

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        # media_id, audio_setting_id, directory, filename, collection_id, has_metadata
        (101, 201, 1, "full_done.flac", 10, True),  # full done -> skipped completely
        (102, 202, 1, "file_done_needs_db.wav", 10, False),  # needs DB metadata -> skip_transcode=True
    ]

    mock_sync = MagicMock()
    mock_sync.connect.return_value = True
    mock_sync.conn = mock_conn

    original_db_sync = copy_media_tree.DatabaseSync
    try:
        copy_media_tree.DatabaseSync = MagicMock(return_value=mock_sync)
        stream = io.StringIO()
        copy_media_tree.copy_tree(
            source,
            destination,
            "sounds",
            stream=stream,
            convert_wav=True,
            extract_metadata=True,
            resume=True,
            db_config={"host": "localhost"},
        )
        # Should only have called add for file_done_needs_db (full_done is skipped without worker task)
        assert mock_sync.add.call_count == 1
        res = mock_sync.add.call_args[0][0]
        assert res.media_id == 102
        assert res.target_filename == "file_done_needs_db.flac"
        assert res.file_metadata is not None
    finally:
        copy_media_tree.DatabaseSync = original_db_sync


def test_copy_tree_resume_plain_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "image.png").write_bytes(b"image_content")

    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "image.png").write_bytes(b"image_content")

    stream = io.StringIO()
    copy_media_tree.copy_tree(
        source,
        destination,
        "images",
        stream=stream,
        resume=True,
    )
    assert "1/1 files" in stream.getvalue()


def test_process_audio_worker_direct(tmp_path: Path) -> None:
    src = tmp_path / "sound.wav"
    _create_wav(src)
    dst = tmp_path / "sound.flac"

    # 1. Transcoding
    task = copy_media_tree.AudioTask(
        source_path=str(src),
        target_path=str(dst),
        relative_path="sound.wav",
        source_filename="sound.wav",
        target_filename="sound.flac",
        convert_wav=True,
        extract_metadata=True,
        source_size=src.stat().st_size,
    )
    res = copy_media_tree._process_audio_worker(task)
    assert res.status == "converted"
    assert dst.exists()
    assert res.file_metadata is not None

    # 2. Skip transcode (resume)
    task_skip = copy_media_tree.AudioTask(
        source_path=str(src),
        target_path=str(dst),
        relative_path="sound.wav",
        source_filename="sound.wav",
        target_filename="sound.flac",
        convert_wav=True,
        extract_metadata=True,
        source_size=src.stat().st_size,
        skip_transcode=True,
    )
    res_skip = copy_media_tree._process_audio_worker(task_skip)
    assert res_skip.status == "skipped"

    # 3. Direct copy
    dst_copy = tmp_path / "copied.wav"
    task_copy = copy_media_tree.AudioTask(
        source_path=str(src),
        target_path=str(dst_copy),
        relative_path="sound.wav",
        source_filename="sound.wav",
        target_filename="copied.wav",
        convert_wav=False,
        extract_metadata=True,
        source_size=src.stat().st_size,
    )
    res_copy = copy_media_tree._process_audio_worker(task_copy)
    assert res_copy.status == "copied"
    assert dst_copy.exists()

    # 4. Skip transcode failure when target unreadable
    broken_dst = tmp_path / "non_existent.flac"
    task_fail = copy_media_tree.AudioTask(
        source_path=str(src),
        target_path=str(broken_dst),
        relative_path="sound.wav",
        source_filename="sound.wav",
        target_filename="non_existent.flac",
        convert_wav=True,
        extract_metadata=True,
        skip_transcode=True,
    )
    res_fail = copy_media_tree._process_audio_worker(task_fail)
    assert res_fail.status == "failed"
    assert "probe on existing target failed" in res_fail.error


def test_process_audio_worker_transcode_fallback(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "sound.wav"
    _create_wav(src)
    dst = tmp_path / "sound.flac"

    task = copy_media_tree.AudioTask(
        source_path=str(src),
        target_path=str(dst),
        relative_path="sound.wav",
        source_filename="sound.wav",
        target_filename="sound.flac",
        convert_wav=True,
        extract_metadata=True,
        source_size=src.stat().st_size,
    )
    monkeypatch.setattr(copy_media_tree, "transcode_to_flac", MagicMock(side_effect=RuntimeError("transcode error")))
    res = copy_media_tree._process_audio_worker(task)
    assert res.status == "failed"
    assert "Transcoding failed" in res.error
    assert (tmp_path / "sound.wav").exists()


def test_process_audio_worker_copy_error(tmp_path: Path) -> None:
    non_existent = tmp_path / "missing.ogg"
    dst = tmp_path / "dest.ogg"
    task = copy_media_tree.AudioTask(
        source_path=str(non_existent),
        target_path=str(dst),
        relative_path="missing.ogg",
        source_filename="missing.ogg",
        target_filename="dest.ogg",
        convert_wav=False,
        extract_metadata=False,
    )
    res = copy_media_tree._process_audio_worker(task)
    assert res.status == "failed"
    assert "Copy/probe failed" in res.error


def test_database_sync_no_psycopg(monkeypatch) -> None:
    monkeypatch.setattr(copy_media_tree, "psycopg", None)
    sync = copy_media_tree.DatabaseSync({})
    assert sync.connect() is False


def test_copy_tree_source_not_dir(tmp_path: Path) -> None:
    non_dir = tmp_path / "not_a_dir"
    with pytest.raises(ValueError, match="Source directory does not exist"):
        copy_media_tree.copy_tree(non_dir, tmp_path / "dest", "test")


def test_copy_tree_prunes_extraneous_and_superseded_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()

    # Source has one wav file and one plain txt file
    src_wav = source / "clip.wav"
    _create_wav(src_wav, duration_s=0.2, sample_rate=44100)
    (source / "info.txt").write_text("hello")

    # Destination already has an old clip.wav, an obsolete extra.wav, and an empty folder
    dst_wav = destination / "clip.wav"
    _create_wav(dst_wav, duration_s=0.2, sample_rate=44100)
    (destination / "extra.wav").write_text("extraneous")
    (destination / "empty_dir").mkdir()

    copy_media_tree.copy_tree(
        source,
        destination,
        "test_prune",
        convert_wav=True,
        extract_metadata=True,
        resume=True,
    )

    # Converted flac exists
    assert (destination / "clip.flac").exists()
    # Old clip.wav in destination was cleaned up because it was superseded by clip.flac
    assert not (destination / "clip.wav").exists()
    # Extra file in destination was pruned
    assert not (destination / "extra.wav").exists()
    # Empty directory was pruned
    assert not (destination / "empty_dir").exists()
    # info.txt was copied
    assert (destination / "info.txt").read_text() == "hello"
    # Source clip.wav is intact
    assert src_wav.exists()


def test_copy_tree_preserves_non_wav_formats(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()

    # Create dummy ogg, mp3, flac and wav files
    ogg_file = source / "10" / "1" / "track.ogg"
    mp3_file = source / "10" / "1" / "track.mp3"
    wav_file = source / "10" / "1" / "audio.wav"
    _create_wav(wav_file, duration_s=0.1, sample_rate=44100)
    ogg_file.parent.mkdir(parents=True, exist_ok=True)
    ogg_file.write_bytes(b"OggS dummy ogg content")
    mp3_file.write_bytes(b"ID3 dummy mp3 content")

    # Mock DB index where collection=10, dir=1 has track.ogg and track.mp3
    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur
    fake_cur.fetchall.return_value = [
        (101, 101, "1", "track.ogg", 10, False),
        (102, 102, "1", "track.mp3", 10, False),
        (103, 103, "1", "audio.wav", 10, False),
    ]

    monkeypatch.setattr(copy_media_tree, "probe_audio", MagicMock(return_value={
        "container": "ogg", "codec": "vorbis", "duration_s": 1.0,
        "sampling_rate_hz": 48000, "bit_depth": 16, "channel_num": 1, "bit_rate_bps": 128000
    }))
    monkeypatch.setattr(copy_media_tree, "extract_audio_tags", MagicMock(return_value=({}, [])))

    db_config = {"host": "localhost", "port": 5432, "user": "u", "password": "p", "dbname": "db"}
    monkeypatch.setattr(copy_media_tree.psycopg, "connect", MagicMock(return_value=fake_conn))

    copy_media_tree.copy_tree(
        source,
        destination,
        "test_non_wav",
        convert_wav=True,
        extract_metadata=True,
        db_config=db_config,
    )

    # wav converted to flac
    assert (destination / "10" / "1" / "audio.flac").exists()
    assert not (destination / "10" / "1" / "audio.wav").exists()
    # ogg preserved as ogg
    assert (destination / "10" / "1" / "track.ogg").exists()
    assert not (destination / "10" / "1" / "track.flac").exists()
    # mp3 preserved as mp3
    assert (destination / "10" / "1" / "track.mp3").exists()
    assert not (destination / "10" / "1" / "track.flac").exists()




