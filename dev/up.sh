#!/usr/bin/env bash
# One command to bring the whole stack up from nothing.
# Safe to re-run: every step is idempotent.
set -euo pipefail
cd "$(dirname "$0")"

for step in 01-infra 02-bench-container 03-bench-init 04-new-site \
            05-get-apps 06-install-apps 07-baton-setup 08-crm-frontend \
            10-dev-config 09-start; do
  echo
  echo "==> $step"
  bash "./$step.sh"
done

source ./env.sh
echo
echo "PulpCRM/Baton is up:  http://$SITE:8000/crm"
echo "  login: Administrator / $ADMIN_PASSWORD"
