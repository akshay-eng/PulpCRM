#!/usr/bin/env bash
# Dev-only seed values.
#
# meta_app_secret: Baton verifies inbound WhatsApp webhooks against Meta's
# X-Hub-Signature-256 and FAILS CLOSED when no secret is set, so without one the
# inbound webhook path is dead and baton.tests.test_webhook fails. The value set
# here is a PLACEHOLDER - replace it with the real App Secret from the Meta app
# dashboard (Baton Settings -> Meta) before pointing real webhooks at this site.
set -euo pipefail
cd "$(dirname "$0")"
source ./env.sh

docker exec -i -e SITE="$SITE" "$BENCH" bash -s <<'INNERSH'
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
# `bench console` ignores piped stdin, so drive frappe directly instead.
cd /workspace/frappe-bench/sites
../env/bin/python - "$SITE" <<'PYEOF'
import sys
import frappe

frappe.init(site=sys.argv[1])
frappe.connect()

s = frappe.get_doc("Baton Settings")
if s.get_password("meta_app_secret", raise_exception=False):
    print("= meta_app_secret already set")
else:
    s.meta_app_secret = "dev-placeholder-not-a-real-meta-app-secret"
    s.save(ignore_permissions=True)
    frappe.db.commit()
    print("+ set placeholder meta_app_secret")
PYEOF
INNERSH
