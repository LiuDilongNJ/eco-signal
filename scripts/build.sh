#! /usr/bin/env sh

# Exit in case of error
set -e

: "${TAG?Variable not set}"
: "${FRONTEND_ENV:=production}"

export TAG FRONTEND_ENV

docker compose -f docker-compose.yml build
