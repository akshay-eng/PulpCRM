#!/usr/bin/env bash
# Starts the bench (web + socketio + watch + scheduler + worker) inside the
# container, detached. Logs land in frappe-bench/logs/bench-start.log.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

# New Frappe sites ship with the scheduler off; Baton's durable waits,
# follow-up ladder and cooldown review all run from scheduler_events.
docker exec -e SITE="$SITE" "$BENCH" bash -c '
  export PATH="$HOME/.local/bin:$PATH"
  cd /workspace/frappe-bench && bench --site "$SITE" enable-scheduler' >/dev/null 2>&1 || true

if docker exec "$BENCH" pgrep -f "honcho start" >/dev/null 2>&1; then
  echo "= bench already running"
else
  docker exec -d -e NODE_VERSION="$NODE_VERSION" "$BENCH" bash -c '
    export PATH="$HOME/.local/bin:$PATH"
    source ~/.nvm/nvm.sh && nvm use "$NODE_VERSION" >/dev/null
    cd /workspace/frappe-bench
    exec bench start >logs/bench-start.log 2>&1'
  echo "+ bench start (detached)"
fi

echo -n "waiting for http"
for i in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: $SITE" http://127.0.0.1:8000/crm 2>/dev/null || true)
  if [ "$code" != "000" ] && [ -n "$code" ]; then echo " ok (HTTP $code)"; exit 0; fi
  echo -n "."; sleep 2
done
echo " TIMED OUT - see frappe-bench/logs/bench-start.log"; exit 1
