#!/usr/bin/env bash
# Run this after `git pull`. Picks up new Python modules, new schema, new
# frontend pages and new hooks, then restarts and runs the tests.
#
# Use up.sh instead if the stack has never been built on this machine.
set -euo pipefail
cd "$(dirname "$0")"

for step in 01-infra 02-bench-container 06-install-apps 07-baton-setup 08-crm-frontend; do
  echo
  echo "==> $step"
  bash "./$step.sh"
done

echo
echo "==> restart"
bash ./restart.sh

echo
echo "==> tests"
bash ./test.sh

source ./env.sh
echo
echo "PulpCRM/Baton rebuilt:  http://$SITE:8000/crm"
