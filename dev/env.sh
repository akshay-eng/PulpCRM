# Shared settings for the Baton dev bench (sourced by the other scripts).
# Bash, not fish — run these with bash dev/<script>.sh

NET=pulpcrm-net
DB=pulpcrm-mariadb
RCACHE=pulpcrm-redis-cache
RQUEUE=pulpcrm-redis-queue
BENCH=pulpcrm-bench

DB_ROOT_PASSWORD=123
ADMIN_PASSWORD=admin
SITE=crm.localhost

# Host directory that holds both the PulpCRM repo and the generated frappe-bench.
WORKSPACE=/home/ppv/Projects/pulpcrm

# Frappe v15 — Baton is written against it (apps/baton/pyproject.toml).
FRAPPE_BRANCH=version-15
# The image defaults to python3.14 / node24; Frappe v15 needs older ones.
PY=/usr/bin/python3.11
NODE_VERSION=22

# CRM 1.x line — the Baton frontend patch does not apply to `develop` (CRM 2.0).
CRM_BRANCH=main
