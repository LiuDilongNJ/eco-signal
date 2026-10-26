"""Prepare persistent Insects model files before the worker starts."""

import fcntl
import logging
import os
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path("/models/insects")
MODEL_MODE_FILE = Path("/app/models/insects/.mode")
LOCAL_MODEL_DIR = Path("/source/insects")
MODEL_MODES = {"download", "local", "disabled"}
DEFAULT_ATTEMPTS = 3
DEFAULT_RETRY_DELAY_SECONDS = 5.0

# Candidate cache paths from previous downloads
CACHE_SEARCH_PATHS = [
    Path("/app/sounds/.insects_model_backup"),
    Path.home() / ".cache" / "torch" / "hub" / "autrainer" / "AlexanderGbd--insects-base-cnn10-96k-t--main",
    Path("/root/.cache/torch/hub/autrainer/AlexanderGbd--insects-base-cnn10-96k-t--main"),
    Path("/var/www/.cache/torch/hub/autrainer/AlexanderGbd--insects-base-cnn10-96k-t--main"),
]

REQUIRED_FILES = [
    "model.yaml",
    "file_handler.yaml",
    "target_transform.yaml",
    "inference_transform.yaml",
    "_best/model.pt",
]


class InsectsModelSetupError(RuntimeError):
    """Raised when insects model files cannot be prepared or validated."""


def error_reason(error: BaseException) -> str:
    seen = set()
    while id(error) not in seen:
        seen.add(id(error))
        cause = error.__cause__ or error.__context__
        if cause is None or id(cause) in seen:
            break
        error = cause
    return f"{type(error).__name__}: {error}"


def installed_model_mode() -> str:
    return MODEL_MODE_FILE.read_text().strip() if MODEL_MODE_FILE.is_file() else "download"


def prepare_image_model(model_dir: Path, mode: str, source: Path = LOCAL_MODEL_DIR) -> None:
    if mode not in MODEL_MODES:
        raise InsectsModelSetupError("INSECTS_MODEL_MODE must be download, local or disabled")
    model_dir.mkdir(parents=True, exist_ok=True)
    if mode == "disabled":
        logger.warning("Insects recognition is disabled")
    elif mode == "local":
        if not check_insects_files(source):
            raise InsectsModelSetupError("Local insects model is incomplete; provide all required non-empty files in backend/model-assets/insects")
        shutil.copytree(source, model_dir, dirs_exist_ok=True)
        if not check_insects_files(model_dir):
            raise InsectsModelSetupError("Local insects model file validation failed")
    else:
        prepare_insects_model(model_dir)
    (model_dir / ".mode").write_text(mode + "\n")


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


def check_insects_files(model_dir: Path = DEFAULT_MODEL_DIR) -> bool:
    """Check if all required model files exist in model_dir."""
    if not model_dir.is_dir():
        return False
    return all(
        (model_dir / rel_path).is_file() and (model_dir / rel_path).stat().st_size > 0
        for rel_path in REQUIRED_FILES
    )


def _copy_from_cache(target_dir: Path) -> bool:
    """Attempt to populate target_dir from existing local cache directories."""
    for cache_dir in CACHE_SEARCH_PATHS:
        if cache_dir.is_dir() and (cache_dir / "model.yaml").is_file() and (cache_dir / "_best" / "model.pt").is_file():
            logger.info("Copying insects model from local cache: %s -> %s", cache_dir, target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            for item in cache_dir.iterdir():
                dest = target_dir / item.name
                if item.is_dir():
                    if not dest.exists():
                        shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            return check_insects_files(target_dir)
    return False


def _download_insects_model(target_dir: Path) -> None:
    """Download model using autrainer HubModelPath into target_dir."""
    from autrainer.serving.model_paths import HubModelPath

    hub_path = HubModelPath("hf:AlexanderGbd/insects-base-cnn10-96k-t", trust_remote=False)
    local_path = hub_path.create_model_path()
    if Path(local_path) != target_dir:
        # Copy downloaded files to target_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in Path(local_path).iterdir():
            dest = target_dir / item.name
            if item.is_dir():
                if not dest.exists():
                    shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)


def prepare_insects_model(
    model_dir: Path = DEFAULT_MODEL_DIR,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    check_model: Callable[[Path], bool] = check_insects_files,
    download_model: Callable[[Path], None] = _download_insects_model,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Ensure the configured insects model is complete, returning whether files were copied/downloaded."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    with model_setup_lock(model_dir):
        if check_model(model_dir):
            logger.info("Insects model files are ready in %s", model_dir)
            return False

        # First try copying from local torch cache without internet access
        if _copy_from_cache(model_dir):
            logger.info("Insects model files restored from local cache")
            return True

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                logger.info("Preparing Insects model files (attempt %s/%s)", attempt, attempts)
                download_model(model_dir)
                if check_model(model_dir):
                    logger.info("Insects model files are ready")
                    return True
                raise InsectsModelSetupError("Insects model file validation failed")
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    logger.warning("Insects model preparation failed; retrying: %s", error_reason(exc))
                    sleep(retry_delay_seconds * attempt)

        raise InsectsModelSetupError(
            f"Insects model download or validation failed: {error_reason(last_error)}"
        ) from last_error


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    model_dir = Path(os.environ.get("INSECTS_MODEL_DIR", DEFAULT_MODEL_DIR))
    try:
        prepare_image_model(model_dir, os.environ.get("INSECTS_MODEL_MODE", "download"))
    except (InsectsModelSetupError, OSError):
        logger.exception("Insects model preparation failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
