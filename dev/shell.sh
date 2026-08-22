#!/usr/bin/env bash
# Interactive shell in the bench container, already in the bench dir with the
# right node on PATH. Run bench commands from here, e.g.
#   bench --site crm.localhost run-tests --app baton
#   bench --site crm.localhost migrate
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh
docker exec -it -e NODE_VERSION="$NODE_VERSION" "$BENCH" bash -c '
  export PATH="$HOME/.local/bin:$PATH"
  source ~/.nvm/nvm.sh && nvm use "$NODE_VERSION" >/dev/null
  cd /workspace/frappe-bench && exec bash'
