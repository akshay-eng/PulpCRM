"""Starter automations and a starter bot, all shipped switched off.

Someone opening the builder for the first time should find something to read
rather than an empty canvas -- and, more usefully, should be able to see what a
workflow is for and what a bot is for by looking at one of each.

Uses baton.workflow.build so generated graphs go through one node builder --
agents/followup.py had its own copy, and two builders drift.
"""

import frappe

from baton.workflow.build import node, reset_layout


def _install(name, description, triggers, nodes):
    if frappe.db.exists("Baton Workflow", name):
        print(f"  = {name} (exists)")
        return

    doc = frappe.get_doc({
        "doctype": "Baton Workflow",
        "workflow_name": name,
        "kind": "Workflow",
        "description": description,
        # Never on by arrival: nobody should discover their leads were being
        # messaged because a setup script ran.
        "enabled": 0,
        "trigger_type": "Manual",
        "triggers": triggers,
        "nodes": nodes,
    })
    doc.insert(ignore_permissions=True)
    print(f"  + {name} (workflow, disabled)")


def _install_bot(name, description, instructions, guardrails, connectors, triggers):
    if not frappe.db.table_exists("Baton Bot"):
        print("  ! Baton Bot table missing; run baton.setup_bots.install first")
        return
    if frappe.db.exists("Baton Bot", name):
        print(f"  = {name} (exists)")
        return

    # Laid out around the brain rather than in a column: the point of the bot
    # canvas is that connectors hang off it, and a starter that arrives as a
    # straight line teaches the wrong shape.
    ring = [(160, 90), (680, 90), (160, 430), (680, 430), (110, 260), (730, 260)]
    rows = []
    for i, c in enumerate(connectors):
        x, y = ring[i % len(ring)]
        rows.append({"connector": c, "enabled": 1, "position_x": x, "position_y": y})

    frappe.get_doc({
        "doctype": "Baton Bot",
        "bot_name": name,
        "description": description,
        "instructions": instructions,
        "guardrails": guardrails,
        "enabled": 0,
        "channel": "WhatsApp",
        "max_steps": 8,
        "position_x": 420,
        "position_y": 260,
        "connectors": rows,
        "triggers": triggers,
    }).insert(ignore_permissions=True)
    print(f"  + {name} (bot, disabled)")


def install():
    reset_layout()
    _install(
        "Tag and notify a new lead",
        "Marks a new lead and raises a task for its owner.",
        [{"enabled": 1, "trigger_type": "Document Event",
          "trigger_doctype": "CRM Lead", "trigger_event": "after_insert"}],
        [
            node("t", "Trigger", "A lead is created", next_node="mark"),
            node("mark", "Update Field", "Mark it new",
                 config={"field": "status", "value": "New"}, next_node="task"),
            node("task", "Create Task", "Tell the owner",
                 config={"subject": "New lead: {{ doc.lead_name }}",
                         "description": "Came in at {{ doc.creation }}.",
                         "priority": "Medium"}),
        ],
    )

    reset_layout()
    _install(
        "Greet, qualify and book",
        "The full path: greet on WhatsApp, work out what they need, offer times, book it.",
        [{"enabled": 1, "trigger_type": "Document Event",
          "trigger_doctype": "CRM Lead", "trigger_event": "after_insert"}],
        [
            node("t", "Trigger", "A lead is created", next_node="greet"),
            node("greet", "Send WhatsApp", "Say hello",
                 config={"message": "Hi {{ doc.lead_name }}, thanks for getting in "
                                    "touch. Mind if I ask a couple of quick questions?",
                         "author": "ai"},
                 next_node="qualify"),
            node("qualify", "AI Conversation", "Work out what they need",
                 config={"agent": "Service Qualifier"},
                 next_node="offer", next_node_alt="handover"),
            node("offer", "Offer Slots", "Offer some times",
                 config={"service": "Intro call", "count": 3},
                 next_node="book", next_node_alt="handover"),
            node("book", "Book Appointment", "Book it",
                 config={"subject": "Intro call with {{ doc.lead_name }}"},
                 next_node="done"),
            node("done", "Update Field", "Mark qualified",
                 config={"field": "status", "value": "Qualified"}),
            # The rescue branch sits in its own column, so the two paths do not
            # cross over each other on the canvas.
            node("handover", "Create Task", "Hand to a person",
                 config={"subject": "Pick up the conversation with {{ doc.lead_name }}",
                         "priority": "High"},
                 x=760, y=500),
        ],
    )

    _install_bot(
        "Front desk",
        "Answers a new lead, works out what they want and books a call.",
        "You look after new leads the moment they arrive.\n\n"
        "Read the lead to see what you already know. Message them on WhatsApp, "
        "introduce yourself, and find out what they are after. When you know "
        "enough, offer them some times and book one. Write what you learned back "
        "onto the lead as you go.\n\n"
        "If they go quiet, or ask for something you cannot do, raise a task for "
        "a person and stop.",
        "Never quote a price or promise a delivery date.\n"
        "Never say a meeting is booked unless book_meeting actually succeeded.\n"
        "Keep every message under three sentences.\n"
        "If they ask to be left alone, stop immediately and raise a task.",
        ["crm_leads", "whatsapp", "calendar", "crm_tasks"],
        [{"enabled": 1, "trigger_type": "Document Event",
          "trigger_doctype": "CRM Lead", "trigger_event": "after_insert"}],
    )

    frappe.db.commit()
    print("Starter automations ready.")
