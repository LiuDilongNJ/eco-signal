#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python app/initial_data.py

# Auto-import GADM into geo_db if ADM tables are missing/empty
python scripts/setup_geo_data.py
