#!/usr/bin/env bash
# Installs crm + frappe_whatsapp into the site, then wires in Baton.
#
# Baton is symlinked rather than copied (the README says `cp -r`) so the repo
# stays the single source of truth: edit PulpCRM/apps/baton and the bench sees
# it immediately.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

docker exec -i -e SITE="$SITE" -e NODE_VERSION="$NODE_VERSION" "$BENCH" bash -s <<'INNER'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
source ~/.nvm/nvm.sh && nvm use "$NODE_VERSION" >/dev/null
cd /workspace/frappe-bench

installed() { bench --site "$SITE" list-apps 2>/dev/null | awk '{print $1}' | grep -qx "$1"; }

installed crm             || bench --site "$SITE" install-app crm
installed frappe_whatsapp || bench --site "$SITE" install-app frappe_whatsapp

# --- baton -----------------------------------------------------------------
if [ ! -e apps/baton ]; then
  ln -s /workspace/PulpCRM/apps/baton apps/baton
  echo "+ symlinked apps/baton -> PulpCRM/apps/baton"
fi
./env/bin/python -m pip install --quiet -e apps/baton

# bench maintains sites/apps.txt only for apps it fetched itself, so a
# symlinked app has to be registered by hand or install-app refuses it.
if ! grep -qx baton sites/apps.txt; then
  # the file has no trailing newline, so add one before appending
  printf '\nbaton\n' >> sites/apps.txt
  echo "+ registered baton in sites/apps.txt"
fi

installed baton || bench --site "$SITE" install-app baton
INNER
