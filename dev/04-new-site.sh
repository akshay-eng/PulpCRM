#!/usr/bin/env bash
# Points the bench at the containerised MariaDB/Redis, then creates the site.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

docker exec -i -e SITE="$SITE" -e DB="$DB" -e RCACHE="$RCACHE" -e RQUEUE="$RQUEUE" \
  -e DB_ROOT_PASSWORD="$DB_ROOT_PASSWORD" -e ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  -e NODE_VERSION="$NODE_VERSION" "$BENCH" bash -s <<'INNER'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
source ~/.nvm/nvm.sh && nvm use "$NODE_VERSION" >/dev/null
cd /workspace/frappe-bench

bench set-config -g db_host "$DB"
bench set-config -g redis_cache "redis://$RCACHE:6379"
bench set-config -g redis_queue "redis://$RQUEUE:6379"
bench set-config -g redis_socketio "redis://$RQUEUE:6379"
bench set-config -g developer_mode 1

if [ -d "sites/$SITE" ]; then echo "= site $SITE already exists"; exit 0; fi

# user-host-login-scope=% : bench and db are separate containers, so the site's
# db user must be allowed to connect from any host, not just localhost.
bench new-site "$SITE" \
  --db-root-username root \
  --db-root-password "$DB_ROOT_PASSWORD" \
  --admin-password "$ADMIN_PASSWORD" \
  --mariadb-user-host-login-scope='%' \
  --set-default
INNER
