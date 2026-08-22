"""Borrowing tools from an MCP server.

This is the capability that separates a bot which can only do what Baton ships
from one that can do whatever you plug into it -- the same mechanism OpenClaw
uses, run inside the CRM so the fence stays here.

Two rules, both enforced in code:

  * **Discovery is not permission.** Listing a server's tools writes them to the
    server row with `enabled = 0`. A bot may call a tool only once a person has
    ticked it and attached the server's connector. A server that adds a
    `delete_everything` tool tomorrow gains nothing by it.
  * **Credentials stay on the server row.** They are read at call time from an
    encrypted field, never written into a bot definition and never returned to
    the browser.

The SDK is asyncio and Frappe is not, so each call runs its own event loop.
That costs a few milliseconds per call and keeps the calling code synchronous,
which is the right trade here -- tool calls are already network-bound.
"""

import asyncio
import json

import frappe
from frappe.utils import cint, now_datetime

TOOL_PREFIX = "mcp"


class MCPError(frappe.ValidationError):
    pass


def tool_name_for(server, tool):
    """Namespaced so two servers offering `search` cannot collide."""
    slug = frappe.scrub(server)
    return f"{TOOL_PREFIX}_{slug}__{tool}"


def parse_tool_name(name):
    """`mcp_my_server__search` -> ("my_server", "search"), or (None, None)."""
    if not name or not name.startswith(TOOL_PREFIX + "_"):
        return None, None
    rest = name[len(TOOL_PREFIX) + 1:]
    if "__" not in rest:
        return None, None
    slug, tool = rest.split("__", 1)
    return slug, tool


def server_by_slug(slug):
    for name in frappe.get_all("Baton MCP Server", filters={"enabled": 1}, pluck="name"):
        if frappe.scrub(name) == slug:
            return name
    return None


# --------------------------------------------------------------- connection

def _server_config(name):
    doc = frappe.get_cached_doc("Baton MCP Server", name)
    if not doc.enabled:
        raise MCPError(f"MCP server '{name}' is switched off.")
    return doc


async def _with_session(doc, fn):
    """Open a session on the configured transport and hand it to `fn`."""
    from mcp import ClientSession

    if doc.transport == "Stdio":
        from mcp.client.stdio import StdioServerParameters, stdio_client

        if not doc.command:
            raise MCPError(f"MCP server '{doc.name}' has no command set.")
        env = {}
        if doc.env_json:
            try:
                env = json.loads(doc.env_json) or {}
            except (ValueError, TypeError):
                raise MCPError(f"Environment on '{doc.name}' is not valid JSON.")

        params = StdioServerParameters(
            command=doc.command,
            args=[a.strip() for a in (doc.args or "").splitlines() if a.strip()],
            env=env or None,
            cwd=doc.cwd or None,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    from mcp.client.streamable_http import streamable_http_client

    if not doc.url:
        raise MCPError(f"MCP server '{doc.name}' has no URL set.")

    headers = {}
    if doc.auth_header:
        value = doc.get_password("auth_value", raise_exception=False)
        if value:
            headers[doc.auth_header] = value

    import httpx2

    async with httpx2.AsyncClient(headers=headers,
                                  timeout=cint(doc.timeout) or 60) as http_client:
        async with streamable_http_client(doc.url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)


def _flatten(exc):
    """Pull the real error out of a TaskGroup's ExceptionGroup.

    The SDK runs its transport in a task group, so anything that goes wrong
    surfaces as "unhandled errors in a TaskGroup (1 sub-exception)" -- which
    names the wrapper and hides the cause. Unwrap it or every failure looks
    identical.
    """
    subs = getattr(exc, "exceptions", None)
    if not subs:
        return f"{type(exc).__name__}: {exc}"
    return "; ".join(_flatten(s) for s in subs)


def _run(doc, fn):
    """Run one async interaction on its own loop.

    The timeout lives on the transport's HTTP client and on the process, not on
    an outer wait_for: cancelling into the SDK's task group mid-handshake turns
    a clean timeout into an ExceptionGroup and can leave a child process behind.
    """
    try:
        return asyncio.run(_with_session(doc, fn))
    except MCPError:
        raise
    except BaseException as e:
        raise MCPError(f"{doc.name}: {_flatten(e)[:400]}")


# ---------------------------------------------------------------- discovery

@frappe.whitelist()
def discover(server):
    """Ask a server what it offers, and record it with everything switched off."""
    frappe.only_for(["System Manager", "Sales Manager"])
    doc = frappe.get_doc("Baton MCP Server", server)

    async def _list(session):
        result = await session.list_tools()
        return [{
            "name": t.name,
            "description": (t.description or "")[:500],
            # SDK 2.0 uses input_schema; earlier releases used inputSchema.
            "input_schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None),
        } for t in result.tools]

    try:
        found = _run(doc, _list)
    except MCPError as e:
        doc.last_error = str(e)[:1000]
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        return {"ok": False, "error": str(e)[:400]}

    # Keep whatever was already allowed; new tools arrive switched off.
    previously_allowed = {r.tool_name for r in (doc.tools or []) if r.enabled}
    doc.set("tools", [])
    for t in found:
        doc.append("tools", {
            "tool_name": t["name"],
            "description": t["description"],
            "input_schema": json.dumps(t["input_schema"] or {}, indent=1)[:4000],
            "enabled": 1 if t["name"] in previously_allowed else 0,
        })
    doc.last_discovered_at = now_datetime()
    doc.last_error = None
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    from baton.audit import log_action
    log_action("mcp.discover", actor_type="SYSTEM", reference_doctype="Baton MCP Server",
               reference_name=server, output={"tools": [t["name"] for t in found]},
               reason=f"{len(found)} tool(s); {len(previously_allowed)} kept enabled")

    return {"ok": True, "tools": found, "count": len(found),
            "enabled": sorted(previously_allowed)}


@frappe.whitelist()
def test_connection(server):
    frappe.only_for(["System Manager", "Sales Manager"])
    result = discover(server)
    if not result.get("ok"):
        return result
    return {"ok": True, "message": f"Connected. {result['count']} tool(s) offered.",
            "tools": [t["name"] for t in result["tools"]]}


# ------------------------------------------------------------------- calling

def allowed_tools(server):
    """Only what a person ticked."""
    doc = frappe.get_cached_doc("Baton MCP Server", server)
    return [r for r in (doc.tools or []) if r.enabled]


def call(server, tool, arguments):
    """Invoke one tool. Refuses anything not explicitly allowed."""
    doc = _server_config(server)

    if tool not in {r.tool_name for r in allowed_tools(server)}:
        raise MCPError(
            f"'{tool}' is not switched on for MCP server '{server}'. "
            "Tools are discovered off and enabled deliberately."
        )

    async def _call(session):
        result = await session.call_tool(tool, arguments or {})
        parts = []
        for block in (result.content or []):
            text = getattr(block, "text", None)
            parts.append(text if text is not None else f"[{getattr(block, 'type', 'content')}]")
        return {"output": "\n".join(parts)[:6000],
                "is_error": bool(getattr(result, "isError", False))}

    return _run(doc, _call)


def connectors():
    """Enabled MCP servers, shaped like built-in connectors for the bot canvas."""
    out = []
    for name in frappe.get_all("Baton MCP Server", filters={"enabled": 1}, pluck="name"):
        tools = allowed_tools(name)
        if not tools:
            continue
        doc = frappe.get_cached_doc("Baton MCP Server", name)
        out.append({
            "id": f"{TOOL_PREFIX}_{frappe.scrub(name)}",
            "label": name,
            "group": "MCP servers",
            "icon": "plug",
            "description": doc.description or f"Tools borrowed from {name}.",
            "doctypes": [],
            "mcp_server": name,
            "tools": [{
                "name": tool_name_for(name, r.tool_name),
                "label": r.tool_name,
                "description": (r.description or f"{r.tool_name} on {name}")[:300],
                "params": _params_from_schema(r.input_schema),
            } for r in tools],
        })
    return out


def _params_from_schema(schema_json):
    """Turn a JSON Schema into the flat param list the prompt builder renders."""
    try:
        schema = json.loads(schema_json or "{}")
    except (ValueError, TypeError):
        return []
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    params = []
    for key, spec in list(props.items())[:12]:
        params.append({
            "name": key,
            "type": (spec or {}).get("type") or "string",
            "required": key in required,
            "description": ((spec or {}).get("description") or "")[:160],
        })
    return params
