# Running PulpCRM / Baton locally

A containerised Frappe v15 bench with `crm` + `frappe_whatsapp` + `baton`
installed, driven by the scripts in this directory.

## Why containers

This machine's toolchain can't build Frappe v15 directly:

| | host has | Frappe v15 needs |
|---|---|---|
| Python | 3.14.6 | 3.10–3.12 |
| Node | 26.4.0 | 18–22 |
| MariaDB | not installed | required |
| Redis | not installed | required |
| wkhtmltopdf | not installed | required |

The `frappe/bench` image ships all of it, so the bench runs there. The bench
directory itself lives on the **host** at `../../frappe-bench` (bind-mounted to
`/workspace`), so you can read and edit everything from your editor.

## Quick start

```bash
bash dev/up.sh
```

Then open **http://crm.localhost:8000/crm** — `Administrator` / `admin`.

First run takes 20–30 minutes (clones Frappe + CRM, builds the venv and the
frontend bundle). Re-runs take seconds: every step is idempotent and the
frontend build is skipped when nothing changed.

## Scripts

| Script | What it does |
|---|---|
| `up.sh` | Runs everything below in order. Start here on a fresh machine. |
| `rebuild.sh` | **Run this after `git pull`.** Picks up new modules, schema, pages and hooks, restarts, runs the tests. |
| `restart.sh` | Clears caches and restarts the bench. Needed after `hooks.py` changes. |
| `down.sh` | Stops the containers. Deletes nothing. |
| `test.sh` | Baton's 64 tests. |
| `shell.sh` | Interactive shell in the bench container. |
| `logs.sh` | Tails web / socketio / scheduler / worker. |
| `env.sh` | Shared settings (site name, passwords, pinned versions). |
| `01-infra` | Network + MariaDB + two Redis containers. |
| `02-bench-container` | The long-lived bench toolchain container. |
| `03-bench-init` | `bench init` on Frappe `version-15`. |
| `04-new-site` | Points bench at the containerised DB/Redis, creates the site. |
| `05-get-apps` | Fetches Frappe CRM and `frappe_whatsapp`. |
| `06-install-apps` | Installs all three apps into the site. |
| `07-baton-setup` | Baton's ten setup phases + `migrate`. Fails loudly if the repo grows a `setup*.py` it doesn't know about. |
| `08-crm-frontend` | Applies `crm-fork/` and rebuilds CRM's assets. |
| `09-start` | Enables the scheduler, starts `bench start`. |
| `10-dev-config` | Seeds the placeholder Meta app secret. |

## Layout

```
pulpcrm/
├── PulpCRM/            <- this repo (bind-mounted at /workspace/PulpCRM)
│   ├── apps/baton/     <- symlinked into the bench; edit here, bench sees it
│   └── dev/            <- these scripts
└── frappe-bench/       <- generated, NOT in this repo
    └── apps/baton -> /workspace/PulpCRM/apps/baton
```

Containers: `pulpcrm-bench`, `pulpcrm-mariadb`, `pulpcrm-redis-cache`,
`pulpcrm-redis-queue`, all on the `pulpcrm-net` network. Ports are published on
loopback only (8000 web, 9000 socketio, 3307 MariaDB).

## Where this differs from the root README's install steps

Following the root README verbatim does not produce a working site. The
differences, and why:

1. **CRM must be pinned to `main`.** `bench get-app crm` defaults to the repo's
   default branch, `develop` (CRM 2.0). `crm-fork/0001-baton-integration.patch`
   does not apply there — it fails on `frontend/package.json` and
   `frontend/src/router.js`. It applies cleanly to `main` (v1.81.2), which is
   what `05-get-apps.sh` pins.

2. **Baton is symlinked, not `cp -r`'d,** so the repo stays the single source of
   truth. A side effect: `bench` only maintains `sites/apps.txt` for apps it
   fetched itself, so `baton` has to be appended there by hand or
   `install-app` fails with `App baton not in apps.txt`.

3. **The scheduler must be enabled.** New Frappe sites ship with it off, and
   Baton's durable waits, follow-up ladder and cooldown review all run from
   `scheduler_events`. `09-start.sh` runs `enable-scheduler`.

4. **A Meta app secret must exist.** Baton verifies inbound WhatsApp webhooks
   and fails closed with no secret, so the inbound path is dead without one and
   `baton.tests.test_webhook` fails. `10-dev-config.sh` seeds a placeholder —
   **replace it** with the real App Secret before pointing real webhooks here.

5. **The root README's schema block is well behind the code.** It lists five
   `setup_*` phases; there are now ten:

   ```
   setup  setup_phase1  setup_phase3  setup_phase3b  setup_phase4
   setup_openwa  setup_runtime  setup_builder  setup_agent
   setup_scheduling  setup_templates
   ```

   A fresh install done by hand from the root README gets no OpenWA fields, no
   triggers table, no agents, no scheduling and no starter automations.
   `07-baton-setup.sh` runs all of them and **fails loudly** if the repo grows
   another `setup*.py` that isn't in its list. Note they are not uniform: some
   expose `install_all()`, some only `install()`, and the script picks whichever
   the module actually defines.

6. **Non-login shells.** The `frappe/bench` image's `~/.bash_logout` ends in a
   failing `&&` chain, which under `set -e` makes a login shell exit 1 even when
   the script succeeded. The scripts use `bash -s` with an explicit `PATH`.

## Known gaps

- **`croniter` is an undeclared dependency.** `baton/workflow/scheduler.py`
  imports it but `apps/baton/pyproject.toml` lists no dependencies. It resolves
  only because Frappe happens to ship `croniter` itself. Worth adding
  explicitly before that stops being true.
- **Two console 417s on every page load**, from
  `frappe.utils.telemetry.pulse.client.boot_config`. CRM `main` calls a
  telemetry endpoint that Frappe v15.118.0 doesn't have. Upstream version skew,
  unrelated to Baton, and harmless.
- **Hooks are cached at boot.** Pulling a change to `hooks.py` (as the OpenWA
  commit did, adding `override_doctype_class`) has no effect on running workers
  until `restart.sh`. `rebuild.sh` does this for you.
- **Baton ships switched off, and should stay that way in this site.**
  `ai_enabled=0`, `openwa_enabled=0`, WhatsApp in Draft, and both starter
  automations disabled. Some tests flip these; they restore them, but if a run
  is interrupted check `Baton Settings` before assuming the site is idle.
- **The test suite commits, so it cannot rely on rollback.** Leads, events,
  agents, holds and workflows created by tests are cleaned up explicitly in
  `tearDownModule` / `_delete_test_workflows`. If you add a fixture that
  commits, clean it up too or it accumulates in the site on every run.
- **`bench start` doesn't survive a reboot.** The containers restart, but the
  bench processes are started via `docker exec`. Re-run `dev/09-start.sh`.
