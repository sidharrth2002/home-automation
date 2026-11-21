"""The Claude Desktop MCP server: protocol handshake, tool listing and calls (the core API is faked; no network).

Run: .venv/bin/python -m tests.test_home_mcp
"""
import importlib.util
import json
from pathlib import Path

from core import client

spec = importlib.util.spec_from_file_location("home_mcp_main", Path(__file__).parent.parent / "home_mcp" / "__main__.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


def run():
    init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})
    r = init["result"]
    assert r["protocolVersion"] == "2025-06-18" and "tools" in r["capabilities"]
    assert "Portfolio sources" in r["instructions"], "the skill's format guide is shared"
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    assert mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"] == -32601

    tools = {t["name"]: t for t in mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})["result"]["tools"]}
    assert {"get_portfolio", "put_portfolio_source", "get_document", "patch_document"} <= set(tools)
    assert tools["put_portfolio_source"]["inputSchema"]["required"] == ["source", "document"]

    calls = []

    def fake(method, path, body=None, if_version=None):
        calls.append((method, path, body, if_version))
        if path.endswith("/forbidden"):
            raise client.CoreError(403, "not allowed")
        return {"ok": True}
    mcp.api = fake
    call = lambda name, args: mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                         "params": {"name": name, "arguments": args}})["result"]
    out = call("put_portfolio_source", {"source": "nsandi", "document": {"name": "NS&I"}})
    assert not out["isError"] and json.loads(out["content"][0]["text"]) == {"ok": True}
    assert calls[-1] == ("PUT", "/v1/portfolio/nsandi", {"name": "NS&I"}, None)
    assert call("put_portfolio_source", {"source": "hl", "document": {}})["isError"], "hl is never written by hand"
    call("patch_document", {"collection": "finance", "key": "plan", "fields": {"a": 1}, "if_version": 3})
    assert calls[-1] == ("PATCH", "/v1/state/finance/plan", {"a": 1}, 3)
    call("get_document", {"collection": "finance", "key": "a/b"})
    assert calls[-1][1] == "/v1/state/finance/a%2Fb", "path segments are escaped"
    denied = call("get_document", {"collection": "x", "key": "forbidden"})
    assert denied["isError"] and "403" in denied["content"][0]["text"]
    ok = call("set_premium_bonds_holder", {"holder": "1234 5678-90"})
    assert not ok["isError"] and calls[-1] == ("PUT", "/v1/state/finance/premium_bonds_holder", {"holder": "1234567890"}, None)
    for bad in ("12", "not a number!", ""):
        assert call("set_premium_bonds_holder", {"holder": bad})["isError"], bad
    assert call("missing_arg", {})["isError"] and call("get_document", {})["isError"]
    print("home mcp OK")


if __name__ == "__main__":
    run()
