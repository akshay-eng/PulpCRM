#!/usr/bin/env bash
# Applies Baton's changes to the CRM frontend and rebuilds CRM's assets.
#
# The patch itself already adds the @vue-flow/* deps to frontend/package.json,
# so a plain `yarn install` is enough --- no `yarn add`, which would re-resolve
# and drift from the pinned ranges.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

docker exec -i -e NODE_VERSION="$NODE_VERSION" "$BENCH" bash -s <<'INNER'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
source ~/.nvm/nvm.sh && nvm use "$NODE_VERSION" >/dev/null
cd /workspace/frappe-bench/apps/crm

FORK=/workspace/PulpCRM/crm-fork
PATCH="$FORK/0001-baton-integration.patch"

# Reset the files the patch owns back to pristine CRM before applying. Checking
# "already applied?" is not enough: when the patch itself changes (a new page,
# a new sidebar entry) the old version is applied and the new one fits neither
# forwards nor backwards. These three files are managed entirely by the patch,
# so discarding local state in them is safe and makes re-runs deterministic.
TOUCHED=$(git apply --numstat "$PATCH" | cut -f3)
git checkout -- $TOUCHED
git apply "$PATCH"
echo "+ applied 0001-baton-integration.patch ($(echo "$TOUCHED" | wc -l) files)"

cp -r "$FORK/new-files/frontend/src/." frontend/src/
echo "+ copied Baton frontend files"

# Rebuilding CRM's bundle takes ~2 minutes, so only do it when the built output
# is actually older than the Baton frontend sources (or missing entirely).
BUILT=crm/www/crm.html
NEWEST=$(find "$FORK" $TOUCHED -type f -newer "$BUILT" 2>/dev/null | head -1 || true)

if [ -f "$BUILT" ] && [ -z "$NEWEST" ]; then
  echo "= CRM assets already up to date, skipping build"
  exit 0
fi

cd frontend && yarn install --silent
cd /workspace/frappe-bench && bench build --app crm
INNER
