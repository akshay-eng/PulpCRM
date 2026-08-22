"""Borrowed tools.

An MCP server is another program's toolbox. The tests that matter are not that
a call works — they are that a tool nobody switched on cannot be called, from
either direction.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from baton.bots import mcp
from baton.bots.tools import ToolError, execute

SERVER = "T MCP Server"


def _server(**kw):
    if frappe.db.exists("Baton MCP Server", SERVER):
        doc = frappe.get_doc("Baton MCP Server", SERVER)
    else:
        doc = frappe.new_doc("Baton MCP Server")
        doc.server_name = SERVER
    doc.update({"enabled": 1, "transport": "Streamable HTTP",
                "url": "http://localhost:9/mcp", "timeout": 5, **kw})
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="Baton MCP Server")
    return doc


def _with_tools(pairs):
    """pairs: [(tool_name, enabled)]"""
    doc = _server()
    doc.set("tools", [])
    for name, on in pairs:
        doc.append("tools", {"tool_name": name, "enabled": 1 if on else 0,
                             "description": f"{name} does something",
                             "input_schema": json.dumps(
                                 {"type": "object",
                                  "properties": {"path": {"type": "string",
                                                          "description": "a path"}},
                                  "required": ["path"]})})
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="Baton MCP Server")
    return doc


class _Run:
    name = "t-mcp-run"


def _ctx(connector_ids):
    return {"doc": None, "run": _Run(),
            "bot": frappe._dict({
                "name": "t-mcp-bot",
                "connectors": [frappe._dict({"connector": i, "enabled": 1})
                               for i in connector_ids]})}


class TestNaming(FrappeTestCase):
    def test_names_are_namespaced_per_server(self):
        """Two servers offering `search` must not collide."""
        a = mcp.tool_name_for("Alpha Tools", "search")
        b = mcp.tool_name_for("Beta Tools", "search")
        self.assertNotEqual(a, b)

    def test_a_name_round_trips(self):
        name = mcp.tool_name_for(SERVER, "read_text_file")
        slug, tool = mcp.parse_tool_name(name)
        self.assertEqual(tool, "read_text_file")
        self.assertEqual(slug, frappe.scrub(SERVER))

    def test_a_builtin_name_is_not_mistaken_for_mcp(self):
        self.assertEqual(mcp.parse_tool_name("send_whatsapp"), (None, None))
        self.assertEqual(mcp.parse_tool_name("convert_lead"), (None, None))


class TestDiscoveryIsNotPermission(FrappeTestCase):
    """The property this whole design rests on."""

    def test_a_discovered_tool_starts_disabled(self):
        doc = _with_tools([("read_text_file", False), ("write_file", False)])
        self.assertTrue(all(not r.enabled for r in doc.tools))
        self.assertEqual(mcp.allowed_tools(SERVER), [])

    def test_calling_a_disabled_tool_is_refused(self):
        _with_tools([("write_file", False)])
        with self.assertRaises(mcp.MCPError) as e:
            mcp.call(SERVER, "write_file", {"path": "/tmp/x"})
        self.assertIn("not switched on", str(e.exception))

    def test_rediscovery_keeps_what_was_enabled_and_adds_the_rest_off(self):
        _with_tools([("read_text_file", True)])

        async def _fake(session):
            return [{"name": "read_text_file", "description": "", "input_schema": {}},
                    {"name": "delete_everything", "description": "", "input_schema": {}}]

        with patch.object(mcp, "_run", side_effect=lambda doc, fn: [
                {"name": "read_text_file", "description": "", "input_schema": {}},
                {"name": "delete_everything", "description": "", "input_schema": {}}]):
            mcp.discover(SERVER)

        doc = frappe.get_doc("Baton MCP Server", SERVER)
        state = {r.tool_name: bool(r.enabled) for r in doc.tools}
        self.assertTrue(state["read_text_file"], "an enabled tool was silently revoked")
        self.assertFalse(state["delete_everything"],
                         "a newly appearing tool must not arrive switched on")


class TestBotGating(FrappeTestCase):
    def test_connector_must_be_attached(self):
        _with_tools([("read_text_file", True)])
        name = mcp.tool_name_for(SERVER, "read_text_file")
        with self.assertRaises(ToolError) as e:
            execute(name, {"path": "/tmp/x"}, _ctx(["crm_leads"]))
        self.assertIn("not attached", str(e.exception))

    def test_a_disabled_server_offers_nothing(self):
        _with_tools([("read_text_file", True)])
        _server(enabled=0)
        self.assertNotIn(f"mcp_{frappe.scrub(SERVER)}",
                         {c["id"] for c in mcp.connectors()})

    def test_a_server_with_no_enabled_tools_is_not_a_connector(self):
        _with_tools([("read_text_file", False)])
        self.assertNotIn(f"mcp_{frappe.scrub(SERVER)}",
                         {c["id"] for c in mcp.connectors()})

    def test_an_enabled_tool_becomes_a_connector_with_params(self):
        _with_tools([("read_text_file", True), ("write_file", False)])
        con = next(c for c in mcp.connectors()
                   if c["id"] == f"mcp_{frappe.scrub(SERVER)}")
        names = [t["label"] for t in con["tools"]]
        self.assertIn("read_text_file", names)
        self.assertNotIn("write_file", names, "a disabled tool was advertised to the model")
        params = con["tools"][0]["params"]
        self.assertEqual(params[0]["name"], "path")
        self.assertTrue(params[0]["required"])


class TestErrorSurfacing(FrappeTestCase):
    def test_a_task_group_error_is_unwrapped(self):
        """"unhandled errors in a TaskGroup" names the wrapper and hides the
        cause; every failure looked identical until this unwrapped them."""
        inner = AttributeError("'Tool' object has no attribute 'inputSchema'")
        group = BaseExceptionGroup("unhandled errors in a TaskGroup", [inner])
        flattened = mcp._flatten(group)
        self.assertIn("inputSchema", flattened)
        self.assertIn("AttributeError", flattened)


def tearDownModule():
    if frappe.db.exists("Baton MCP Server", SERVER):
        frappe.delete_doc("Baton MCP Server", SERVER, force=True, ignore_permissions=True)
    frappe.db.commit()
