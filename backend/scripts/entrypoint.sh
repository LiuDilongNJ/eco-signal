#!/usr/bin/env bash

set -e

if [ "${PROMETHEUS_MULTIPROC_CLEANUP:-false}" = "true" ]; then
    mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
    find "$PROMETHEUS_MULTIPROC_DIR" -mindepth 1 -maxdepth 1 -type f -delete
fi

# Run prestart script (migrations, initial data, fdw setup)
# This is now part of the container startup instead of a separate service
if [ "$SKIP_PRESTART" != "true" ]; then
    echo "🚀 Running prestart script (migrations, initial data, FDW setup)..."
    bash /app/scripts/prestart.sh
else
    echo "⏭️ Skipping prestart script (SKIP_PRESTART is set to true)"
fi

# Execute the passed command
echo "🚀 Starting application command: $@"
exec "$@"
