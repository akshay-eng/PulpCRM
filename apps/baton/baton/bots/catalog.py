"""What a bot can be plugged into.

A connector is a *capability*, granted by dragging it onto the bot. Each one
declares the tools it hands the model. Nothing else does: the model is only
ever offered tools whose connector is attached and enabled, so "what can this
bot do?" is answerable by looking at the canvas.

Two rules the catalog exists to enforce:

  * **Credentials are never here.** A connector names the credential it needs
    and where that credential is configured; the value lives in Settings. This
    is why attaching a connector cannot leak a key into a bot definition.
  * **Doctypes are an allow-list.** A connector grants access to named CRM
    doctypes, not "any doctype". A bot that can write to `User` is a different
    product with a much bigger blast radius.
"""

# Where a credential is configured, so the builder can deep-link to it rather
# than telling someone to "go to settings" and leaving them to find it.
CRED_MODEL = {"id": "ai_model", "label": "AI model", "settings": "ai-models"}
CRED_WHATSAPP = {"id": "whatsapp", "label": "WhatsApp channel", "settings": "channels"}
CRED_EMAIL = {"id": "email", "label": "Outgoing email account", "settings": "email-accounts"}
CRED_CALENDAR = {"id": "calendar", "label": "Availability", "settings": "scheduling"}


def _record_tools(slug, doctype, label, writable=True, creatable=True):
    """The three things a bot does with a CRM record type."""
    tools = [
        {
            "name": f"find_{slug}",
            "label": f"Find {label.lower()}",
            "description": f"Search {label} by a phrase, or list the most recent ones.",
            "params": [
                {"name": "query", "type": "string", "required": False,
                 "description": "Words to look for. Leave out to get the newest."},
                {"name": "limit", "type": "int", "required": False,
                 "description": "How many to return, at most 20."},
            ],
        },
        {
            "name": f"read_{slug}",
            "label": f"Read one {label.lower()[:-1] if label.endswith('s') else label.lower()}",
            "description": f"Get the fields of one {doctype} by its id.",
            "params": [{"name": "name", "type": "string", "required": True,
                        "description": "The record id."}],
        },
    ]
    if writable:
        tools.append({
            "name": f"update_{slug}",
            "label": f"Update {label.lower()}",
            "description": f"Change fields on one {doctype}.",
            "params": [
                {"name": "name", "type": "string", "required": True},
                {"name": "values", "type": "object", "required": True,
                 "description": "Fieldname to new value."},
            ],
        })
    if creatable:
        tools.append({
            "name": f"create_{slug}",
            "label": f"Create {label.lower()[:-1] if label.endswith('s') else label.lower()}",
            "description": f"Make a new {doctype}.",
            "params": [{"name": "values", "type": "object", "required": True}],
        })
    return tools


CONNECTORS = [
    # ------------------------------------------------------------- CRM data
    {
        "id": "crm_leads", "label": "Leads", "group": "CRM records", "icon": "user-plus",
        "description": "Look up, create and update leads.",
        "doctypes": ["CRM Lead"],
        "tools": _record_tools("leads", "CRM Lead", "Leads"),
    },
    {
        "id": "crm_deals", "label": "Deals", "group": "CRM records", "icon": "handshake",
        "description": "Look up, create and update deals, and move them between stages.",
        "doctypes": ["CRM Deal"],
        "tools": _record_tools("deals", "CRM Deal", "Deals"),
    },
    {
        "id": "crm_contacts", "label": "Contacts", "group": "CRM records", "icon": "contact",
        "description": "Look up, create and update contacts.",
        "doctypes": ["Contact"],
        "tools": _record_tools("contacts", "Contact", "Contacts"),
    },
    {
        "id": "crm_organizations", "label": "Organizations", "group": "CRM records",
        "icon": "building-2",
        "description": "Look up, create and update organizations.",
        "doctypes": ["CRM Organization"],
        "tools": _record_tools("organizations", "CRM Organization", "Organizations"),
    },
    {
        "id": "crm_tasks", "label": "Tasks", "group": "CRM records", "icon": "check-circle",
        "description": "Raise tasks and hand work to a person.",
        "doctypes": ["CRM Task"],
        "tools": [
            {"name": "create_task", "label": "Create a task",
             "description": "Raise a task against the record in hand.",
             "params": [
                 {"name": "title", "type": "string", "required": True},
                 {"name": "description", "type": "string", "required": False},
                 {"name": "priority", "type": "string", "required": False,
                  "description": "Low, Medium or High."},
                 {"name": "assign_to", "type": "string", "required": False,
                  "description": "A user id. Leave out to use the record's owner."},
             ]},
        ],
    },
    {
        "id": "crm_notes", "label": "Notes", "group": "CRM records", "icon": "sticky-note",
        "description": "Write a note onto the record.",
        "doctypes": ["FCRM Note"],
        "tools": [
            {"name": "add_note", "label": "Add a note",
             "description": "Attach a note to the record in hand.",
             "params": [
                 {"name": "title", "type": "string", "required": False},
                 {"name": "content", "type": "string", "required": True},
             ]},
        ],
    },
    {
        "id": "crm_call_logs", "label": "Call logs", "group": "CRM records", "icon": "phone",
        "description": "Read recent calls. Read-only -- a bot does not invent call history.",
        "doctypes": ["CRM Call Log"],
        "tools": _record_tools("calls", "CRM Call Log", "Calls",
                               writable=False, creatable=False),
    },

    # ---------------------------------------------------------- conversation
    {
        "id": "whatsapp", "label": "WhatsApp", "group": "Talking", "icon": "message-circle",
        "description": "Send a WhatsApp message and wait for the answer.",
        "credential": CRED_WHATSAPP,
        "tools": [
            {"name": "send_whatsapp", "label": "Send a message",
             "description": "Message the contact on the record in hand. "
                            "Goes through the same approval and quiet-hours rules a "
                            "human-sent message would.",
             "params": [{"name": "message", "type": "string", "required": True}]},
            {"name": "wait_for_reply", "label": "Wait for their reply",
             "description": "Stop and wait until they answer. Use this after asking "
                            "a question -- do not guess what they will say.",
             "params": []},
        ],
    },
    {
        "id": "email", "label": "Email", "group": "Talking", "icon": "send",
        "description": "Email the record's address, or a fixed one you set here.",
        "credential": CRED_EMAIL,
        "config": [
            {"field": "to", "label": "Always send to", "type": "text",
             "placeholder": "you@example.com",
             "help": "Leave blank to email whoever is on the record. Fill it in for a "
                     "bot that reports to you rather than talking to a customer -- a "
                     "scheduled bot has no record in hand."},
            {"field": "sender", "label": "Send from", "type": "sender",
             "help": "Which mailbox it goes out of. Connect your own Gmail under "
                     "Settings > Google to send as yourself."},
        ],
        "tools": [
            {"name": "send_email", "label": "Send an email",
             "description": "Email the fixed address if one is set, otherwise the "
                            "contact on the record in hand.",
             "params": [
                 {"name": "subject", "type": "string", "required": True},
                 {"name": "body", "type": "string", "required": True},
             ]},
        ],
    },

    # ------------------------------------------------------------ scheduling
    {
        "id": "calendar", "label": "Calendar", "group": "Scheduling", "icon": "calendar-clock",
        "description": "Offer free times from the rep's calendar and book one.",
        "credential": CRED_CALENDAR,
        "config": [
            {"field": "availability", "label": "Availability", "type": "availability",
             "help": "Blank picks the record owner's schedule, then the shared one."},
            {"field": "duration", "label": "Meeting length (minutes)", "type": "int",
             "default": 30},
        ],
        "tools": [
            {"name": "find_free_times", "label": "Find free times",
             "description": "Free slots on the rep's calendar, honouring working "
                            "hours and holidays.",
             "params": [{"name": "count", "type": "int", "required": False,
                         "description": "How many to look for, at most 5."}]},
            {"name": "book_meeting", "label": "Book a meeting",
             "description": "Book one of the times find_free_times returned. "
                            "Pass the slot exactly as it was given to you.",
             "params": [
                 {"name": "slot", "type": "string", "required": True,
                  "description": "The slot id from find_free_times."},
                 {"name": "subject", "type": "string", "required": False},
             ]},
        ],
    },

    # ----------------------------------------------------------------- other
    {
        "id": "web", "label": "Web pages", "group": "Other", "icon": "globe",
        "description": "Read pages you list here. The bot picks which one, never a "
                       "new address.",
        "config": [
            {"field": "urls", "label": "Pages it may read", "type": "textarea",
             "required": True,
             "placeholder": "https://news.ycombinator.com\nhttps://example.com/blog",
             "help": "One per line. An address that is not on this list is refused, "
                     "so a bot cannot be talked into fetching somewhere else."},
        ],
        "tools": [
            {"name": "list_pages", "label": "See which pages it may read",
             "description": "The addresses this bot is allowed to fetch.",
             "params": []},
            {"name": "read_page", "label": "Read a page",
             "description": "Fetch one of the allowed addresses and get its text back. "
                            "Plain HTML only -- pages that build themselves with "
                            "JavaScript will come back nearly empty.",
             "params": [{"name": "url", "type": "string", "required": True,
                         "description": "One of the allowed addresses, exactly."}]},
        ],
    },
    {
        "id": "http", "label": "HTTP request", "group": "Other", "icon": "webhook",
        "description": "Send data to one URL you nominate. For pushing, not reading.",
        "config": [
            {"field": "url", "label": "URL", "type": "text", "required": True,
             "placeholder": "https://example.com/hook",
             "help": "Fixed here, so the bot can call it but never redirect it elsewhere."},
            {"field": "method", "label": "Method", "type": "select",
             "options": ["POST", "GET"], "default": "POST"},
        ],
        "tools": [
            {"name": "call_url", "label": "Call the URL",
             "description": "Send data to the address configured on this connector.",
             "params": [{"name": "body", "type": "object", "required": False}]},
        ],
    },
]

BY_ID = {c["id"]: c for c in CONNECTORS}


def public_catalog():
    """The catalog as the builder needs it -- no handlers, no secrets."""
    return CONNECTORS


def tools_for(connector_ids):
    """Tool specs granted by these connectors, in catalog order.

    Order is stable so the prompt is stable, which keeps model behaviour
    reproducible between runs of the same bot.
    """
    out = []
    for c in CONNECTORS:
        if c["id"] not in connector_ids:
            continue
        for t in c["tools"]:
            out.append({**t, "connector": c["id"]})
    return out


def connector_of(tool_name):
    for c in CONNECTORS:
        for t in c["tools"]:
            if t["name"] == tool_name:
                return c
    return None
