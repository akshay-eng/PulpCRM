"""Phase 4 — qualification profiles, scoring and results.

    bench --site crm.localhost execute baton.setup_phase4.install_all
"""

import frappe

from baton.setup_phase1 import _doctype


def install():
    # Spec §18: the questions and their weights are configuration. Nothing about
    # what makes a good lead belongs in code -- it differs per business.
    _doctype(
        "Baton Qualification Criterion",
        [
            {"fieldname": "criterion", "fieldtype": "Data", "label": "Criterion", "reqd": 1,
             "in_list_view": 1},
            {"fieldname": "question", "fieldtype": "Small Text", "label": "Question to ask",
             "in_list_view": 1},
            {"fieldname": "weight", "fieldtype": "Int", "label": "Weight", "default": "25",
             "in_list_view": 1},
            {"fieldname": "col_c", "fieldtype": "Column Break"},
            {"fieldname": "required", "fieldtype": "Check", "label": "Required", "default": "1"},
            {"fieldname": "priority", "fieldtype": "Int", "label": "Ask order", "default": "1"},
            {"fieldname": "acceptable", "fieldtype": "Small Text", "label": "Acceptable answers",
             "description": "Free text guidance given to the model, e.g. 'budget of at least 5 lakh'."},
            {"fieldname": "reject_if", "fieldtype": "Small Text", "label": "Reject if",
             "description": "Answers that disqualify outright."},
        ],
        istable=1,
    )

    _doctype(
        "Baton Qualification Band",
        [
            {"fieldname": "band", "fieldtype": "Data", "label": "Band", "reqd": 1, "in_list_view": 1},
            {"fieldname": "min_score", "fieldtype": "Int", "label": "From", "in_list_view": 1},
            {"fieldname": "max_score", "fieldtype": "Int", "label": "To", "in_list_view": 1},
            {"fieldname": "col_b", "fieldtype": "Column Break"},
            {"fieldname": "action", "fieldtype": "Select", "label": "Action",
             "options": "Nurture\nHuman review\nCreate deal", "default": "Nurture",
             "in_list_view": 1},
        ],
        istable=1,
    )

    _doctype(
        "Baton Qualification Profile",
        [
            {"fieldname": "profile_name", "fieldtype": "Data", "label": "Name", "reqd": 1,
             "unique": 1, "in_list_view": 1},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1",
             "in_list_view": 1},
            {"fieldname": "col_p", "fieldtype": "Column Break"},
            {"fieldname": "is_default", "fieldtype": "Check", "label": "Default profile"},
            {"fieldname": "business_context", "fieldtype": "Small Text", "label": "Business context",
             "description": "What you sell, to whom. Grounds the model so it cannot invent "
                            "capabilities or pricing (spec §110)."},
            {"fieldname": "sec_c", "fieldtype": "Section Break", "label": "Criteria"},
            {"fieldname": "criteria", "fieldtype": "Table", "label": "Criteria",
             "options": "Baton Qualification Criterion"},
            {"fieldname": "sec_b", "fieldtype": "Section Break", "label": "Score bands"},
            {"fieldname": "bands", "fieldtype": "Table", "label": "Bands",
             "options": "Baton Qualification Band"},
        ],
        title_field="profile_name",
        autoname="field:profile_name",
    )

    # Spec §20: the output, kept as a record so a score can always be traced to
    # the conversation that produced it.
    _doctype(
        "Baton Qualification Result",
        [
            {"fieldname": "reference_doctype", "fieldtype": "Link", "label": "Reference Type",
             "options": "DocType", "reqd": 1},
            {"fieldname": "reference_name", "fieldtype": "Dynamic Link", "label": "Reference",
             "options": "reference_doctype", "reqd": 1, "in_list_view": 1},
            {"fieldname": "profile", "fieldtype": "Link", "label": "Profile",
             "options": "Baton Qualification Profile"},
            {"fieldname": "col_r", "fieldtype": "Column Break"},
            {"fieldname": "score", "fieldtype": "Int", "label": "Score", "in_list_view": 1},
            {"fieldname": "band", "fieldtype": "Data", "label": "Band", "in_list_view": 1,
             "in_standard_filter": 1},
            {"fieldname": "confidence", "fieldtype": "Float", "label": "Confidence"},
            {"fieldname": "complete", "fieldtype": "Check", "label": "All required answered"},
            {"fieldname": "sec_s", "fieldtype": "Section Break", "label": "Summary"},
            {"fieldname": "summary", "fieldtype": "Small Text", "label": "Summary"},
            {"fieldname": "next_action", "fieldtype": "Small Text", "label": "Recommended action"},
            {"fieldname": "objections", "fieldtype": "Small Text", "label": "Objections"},
            {"fieldname": "missing", "fieldtype": "Small Text", "label": "Still missing"},
            {"fieldname": "next_question", "fieldtype": "Small Text", "label": "Next question to ask"},
            {"fieldname": "sec_a", "fieldtype": "Section Break", "label": "Answers"},
            {"fieldname": "answers", "fieldtype": "Code", "label": "Extracted answers",
             "options": "JSON"},
            {"fieldname": "ai_model", "fieldtype": "Link", "label": "Model",
             "options": "Baton AI Model"},
        ],
        autoname="hash",
        sort_field="creation",
        sort_order="DESC",
    )

    frappe.db.commit()
    print("Phase 4 doctypes ready.")


def install_default_profile():
    """A working profile out of the box, matching BATON.md's target market."""
    name = "Default"
    if frappe.db.exists("Baton Qualification Profile", name):
        print("  = Default profile exists")
        return

    frappe.get_doc({
        "doctype": "Baton Qualification Profile",
        "profile_name": name,
        "enabled": 1,
        "is_default": 1,
        "business_context": (
            "We are an Indian service business that delivers projects and invoices "
            "per project, typically between INR 50,000 and INR 5,00,000. "
            "Never invent pricing, delivery dates or capabilities."
        ),
        "criteria": [
            {"criterion": "Requirement", "weight": 25, "required": 1, "priority": 1,
             "question": "What are you looking to get done?",
             "acceptable": "A specific, describable piece of work we could scope."},
            {"criterion": "Budget", "weight": 25, "required": 1, "priority": 2,
             "question": "Do you have a budget range in mind for this?",
             "acceptable": "Any stated range at or above INR 50,000.",
             "reject_if": "Explicitly looking for free or under INR 10,000."},
            {"criterion": "Timeline", "weight": 20, "required": 1, "priority": 3,
             "question": "When are you hoping to start?",
             "acceptable": "A start date within the next 90 days."},
            {"criterion": "Authority", "weight": 20, "required": 0, "priority": 4,
             "question": "Will you be the one signing off on this?",
             "acceptable": "They decide, or they name the decision maker."},
            {"criterion": "Urgency", "weight": 10, "required": 0, "priority": 5,
             "question": "Is there a deadline driving this?",
             "acceptable": "Any concrete driver such as an event or launch."},
        ],
        "bands": [
            {"band": "Cold", "min_score": 0, "max_score": 39, "action": "Nurture"},
            {"band": "Warm", "min_score": 40, "max_score": 69, "action": "Nurture"},
            {"band": "Qualified", "min_score": 70, "max_score": 84, "action": "Human review"},
            {"band": "Hot", "min_score": 85, "max_score": 100, "action": "Create deal"},
        ],
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    print("  + Default qualification profile (5 criteria, 4 bands)")


def install_all():
    install()
    install_default_profile()


def install_assignment_rule():
    """A default round-robin rule for Deals (spec §22 -- reuse Frappe's engine).

    Deliberately uses Frappe's own Assignment Rule rather than a Baton-specific
    mechanism, so an admin who already knows Frappe can change it without
    learning our system.
    """
    name = "Baton — Round robin Deals"
    if frappe.db.exists("Assignment Rule", name):
        print("  = assignment rule exists")
        return name

    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User",
                 "name": ["not in", ["Administrator", "Guest"]]},
        pluck="name",
    )
    if not users:
        users = ["Administrator"]

    doc = frappe.get_doc({
        "doctype": "Assignment Rule",
        "name": name,
        "document_type": "CRM Deal",
        "rule": "Round Robin",
        "disabled": 0,
        "priority": 0,
        # Assign every deal; narrowing is the admin's job.
        "assign_condition": "1 == 1",
        "users": [{"user": u} for u in users],
        # Assignment Rule requires at least one working day.
        "assignment_days": [{"day": d} for d in
                            ["Monday", "Tuesday", "Wednesday", "Thursday",
                             "Friday", "Saturday", "Sunday"]],
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"  + Assignment Rule '{name}' -> {len(users)} user(s), round robin")
    return name
