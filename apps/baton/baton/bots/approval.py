"""Stopping to ask a person.

Some actions should not happen merely because a model decided they should. This
is the interrupt: before a guarded tool runs, the bot parks, asks a named human,
and does nothing at all until they answer -- or until the deadline passes, which
counts as no.

The question goes out over the channel the bot already uses, so approving does
not mean logging into the CRM. Email gets one-click links. WhatsApp gets a short
code to reply with, because tapping a link inside WhatsApp is a worse experience
than typing four characters back.

A rejection is not an error. It goes back to the model as an observation, so a
bot told "no, do not message them" can decide to raise a task for a human
instead of simply dying.
"""

import json

import frappe
from frappe.utils import add_to_date, cint, cstr, now_datetime

from baton.audit import log_action

# No I, O, 0 or 1: this gets read off a phone screen and typed back.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_TIMEOUT_HOURS = 24


def gated(bot):
    """Tool names this bot must ask about first."""
    if (bot.get("approval_channel") or "Off") == "Off":
        return set()
    raw = cstr(bot.get("gated_tools") or "")
    return {t.strip() for t in raw.replace(",", "\n").splitlines() if t.strip()}


def _code():
    import secrets

    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        if not frappe.db.exists("Baton Approval", {"code": code, "status": "Pending"}):
            return code
    # Astronomically unlikely; a longer code is better than a collision.
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def _describe(tool_name, args):
    """What the human is being asked to allow, in their words not the model's."""
    args = args if isinstance(args, dict) else {}
    if tool_name == "send_whatsapp":
        return f"send this WhatsApp message:\n\n{cstr(args.get('message'))[:600]}"
    if tool_name == "send_email":
        return (f"send this email:\n\nSubject: {cstr(args.get('subject'))[:200]}\n\n"
                f"{cstr(args.get('body'))[:600]}")
    if tool_name == "assign_to":
        return f"hand this record to {cstr(args.get('user'))}"
    if tool_name == "convert_lead":
        return "convert this lead into a deal"
    pretty = json.dumps(args, default=str, indent=2)[:600] if args else "no arguments"
    return f"run {tool_name} with:\n\n{pretty}"


def _fallback_recipient(doc):
    """Who to ask when no approval_recipient is configured on the bot.

    Draft-mode sending (the site-wide send-mode setting, not gated_tools)
    routes here with nothing configured far more often than not -- an admin
    who turned on "review before sending" was not necessarily the same one
    who'd think to also fill in an approval recipient. Whoever the record is
    assigned to is the same person book_meeting's own rep notification
    already finds, so the request has somewhere to go by default instead of
    silently landing on nobody.
    """
    if not doc:
        return None, None
    from baton.bots.tools import _assigned_user, _assignee_number

    user = _assigned_user(doc)
    if not user:
        return None, None
    number = _assignee_number(doc)
    if number:
        return number, "WhatsApp"
    return user, "Email"  # a User's docname is their email


def _resolve_recipient(bot, doc):
    """(to, channel) -- explicit bot config first, the record's assignee
    otherwise. "Off" is a real, common value for the bot's own setting (it's
    what a bot with no gated_tools at all carries), but not a legal value on
    Baton Approval.channel, which only knows Email/WhatsApp."""
    channel = bot.get("approval_channel")
    if channel == "Off":
        channel = None
    to = cstr(bot.get("approval_recipient") or "").strip()
    if not to:
        fallback_to, fallback_channel = _fallback_recipient(doc)
        if fallback_to:
            to, channel = fallback_to, fallback_channel
    return to, (channel or "Email")


def notify(approval, bot, run, doc):
    """Actually tell someone a Baton Approval exists to act on -- a code and
    a token are not the same thing as anybody being told to use them.

    Split out from request() so a caller that creates its own approval
    record a different way (wa_action.send()'s own draft path, kept
    separate deliberately -- it is the one choke point every WhatsApp send
    goes through, workflow node or bot, and duplicating it here would open
    a second one) can still get a real notification sent for it, instead of
    the draft sitting there with nobody ever told it existed.
    """
    to, channel = _resolve_recipient(bot, doc)
    frappe.db.set_value("Baton Approval", approval.name, {"channel": channel, "sent_to": to})
    approval.channel, approval.sent_to = channel, to

    delivered = False
    try:
        if not to:
            raise ValueError("no recipient configured")
        delivered = (_send_email(approval, bot, to) if channel == "Email"
                     else _send_whatsapp(approval, bot, to, run, doc))
    except Exception as e:
        # The approval still stands and can be actioned in the CRM. Failing to
        # deliver the question must not silently turn into permission.
        frappe.log_error(title=f"Baton: could not ask for approval {approval.name}")
        log_action("bot.approval.undelivered", status="Failed", actor_type="AI_AGENT",
                   bot=bot.name, workflow_run=run.name,
                   output={"approval": approval.name, "error": str(e)[:300]})

    log_action("bot.approval.requested", actor_type="AI_AGENT", bot=bot.name,
               workflow_run=run.name,
               reference_doctype=doc.doctype if doc else None,
               reference_name=doc.name if doc else None,
               output={"approval": approval.name, "tool": approval.tool_name,
                       "channel": channel, "to": to, "delivered": delivered})
    return delivered


def request(bot, run, doc, tool_name, args):
    """Raise the question and send it. Returns (approval_name, timeout_hours)."""
    hours = cint(bot.get("approval_timeout_hours")) or DEFAULT_TIMEOUT_HOURS

    approval = frappe.get_doc({
        "doctype": "Baton Approval",
        "kind": "Send Message" if tool_name in ("send_whatsapp", "send_email") else "Other",
        "status": "Pending",
        "code": _code(),
        "token": frappe.generate_hash(length=32),
        "bot": bot.name,
        "tool_name": tool_name,
        "draft_text": _describe(tool_name, args)[:2000],
        "reference_doctype": doc.doctype if doc else None,
        "reference_name": doc.name if doc else None,
        "workflow_run": run.name,
        "expires_at": add_to_date(now_datetime(), hours=hours),
        # The arguments are stored, not re-asked. Approving means approving
        # *this* message, not "whatever the bot decides to send next".
        "payload": json.dumps({"tool": tool_name, "args": args}, default=str),
    }).insert(ignore_permissions=True)

    notify(approval, bot, run, doc)
    return approval.name, hours


def finalize_draft(approval_name, bot, run, doc, tool_name, args):
    """Turn a bare Baton Approval -- one wa_action.send() created itself,
    with no code, no token, and nobody told -- into a real, actionable,
    notified request. Same end state as request(), for an approval that
    already exists rather than one this call creates."""
    approval = frappe.get_doc("Baton Approval", approval_name)
    hours = cint(bot.get("approval_timeout_hours")) or DEFAULT_TIMEOUT_HOURS
    approval.tool_name = tool_name
    approval.payload = json.dumps({"tool": tool_name, "args": args}, default=str)
    if not approval.code:
        approval.code = _code()
    if not approval.token:
        approval.token = frappe.generate_hash(length=32)
    if not approval.expires_at:
        approval.expires_at = add_to_date(now_datetime(), hours=hours)
    approval.save(ignore_permissions=True)

    notify(approval, bot, run, doc)
    return hours


def _links(approval):
    base = (frappe.utils.get_url() or "").rstrip("/")
    stem = f"{base}/api/method/baton.api.approve.decide?code={approval.code}&token={approval.token}"
    return f"{stem}&decision=Approved", f"{stem}&decision=Rejected"


def _send_email(approval, bot, to):
    yes, no = _links(approval)
    body = (
        f"<p><b>{frappe.utils.escape_html(bot.bot_name)}</b> wants to "
        f"{frappe.utils.escape_html(approval.draft_text).replace(chr(10), '<br>')}</p>"
        f"<p style='margin-top:20px'>"
        f"<a href='{yes}' style='background:#16a34a;color:#fff;padding:10px 18px;"
        f"border-radius:6px;text-decoration:none'>Approve</a>&nbsp;&nbsp;"
        f"<a href='{no}' style='background:#dc2626;color:#fff;padding:10px 18px;"
        f"border-radius:6px;text-decoration:none'>Reject</a></p>"
        f"<p style='color:#666;font-size:12px;margin-top:18px'>"
        f"Nothing happens until you choose. This expires "
        f"{frappe.utils.format_datetime(approval.expires_at)}.</p>"
    )
    frappe.sendmail(recipients=[to], subject=f"[{bot.bot_name}] Approve: {approval.tool_name}",
                    message=body)
    return True


def _send_whatsapp(approval, bot, to, run, doc):
    from baton.workflow.actions import whatsapp as wa_action

    class _Node:
        node_id = f"approval-{approval.name}"

    text = (f"{bot.bot_name} wants to {approval.draft_text}\n\n"
            f"Reply YES {approval.code} to approve, or NO {approval.code} to reject.")
    outcome = wa_action.send(to=to, message=text[:1400], run=run, node=_Node(),
                             doc=None, author="human", turn=0)
    return not (outcome.get("skipped") or outcome.get("blocked"))


def settle(run, state):
    """On resume: what happened to the approval this run was waiting on.

    Returns (status, tool_name, args). `status` is Approved, Rejected or
    Expired -- and Expired is deliberately not Approved, because a question
    nobody answered is not permission.
    """
    name = (state or {}).get("pending_approval")
    if not name or not frappe.db.exists("Baton Approval", name):
        return None, None, None

    doc = frappe.get_doc("Baton Approval", name)
    payload = {}
    try:
        payload = json.loads(doc.payload) if doc.payload else {}
    except (ValueError, TypeError):
        pass

    status = doc.status
    if status == "Pending":
        # The deadline arrived before an answer did.
        status = "Expired"
        frappe.db.set_value("Baton Approval", name, "status", "Expired")

    return status, payload.get("tool"), payload.get("args") or {}


def resolve(doc, decision, by=None, note=None):
    """Record the answer and wake whatever was waiting on it.

    Every route in lands here -- the CRM button, the emailed link, the WhatsApp
    reply -- so a decision means the same thing however it arrived, and there is
    one place where "approved" turns into "the run continues".
    """
    from baton.workflow.claim import claim_run

    if doc.status != "Pending":
        return {"ok": False, "already": doc.status}

    doc.status = decision
    doc.resolved_by = frappe.session.user
    doc.resolved_at = now_datetime()
    if note:
        doc.draft_text = f"{doc.draft_text}\n\n-- {note}"[:2000]
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    log_action("bot.approval.resolved", actor_type="HUMAN",
               bot=doc.bot, workflow_run=doc.workflow_run,
               reference_doctype=doc.reference_doctype,
               reference_name=doc.reference_name,
               output={"approval": doc.name, "decision": decision, "via": by})

    if not doc.workflow_run:
        return {"ok": True, "resumed": None}

    run = frappe.db.get_value(
        "Baton Workflow Run", doc.workflow_run,
        ["name", "bot", "workflow", "status", "resume_node", "resume_node_alt"],
        as_dict=True)
    if not run or run.status != "Waiting":
        return {"ok": True, "resumed": None}

    if not run.bot:
        # A workflow approval: the existing node-routing path owns this.
        from baton.conversation.parking import resume_workflow_after_approval

        return resume_workflow_after_approval(run, decision)

    if not claim_run(run.name):
        return {"ok": True, "resumed": None}

    frappe.enqueue("baton.bots.runtime.run_bot", queue="long", timeout=1500,
                   enqueue_after_commit=True,
                   bot_name=run.bot, resume_run=run.name, run_reason="approval")
    return {"ok": True, "resumed": run.name}


# --------------------------------------------------------------- reply parsing

YES = {"yes", "y", "ok", "okay", "approve", "approved", "go", "send"}
NO = {"no", "n", "reject", "rejected", "stop", "cancel", "dont", "don't"}


def digits(v):
    return "".join(ch for ch in cstr(v) if ch.isdigit())


def same_number(a, b):
    """Do these two numbers belong to the same person?

    Compared on the last ten digits, because the manager's number is stored as
    someone typed it and comes back from WhatsApp in international form.
    """
    a, b = digits(a), digits(b)
    return bool(a) and bool(b) and a[-10:] == b[-10:]


UNCODED_REPLY_MAX_WORDS = 3


def parse_reply(text):
    """(decision, code) from a reply like "YES 4KDP", or (None, None).

    A reply that opens with "yes"/"no" but runs on for a full sentence --
    "Yes, went really well, they want a proposal" -- is far more likely a
    genuine conversational answer than a terse approval decision, so an
    uncoded bare yes/no is only accepted when the whole message is short.
    A message that also carries a valid code is unambiguous regardless of
    length and is always accepted, checked first.
    """
    words = [w.strip(".,!?:;").lower() for w in cstr(text).split()]
    words = [w for w in words if w]
    if not words:
        return None, None

    decision = None
    if words[0] in YES:
        decision = "Approved"
    elif words[0] in NO:
        decision = "Rejected"
    if not decision:
        return None, None

    for w in words[1:]:
        candidate = w.upper()
        if len(candidate) in (4, 8) and all(c in CODE_ALPHABET for c in candidate):
            return decision, candidate

    if len(words) > UNCODED_REPLY_MAX_WORDS:
        return None, None
    # A bare "yes" is only unambiguous when exactly one request is outstanding.
    return decision, None


def try_reply(message_doc):
    """Was this inbound WhatsApp an answer to an approval? True if it was.

    Returning True means the message has been consumed and must not also be fed
    to the conversation machinery -- the manager was answering a question, not
    talking to a lead.
    """
    text = cstr(message_doc.get("message") or "")
    decision, code = parse_reply(text)
    if not decision:
        return False

    sender = message_doc.get("from") or message_doc.get("from_") or ""

    filters = {"status": "Pending", "channel": "WhatsApp"}
    if code:
        filters["code"] = code
    pending = frappe.get_all("Baton Approval", filters=filters,
                             fields=["name", "sent_to", "code"],
                             order_by="creation desc", limit_page_length=10)

    # Only ever act on a request that was sent to *this* number. Without this a
    # lead replying "no" could reject a manager's approval.
    mine = [p for p in pending if same_number(p.sent_to, sender)]
    if not mine:
        return False
    if not code and len(mine) > 1:
        _reply(sender, "You have more than one request waiting. Reply with the "
                       "code too, for example: YES " + mine[0].code)
        return True

    doc = frappe.get_doc("Baton Approval", mine[0].name)
    resolve(doc, decision, by=f"WhatsApp {sender}")
    _reply(sender, "Approved — going ahead." if decision == "Approved"
           else "Rejected — nothing was sent.")
    return True


def _reply(to, text):
    try:
        from baton.channels import openwa

        openwa.send_text(to, text)
    except Exception:
        frappe.log_error(title="Baton: could not confirm approval reply")
