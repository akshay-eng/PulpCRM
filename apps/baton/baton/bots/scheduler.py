"""Bots that run on their own.

A workflow is a reaction: something happens, it responds. A bot with a schedule
is a standing instruction -- it wakes on its own clock, does its job, and keeps
doing so until it is switched off or deleted. Nothing triggers it, and nothing
has to.

`next_run_at` on the bot is the single authority for when that is. Both the
"every N" and the cron mode maintain it, so the tick loop is identical either
way and the next wake-up is a visible timestamp rather than something a person
has to decode a cron expression to know.

Two workers can tick the same minute. Claiming is therefore a conditional
UPDATE whose token is read back -- `frappe.db.sql` returns () for any UPDATE, so
a rowcount is simply not available (see workflow/claim.py for the long version).
"""

import frappe
from croniter import croniter
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

RUN_QUEUE = "long"
RUN_TIMEOUT = 1500

UNIT_KWARG = {"Minutes": "minutes", "Hours": "hours", "Days": "days"}
SCHEDULED = ("Every", "On a cron")


def next_run_after(bot, after=None):
    """When this bot should next wake, or None if it should not.

    `bot` may be a Document or a plain dict, because the tick loop reads rows
    with get_all and the save hook has a full document.
    """
    get = bot.get if hasattr(bot, "get") else bot.__getitem__
    mode = get("schedule_mode") or "Off"
    if mode not in SCHEDULED:
        return None

    after = get_datetime(after or now_datetime())

    if mode == "Every":
        n = cint(get("every_value"))
        if n < 1:
            return None
        unit = UNIT_KWARG.get(get("every_unit") or "Hours", "hours")
        return add_to_date(after, **{unit: n})

    cron = (get("cron_expression") or "").strip()
    if not cron:
        return None
    try:
        return croniter(cron, after).get_next(type(after))
    except Exception:
        frappe.log_error(title="Baton: bad cron on bot")
        return None


def reschedule(doc, method=None):
    """The clock starts when the bot is switched on.

    A schedule is a promise about what happens *from now*, so the countdown
    begins the moment the bot is enabled -- not when it was created, and never
    carried over from a previous stint. A bot switched off for a week and back
    on runs one interval later, not immediately.

    Equally, editing a running bot must not silently postpone it: the previous
    version of this recomputed the time on every save, so saving a typo fix on a
    four-hour bot pushed its next run four hours away. The time now moves only
    when the bot was just switched on, or the schedule itself changed.
    """
    before = doc.get_doc_before_save()

    if doc.schedule_mode not in SCHEDULED or not doc.enabled:
        # Off means off: no pending time to fire from if it comes back later.
        if doc.next_run_at:
            doc.db_set("next_run_at", None, update_modified=False)
        return

    if doc.get("catch_up"):
        # "Run once as soon as I save" -- due now, and the box unticks itself so
        # the next save does not silently fire another run.
        doc.db_set({"next_run_at": now_datetime(), "catch_up": 0}, update_modified=False)
        return

    SHAPE = ("schedule_mode", "every_value", "every_unit", "cron_expression")
    just_enabled = before is not None and not before.get("enabled")
    shape_changed = before is not None and any(
        before.get(f) != doc.get(f) for f in SHAPE)

    # `before is None` is an insert. No pending time means nothing is scheduled
    # yet and one has to be set regardless.
    if before is not None and not (just_enabled or shape_changed) and doc.next_run_at:
        return

    nxt = next_run_after(doc)
    if nxt:
        doc.db_set("next_run_at", nxt, update_modified=False)


def _claim(name, now, next_at):
    """Win the right to run this bot this minute. False means someone else did."""
    token = frappe.generate_hash(length=16)
    frappe.db.sql(
        """UPDATE `tabBaton Bot`
              SET next_run_at = %s, last_run_at = %s, schedule_token = %s
            WHERE name = %s AND enabled = 1
              AND (next_run_at IS NULL OR next_run_at <= %s)""",
        (next_at, now, token, name, now),
    )
    frappe.db.commit()
    return frappe.db.get_value("Baton Bot", name, "schedule_token") == token


def tick():
    """Once a minute: start every bot whose next run has come due."""
    if not frappe.db.table_exists("Baton Bot"):
        return

    now = now_datetime()
    rows = frappe.get_all(
        "Baton Bot",
        filters={"enabled": 1, "schedule_mode": ["in", SCHEDULED]},
        fields=["name", "schedule_mode", "every_value", "every_unit",
                "cron_expression", "next_run_at", "last_run_at"],
    )

    for row in rows:
        try:
            if row.next_run_at and get_datetime(row.next_run_at) > now:
                continue

            nxt = next_run_after(row, now)
            if not nxt:
                continue

            # Read the previous run time *before* claiming: the claim overwrites
            # last_run_at, and this value is what the bot is told to treat as
            # "since last time".
            since = row.last_run_at

            if row.next_run_at is None:
                # First sight of a bot that has never been scheduled. Give it a
                # next time rather than running it now -- a bot should not fire
                # the instant it is created unless its owner asked for that.
                frappe.db.set_value("Baton Bot", row.name, "next_run_at", nxt,
                                    update_modified=False)
                frappe.db.commit()
                continue

            if not _claim(row.name, now, nxt):
                continue

            frappe.enqueue(
                "baton.bots.runtime.run_bot",
                queue=RUN_QUEUE,
                timeout=RUN_TIMEOUT,
                job_id=f"baton-bot-schedule-{row.name}-{now:%Y%m%d%H%M}",
                deduplicate=True,
                bot_name=row.name,
                run_reason="schedule",
                since=str(since) if since else None,
            )
        except Exception:
            frappe.log_error(title=f"Baton: scheduling bot {row.name}")
