#!/usr/bin/env bash
# Fetches Frappe CRM and frappe_whatsapp into the bench (source only).
#
# CRM is pinned to `main`, NOT the repo default `develop`. develop is the
# CRM 2.0 line; crm-fork/0001-baton-integration.patch only applies to the 1.x
# frontend (verified: it fails on develop, applies clean on main/v1.81.2).
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

docker exec -i -e NODE_VERSION="$NODE_VERSION" -e CRM_BRANCH="$CRM_BRANCH" \
  "$BENCH" bash -s <<'INNER'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
source ~/.nvm/nvm.sh && nvm use "$NODE_VERSION" >/dev/null
cd /workspace/frappe-bench

[ -d apps/crm ] || bench get-app crm https://github.com/frappe/crm.git --branch "$CRM_BRANCH"
[ -d apps/frappe_whatsapp ] || bench get-app https://github.com/shridarpatil/frappe_whatsapp.git

# Guard against a stale checkout from an earlier run on the wrong branch.
cd apps/crm
if [ "$(git rev-parse --abbrev-ref HEAD)" != "$CRM_BRANCH" ]; then
  echo "! apps/crm is on $(git rev-parse --abbrev-ref HEAD), switching to $CRM_BRANCH"
  git fetch --depth 1 upstream "$CRM_BRANCH:$CRM_BRANCH" 2>/dev/null || true
  git checkout "$CRM_BRANCH"
fi
INNER
