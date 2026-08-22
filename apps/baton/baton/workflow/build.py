"""Building graphs in code.

Promoted out of agents/followup.py, which had the only copy. Anything that
generates a workflow -- the follow-up ladder, the starter templates -- should
produce nodes the same way, or the two drift and only one of them stays correct.
"""

import json


# Vertical gap between generated nodes, matching the canvas's own spacing.
ROW = 140
_COUNTER = {"n": 0}


def reset_layout():
    """Start a fresh column. Call once per graph being generated."""
    _COUNTER["n"] = 0


def node(node_id, node_type, label=None, config=None, next_node=None,
         next_node_alt=None, x=420, y=None, **kw):
    """One row for a Baton Workflow's `nodes` table.

    y is assigned automatically when it is not given. It used to be left unset,
    and because position_y is an Int -- which Frappe stores as 0, never NULL --
    every generated node landed on the same coordinates and the canvas rendered
    the whole graph as one illegible pile. "Unset" and "at the top" are not
    distinguishable after a round trip, so the answer is to always set it.
    """
    if y is None:
        y = 80 + _COUNTER["n"] * ROW
        _COUNTER["n"] += 1

    row = {
        "node_id": node_id,
        "node_type": node_type,
        "label": label or node_id,
        "config": json.dumps(config or {}),
        "next_node": next_node,
        "next_node_alt": next_node_alt,
        "position_x": x,
        "position_y": y,
    }
    row.update(kw)
    return row
