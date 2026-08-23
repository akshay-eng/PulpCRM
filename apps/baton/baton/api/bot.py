"""CRUD + catalogue for the bot canvas.

Deliberately a separate module from api/workflow.py. A bot is a brain with
connectors plugged into it, not a graph of steps, and the moment the two share
an endpoint they start sharing a shape -- which is exactly how "bot" became
"workflow with two node types greyed out" the first time round.
"""

import json

import frappe
from frappe import _

from baton.bots.catalog import BY_ID, public_catalog

DEFAULTS = {
    "max_steps": 8,
    "reply_timeout_hours": 24,
    "channel": "WhatsApp",
    "position_x": 420,
    "position_y": 260,
}


@frappe.whitelist()
def get_connector_catalog():
    """Connectors, their tools, and where each credential is configured.

    The credential *status* is resolved here rather than in the browser, so the
    canvas can say "WhatsApp is not connected yet" without ever being told what
    the key is.
    """
    catalog = []
    for c in public_catalog():
        entry = {k: v for k, v in c.items()}
        cred = c.get("credential")
        if cred:
            entry["credential"] = {**cred, "configured": _credential_ready(cred["id"])}
        catalog.append(entry)
    return catalog


def _credential_ready(cred_id):
    try:
        if cred_id == "whatsapp":
            from baton.channels import openwa

            if openwa.is_enabled():
                return True
            return bool(frappe.db.exists("WhatsApp Account", {"status": "Active"})) \
                if frappe.db.table_exists("WhatsApp Account") else False
        if cred_id == "email":
            return bool(frappe.db.exists("Email Account", {"default_outgoing": 1}))
        if cred_id == "calendar":
            return bool(frappe.db.exists("Baton Availability", {"enabled": 1}))
        if cred_id == "ai_model":
            # A model row with no key is not a configured model. Checking only
            # that the row exists made the canvas say "ready" and then fail at
            # the first call with an error nobody was warned about.
            return bool(_usable_model())
    except Exception:
        return False
    return True


def _usable_model():
    """An enabled model that actually has a key, or None.

    Ollama needs no key, so its presence alone counts.
    """
    for row in frappe.get_all("Baton AI Model", filters={"enabled": 1},
                              fields=["name", "provider"]):
        if row.provider == "Ollama":
            return row.name
        if frappe.utils.password.get_decrypted_password(
                "Baton AI Model", row.name, "api_key", raise_exception=False):
            return row.name
    return None


@frappe.whitelist()
def get_bots():
    rows = frappe.get_all(
        "Baton Bot",
        fields=["name", "bot_name", "enabled", "description", "modified"],
        order_by="modified desc",
    )
    if not rows:
        return rows

    counts = {}
    for row in frappe.get_all("Baton Bot Connector",
                              filters={"parenttype": "Baton Bot",
                                       "parent": ["in", [r.name for r in rows]],
                                       "enabled": 1},
                              fields=["parent", "connector"]):
        counts.setdefault(row.parent, []).append(row.connector)

    triggers = {}
    for row in frappe.get_all("Baton Workflow Trigger",
                              filters={"parenttype": "Baton Bot",
                                       "parent": ["in", [r.name for r in rows]]},
                              fields=["parent", "trigger_type", "trigger_doctype",
                                      "trigger_event"]):
        triggers.setdefault(row.parent, []).append(row)

    for r in rows:
        r.connectors = counts.get(r.name, [])
        mine = triggers.get(r.name, [])
        r.trigger_count = len(mine)
        r.trigger_summary = _describe(mine[0]) if mine else ""
    return rows


def _describe(t):
    if t.trigger_type == "Document Event":
        return f"{t.trigger_doctype} · {t.trigger_event}"
    return t.trigger_type or ""


@frappe.whitelist()
def get_bot(name):
    doc = frappe.get_doc("Baton Bot", name)
    doc.check_permission("read")
    return {
        "name": doc.name,
        "bot_name": doc.bot_name,
        "enabled": doc.enabled,
        "description": doc.description,
        "instructions": doc.instructions,
        "guardrails": doc.guardrails,
        "ai_model": doc.ai_model,
        "channel": doc.channel or "WhatsApp",
        "max_steps": doc.max_steps or DEFAULTS["max_steps"],
        "reply_timeout_hours": doc.reply_timeout_hours or DEFAULTS["reply_timeout_hours"],
        "position_x": doc.position_x or DEFAULTS["position_x"],
        "position_y": doc.position_y or DEFAULTS["position_y"],
        "connectors": [
            {
                "connector": c.connector,
                "label": c.label or (BY_ID.get(c.connector) or {}).get("label"),
                "enabled": c.enabled,
                "config": json.loads(c.config) if c.config else {},
                "position_x": c.position_x or 0,
                "position_y": c.position_y or 0,
            }
            for c in doc.get("connectors") or []
        ],
        "triggers": [
            {
                "enabled": t.enabled,
                "trigger_type": t.trigger_type,
                "trigger_doctype": t.trigger_doctype,
                "trigger_event": t.trigger_event,
                "field_changed": t.field_changed,
                "cron": t.cron,
                "event_name": t.event_name,
                "webhook_path": t.webhook_path,
                "condition": t.condition,
            }
            for t in doc.get("triggers") or []
        ],
        "models": frappe.get_all("Baton AI Model", filters={"enabled": 1}, pluck="name"),
    }


def _unique_name(wanted):
    if not frappe.db.exists("Baton Bot", wanted):
        return wanted
    for i in range(2, 200):
        if not frappe.db.exists("Baton Bot", f"{wanted} {i}"):
            return f"{wanted} {i}"
    return f"{wanted} {frappe.generate_hash(length=6)}"


@frappe.whitelist()
def validate_bot(data, browser_model=None):
    """Everything wrong with this bot right now, as the canvas asks."""
    if isinstance(data, str):
        data = json.loads(data)
    if browser_model != data.get("ai_model"):
        browser_model = None
    return _problems(data, browser_model)


def _problems(data, browser_model=None):
    out = []
    connectors = [c for c in (data.get("connectors") or []) if c.get("enabled", 1)]
    ids = [c.get("connector") for c in connectors]

    if not (data.get("instructions") or "").strip():
        out.append({"level": "error", "target": "bot",
                    "message": _("Tell the bot what it is for. Without instructions "
                                 "it has nothing to work from.")})
    if not connectors:
        out.append({"level": "error", "target": "bot",
                    "message": _("Attach at least one connector. A bot with none "
                                 "can decide things but cannot do any of them.")})
    # The model is the one credential a bot cannot work without, and it is not a
    # connector -- so nothing on the canvas was checking it.
    wanted = data.get("ai_model")
    if wanted and frappe.db.exists("Baton AI Model", wanted):
        has_key = (
            wanted == browser_model
            or bool(
                frappe.utils.password.get_decrypted_password(
                    "Baton AI Model", wanted, "api_key", raise_exception=False
                )
            )
            or frappe.db.get_value("Baton AI Model", wanted, "provider") == "Ollama"
        )
        if not has_key:
            out.append({"level": "warning", "target": "bot",
                        "message": _("{0} has no API key, so this bot cannot think.")
                        .format(wanted)})
    elif not _usable_model():
        out.append({"level": "warning", "target": "bot",
                    "message": _("No AI model is set up, so this bot cannot think. "
                                 "Add one under Settings > Models & channels.")})

    if not (data.get("triggers") or []):
        out.append({"level": "warning", "target": "triggers",
                    "message": _("No trigger, so this only runs when you start it "
                                 "by hand.")})

    seen = set()
    for c in connectors:
        cid = c.get("connector")
        spec = BY_ID.get(cid)
        if not spec:
            out.append({"level": "error", "target": cid,
                        "message": _("Unknown connector {0}.").format(cid)})
            continue
        if cid in seen:
            out.append({"level": "error", "target": cid,
                        "message": _("{0} is attached twice.").format(spec["label"])})
        seen.add(cid)

        cred = spec.get("credential")
        if cred and not _credential_ready(cred["id"]):
            out.append({"level": "warning", "target": cid,
                        "message": _("{0} needs a {1} and there isn't one yet.")
                        .format(spec["label"], cred["label"])})

        for field in spec.get("config") or []:
            if field.get("required") and not (c.get("config") or {}).get(field["field"]):
                out.append({"level": "error", "target": cid,
                            "message": _("{0} needs {1}.")
                            .format(spec["label"], field["label"])})

    if "wait_for_reply" in [t for cid in ids for t in _tool_names(cid)] \
            and (data.get("channel") or "WhatsApp") == "None":
        out.append({"level": "warning", "target": "bot",
                    "message": _("This bot can wait for a reply but is set to talk "
                                 "on nothing, so it will never hear one.")})
    return out


def _tool_names(connector_id):
    spec = BY_ID.get(connector_id)
    return [t["name"] for t in (spec or {}).get("tools") or []]


@frappe.whitelist()
def save_bot(data):
    if isinstance(data, str):
        data = json.loads(data)

    blocking = [p for p in _problems(data) if p["level"] == "error"]
    if blocking:
        frappe.throw(
            _("This bot cannot be saved yet:") + "\n"
            + "\n".join(f"- {p['message']}" for p in blocking),
            title=_("Not ready"),
        )

    name = data.get("name")
    if name and frappe.db.exists("Baton Bot", name):
        doc = frappe.get_doc("Baton Bot", name)
        doc.check_permission("write")
    else:
        doc = frappe.new_doc("Baton Bot")
        doc.bot_name = _unique_name(data.get("bot_name") or "Untitled bot")

    for field in ("description", "instructions", "guardrails", "ai_model", "channel"):
        if field in data:
            doc.set(field, data.get(field))
    doc.max_steps = data.get("max_steps") or DEFAULTS["max_steps"]
    doc.reply_timeout_hours = data.get("reply_timeout_hours") or DEFAULTS["reply_timeout_hours"]
    doc.position_x = data.get("position_x") or DEFAULTS["position_x"]
    doc.position_y = data.get("position_y") or DEFAULTS["position_y"]
    doc.enabled = 1 if data.get("enabled") else 0

    doc.set("connectors", [])
    for c in data.get("connectors") or []:
        if c.get("connector") not in BY_ID:
            continue
        doc.append("connectors", {
            "connector": c["connector"],
            "label": c.get("label") or BY_ID[c["connector"]]["label"],
            "enabled": 1 if c.get("enabled", 1) else 0,
            "config": json.dumps(c.get("config") or {}),
            "position_x": c.get("position_x") or 0,
            "position_y": c.get("position_y") or 0,
        })

    _save_triggers(doc, data.get("triggers"))
    doc.save()
    frappe.db.commit()
    return get_bot(doc.name)


def _save_triggers(doc, triggers):
    """Same rules as a workflow's: a generated webhook path is an address
    someone configured on the far end, so it survives a save."""
    if triggers is None:
        return
    existing = {(t.trigger_type, t.trigger_doctype, t.trigger_event): t.webhook_path
                for t in doc.get("triggers") or [] if t.webhook_path}
    doc.set("triggers", [])
    for t in triggers:
        key = (t.get("trigger_type"), t.get("trigger_doctype"), t.get("trigger_event"))
        path = t.get("webhook_path") or existing.get(key)
        secret = t.get("webhook_secret")
        if t.get("trigger_type") == "Webhook" and not path:
            path = frappe.generate_hash(length=24)
            secret = frappe.generate_hash(length=32)
        doc.append("triggers", {
            "enabled": 1 if t.get("enabled", 1) else 0,
            "trigger_type": t.get("trigger_type"),
            "trigger_doctype": t.get("trigger_doctype"),
            "trigger_event": t.get("trigger_event"),
            "field_changed": t.get("field_changed"),
            "cron": t.get("cron"),
            "event_name": t.get("event_name"),
            "webhook_path": path,
            "webhook_secret": secret,
            "condition": t.get("condition"),
        })


@frappe.whitelist()
def rename_bot(name, new_name):
    frappe.only_for(["System Manager", "Sales Manager"])
    new_name = (new_name or "").strip()
    if not new_name:
        frappe.throw(_("A bot needs a name."))
    if new_name == name:
        return name
    if frappe.db.exists("Baton Bot", new_name):
        frappe.throw(_("A bot called {0} already exists.").format(new_name))
    frappe.rename_doc("Baton Bot", name, new_name, force=True)
    frappe.db.set_value("Baton Bot", new_name, "bot_name", new_name)
    frappe.db.commit()
    return new_name


@frappe.whitelist()
def set_enabled(name, enabled):
    doc = frappe.get_doc("Baton Bot", name)
    doc.check_permission("write")
    doc.enabled = 1 if str(enabled) in ("1", "true", "True") else 0
    doc.save()
    frappe.db.commit()
    return doc.enabled


@frappe.whitelist()
def delete_bot(name):
    frappe.only_for(["System Manager", "Sales Manager"])
    frappe.delete_doc("Baton Bot", name)
    frappe.db.commit()
    return True


@frappe.whitelist()
def test_bot(name, reference_doctype=None, reference_name=None, credential=None):
    """Run the bot without letting it touch anything.

    Deliberately not gated on `enabled`: the point of a tester is to try a bot
    *before* switching it on, and refusing to test a disabled bot means the only
    way to see what it does is to make it live.
    """
    from baton.bots.runtime import run_bot

    frappe.only_for(["System Manager", "Sales Manager"])

    doc = None
    subject = None
    if reference_doctype and reference_name:
        doc = frappe.get_doc(reference_doctype, reference_name)
    else:
        subject = frappe.db.get_value(
            "Baton Workflow Trigger",
            {"parent": name, "parenttype": "Baton Bot", "trigger_type": "Document Event"},
            "trigger_doctype")
        if subject:
            latest = frappe.get_all(subject, limit=1, order_by="modified desc", pluck="name")
            if latest:
                doc = frappe.get_doc(subject, latest[0])

    from baton.llm import use_client_credential

    with use_client_credential(credential):
        run_name = run_bot(name, doc=doc, run_reason="test", dry_run=True)
    if not run_name:
        return {"ok": False, "message": _("The bot did not start.")}

    warning = None
    if not doc:
        warning = _("No record to work on, so the bot was asked to decide with "
                    "nothing in hand.") if subject else _(
            "This bot has no document trigger, so it ran with no record.")

    return {"ok": True, "run": get_run(run_name), "warning": warning}


@frappe.whitelist()
def get_runs(bot=None, limit=50):
    return frappe.get_all(
        "Baton Workflow Run",
        filters={"bot": bot} if bot else {"bot": ["is", "set"]},
        fields=["name", "bot", "status", "reference_doctype", "reference_name", "creation"],
        order_by="creation desc",
        limit_page_length=limit,
    )


@frappe.whitelist()
def get_run(name):
    from baton.api.workflow import get_run as workflow_run

    return workflow_run(name)
