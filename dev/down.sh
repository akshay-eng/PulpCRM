#!/usr/bin/env bash
# Stops the containers. Nothing is deleted: the bench, the site and the MariaDB
# volume all survive, so `up.sh` brings the same state back.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh
docker stop "$BENCH" "$RQUEUE" "$RCACHE" "$DB" >/dev/null
echo "stopped"
