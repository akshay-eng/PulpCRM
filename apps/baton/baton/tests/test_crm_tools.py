"""The CRM operations a bot can perform.

Raw CRUD lets a bot describe work. These are the things a salesperson actually
does — convert, assign, log, comment — and without them a bot that "handles a
lead" cannot finish the job it was asked to do.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.bots import catalog, tools
from baton.bots.tools import ToolError


class _Run:
    name = "test-run"


def _ctx(doc, connector_ids=None):
    ids = connector_ids if connector_ids is not None else [c["id"] for c in catalog.CONNECTORS]
    return {
        "doc": doc,
        "run": _Run(),
        "bot": frappe._dict({
            "name": "test-bot",
            "connectors": [frappe._dict({"connector": i, "enabled": 1}) for i in ids],
        }),
    }


def _lead(**kw):
    values = {"doctype": "CRM Lead", "first_name": "Tool", "last_name": "Test",
              "lead_name": "Tool Test", "mobile_no": "+919000000777",
              "email": "tool.test@example.com"}
    values.update(kw)
    return frappe.get_doc(values).insert(ignore_permissions=True)


class TestToolsAreGated(FrappeTestCase):
    """The fence, not the prompt, is what stops a bot doing the wrong thing."""

    def test_unknown_tool_is_refused(self):
        with self.assertRaises(ToolError):
            tools.execute("delete_everything", {}, _ctx(_lead()))

    def test_tool_without_its_connector_is_refused(self):
        ctx = _ctx(_lead(), connector_ids=["crm_notes"])
        with self.assertRaises(ToolError) as e:
            tools.execute("assign_to", {"user": "Administrator"}, ctx)
        self.assertIn("not attached", str(e.exception))

    def test_every_catalogued_tool_is_dispatchable(self):
        """A tool advertised to the model must exist, or the bot is told about
        capabilities it cannot use."""
        lead = _lead()
        for c in catalog.CONNECTORS:
            for t in c["tools"]:
                try:
                    tools.execute(t["name"], {}, _ctx(lead))
                except ToolError as err:
                    self.assertNotIn("There is no tool called", str(err),
                                     f"{t['name']} is offered but not dispatchable")
                except Exception:
                    pass  # bad args are fine here; absence is not


class TestCrmOperations(FrappeTestCase):
    def test_list_options_returns_real_values(self):
        out = tools.execute("list_options", {"doctype": "CRM Deal", "field": "status"},
                            _ctx(_lead()))
        self.assertTrue(out["options"], "a bot with no option list invents a status")

    def test_list_options_rejects_a_free_text_field(self):
        with self.assertRaises(ToolError):
            tools.execute("list_options", {"doctype": "CRM Lead", "field": "lead_name"},
                          _ctx(_lead()))

    def test_assign_to_requires_a_real_user(self):
        with self.assertRaises(ToolError):
            tools.execute("assign_to", {"user": "nobody@nowhere.test"}, _ctx(_lead()))

    def test_add_comment_needs_text(self):
        with self.assertRaises(ToolError):
            tools.execute("add_comment", {"comment": "   "}, _ctx(_lead()))

    def test_log_call_survives_a_missing_from_number(self):
        """`from` is mandatory on CRM Call Log; a blank one used to abort."""
        out = tools.execute("log_call", {"type": "Outgoing", "status": "No Answer"},
                            _ctx(_lead()))
        self.assertTrue(out["call_log"])

    def test_search_finds_a_lead_by_name(self):
        lead = _lead(lead_name="Findable Person", first_name="Findable")
        out = tools.execute("search", {"query": "Findable"}, _ctx(lead))
        self.assertTrue(any(r["name"] == lead.name for r in out["results"]))

    def test_search_needs_a_query(self):
        with self.assertRaises(ToolError):
            tools.execute("search", {}, _ctx(_lead()))


class TestConvertLead(FrappeTestCase):
    def test_it_creates_a_deal_and_marks_the_lead_converted(self):
        lead = _lead(lead_name="Convert Me", organization="Convert Co")
        out = tools.execute("convert_lead", {}, _ctx(lead))
        self.assertTrue(frappe.db.exists("CRM Deal", out["deal"]))
        self.assertTrue(frappe.db.get_value("CRM Lead", lead.name, "converted"))

    def test_converting_twice_is_refused(self):
        lead = _lead(lead_name="Convert Once", organization="Once Co")
        tools.execute("convert_lead", {}, _ctx(lead))
        with self.assertRaises(ToolError) as e:
            tools.execute("convert_lead", {"lead": lead.name}, _ctx(lead))
        self.assertIn("already been converted", str(e.exception))

    def test_it_needs_both_connectors(self):
        """Converting writes a Deal, so granting only Leads must not be enough."""
        lead = _lead(lead_name="Half Granted")
        with self.assertRaises(ToolError):
            tools.execute("convert_lead", {}, _ctx(lead, connector_ids=["crm_leads"]))


def tearDownModule():
    for nm in ("Tool Test", "Findable Person", "Convert Me", "Convert Once", "Half Granted"):
        for lead in frappe.get_all("CRM Lead", filters={"lead_name": nm}, pluck="name"):
            for deal in frappe.get_all("CRM Deal", filters={"lead": lead}, pluck="name"):
                frappe.delete_doc("CRM Deal", deal, force=True, ignore_permissions=True)
            frappe.delete_doc("CRM Lead", lead, force=True, ignore_permissions=True)
    frappe.db.commit()
