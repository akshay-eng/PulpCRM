"""Static checks on a workflow graph, run before it can be saved.

The engine has a runtime backstop (MAX_STEPS) for graphs that loop, but a
backstop is not a design tool: by the time it fires the run has already done a
hundred nodes' worth of side effects. Everything catchable by looking at the
graph is caught here instead.

Errors block a save. Warnings do not -- a half-built graph is a normal state to
be in while building one.
"""

import json

# Config keys a node cannot run without. Anything not listed needs no config.
REQUIRED_CONFIG = {
    "Update Field": ["field"],
    "Create Document": ["doctype"],
    "Send WhatsApp": ["message"],
    "Send Email": ["to"],
    "AI Agent": ["prompt"],
    "Webhook": ["url"],
    "Create Task": ["subject"],
    "Add Comment": ["comment"],
    "Create Note": ["content"],
}

# Nodes that suspend the run. Each should have somewhere to go when its wait
# times out, or the run quietly ends there.
#
# These used to double as the Bot/Workflow split -- a "bot" was a workflow that
# was forbidden to pause. That was never a real distinction, only a smaller
# palette, and it is gone: a Bot is now its own thing (baton.bots) with
# connectors instead of a graph. A workflow may pause wherever it likes.
PARKING_TYPES = {"Await Reply", "Request Approval", "AI Conversation",
                 "Offer Slots", "Wait"}

# Every branch a node can hand control to.
LINK_FIELDS = ("next_node", "next_node_alt", "fallback_node")


def _cfg(node):
    cfg = node.get("config")
    if isinstance(cfg, dict):
        return cfg
    try:
        return json.loads(cfg) if cfg else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _find_cycle(nodes_by_id, entries):
    """Three-colour DFS. Returns the node id a back-edge points at, or None."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(nodes_by_id, WHITE)

    def visit(node_id):
        colour[node_id] = GREY
        node = nodes_by_id[node_id]
        for field in LINK_FIELDS:
            nxt = node.get(field)
            if not nxt or nxt not in nodes_by_id:
                continue
            if colour[nxt] == GREY:
                return nxt
            if colour[nxt] == WHITE:
                hit = visit(nxt)
                if hit:
                    return hit
        colour[node_id] = BLACK
        return None

    for entry in entries:
        if colour.get(entry) == WHITE:
            hit = visit(entry)
            if hit:
                return hit
    for node_id in nodes_by_id:
        if colour[node_id] == WHITE:
            hit = visit(node_id)
            if hit:
                return hit
    return None


def _reachable(nodes_by_id, entries):
    seen, stack = set(), list(entries)
    while stack:
        node_id = stack.pop()
        if node_id in seen or node_id not in nodes_by_id:
            continue
        seen.add(node_id)
        for field in LINK_FIELDS:
            nxt = nodes_by_id[node_id].get(field)
            if nxt:
                stack.append(nxt)
    return seen


def _trigger_doctype(triggers):
    for t in triggers or []:
        if t.get("trigger_type") == "Document Event" and t.get("trigger_doctype"):
            return t["trigger_doctype"]
    return None


def validate_graph(nodes, triggers=None, kind="Workflow"):
    """Returns [{level, node_id, message}] -- 'error' blocks a save."""
    issues = []
    nodes = nodes or []

    if not nodes:
        return [{"level": "error", "node_id": None, "message": "The workflow has no nodes."}]

    # --- duplicate ids. Everything downstream assumes node_id is a key.
    seen = set()
    for n in nodes:
        node_id = n.get("node_id")
        if not node_id:
            issues.append({"level": "error", "node_id": None,
                           "message": "A node has no id."})
        elif node_id in seen:
            issues.append({"level": "error", "node_id": node_id,
                           "message": f"Duplicate node id '{node_id}'."})
        else:
            seen.add(node_id)

    nodes_by_id = {n["node_id"]: n for n in nodes if n.get("node_id")}

    # --- dangling branches
    for n in nodes:
        for field in LINK_FIELDS:
            target = n.get(field)
            if target and target not in nodes_by_id:
                issues.append({
                    "level": "error", "node_id": n.get("node_id"),
                    "message": f"{field.replace('_', ' ')} points at '{target}', which does not exist.",
                })

    # --- required config
    for n in nodes:
        cfg = _cfg(n)
        for key in REQUIRED_CONFIG.get(n.get("node_type"), []):
            if not cfg.get(key):
                issues.append({
                    "level": "error", "node_id": n.get("node_id"),
                    "message": f"{n.get('node_type')} needs '{key}' set.",
                })

        # A Condition is satisfied by either route: rules built in the picker, or
        # a hand-written expression. Requiring the expression outright made the
        # no-code path unsaveable.
        if n.get("node_type") == "Condition":
            has_rules = bool(cfg.get("rules"))
            if not has_rules and not cfg.get("expression"):
                issues.append({
                    "level": "error", "node_id": n.get("node_id"),
                    "message": "Add a rule to this If / Else, or write an expression.",
                })
            elif has_rules:
                incomplete = [
                    r for r in cfg["rules"]
                    if not (r or {}).get("field") or not (r or {}).get("operator")
                ]
                if incomplete:
                    issues.append({
                        "level": "error", "node_id": n.get("node_id"),
                        "message": "A rule on this If / Else is incomplete.",
                    })

    # --- a step meant for one record type, dropped into a workflow about
    # another. The engine acts on whatever record triggered the run, so
    # "Update the deal" in a lead workflow updates the lead. Saying so beats
    # letting someone find out from a run history.
    subject = _trigger_doctype(triggers)
    if subject:
        for n in nodes:
            wants = _cfg(n).get("for_doctype")
            if wants and wants != subject:
                issues.append({
                    "level": "warning", "node_id": n.get("node_id"),
                    "message": f"This step is written for a {wants}, but the workflow "
                               f"runs on a {subject}. It will act on the {subject}.",
                })

    entries = [n["node_id"] for n in nodes if n.get("node_type") == "Trigger"]
    if not entries and nodes_by_id:
        entries = [nodes[0]["node_id"]]

    # --- cycles
    cycle_at = _find_cycle(nodes_by_id, entries)
    if cycle_at:
        issues.append({
            "level": "error", "node_id": cycle_at,
            "message": f"The graph loops back to '{cycle_at}'. It would never finish.",
        })
    else:
        # Only meaningful once we know the graph terminates.
        reachable = _reachable(nodes_by_id, entries)
        for node_id in nodes_by_id:
            if node_id not in reachable:
                issues.append({
                    "level": "warning", "node_id": node_id,
                    "message": "Nothing leads to this node, so it will never run.",
                })

    # --- waits with no way out
    for n in nodes:
        if (n.get("node_type") in PARKING_TYPES - {"Wait"}
                and not n.get("next_node_alt")):
            issues.append({
                "level": "warning", "node_id": n.get("node_id"),
                "message": "No timeout branch: if nobody responds the run stops here.",
            })
        if n.get("node_type") == "Condition" and not (n.get("next_node") and n.get("next_node_alt")):
            issues.append({
                "level": "warning", "node_id": n.get("node_id"),
                "message": "Only one branch is connected.",
            })

    return issues


def errors_only(issues):
    return [i for i in issues if i["level"] == "error"]
