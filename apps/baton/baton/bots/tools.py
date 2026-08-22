"""What happens when a bot actually calls a tool.

Every function here is reachable only through `execute()`, and `execute()` only
dispatches tools whose connector is attached to the bot. That is the whole
security model and it is deliberately boring: the model chooses *which* granted
tool to call and with what arguments, never *what tools exist*.

Three things are enforced in code rather than in the prompt, because a prompt is
a request and this is a rule:

  * writes go to allow-listed doctypes and never to structural fields
  * outbound messages go through `workflow.actions.whatsapp.send`, the same
    single gated path the workflow engine uses
  * every call is capped, so "list the leads" cannot mean forty thousand rows
"""

import json

import frappe
from frappe.utils import add_to_date, cint, cstr

from baton.audit import log_action
from baton.bots.catalog import BY_ID, connector_of

MAX_ROWS = 20

# How much of a fetched page reaches the model. Everything here is paid for per
# token and replayed on every subsequent step, so an uncapped page is an
# uncapped bill.
PAGE_CHARS = 6000

# Fields the bot may never write, whatever a connector allows. Ownership and
# identity are not the model's to change, and letting it near `docstatus` or
# `parent` lets it move a row into a document it was never given.
PROTECTED_FIELDS = {
    "name", "owner", "doctype", "docstatus", "creation", "modified", "modified_by",
    "parent", "parenttype", "parentfield", "idx", "_assign", "_comments",
    "_user_tags", "_liked_by",
}

# What a search looks in, per doctype. A generic "search every Data field" turns
# one tool call into a table scan on a live CRM.
SEARCH_FIELDS = {
    "CRM Lead": ["lead_name", "organization", "email_id", "mobile_no", "status"],
    "CRM Deal": ["organization", "email", "mobile_no", "status"],
    "Contact": ["first_name", "last_name", "email_id", "mobile_no"],
    "CRM Organization": ["organization_name", "website", "industry"],
    "CRM Call Log": ["from", "to", "status", "type"],
}

# What comes back from a find. Enough to decide, not the whole row -- a bot that
# reads 60 fields per result burns its context on nothing.
SUMMARY_FIELDS = {
    "CRM Lead": ["name", "lead_name", "organization", "status", "email_id", "mobile_no"],
    "CRM Deal": ["name", "organization", "status", "email", "mobile_no"],
    "Contact": ["name", "first_name", "last_name", "email_id", "mobile_no"],
    "CRM Organization": ["name", "organization_name", "industry", "website"],
    "CRM Call Log": ["name", "from", "to", "type", "status", "duration", "creation"],
}

SLUG_DOCTYPE = {
    "leads": "CRM Lead", "deals": "CRM Deal", "contacts": "Contact",
    "organizations": "CRM Organization", "calls": "CRM Call Log",
}


class ToolError(Exception):
    """A tool refused. The model is told why and gets to try something else."""


class Park:
    """A tool that means "stop and wait", not "here is your answer"."""

    def __init__(self, kind, seconds, channel=None):
        self.kind = kind
        self.seconds = seconds
        self.channel = channel


# ------------------------------------------------------------------ helpers

def _connector_config(ctx, connector_id):
    for row in ctx["bot"].get("connectors") or []:
        if row.connector == connector_id:
            try:
                return json.loads(row.config) if row.config else {}
            except (ValueError, TypeError):
                return {}
    return {}


def _allowed_doctypes(ctx):
    out = set()
    for row in ctx["bot"].get("connectors") or []:
        if not row.enabled:
            continue
        out.update((BY_ID.get(row.connector) or {}).get("doctypes") or [])
    return out


def _check_doctype(ctx, doctype):
    if doctype not in _allowed_doctypes(ctx):
        raise ToolError(
            f"This bot has no connector for {doctype}. "
            "Attach one on the canvas if it should be able to touch these."
        )


def _clean_values(doctype, values):
    if not isinstance(values, dict):
        raise ToolError("values must be an object of fieldname to value.")
    meta = frappe.get_meta(doctype)
    known = {f.fieldname for f in meta.fields}
    out, refused = {}, []
    for k, v in values.items():
        if k in PROTECTED_FIELDS or str(k).startswith("_"):
            refused.append(k)
            continue
        if k not in known:
            refused.append(k)
            continue
        out[k] = v
    if not out:
        raise ToolError(
            f"None of those fields exist on {doctype}: {', '.join(refused) or '(none given)'}."
        )
    return out, refused


def _subject(ctx):
    doc = ctx.get("doc")
    if not doc:
        raise ToolError("There is no record in hand for this run, so this tool cannot run.")
    return doc


# -------------------------------------------------------------- record tools

def _find(ctx, doctype, args):
    _check_doctype(ctx, doctype)
    limit = min(cint(args.get("limit")) or 5, MAX_ROWS)
    fields = [f for f in SUMMARY_FIELDS.get(doctype, ["name"])
              if frappe.get_meta(doctype).has_field(f) or f == "name"]
    query = cstr(args.get("query") or "").strip()

    or_filters = {}
    if query:
        for f in SEARCH_FIELDS.get(doctype, []):
            if frappe.get_meta(doctype).has_field(f):
                or_filters[f] = ["like", f"%{query}%"]

    rows = frappe.get_all(doctype, fields=fields, or_filters=or_filters or None,
                          order_by="modified desc", limit_page_length=limit,
                          ignore_permissions=True)
    return {"found": len(rows), "records": rows}


def _read(ctx, doctype, args):
    _check_doctype(ctx, doctype)
    name = cstr(args.get("name") or "").strip()
    if not name:
        raise ToolError("Which record? Pass its id as `name`.")
    if not frappe.db.exists(doctype, name):
        raise ToolError(f"No {doctype} called {name}.")
    doc = frappe.get_doc(doctype, name)
    fields = SUMMARY_FIELDS.get(doctype, ["name"])
    extra = ["notes", "next_step", "annual_revenue", "no_of_employees", "territory",
             "industry", "source", "lead_owner", "deal_owner", "probability"]
    out = {}
    for f in list(fields) + extra:
        if doc.meta.has_field(f) or f == "name":
            value = doc.get(f)
            if value not in (None, ""):
                out[f] = value
    return {"record": out}


def _update(ctx, doctype, args):
    _check_doctype(ctx, doctype)
    name = cstr(args.get("name") or "").strip() or (
        ctx["doc"].name if ctx.get("doc") and ctx["doc"].doctype == doctype else "")
    if not name:
        raise ToolError("Which record? Pass its id as `name`.")
    if not frappe.db.exists(doctype, name):
        raise ToolError(f"No {doctype} called {name}.")

    values, refused = _clean_values(doctype, args.get("values") or {})
    doc = frappe.get_doc(doctype, name)
    for k, v in values.items():
        doc.set(k, v)
    doc.save(ignore_permissions=True)
    log_action("bot.update", actor_type="AI_AGENT", reference_doctype=doctype,
               reference_name=name, workflow_run=ctx["run"].name, bot=ctx["bot"].name,
               output={"fields": list(values)})
    result = {"updated": name, "fields": list(values)}
    if refused:
        result["ignored"] = refused
    return result


def _create(ctx, doctype, args):
    _check_doctype(ctx, doctype)
    values, refused = _clean_values(doctype, args.get("values") or {})
    doc = frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)
    log_action("bot.create", actor_type="AI_AGENT", reference_doctype=doctype,
               reference_name=doc.name, workflow_run=ctx["run"].name, bot=ctx["bot"].name,
               output={"fields": list(values)})
    result = {"created": doc.name, "doctype": doctype}
    if refused:
        result["ignored"] = refused
    return result


# ----------------------------------------------------------- everything else

def _create_task(ctx, args):
    doc = _subject(ctx)
    title = cstr(args.get("title") or "").strip()
    if not title:
        raise ToolError("A task needs a title.")
    task = frappe.get_doc({
        "doctype": "CRM Task",
        "title": title[:140],
        "description": cstr(args.get("description") or "")[:2000],
        "reference_doctype": doc.doctype,
        "reference_docname": doc.name,
        "assigned_to": cstr(args.get("assign_to") or "") or doc.get("lead_owner")
        or doc.get("deal_owner") or doc.owner,
        "status": "Backlog",
        "priority": args.get("priority") if args.get("priority") in ("Low", "Medium", "High")
        else "Medium",
    }).insert(ignore_permissions=True)
    log_action("bot.task", actor_type="AI_AGENT", reference_doctype=doc.doctype,
               reference_name=doc.name, workflow_run=ctx["run"].name, bot=ctx["bot"].name,
               output={"task": task.name})
    return {"task": task.name}


def _add_note(ctx, args):
    doc = _subject(ctx)
    content = cstr(args.get("content") or "").strip()
    if not content:
        raise ToolError("A note needs some content.")
    note = frappe.get_doc({
        "doctype": "FCRM Note",
        "title": cstr(args.get("title") or "Note from a bot")[:140],
        "content": content[:4000],
        "reference_doctype": doc.doctype,
        "reference_docname": doc.name,
    }).insert(ignore_permissions=True)
    return {"note": note.name}


def _send_whatsapp(ctx, args):
    from baton.workflow.actions import whatsapp as wa_action

    doc = _subject(ctx)
    message = cstr(args.get("message") or "").strip()
    if not message:
        raise ToolError("Nothing to send.")

    ctx["turn"] += 1
    outcome = wa_action.send(
        to=None, message=message[:900], run=ctx["run"],
        node=_ShimNode("whatsapp"), doc=doc, author="ai", turn=ctx["turn"],
    )
    if outcome.get("blocked"):
        # A refusal is an answer, not a crash. The bot is told, and can decide to
        # raise a task for a human instead of retrying a send that cannot happen.
        return {"sent": False, "refused": outcome.get("skipped")}
    if outcome.get("drafted"):
        return {"sent": False, "drafted_for_approval": outcome["drafted"]}
    return {"sent": True}


def _send_email(ctx, args):
    """Email the record's contact, or a fixed address the admin configured.

    The fixed address is what makes a *reporting* bot possible: a scheduled run
    has no record in hand, so "email the contact on the record" cannot apply.

    The two paths are gated differently on purpose. Writing to a customer goes
    through `can_ai_send`, because that is what human handoff, quiet hours and
    do-not-contact protect. Writing to an address an admin typed into the
    connector is not that -- it is the bot reporting to its owner -- so it is
    logged rather than gated. Neither path lets the model choose the recipient.
    """
    cfg = _connector_config(ctx, "email")
    fixed = cstr(cfg.get("to") or "").strip()
    subject = cstr(args.get("subject") or "").strip()
    body = cstr(args.get("body") or "").strip()
    if not subject or not body:
        raise ToolError("An email needs both a subject and a body.")

    sender = cstr(cfg.get("sender") or "").strip() or None

    if fixed:
        frappe.sendmail(recipients=[fixed], subject=subject[:200], message=body[:20000],
                        sender=sender)
        log_action("bot.email", actor_type="AI_AGENT", workflow_run=ctx["run"].name,
                   bot=ctx["bot"].name,
                   output={"to": fixed, "from": sender, "fixed_recipient": True})
        return {"sent": True, "to": fixed}

    doc = _subject(ctx)
    from baton.conversation.state import can_ai_send

    allowed, mode, why = can_ai_send(doc.doctype, doc.name, channel="Email")
    if not allowed:
        return {"sent": False, "refused": why}
    to = doc.get("email_id") or doc.get("email")
    if not to:
        raise ToolError("This record has no email address, and no fixed address is set "
                        "on the Email connector.")
    if mode == "Draft":
        return {"sent": False, "refused": "Email is in Draft mode; a human has to approve it."}
    frappe.sendmail(recipients=[to], subject=subject[:200], message=body[:20000],
                    sender=sender,
                    reference_doctype=doc.doctype, reference_name=doc.name)
    log_action("bot.email", actor_type="AI_AGENT", reference_doctype=doc.doctype,
               reference_name=doc.name, workflow_run=ctx["run"].name, bot=ctx["bot"].name,
               output={"to": to})
    return {"sent": True, "to": to}


def _find_free_times(ctx, args):
    from baton.scheduling import slots as slot_mod
    from baton.scheduling import workhours as wh

    doc = _subject(ctx)
    cfg = _connector_config(ctx, "calendar")
    availability = slot_mod.resolve_availability(
        doc.doctype, doc.name, explicit=cfg.get("availability"))
    if not availability:
        raise ToolError(
            "No availability is configured, so there are no times to offer. "
            "Set one up under Settings > Scheduling."
        )
    count = min(cint(args.get("count")) or 3, 5)
    duration = cint(cfg.get("duration")) or 30
    found = slot_mod.free_slots(availability, duration_minutes=duration, limit=count)[:count]
    if not found:
        return {"slots": [], "note": "Nothing free inside the booking window."}

    tz = wh.tz_of(availability)
    # Stored on the run, not just described to the model: book_meeting resolves
    # a slot number against this list, so the model can only ever book a time
    # that was actually offered.
    ctx["vars"]["offered_slots"] = [
        {"start": str(s), "end": str(add_to_date(s, minutes=duration)),
         "label": wh.label(s, tz), "availability": availability.name,
         "user": availability.get("user")}
        for s in found
    ]
    return {"slots": [{"slot": str(i + 1), "when": s["label"]}
                      for i, s in enumerate(ctx["vars"]["offered_slots"])]}


def _book_meeting(ctx, args):
    from baton.scheduling import book as booking

    doc = _subject(ctx)
    offered = ctx["vars"].get("offered_slots") or []
    if not offered:
        raise ToolError("Call find_free_times first -- there is nothing to book yet.")

    wanted = cstr(args.get("slot") or "").strip()
    chosen = None
    if wanted.isdigit() and 1 <= int(wanted) <= len(offered):
        chosen = offered[int(wanted) - 1]
    else:
        chosen = next((s for s in offered
                       if wanted and (s["label"] == wanted or s["start"] == wanted)), None)
    if not chosen:
        raise ToolError(
            "That is not one of the times offered. Use the slot number you were given."
        )

    held, why = booking.hold(
        chosen.get("user"), chosen["start"], chosen["end"],
        reference_doctype=doc.doctype, reference_name=doc.name,
        workflow_run=ctx["run"].name)
    if not held:
        # Someone took it between offering and booking. Say so plainly so the
        # bot re-offers rather than telling the customer it is booked.
        ctx["vars"].pop("offered_slots", None)
        raise ToolError(f"Could not book it -- {why}. Find free times again and offer new ones.")

    event = booking.confirm(
        held,
        subject=cstr(args.get("subject") or "").strip()
        or f"Call with {doc.get('lead_name') or doc.name}",
    )
    log_action("bot.booking", actor_type="AI_AGENT", reference_doctype=doc.doctype,
               reference_name=doc.name, workflow_run=ctx["run"].name, bot=ctx["bot"].name,
               external_id=event)
    ctx["vars"]["event"] = event
    return {"booked": chosen["label"], "event": event}


def _allowed_pages(ctx):
    raw = _connector_config(ctx, "web").get("urls") or ""
    return [u.strip() for u in str(raw).replace(",", "\n").splitlines() if u.strip()]


def _list_pages(ctx, args):
    pages = _allowed_pages(ctx)
    if not pages:
        raise ToolError("No pages are configured on the Web pages connector.")
    return {"pages": pages}


def _read_page(ctx, args):
    """Fetch one allow-listed page and hand back its readable text.

    The allow-list is the whole security model, and it is checked against the
    exact configured string rather than a prefix: a prefix test lets
    `https://example.com.attacker.net/` through, and an open fetcher inside a
    CRM is a way to reach anything the server can reach.
    """
    import requests

    pages = _allowed_pages(ctx)
    if not pages:
        raise ToolError("No pages are configured on the Web pages connector.")

    wanted = cstr(args.get("url") or "").strip()
    if wanted not in pages:
        raise ToolError(
            "That address is not on this bot's list. It may read: " + ", ".join(pages)
        )

    try:
        resp = requests.get(
            wanted, timeout=25,
            headers={"User-Agent": "BatonBot/1.0 (+CRM automation)"},
            allow_redirects=True,
        )
    except Exception as e:
        raise ToolError(f"Could not fetch that page: {str(e)[:200]}")

    if resp.status_code >= 400:
        raise ToolError(f"That page answered {resp.status_code}.")

    text = _readable(resp.text)
    if not text:
        raise ToolError(
            "That page came back with no readable text. It probably builds itself "
            "with JavaScript, which this connector cannot run."
        )
    return {"url": wanted, "chars": len(text), "text": text[:PAGE_CHARS]}


def _readable(html):
    """HTML to something worth putting in a prompt.

    Scripts and styles are dropped rather than stripped of tags: leaving their
    contents in means feeding the model a page of minified JavaScript and paying
    for it.
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()
        text = soup.get_text("\n")
    except Exception:
        from frappe.utils import strip_html

        text = strip_html(html or "")

    lines = [line.strip() for line in (text or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _call_url(ctx, args):
    import requests

    cfg = _connector_config(ctx, "http")
    url = cfg.get("url")
    if not url:
        raise ToolError("No URL is configured on the HTTP connector.")
    method = (cfg.get("method") or "POST").upper()
    body = args.get("body") if isinstance(args.get("body"), dict) else {}
    try:
        if method == "GET":
            resp = requests.get(url, params=body, timeout=20)
        else:
            resp = requests.post(url, json=body, timeout=20)
    except Exception as e:
        raise ToolError(f"The request failed: {str(e)[:200]}")
    return {"status_code": resp.status_code, "body": resp.text[:800]}


def _wait_for_reply(ctx, args):
    doc = _subject(ctx)
    hours = cint(ctx["bot"].reply_timeout_hours) or 24
    return Park("Reply", hours * 3600, channel=ctx["bot"].channel or "WhatsApp")


class _ShimNode:
    """`whatsapp.send` writes a node id into the audit trail and the idempotency
    key. A bot has no nodes, so it supplies a stable stand-in rather than the
    send path growing a second signature."""

    def __init__(self, node_id):
        self.node_id = node_id
        self.node_type = "Bot"


# ----------------------------------------------------------------- dispatch

# ------------------------------------------------------- CRM operation tools
#
# The tools above are generic CRUD. These are the things a salesperson actually
# *does* in the portal -- convert a lead, hand it to someone, log a call, move a
# stage. Without them a bot can describe work but not perform it, and a user
# watching it would reasonably ask what the point was.

def _valid_options(doctype, fieldname):
    """The values a Select/Link field will actually accept."""
    meta = frappe.get_meta(doctype)
    field = meta.get_field(fieldname)
    if not field:
        return []
    if field.fieldtype == "Select":
        return [o for o in (field.options or "").split("\n") if o]
    if field.fieldtype == "Link" and field.options:
        return frappe.get_all(field.options, pluck="name", limit_page_length=60)
    return []


def _list_options(ctx, args):
    """What may go in a field. Stops a bot inventing a status that does not exist."""
    doctype = cstr(args.get("doctype") or "").strip()
    fieldname = cstr(args.get("field") or "").strip()
    _check_doctype(ctx, doctype)
    if not fieldname:
        raise ToolError("Which field? Pass `field`.")
    values = _valid_options(doctype, fieldname)
    if not values:
        raise ToolError(f"{fieldname} on {doctype} has no fixed set of values.")
    return {"doctype": doctype, "field": fieldname, "options": values}


def _convert_lead(ctx, args):
    """Lead -> Deal, through the CRM's own conversion.

    Delegates to crm.fcrm.doctype.crm_lead.crm_lead.convert_to_deal rather than
    creating a Deal directly: that function also creates the Contact and
    Organization and maps custom fields by label, none of which a bot should be
    reimplementing.
    """
    from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal

    lead = cstr(args.get("lead") or "").strip()
    if not lead:
        doc = _subject(ctx)
        if doc.doctype != "CRM Lead":
            raise ToolError("Pass `lead`, or run this on a lead.")
        lead = doc.name

    _check_doctype(ctx, "CRM Lead")
    _check_doctype(ctx, "CRM Deal")

    if not frappe.db.exists("CRM Lead", lead):
        raise ToolError(f"No lead called {lead}.")
    if frappe.db.get_value("CRM Lead", lead, "converted"):
        raise ToolError(f"{lead} has already been converted.")

    deal = convert_to_deal(lead=lead)
    log_action("bot.convert_lead", actor_type="AI_AGENT",
               reference_doctype="CRM Lead", reference_name=lead,
               workflow_run=ctx["run"].name, bot=ctx["bot"].name,
               decision="CONVERTED", output={"deal": deal})
    return {"lead": lead, "deal": deal}


def _assign_to(ctx, args):
    """Hand a record to a person, using Frappe's own assignment."""
    from frappe.desk.form.assign_to import add as assign_add

    doc = _subject(ctx)
    user = cstr(args.get("user") or "").strip()
    if not user:
        raise ToolError("Who to? Pass `user` (an email address).")
    if not frappe.db.exists("User", user):
        raise ToolError(f"{user} is not a user on this site.")

    _check_doctype(ctx, doc.doctype)
    assign_add({
        "assign_to": [user],
        "doctype": doc.doctype,
        "name": doc.name,
        "description": cstr(args.get("reason") or "Assigned by a bot")[:400],
    })
    log_action("bot.assign", actor_type="AI_AGENT", reference_doctype=doc.doctype,
               reference_name=doc.name, workflow_run=ctx["run"].name,
               bot=ctx["bot"].name, output={"user": user})
    return {"assigned_to": user, "record": f"{doc.doctype}/{doc.name}"}


def _list_users(ctx, args):
    """Who a record can be assigned to. Without this a bot guesses addresses."""
    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User",
                 "name": ["not in", ["Administrator", "Guest"]]},
        fields=["name", "full_name"], limit_page_length=50,
    )
    return {"users": users, "count": len(users)}


def _add_comment(ctx, args):
    doc = _subject(ctx)
    text = cstr(args.get("comment") or "").strip()
    if not text:
        raise ToolError("A comment needs some text.")
    c = frappe.get_doc({
        "doctype": "Comment", "comment_type": "Comment",
        "reference_doctype": doc.doctype, "reference_name": doc.name,
        "content": text[:4000],
    }).insert(ignore_permissions=True)
    return {"comment": c.name}


def _log_call(ctx, args):
    """Record a call that happened outside the CRM."""
    doc = _subject(ctx)
    duration = cint(args.get("duration_seconds") or 0)
    status = args.get("status") if args.get("status") in (
        "Completed", "No Answer", "Busy", "Failed") else "Completed"
    call = frappe.get_doc({
        "doctype": "CRM Call Log",
        "id": frappe.generate_hash(length=16),
        "telephony_medium": "Manual",
        "type": args.get("type") if args.get("type") in ("Incoming", "Outgoing") else "Outgoing",
        "status": status,
        "duration": duration,
        # `from` is mandatory on CRM Call Log. Fall back to the caller's own
        # telephony number so logging a call never fails on a blank field.
        "from": cstr(args.get("from_number") or "")
        or frappe.db.get_value("CRM Telephony Agent", {"user": frappe.session.user}, "mobile_no")
        or "unknown",
        "to": cstr(args.get("to_number") or doc.get("mobile_no") or ""),
        "reference_doctype": doc.doctype,
        "reference_docname": doc.name,
    }).insert(ignore_permissions=True)
    return {"call_log": call.name, "status": status, "duration": duration}


def _find_tasks(ctx, args):
    _check_doctype(ctx, "CRM Task")
    filters = {}
    doc = ctx.get("doc")
    if args.get("mine") and frappe.session.user:
        filters["assigned_to"] = frappe.session.user
    if args.get("status"):
        filters["status"] = args["status"]
    if args.get("for_this_record") and doc:
        filters["reference_docname"] = doc.name
    rows = frappe.get_all("CRM Task", filters=filters,
                          fields=["name", "title", "status", "priority", "due_date", "assigned_to"],
                          order_by="modified desc",
                          limit_page_length=min(cint(args.get("limit") or 20), 50))
    return {"tasks": rows, "count": len(rows)}


def _complete_task(ctx, args):
    _check_doctype(ctx, "CRM Task")
    name = cstr(args.get("task") or "").strip()
    if not name or not frappe.db.exists("CRM Task", name):
        raise ToolError(f"No task called {name or '(none given)'}.")
    frappe.db.set_value("CRM Task", name, "status", "Done")
    frappe.db.commit()
    return {"task": name, "status": "Done"}


def _search(ctx, args):
    """One search across everything this bot is allowed to see."""
    term = cstr(args.get("query") or "").strip()
    if not term:
        raise ToolError("What should I search for? Pass `query`.")

    hits, allowed = [], _allowed_doctypes(ctx)
    fields_by_doctype = {
        "CRM Lead": ["lead_name", "email", "mobile_no", "organization"],
        "CRM Deal": ["organization", "email", "mobile_no"],
        "Contact": ["first_name", "last_name", "email_id", "mobile_no"],
        "CRM Organization": ["organization_name", "website"],
    }
    for doctype, fields in fields_by_doctype.items():
        if doctype not in allowed:
            continue
        ors = [[doctype, f, "like", f"%{term}%"] for f in fields
               if frappe.get_meta(doctype).get_field(f)]
        if not ors:
            continue
        rows = frappe.get_all(doctype, or_filters=ors,
                              fields=["name"] + fields[:2],
                              limit_page_length=5)
        for r in rows:
            hits.append({"doctype": doctype, **r})
    return {"query": term, "results": hits, "count": len(hits)}


def execute(tool_name, args, ctx):
    """Run one tool. Returns a result dict, or a Park to suspend the run.

    Raises ToolError for anything the bot got wrong -- the caller feeds that
    back to the model as an observation, because a bot correcting itself is
    better than a run that dies on a typo.
    """
    connector = connector_of(tool_name)
    if not connector:
        raise ToolError(f"There is no tool called {tool_name}.")

    attached = {row.connector for row in ctx["bot"].get("connectors") or [] if row.enabled}
    if connector["id"] not in attached:
        raise ToolError(
            f"{tool_name} belongs to the {connector['label']} connector, "
            "which is not attached to this bot."
        )

    args = args if isinstance(args, dict) else {}

    for slug, doctype in SLUG_DOCTYPE.items():
        if tool_name == f"find_{slug}":
            return _find(ctx, doctype, args)
        if tool_name == f"read_{slug}":
            return _read(ctx, doctype, args)
        if tool_name == f"update_{slug}":
            return _update(ctx, doctype, args)
        if tool_name == f"create_{slug}":
            return _create(ctx, doctype, args)

    handlers = {
        "create_task": _create_task,
        "add_note": _add_note,
        "send_whatsapp": _send_whatsapp,
        "send_email": _send_email,
        "find_free_times": _find_free_times,
        "book_meeting": _book_meeting,
        "list_pages": _list_pages,
        "read_page": _read_page,
        "call_url": _call_url,
        "wait_for_reply": _wait_for_reply,
        # CRM operations a salesperson performs, as opposed to raw CRUD.
        "convert_lead": _convert_lead,
        "assign_to": _assign_to,
        "list_users": _list_users,
        "add_comment": _add_comment,
        "log_call": _log_call,
        "find_tasks": _find_tasks,
        "complete_task": _complete_task,
        "list_options": _list_options,
        "search": _search,
    }
    handler = handlers.get(tool_name)
    if not handler:
        raise ToolError(f"There is no tool called {tool_name}.")
    return handler(ctx, args)
