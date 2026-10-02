"""Relative sound level (dB) per fixed-width frequency band for annotations."""
import csv
import io
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.annotation import Annotation
from app.models.taxon import SoundClassification
from app.models.user import User
from app.services.analysis_service import analysis_service
from app.spectrogram import _select_channel, _window_values, normalize_window_name

BAND_WIDTH_HZ = 1000
CSV_COLUMNS = [
    "annotation_id",
    "frequency_low_kHz",
    "frequency_high_kHz",
    "dB_relative",
    "annotation_comment",
    "soundscape_component",
    "sound_type",
]
_LEFT_CHANNEL = 1
_POWER_FLOOR = 1e-30
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def compute_band_levels(
    samples: np.ndarray,
    sample_rate: int,
    *,
    fft_size: int,
    window: str,
    min_frequency: float,
    max_frequency: float,
) -> list[tuple[int, int, float]]:
    """Return (low kHz, high kHz, relative dB) for each 1 kHz band overlapping the frequency range.

    Band edges are integer kHz; the highest edge is clipped to the recording's Nyquist frequency.
    Uses the spectrogram renderer's normalization (windowed FFT magnitude / fft_size),
    averages power over frames and bins in the band, then converts to dB.
    """
    win = _window_values(window, fft_size)
    hop = fft_size // 2
    total = int(samples.shape[0])
    if total < fft_size:
        samples = np.concatenate((samples, np.zeros(fft_size - total)))
        total = fft_size
    starts = range(0, total - fft_size + 1, hop)
    power_sum = np.zeros(fft_size // 2 + 1)
    frame_count = 0
    for start in starts:
        spectrum = np.abs(np.fft.rfft(samples[start : start + fft_size] * win)) / float(fft_size)
        power_sum += spectrum**2
        frame_count += 1
    mean_power = power_sum / max(frame_count, 1)
    freqs = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)

    results: list[tuple[int, int, float]] = []
    first_band = int(math.floor(min_frequency / BAND_WIDTH_HZ))
    last_band = int(math.ceil(max_frequency / BAND_WIDTH_HZ))
    for band in range(first_band, last_band):
        band_lo = band * BAND_WIDTH_HZ
        band_hi = band_lo + BAND_WIDTH_HZ
        lo = max(band_lo, min_frequency)
        hi = min(band_hi, max_frequency)
        mask = (freqs >= lo) & (freqs < hi)
        if not mask.any():
            # Range narrower than the FFT bin spacing: use the bin nearest to its center.
            mask = np.zeros_like(freqs, dtype=bool)
            mask[int(np.argmin(np.abs(freqs - (lo + hi) / 2.0)))] = True
        level = 10.0 * math.log10(float(mean_power[mask].mean()) + _POWER_FLOOR)
        results.append((
            band_lo // BAND_WIDTH_HZ,
            round(min(band_hi, sample_rate / 2.0) / BAND_WIDTH_HZ),
            level,
        ))
    return results


def _csv_safe(value: str | None) -> str:
    text = value or ""
    return f"'{text}" if text.startswith(_CSV_FORMULA_PREFIXES) else text


def build_band_levels_csv(
    session: Session,
    *,
    project_id: int,
    media_id: int,
    annotation_ids: list[int],
    fft_size: int,
    window: str,
    current_user: User,
) -> str:
    """Compute band levels for the given annotations (left channel) and render CSV text."""
    media = analysis_service.get_media_for_user(session, project_id, media_id, current_user)
    annotations = session.exec(
        select(Annotation)
        .where(Annotation.media_id == media_id, Annotation.annotation_id.in_(annotation_ids))  # type: ignore[union-attr]
        .order_by(Annotation.annotation_id)
    ).all()
    if len(annotations) != len(set(annotation_ids)):
        raise HTTPException(status_code=404, detail="Annotation not found for this media")

    audio_path = Path(analysis_service._resolve_audio_path(session, media, media_id))
    sound_ids = {a.sound_id for a in annotations if a.sound_id is not None}
    sounds = {
        s.sound_id: s
        for s in session.exec(
            select(SoundClassification).where(SoundClassification.sound_id.in_(sound_ids))  # type: ignore[attr-defined]
        ).all()
    } if sound_ids else {}
    normalized_window = normalize_window_name(window)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)
    row_count = 0
    with sf.SoundFile(str(audio_path), "r") as audio_file:
        sample_rate = audio_file.samplerate
        nyquist = sample_rate / 2.0
        for annotation in annotations:
            frame_start = int(max(0.0, annotation.min_x) * sample_rate)
            frame_stop = min(int(annotation.max_x * sample_rate), len(audio_file))
            if frame_stop <= frame_start:
                continue
            audio_file.seek(frame_start)
            raw = audio_file.read(frame_stop - frame_start, dtype="float64", always_2d=False)
            sound = sounds.get(annotation.sound_id) if annotation.sound_id is not None else None
            samples = _select_channel(np.asarray(raw), _LEFT_CHANNEL)
            for low_khz, high_khz, level in compute_band_levels(
                samples,
                sample_rate,
                fft_size=fft_size,
                window=normalized_window,
                min_frequency=max(0.0, annotation.min_y),
                max_frequency=min(annotation.max_y, nyquist),
            ):
                writer.writerow([
                    annotation.annotation_id,
                    low_khz,
                    high_khz,
                    f"{level:.2f}",
                    _csv_safe(annotation.comments),
                    _csv_safe(sound.soundscape_component if sound else None),
                    _csv_safe(sound.sound_type if sound else None),
                ])
                row_count += 1
    if row_count == 0:
        raise HTTPException(
            status_code=422,
            detail="No band levels could be computed: selected annotations lie outside the audio duration or frequency range",
        )
    return output.getvalue()
