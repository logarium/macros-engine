"""
MACROS Engine v4.0 — MCP Server (Thin Bridge)
Claude Desktop connects to this via stdio. It bridges to the game server HTTP API.

Claude's role: provide creative content when the engine requests it.
Claude does NOT run T&P, travel, or manage game flow.

Tools:
  Creative flow:
    get_creative_requests     — Pull pending requests from engine
    submit_creative_response  — Push creative content back to engine
  State inspection (read-only):
    get_game_state            — Compact state summary
    get_clock_detail          — Individual clock inspection
    get_npcs                  — NPC list
    get_factions              — Faction list
  Manual corrections:
    advance_clock             — Manual clock advance
    set_clock                 — Set clock to specific value
    add_fact                  — Add narrative fact
    roll_dice                 — Dice roll
    log_event                 — Log entry
"""

import sys
import os
import json

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)

from mcp.server.fastmcp import FastMCP

server = FastMCP("gammaria-engine")

GAME_SERVER = "http://localhost:8000"


def _get(path: str) -> str:
    """HTTP GET to the game server. Returns response text."""
    import urllib.request
    try:
        url = f"{GAME_SERVER}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        return json.dumps({"error": f"Game server unavailable: {e}"})


def _post(path: str, data: dict = None, raw_body: str = None) -> str:
    """HTTP POST to the game server. Returns response text."""
    import urllib.request
    try:
        url = f"{GAME_SERVER}{path}"
        if raw_body:
            body = raw_body.encode("utf-8")
        else:
            body = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        return json.dumps({"error": f"Game server unavailable: {e}"})


# ─────────────────────────────────────────────────────
# CREATIVE FLOW — The core of the new architecture
# ─────────────────────────────────────────────────────

@server.tool()
def get_creative_requests() -> str:
    """
    Get pending creative requests from the game engine.
    The engine queues these when it needs creative content (narration,
    clock audit review, NPAG resolution, encounter narration, etc.).

    If requests are pending, read each one and generate the creative
    content described in its 'type', 'context', and 'constraints' fields.
    Then call submit_creative_response with your output.

    If no requests are pending, the engine doesn't need anything from you.
    """
    result = _get("/api/creative/pending")
    data = json.loads(result)

    if not data.get("pending"):
        return "No pending creative requests. The engine is not waiting for content."

    count = data.get("request_count", 0)
    requests = data.get("requests", [])

    output = [f"PENDING CREATIVE REQUESTS ({count})", ""]
    output.append("Process each request below. Return a JSON response matching the format shown at the end.")
    output.append("")

    for req in requests:
        output.append(f"--- [{req['id']}] {req['type']} ---")

        # Context
        ctx = req.get("context", {})
        for k, v in ctx.items():
            if isinstance(v, list) and len(v) > 0:
                output.append(f"  {k}:")
                for item in v[:10]:
                    if isinstance(item, dict):
                        output.append(f"    - {json.dumps(item)}")
                    else:
                        output.append(f"    - {item}")
            elif isinstance(v, dict):
                output.append(f"  {k}: {json.dumps(v)}")
            else:
                output.append(f"  {k}: {v}")

        # Constraints
        constraints = req.get("constraints", {})
        if constraints:
            output.append(f"  CONSTRAINTS: {json.dumps(constraints)}")
        output.append("")

    # Response format
    output.append("=" * 50)
    output.append("RESPONSE FORMAT — call submit_creative_response with this JSON:")
    output.append('{')
    output.append('  "responses": [')
    for i, req in enumerate(requests):
        comma = "," if i < len(requests) - 1 else ""
        output.append(f'    {{"id": "{req["id"]}", "type": "{req["type"]}", '
                      f'"content": "your creative text here", '
                      f'"state_changes": []}}{comma}')
    output.append('  ]')
    output.append('}')
    output.append("")
    output.append("state_changes types: clock_advance, clock_reduce, fact, npc_update")
    output.append("Only include state_changes when mechanically justified.")

    return "\n".join(output)


@server.tool()
def submit_creative_response(response_json: str) -> str:
    """
    Submit your creative responses back to the game engine.
    response_json must be a JSON string with this structure:
    {
      "responses": [
        {
          "id": "cr_001",
          "type": "NARR_ARRIVAL",
          "content": "Your narration text here",
          "state_changes": []
        }
      ]
    }
    Include one response for each pending request.
    """
    result = _post("/api/creative/submit", data={"response_json": response_json})
    data = json.loads(result)

    if data.get("success"):
        applied = data.get("responses_applied", 0)
        calls = data.get("call_count", 0)
        return (f"Creative content applied. {applied} responses processed. "
                f"Total Claude calls this session: {calls}.")
    else:
        return f"Error: {data.get('error', 'Unknown error')}"


# ─────────────────────────────────────────────────────
# STATE INSPECTION (read-only)
# ─────────────────────────────────────────────────────

@server.tool()
def get_game_state() -> str:
    """
    Get a summary of the current game state.
    Shows session, date, zone, phase, clocks, engines, recent log.
    """
    result = _get("/api/state")
    data = json.loads(result)

    if "error" in data:
        return f"Error: {data['error']}"

    meta = data.get("meta", {})
    lines = [
        f"SESSION: {meta.get('session_id', '?')}",
        f"DATE: {meta.get('in_game_date', '?')}",
        f"ZONE: {meta.get('pc_zone', '?')}",
        f"PHASE: {data.get('phase', '?')}",
        f"INTENSITY: {meta.get('campaign_intensity', '?')}",
        f"SEASON: {meta.get('season', '?')}",
        "",
        f"ACTIVE CLOCKS ({len(data.get('active_clocks', []))}):",
    ]

    for c in data.get("active_clocks", [])[:15]:
        pct = int(100 * c["progress"] / max(c["max_progress"], 1))
        cad = " [CADENCE]" if c.get("is_cadence") else ""
        lines.append(f"  {c['name']}: {c['progress']}/{c['max_progress']} ({pct}%){cad}")

    fired = data.get("fired_clocks", [])
    if fired:
        lines.append(f"\nFIRED TRIGGERS ({len(fired)}):")
        for c in fired:
            lines.append(f"  {c['name']}: {c.get('trigger_text', '')}")

    pending = data.get("creative_pending", 0)
    if pending:
        lines.append(f"\nCREATIVE PENDING: {pending} requests")

    return "\n".join(lines)


@server.tool()
def get_clock_detail(clock_name: str) -> str:
    """Get detailed information about a specific clock."""
    result = _get("/api/state")
    data = json.loads(result)

    all_clocks = (data.get("active_clocks", []) +
                  data.get("fired_clocks", []) +
                  data.get("halted_clocks", []))

    for c in all_clocks:
        if clock_name.lower() in c.get("name", "").lower():
            return (f"Clock: {c['name']}\n"
                    f"  Progress: {c['progress']}/{c['max_progress']}\n"
                    f"  Status: {c.get('status', '?')}\n"
                    f"  Owner: {c.get('owner', '?')}\n"
                    f"  Cadence: {c.get('is_cadence', False)}\n"
                    f"  Trigger fired: {c.get('trigger_fired', False)}\n"
                    f"  Trigger text: {c.get('trigger_text', '—')}")

    return f"Clock not found: {clock_name}"


@server.tool()
def get_npcs(zone: str = "") -> str:
    """List NPCs, optionally filtered by zone."""
    result = _get("/api/state")
    data = json.loads(result)

    npcs = data.get("companions", []) + data.get("other_npcs", [])
    if zone:
        npcs = [n for n in npcs if n.get("zone", "").lower() == zone.lower()]

    if not npcs:
        return f"No NPCs found{' in ' + zone if zone else ''}."

    lines = [f"NPCs ({len(npcs)}):"]
    for n in npcs:
        comp = " *" if n.get("is_companion") else ""
        wp = " [WITH PC]" if n.get("with_pc") else ""
        lines.append(f"  {n['name']}{comp} @ {n.get('zone', '?')} | "
                     f"{n.get('role', '?')} | {n.get('status', '?')}{wp}")
    return "\n".join(lines)


@server.tool()
def get_factions() -> str:
    """List all factions."""
    result = _get("/api/state")
    data = json.loads(result)

    factions = data.get("factions", [])
    if not factions:
        return "No factions registered."

    lines = [f"FACTIONS ({len(factions)}):"]
    for f in factions:
        lines.append(f"  {f['name']} | {f.get('status', '?')} | "
                     f"{f.get('disposition', '?')} | {f.get('trend', '—')}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────
# MANUAL CORRECTIONS
# ─────────────────────────────────────────────────────

@server.tool()
def advance_clock(clock_name: str, reason: str) -> str:
    """Manually advance a clock by 1. Provide exact name and reason."""
    # This goes directly to the game loop's state via the API
    # For now, we load state directly since manual corrections
    # bypass the normal creative flow
    from models import state_from_json
    result = _get("/api/state")
    return f"Manual clock advance requested: {clock_name} ({reason}). Use the game UI for state mutations."


@server.tool()
def add_fact(fact: str) -> str:
    """Add a narrative fact to the game state."""
    return f"Fact noted: {fact}. Use submit_creative_response with state_changes for official facts."


@server.tool()
def roll_dice(expression: str = "2d6") -> str:
    """Roll dice. Supports: 1d6, 2d6, 1d8, 1d20, etc."""
    from dice import roll_dice as _roll
    try:
        result = _roll(expression)
        return f"Roll {expression} = {result['dice']} = {result['total']}"
    except Exception as e:
        return f"Error: {e}"


@server.tool()
def log_event(event_type: str, detail: str) -> str:
    """Log a mechanical event to the audit trail."""
    return f"Logged: [{event_type}] {detail}"


if __name__ == "__main__":
    server.run(transport="stdio")
