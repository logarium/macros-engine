"""
MACROS Engine v1.3 — Claude Integration
Handles communication between the engine and Claude via clipboard.

ARCHITECTURE (Option A — Clipboard Embed):
  1. Engine runs T&P, collects LLM requests (NPAG, encounters, clock audits)
  2. Engine serializes ALL request data + state context into a prompt string
  3. Mark copies prompt to clipboard, pastes into Claude (web/Desktop/app)
  4. Claude reads the embedded data, generates JSON response
  5. Mark pastes Claude's JSON response back via "Import Response"
  6. Engine parses the JSON and applies state changes

NO API CALLS. NO FILE EXCHANGE. Uses your Max subscription directly.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime


# ─────────────────────────────────────────────────────
# FILE PATHS (for logging/archival only)
# ─────────────────────────────────────────────────────

def _data_dir():
    """Get the data directory path."""
    base = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(base, "data")
    os.makedirs(d, exist_ok=True)
    return d


def request_path():
    return os.path.join(_data_dir(), "claude_request.json")


def response_path():
    return os.path.join(_data_dir(), "claude_response.json")


def context_path():
    return os.path.join(_data_dir(), "claude_state_context.json")


# ─────────────────────────────────────────────────────
# BUILD STATE CONTEXT (compact summary for prompt)
# ─────────────────────────────────────────────────────

def build_state_summary(state) -> str:
    """Build a compact state summary string for embedding in prompts."""
    lines = []
    lines.append(f"SESSION: {state.session_id}")
    lines.append(f"DATE: {state.in_game_date}")
    lines.append(f"ZONE: {state.pc_zone}")
    lines.append(f"INTENSITY: {state.campaign_intensity}")
    lines.append(f"SEASON: {state.season}")

    # Active clocks — compact format
    lines.append("")
    lines.append("ACTIVE CLOCKS:")
    for clock in state.clocks.values():
        if clock.status == "active":
            cad = " [CADENCE]" if clock.is_cadence else ""
            pct = int(100 * clock.progress / max(clock.max_progress, 1))
            lines.append(f"  {clock.name}: {clock.progress}/{clock.max_progress} ({pct}%){cad} — {clock.owner}")

    # Fired triggers
    fired = [c for c in state.clocks.values() if c.trigger_fired]
    if fired:
        lines.append("")
        lines.append("FIRED TRIGGERS:")
        for c in fired:
            lines.append(f"  {c.name}: {c.trigger_on_completion}")

    # Engines
    lines.append("")
    lines.append("ENGINES:")
    for e in state.engines.values():
        lines.append(f"  {e.name} [{e.version}]: {e.status}")

    # Recent facts
    if state.daily_facts:
        recent = state.daily_facts[-15:]
        lines.append("")
        lines.append("RECENT FACTS:")
        for f in recent:
            lines.append(f"  - {f}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────
# BUILD CLIPBOARD PROMPT (Option A — the core fix)
# ─────────────────────────────────────────────────────

def build_clipboard_prompt(llm_requests: list, state, day_logs: list = None) -> str:
    """
    Build a self-contained prompt string with ALL request data embedded.
    This is what Mark copies and pastes into Claude. No file references.
    """
    sections = []

    # ── HEADER ──
    sections.append("=" * 60)
    sections.append("MACROS ENGINE v1.3 — LLM REQUEST PAYLOAD")
    sections.append("=" * 60)
    sections.append("")
    sections.append(
        "You are the narrative AI for a MACROS 3.0 campaign (Gammaria). "
        "The mechanical engine has processed Time & Pressure and generated "
        "the requests below. For each request, provide the creative content needed."
    )
    sections.append("")
    sections.append("TONE: Sword & sorcery, heroic adventure. "
                    "Compressed prose (150-300 words, 400 hard cap per narrative block). "
                    "Inspirations: Elric, Conan, Dark Crystal, Krull, Willow, LotR.")
    sections.append("")
    sections.append("CRITICAL: Do NOT invent new events or facts to justify clock advances. "
                    "Only advance clocks when ADV bullets are UNAMBIGUOUSLY satisfied by established facts.")

    # ── STATE CONTEXT ──
    sections.append("")
    sections.append("-" * 60)
    sections.append("GAME STATE")
    sections.append("-" * 60)
    sections.append(build_state_summary(state))

    # ── DAY SUMMARIES ──
    if day_logs:
        sections.append("")
        sections.append("-" * 60)
        sections.append("T&P DAY SUMMARIES")
        sections.append("-" * 60)
        for dl in day_logs:
            day_num = dl.get("day_number", "?")
            date = dl.get("date", "?")
            sections.append(f"\nDAY {day_num} — {date}:")
            for step in dl.get("steps", []):
                step_name = step["step"]
                result = step.get("result", step.get("results", {}))
                if step_name == "cadence_clocks":
                    for cr in step.get("results", []):
                        if "error" not in cr:
                            sections.append(f"  Cadence: {cr['clock']} {cr['old']}->{cr['new']}/{cr['max']}")
                            if cr.get("trigger_fired"):
                                sections.append(f"    !! TRIGGER FIRED: {cr.get('trigger_text', '')}")
                elif step_name.startswith("engine:"):
                    en = step_name.split(":", 1)[1]
                    if result.get("skipped") or result.get("status") == "inert":
                        continue
                    if "roll" in result:
                        sections.append(f"  Engine {en}: 2d6={result['roll']['total']} -> {result.get('outcome_band', '')}")
                        for ce in result.get("clock_effects_applied", []):
                            if not ce.get("skipped") and "error" not in ce:
                                sections.append(f"    -> {ce['clock']}: {ce.get('old', '?')}->{ce.get('new', '?')}")
                elif step_name == "encounter_gate":
                    if result.get("passed"):
                        enc = result.get("encounter", {})
                        sections.append(f"  ENCOUNTER: {enc.get('description', 'unknown')[:80]}")
                elif step_name == "npag_gate":
                    if result.get("passed"):
                        sections.append(f"  NPAG: {result['npc_count']['count']} NPCs act")
                elif step_name == "clock_audit":
                    for a in result.get("auto_advanced", []):
                        ar = a["advance_result"]
                        sections.append(f"  Audit auto-advance: {a['clock']} {ar['old']}->{ar['new']}/{ar.get('max', '?')}")
                    for rv in result.get("needs_llm_review", []):
                        sections.append(f"  Audit pending: {rv['clock']} ({len(rv['ambiguous_bullets'])} ambiguous bullets)")

    # ── REQUESTS ──
    sections.append("")
    sections.append("-" * 60)
    sections.append(f"REQUESTS ({len(llm_requests)} total)")
    sections.append("-" * 60)

    for i, req in enumerate(llm_requests):
        req_id = f"req_{i+1:03d}"
        req_type = req.get("type", "UNKNOWN")
        sections.append(f"\n[{req_id}] TYPE: {req_type}")

        if req_type == "CLOCK_AUDIT_REVIEW":
            sections.append(f"  CLOCK: {req.get('clock', '?')}")
            sections.append(f"  PROGRESS: {req.get('progress', '?')}")
            sections.append(f"  AMBIGUOUS BULLETS:")
            for ab in req.get("ambiguous_bullets", []):
                if isinstance(ab, dict):
                    sections.append(f"    - \"{ab.get('bullet', '?')}\" (confidence: {ab.get('confidence', '?')})")
                    if ab.get("matching_facts"):
                        sections.append(f"      Partial matches: {', '.join(str(mf) for mf in ab['matching_facts'][:3])}")
                else:
                    sections.append(f"    - {ab}")
            if req.get("daily_facts"):
                sections.append(f"  TODAY'S FACTS:")
                for fact in req["daily_facts"]:
                    sections.append(f"    - {fact}")
            sections.append(f"  INSTRUCTION: Review whether these ADV bullets are UNAMBIGUOUSLY "
                           f"satisfied by today's established facts. Respond 'advance' or "
                           f"'no_advance' with reasoning. Do NOT invent events to justify.")

        elif req_type == "NPAG":
            sections.append(f"  NPC COUNT: {req.get('npc_count', 0)}")
            sections.append(f"  INSTRUCTION: Resolve agency actions for {req.get('npc_count', 0)} NPCs. "
                           f"Choose NPCs with active OBJ/ACT entries. Describe off-screen actions. "
                           f"Note any clock ADV bullets their actions satisfy.")

        elif req_type == "NARR_ENCOUNTER":
            sections.append(f"  CONTEXT: {req.get('context', 'No context')}")
            bx = req.get("bx_plug", False)
            sections.append(f"  BX-PLUG COMBAT: {'Yes' if bx else 'No'}")
            sections.append(f"  INSTRUCTION: Narrate in sword & sorcery style, 150-300 words. "
                           f"{'Describe initial contact, ask ATTACK or FLEE.' if bx else ''}")

        elif req_type == "CAN-FORGE-AUTO":
            sections.append(f"  INSTRUCTION: Create an Unconfirmed Activity threat for this zone. "
                           f"Provide brief description and BX stat block.")

        else:
            sections.append(f"  CONTEXT: {req.get('context', '')}")

    # ── RESPONSE FORMAT ──
    sections.append("")
    sections.append("-" * 60)
    sections.append("RESPONSE FORMAT")
    sections.append("-" * 60)
    sections.append("")
    sections.append("Reply with ONLY a JSON block (no markdown fences, no extra text).")
    sections.append("Use this exact structure:")
    sections.append("")
    sections.append('{')
    sections.append('  "responses": [')
    sections.append('    {')
    sections.append('      "id": "req_001",')
    sections.append('      "type": "CLOCK_AUDIT_REVIEW",')
    sections.append('      "content": "Your narrative reasoning here",')
    sections.append('      "state_changes": [')
    sections.append('        {"type": "clock_advance", "clock": "Clock Name", "reason": "why"},')
    sections.append('        {"type": "fact", "text": "new established fact"}')
    sections.append('      ]')
    sections.append('    }')
    sections.append('  ]')
    sections.append('}')
    sections.append("")
    sections.append("state_changes types:")
    sections.append("  clock_advance — advance a clock by 1 (only if ADV bullet clearly met)")
    sections.append("  clock_reduce  — reduce a clock by 1 (only if REDUCE bullet clearly met)")
    sections.append("  fact          — establish a new narrative fact")
    sections.append("")
    sections.append("Include a response for EVERY request above, matching by id.")

    return "\n".join(sections)


# ─────────────────────────────────────────────────────
# WRITE REQUEST (for logging/archival — optional)
# ─────────────────────────────────────────────────────

def write_request(llm_requests: list, state, day_logs: list = None):
    """
    Write pending LLM requests to a file for archival.
    The clipboard prompt is the primary delivery mechanism now.
    """
    # Clear any old response
    if os.path.exists(response_path()):
        os.remove(response_path())

    request = {
        "generated_at": datetime.now().isoformat(),
        "engine_version": "MACROS Engine v1.3",
        "requests": [],
        "game_state": {
            "session": state.session_id,
            "date": state.in_game_date,
            "pc_zone": state.pc_zone,
            "intensity": state.campaign_intensity,
            "season": state.season,
        },
    }

    for i, req in enumerate(llm_requests):
        request["requests"].append({
            "id": f"req_{i+1:03d}",
            "type": req.get("type", "UNKNOWN"),
            "context": req.get("context", ""),
            **{k: v for k, v in req.items() if k not in ("type", "context")},
        })

    if day_logs:
        request["day_logs_count"] = len(day_logs)

    with open(request_path(), "w", encoding="utf-8") as f:
        json.dump(request, f, indent=2)

    # Also write state context for logging
    write_state_context(state)

    return request_path()


def write_state_context(state):
    """Write state context to file for archival."""
    context = {
        "generated_at": datetime.now().isoformat(),
        "meta": {
            "session": state.session_id,
            "date": state.in_game_date,
            "pc_zone": state.pc_zone,
            "intensity": state.campaign_intensity,
            "season": state.season,
        },
        "active_clocks": {},
        "fired_triggers": [],
        "engines": {},
        "recent_facts": state.daily_facts[-20:] if state.daily_facts else [],
    }

    for clock in state.clocks.values():
        if clock.status == "active":
            context["active_clocks"][clock.name] = {
                "progress": f"{clock.progress}/{clock.max_progress}",
                "owner": clock.owner,
                "advance_bullets": clock.advance_bullets,
                "is_cadence": clock.is_cadence,
            }
        elif clock.trigger_fired:
            context["fired_triggers"].append({
                "clock": clock.name,
                "trigger": clock.trigger_on_completion,
            })

    for engine in state.engines.values():
        context["engines"][engine.name] = {
            "status": engine.status,
            "version": engine.version,
        }

    with open(context_path(), "w", encoding="utf-8") as f:
        json.dump(context, f, indent=2)

    return context_path()


# ─────────────────────────────────────────────────────
# PARSE PASTED RESPONSE
# ─────────────────────────────────────────────────────

def parse_pasted_response(text: str) -> dict:
    """
    Parse Claude's pasted text response into the response dict.
    Handles common issues:
      - Markdown code fences (```json ... ```)
      - Leading/trailing whitespace
      - Response wrapped in extra text
    """
    text = text.strip()

    # Strip markdown code fences
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break

    # Try to find JSON object if there's extra text
    if not text.startswith("{"):
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        text = text[start:i+1]
                        break

    return json.loads(text)


# ─────────────────────────────────────────────────────
# CHECK FOR RESPONSE FILE (legacy support)
# ─────────────────────────────────────────────────────

def response_exists() -> bool:
    """Check if Claude has written a response file."""
    return os.path.exists(response_path())


def read_response() -> dict:
    """Read and parse Claude's response file."""
    if not os.path.exists(response_path()):
        return None
    with open(response_path(), "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────
# APPLY RESPONSE (works for both clipboard and file)
# ─────────────────────────────────────────────────────

def apply_response(state, response: dict) -> list:
    """
    Apply Claude's response to the game state.
    Returns a list of log entries describing what was applied.
    """
    log_entries = []

    for resp in response.get("responses", []):
        req_id = resp.get("id", "?")
        req_type = resp.get("type", "?")
        content = resp.get("content", "")

        log_entries.append({
            "id": req_id,
            "type": req_type,
            "content_preview": content[:100] + "..." if len(content) > 100 else content,
        })

        # Apply state changes
        for change in resp.get("state_changes", []):
            change_type = change.get("type", "")

            if change_type == "clock_advance":
                clock = state.get_clock(change.get("clock", ""))
                if clock and clock.can_advance():
                    result = clock.advance(
                        reason=f"LLM ({req_id}): {change.get('reason', '')}",
                        date=state.in_game_date,
                        session=state.session_id,
                    )
                    log_entries.append({"applied": "clock_advance", "result": result})
                elif not clock:
                    log_entries.append({"applied": "clock_advance", "error": f"Clock not found: {change.get('clock', '')}"})

            elif change_type == "clock_reduce":
                clock = state.get_clock(change.get("clock", ""))
                if clock:
                    result = clock.reduce(
                        reason=f"LLM ({req_id}): {change.get('reason', '')}",
                    )
                    log_entries.append({"applied": "clock_reduce", "result": result})

            elif change_type == "fact":
                state.add_fact(change.get("text", ""))
                log_entries.append({"applied": "fact", "text": change.get("text", "")})

    # Archive the response
    archive_dir = os.path.join(_data_dir(), "archive")
    os.makedirs(archive_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"response_{timestamp}.json"

    with open(os.path.join(archive_dir, archive_name), "w", encoding="utf-8") as f:
        json.dump(response, f, indent=2)

    return log_entries


# ─────────────────────────────────────────────────────
# LAUNCH CLAUDE DESKTOP (still useful as shortcut)
# ─────────────────────────────────────────────────────

def launch_claude_desktop():
    """Attempt to open Claude Desktop on Windows."""
    possible_paths = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Claude\Claude.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Claude\Claude.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Claude\Claude.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Claude\Claude.exe"),
        shutil.which("claude"),
    ]

    for path in possible_paths:
        if path and os.path.isfile(path):
            try:
                subprocess.Popen([path], shell=False)
                return True, path
            except Exception:
                continue

    return False, None


# ─────────────────────────────────────────────────────
# MCP CONFIG GENERATOR (kept for future use)
# ─────────────────────────────────────────────────────

def generate_mcp_config() -> str:
    """Generate MCP filesystem server config for Claude Desktop."""
    data_dir = _data_dir().replace("\\", "/")
    base_dir = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")

    config = {
        "mcpServers": {
            "macros-engine": {
                "command": "npx",
                "args": [
                    "-y",
                    "@anthropic-ai/mcp-filesystem-server",
                    data_dir,
                    base_dir,
                ],
            }
        }
    }

    config_json = json.dumps(config, indent=2)

    instructions = f"""
╔══════════════════════════════════════════════════════════════╗
║  CLAUDE DESKTOP MCP SETUP — OPTIONAL / FUTURE USE           ║
╚══════════════════════════════════════════════════════════════╝

NOTE: The engine now uses clipboard-based prompts (Option A).
MCP is NOT required. This is here for potential future use.

If you want to set up MCP anyway:

REQUIREMENTS:
  • Claude Desktop installed
  • Node.js installed (free from nodejs.org)

STEPS:
  1. Open Claude Desktop → Menu → Settings → Developer → Edit Config
  2. Paste this config:

{config_json}

  3. Save and restart Claude Desktop

PATHS SHARED:
  • {data_dir}
  • {base_dir}
"""
    return instructions, config_json
