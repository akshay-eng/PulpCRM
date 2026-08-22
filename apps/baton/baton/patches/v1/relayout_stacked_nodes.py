"""Spread out graphs whose nodes all share one position.

`position_y` is an Int, and Frappe stores an unset Int as 0 rather than NULL.
Anything generated in code -- the starter templates, the follow-up ladder --
therefore arrived with every node at the same coordinates, and the canvas drew
the whole workflow as a single illegible pile of overlapping cards.

The generator no longer does that. This repairs the graphs that already exist,
because "delete it and make a new one" is not a fix for someone who built one.
"""

import frappe

ROW = 140
COL = 300


def execute():
    if not frappe.db.table_exists("Baton Workflow"):
        return

    for name in frappe.get_all("Baton Workflow", pluck="name"):
        doc = frappe.get_doc("Baton Workflow", name)
        nodes = doc.get("nodes") or []
        if len(nodes) < 2:
            continue

        spots = {(n.position_x or 0, n.position_y or 0) for n in nodes}
        # More than one node on a spot means the layout is not a layout.
        if len(spots) == len(nodes):
            continue

        _lay_out(nodes)
        doc.save(ignore_permissions=True)

    frappe.db.commit()


def _lay_out(nodes):
    """Walk the graph breadth-first: main branch down, alternates to the right."""
    by_id = {n.node_id: n for n in nodes}
    start = next((n.node_id for n in nodes if n.node_type == "Trigger"), nodes[0].node_id)

    placed = set()
    frontier = [(start, 0, 0)]
    while frontier:
        node_id, depth, column = frontier.pop(0)
        node = by_id.get(node_id)
        if not node or node_id in placed:
            continue
        placed.add(node_id)
        node.position_x = 420 + column * COL
        node.position_y = 80 + depth * ROW
        if node.next_node:
            frontier.append((node.next_node, depth + 1, column))
        if node.next_node_alt:
            frontier.append((node.next_node_alt, depth + 1, column + 1))

    # Anything nothing points at still needs somewhere to be.
    orphan_row = 0
    for node in nodes:
        if node.node_id not in placed:
            node.position_x = 420 - COL
            node.position_y = 80 + orphan_row * ROW
            orphan_row += 1
