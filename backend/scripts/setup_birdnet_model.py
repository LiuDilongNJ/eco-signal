"""Prepare persistent BirdNET model files before the worker starts."""

import fcntl
import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from birdnet_analyzer.utils import check_birdnet_files, ensure_model_exists

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("/models/birdnet")
DEFAULT_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 5.0


class ModelSetupError(RuntimeError):
    """Raised when model files cannot be prepared or validated."""


@contextmanager
def model_setup_lock(model_dir: Path) -> Iterator[None]:
    """Serialize model preparation across worker processes sharing a volume."""
    model_dir.mkdir(parents=True, exist_ok=True)
    lock_path = model_dir / ".setup.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def prepare_birdnet_model(
    model_dir: Path = DEFAULT_MODEL_DIR,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    check_model: Callable[[], bool] = check_birdnet_files,
    download_model: Callable[[], None] = ensure_model_exists,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Ensure the configured model is complete, returning whether it was downloaded."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    with model_setup_lock(model_dir):
        if check_model():
            logger.info("BirdNET model files are ready")
            return False

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                logger.info("Preparing BirdNET model files (attempt %s/%s)", attempt, attempts)
                download_model()
                if check_model():
                    logger.info("BirdNET model files are ready")
                    return True
                raise ModelSetupError("BirdNET model file validation failed")
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    logger.warning("BirdNET model preparation failed; retrying")
                    sleep(retry_delay_seconds * attempt)

        raise ModelSetupError("BirdNET model files could not be prepared") from last_error


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    model_dir = Path(os.environ.get("BIRDNET_MODEL_DIR", DEFAULT_MODEL_DIR))
    try:
        prepare_birdnet_model(model_dir)
    except (ModelSetupError, OSError):
        logger.exception("BirdNET model preparation failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
