"""Atomic ownership of a workflow run.

Every path that wakes a parked run -- the scheduler's timeout sweep, an inbound
customer reply, the stale-run sweeper -- races the others for the same row.
They all claim through here.

Why a token rather than a rowcount: `frappe.db.sql` returns () for any statement
with no cursor description, which includes every UPDATE (see
frappe/database/database.py, `if not self._cursor.description: return ()`). So
the number of rows affected simply is not available from the return value, and
`if not updated: continue` -- the obvious-looking guard -- is always true. We
write a token under a conditional WHERE and read it back instead: if the token
we read is ours, we won.

`frappe.db._cursor.rowcount` would be cheaper, but it reaches into a private
attribute of whichever DB driver is loaded. The read-back is one indexed SELECT
and works the same on MariaDB and Postgres.
"""

import frappe
from frappe.utils import now_datetime


def claim_run(run_name, expect="Waiting"):
    """Take ownership of a run, moving it `expect` -> Running.

    Returns True if this caller won the claim. A False means someone else got
    there first and this caller must do nothing at all -- not even log.
    """
    token = frappe.generate_hash(length=16)
    frappe.db.sql(
        """UPDATE `tabBaton Workflow Run`
           SET status = 'Running', claim_token = %s, heartbeat_at = %s
           WHERE name = %s AND status = %s""",
        (token, now_datetime(), run_name, expect),
    )
    frappe.db.commit()
    return frappe.db.get_value("Baton Workflow Run", run_name, "claim_token") == token


def heartbeat(run_name):
    """Mark a run as still alive. Called after each node.

    `update_modified=False` keeps this off the document's modified timestamp --
    a heartbeat is not a user-visible edit, and bumping `modified` would make
    every run look freshly touched in list views.
    """
    frappe.db.set_value(
        "Baton Workflow Run", run_name, "heartbeat_at", now_datetime(),
        update_modified=False,
    )
