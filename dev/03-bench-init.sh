#!/usr/bin/env bash
# bench init: clones frappe, builds the venv and the base assets. Slow.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

docker exec -i -e FRAPPE_BRANCH="$FRAPPE_BRANCH" -e PY="$PY" -e NODE_VERSION="$NODE_VERSION" \
  "$BENCH" bash -s <<'INNER'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
source ~/.nvm/nvm.sh && nvm use "$NODE_VERSION" >/dev/null
cd /workspace
if [ -d frappe-bench ]; then echo "= frappe-bench already exists"; exit 0; fi
# --skip-redis-config-generation: redis lives in its own containers, not here.
bench init --frappe-branch "$FRAPPE_BRANCH" --python "$PY" --skip-redis-config-generation frappe-bench
INNER
