#!/usr/bin/env bash
# Runs Baton's test suite (64 tests).
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh
docker exec -e SITE="$SITE" "$BENCH" bash -c '
  export PATH="$HOME/.local/bin:$PATH"
  cd /workspace/frappe-bench
  bench --site "$SITE" set-config allow_tests true >/dev/null 2>&1 || true
  bench --site "$SITE" run-tests --app baton'
