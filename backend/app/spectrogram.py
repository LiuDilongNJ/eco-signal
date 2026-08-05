"""Spectrogram rendering utilities for the current server-side waveform views."""
import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from PIL import Image

WINDOW_FUNCTIONS: frozenset[str] = frozenset(
    {"hann", "hanning", "bartlett", "blackman", "hamming", "kaiser"}
)

DETAIL_DEFAULT_FFT_SIZE = 1024
DETAIL_DEFAULT_WINDOW = "hanning"
DETAIL_DEFAULT_MIN_FREQ = 1

_SPEC_TOP_DB = 120.0
_THUMB_WIDTH = 300
_THUMB_HEIGHT = 150
_THUMB_HALF_HEIGHT = 75
_THUMB_FFT_SIZE = 4096
_THUMB_MIN_FREQ = 10
_THUMB_WINDOW = "hanning"
_PLAYER_WIDTH = 1200
_PLAYER_HEIGHT = 400
_KAISER_BETA = 14.0

logger = logging.getLogger(__name__)

_SVT_COLORS = [
    (0, 0, 0),
    (58 / 4, 68 / 4, 65 / 4),
    (80 / 2, 100 / 2, 153 / 2),
    (90, 180, 100),
    (224, 224, 44),
    (255, 60, 30),
    (255, 255, 255),
]
_SVT_PALETTE = [
    channel
    for rgb in (
        tuple(int(v) for v in color)
        for color in (
            (
                (1.0 - alpha) * _SVT_COLORS[index_int][0]
                + alpha * _SVT_COLORS[index_int + 1][0],
                (1.0 - alpha) * _SVT_COLORS[index_int][1]
                + alpha * _SVT_COLORS[index_int + 1][1],
                (1.0 - alpha) * _SVT_COLORS[index_int][2]
                + alpha * _SVT_COLORS[index_int + 1][2],
            )
            if alpha > 0
            else (
                (1.0 - alpha) * _SVT_COLORS[index_int][0],
                (1.0 - alpha) * _SVT_COLORS[index_int][1],
                (1.0 - alpha) * _SVT_COLORS[index_int][2],
            )
            for i in range(256)
            for index in [i * (len(_SVT_COLORS) - 1) / 255.0]
            for index_int in [int(index)]
            for alpha in [index - float(index_int)]
        )
    )
    for channel in rgb
]


class _AudioWindowProcessor:
    """Read sliding FFT windows from an audio file."""

    def __init__(
        self,
        audio_file: sf.SoundFile,
        fft_size: int,
        channel: int,
        window: str,
        *,
        frame_start: int = 0,
        frame_stop: int | None = None,
    ) -> None:
        self.audio_file = audio_file
        self.fft_size = fft_size
        self.channel = channel
        self.window = _window_values(window, fft_size)
        self.frame_start = max(0, frame_start)
        self.frame_stop = min(
            int(frame_stop) if frame_stop is not None else len(audio_file),
            len(audio_file),
        )
        self.frames = max(0, self.frame_stop - self.frame_start)

    def read(self, start: int, size: int, resize_if_less: bool = False) -> np.ndarray:
        """Read a frame window using the renderer's boundary-padding rules."""
        add_to_start = 0
        add_to_end = 0

        if start < 0:
            if size + start <= 0:
                return np.zeros(size, dtype=np.float64) if resize_if_less else np.array([])
            add_to_start = -start
            read_start = 0
            to_read = size + start
            if to_read > self.frames:
                add_to_end = to_read - self.frames
                to_read = self.frames
        else:
            read_start = start
            to_read = size
            if start + to_read >= self.frames:
                to_read = self.frames - start
                add_to_end = size - to_read

        if to_read <= 0:
            samples: np.ndarray = np.zeros(size, dtype=np.float64) if resize_if_less else np.array([])
        else:
            self.audio_file.seek(self.frame_start + read_start)
            samples = self.audio_file.read(to_read, dtype="float64", always_2d=False)

        samples = _select_channel(samples, self.channel)

        if resize_if_less and (add_to_start > 0 or add_to_end > 0 or samples.shape[0] < size):
            if add_to_start > 0:
                samples = np.concatenate((np.zeros(add_to_start, dtype=np.float64), samples), axis=0)
            if add_to_end > 0:
                resized = np.resize(samples, size)
                resized[size - add_to_end:] = 0
                samples = resized
            elif samples.shape[0] < size:
                resized = np.resize(samples, size)
                resized[samples.shape[0]:] = 0
                samples = resized

        return np.asarray(samples, dtype=np.float64)

    def spectral_centroid(self, seek_point: int, spec_range: float = _SPEC_TOP_DB) -> np.ndarray:
        samples = self.read(seek_point - self.fft_size // 2, self.fft_size, True)
        samples *= self.window
        fft = np.fft.fft(samples)
        spectrum = np.abs(fft[: fft.shape[0] // 2 + 1]) / float(self.fft_size)
        return ((20 * np.log10(spectrum + 1e-30)).clip(-spec_range, 0.0) + spec_range) / spec_range


class _ArrayWindowProcessor:
    """Apply the FFT window processing rules to an in-memory sample array."""

    def __init__(self, samples: np.ndarray, fft_size: int, window: str) -> None:
        self.samples = np.asarray(samples, dtype=np.float64)
        self.fft_size = fft_size
        self.window = _window_values(window, fft_size)
        self.frames = int(self.samples.shape[0])

    def read(self, start: int, size: int, resize_if_less: bool = False) -> np.ndarray:
        add_to_start = 0
        add_to_end = 0

        if start < 0:
            if size + start <= 0:
                return np.zeros(size, dtype=np.float64) if resize_if_less else np.array([])
            add_to_start = -start
            read_start = 0
            to_read = size + start
            if to_read > self.frames:
                add_to_end = to_read - self.frames
                to_read = self.frames
        else:
            read_start = start
            to_read = size
            if start + to_read >= self.frames:
                to_read = self.frames - start
                add_to_end = size - to_read

        if to_read <= 0:
            samples: np.ndarray = np.zeros(size, dtype=np.float64) if resize_if_less else np.array([])
        else:
            samples = self.samples[read_start : read_start + to_read]

        if resize_if_less and (add_to_start > 0 or add_to_end > 0 or samples.shape[0] < size):
            if add_to_start > 0:
                samples = np.concatenate((np.zeros(add_to_start, dtype=np.float64), samples), axis=0)
            if add_to_end > 0:
                resized = np.resize(samples, size)
                resized[size - add_to_end:] = 0
                samples = resized
            elif samples.shape[0] < size:
                resized = np.resize(samples, size)
                resized[samples.shape[0]:] = 0
                samples = resized

        return np.asarray(samples, dtype=np.float64)

    def spectral_centroid(self, seek_point: int, spec_range: float = _SPEC_TOP_DB) -> np.ndarray:
        samples = self.read(seek_point - self.fft_size // 2, self.fft_size, True)
        samples *= self.window
        fft = np.fft.fft(samples)
        spectrum = np.abs(fft[: fft.shape[0] // 2 + 1]) / float(self.fft_size)
        return ((20 * np.log10(spectrum + 1e-30)).clip(-spec_range, 0.0) + spec_range) / spec_range


def generate_spectrogram_png(
    audio_path: str,
    start_time: float,
    end_time: Optional[float],
    min_freq: float,
    max_freq: Optional[float],
    fft_size: int,
    window: str,
    channel: int,
    width_px: int,
    height_px: int,
    apply_frequency_filter: bool = False,
) -> bytes:
    """Generate a spectrogram PNG using the current server-side rendering rules."""
    normalized_window = normalize_window_name(window)
    with sf.SoundFile(audio_path, "r") as audio_file:
        sample_rate = audio_file.samplerate
        frame_start = int(max(0.0, start_time) * sample_rate)
        frame_stop = (
            int(max(start_time, end_time) * sample_rate)
            if end_time is not None
            else len(audio_file)
        )
        frame_stop = max(frame_start, min(frame_stop, len(audio_file)))
        f_max = max_freq if max_freq is not None else sample_rate / 2.0
        if apply_frequency_filter:
            return _render_filtered_palette_spectrogram(
                audio_file=audio_file,
                frame_start=frame_start,
                frame_stop=frame_stop,
                width_px=width_px,
                height_px=height_px,
                fft_size=fft_size,
                min_freq=min_freq,
                max_freq=f_max,
                channel=channel,
                window=normalized_window,
            )
        return _render_palette_spectrogram(
            audio_file=audio_file,
            frame_start=frame_start,
            frame_stop=frame_stop,
            width_px=width_px,
            height_px=height_px,
            fft_size=fft_size,
            min_freq=min_freq,
            max_freq=f_max,
            channel=channel,
            window=normalized_window,
        )


def generate_thumbnail(
    audio_path: str,
    channel_num: int,
    sampling_rate: int,
) -> bytes:
    """Generate the thumbnail spectrogram preview."""
    max_frequency = max(1, int(sampling_rate // 2))
    if channel_num >= 2:
        left_bytes = generate_spectrogram_png(
            audio_path=audio_path,
            start_time=0.0,
            end_time=None,
            min_freq=_THUMB_MIN_FREQ,
            max_freq=max_frequency,
            fft_size=_THUMB_FFT_SIZE,
            window=_THUMB_WINDOW,
            channel=1,
            width_px=_THUMB_WIDTH,
            height_px=_THUMB_HALF_HEIGHT,
        )
        right_bytes = generate_spectrogram_png(
            audio_path=audio_path,
            start_time=0.0,
            end_time=None,
            min_freq=_THUMB_MIN_FREQ,
            max_freq=max_frequency,
            fft_size=_THUMB_FFT_SIZE,
            window=_THUMB_WINDOW,
            channel=2,
            width_px=_THUMB_WIDTH,
            height_px=_THUMB_HALF_HEIGHT,
        )
        annotated_bytes = _annotated_stereo_thumbnail_bytes(
            left_bytes,
            right_bytes,
            max_frequency=max_frequency,
        )
        if annotated_bytes is not None:
            return annotated_bytes
        return _stack_vertically(left_bytes, right_bytes, width=_THUMB_WIDTH, height=_THUMB_HEIGHT)

    raw_bytes = generate_spectrogram_png(
        audio_path=audio_path,
        start_time=0.0,
        end_time=None,
        min_freq=_THUMB_MIN_FREQ,
        max_freq=max_frequency,
        fft_size=_THUMB_FFT_SIZE,
        window=_THUMB_WINDOW,
        channel=0,
        width_px=_THUMB_WIDTH,
        height_px=_THUMB_HEIGHT,
    )
    annotated_bytes = _annotated_mono_thumbnail_bytes(raw_bytes, max_frequency=max_frequency)
    return annotated_bytes if annotated_bytes is not None else raw_bytes


def generate_player_spectrogram(
    audio_path: str,
    *,
    channel_num: int = 1,
    fft_size: int = DETAIL_DEFAULT_FFT_SIZE,
) -> bytes:
    """Generate the upload-time/player static spectrogram preview."""
    render_channel = 1 if channel_num >= 2 else 0
    return generate_spectrogram_png(
        audio_path=audio_path,
        start_time=0.0,
        end_time=None,
        min_freq=DETAIL_DEFAULT_MIN_FREQ,
        max_freq=None,
        fft_size=fft_size,
        window=DETAIL_DEFAULT_WINDOW,
        channel=render_channel,
        width_px=_PLAYER_WIDTH,
        height_px=_PLAYER_HEIGHT,
    )


def normalize_window_name(window: str) -> str:
    """Normalize window aliases to the stored window naming."""
    normalized = (window or DETAIL_DEFAULT_WINDOW).strip().lower()
    if normalized == "hann":
        return "hanning"
    if normalized not in WINDOW_FUNCTIONS:
        raise ValueError(f"Unsupported window function: {window}")
    return normalized


def _select_channel(samples: np.ndarray, channel: int) -> np.ndarray:
    if samples.ndim > 1:
        if channel == 1:
            return np.asarray(samples[:, 0], dtype=np.float64)
        if channel == 2:
            index = 1 if samples.shape[1] > 1 else 0
            return np.asarray(samples[:, index], dtype=np.float64)
        return np.asarray(samples.mean(axis=1), dtype=np.float64)
    return np.asarray(samples, dtype=np.float64)


def _render_palette_spectrogram(
    *,
    audio_file: sf.SoundFile,
    frame_start: int,
    frame_stop: int,
    width_px: int,
    height_px: int,
    fft_size: int,
    min_freq: float,
    max_freq: float,
    channel: int,
    window: str,
) -> bytes:
    processor = _AudioWindowProcessor(
        audio_file,
        fft_size,
        channel,
        window,
        frame_start=frame_start,
        frame_stop=frame_stop,
    )
    return _render_processor_spectrogram(
        processor=processor,
        sample_rate=audio_file.samplerate,
        width_px=width_px,
        height_px=height_px,
        fft_size=fft_size,
        min_freq=min_freq,
        max_freq=max_freq,
    )


def _render_filtered_palette_spectrogram(
    *,
    audio_file: sf.SoundFile,
    frame_start: int,
    frame_stop: int,
    width_px: int,
    height_px: int,
    fft_size: int,
    min_freq: float,
    max_freq: float,
    channel: int,
    window: str,
) -> bytes:
    # Match legacy Utils::filterFrequenciesSound: sox <in> <out> sinc lo-hi
    with tempfile.TemporaryDirectory(prefix="spectrogram-filter-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        source_path = tmp_dir / "source.wav"
        filtered_path = tmp_dir / "filtered.wav"

        audio_file.seek(frame_start)
        raw_samples = audio_file.read(
            max(0, frame_stop - frame_start),
            dtype="float64",
            always_2d=True,
        )
        sf.write(
            str(source_path),
            np.asarray(raw_samples),
            audio_file.samplerate,
            format="WAV",
            subtype="FLOAT",
        )
        apply_sox_sinc_filter(
            source_path,
            filtered_path,
            sample_rate=audio_file.samplerate,
            min_freq=min_freq,
            max_freq=max_freq,
        )
        filtered_samples, _ = sf.read(str(filtered_path), dtype="float64", always_2d=False)
        selected_samples = _select_channel(np.asarray(filtered_samples), channel)
        processor = _ArrayWindowProcessor(selected_samples, fft_size, window)
        return _render_processor_spectrogram(
            processor=processor,
            sample_rate=audio_file.samplerate,
            width_px=width_px,
            height_px=height_px,
            fft_size=fft_size,
            min_freq=min_freq,
            max_freq=max_freq,
        )


def _render_processor_spectrogram(
    *,
    processor: _AudioWindowProcessor | _ArrayWindowProcessor,
    sample_rate: int,
    width_px: int,
    height_px: int,
    fft_size: int,
    min_freq: float,
    max_freq: float,
) -> bytes:
    samples_per_pixel = processor.frames / float(width_px)
    nyquist_freq = (sample_rate / 2) + 0.0
    y_to_bin = _build_y_to_bin(height_px, fft_size, max_freq, min_freq, nyquist_freq)

    image = Image.new("P", (height_px, width_px))
    image.putpalette(_SVT_PALETTE)

    pixels: list[int] = []
    for x in range(width_px):
        seek_point = int(x * samples_per_pixel)
        db_spectrum = processor.spectral_centroid(seek_point)

        for index, alpha in y_to_bin:
            pixels.append(int(((255.0 - alpha) * db_spectrum[index] + alpha * db_spectrum[index + 1])))

        for _ in range(len(y_to_bin), height_px):
            pixels.append(0)

    image.putdata(pixels)
    rotated = image.transpose(Image.ROTATE_90)

    buf = io.BytesIO()
    rotated.save(buf, format="PNG")
    return buf.getvalue()


def build_sox_sinc_frequency_spec(
    sample_rate: int,
    min_freq: float,
    max_freq: float,
) -> str:
    """Build the `sinc lo-hi` band used by legacy SoX frequency filtering."""
    nyquist = float(max(1, sample_rate // 2))
    lo = int(max(0.0, float(min_freq)))
    hi_float = min(float(max_freq), nyquist)
    hi = int(hi_float - 1 if hi_float == nyquist else hi_float)
    if hi < lo:
        hi = lo
    return f"{lo}-{hi}"


def apply_sox_sinc_filter(
    source_path: Path,
    output_path: Path,
    *,
    sample_rate: int,
    min_freq: float,
    max_freq: float,
) -> None:
    """Apply legacy-compatible SoX sinc bandpass filtering."""
    if shutil.which("sox") is None:
        raise RuntimeError("SoX is required for spectrogram frequency filtering")
    frequency_spec = build_sox_sinc_frequency_spec(sample_rate, min_freq, max_freq)
    command = ["sox", str(source_path), str(output_path), "sinc", frequency_spec]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("SoX audio processing timed out") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown SoX error").strip()
        raise RuntimeError(f"SoX audio processing failed: {detail}")


def _build_y_to_bin(
    image_height: int,
    fft_size: int,
    max_freq: float,
    min_freq: float,
    nyquist_freq: float,
) -> list[tuple[int, float]]:
    y_to_bin: list[tuple[int, float]] = []
    for y in range(image_height):
        freq = min_freq + y / (image_height - 1.0) * (max_freq - min_freq)
        fft_bin = freq / nyquist_freq * (fft_size // 2 + 1)
        if fft_bin < fft_size // 2:
            alpha = fft_bin - int(fft_bin)
            y_to_bin.append((int(fft_bin), alpha * 255))
    return y_to_bin


def _window_values(window: str, fft_size: int) -> np.ndarray:
    normalized = normalize_window_name(window)
    if normalized == "bartlett":
        return np.bartlett(fft_size)
    if normalized == "blackman":
        return np.blackman(fft_size)
    if normalized == "hanning":
        return np.hanning(fft_size)
    if normalized == "hamming":
        return np.hamming(fft_size)
    if normalized == "kaiser":
        return np.kaiser(fft_size, _KAISER_BETA)
    raise ValueError(f"Unsupported window function: {window}")


def _stack_vertically(top_bytes: bytes, bottom_bytes: bytes, *, width: int, height: int) -> bytes:
    top = Image.open(io.BytesIO(top_bytes)).convert("RGB")
    bottom = Image.open(io.BytesIO(bottom_bytes)).convert("RGB")

    combined = Image.new("RGB", (width, height))
    combined.paste(top, (0, 0))
    combined.paste(bottom, (0, height // 2))
    return _image_to_png_bytes(combined)


def _image_to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _annotated_mono_thumbnail_bytes(
    spectrogram_bytes: bytes,
    *,
    max_frequency: int,
) -> bytes | None:
    with tempfile.TemporaryDirectory(prefix="spectrogram-thumb-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        source_path = tmp_dir / "small_s1.png"
        output_path = tmp_dir / "thumbnail.png"
        source_path.write_bytes(spectrogram_bytes)
        if not _run_imagemagick_command(
            [
                "convert",
                "-fill",
                "white",
                "-draw",
                f"text 5,15 '{max_frequency} Hz '",
                str(source_path),
                "-quality",
                "10",
                str(output_path),
            ]
        ):
            return None
        return output_path.read_bytes()


def _annotated_stereo_thumbnail_bytes(
    left_bytes: bytes,
    right_bytes: bytes,
    *,
    max_frequency: int,
) -> bytes | None:
    with tempfile.TemporaryDirectory(prefix="spectrogram-thumb-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        left_path = tmp_dir / "sl.png"
        right_path = tmp_dir / "sr.png"
        combined_path = tmp_dir / "sall.png"
        output_path = tmp_dir / "thumbnail.png"
        left_path.write_bytes(left_bytes)
        right_path.write_bytes(right_bytes)
        if not _run_imagemagick_command(
            [
                "montage",
                "-tile",
                "1x2",
                "-mode",
                "Concatenate",
                str(left_path),
                str(right_path),
                str(combined_path),
            ]
        ):
            return None
        if not _run_imagemagick_command(
            [
                "convert",
                "-fill",
                "white",
                "-draw",
                f"text 5,15 '{max_frequency} Hz '",
                "-draw",
                f"text 5,85 '{max_frequency} Hz'",
                "-draw",
                "text 290,15 'L'",
                "-draw",
                "text 290,85 'R'",
                str(combined_path),
                "-quality",
                "10",
                str(output_path),
            ]
        ):
            return None
        return output_path.read_bytes()


def _run_imagemagick_command(command: list[str]) -> bool:
    executable = command[0]
    if shutil.which(executable) is None:
        logger.warning(
            "ImageMagick executable %s is unavailable; using thumbnail without text overlay",
            executable,
        )
        return False
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ImageMagick command timed out: %s", command)
        return False
    if result.returncode != 0:
        logger.warning(
            "ImageMagick command failed: %s",
            (result.stderr or result.stdout or "unknown error").strip(),
        )
        return False
    return True
