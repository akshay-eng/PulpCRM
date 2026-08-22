#!/usr/bin/env bash
# Long-lived container that holds the bench toolchain (python3.11, node, yarn,
# wkhtmltopdf). The bench itself lives on the host at $WORKSPACE/frappe-bench,
# bind-mounted in, so you can read and edit it from your editor.
#
# Ports are bound on both loopback families: `crm.localhost` resolves to ::1
# on this box, so an IPv4-only binding would leave that hostname unreachable.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

if docker inspect "$BENCH" >/dev/null 2>&1; then
  docker start "$BENCH" >/dev/null
  echo "= $BENCH (already exists, started)"
  exit 0
fi

docker run -d --name "$BENCH" --network "$NET" --restart unless-stopped \
  -v "$WORKSPACE":/workspace \
  -w /workspace \
  -p 127.0.0.1:8000:8000 -p '[::1]:8000:8000' \
  -p 127.0.0.1:9000:9000 -p '[::1]:9000:9000' \
  -p 127.0.0.1:8080:8080 \
  --entrypoint bash \
  frappe/bench:latest -c 'sleep infinity' >/dev/null
echo "+ $BENCH"
