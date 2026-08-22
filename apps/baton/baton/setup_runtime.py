"""Run-claim and liveness fields on Baton Workflow Run.

`claim_token` exists because `frappe.db.sql` cannot tell you how many rows an
UPDATE touched -- it returns () for any statement without a cursor description
(frappe/database/database.py). Claiming a run therefore has to write a token and
read it back; see baton.workflow.claim.

`heartbeat_at` lets the scheduler tell a run that is genuinely working from one
whose worker died mid-run.
"""

import frappe

from baton.setup_phase1 import _add_fields, _extend_select


def _drop_fields(doctype, fieldnames):
    """Remove fields we no longer use, so the schema stops lying about them."""
    dt = frappe.get_doc("DocType", doctype)
    keep = [f for f in dt.fields if f.fieldname not in fieldnames]
    dropped = [f.fieldname for f in dt.fields if f.fieldname in fieldnames]
    if dropped:
        dt.set("fields", keep)
        dt.save(ignore_permissions=True)
        print(f"  - {doctype}: {', '.join(dropped)}")
    else:
        print(f"  = {doctype} (nothing to drop)")


def _set_perm(doctype, role, **flags):
    """Adjust one role's permissions on one of our DocTypes."""
    dt = frappe.get_doc("DocType", doctype)
    for p in dt.permissions:
        if p.role == role:
            changed = {k: v for k, v in flags.items() if p.get(k) != v}
            if not changed:
                print(f"  = {doctype}/{role} (permissions already set)")
                return
            for k, v in flags.items():
                p.set(k, v)
            dt.save(ignore_permissions=True)
            print(f"  ~ {doctype}/{role}: {changed}")
            return


def install():
    # state.py has always written "Cancelled" via db.set_value, which bypasses
    # validation -- so the option was never actually in the Select. Anything
    # calling run.save() on such a row would fail.
    _extend_select("Baton Workflow Run", "status", ["Cancelled", "Expired"])

    _add_fields("Baton Workflow Run", [
        {"fieldname": "sec_claim", "fieldtype": "Section Break", "label": "Worker"},
        {"fieldname": "claim_token", "fieldtype": "Data", "label": "Claim token",
         "read_only": 1, "no_copy": 1,
         "description": "Written and read back to prove which worker won the claim."},
        {"fieldname": "col_claim", "fieldtype": "Column Break"},
        {"fieldname": "heartbeat_at", "fieldtype": "Datetime", "label": "Last heartbeat",
         "read_only": 1, "no_copy": 1,
         "description": "Updated after each node. A stale value means the worker died."},
    ])

    # Dead since it was created: nothing reads or writes it. Canvas positions
    # live on the node rows (position_x / position_y), not here.
    _drop_fields("Baton Workflow", ["graph"])

    # A workflow can message customers unattended, so editing one is a manager
    # action. Sales User keeps read so the builder is still viewable.
    _set_perm("Baton Workflow", "Sales User", write=0, create=0, delete=0)

    frappe.db.commit()
    print("Runtime fields ready.")
