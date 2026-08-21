"""Follow-up policy DocTypes (spec §15-16)."""

import frappe

from baton.setup_phase1 import _doctype


def install():
    _doctype(
        "Baton Followup Step",
        [
            {"fieldname": "step", "fieldtype": "Int", "label": "#", "in_list_view": 1},
            {"fieldname": "channel", "fieldtype": "Select", "label": "Channel",
             "options": "WhatsApp\nEmail", "reqd": 1, "in_list_view": 1},
            {"fieldname": "wait_amount", "fieldtype": "Int", "label": "Wait", "default": "1",
             "in_list_view": 1},
            {"fieldname": "wait_unit", "fieldtype": "Select", "label": "Unit",
             "options": "minutes\nhours\ndays", "default": "days", "in_list_view": 1},
            {"fieldname": "col_f", "fieldtype": "Column Break"},
            {"fieldname": "prompt", "fieldtype": "Small Text", "label": "What to say",
             "description": "Instruction for the model, not the literal message."},
        ],
        istable=1,
    )

    _doctype(
        "Baton Followup Policy",
        [
            {"fieldname": "policy_name", "fieldtype": "Data", "label": "Name", "reqd": 1,
             "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1",
             "in_list_view": 1},
            {"fieldname": "col_p", "fieldtype": "Column Break"},
            {"fieldname": "is_default", "fieldtype": "Check", "label": "Default"},
            {"fieldname": "max_attempts", "fieldtype": "Int", "label": "Max attempts",
             "default": "4", "description": "After this, stop messaging and escalate to a human."},
            {"fieldname": "sec_steps", "fieldtype": "Section Break", "label": "Ladder"},
            {"fieldname": "steps", "fieldtype": "Table", "label": "Steps",
             "options": "Baton Followup Step"},
            {"fieldname": "sec_esc", "fieldtype": "Section Break", "label": "On exhaustion"},
            {"fieldname": "create_task", "fieldtype": "Check", "label": "Create a call task",
             "default": "1"},
            {"fieldname": "task_subject", "fieldtype": "Data", "label": "Task subject",
             "default": "Call lead — no response to automated follow-ups"},
            {"fieldname": "col_esc", "fieldtype": "Column Break"},
            {"fieldname": "notify_owner", "fieldtype": "Check", "label": "Notify owner",
             "default": "1"},
        ],
        title_field="policy_name",
        autoname="field:policy_name",
    )
    frappe.db.commit()
    print("Followup policy doctypes ready.")


def install_default_policy():
    name = "Default"
    if frappe.db.exists("Baton Followup Policy", name):
        print("  = Default followup policy exists")
        return
    frappe.get_doc({
        "doctype": "Baton Followup Policy",
        "policy_name": name, "enabled": 1, "is_default": 1, "max_attempts": 4,
        "create_task": 1, "notify_owner": 1,
        "task_subject": "Call lead — no response to automated follow-ups",
        # Spec §16's example ladder, alternating channels. Every delay is data.
        "steps": [
            {"step": 1, "channel": "Email", "wait_amount": 0, "wait_unit": "minutes",
             "prompt": "Introduce ourselves and ask what they need. Warm, two sentences."},
            {"step": 2, "channel": "WhatsApp", "wait_amount": 1, "wait_unit": "days",
             "prompt": "Short nudge. Ask if they still need help with their enquiry."},
            {"step": 3, "channel": "Email", "wait_amount": 2, "wait_unit": "days",
             "prompt": "Offer something concrete: a quick call or an example of similar work."},
            {"step": 4, "channel": "WhatsApp", "wait_amount": 2, "wait_unit": "days",
             "prompt": "Final polite check-in. Make clear we will stop following up."},
        ],
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    print("  + Default followup policy (4 steps, email/WhatsApp alternating)")


def install_all():
    install()
    install_default_policy()
