"""Tests for spectrogram and thumbnail generation."""
import io
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import app.spectrogram as spectrogram
from app.spectrogram import generate_spectrogram_png, generate_thumbnail


def _write_mono_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def _write_stereo_wav(
    path: Path,
    left: np.ndarray,
    right: np.ndarray,
    sample_rate: int,
) -> None:
    left_pcm = np.clip(left, -1.0, 1.0)
    right_pcm = np.clip(right, -1.0, 1.0)
    pcm = np.column_stack((left_pcm, right_pcm))
    pcm = (pcm * 32767).astype(np.int16)

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def test_silence_spectrogram_is_pure_black(tmp_path: Path) -> None:
    """Silence maps to palette index 0 everywhere (pure black)."""
    wav_path = tmp_path / "silence.wav"
    sample_rate = 8000
    silence = np.zeros(sample_rate, dtype=np.float32)
    _write_mono_wav(wav_path, silence, sample_rate)

    png_bytes = generate_spectrogram_png(
        audio_path=str(wav_path),
        start_time=0.0,
        end_time=None,
        min_freq=0,
        max_freq=None,
        fft_size=256,
        window="hanning",
        channel=0,
        width_px=64,
        height_px=32,
    )

    image = Image.open(io.BytesIO(png_bytes))

    assert image.size == (64, 32)
    assert image.convert("L").getextrema() == (0, 0)


def _install_fake_imagemagick(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    commands: list[list[str]] = []

    def _fake_run(command: list[str]) -> bool:
        commands.append(command)
        if command[0] == "montage":
            top = Image.open(command[-3]).convert("RGB")
            bottom = Image.open(command[-2]).convert("RGB")
            combined = Image.new("RGB", (top.width, top.height + bottom.height))
            combined.paste(top, (0, 0))
            combined.paste(bottom, (0, top.height))
            combined.save(command[-1])
            return True

        image = Image.open(command[-4]).convert("RGB")
        pixels = image.load()
        for x in range(5, 35):
            for y in range(5, 16):
                pixels[x, y] = (255, 255, 255)
        if len(command) > 9:
            for x in range(5, 35):
                for y in range(80, 91):
                    pixels[x, y] = (255, 255, 255)
            for x in range(288, 300):
                for y in range(5, 16):
                    pixels[x, y] = (255, 255, 255)
                for y in range(80, 91):
                    pixels[x, y] = (255, 255, 255)
        image.save(command[-1])
        return True

    monkeypatch.setattr(spectrogram, "_run_imagemagick_command", _fake_run)
    return commands


def test_silence_thumbnail_uses_frequency_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silent mono thumbnails include the max-frequency text overlay."""
    commands = _install_fake_imagemagick(monkeypatch)
    wav_path = tmp_path / "silence_thumb.wav"
    sample_rate = 8000
    silence = np.zeros(sample_rate, dtype=np.float32)
    _write_mono_wav(wav_path, silence, sample_rate)

    png_bytes = generate_thumbnail(
        audio_path=str(wav_path),
        channel_num=1,
        sampling_rate=sample_rate,
    )

    image = Image.open(io.BytesIO(png_bytes))

    assert image.size == (300, 150)
    assert commands[0][:3] == ["convert", "-fill", "white"]
    assert "text 5,15 '4000 Hz '" in commands[0]
    assert image.convert("L").getextrema() == (0, 255)


def test_hann_alias_matches_hanning(tmp_path: Path) -> None:
    """The hann alias should render exactly like the hanning name."""
    wav_path = tmp_path / "alias.wav"
    sample_rate = 8000
    signal = np.sin(2 * np.pi * 440 * np.arange(sample_rate, dtype=np.float32) / sample_rate)
    _write_mono_wav(wav_path, signal, sample_rate)

    hann_bytes = generate_spectrogram_png(
        audio_path=str(wav_path),
        start_time=0.0,
        end_time=None,
        min_freq=1,
        max_freq=None,
        fft_size=256,
        window="hann",
        channel=1,
        width_px=64,
        height_px=32,
    )
    hanning_bytes = generate_spectrogram_png(
        audio_path=str(wav_path),
        start_time=0.0,
        end_time=None,
        min_freq=1,
        max_freq=None,
        fft_size=256,
        window="hanning",
        channel=1,
        width_px=64,
        height_px=32,
    )

    assert hann_bytes == hanning_bytes


def test_frequency_filter_changes_spectrogram_content(tmp_path: Path) -> None:
    """Filter mode should alter the rendered content, not just crop the axis."""
    wav_path = tmp_path / "filter.wav"
    sample_rate = 8000
    t = np.arange(sample_rate * 2, dtype=np.float32) / sample_rate
    signal = (
        0.6 * np.sin(2 * np.pi * 400 * t)
        + 0.6 * np.sin(2 * np.pi * 2400 * t)
    )
    _write_mono_wav(wav_path, signal, sample_rate)

    unfiltered_bytes = generate_spectrogram_png(
        audio_path=str(wav_path),
        start_time=0.0,
        end_time=None,
        min_freq=1000,
        max_freq=3000,
        fft_size=256,
        window="hanning",
        channel=1,
        width_px=96,
        height_px=48,
        apply_frequency_filter=False,
    )
    filtered_bytes = generate_spectrogram_png(
        audio_path=str(wav_path),
        start_time=0.0,
        end_time=None,
        min_freq=1000,
        max_freq=3000,
        fft_size=256,
        window="hanning",
        channel=1,
        width_px=96,
        height_px=48,
        apply_frequency_filter=True,
    )

    unfiltered = Image.open(io.BytesIO(unfiltered_bytes)).convert("L")
    filtered = Image.open(io.BytesIO(filtered_bytes)).convert("L")
    diff = np.abs(
        np.asarray(filtered, dtype=np.int16) - np.asarray(unfiltered, dtype=np.int16)
    )

    assert unfiltered_bytes != filtered_bytes
    assert int(diff.sum()) > 10_000


def test_stereo_thumbnail_uses_stacked_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stereo thumbnails use montage stacking and channel labels."""
    commands = _install_fake_imagemagick(monkeypatch)
    wav_path = tmp_path / "stereo_thumb.wav"
    sample_rate = 8000
    t = np.arange(sample_rate, dtype=np.float32) / sample_rate
    left = np.sin(2 * np.pi * 440 * t)
    right = np.sin(2 * np.pi * 880 * t)
    _write_stereo_wav(wav_path, left, right, sample_rate)

    png_bytes = generate_thumbnail(
        audio_path=str(wav_path),
        channel_num=2,
        sampling_rate=sample_rate,
    )

    image = Image.open(io.BytesIO(png_bytes))

    assert image.size == (300, 150)
    grayscale = image.convert("L")

    assert grayscale.getbbox() is not None
    assert commands[0][:5] == ["montage", "-tile", "1x2", "-mode", "Concatenate"]
    assert commands[1][:3] == ["convert", "-fill", "white"]
    assert "text 5,15 '4000 Hz '" in commands[1]
    assert "text 5,85 '4000 Hz'" in commands[1]
    assert "text 290,15 'L'" in commands[1]
    assert "text 290,85 'R'" in commands[1]
    assert grayscale.crop((0, 0, 40, 24)).getextrema()[1] == 255
    assert grayscale.crop((0, 75, 40, 99)).getextrema()[1] == 255
