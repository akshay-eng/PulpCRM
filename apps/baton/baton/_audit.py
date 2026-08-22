import frappe

def run():
    from baton.bots import catalog
    cons = catalog.CONNECTORS if hasattr(catalog, "CONNECTORS") else catalog.connectors()
    print(f"{len(cons)} connectors\n")
    all_tools = []
    for c in cons:
        tools = [t["name"] for t in c.get("tools", [])]
        all_tools += tools
        dts = c.get("doctypes") or []
        print(f"  {c['id']:<18} {', '.join(tools) or '(none)'}")
        if dts: print(f"  {'':<18} doctypes: {', '.join(dts)}")
    print(f"\ntotal distinct tools: {len(set(all_tools))}")
    print(sorted(set(all_tools)))
