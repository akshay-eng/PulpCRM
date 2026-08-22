"""Retire `Baton Workflow.kind = "Bot"`.

A "bot" used to be a workflow with the pausing node types greyed out. That was
never a real distinction -- same runtime, same storage, smaller palette -- and
it is now its own DocType with connectors instead of a graph (baton.bots).

Existing rows are workflows and are relabelled as such. Nothing is deleted:
whatever someone built still runs exactly as it did.
"""

import frappe


def execute():
    if not frappe.db.table_exists("Baton Workflow"):
        return
    if not frappe.db.has_column("Baton Workflow", "kind"):
        return

    frappe.db.sql("""UPDATE `tabBaton Workflow` SET kind = 'Workflow'
                     WHERE kind = 'Bot' OR kind IS NULL OR kind = ''""")
    frappe.db.commit()
