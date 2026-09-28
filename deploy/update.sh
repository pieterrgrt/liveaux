#!/usr/bin/env bash
# Pull the latest code and restart liveaux. Run from the project folder on the server.
set -euo pipefail
git pull --ff-only
docker compose up -d --build
docker compose ps
