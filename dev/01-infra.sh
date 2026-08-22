#!/usr/bin/env bash
# Creates the network and the MariaDB / Redis containers the bench needs.
# Idempotent: re-running leaves existing containers alone.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET"

start() { # start <name> <docker run args...>
  local name=$1; shift
  if docker inspect "$name" >/dev/null 2>&1; then
    docker start "$name" >/dev/null
    echo "= $name (already exists, started)"
  else
    docker run -d --name "$name" --network "$NET" --restart unless-stopped "$@" >/dev/null
    echo "+ $name"
  fi
}

# skip-innodb-read-only-compressed is required by Frappe on MariaDB 10.6+.
start "$DB" \
  -e MARIADB_ROOT_PASSWORD="$DB_ROOT_PASSWORD" \
  -v pulpcrm-mariadb-data:/var/lib/mysql \
  -p 127.0.0.1:3307:3306 \
  mariadb:10.6 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci \
  --skip-character-set-client-handshake \
  --skip-innodb-read-only-compressed

start "$RCACHE" redis:6.2-alpine
start "$RQUEUE" redis:6.2-alpine

echo -n "waiting for mariadb"
for i in $(seq 1 60); do
  if docker exec "$DB" mariadb -uroot -p"$DB_ROOT_PASSWORD" -e "SELECT 1" >/dev/null 2>&1; then
    echo " ok"; exit 0
  fi
  echo -n "."; sleep 2
done
echo " TIMED OUT"; exit 1
