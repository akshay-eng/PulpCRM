#!/usr/bin/env bash
# Clears Frappe's caches and restarts the bench processes. Needed after pulling
# code that changes hooks.py --- hooks are read once at boot and cached, so a
# running worker keeps the old ones.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

docker exec -e SITE="$SITE" "$BENCH" bash -c '
  export PATH="$HOME/.local/bin:$PATH"
  cd /workspace/frappe-bench
  bench --site "$SITE" clear-cache' >/dev/null
echo "+ cleared cache"

docker exec "$BENCH" pkill -f "honcho start" >/dev/null 2>&1 || true
sleep 2
docker exec "$BENCH" pkill -f "bench (serve|socketio|watch|schedule|worker)" >/dev/null 2>&1 || true
sleep 1
echo "+ stopped bench"

bash ./09-start.sh
