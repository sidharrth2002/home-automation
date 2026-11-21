"""The home state for Claude Desktop: an MCP server (stdio) over the core API, the desktop-chat twin of the
home-state skill (skills/home-state) that Claude Code sessions use.

    python home_mcp          (Claude Desktop starts it; bin/install-mcp adds it to claude_desktop_config.json)

Standard library only (the MCP SDK's dependencies clash with the core's FastAPI pins). It speaks MCP's stdio
transport: one JSON-RPC message per line on stdin/stdout; anything else goes to stderr. It uses the token in
~/.config/home-core/token (made by bin/install-skill: the `claude` token,
writing doc/*, portfolio/*, price/*, live/*, media/*, task/*, schedule/*), so it can read everything and write only what that token allows. The portfolio format and the
rules for writing come from skills/home-state/SKILL.md, so the two stay the same.
"""
import json
import os
import re
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
                "whose data shows on their Hub, TV and phone widget within seconds. Use it to view or change anything "
                "there: their portfolio (HL, Trading 212, HSBC, NS&I Premium Bonds, savings), snapshots, prices, "
                "daily valuations, Premium Bonds prize checks, finance notes, plans and to-dos, the live sensors the "
                "services report, the photo library, and background tasks and schedules. The named tools cover the "
                "common cases; api_schema lists every endpoint and api_request calls any of them. Read before "
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


def set_holder(a):
    holder = re.sub(r"[\s-]", "", str(a.get("holder", "")))
    if not re.fullmatch(r"[A-Za-z0-9]{6,20}", holder):
        raise ValueError("that doesn't look like a Premium Bonds holder number (letters and digits, from the NS&I "
                         "app or a prize letter; not a bond number)")
    api("PUT", "/v1/state/finance/premium_bonds_holder", {"holder": holder})
    return {"saved": True, "next": "The home system is checking NS&I's prize checker now; the result shows on the Hub "
                                   "(Cash card) within a minute."}


WORKER_ONLY = re.compile(r"^/v1/tasks/(claim|\d+/(heartbeat|finish))$")
AUTOMATIC_PATH = re.compile(r"^/v1/portfolio/(hl|t212)(/|$)")


def schema(a):
    """The API's endpoints (method, path, summary), or the full description of the ones matching `path`."""
    spec = api("GET", "/openapi.json")
    want = a.get("path")
    if not want:
        return [f"{m.upper()} {path}  {op.get('summary') or ''}".rstrip()
                for path, ops in spec["paths"].items() for m, op in ops.items()]
    ops = {path: o for path, o in spec["paths"].items() if want in path}
    names = set(re.findall(r'#/components/schemas/([\w.-]+)', json.dumps(ops)))
    for _ in range(3):  # schemas that refer to other schemas
        names |= set(re.findall(r'#/components/schemas/([\w.-]+)', json.dumps(
            [spec["components"]["schemas"][n] for n in names if n in spec["components"]["schemas"]])))
    return {"paths": ops, "schemas": {n: spec["components"]["schemas"][n] for n in sorted(names)
                                      if n in spec["components"]["schemas"]}}


def request(a):
    method, path = str(a.get("method", "GET")).upper(), str(a.get("path", ""))
    if method not in ("GET", "PUT", "PATCH", "POST", "DELETE"):
        raise ValueError(f"method {method}?")
    if not path.startswith("/v1/") or ".." in path:
        raise ValueError("path must start with /v1/ (see api_schema)")
    if method != "GET" and AUTOMATIC_PATH.match(path.split("?")[0]):
        raise ValueError("HL and Trading 212 are fetched automatically; never write them by hand")
    if WORKER_ONLY.match(path.split("?")[0]):
        raise ValueError("that endpoint is for the task worker only")
    return api(method, path, a.get("body"), a.get("if_version"))


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
    "set_premium_bonds_holder": ("Save the user's NS&I Premium Bonds holder number, so the home system can check "
                                 "for prizes after each monthly draw (it checks straight away too). Only use a "
                                 "number the user gave you. It is sent only to NS&I's public prize checker.",
                                 {"holder": {"type": "string", "description": "the holder number"}}, ["holder"],
                                 set_holder),
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
    "api_schema": ("Every endpoint of the home state API (method, path, summary). Pass `path` (or part of one, e.g. "
                   "'/v1/tasks') for the full request and response formats of the matching endpoints.",
                   {"path": {"type": "string"}}, [], schema),
    "api_request": ("Call any endpoint of the home state API (see api_schema), e.g. GET /v1/valuations, "
                    "GET /v1/portfolio/hsbc/snapshots, PUT /v1/prices/<isin>, POST /v1/tasks, GET /v1/live, "
                    "GET /v1/media/onedrive. Writes need the token's scope; HL and Trading 212 can't be written.",
                    {"method": {"type": "string", "enum": ["GET", "PUT", "PATCH", "POST", "DELETE"]},
                     "path": {"type": "string", "description": "starting /v1/, with any ?query"},
                     "body": {"description": "JSON body for PUT, PATCH and POST"},
                     "if_version": {"type": "integer", "description": "for document edits: the version you read"}},
                    ["method", "path"], request),
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
