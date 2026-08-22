#!/usr/bin/env bash
# Creates Baton's DocTypes and settings fields. These are built in code (see
# apps/baton/baton/setup*.py) rather than checked-in JSON, which needs
# developer_mode on (04-new-site.sh sets it).
#
# Order matters: `setup` creates Baton Settings, and later phases add fields to
# it. Newer phases expose `install()` where the original ones expose
# `install_all()`, so pick whichever the module actually defines.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

PHASES="setup setup_phase1 setup_phase3 setup_phase3b setup_phase4 setup_openwa setup_runtime setup_builder setup_agent setup_scheduling setup_bots setup_templates"

# Fail loudly if the repo grew a setup module this script doesn't know about,
# rather than silently skipping its schema.
for f in ../apps/baton/baton/setup*.py; do
  mod=$(basename "$f" .py)
  case " $PHASES " in
    *" $mod "*) ;;
    *) echo "! unknown setup module '$mod' - add it to PHASES in $0" >&2; exit 1 ;;
  esac
done

docker exec -i -e SITE="$SITE" -e PHASES="$PHASES" "$BENCH" bash -s <<'INNER'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd /workspace/frappe-bench

for phase in $PHASES; do
  src="apps/baton/baton/$phase.py"
  if grep -q "^def install_all" "$src"; then fn=install_all; else fn=install; fi
  echo "--- baton.$phase.$fn ---"
  bench --site "$SITE" execute "baton.$phase.$fn"
done

bench --site "$SITE" migrate
INNER
