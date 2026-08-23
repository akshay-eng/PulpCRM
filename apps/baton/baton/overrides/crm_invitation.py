"""Override crm.api.invite_by_email without editing that app, so an upgrade
cannot silently restore the bug.

Upstream's "already invited" check matches on email + role alone, with no
status filter -- so a CRM Invitation that lapsed past its 3-day expiry
(`crm.fcrm.doctype.crm_invitation.crm_invitation.expire_invitations`) still
counts as "already invited" forever. Nothing errors, no email sends, and the
UI shows a plain "Invitations sent successfully" toast regardless, because
the frontend calls onSuccess on any non-error response -- so re-inviting
someone whose first invite lapsed silently does nothing, with no sign
anything went wrong.

The only change from upstream is the added status="Pending" filter below.
"""

import frappe
from frappe import _
from frappe.utils import split_emails, validate_email_address


@frappe.whitelist()
def invite_by_email(emails: str, role: str):
    frappe.only_for(["Sales Manager", "System Manager"], True)

    user_roles = frappe.get_roles(frappe.session.user)

    if role == "System Manager" and "System Manager" not in user_roles:
        frappe.throw(_("You are not allowed to invite System Managers"), frappe.PermissionError)

    if role == "Sales Manager" and "System Manager" not in user_roles:
        frappe.throw(_("You are not allowed to invite Sales Managers"), frappe.PermissionError)

    if role not in ["System Manager", "Sales Manager", "Sales User"]:
        frappe.throw(_("Cannot invite for this role"), frappe.PermissionError)

    if not emails:
        return
    email_string = validate_email_address(emails, throw=False)
    email_list = split_emails(email_string)
    if not email_list:
        return
    existing_members = frappe.db.get_all("User", filters={"email": ["in", email_list]}, pluck="email")
    existing_invites = frappe.db.get_all(
        "CRM Invitation",
        filters={
            "email": ["in", email_list],
            "role": ["in", ["System Manager", "Sales Manager", "Sales User"]],
            # The one line different from upstream: an Expired or Rejected
            # invitation must not block a re-invite forever.
            "status": "Pending",
        },
        pluck="email",
    )

    to_invite = list(set(email_list) - set(existing_members) - set(existing_invites))

    for email in to_invite:
        frappe.get_doc(doctype="CRM Invitation", email=email, role=role).insert(ignore_permissions=True)

    return {
        "existing_members": existing_members,
        "existing_invites": existing_invites,
        "to_invite": to_invite,
    }
