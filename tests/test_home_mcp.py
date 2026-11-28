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
    out = call("api_request", {"method": "POST", "path": "/v1/tasks", "body": {"kind": "agent", "title": "t"}})
    assert not out["isError"] and calls[-1] == ("POST", "/v1/tasks", {"kind": "agent", "title": "t"}, None)
    call("api_request", {"method": "get", "path": "/v1/portfolio/hl/snapshots"})
    assert calls[-1][:2] == ("GET", "/v1/portfolio/hl/snapshots"), "reading HL is fine"
    for bad in ({"method": "PUT", "path": "/v1/portfolio/t212", "body": {}}, {"method": "DELETE", "path": "/v1/portfolio/hl"},
                {"method": "POST", "path": "/v1/tasks/claim", "body": {}}, {"method": "POST", "path": "/v1/tasks/3/finish"},
                {"method": "GET", "path": "/etc/passwd"}, {"method": "GET", "path": "/v1/../x"}, {"method": "HEAD", "path": "/v1/me"}):
        assert call("api_request", bad)["isError"], bad
    spec = {"paths": {"/v1/tasks": {"post": {"summary": "Queue", "requestBody": {"$ref": "#/components/schemas/NewTask"}}},
                      "/v1/me": {"get": {"summary": "Me"}}},
            "components": {"schemas": {"NewTask": {"properties": {"x": {"$ref": "#/components/schemas/Inner"}}},
                                       "Inner": {"type": "object"}, "Unused": {}}}}
    mcp.api = lambda method, path, body=None, if_version=None: spec
    listing = json.loads(call("api_schema", {})["content"][0]["text"])
    assert "POST /v1/tasks  Queue" in listing and "GET /v1/me  Me" in listing
    detail = json.loads(call("api_schema", {"path": "/v1/tasks"})["content"][0]["text"])
    assert list(detail["paths"]) == ["/v1/tasks"] and set(detail["schemas"]) == {"NewTask", "Inner"}
    mcp.api = fake
    assert call("missing_arg", {})["isError"] and call("get_document", {})["isError"]
    http_transport()
    print("home mcp OK")


def http_transport():
    """Over HTTP: a token the core accepts is needed, web pages from other origins are refused, and tool calls run
    with the caller's own token (so the core applies that token's scopes)."""
    import threading
    import urllib.error
    import urllib.request
    import http.server

    good = {"good-token"}

    def fake_core(method, path, body=None, token=None, if_version=None, timeout=10):
        assert token, "never an empty token (client.call would use the admin one)"
        if token not in good:
            raise client.CoreError(401, "bad token")
        return {"name": "claude"}
    seen = []
    mcp.client.call, real_call = fake_core, mcp.client.call
    mcp.api, real_api = (lambda method, path, body=None, if_version=None: seen.append(mcp.token()) or {"ok": True}), mcp.api
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), mcp.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/mcp"

    def post(msg, token="good-token", origin=None, path=url):
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {}),
                   **({"Origin": origin} if origin else {})}
        req = urllib.request.Request(path, data=json.dumps(msg).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                body = r.read()
                return r.status, json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            return e.code, None
    try:
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        assert post(ping)[0] == 200 and post(ping)[1]["result"] == {}
        assert post(ping, token=None)[0] == 401, "no token"
        assert post(ping, token="wrong")[0] == 401, "a token the core refuses"
        assert post(ping, origin="https://evil.example")[0] == 403, "a web page from elsewhere"
        assert post({"jsonrpc": "2.0", "method": "notifications/initialized"})[0] == 202
        assert post(ping, path=url.replace("/mcp", "/other"))[0] == 404
        status, out = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "get_portfolio", "arguments": {}}})
        assert status == 200 and not out["result"]["isError"] and seen == ["good-token"], "the caller's token"
        assert mcp.CALLER.get() is None, "and only for that request"
        try:
            urllib.request.urlopen(url, timeout=5)
            raise AssertionError("GET should be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 405
    finally:
        server.shutdown()
        mcp.client.call, mcp.api = real_call, real_api


if __name__ == "__main__":
    run()
