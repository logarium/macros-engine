"""
MACROS Engine v4.1 — MCP Server
Full delta-parity: every field in NSV-DELTA is stored, tracked, and rendered.

v4.1 changes:
  - All creative requests go to pending queue (no auto-sampling)
  - Player processes them via get_pending_requests + apply_llm_judgments

v3.1 changes:
  - NEW: set_session_id — set/increment session counter
  - UPDATED: save_game — canonical naming: Session XX - DD MonthName - ZoneName.json
  - UPDATED: _auto_save — uses canonical naming
  - UPDATED: list_saves, _get_state — find both old (save_*) and new (Session *) patterns

v3.0 changes (Delta Parity):
  - NEW: update_zone — create or update zone with threat_level and situation_summary
  - NEW: update_ua — create or update Unknown Actor entries
  - NEW: update_session_meta — store tone_shift, pacing, next_session_pressure
  - NEW: update_divine — create or update divine/metaphysical consequences
  - NEW: update_risk_flag — create or update NPC risk flags
  - NEW: update_seed_override — track canonical truth restrictions
  - UPDATED: update_npc — now accepts negative_knowledge parameter
  - UPDATED: update_pc_state — now accepts affection_summary and reputation_levels_json
  - UPDATED: export_html_report — renders all 12 previously missing sections
  - UPDATED: engines section — full detail with roll history, authority tier, scope
  - UPDATED: zone section — zone summary table with threat levels

v2.2 changes (Phase 2 — delta replacement):
  - update_npc, update_faction, update_relationship, add_discovery
  - update_pc_state, update_companion, add_session_summary
  - add_thread, resolve_thread, add_loss
  - get_npcs, get_npc_detail, get_factions
  - export_html_report, export_save
"""

import sys
import os
import json
import glob
from datetime import datetime

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)

from mcp.server.fastmcp import FastMCP
from models import (
    GameState, state_to_json, state_from_json,
    NPC, CompanionDetail, Faction, Relationship, NPCRiskFlag,
    Discovery, PCState, UnresolvedThread,
)
from engine import run_day, run_time_and_pressure
from campaign_state import load_gammaria_state
from dice import roll_dice as _roll_dice
from claude_integration import apply_response, build_state_summary

server = FastMCP("macros-engine")

_state: GameState = None
_pending_llm_requests: list = []
_day_logs: list = []


def _get_state() -> GameState:
    global _state
    if _state is None:
        data_dir = os.path.join(ENGINE_DIR, "data")
        if os.path.isdir(data_dir):
            # Find saves with both old (save_*.json) and new (Session *.json) naming
            saves = sorted(
                glob.glob(os.path.join(data_dir, "save_*.json")) +
                glob.glob(os.path.join(data_dir, "Session *.json")),
                key=os.path.getmtime, reverse=True
            )
            if saves:
                try:
                    with open(saves[0], "r", encoding="utf-8") as f:
                        _state = state_from_json(f.read())
                    return _state
                except Exception:
                    pass
        _state = load_gammaria_state()
    return _state


def _data_dir() -> str:
    d = os.path.join(ENGINE_DIR, "data")
    os.makedirs(d, exist_ok=True)
    return d


def _canonical_save_name(state: GameState) -> str:
    """Generate canonical save filename: Session XX - DD MonthName - ZoneName.json"""
    sid = str(state.session_id).zfill(2)
    date_str = state.in_game_date if state.in_game_date else "unknown"
    zone_str = state.pc_zone if state.pc_zone else "unknown"
    # Sanitize for filesystem
    safe_date = date_str.replace("/", "-").replace("\\", "-").replace(":", "-")
    safe_zone = zone_str.replace("/", "-").replace("\\", "-").replace(":", "-")
    return f"Session {sid} - {safe_date} - {safe_zone}.json"


def _auto_save(state: GameState) -> str:
    data_dir = _data_dir()
    auto_fn = _canonical_save_name(state)
    auto_path = os.path.join(data_dir, auto_fn)
    try:
        with open(auto_path, "w", encoding="utf-8") as f:
            f.write(state_to_json(state))
    except Exception:
        pass
    return auto_fn


def _pending_file_path() -> str:
    return os.path.join(ENGINE_DIR, "data", "pending_creative.json")


def _read_pending_file() -> list:
    """Read pending creative requests from shared file (written by GUI)."""
    path = _pending_file_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("requests", [])
    except Exception:
        return []


def _clear_pending_file():
    """Remove the shared pending file after requests are consumed."""
    path = _pending_file_path()
    if os.path.exists(path):
        os.remove(path)


# ─────────────────────────────────────────────────────
# EXISTING TOOLS (unchanged from v2.1)
# ─────────────────────────────────────────────────────

@server.tool()
def run_tp_days(days: int = 1) -> str:
    """
    Run Time & Pressure for N days (1-30). This is the core mechanical loop.
    Advances the calendar, runs procedural engines, ticks cadence clocks,
    performs clock audits, rolls encounter and NPAG gates.

    Creative requests are queued for manual resolution via get_pending_requests.
    All dice rolls are real. All clock advances are mechanical.
    """
    global _pending_llm_requests, _day_logs

    state = _get_state()

    if days < 1 or days > 30:
        return "Error: days must be 1-30"
    if not state.pc_zone:
        return "Error: PC Zone is blank. Use set_pc_zone first."

    all_logs = []
    new_llm_requests = []

    for i in range(days):
        day_log = run_day(state)
        day_log["day_number"] = i + 1
        all_logs.append(day_log)
        for req in day_log.get("llm_requests", []):
            new_llm_requests.append(req)

    for dl in all_logs:
        state.log({
            "type": "T&P",
            "day": dl.get("date", "?"),
            "steps": dl.get("steps", []),
            "llm_requests": len(dl.get("llm_requests", [])),
        })

    # ── Format mechanical output ──
    output = []
    output.append(f"═══ T&P — {days} DAY(S) ═══")
    output.append(f"Date: {state.in_game_date} | Season: {state.season}")

    for dl in all_logs:
        output.append(f"── {dl.get('date', '?')} ──")
        for step in dl.get("steps", []):
            sn = step["step"]
            r = step.get("result", step.get("results", {}))
            if sn == "date_advance":
                pass
            elif sn.startswith("engine:"):
                en = sn.split(":", 1)[1]
                if r.get("skipped") or r.get("status") == "inert":
                    pass
                elif "roll" in r:
                    output.append(f"  ⚙️ {en}: 2d6={r['roll']['total']} → {r.get('outcome_band','')}")
                    for ce in r.get("clock_effects_applied", []):
                        if not ce.get("skipped") and "error" not in ce:
                            output.append(f"    → {ce['clock']}: {ce.get('old','?')}→{ce.get('new','?')}")
            elif sn == "cadence_clocks":
                for cr in step.get("results", []):
                    if "error" not in cr:
                        output.append(f"  ⏰ {cr['clock']}: {cr['old']}→{cr['new']}/{cr['max']}")
                        if cr.get("trigger_fired"):
                            output.append(f"    🔥 TRG: {cr.get('trigger_text','')}")
            elif sn == "clock_audit":
                for a in r.get("auto_advanced", []):
                    ar = a["advance_result"]
                    output.append(f"  🔍 {a['clock']}: {ar['old']}→{ar['new']}/{ar.get('max','?')}")
                for rv in r.get("needs_llm_review", []):
                    output.append(f"  ❓ {rv['clock']}: review ({len(rv['ambiguous_bullets'])} bullets)")
            elif sn == "encounter_gate":
                rv = r["roll"]["total"]
                output.append(f"  ⚔️ Enc: {'PASS' if r['passed'] else 'fail'} (d6={rv})")
            elif sn == "npag_gate":
                rv = r["roll"]["total"]
                if r["passed"]:
                    output.append(f"  👥 NPAG: PASS (d6={rv}) → {r['npc_count']['count']} NPCs")
                else:
                    output.append(f"  👥 NPAG: fail (d6={rv})")

    # ── All creative requests go to pending queue ──
    if new_llm_requests:
        _day_logs.extend(all_logs)
        _pending_llm_requests.extend(new_llm_requests)
        output.append(f"\n⚡ {len(new_llm_requests)} creative request(s) queued — use get_pending_requests to process")

    _auto_save(state)
    return "\n".join(output)


@server.tool()
def get_pending_requests() -> str:
    """
    Get all pending LLM requests that need creative judgment.
    These are clock audit reviews, NPAG actions, encounter narrations, etc.
    that the mechanical engine cannot resolve — they need narrative judgment.
    Returns the full request payload with all context needed for judgment.
    """
    # Check in-memory (from run_tp_days called via MCP)
    combined = list(_pending_llm_requests)

    # Check shared file (from web UI / GUI running T&P)
    file_requests = _read_pending_file()
    if file_requests:
        combined.extend(file_requests)

    if not combined:
        return "No pending LLM requests."

    output = [f"═══ PENDING ({len(combined)}) ═══", ""]
    output.append("Process each request below. Return a JSON response with "
                  "apply_llm_judgments matching the IDs shown.")
    output.append("")

    for i, req in enumerate(combined):
        req_type = req.get("type", "UNKNOWN")
        # Use request's own ID if present (CreativeRequest format), else assign
        req_id = req.get("id", f"req_{i+1:03d}")
        output.append(f"--- [{req_id}] {req_type} ---")

        # CreativeRequest format: context is a dict, constraints separate
        ctx = req.get("context", {})
        constraints = req.get("constraints", {})

        if isinstance(ctx, dict) and ctx:
            # Rich context — render all keys
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
        elif isinstance(ctx, str) and ctx:
            output.append(f"  Context: {ctx}")

        # Show constraints if present
        if constraints:
            output.append(f"  CONSTRAINTS: {json.dumps(constraints)}")

        # Fallback: render old-format flat keys
        if not ctx and not constraints:
            if req_type == "CLOCK_AUDIT_REVIEW":
                output.append(f"  CLK: {req.get('clock','?')} @ {req.get('progress','?')}")
                for ab in req.get("ambiguous_bullets", []):
                    b = ab.get("bullet", ab) if isinstance(ab, dict) else ab
                    output.append(f"    - {b}")
            elif req_type == "NPAG":
                output.append(f"  Count: {req.get('npc_count', 0)}")
            else:
                for k, v in req.items():
                    if k not in ("type", "id"):
                        output.append(f"  {k}: {str(v)[:200]}")
        output.append("")

    # Response format guide
    output.append("=" * 50)
    output.append("RESPONSE FORMAT — call apply_llm_judgments with this JSON:")
    output.append('{')
    output.append('  "responses": [')
    for i, req in enumerate(combined):
        req_id = req.get("id", f"req_{i+1:03d}")
        req_type = req.get("type", "UNKNOWN")
        comma = "," if i < len(combined) - 1 else ""
        output.append(f'    {{"id": "{req_id}", "type": "{req_type}", '
                      f'"content": "your creative text here", '
                      f'"state_changes": []}}{comma}')
    output.append('  ]')
    output.append('}')
    output.append("")
    output.append("state_changes types: clock_advance, clock_reduce, fact, npc_update")
    output.append("Only include state_changes when mechanically justified.")

    return "\n".join(output)


@server.tool()
def apply_llm_judgments(response_json: str) -> str:
    """
    Apply creative judgments (clock audit decisions, NPAG results, etc.)
    to the game state. Input must be a JSON string with this structure:
    {
      "responses": [
        {
          "id": "req_001",
          "type": "CLOCK_AUDIT_REVIEW",
          "content": "reasoning",
          "state_changes": [
            {"type": "clock_advance", "clock": "Name", "reason": "why"},
            {"type": "fact", "text": "new fact"}
          ]
        }
      ]
    }
    """
    global _pending_llm_requests, _day_logs
    state = _get_state()

    try:
        response = json.loads(response_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON — {e}"
    if "responses" not in response:
        return "Error: JSON must contain 'responses' array"

    entries = apply_response(state, response)

    output = ["═══ LLM JUDGMENTS APPLIED ═══"]
    for e in entries:
        if "content_preview" in e:
            output.append(f"  🤖 [{e['type']}] {e['content_preview']}")
            state.log({"type": "LLM_JUDGMENT", "subtype": e["type"], "detail": e["content_preview"][:120]})
        elif e.get("applied") == "clock_advance":
            r = e["result"]
            output.append(f"    → {r['clock']}: {r['old']}→{r['new']}")
            if r.get("trigger_fired"):
                output.append(f"    🔥 TRG: {r.get('trigger_text','')}")
            state.log({"type": "CLOCK_ADVANCE", "detail": f"{r['clock']}: {r['old']}→{r['new']}", "clock": r["clock"], "old": r["old"], "new": r["new"], "trigger_fired": r.get("trigger_fired", False), "trigger_text": r.get("trigger_text", "")})
        elif e.get("applied") == "clock_reduce":
            output.append(f"    → Clock reduced")
            state.log({"type": "CLOCK_REDUCE", "detail": "Clock reduced (LLM)"})
        elif e.get("applied") == "fact":
            output.append(f"    📌 {e['text'][:80]}")
            state.log({"type": "FACT", "detail": e["text"][:200]})
        elif e.get("error"):
            output.append(f"    ❌ {e['error']}")

    _pending_llm_requests = []
    _day_logs = []
    _clear_pending_file()
    output.append("  ✅ Applied.")
    _auto_save(state)

    # Forward response to web UI game server (if running)
    try:
        import urllib.request
        fwd_req = urllib.request.Request(
            "http://localhost:8000/api/creative/submit_raw",
            data=response_json.encode("utf-8"),
            method="POST",
        )
        fwd_req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(fwd_req, timeout=5) as resp:
            resp.read()
        output.append("  ↪ Forwarded to web UI.")
    except Exception:
        pass  # Web server not running — that's fine

    return "\n".join(output)


@server.tool()
def clear_pending_requests() -> str:
    """
    Emergency escape hatch — clears all pending creative requests.
    Use when the engine is stuck in AWAIT_CREATIVE and needs to be unstuck.
    Discards all queued requests without processing.
    """
    global _pending_llm_requests, _day_logs
    count = len(_pending_llm_requests)
    _pending_llm_requests = []
    _day_logs = []
    _clear_pending_file()
    return f"Cleared {count} in-memory requests. Pending file removed."


@server.tool()
def log_event(event_type: str, detail: str) -> str:
    """
    Log any mechanical event to the master audit trail.
    Use this for everything the engine can't handle automatically:
    NPAG resolutions, EL encounters, BX-PLUG combat, ZONE-FORGE,
    NPC-FORGE, travel events, rulings, LLM decisions, etc.

    event_type: DICE, NPAG, NPAG_RESOLUTION, EL, EL_DEF, BX_COMBAT,
                BX_ROUND, BX_RESULT, TRAVEL, ZONE_FORGE, NPC_FORGE,
                CLOCK_FORGE, CLOCK_AUDIT, RULING, LLM_DECISION,
                SESSION, ENCOUNTER, REACTION, MORALE, ZONE_CHANGE,
                PARTY, LOOT, REST, ABILITY_CHECK, SAVE, TRIGGER,
                NARRATIVE_BEAT, CAN_FORGE, FAC_FORGE, PE_FORGE
    detail: compressed single-line description
    """
    state = _get_state()
    state.log({"type": event_type, "detail": detail[:500]})
    _auto_save(state)
    return f"📋 [{event_type}] {detail[:80]}"


@server.tool()
def get_game_state() -> str:
    """
    Get a comprehensive summary of the current game state.
    Shows session info, date, zone, all active clocks with progress,
    fired triggers, engine status, and recent facts.
    """
    return build_state_summary(_get_state())


@server.tool()
def get_clock_detail(clock_name: str) -> str:
    """
    Get detailed information about a specific clock.
    Includes progress, ADV bullets, HALT conditions, RED conditions,
    trigger on completion, advancement history, and notes.
    """
    state = _get_state()
    clock = state.get_clock(clock_name)
    if not clock:
        matches = [c for c in state.clocks.values() if clock_name.lower() in c.name.lower()]
        if len(matches) == 1:
            clock = matches[0]
        elif len(matches) > 1:
            return f"Multiple matches: {', '.join(m.name for m in matches)}"
        else:
            return f"Clock not found: {clock_name}"

    lines = [f"CLK: {clock.name}", f"  Owner: {clock.owner}", f"  Progress: {clock.progress}/{clock.max_progress}",
             f"  Status: {clock.status}", f"  Cadence: {'Yes' if clock.is_cadence else 'No'}",
             f"  ADV: {'; '.join(clock.advance_bullets) if clock.advance_bullets else '(none)'}",
             f"  HALT: {'; '.join(clock.halt_conditions) if clock.halt_conditions else '(none)'}",
             f"  RED: {'; '.join(clock.reduce_conditions) if clock.reduce_conditions else '(none)'}",
             f"  TRG: {clock.trigger_on_completion or '(none)'}", f"  Fired: {clock.trigger_fired}"]
    if clock.notes:
        lines.append(f"  Notes: {clock.notes}")
    return "\n".join(lines)


@server.tool()
def roll_dice(expression: str = "2d6") -> str:
    """
    Roll dice. Supports standard expressions: 1d6, 2d6, 1d8, 1d20, etc.
    Returns the individual dice and total.
    """
    state = _get_state()
    try:
        result = _roll_dice(expression)
        detail = f"{expression} = {result['dice']} = {result['total']}"
        state.log({"type": "DICE", "detail": detail, "expression": expression, "dice": result["dice"], "total": result["total"]})
        _auto_save(state)
        return f"🎲 {detail}"
    except Exception as e:
        return f"Error: {e}"


@server.tool()
def save_game(filename: str = "") -> str:
    """
    Save the current game state to a JSON file.
    If no filename given, auto-generates canonical name:
    Session XX - DD MonthName - ZoneName.json
    """
    state = _get_state()
    data_dir = _data_dir()
    if not filename:
        filename = _canonical_save_name(state)
    if not filename.endswith(".json"):
        filename += ".json"
    filepath = os.path.join(data_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(state_to_json(state))
    return f"💾 Saved: {filename}"


@server.tool()
def load_game(filename: str) -> str:
    """
    Load game state from a save file.
    Use list_saves to see available files.
    """
    global _state, _pending_llm_requests, _day_logs
    data_dir = _data_dir()
    filepath = os.path.join(data_dir, filename)
    if not os.path.exists(filepath):
        filepath = filepath + ".json" if not filepath.endswith(".json") else filepath
        if not os.path.exists(filepath):
            return f"Error: File not found — {filename}"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            _state = state_from_json(f.read())
        _pending_llm_requests = []
        _day_logs = []
        return (
            f"Loaded: {filename}\n"
            f"  Session {_state.session_id} | {_state.in_game_date} | {_state.pc_zone}\n"
            f"  Run zone_forge to begin session."
        )
    except Exception as e:
        return f"Error loading: {e}"


@server.tool()
def list_saves() -> str:
    """List all available save files."""
    data_dir = _data_dir()
    saves = sorted(
        glob.glob(os.path.join(data_dir, "save_*.json")) +
        glob.glob(os.path.join(data_dir, "Session *.json")),
        key=os.path.getmtime, reverse=True
    )
    if not saves:
        return "No save files found."
    lines = ["Available saves:"]
    for s in saves:
        name = os.path.basename(s)
        mtime = datetime.fromtimestamp(os.path.getmtime(s)).strftime("%Y-%m-%d %H:%M")
        lines.append(f"  {name} ({os.path.getsize(s):,}b, {mtime})")
    return "\n".join(lines)


@server.tool()
def set_pc_zone(zone: str) -> str:
    """
    Set the PC's current zone. Required for T&P to run.
    Common zones: Caras, Vornost, Fort Vanguard, Grey Plains,
    Khuzduk Hills, Khuzdukan, Riverwatch, Fort Seawatch,
    Seawatch Ramparts, Eastern Scarps, Western Scarps, Hinterlands,
    Deep Swamps, Sighing Swamps, Sea of Birds
    """
    state = _get_state()
    old_zone = state.pc_zone
    state.pc_zone = zone
    state.log({"type": "ZONE_CHANGE", "detail": f"{old_zone} → {zone}", "old_zone": old_zone, "new_zone": zone})
    _auto_save(state)
    return f"Zone: {old_zone} → {zone}"


@server.tool()
def set_session_id(session_id: int) -> str:
    """
    Set the current session number. Used at ENDS to increment session counter,
    or to correct a mismatched session_id.
    """
    state = _get_state()
    old = state.session_id
    state.session_id = session_id
    state.log({"type": "SESSION", "detail": f"Session ID: {old} → {session_id}"})
    _auto_save(state)
    return f"📋 Session: {old} → {session_id}"


@server.tool()
def add_fact(fact: str) -> str:
    """Add a narrative fact to the game state."""
    state = _get_state()
    state.add_fact(fact)
    state.log({"type": "FACT", "detail": fact[:300]})
    _auto_save(state)
    return f"📌 {fact}"


@server.tool()
def advance_clock(clock_name: str, reason: str) -> str:
    """
    Manually advance a clock by 1. Use only when mechanically justified.
    Provide the exact clock name and reason for advancement.
    """
    state = _get_state()
    clock = state.get_clock(clock_name)
    if not clock:
        matches = [c for c in state.clocks.values() if clock_name.lower() in c.name.lower()]
        if len(matches) == 1:
            clock = matches[0]
        else:
            return f"Clock not found: {clock_name}"
    if not clock.can_advance():
        return f"Cannot advance {clock.name} — {clock.status}, fired={clock.trigger_fired}"

    result = clock.advance(reason=f"Manual: {reason}", date=state.in_game_date, session=state.session_id)
    state.log({"type": "CLOCK_ADVANCE", "detail": f"{result['clock']}: {result['old']}→{result['new']}/{result.get('max','?')} — {reason}", "clock": result["clock"], "old": result["old"], "new": result["new"], "reason": reason, "trigger_fired": result.get("trigger_fired", False), "trigger_text": result.get("trigger_text", "")})
    _auto_save(state)

    out = f"→ {result['clock']}: {result['old']}→{result['new']}/{result.get('max', '?')}"
    if result.get("trigger_fired"):
        out += f"\n🔥 TRG: {result.get('trigger_text', '')}"
    return out


@server.tool()
def set_clock(clock_name: str, progress: int, reason: str) -> str:
    """
    Set a clock to a specific progress value. For error correction,
    RED bullet processing, or any case where a clock needs to move
    to an arbitrary value (not just +1).
    Handles unfiring triggers if progress drops below max.
    """
    state = _get_state()
    clock = state.get_clock(clock_name)
    if not clock:
        matches = [c for c in state.clocks.values() if clock_name.lower() in c.name.lower()]
        if len(matches) == 1:
            clock = matches[0]
        else:
            return f"Clock not found: {clock_name}"

    old = clock.progress
    old_status = clock.status
    progress = max(0, min(progress, clock.max_progress))
    clock.progress = progress

    if progress < clock.max_progress:
        if clock.trigger_fired:
            clock.trigger_fired = False
            clock.trigger_fired_text = ""
        if clock.status == "trigger_fired":
            clock.status = "active"

    if progress >= clock.max_progress and not clock.trigger_fired:
        clock.trigger_fired = True
        clock.trigger_fired_text = clock.trigger_on_completion
        clock.status = "trigger_fired"

    clock.last_advanced_session = state.session_id
    clock.last_advanced_date = state.in_game_date

    entry = f"SET_CLOCK: {clock.name} {old}→{progress}/{clock.max_progress} ({reason})"
    if old_status != clock.status:
        entry += f" [status: {old_status}→{clock.status}]"
    state.log({"type": "SET_CLOCK", "detail": entry, "clock": clock.name, "old": old, "new": progress, "reason": reason})
    _auto_save(state)

    out = f"⚙️ {clock.name}: {old}→{progress}/{clock.max_progress} ({reason})"
    if old_status != clock.status:
        out += f"\n  Status: {old_status}→{clock.status}"
    if progress >= clock.max_progress and clock.trigger_fired:
        out += f"\n  🔥 TRG: {clock.trigger_on_completion}"
    return out


@server.tool()
def set_date(date_str: str, reason: str) -> str:
    """
    Set the in-game date to a specific value. For error correction
    or any case where the date needs to be adjusted.
    Format: "28 Ilrym", "3 Reapmere", etc.
    """
    state = _get_state()
    old_date = state.in_game_date

    # Parse day number from date string
    parts = date_str.strip().split()
    if len(parts) >= 2:
        try:
            state.day_of_month = int(parts[0])
            state.month = parts[1]
        except ValueError:
            return f"Error: cannot parse date '{date_str}'. Format: '28 Ilrym'"
    else:
        return f"Error: cannot parse date '{date_str}'. Format: '28 Ilrym'"

    state.in_game_date = date_str
    state.log({"type": "SET_DATE", "detail": f"SET_DATE: {old_date}→{date_str} ({reason})", "old_date": old_date, "new_date": date_str, "reason": reason})
    _auto_save(state)

    return f"📅 Date: {old_date}→{date_str} ({reason})"


# ─────────────────────────────────────────────────────
# PHASE 2: NARRATIVE STATE TOOLS (v2.2)
# ─────────────────────────────────────────────────────

@server.tool()
def update_npc(
    name: str,
    zone: str = "",
    status: str = "",
    role: str = "",
    trait: str = "",
    appearance: str = "",
    faction: str = "",
    objective: str = "",
    knowledge: str = "",
    negative_knowledge: str = "",
    next_action: str = "",
    with_pc: str = "",
    is_companion: str = "",
    history_event: str = "",
) -> str:
    """
    Create or update an NPC in the save file.
    If NPC exists, only provided fields are updated (empty strings are ignored).
    If NPC does not exist, a new entry is created.
    with_pc and is_companion: pass "true" or "false" as strings.
    history_event: if provided, appends to the NPC's history log.
    """
    state = _get_state()
    npc = state.get_npc(name)
    is_new = npc is None

    if is_new:
        npc = NPC(name=name, created_session=state.session_id)

    # Update only provided fields
    if zone: npc.zone = zone
    if status: npc.status = status
    if role: npc.role = role
    if trait: npc.trait = trait
    if appearance: npc.appearance = appearance
    if faction: npc.faction = faction
    if objective: npc.objective = objective
    if knowledge: npc.knowledge = knowledge
    if negative_knowledge: npc.negative_knowledge = negative_knowledge
    if next_action: npc.next_action = next_action
    if with_pc.lower() in ("true", "yes"):
        npc.with_pc = True
    elif with_pc.lower() in ("false", "no"):
        npc.with_pc = False
    if is_companion.lower() in ("true", "yes"):
        npc.is_companion = True
    elif is_companion.lower() in ("false", "no"):
        npc.is_companion = False

    npc.last_updated_session = state.session_id

    if history_event:
        npc.history.append({
            "session": state.session_id,
            "date": state.in_game_date,
            "event": history_event,
        })

    state.npcs[name] = npc
    action = "Created" if is_new else "Updated"
    state.log({"type": "NPC_FORGE" if is_new else "NPC_UPDATE",
               "detail": f"{action}: {name} @ {npc.zone} | {npc.role} | {npc.trait}"})
    _auto_save(state)
    return f"👤 {action} NPC: {name} @ {npc.zone}"


@server.tool()
def update_companion(
    npc_name: str,
    motivation_shift: str = "",
    loyalty_change: str = "",
    trust_in_pc: str = "",
    affection_json: str = "",
    stress_or_fatigue: str = "",
    grievances: str = "",
    agency_notes: str = "",
    future_flashpoints: str = "",
    history_event: str = "",
) -> str:
    """
    Create or update companion detail (PARTY-DELTA replacement).
    npc_name must match an existing NPC entry.
    affection_json: JSON string like {"Thoron": "love", "Suzanne": "aversion"}
    Only provided fields are updated.
    """
    state = _get_state()
    comp = state.companions.get(npc_name)
    is_new = comp is None

    if is_new:
        comp = CompanionDetail(npc_name=npc_name)

    if motivation_shift: comp.motivation_shift = motivation_shift
    if loyalty_change: comp.loyalty_change = loyalty_change
    if trust_in_pc: comp.trust_in_pc = trust_in_pc
    if affection_json:
        try:
            comp.affection_levels = json.loads(affection_json)
        except json.JSONDecodeError:
            return f"Error: Invalid affection_json"
    if stress_or_fatigue: comp.stress_or_fatigue = stress_or_fatigue
    if grievances: comp.grievances = grievances
    if agency_notes: comp.agency_notes = agency_notes
    if future_flashpoints: comp.future_flashpoints = future_flashpoints

    if history_event:
        comp.history.append({
            "session": state.session_id,
            "date": state.in_game_date,
            "event": history_event,
        })

    state.companions[npc_name] = comp
    action = "Created" if is_new else "Updated"
    state.log({"type": "PARTY", "detail": f"{action} companion: {npc_name} | trust={comp.trust_in_pc}"})
    _auto_save(state)
    return f"👥 {action} companion: {npc_name}"


@server.tool()
def update_faction(
    name: str,
    status: str = "",
    trend: str = "",
    disposition: str = "",
    last_action: str = "",
    notes: str = "",
    history_event: str = "",
) -> str:
    """
    Create or update a faction in the save file.
    Only provided fields are updated.
    """
    state = _get_state()
    fac = state.get_faction(name)
    is_new = fac is None

    if is_new:
        fac = Faction(name=name, created_session=state.session_id)

    if status: fac.status = status
    if trend: fac.trend = trend
    if disposition: fac.disposition = disposition
    if last_action: fac.last_action = last_action
    if notes: fac.notes = notes

    fac.last_updated_session = state.session_id

    if history_event:
        fac.history.append({
            "session": state.session_id,
            "date": state.in_game_date,
            "event": history_event,
        })

    state.factions[name] = fac
    action = "Created" if is_new else "Updated"
    state.log({"type": "FAC_FORGE" if is_new else "FAC_UPDATE",
               "detail": f"{action}: {name} | {fac.status} | {fac.disposition}"})
    _auto_save(state)
    return f"🏛️ {action} faction: {name}"


@server.tool()
def update_relationship(
    rel_id: str,
    npc_a: str = "",
    npc_b: str = "",
    rel_type: str = "",
    visibility: str = "",
    trust: str = "",
    loyalty: str = "",
    current_state: str = "",
    history_event: str = "",
) -> str:
    """
    Create or update a relationship in the save file.
    rel_id format: REL-NpcA-NpcB-type-NN (e.g., REL-Thoron-Valania-love-01)
    Only provided fields are updated.
    """
    state = _get_state()
    rel = state.get_relationship(rel_id)
    is_new = rel is None

    if is_new:
        if not npc_a or not npc_b:
            return "Error: npc_a and npc_b required for new relationship"
        rel = Relationship(id=rel_id, npc_a=npc_a, npc_b=npc_b,
                           created_session=state.session_id)

    if rel_type: rel.rel_type = rel_type
    if visibility: rel.visibility = visibility
    if trust: rel.trust = trust
    if loyalty: rel.loyalty = loyalty
    if current_state: rel.current_state = current_state

    rel.last_updated_session = state.session_id

    if history_event:
        rel.history.append({
            "session": state.session_id,
            "date": state.in_game_date,
            "event": history_event,
        })

    state.relationships[rel_id] = rel
    action = "Created" if is_new else "Updated"
    state.log({"type": "REL_UPDATE",
               "detail": f"{action}: {rel_id} | {rel.npc_a}↔{rel.npc_b} | {rel.rel_type}"})
    _auto_save(state)
    return f"💞 {action} relationship: {rel.npc_a} ↔ {rel.npc_b} ({rel.rel_type})"


@server.tool()
def add_discovery(
    disc_id: str,
    zone: str = "",
    ua_code: str = "",
    certainty: str = "uncertain",
    visibility: str = "public",
    source: str = "",
    info: str = "",
) -> str:
    """
    Add a discovery to the save file.
    disc_id: unique identifier (e.g., DISC-cairn-desecration-01)
    """
    state = _get_state()

    # Check for duplicate ID
    for d in state.discoveries:
        if d.id == disc_id:
            return f"Error: Discovery {disc_id} already exists"

    disc = Discovery(
        id=disc_id, zone=zone, ua_code=ua_code,
        certainty=certainty, visibility=visibility,
        source=source, info=info,
        session_discovered=state.session_id,
    )
    state.discoveries.append(disc)
    state.log({"type": "CAN_FORGE",
               "detail": f"DISC: {disc_id} | {zone} | {certainty} | {info[:80]}"})
    _auto_save(state)
    return f"🔍 Discovery added: {disc_id}"


@server.tool()
def update_pc_state(
    goals_json: str = "",
    psychological_state_json: str = "",
    secrets_json: str = "",
    reputation: str = "",
    conditions_json: str = "",
    equipment_notes: str = "",
    affection_summary: str = "",
    reputation_levels_json: str = "",
    history_event: str = "",
) -> str:
    """
    Update PC state in the save file. Creates PCState if it doesn't exist.
    goals_json, psychological_state_json, secrets_json, conditions_json:
        JSON arrays like ["goal1", "goal2"]
    reputation_levels_json: JSON object like {"Caras": "1/4", "Frontier": "5/6"}
    Only provided fields are updated.
    """
    state = _get_state()

    if state.pc_state is None:
        state.pc_state = PCState()

    pc = state.pc_state

    if goals_json:
        try:
            pc.goals = json.loads(goals_json)
        except json.JSONDecodeError:
            return "Error: Invalid goals_json"
    if psychological_state_json:
        try:
            pc.psychological_state = json.loads(psychological_state_json)
        except json.JSONDecodeError:
            return "Error: Invalid psychological_state_json"
    if secrets_json:
        try:
            pc.secrets = json.loads(secrets_json)
        except json.JSONDecodeError:
            return "Error: Invalid secrets_json"
    if reputation: pc.reputation = reputation
    if conditions_json:
        try:
            pc.conditions = json.loads(conditions_json)
        except json.JSONDecodeError:
            return "Error: Invalid conditions_json"
    if equipment_notes: pc.equipment_notes = equipment_notes
    if affection_summary: pc.affection_summary = affection_summary
    if reputation_levels_json:
        try:
            pc.reputation_levels = json.loads(reputation_levels_json)
        except json.JSONDecodeError:
            return "Error: Invalid reputation_levels_json"

    if history_event:
        pc.history.append({
            "session": state.session_id,
            "date": state.in_game_date,
            "event": history_event,
        })

    state.log({"type": "PARTY", "detail": f"PC state updated | rep={pc.reputation[:40] if pc.reputation else '—'}"})
    _auto_save(state)
    return f"⚔️ PC state updated"


@server.tool()
def add_session_summary(session_id: str, summary: str) -> str:
    """
    Add or replace a session narrative summary.
    session_id: the session number as a string (e.g., "7")
    summary: 400-600 word narrative summary of the session
    """
    state = _get_state()
    state.session_summaries[session_id] = summary
    state.log({"type": "SESSION", "detail": f"Session {session_id} summary added ({len(summary)} chars)"})
    _auto_save(state)
    return f"📜 Session {session_id} summary saved ({len(summary)} chars)"


@server.tool()
def add_thread(
    thread_id: str,
    zone: str = "",
    description: str = "",
) -> str:
    """
    Add an unresolved narrative thread.
    thread_id: unique identifier (e.g., UT-cairn-desecration-01)
    """
    state = _get_state()

    # Check for duplicate
    for t in state.unresolved_threads:
        if t.id == thread_id:
            return f"Error: Thread {thread_id} already exists"

    thread = UnresolvedThread(
        id=thread_id, zone=zone, description=description,
        session_created=state.session_id,
    )
    state.unresolved_threads.append(thread)
    state.log({"type": "NARRATIVE_BEAT",
               "detail": f"Thread: {thread_id} | {description[:80]}"})
    _auto_save(state)
    return f"🧵 Thread added: {thread_id}"


@server.tool()
def resolve_thread(thread_id: str, resolution: str = "") -> str:
    """
    Mark an unresolved thread as resolved.
    thread_id: the thread to resolve
    resolution: how it was resolved
    """
    state = _get_state()

    for t in state.unresolved_threads:
        if t.id == thread_id:
            t.resolved = True
            t.resolution = resolution
            t.session_resolved = state.session_id
            state.log({"type": "NARRATIVE_BEAT",
                       "detail": f"Thread resolved: {thread_id} | {resolution[:80]}"})
            _auto_save(state)
            return f"✅ Thread resolved: {thread_id}"

    return f"Error: Thread {thread_id} not found"


@server.tool()
def add_loss(description: str) -> str:
    """
    Record an irreversible loss (death, destruction, permanent consequence).
    """
    state = _get_state()
    entry = {
        "description": description,
        "session": state.session_id,
        "date": state.in_game_date,
    }
    state.losses_irreversibles.append(entry)
    state.log({"type": "TRIGGER", "detail": f"LOSS: {description[:120]}"})
    _auto_save(state)
    return f"💀 Loss recorded: {description[:80]}"


@server.tool()
def get_npcs(zone: str = "") -> str:
    """
    List all NPCs, optionally filtered by zone.
    Shows name, zone, role, status, and whether with PC.
    """
    state = _get_state()
    npcs = list(state.npcs.values())
    if zone:
        npcs = [n for n in npcs if n.zone.lower() == zone.lower()]
    if not npcs:
        return f"No NPCs found{' in ' + zone if zone else ''}."

    lines = [f"═══ NPCs ({len(npcs)}) ═══"]
    for n in sorted(npcs, key=lambda x: (x.zone, x.name)):
        wp = " [WITH PC]" if n.with_pc else ""
        comp = " ★" if n.is_companion else ""
        lines.append(f"  {n.name}{comp} @ {n.zone} | {n.role} | {n.status}{wp}")
    return "\n".join(lines)


@server.tool()
def get_npc_detail(npc_name: str) -> str:
    """
    Get full details about a specific NPC including history.
    """
    state = _get_state()
    npc = state.get_npc(npc_name)
    if not npc:
        matches = [n for n in state.npcs.values() if npc_name.lower() in n.name.lower()]
        if len(matches) == 1:
            npc = matches[0]
        elif len(matches) > 1:
            return f"Multiple matches: {', '.join(m.name for m in matches)}"
        else:
            return f"NPC not found: {npc_name}"

    lines = [
        f"NPC: {npc.name}",
        f"  Zone: {npc.zone}",
        f"  Status: {npc.status}",
        f"  Role: {npc.role}",
        f"  Trait: {npc.trait}",
        f"  Faction: {npc.faction or '—'}",
        f"  With PC: {npc.with_pc}",
        f"  Companion: {npc.is_companion}",
        f"  OBJ: {npc.objective}",
        f"  K: {npc.knowledge}",
        f"  ACT: {npc.next_action}",
    ]
    if npc.appearance:
        lines.append(f"  Appearance: {npc.appearance}")
    if npc.bx_hp_max > 0:
        lines.append(f"  BX: AC={npc.bx_ac} HD={npc.bx_hd} hp={npc.bx_hp}/{npc.bx_hp_max} AT=+{npc.bx_at} Dmg={npc.bx_dmg} ML={npc.bx_ml}")
    if npc.history:
        lines.append(f"  History ({len(npc.history)} entries):")
        for h in npc.history[-5:]:
            lines.append(f"    S{h.get('session','?')} {h.get('date','')}: {h.get('event','')}")
    return "\n".join(lines)


@server.tool()
def get_factions() -> str:
    """List all factions with current status and disposition."""
    state = _get_state()
    if not state.factions:
        return "No factions registered."

    lines = [f"═══ FACTIONS ({len(state.factions)}) ═══"]
    for f in sorted(state.factions.values(), key=lambda x: x.name):
        lines.append(f"  {f.name} | {f.status} | {f.disposition} | {f.trend or '—'}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────
# v3.0 TOOLS — DELTA PARITY
# ─────────────────────────────────────────────────────

@server.tool()
def update_zone(
    zone_name: str,
    threat_level: str = "",
    controlling_faction: str = "",
    situation_summary: str = "",
    intensity: str = "",
    description: str = "",
    notes: str = "",
) -> str:
    """
    Create or update a zone in the save file.
    zone_name: exact zone name (e.g., "Khuzdukan", "Grey Plains")
    Only provided fields are updated.
    """
    state = _get_state()
    from models import Zone
    zone = state.zones.get(zone_name)
    if zone is None:
        zone = Zone(name=zone_name)
        state.zones[zone_name] = zone

    if threat_level: zone.threat_level = threat_level
    if controlling_faction: zone.controlling_faction = controlling_faction
    if situation_summary: zone.situation_summary = situation_summary
    if intensity: zone.intensity = intensity
    if description: zone.description = description
    if notes: zone.notes = notes

    state.log({"type": "ZONE_UPDATE", "detail": f"Zone '{zone_name}' updated: threat={threat_level or '—'}"})
    _auto_save(state)
    return f"Zone '{zone_name}' updated. threat_level={zone.threat_level}, faction={zone.controlling_faction}"


@server.tool()
def update_ua(
    ua_id: str,
    zone: str = "",
    description: str = "",
    status: str = "ACTIVE",
    touched: str = "no",
    promotion: str = "no",
    notes: str = "",
) -> str:
    """
    Create or update an Unknown Actor in the UA log.
    ua_id: e.g. "UA-01", "UA-11"
    """
    state = _get_state()
    # Find existing
    existing = None
    for ua in state.ua_log:
        if ua.get("id") == ua_id:
            existing = ua
            break

    if existing is None:
        existing = {"id": ua_id}
        state.ua_log.append(existing)

    if zone: existing["zone"] = zone
    if description: existing["description"] = description
    if status: existing["status"] = status
    if touched: existing["touched"] = touched
    if promotion: existing["promotion"] = promotion
    if notes: existing["notes"] = notes

    state.log({"type": "UA_UPDATE", "detail": f"{ua_id} updated: {description[:60] if description else '—'}"})
    _auto_save(state)
    return f"UA '{ua_id}' updated."


@server.tool()
def update_session_meta(
    session_id: str,
    tone_shift: str = "",
    pacing: str = "",
    next_session_pressure: str = "",
) -> str:
    """
    Store session-level metadata: tone_shift, pacing, next_session_pressure.
    session_id: the session number as a string (e.g., "8")
    """
    state = _get_state()
    meta = state.session_meta.get(session_id, {})

    if tone_shift: meta["tone_shift"] = tone_shift
    if pacing: meta["pacing"] = pacing
    if next_session_pressure: meta["next_session_pressure"] = next_session_pressure

    state.session_meta[session_id] = meta
    state.log({"type": "SESSION_META", "detail": f"Session {session_id} meta updated"})
    _auto_save(state)
    return f"Session {session_id} meta updated."


@server.tool()
def update_divine(
    deity: str,
    nature_of_intervention: str = "",
    cost_incurred: str = "",
    jurisdiction_changed: str = "",
    lingering_effects: str = "",
    visibility: str = "",
) -> str:
    """
    Create or update a divine/metaphysical consequence entry.
    deity: name of deity or power (e.g., "Orcus", "Haadis", "Gramlar")
    """
    state = _get_state()
    # Find existing
    existing = None
    for d in state.divine_metaphysical:
        if d.get("deity") == deity:
            existing = d
            break

    if existing is None:
        existing = {"deity": deity}
        state.divine_metaphysical.append(existing)

    if nature_of_intervention: existing["nature_of_intervention"] = nature_of_intervention
    if cost_incurred: existing["cost_incurred"] = cost_incurred
    if jurisdiction_changed: existing["jurisdiction_changed"] = jurisdiction_changed
    if lingering_effects: existing["lingering_effects"] = lingering_effects
    if visibility: existing["visibility"] = visibility

    state.log({"type": "DIVINE_UPDATE", "detail": f"Divine '{deity}' updated"})
    _auto_save(state)
    return f"Divine/metaphysical entry '{deity}' updated."


@server.tool()
def update_risk_flag(
    npc_name: str,
    risk_type: str = "",
    level: str = "",
    triggers: str = "",
    consequences: str = "",
    visibility: str = "",
    basis: str = "",
) -> str:
    """
    Create or update an NPC risk flag.
    Updates existing flag for this npc_name if one exists, else creates new.
    """
    state = _get_state()
    from models import NPCRiskFlag
    # Find existing
    existing = None
    for rf in state.npc_risk_flags:
        if rf.npc_name == npc_name and (not risk_type or rf.risk_type == risk_type):
            existing = rf
            break

    if existing is None:
        existing = NPCRiskFlag(npc_name=npc_name)
        state.npc_risk_flags.append(existing)

    if risk_type: existing.risk_type = risk_type
    if level: existing.level = level
    if triggers: existing.triggers = triggers
    if consequences: existing.consequences = consequences
    if visibility: existing.visibility = visibility
    if basis: existing.basis = basis

    state.log({"type": "RISK_FLAG", "detail": f"Risk flag on '{npc_name}': {risk_type} ({level})"})
    _auto_save(state)
    return f"Risk flag on '{npc_name}' updated: {risk_type} ({level})"


@server.tool()
def update_seed_override(
    section_affected: str,
    nature_of_change: str = "",
    reason: str = "",
    details: str = "",
) -> str:
    """
    Track a seed override — canonical truth restriction changes.
    section_affected: e.g. "CANONICAL TRUTHS (Ringur restricted lists)"
    """
    state = _get_state()
    # Find existing
    existing = None
    for so in state.seed_overrides:
        if so.get("section_affected") == section_affected:
            existing = so
            break

    if existing is None:
        existing = {"section_affected": section_affected}
        state.seed_overrides.append(existing)

    if nature_of_change: existing["nature_of_change"] = nature_of_change
    if reason: existing["reason"] = reason
    if details: existing["details"] = details

    state.log({"type": "SEED_OVERRIDE", "detail": f"Seed override: {section_affected}"})
    _auto_save(state)
    return f"Seed override '{section_affected}' updated."


def _generate_html_report(state: GameState) -> str:
    """Generate a full delta-equivalent HTML audit report from the current game state."""
    import html as html_mod

    def esc(s):
        return html_mod.escape(str(s)) if s else "\u2014"

    def pct_bar(val, mx, color="#e67e22"):
        pct = int((val / mx) * 100) if mx > 0 else 0
        return (f'<div class="bar-bg"><div class="bar-fill" style="background:{color};'
                f'width:{pct}%"></div></div> <b>{val}/{mx}</b>')

    def clock_color_from_obj(clock):
        if clock.trigger_fired: return "#e74c3c"
        pct = clock.progress / max(clock.max_progress, 1)
        if pct >= 0.75: return "#e74c3c"
        if pct >= 0.5: return "#e67e22"
        return "#27ae60"

    L = []
    L.append("""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>Gammaria \u2014 Full Audit Report</title>
<style>
body{background:#0d0d1a;color:#d4d4d4;font-family:'Segoe UI',Consolas,sans-serif;max-width:1100px;margin:0 auto;padding:24px;line-height:1.5}
h1{color:#e67e22;border-bottom:3px solid #e67e22;padding-bottom:10px;font-size:1.8em;letter-spacing:1px}
h2{color:#f39c12;margin-top:36px;border-bottom:1px solid #555;padding-bottom:6px;font-size:1.3em}
h3{color:#e0c068;margin-top:18px;font-size:1.1em}
h4{color:#aaa;margin-top:12px;font-size:0.95em}
table{border-collapse:collapse;width:100%;margin:8px 0 16px 0;font-size:0.9em}
th{background:#1a1a30;color:#f39c12;text-align:left;padding:7px 10px;border:1px solid #333;font-weight:600}
td{padding:5px 10px;border:1px solid #2a2a2a;vertical-align:top}
tr:nth-child(even){background:#12122a}
tr:nth-child(odd){background:#0d0d1a}
.bar-bg{background:#1a1a30;border-radius:4px;height:12px;width:140px;display:inline-block;vertical-align:middle}
.bar-fill{height:12px;border-radius:4px}
.fired{color:#e74c3c;font-weight:bold}
.muted{color:#666;font-size:0.85em}
.tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:0.8em;margin:1px 2px}
.tag-cadence{background:#2a1a40;color:#9b59b6;border:1px solid #9b59b6}
.tag-fired{background:#3a1a1a;color:#e74c3c;border:1px solid #e74c3c}
.tag-companion{background:#1a2a40;color:#3498db;border:1px solid #3498db}
.tag-with-pc{background:#1a3a1a;color:#27ae60;border:1px solid #27ae60}
.section{background:#111128;padding:14px 16px;border-radius:6px;margin:8px 0;border-left:3px solid #e67e22}
.section-inner{background:#0e0e22;padding:10px 14px;border-radius:4px;margin:6px 0;border-left:2px solid #555}
.meta-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}
.meta-box{background:#111128;padding:10px;border-radius:6px;text-align:center;border:1px solid #2a2a40}
.meta-label{color:#888;font-size:0.8em;text-transform:uppercase;letter-spacing:1px}
.meta-value{color:#f39c12;font-size:1.4em;font-weight:bold}
.summary-block{background:#111128;padding:16px;border-radius:6px;margin:8px 0;line-height:1.7;white-space:pre-wrap;font-size:0.92em}
.hist-entry{margin:3px 0;padding:3px 0;border-bottom:1px solid #1a1a2a;font-size:0.88em}
.hist-session{color:#e67e22;font-weight:bold;min-width:30px;display:inline-block}
.hist-date{color:#888;min-width:70px;display:inline-block}
ul{margin:4px 0;padding-left:20px}
li{margin:2px 0;font-size:0.92em}
.toc{background:#111128;padding:16px;border-radius:6px;margin:16px 0}
.toc a{color:#3498db;text-decoration:none}
.toc a:hover{text-decoration:underline}
.toc li{margin:4px 0}
details{margin:4px 0}
details summary{cursor:pointer;color:#e0c068;font-weight:500}
details summary:hover{color:#f39c12}
</style></head><body>
""")

    # ── HEADER ──
    L.append(f"<h1>GAMMARIA \u2014 Session {state.session_id} Full Audit Report</h1>")
    L.append("<div class='meta-grid'>")
    for label, val in [("Session", state.session_id), ("Date", state.in_game_date),
                       ("Zone", state.pc_zone), ("Season", state.season)]:
        L.append(f"<div class='meta-box'><div class='meta-label'>{label}</div>"
                 f"<div class='meta-value'>{esc(val)}</div></div>")
    L.append("</div>")
    L.append(f"<p class='muted'>Intensity: {esc(state.campaign_intensity)} | "
             f"Seasonal Pressure: {esc(state.seasonal_pressure)}</p>")

    # ── TABLE OF CONTENTS ──
    L.append("""<div class='toc'><strong>Contents</strong><ul>
<li><a href='#summaries'>Session Summaries</a></li>
<li><a href='#session-meta'>Session Meta (Tone / Pacing / Pressure)</a></li>
<li><a href='#pc'>PC State — Thoron</a></li>
<li><a href='#risk-flags'>NPC Risk Flags</a></li>
<li><a href='#clocks'>Clocks (Active)</a></li>
<li><a href='#fired'>Fired Triggers</a></li>
<li><a href='#engines'>Engines</a></li>
<li><a href='#zones'>Zone Summary</a></li>
<li><a href='#companions'>Companions</a></li>
<li><a href='#npcs'>All NPCs</a></li>
<li><a href='#factions'>Factions</a></li>
<li><a href='#relationships'>Relationships</a></li>
<li><a href='#discoveries'>Discoveries</a></li>
<li><a href='#ua-log'>Unknown Anomalies (UA Log)</a></li>
<li><a href='#divine'>Divine / Metaphysical Consequences</a></li>
<li><a href='#threads'>Unresolved Threads</a></li>
<li><a href='#seed-overrides'>Seed Overrides</a></li>
<li><a href='#losses'>Losses &amp; Irreversibles</a></li>
<li><a href='#log'>Adjudication Log</a></li>
</ul></div>""")

    # ── SESSION SUMMARIES (full CNS text) ──
    L.append("<h2 id='summaries'>Session Summaries</h2>")
    for sid_key in sorted(state.session_summaries.keys(),
                          key=lambda x: int(x) if x.isdigit() else 0):
        L.append(f"<h3>Session {esc(sid_key)}</h3>")
        L.append(f"<div class='summary-block'>{esc(state.session_summaries[sid_key])}</div>")

    # ── SESSION META (tone_shift, pacing, next_session_pressure) ──
    L.append("<h2 id='session-meta'>Session Meta — Tone / Pacing / Pressure</h2>")
    if state.session_meta:
        for sid_key in sorted(state.session_meta.keys(),
                              key=lambda x: int(x) if x.isdigit() else 0):
            meta = state.session_meta[sid_key]
            L.append(f"<h3>Session {esc(sid_key)}</h3>")
            L.append("<div class='section'>")
            if meta.get("tone_shift"):
                L.append(f"<b>Tone Shift:</b> {esc(meta['tone_shift'])}<br>")
            if meta.get("pacing"):
                L.append(f"<b>Pacing:</b> {esc(meta['pacing'])}<br>")
            if meta.get("next_session_pressure"):
                L.append(f"<b>Next Session Pressure:</b><br>"
                         f"<div style='white-space:pre-wrap;margin-left:12px;font-size:0.9em'>"
                         f"{esc(meta['next_session_pressure'])}</div>")
            L.append("</div>")
    else:
        L.append("<p class='muted'>No session meta recorded</p>")

    # ── PC STATE ──
    L.append("<h2 id='pc'>PC State \u2014 Thoron</h2>")
    if state.pc_state:
        pc = state.pc_state
        L.append("<div class='section'>")
        if pc.reputation:
            L.append(f"<b>Reputation:</b> {esc(pc.reputation)}<br>")
        if pc.reputation_levels:
            L.append("<b>Reputation Levels:</b><ul>")
            for loc, lvl in pc.reputation_levels.items():
                L.append(f"<li><b>{esc(loc)}:</b> {esc(lvl)}</li>")
            L.append("</ul>")
        if pc.affection_summary:
            L.append(f"<b>Affection Summary:</b> {esc(pc.affection_summary)}<br>")
        if pc.equipment_notes:
            L.append(f"<b>Equipment:</b> {esc(pc.equipment_notes)}<br>")
        for field_name, label in [("goals", "Goals"), ("psychological_state", "Psychological State"),
                                  ("secrets", "Secrets"), ("conditions", "Conditions")]:
            items = getattr(pc, field_name, [])
            if items:
                L.append(f"<h4>{label}</h4><ul>")
                for item in items:
                    L.append(f"<li>{esc(item)}</li>")
                L.append("</ul>")
        if pc.history:
            L.append("<h4>History</h4>")
            for h in pc.history:
                L.append(f"<div class='hist-entry'><span class='hist-session'>"
                         f"S{h.get('session','?')}</span> "
                         f"<span class='hist-date'>{esc(h.get('date',''))}</span> "
                         f"{esc(h.get('event',''))}</div>")
        L.append("</div>")

    # ── NPC RISK FLAGS ──
    L.append("<h2 id='risk-flags'>NPC Risk Flags</h2>")
    if state.npc_risk_flags:
        L.append("<table><tr><th>NPC</th><th>Risk Type</th><th>Level</th>"
                 "<th>Triggers</th><th>Consequences</th><th>Basis</th></tr>")
        for rf in state.npc_risk_flags:
            lvl_col = ("#e74c3c" if rf.level.lower() == "critical"
                       else "#e67e22" if rf.level.lower() == "high"
                       else "#f1c40f" if rf.level.lower() == "moderate"
                       else "#d4d4d4")
            L.append(f"<tr><td><b>{esc(rf.npc_name)}</b></td>"
                     f"<td>{esc(rf.risk_type)}</td>"
                     f"<td style='color:{lvl_col};font-weight:bold'>{esc(rf.level)}</td>"
                     f"<td style='font-size:0.85em'>{esc(rf.triggers)}</td>"
                     f"<td style='font-size:0.85em'>{esc(rf.consequences)}</td>"
                     f"<td style='font-size:0.8em'>{esc(rf.basis)}</td></tr>")
        L.append("</table>")
    else:
        L.append("<p class='muted'>None</p>")

    # ── CLOCKS (ACTIVE — full detail) ──
    L.append("<h2 id='clocks'>Clocks \u2014 Active</h2>")
    active = [c for c in state.clocks.values() if c.status == "active"]
    active.sort(key=lambda c: -c.progress / max(c.max_progress, 1))
    for clock in active:
        col = clock_color_from_obj(clock)
        tags = ""
        if clock.is_cadence:
            tags += " <span class='tag tag-cadence'>CADENCE</span>"
        if clock.trigger_fired:
            tags += " <span class='tag tag-fired'>FIRED</span>"
        L.append("<div class='section'>")
        L.append(f"<b style='color:{col}'>{esc(clock.name)}</b>{tags}<br>")
        L.append(f"<span class='muted'>Owner: {esc(clock.owner)}</span><br>")
        L.append(f"{pct_bar(clock.progress, clock.max_progress, col)}<br>")
        if clock.advance_bullets:
            L.append("<b>ADV:</b><ul>")
            for b in clock.advance_bullets:
                L.append(f"<li>{esc(b)}</li>")
            L.append("</ul>")
        if clock.halt_conditions:
            L.append("<b>HALT:</b><ul>")
            for b in clock.halt_conditions:
                L.append(f"<li>{esc(b)}</li>")
            L.append("</ul>")
        if clock.reduce_conditions:
            L.append("<b style='color:#27ae60'>RED:</b><ul>")
            for b in clock.reduce_conditions:
                L.append(f"<li>{esc(b)}</li>")
            L.append("</ul>")
        if clock.trigger_on_completion:
            L.append(f"<b>TRIGGER:</b> {esc(clock.trigger_on_completion)}<br>")
        if clock.notes:
            L.append(f"<span class='muted'>Notes: {esc(clock.notes)}</span><br>")
        L.append("</div>")

    # ── FIRED TRIGGERS ──
    L.append("<h2 id='fired'>Fired Triggers</h2>")
    fired = [c for c in state.clocks.values() if c.trigger_fired]
    if fired:
        L.append("<table><tr><th>Clock</th><th>Trigger Text</th></tr>")
        for c in fired:
            L.append(f"<tr><td class='fired'>{esc(c.name)}</td>"
                     f"<td>{esc(c.trigger_on_completion)}</td></tr>")
        L.append("</table>")
    else:
        L.append("<p class='muted'>None</p>")

    # ── ENGINES (full detail) ──
    L.append("<h2 id='engines'>Engines</h2>")
    for ename, eng in state.engines.items():
        L.append("<div class='section'>")
        L.append(f"<b>{esc(ename)}</b> <span class='muted'>v{esc(eng.version)}</span> "
                 f"| Status: {esc(eng.status)} | Cadence: {'Yes' if eng.cadence else 'No'}<br>")
        if eng.authority_tier:
            L.append(f"<b>Authority:</b> {esc(eng.authority_tier)} | "
                     f"<b>Zone Scope:</b> {esc(eng.zone_scope)}<br>")
        if eng.state_scope:
            L.append(f"<b>State Scope:</b> {esc(eng.state_scope)}<br>")
        if eng.trigger_event:
            L.append(f"<b>Trigger:</b> {esc(eng.trigger_event)}<br>")
        if eng.resolution_method:
            L.append(f"<b>Resolution:</b> {esc(eng.resolution_method)}<br>")
        if eng.linked_clocks:
            L.append(f"<b>Linked Clocks:</b> {', '.join(esc(c) for c in eng.linked_clocks)}<br>")
        if eng.last_run_date:
            L.append(f"<span class='muted'>Last run: {esc(eng.last_run_date)} "
                     f"(Session {eng.last_run_session})</span><br>")
        if eng.roll_history:
            L.append("<details><summary>Roll History "
                     f"({len(eng.roll_history)} entries)</summary>")
            L.append("<div style='font-size:0.85em;padding:6px'>")
            for rh in eng.roll_history:
                L.append(f"{esc(str(rh))}<br>")
            L.append("</div></details>")
        L.append("</div>")

    # ── ZONE SUMMARY ──
    L.append("<h2 id='zones'>Zone Summary</h2>")
    if state.zones:
        L.append("<table><tr><th>Zone</th><th>Threat</th><th>Intensity</th>"
                 "<th>Controlling Faction</th><th>Situation</th></tr>")
        for zname, zone in sorted(state.zones.items()):
            tl = zone.threat_level or zone.intensity
            tl_col = ("#e74c3c" if tl in ("high", "ESCALATED", "critical")
                      else "#e67e22" if tl in ("moderate", "medium")
                      else "#27ae60" if tl in ("low", "stabilized")
                      else "#d4d4d4")
            L.append(f"<tr><td><b>{esc(zname)}</b></td>"
                     f"<td style='color:{tl_col}'>{esc(tl)}</td>"
                     f"<td>{esc(zone.intensity)}</td>"
                     f"<td>{esc(zone.controlling_faction)}</td>"
                     f"<td style='font-size:0.85em'>{esc(zone.situation_summary or zone.notes)}</td></tr>")
        L.append("</table>")
    else:
        L.append("<p class='muted'>No zones registered</p>")

    # ── COMPANIONS (full detail + companion detail + history) ──
    L.append("<h2 id='companions'>Companions</h2>")
    companion_npcs = [npc for npc in state.npcs.values() if npc.is_companion]
    for npc in companion_npcs:
        comp = state.companions.get(npc.name)
        wp = ("<span class='tag tag-with-pc'>WITH PC</span>"
              if npc.with_pc else f"@ {esc(npc.zone)}")
        L.append(f"<h3><span class='tag tag-companion'>COMPANION</span> "
                 f"{esc(npc.name)} {wp}</h3>")
        L.append("<div class='section'>")
        for label, val in [("Role", npc.role), ("Trait", npc.trait),
                           ("Appearance", npc.appearance), ("Faction", npc.faction),
                           ("Objective", npc.objective), ("Knowledge", npc.knowledge),
                           ("Does NOT Know", npc.negative_knowledge),
                           ("Next Action", npc.next_action)]:
            L.append(f"<b>{label}:</b> {esc(val)}<br>")
        if npc.bx_hp_max > 0:
            L.append(f"<b>BX:</b> AC={npc.bx_ac} HD={npc.bx_hd} "
                     f"HP={npc.bx_hp}/{npc.bx_hp_max} AT=+{npc.bx_at} "
                     f"Dmg={esc(npc.bx_dmg)} ML={npc.bx_ml}<br>")
        # Companion detail block
        if comp:
            L.append("<div class='section-inner'>")
            for label, val in [("Trust in PC", comp.trust_in_pc),
                               ("Motivation Shift", comp.motivation_shift),
                               ("Loyalty Change", comp.loyalty_change),
                               ("Stress/Fatigue", comp.stress_or_fatigue),
                               ("Grievances", comp.grievances),
                               ("Agency Notes", comp.agency_notes),
                               ("Flashpoints", comp.future_flashpoints)]:
                L.append(f"<b>{label}:</b> {esc(val)}<br>")
            if comp.affection_levels:
                L.append("<b>Affection:</b><ul>")
                for k, v in comp.affection_levels.items():
                    L.append(f"<li><b>{esc(k)}:</b> {esc(v)}</li>")
                L.append("</ul>")
            if comp.history:
                L.append("<b>Companion History:</b>")
                for h in comp.history:
                    L.append(f"<div class='hist-entry'>"
                             f"<span class='hist-session'>S{h.get('session','?')}</span> "
                             f"<span class='hist-date'>{esc(h.get('date',''))}</span> "
                             f"{esc(h.get('event',''))}</div>")
            L.append("</div>")
        # NPC history
        if npc.history:
            L.append("<b>NPC History:</b>")
            for h in npc.history:
                L.append(f"<div class='hist-entry'>"
                         f"<span class='hist-session'>S{h.get('session','?')}</span> "
                         f"<span class='hist-date'>{esc(h.get('date',''))}</span> "
                         f"{esc(h.get('event',''))}</div>")
        L.append("</div>")

    # ── ALL NPCs (by zone, with expandable history) ──
    L.append("<h2 id='npcs'>All NPCs</h2>")
    non_comp = [npc for npc in state.npcs.values() if not npc.is_companion]
    zones_seen = sorted(set(npc.zone or "Unknown" for npc in non_comp))
    for zone in zones_seen:
        zone_npcs = [n for n in non_comp if (n.zone or "Unknown") == zone]
        L.append(f"<h3>{esc(zone)}</h3>")
        L.append("<table><tr><th>Name</th><th>Role</th><th>Status</th>"
                 "<th>Trait</th><th>Objective</th></tr>")
        for npc in sorted(zone_npcs, key=lambda n: n.name):
            st = npc.status
            stcol = "#e74c3c" if st == "dead" else "#d4d4d4"
            L.append(f"<tr><td>{esc(npc.name)}</td><td>{esc(npc.role)}</td>"
                     f"<td style='color:{stcol}'>{esc(st)}</td>"
                     f"<td>{esc(npc.trait)}</td>"
                     f"<td>{esc(npc.objective)[:100]}</td></tr>")
        L.append("</table>")
        for npc in sorted(zone_npcs, key=lambda n: n.name):
            if npc.history:
                L.append(f"<details><summary>{esc(npc.name)} \u2014 "
                         f"{len(npc.history)} history entries</summary>")
                for h in npc.history:
                    L.append(f"<div class='hist-entry'>"
                             f"<span class='hist-session'>S{h.get('session','?')}</span> "
                             f"<span class='hist-date'>{esc(h.get('date',''))}</span> "
                             f"{esc(h.get('event',''))}</div>")
                L.append("</details>")

    # ── FACTIONS ──
    L.append("<h2 id='factions'>Factions</h2>")
    L.append("<table><tr><th>Faction</th><th>Status</th><th>Disposition</th>"
             "<th>Trend</th><th>Last Action</th></tr>")
    for fname, fac in sorted(state.factions.items()):
        disp = fac.disposition
        dcol = ("#e74c3c" if disp == "hostile"
                else "#27ae60" if disp in ("friendly", "loyal")
                else "#d4d4d4")
        L.append(f"<tr><td>{esc(fac.name)}</td><td>{esc(fac.status)}</td>"
                 f"<td style='color:{dcol}'>{esc(disp)}</td>"
                 f"<td>{esc(fac.trend)}</td>"
                 f"<td>{esc(fac.last_action)[:80]}</td></tr>")
    L.append("</table>")

    # ── RELATIONSHIPS ──
    L.append("<h2 id='relationships'>Relationships</h2>")
    if state.relationships:
        L.append("<table><tr><th>Parties</th><th>Type</th><th>Trust</th>"
                 "<th>Loyalty</th><th>Current State</th></tr>")
        for rid, rel in state.relationships.items():
            L.append(f"<tr><td>{esc(rel.npc_a)} \u2194 {esc(rel.npc_b)}</td>"
                     f"<td>{esc(rel.rel_type)}</td><td>{esc(rel.trust)}</td>"
                     f"<td>{esc(rel.loyalty)}</td>"
                     f"<td>{esc(rel.current_state)}</td></tr>")
        L.append("</table>")
        # Relationship histories
        rels_with_hist = [r for r in state.relationships.values() if r.history]
        if rels_with_hist:
            for rel in rels_with_hist:
                L.append(f"<details><summary>{esc(rel.npc_a)} \u2194 "
                         f"{esc(rel.npc_b)} \u2014 {len(rel.history)} history entries</summary>")
                for h in rel.history:
                    L.append(f"<div class='hist-entry'>"
                             f"<span class='hist-session'>S{h.get('session','?')}</span> "
                             f"<span class='hist-date'>{esc(h.get('date',''))}</span> "
                             f"{esc(h.get('event',''))}</div>")
                L.append("</details>")
    else:
        L.append("<p class='muted'>None</p>")

    # ── DISCOVERIES ──
    L.append("<h2 id='discoveries'>Discoveries</h2>")
    if state.discoveries:
        L.append("<table><tr><th>ID</th><th>Zone</th><th>Certainty</th>"
                 "<th>Source</th><th>Info</th></tr>")
        for d in state.discoveries:
            cert = d.certainty
            ccol = ("#27ae60" if cert == "confirmed"
                    else "#e67e22" if cert == "uncertain" else "#888")
            L.append(f"<tr><td style='font-size:0.8em'>{esc(d.id)}</td>"
                     f"<td>{esc(d.zone)}</td>"
                     f"<td style='color:{ccol}'>{esc(cert)}</td>"
                     f"<td>{esc(d.source)[:60]}</td>"
                     f"<td>{esc(d.info)}</td></tr>")
        L.append("</table>")
    else:
        L.append("<p class='muted'>None</p>")

    # ── UNKNOWN ANOMALIES (UA LOG) ──
    L.append("<h2 id='ua-log'>Unknown Anomalies (UA Log)</h2>")
    if state.ua_log:
        L.append("<table><tr><th>UA ID</th><th>Status</th><th>Zone</th>"
                 "<th>Description</th><th>Touched</th><th>Promotion</th></tr>")
        for ua in sorted(state.ua_log, key=lambda x: x.get("id", "")):
            st = ua.get("status", "ACTIVE")
            st_col = "#27ae60" if st == "ACTIVE" else "#888"
            L.append(f"<tr><td><b>{esc(ua.get('id',''))}</b></td>"
                     f"<td style='color:{st_col}'>{esc(st)}</td>"
                     f"<td>{esc(ua.get('zone',''))}</td>"
                     f"<td>{esc(ua.get('description',''))}</td>"
                     f"<td>{esc(ua.get('touched','no'))}</td>"
                     f"<td>{esc(ua.get('promotion','no'))}</td></tr>")
        L.append("</table>")
    else:
        L.append("<p class='muted'>None</p>")

    # ── DIVINE / METAPHYSICAL CONSEQUENCES ──
    L.append("<h2 id='divine'>Divine / Metaphysical Consequences</h2>")
    if state.divine_metaphysical:
        for dm in state.divine_metaphysical:
            deity = dm.get("deity", "Unknown")
            L.append(f"<h3>{esc(deity)}</h3>")
            L.append("<div class='section'>")
            for label, key in [("Intervention", "nature_of_intervention"),
                               ("Cost Incurred", "cost_incurred"),
                               ("Jurisdiction Changed", "jurisdiction_changed"),
                               ("Lingering Effects", "lingering_effects"),
                               ("Visibility", "visibility")]:
                val = dm.get(key, "")
                if val:
                    L.append(f"<b>{label}:</b> {esc(val)}<br>")
            L.append("</div>")
    else:
        L.append("<p class='muted'>None</p>")

    # ── UNRESOLVED THREADS ──
    L.append("<h2 id='threads'>Unresolved Threads</h2>")
    open_t = [t for t in state.unresolved_threads if not t.resolved]
    resolved_t = [t for t in state.unresolved_threads if t.resolved]
    if open_t:
        L.append(f"<h3>Open ({len(open_t)})</h3>")
        L.append("<table><tr><th>ID</th><th>Zone</th><th>Session</th>"
                 "<th>Description</th></tr>")
        for t in open_t:
            L.append(f"<tr><td style='font-size:0.8em'>{esc(t.id)}</td>"
                     f"<td>{esc(t.zone)}</td>"
                     f"<td>S{t.session_created}</td>"
                     f"<td>{esc(t.description)}</td></tr>")
        L.append("</table>")
    if resolved_t:
        L.append(f"<details><summary>Resolved ({len(resolved_t)})</summary>")
        L.append("<table><tr><th>ID</th><th>Zone</th><th>Resolution</th></tr>")
        for t in resolved_t:
            L.append(f"<tr><td style='font-size:0.8em'>{esc(t.id)}</td>"
                     f"<td>{esc(t.zone)}</td>"
                     f"<td>{esc(t.resolution)}</td></tr>")
        L.append("</table></details>")

    # ── SEED OVERRIDES ──
    L.append("<h2 id='seed-overrides'>Seed Overrides</h2>")
    if state.seed_overrides:
        for so in state.seed_overrides:
            L.append("<div class='section'>")
            L.append(f"<b>Section:</b> {esc(so.get('section_affected',''))}<br>")
            if so.get("nature_of_change"):
                L.append(f"<b>Nature:</b> {esc(so['nature_of_change'])}<br>")
            if so.get("reason"):
                L.append(f"<b>Reason:</b> {esc(so['reason'])}<br>")
            if so.get("details"):
                L.append(f"<b>Details:</b><br>"
                         f"<div style='white-space:pre-wrap;margin-left:12px;font-size:0.9em'>"
                         f"{esc(so['details'])}</div>")
            L.append("</div>")
    else:
        L.append("<p class='muted'>None</p>")

    # ── LOSSES ──
    L.append("<h2 id='losses'>Losses &amp; Irreversibles</h2>")
    if state.losses_irreversibles:
        for loss in state.losses_irreversibles:
            L.append(f"<div class='section'><b>S{loss.get('session','?')}</b> "
                     f"{esc(loss.get('date',''))} \u2014 "
                     f"{esc(loss.get('description',''))}</div>")
    else:
        L.append("<p class='muted'>None recorded</p>")

    # ── ADJUDICATION LOG ──
    L.append("<h2 id='log'>Adjudication Log</h2>")
    log = state.adjudication_log
    L.append(f"<details><summary>{len(log)} entries (click to expand)</summary>")
    L.append("<table><tr><th>Session</th><th>Date</th><th>Type</th><th>Detail</th></tr>")
    for entry in log[-200:]:
        detail = entry.get("detail", "")
        if not detail and "steps" in entry:
            detail = str(entry["steps"])[:200]
        L.append(f"<tr><td>S{entry.get('session','?')}</td>"
                 f"<td>{esc(entry.get('date',''))}</td>"
                 f"<td>{esc(entry.get('type',''))}</td>"
                 f"<td style='font-size:0.85em'>{esc(str(detail)[:200])}</td></tr>")
    L.append("</table></details>")

    # ── RECENT FACTS ──
    if state.daily_facts:
        L.append("<h2>Recent Facts</h2><ul>")
        for f in state.daily_facts[-20:]:
            L.append(f"<li>{esc(f)}</li>")
        L.append("</ul>")

    # ── FOOTER ──
    L.append(f"<hr><p class='muted'>Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
             f"Gammaria MACROS Engine v3.1 | Full Delta-Parity Audit</p>")
    L.append("</body></html>")
    return "\n".join(L)


@server.tool()
def export_html_report(filepath: str = "") -> str:
    """
    Generate a formatted HTML audit report of the current game state.
    If no filepath given, writes to Desktop as gammaria_report.html.
    Auto-called by ENDS macro. Can also be called manually.
    """
    state = _get_state()
    if not filepath:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(desktop):
            desktop = os.path.expanduser("~")
        filepath = os.path.join(desktop, "gammaria_report.html")
    try:
        html_content = _generate_html_report(state)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        return f"📊 HTML report exported to: {filepath}"
    except Exception as e:
        return f"Error: {e}"


@server.tool()
def export_save(filepath: str = "") -> str:
    """
    Export the current save state to a JSON file at a specified path.
    If no filepath given, writes to Desktop as gammaria_export.json.
    Use this to audit the full save state outside the engine.
    """
    state = _get_state()
    if not filepath:
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(desktop):
            desktop = os.path.expanduser("~")
        filepath = os.path.join(desktop, "gammaria_export.json")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(state_to_json(state))
        return f"📤 Exported to: {filepath}"
    except Exception as e:
        return f"Error: {e}"


@server.tool()
def zone_forge(zone_name: str = "") -> str:
    """
    Run ZONE-FORGE checks for a zone (DG-13). Determines what content
    gaps exist and queues only necessary creative requests.
    If zone_name is empty, uses current PC zone.
    Returns a summary of what was found and what was queued.
    """
    global _pending_llm_requests, _day_logs
    state = _get_state()
    if not zone_name:
        zone_name = state.pc_zone
    if not zone_name:
        return "Error: No zone specified and no current PC zone."

    old_zone = state.pc_zone
    state.pc_zone = zone_name

    from zone_forge import run_zone_forge
    result = run_zone_forge(state)

    # Restore pc_zone if this was a manual check on a different zone
    if zone_name != old_zone:
        state.pc_zone = old_zone

    forge_requests = result.get("forge_requests", [])
    if forge_requests:
        _pending_llm_requests.extend(forge_requests)
        _day_logs.append({
            "step": "zone_forge",
            "zone": zone_name,
            "gaps": result.get("gaps", []),
            "requests_queued": len(forge_requests),
        })

    _auto_save(state)

    # Format summary
    lines = [f"ZONE-FORGE: {zone_name}"]
    lines.append(f"  Status: {result.get('status', '?')}")
    lines.append(f"  Faction: {result.get('controlling_faction', '—')}")
    lines.append(f"  NPCs in zone: {result.get('npc_count', 0)}")
    if result.get("with_pc_moved"):
        lines.append(f"  Moved with_pc: {', '.join(result['with_pc_moved'])}")
    gaps = result.get("gaps", [])
    if gaps:
        lines.append(f"  Gaps ({len(gaps)}):")
        for g in gaps:
            lines.append(f"    - {g}")
        lines.append(f"  ⚡ {len(forge_requests)} creative request(s) queued")
    else:
        lines.append("  No gaps found.")
    return "\n".join(lines)


if __name__ == "__main__":
    server.run(transport="stdio")
