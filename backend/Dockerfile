# Stage 1: Builder
ARG PYTHON_BASE_IMAGE=python:3.12-slim
FROM ${PYTHON_BASE_IMAGE} AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install uv from PyPI instead of GHCR to avoid registry EOF failures.
RUN python -m pip install --no-cache-dir "uv==0.5.11"

# Keep downloaded .deb packages so the apt cache mount below can persist them across builds
RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

# Install system dependencies required for building/downloading
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libjpeg62-turbo \
    libopenjp2-7 \
    curl \
    imagemagick \
    sox \
    libsox-fmt-all \
    lame \
    ca-certificates \
    gcc \
    g++ \
    python3-dev \
    libgdal-dev \
    gdal-bin

RUN sox --version && lame --version | head -n 1

# Install dependencies (frozen, deps only)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Download and validate the BirdNET model while the dependency layer is built.
RUN --mount=type=cache,id=birdnet-v2.4-model,target=/root/.cache/birdnet-model,sharing=locked \
    set -eux; \
    checkpoint_dir="$(.venv/bin/python -c 'from birdnet_analyzer import config; print(config.SCRIPT_DIR + "/checkpoints")')"; \
    if ! .venv/bin/python -c \
        'import sys, zipfile; path="/root/.cache/birdnet-model/V2.4.zip"; sys.exit(0 if zipfile.is_zipfile(path) and zipfile.ZipFile(path).testzip() is None else 1)'; then \
        curl --fail --location --continue-at - --retry 20 --retry-all-errors --retry-delay 5 --connect-timeout 30 \
            --output /root/.cache/birdnet-model/V2.4.zip \
            https://tuc.cloud/index.php/s/886x39f5N3sdsAM/download/V2.4.zip; \
    fi; \
    BIRDNET_CHECKPOINT_DIR="${checkpoint_dir}" .venv/bin/python -c \
        'import os, zipfile; zipfile.ZipFile("/root/.cache/birdnet-model/V2.4.zip").extractall(os.environ["BIRDNET_CHECKPOINT_DIR"])'; \
    .venv/bin/python -c \
        "from birdnet_analyzer.utils import check_birdnet_files; assert check_birdnet_files(), 'BirdNET model validation failed'"

# The project package must exist before installing it via editable build.
COPY ./app /app/app

# Sync project (installs the project package itself)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev

# Stage 2: Runtime
FROM ${PYTHON_BASE_IMAGE} AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

WORKDIR /app

# Keep downloaded .deb packages so the apt cache mount below can persist them across builds
RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

# Install runtime system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libjpeg62-turbo \
    libopenjp2-7 \
    curl \
    imagemagick \
    sox \
    libsox-fmt-all \
    lame \
    libgdal-dev \
    gdal-bin

RUN sox --version && lame --version | head -n 1

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv
# Copy application code
COPY ./scripts /app/scripts
COPY ./pyproject.toml ./uv.lock ./alembic.ini /app/
COPY ./app /app/app

# Ensure entrypoint is executable
RUN chmod +x /app/scripts/entrypoint.sh

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["fastapi", "run", "--workers", "4", "app/main.py"]
