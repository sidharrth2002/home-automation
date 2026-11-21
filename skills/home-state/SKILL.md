---
name: home-state
description: Read and update the user's home "core" state service (their central local database behind the Hub, TV and widget). Use when the user asks to update their portfolio or holdings (e.g. HSBC, savings, Premium Bonds), record finance notes, plans or to-dos for the home system, check what the Hub is showing, or otherwise read or write the home state. Not for controlling lights or the TV.
---

# Home state (core API)

The user's home system has a central state service ("core") on their machine: a SQLite database behind an HTTP API.
What you write there shows up on their Hub, TV screensaver and phone widget within a second or two.

Talk to it with the helper next to this file (Python 3, no dependencies):

```bash
python3 ~/.claude/skills/home-state/home_state.py me                 # who this token is, what it may write
python3 ~/.claude/skills/home-state/home_state.py get portfolio      # every source + the merged summary
python3 ~/.claude/skills/home-state/home_state.py get portfolio/hsbc
python3 ~/.claude/skills/home-state/home_state.py put portfolio/hsbc file.json   # or - for stdin
python3 ~/.claude/skills/home-state/home_state.py get state/finance/plan
python3 ~/.claude/skills/home-state/home_state.py patch state/finance/plan '{"next_review": "2027-01-17"}'
python3 ~/.claude/skills/home-state/home_state.py get audit?entity=portfolio
python3 ~/.claude/skills/home-state/home_state.py schema             # the full OpenAPI description
```

Paths are the API's, after `/v1/`. The token lives in `~/.config/home-core/token` (never print it or put it in
files you write). The token only writes what its scopes allow (`me` shows them); a 403 means out of scope, so tell
the user rather than working around it.

## Portfolio sources

Each source (`hsbc`, `nsandi`, ...) is one document holding its **full current state**. A PUT replaces it and keeps
the old one as a snapshot, so always send everything for that source, not just what changed: read it first, edit,
write it back.

```json
{"name": "HSBC", "kind": "manual", "as_of": "2026-11-21",
 "accounts": [
   {"name": "GIA", "type": "gia", "cash": 0,
    "holdings": [
      {"name": "Example Index Fund C Inc", "id": "gb00b0000000", "value": 1000.00, "units": 512.3},
      {"name": "Example Fund (buying)", "id": "gb00b0000001", "value": 500.00, "status": "pending", "settles": "2026-11-23"}]},
   {"name": "Regular Saver", "type": "savings", "cash": 1000.00, "interest_pct": 5.0, "matures": "2027-05-01"},
   {"name": "Current account", "type": "current", "cash": 900.00, "in_total": false}]}
```

- Money is GBP. `value` is what a holding is worth now; for a pending buy it's the amount being invested.
- Account `type`: isa, gia, sipp, pension, lisa, savings, premium_bonds, current, cash, other.
- Give a fund its ISIN as `id` and its `units`: core then revalues it daily from fund prices. Without units, the
  value stays what you wrote until you write again.
- `"in_total": false` keeps an account on record but out of the headline total (e.g. a current account).
- Extra fields are kept (e.g. `"notes"`), but put long-form notes in a document instead (below).
- HL (`hl`) and Trading 212 (`t212`) are fetched automatically; never write those.

## Documents

Free-form JSON documents in collections, e.g. `state/finance/plan`, `state/finance/todos`. PUT replaces, PATCH
merges top-level fields (null removes one); each write is a new version (`state/<c>/<k>/versions`). Send
`If-Match: <version>` (helper: `--if-match N`) when editing something you read, to avoid overwriting a newer edit.

## Before writing

Show the user what you're about to change (old vs new figures), then write, then confirm with a `get`. Every write
is recorded with this token's name in the audit log (`get audit`).
