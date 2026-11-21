"""The home state for Claude Desktop: an MCP server (stdio) over the core API, the desktop-chat twin of the
home-state skill (skills/home-state) that Claude Code sessions use.

    python home_mcp          (Claude Desktop starts it; bin/install-mcp adds it to claude_desktop_config.json)

Standard library only (the MCP SDK's dependencies clash with the core's FastAPI pins). It speaks MCP's stdio
transport: one JSON-RPC message per line on stdin/stdout; anything else goes to stderr. It uses the token in
~/.config/home-core/token (made by bin/install-skill, scoped: e.g. portfolio/hsbc*, portfolio/nsandi*,
doc/finance/*), so it can read everything and write only what that token allows. The portfolio format and the
rules for writing come from skills/home-state/SKILL.md, so the two stay the same.
"""
import json
import os
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import client  # noqa: E402

TOKEN_FILE = Path(os.environ.get("HOME_CORE_TOKEN_FILE", Path.home() / ".config" / "home-core" / "token"))
SKILL = ROOT / "skills" / "home-state" / "SKILL.md"
AUTOMATIC = {"hl", "t212"}  # fetched by the investments service; never written by hand
PROTOCOL = "2025-06-18"


def guide() -> str:
    """The skill's portfolio and documents sections (from "## Portfolio sources" on), without its CLI examples."""
    text = SKILL.read_text()
    return text[text.index("## Portfolio sources"):] if "## Portfolio sources" in text else ""


INSTRUCTIONS = ("This connects to the user's home system: a central state service on their Mac (SQLite behind an API) "
                "whose data shows on their Hub, TV and phone widget within seconds. Use it to read or update their "
                "portfolio (e.g. HSBC, NS&I Premium Bonds and savings), finance notes, plans and to-dos. Read before "
                "you write, show the user old vs new figures before writing, and confirm with a read afterwards. A "
                "403 means the token may not write there: tell the user rather than working around it.\n\n")


def seg(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")


def api(method: str, path: str, body=None, if_version=None):
    return client.call(method, path, body, token=TOKEN_FILE.read_text().strip(), if_version=if_version, timeout=20)


def put_source(a):
    if a["source"] in AUTOMATIC:
        raise ValueError(f"{a['source']} is fetched automatically; never write it by hand")
    return api("PUT", f"/v1/portfolio/{seg(a['source'])}", a["document"])


TOOLS = {
    "whoami": ("Who this connection is and which parts of the home state it may write.", {}, [],
               lambda a: api("GET", "/v1/me")),
    "get_portfolio": ("Every portfolio source now (HL, Trading 212, HSBC, NS&I, ...) plus the merged summary the Hub "
                      "shows.", {}, [], lambda a: api("GET", "/v1/portfolio")),
    "get_portfolio_source": ("One portfolio source's current full document, e.g. 'hsbc' or 'nsandi'. Read this "
                             "before replacing it.", {"source": {"type": "string"}}, ["source"],
                             lambda a: api("GET", f"/v1/portfolio/{seg(a['source'])}")),
    "put_portfolio_source": ("Replace a portfolio source with its FULL current state (a new snapshot; the old one is "
                             "kept). Always send everything for that source, not just what changed: read it first, "
                             "edit, write back. Never write 'hl' or 't212'. Premium Bonds go in 'nsandi' as an "
                             "account named 'Premium Bonds' with type 'premium_bonds'.\n\n" + guide(),
                             {"source": {"type": "string", "description": "e.g. hsbc, nsandi"},
                              "document": {"type": "object", "description": "the source's full state"}},
                             ["source", "document"], put_source),
    "list_documents": ("The documents in a collection, e.g. 'finance'.", {"collection": {"type": "string"}},
                       ["collection"], lambda a: api("GET", f"/v1/state/{seg(a['collection'])}")),
    "get_document": ("A free-form JSON document, e.g. collection 'finance', key 'plan'; includes its version.",
                     {"collection": {"type": "string"}, "key": {"type": "string"}}, ["collection", "key"],
                     lambda a: api("GET", f"/v1/state/{seg(a['collection'])}/{seg(a['key'])}")),
    "put_document": ("Replace a document (any JSON). Pass if_version (from get_document) when editing something you "
                     "read, so a newer edit isn't overwritten.",
                     {"collection": {"type": "string"}, "key": {"type": "string"}, "data": {},
                      "if_version": {"type": "integer"}}, ["collection", "key", "data"],
                     lambda a: api("PUT", f"/v1/state/{seg(a['collection'])}/{seg(a['key'])}", a["data"],
                                   a.get("if_version"))),
    "patch_document": ("Merge top-level fields into a document; a null value removes that field.",
                       {"collection": {"type": "string"}, "key": {"type": "string"}, "fields": {"type": "object"},
                        "if_version": {"type": "integer"}}, ["collection", "key", "fields"],
                       lambda a: api("PATCH", f"/v1/state/{seg(a['collection'])}/{seg(a['key'])}", a["fields"],
                                     a.get("if_version"))),
    "get_audit": ("Who changed what, newest first (counts, never amounts). entity e.g. 'portfolio' or 'document'.",
                  {"entity": {"type": "string"}, "limit": {"type": "integer"}}, [],
                  lambda a: api("GET", "/v1/audit?" + urllib.parse.urlencode(
                      {k: v for k, v in (("entity", a.get("entity")), ("limit", a.get("limit") or 50)) if v}))),
}


def tool_list() -> list[dict]:
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": props, "required": req}}
            for n, (d, props, req, _) in TOOLS.items()]


def call_tool(name: str, args: dict) -> dict:
    if name not in TOOLS:
        return {"content": [{"type": "text", "text": f"no such tool: {name}"}], "isError": True}
    try:
        out = TOOLS[name][3](args or {})
        return {"content": [{"type": "text", "text": json.dumps(out, indent=1, ensure_ascii=False)}], "isError": False}
    except FileNotFoundError:
        msg = f"no token at {TOKEN_FILE}: run bin/install-skill in the home-automation repo"
    except client.CoreError as e:
        msg = str(e)
    except OSError as e:
        msg = f"the home core isn't reachable ({e}); is the home system running (./home status)?"
    except (KeyError, ValueError) as e:
        msg = f"bad request: {e}"
    return {"content": [{"type": "text", "text": msg}], "isError": True}


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message -> its response (None for notifications)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notifications (initialized, cancelled) need no answer
    if method == "initialize":
        result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or PROTOCOL,
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "home-state", "version": "1"},
                  "instructions": INSTRUCTIONS + guide()}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        p = msg.get("params") or {}
        result = call_tool(p.get("name"), p.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
