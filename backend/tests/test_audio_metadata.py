import os
import struct
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.audio_metadata import (
    as_float,
    as_int,
    build_audio_file_metadata,
    compute_file_md5,
    extract_audio_tags,
    json_tag_value,
    missing_audio_tag_names,
    optimal_worker_count,
    probe_audio,
    transcode_to_flac,
)


def _create_wav(path: Path, duration_s: float = 0.2, sample_rate: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        n_frames = int(duration_s * sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


def test_as_int_and_as_float() -> None:
    assert as_int(123) == 123
    assert as_int("456") == 456
    assert as_int(None) is None
    assert as_int("") is None
    assert as_int("invalid") is None

    assert as_float(1.23) == 1.23
    assert as_float("4.56") == 4.56
    assert as_float(None) is None
    assert as_float("") is None
    assert as_float("invalid") is None


def test_json_tag_value() -> None:
    assert json_tag_value("test") == "test"
    assert json_tag_value(123) == 123
    assert json_tag_value(1.23) == 1.23
    assert json_tag_value(True) is True
    assert json_tag_value(b"12345") == "binary:5 bytes"
    assert json_tag_value(bytearray(b"123")) == "binary:3 bytes"
    assert json_tag_value([1, 2]) == "[1, 2]"

    # Mutagen APIC frame object with data, mime, and desc
    class MockAPIC:
        mime = "image/jpeg"
        desc = "cover"
        data = b"\xff\xd8\xff" * 100

    assert json_tag_value(MockAPIC()) == "picture:image/jpeg:cover:300 bytes"

    # Mutagen frame object with data only (e.g. PRIV)
    class MockPRIV:
        data = b"\x00" * 50

    assert json_tag_value(MockPRIV()) == "MockPRIV:50 bytes"

    # Truncate strings longer than 2048 chars
    long_str = "A" * 3000
    res = json_tag_value(long_str)
    assert isinstance(res, str)
    assert len(res) == 2048
    assert res.endswith("...")


def test_missing_audio_tag_names() -> None:
    source_tags = {
        "id3v2": {
            "title": ["Morning Birds"],
            "artist": ["Surveyor A"],
            "encoder": ["LAME"],  # non-content tag ignored
        }
    }
    stored_tags = {
        "vorbis_comment": {
            "title": ["morning birds"],
        }
    }
    missing = missing_audio_tag_names(source_tags, stored_tags)
    assert missing == ["artist"]


def test_compute_file_md5(tmp_path: Path) -> None:
    test_file = tmp_path / "test.bin"
    test_file.write_bytes(b"hello world")
    assert compute_file_md5(test_file) == "5eb63bbbe01eeed093cb22bb8f5acdc3"


def test_optimal_worker_count() -> None:
    count = optimal_worker_count()
    assert isinstance(count, int)
    assert 1 <= count <= 8


def test_probe_audio_valid_wav(tmp_path: Path) -> None:
    wav_path = tmp_path / "sample.wav"
    _create_wav(wav_path, duration_s=0.2, sample_rate=44100)
    probed = probe_audio(wav_path)
    assert probed["sampling_rate_hz"] == 44100
    assert probed["channel_num"] == 1
    assert probed["duration_s"] is not None
    assert probed["codec"].startswith("pcm_") or probed["codec"] == "wav"


def test_probe_audio_no_audio_stream(tmp_path: Path) -> None:
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("not an audio")
    with pytest.raises(RuntimeError):
        probe_audio(txt_file)


def test_extract_audio_tags(tmp_path: Path) -> None:
    wav_path = tmp_path / "sample.wav"
    _create_wav(wav_path)
    tags, warnings = extract_audio_tags(wav_path)
    assert isinstance(tags, dict)
    assert isinstance(warnings, list)


def test_build_audio_file_metadata() -> None:
    meta = build_audio_file_metadata(
        source_filename="test.wav",
        target_filename="test.flac",
        source_probe={"codec": "pcm_s16le", "sampling_rate_hz": 44100},
        stored_probe={"codec": "flac", "container": "flac", "sampling_rate_hz": 44100},
        tags={"id3v2": {"title": ["Birdsong"]}},
        warnings=[],
    )
    assert meta["schema_version"] == 1
    assert meta["source"]["filename"] == "test.wav"
    assert meta["stored"]["filename"] == "test.flac"
    assert meta["stored"]["container"] == "flac"
    assert meta["tags"]["id3v2"]["title"] == ["Birdsong"]


def test_transcode_to_flac(tmp_path: Path) -> None:
    wav_path = tmp_path / "source.wav"
    _create_wav(wav_path, duration_s=0.2, sample_rate=44100)
    flac_path = tmp_path / "target.flac"
    transcode_to_flac(wav_path, flac_path)
    assert flac_path.exists()
    assert flac_path.stat().st_size > 0
    probed = probe_audio(flac_path)
    assert probed["codec"] == "flac"
    assert probed["sampling_rate_hz"] == 44100


def test_transcode_to_flac_with_resample(tmp_path: Path) -> None:
    wav_path = tmp_path / "source48k.wav"
    _create_wav(wav_path, duration_s=0.2, sample_rate=48000)
    flac_path = tmp_path / "target24k.flac"
    transcode_to_flac(wav_path, flac_path, sampling_rate_hz=24000)
    assert flac_path.exists()
    probed = probe_audio(flac_path)
    assert probed["sampling_rate_hz"] == 24000


def test_probe_audio_errors(tmp_path: Path, monkeypatch) -> None:
    wav_path = tmp_path / "test.wav"
    _create_wav(wav_path)

    # FileNotFoundError
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=FileNotFoundError("ffprobe")))
    with pytest.raises(RuntimeError, match="ffprobe is not installed"):
        probe_audio(wav_path)

    # Empty streams (no audio stream)
    mock_res = MagicMock()
    mock_res.stdout = '{"streams": [], "format": {}}'
    monkeypatch.setattr(subprocess, "run", MagicMock(return_value=mock_res))
    with pytest.raises(ValueError, match="File does not contain an audio stream"):
        probe_audio(wav_path)


def test_extract_audio_tags_edge_cases(tmp_path: Path, monkeypatch) -> None:
    wav_path = tmp_path / "test.wav"
    _create_wav(wav_path)

    # mutagen is None
    monkeypatch.setattr("app.audio_metadata.mutagen", None)
    tags, warnings = extract_audio_tags(wav_path)
    assert tags == {}
    assert any("mutagen is not installed" in w for w in warnings)

    # mutagen raises Exception
    monkeypatch.setattr("app.audio_metadata.mutagen", MagicMock(File=MagicMock(side_effect=RuntimeError("corrupt header"))))
    tags, warnings = extract_audio_tags(wav_path)
    assert tags == {}
    assert any("could not be fully read" in w for w in warnings)

    # Real tags simulation (ID3, Vorbis, WAVE)
    class FakeID3(dict):
        pass
    FakeID3.__module__ = "mutagen.id3"

    mock_tags = FakeID3({"title": "Forest", "artist": ["Echo"], "track": 1})
    mock_audio = MagicMock()
    mock_audio.tags = mock_tags
    monkeypatch.setattr("app.audio_metadata.mutagen", MagicMock(File=MagicMock(return_value=mock_audio)))
    tags, warnings = extract_audio_tags(wav_path)
    assert "id3v2" in tags
    assert tags["id3v2"]["title"] == ["Forest"]
    assert tags["id3v2"]["artist"] == ["Echo"]


def test_transcode_to_flac_errors(tmp_path: Path, monkeypatch) -> None:
    wav_path = tmp_path / "src.wav"
    _create_wav(wav_path)
    target = tmp_path / "target.flac"

    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=FileNotFoundError("ffmpeg")))
    with pytest.raises(RuntimeError, match="ffmpeg is not installed"):
        transcode_to_flac(wav_path, target)

    err = subprocess.CalledProcessError(1, ["ffmpeg"], stderr="corrupt data")
    monkeypatch.setattr(subprocess, "run", MagicMock(side_effect=err))
    with pytest.raises(RuntimeError, match="ffmpeg conversion failed"):
        transcode_to_flac(wav_path, target)


def test_extract_audio_tags_wav_riff_info(tmp_path: Path) -> None:
    wav_path = tmp_path / "test_info.wav"
    inam_data = b"Morning Birds\x00"
    inam_chunk = b"INAM" + struct.pack("<I", len(inam_data)) + inam_data
    if len(inam_data) % 2 == 1:
        inam_chunk += b"\x00"

    info_payload = b"INFO" + inam_chunk
    list_chunk = b"LIST" + struct.pack("<I", len(info_payload)) + info_payload
    if len(info_payload) % 2 == 1:
        list_chunk += b"\x00"

    fmt_chunk = b"fmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00"
    data_chunk = b"data\x00\x00\x00\x00"
    body = fmt_chunk + data_chunk + list_chunk
    riff_header = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE"
    wav_path.write_bytes(riff_header + body)

    tags, warnings = extract_audio_tags(wav_path)
    assert "riff_info" in tags
    assert tags["riff_info"]["INAM"] == ["Morning Birds"]
    assert warnings == []


def test_extract_audio_tags_wav_id3_extended_header(tmp_path: Path) -> None:
    wav_path = tmp_path / "test_id3.wav"
    frame_body = b"\x00Dawn Chorus"
    frame = b"TIT2" + struct.pack(">I", len(frame_body)) + b"\x00\x00" + frame_body
    ext_header = b"\x00\x00\x00\x0c\x01\x00\x00\x00\x00\x00\x00\x00"
    tag_payload = ext_header + frame

    payload_len = len(tag_payload)
    b1 = (payload_len >> 21) & 0x7f
    b2 = (payload_len >> 14) & 0x7f
    b3 = (payload_len >> 7) & 0x7f
    b4 = payload_len & 0x7f
    id3_header = b"ID3\x04\x00\x40" + bytes([b1, b2, b3, b4])

    id3_chunk_data = id3_header + tag_payload
    id3_chunk = b"id3 " + struct.pack("<I", len(id3_chunk_data)) + id3_chunk_data
    if len(id3_chunk_data) % 2 == 1:
        id3_chunk += b"\x00"

    fmt_chunk = b"fmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00"
    data_chunk = b"data\x00\x00\x00\x00"
    body = fmt_chunk + data_chunk + id3_chunk
    riff_header = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE"
    wav_path.write_bytes(riff_header + body)

    tags, warnings = extract_audio_tags(wav_path)
    assert "id3v2" in tags
    assert tags["id3v2"]["TIT2"] == ["Dawn Chorus"]
    assert warnings == []


def test_extract_audio_tags_ffprobe_fallback(tmp_path: Path, monkeypatch) -> None:
    wav_path = tmp_path / "test_fallback.wav"
    _create_wav(wav_path)
    monkeypatch.setattr("app.audio_metadata._extract_tags_ffprobe", lambda p: {"title": ["Fallback Bird"]})
    tags, warnings = extract_audio_tags(wav_path)
    assert "riff_info" in tags
    assert tags["riff_info"]["title"] == ["Fallback Bird"]
    assert warnings == []


def test_extract_audio_tags_empty_exception_formatting(tmp_path: Path, monkeypatch) -> None:
    wav_path = tmp_path / "test_err.wav"
    _create_wav(wav_path)

    class EmptyMessageError(Exception):
        def __str__(self) -> str:
            return ""

    monkeypatch.setattr("app.audio_metadata.mutagen.File", MagicMock(side_effect=EmptyMessageError()))
    monkeypatch.setattr("app.audio_metadata._extract_tags_ffprobe", lambda p: {})
    tags, warnings = extract_audio_tags(wav_path)
    assert tags == {}
    assert any("EmptyMessageError" in w for w in warnings)

