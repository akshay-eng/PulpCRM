#!/usr/bin/env bash
# Tails the bench processes (web, socketio, watch, schedule, worker).
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh
docker exec "$BENCH" tail -f -n 100 /workspace/frappe-bench/logs/bench-start.log
