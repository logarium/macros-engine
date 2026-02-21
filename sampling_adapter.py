"""
MACROS Engine v4.1 — Sampling Adapter
Resolves creative requests by calling back to Claude Desktop via MCP sampling.

When a tool handler (e.g., run_tp_days) generates LLM requests, this adapter
sends them to Claude through ctx.session.create_message() and parses the
structured JSON response back into the format apply_response() expects.

Uses the player's Max subscription — no API key required.
"""

import json
import logging
from mcp.types import SamplingMessage, TextContent, ModelPreferences, ModelHint
from lore_index import get_lore_index

logger = logging.getLogger("macros.sampling")


# ─────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are the narrative AI for a MACROS 3.0 solo RPG campaign set in Gammaria.
The mechanical engine has processed Time & Pressure and generated creative requests.
For each request, provide the content needed.

TONE: Sword & sorcery, heroic adventure.
Compressed prose (150-300 words, 400 hard cap per narrative block).
Inspirations: Elric, Conan, Dark Crystal, Krull, Willow, LotR.
VOICE: Second person present tense. The player IS the character.
"You stand at the gate" not "Thoron stood at the gate". Never use the PC name as subject.

CRITICAL RULES:
- Do NOT invent new events or facts to justify clock advances.
- Only advance clocks when ADV bullets are UNAMBIGUOUSLY satisfied by established facts.
- For CLOCK_AUDIT_REVIEW: respond "advance" or "no_advance" with reasoning.
- For NPAG: describe off-screen NPC actions. Note any clock ADV bullets satisfied.
- For NARR_ENCOUNTER: narrate the encounter. If BX-PLUG, set up ATTACK/FLEE choice.
- For NARR_COMBAT_END: narrate the aftermath of combat. Do not re-narrate the fight itself.
- For RUMOR: generate a brief rumor (1-2 sentences). Return as content text.
- If a MODE INSTRUCTION is present, follow its format requirements precisely.

Reply with ONLY a JSON object (no markdown fences, no extra text):
{
  "responses": [
    {
      "id": "req_001",
      "type": "REQUEST_TYPE",
      "content": "Your narrative/reasoning here",
      "state_changes": [
        {"type": "clock_advance", "clock": "Clock Name", "reason": "why"},
        {"type": "fact", "text": "new established fact"}
      ]
    }
  ]
}

state_changes types:
  clock_advance    — advance a clock by 1 (only if ADV bullet clearly met)
  clock_reduce     — reduce a clock by 1 (only if REDUCE bullet clearly met)
  fact             — establish a new narrative fact
  npc_update       — update an NPC field (zone, status, next_action, objective)
  npc_create       — create a new NPC (name, zone, role, trait, appearance, faction, BX stats)
  el_create        — create encounter list for zone (zone, randomizer, entries[] with range/prompt/ua_cue/bx_plug)
  faction_create   — create new faction (name, status, trend, disposition, notes)
  faction_update   — update existing faction (name + changed fields + history_entry)
  clock_create     — create new clock (name, owner, max_progress, advance_bullets[], trigger_on_completion)
  companion_create — create companion detail (npc_name, trust_in_pc, motivation_shift, etc.)
  pe_create        — create persistent procedural engine (engine_name, version, zone_scope, trigger_event, etc.)
  ua_create        — create Unknown Actor (ua_id, zone, description, status)
  discovery_create — create a discovery (id, zone, ua_code, certainty, info)
  thread_create    — create an unresolved thread (id, zone, description)

For *_FORGE requests: return structured state_changes with the exact fields specified
in the request constraints. The "content" field should be a brief 1-sentence summary.
Prioritize structured data in state_changes over prose in content.

LORE CONTEXT: Some requests include a LORE section with canonical passages from
the Gammaria setting documents. Use these to inform tone, atmosphere, character
voice, and world details. Do not contradict lore passages. For FORGE requests,
the FORGE SPEC section contains the authoritative creation rules — follow them.

Include a response for EVERY request, matching by id."""


# ─────────────────────────────────────────────────────
# BUILD USER MESSAGE
# ─────────────────────────────────────────────────────

def _build_state_context(state) -> str:
    """Compact state summary for the sampling prompt."""
    lines = []
    lines.append(f"SESSION: {state.session_id}")
    lines.append(f"DATE: {state.in_game_date}")
    lines.append(f"ZONE: {state.pc_zone}")
    lines.append(f"INTENSITY: {state.campaign_intensity}")
    lines.append(f"SEASON: {state.season}")

    lines.append("\nACTIVE CLOCKS:")
    for clock in state.clocks.values():
        if clock.status == "active":
            cad = " [CADENCE]" if clock.is_cadence else ""
            lines.append(f"  {clock.name}: {clock.progress}/{clock.max_progress}{cad}")
            if clock.advance_bullets:
                for b in clock.advance_bullets:
                    lines.append(f"    ADV: {b}")

    lines.append("\nRECENT FACTS:")
    for f in (state.daily_facts[-15:] if state.daily_facts else []):
        lines.append(f"  - {f}")

    return "\n".join(lines)


def _build_request_section(llm_requests: list) -> str:
    """Format LLM requests into the user message."""
    lines = [f"REQUESTS ({len(llm_requests)} total):"]

    for i, req in enumerate(llm_requests):
        req_id = f"req_{i+1:03d}"
        req_type = req.get("type", "UNKNOWN")
        lines.append(f"\n[{req_id}] TYPE: {req_type}")

        if req_type == "CLOCK_AUDIT_REVIEW":
            lines.append(f"  CLOCK: {req.get('clock', '?')}")
            lines.append(f"  PROGRESS: {req.get('progress', '?')}")
            lines.append(f"  AMBIGUOUS BULLETS:")
            for ab in req.get("ambiguous_bullets", []):
                if isinstance(ab, dict):
                    lines.append(f"    - \"{ab.get('bullet', '?')}\" "
                                 f"(confidence: {ab.get('confidence', '?')})")
                else:
                    lines.append(f"    - {ab}")
            if req.get("daily_facts"):
                lines.append(f"  TODAY'S FACTS:")
                for fact in req["daily_facts"]:
                    lines.append(f"    - {fact}")

        elif req_type == "NPAG":
            lines.append(f"  NPC COUNT: {req.get('npc_count', 0)}")
            lines.append(f"  Resolve agency for {req.get('npc_count', 0)} NPCs "
                         f"with active objectives.")

        elif req_type == "NARR_ENCOUNTER":
            ctx = req.get("context", {})
            if isinstance(ctx, dict):
                lines.append(f"  ZONE: {json.dumps(ctx.get('zone', '?'))}")
                lines.append(f"  ENCOUNTER: {ctx.get('encounter_description', '')}")
                bx = ctx.get("has_bx_plug", False)
                lines.append(f"  BX-PLUG COMBAT: {'Yes' if bx else 'No'}")
                stat_block = ctx.get("bx_stat_block", "")
                if stat_block:
                    lines.append(f"  BX STAT BLOCK: {json.dumps(stat_block)}")
                if ctx.get("ua_cue"):
                    lines.append(f"  UNKNOWN ACTOR CUE: Yes")
            else:
                lines.append(f"  CONTEXT: {ctx}")
                bx = req.get("bx_plug", False)
                lines.append(f"  BX-PLUG COMBAT: {'Yes' if bx else 'No'}")

        elif req_type == "NARR_COMBAT_END":
            ctx = req.get("context", {})
            cs = ctx.get("combat_summary", {})
            lines.append(f"  ZONE: {ctx.get('zone', '?')}")
            lines.append(f"  COMBAT RESULT: {cs.get('end_reason', '?')} "
                         f"({cs.get('rounds', '?')} rounds)")
            lines.append(f"  ENCOUNTER: {cs.get('encounter_prompt', '?')}")
            lines.append(f"  PC HP: {cs.get('pc_hp_final', '?')}")
            for comp in cs.get("companions_status", []):
                status = "DOWN" if comp.get("down") else "OK"
                lines.append(f"  COMPANION: {comp.get('name', '?')} "
                             f"HP={comp.get('hp', '?')} [{status}]")
            for evt in cs.get("key_events", [])[:5]:
                lines.append(f"  EVENT: {evt[:80]}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "PLAYER_INPUT":
            ctx = req.get("context", {})
            lines.append(f"  PLAYER SAYS: \"{ctx.get('intent', '')}\"")
            lines.append(f"  ZONE: {ctx.get('pc_zone', '?')}")
            comps = ctx.get("companions_with_pc", [])
            if comps:
                lines.append(f"  COMPANIONS: {', '.join(c.get('name', '?') for c in comps)}")
            npcs = ctx.get("npcs_present", [])
            if npcs:
                lines.append(f"  NPCs PRESENT: {', '.join(n.get('name', '?') + ' (' + n.get('role', '?') + ')' for n in npcs)}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "RUMOR":
            ctx = req.get("context", {})
            lines.append(f"  ZONE: {ctx.get('pc_zone', '?')}")
            lines.append(f"  TRUTH ROLL: 1d8={ctx.get('truth_roll', '?')}")
            lines.append(f"  IS TRUE: {ctx.get('is_true', False)}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "CAN-FORGE-AUTO":
            lines.append(f"  CONTEXT: {req.get('context', '')}")
            lines.append(f"  Create an Unconfirmed Activity threat.")

        # DG-17 Forge request formatting
        elif req_type == "NPC_FORGE":
            ctx = req.get("context", {})
            lines.append(f"  ZONE: {ctx.get('zone', '?')}")
            if ctx.get("role_hint"):
                lines.append(f"  ROLE HINT: {ctx['role_hint']}")
            if ctx.get("faction_hint"):
                lines.append(f"  FACTION HINT: {ctx['faction_hint']}")
            existing = ctx.get("existing_npcs_in_zone", [])
            if existing:
                lines.append(f"  EXISTING NPCs ({len(existing)}):")
                for n in existing[:10]:
                    lines.append(f"    - {n.get('name', '?')} ({n.get('role', '?')})")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "EL_FORGE":
            ctx = req.get("context", {})
            lines.append(f"  ZONE: {ctx.get('zone', '?')}")
            zd = ctx.get("zone_data", {})
            if zd:
                lines.append(f"  THREAT LEVEL: {zd.get('threat_level', '?')}")
                lines.append(f"  INTENSITY: {zd.get('intensity', '?')}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "FAC_FORGE":
            ctx = req.get("context", {})
            lines.append(f"  FACTION: {ctx.get('faction_name', 'NEW')}")
            lines.append(f"  IS UPDATE: {ctx.get('is_update', False)}")
            if ctx.get("existing_faction_data"):
                lines.append(f"  CURRENT: {json.dumps(ctx['existing_faction_data'])}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "CL_FORGE":
            ctx = req.get("context", {})
            lines.append(f"  OWNER: {ctx.get('owner', '?')}")
            if ctx.get("trigger_context"):
                lines.append(f"  TRIGGER: {ctx['trigger_context']}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "CAN_FORGE":
            ctx = req.get("context", {})
            lines.append(f"  ZONE: {ctx.get('zone', '?')}")
            lines.append(f"  TRIGGER: {ctx.get('trigger', 'manual')}")
            npcs_in_zone = ctx.get("existing_npcs_in_zone", [])
            if npcs_in_zone:
                names = [n.get("name", "?") for n in npcs_in_zone]
                lines.append(f"  EXISTING NPCs: {', '.join(names)}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "PE_FORGE":
            ctx = req.get("context", {})
            lines.append(f"  ENGINE NAME: {ctx.get('engine_name', '?')}")
            lines.append(f"  ZONE SCOPE: {ctx.get('zone_scope', '?')}")
            if ctx.get("trigger_event"):
                lines.append(f"  TRIGGER EVENT: {ctx['trigger_event']}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        elif req_type == "UA_FORGE":
            ctx = req.get("context", {})
            lines.append(f"  ZONE: {ctx.get('zone', '?')}")
            lines.append(f"  NEXT CODE: {ctx.get('next_ua_code', '?')}")
            if ctx.get("trigger_context"):
                lines.append(f"  TRIGGER: {ctx['trigger_context']}")
            lines.append(f"  INSTRUCTIONS: {req.get('constraints', {}).get('instruction', '')}")

        else:
            lines.append(f"  CONTEXT: {req.get('context', '')}")

        # DG-20: Append lore section if present
        # Check both req["lore"] (raw dicts) and req["context"]["lore"] (CreativeRequest)
        lore_dict = req.get("lore", {})
        if not lore_dict:
            ctx = req.get("context", {})
            if isinstance(ctx, dict):
                lore_dict = ctx.get("lore", {})
        if lore_dict:
            lines.extend(_format_lore(lore_dict))

        # DG-22: Append mode instruction if present in constraints
        mode_instr = req.get("constraints", {}).get("mode_instruction", "")
        if mode_instr:
            lines.append(f"  MODE INSTRUCTION: {mode_instr}")

    return "\n".join(lines)


def _build_day_summaries(day_logs: list) -> str:
    """Compact day summaries for context."""
    if not day_logs:
        return ""

    lines = ["T&P DAY SUMMARIES:"]
    for dl in day_logs:
        day_num = dl.get("day_number", "?")
        date = dl.get("date", "?")
        lines.append(f"\nDAY {day_num} — {date}:")
        for step in dl.get("steps", []):
            sn = step["step"]
            r = step.get("result", step.get("results", {}))
            if sn == "cadence_clocks":
                for cr in step.get("results", []):
                    if "error" not in cr:
                        lines.append(f"  Cadence: {cr['clock']} "
                                     f"{cr['old']}->{cr['new']}/{cr['max']}")
                        if cr.get("trigger_fired"):
                            lines.append(f"    TRIGGER: {cr.get('trigger_text', '')}")
            elif sn.startswith("engine:"):
                en = sn.split(":", 1)[1]
                if r.get("skipped") or r.get("status") == "inert":
                    continue
                if "roll" in r:
                    lines.append(f"  Engine {en}: 2d6={r['roll']['total']} "
                                 f"-> {r.get('outcome_band', '')}")
            elif sn == "encounter_gate":
                if r.get("passed"):
                    enc = r.get("encounter", {})
                    lines.append(f"  ENCOUNTER: "
                                 f"{enc.get('description', 'unknown')[:80]}")
            elif sn == "npag_gate":
                if r.get("passed"):
                    lines.append(f"  NPAG: {r['npc_count']['count']} NPCs act")
            elif sn == "clock_audit":
                for a in r.get("auto_advanced", []):
                    ar = a["advance_result"]
                    lines.append(f"  Audit: {a['clock']} "
                                 f"{ar['old']}->{ar['new']}/{ar.get('max', '?')}")
                for rv in r.get("needs_llm_review", []):
                    lines.append(f"  Audit pending: {rv['clock']}")

    return "\n".join(lines)


# DG-25: Context budget constants
MAX_LORE_CHARS_PER_KEY = 500
MAX_TOTAL_LORE_CHARS = 2000


def _format_lore(lore_dict: dict) -> list:
    """Format a lore dict into indented LORE section lines (DG-25 budget-aware)."""
    if not lore_dict:
        return []
    lines = ["  LORE:"]
    total_chars = 0
    for key, text in lore_dict.items():
        label = key.upper().replace("_", " ")
        passage = text.strip()
        # Per-key cap
        if len(passage) > MAX_LORE_CHARS_PER_KEY:
            passage = passage[:MAX_LORE_CHARS_PER_KEY - 3] + "..."
        # Total budget cap
        if total_chars + len(passage) > MAX_TOTAL_LORE_CHARS:
            remaining = MAX_TOTAL_LORE_CHARS - total_chars
            if remaining > 50:
                passage = passage[:remaining - 3] + "..."
            else:
                break
        total_chars += len(passage)
        lines.append(f"    [{label}]")
        for pline in passage.split("\n"):
            lines.append(f"    {pline}")
    return lines


def _inject_lore_for_raw_requests(llm_requests: list, state) -> None:
    """Inject lore into raw T&P dicts that bypass creative_bridge builders.
    Mutates requests in place — only adds lore if not already present."""
    lore = get_lore_index()
    for req in llm_requests:
        # Skip requests that already have lore (came through creative_bridge)
        ctx = req.get("context", {})
        if isinstance(ctx, dict) and ctx.get("lore"):
            continue
        if req.get("lore"):
            continue

        req_type = req.get("type", "")
        lore_dict = {}

        if req_type == "NARR_ENCOUNTER":
            zone_lore = lore.get_zone_lore(state.pc_zone)
            if zone_lore:
                lore_dict["zone_atmosphere"] = zone_lore
            if req.get("bx_plug") or req.get("bx_plug_detail"):
                bx_rules = lore.get_bx_plug(["0", "1", "6", "9"])
                if bx_rules:
                    lore_dict["bx_plug_rules"] = bx_rules

        elif req_type == "NPAG":
            # Inject lore for first few NPCs referenced
            npc_count = req.get("npc_count", 0)
            if npc_count > 0:
                for npc in list(state.npcs.values())[:npc_count]:
                    if npc.status == "active" and (npc.objective or npc.next_action):
                        npc_lore = lore.get_npc_lore(npc.name, max_lines=10)
                        if npc_lore:
                            lore_dict[f"npc:{npc.name}"] = npc_lore
                        if npc.faction:
                            fac_lore = lore.get_faction_lore(npc.faction)
                            if fac_lore:
                                lore_dict[f"faction:{npc.faction}"] = fac_lore

        elif req_type == "NARR_COMBAT_END":
            zone_lore = lore.get_zone_lore(state.pc_zone)
            if zone_lore:
                lore_dict["zone_atmosphere"] = zone_lore

        elif req_type == "RUMOR":
            zone_lore = lore.get_zone_lore(state.pc_zone)
            if zone_lore:
                lore_dict["zone_atmosphere"] = zone_lore

        elif req_type == "PLAYER_INPUT":
            zone_lore = lore.get_zone_lore(state.pc_zone)
            if zone_lore:
                lore_dict["zone_atmosphere"] = zone_lore
            # Inject lore for NPCs present in the zone
            for npc in list(state.npcs.values()):
                if npc.current_zone == state.pc_zone and npc.status == "active":
                    npc_lore = lore.get_npc_lore(npc.name, max_lines=10)
                    if npc_lore:
                        lore_dict[f"npc:{npc.name}"] = npc_lore

        # CLOCK_AUDIT_REVIEW: no lore (keep mechanical)

        if lore_dict:
            req["lore"] = lore_dict


def build_sampling_prompt(llm_requests: list, state, day_logs: list) -> str:
    """Build the complete user message for the sampling call."""
    # DG-20: Inject lore for raw MCP-path requests
    _inject_lore_for_raw_requests(llm_requests, state)

    sections = [
        "GAME STATE:",
        _build_state_context(state),
        "",
        _build_day_summaries(day_logs),
        "",
        _build_request_section(llm_requests),
    ]
    return "\n".join(sections)


# ─────────────────────────────────────────────────────
# RESPONSE PARSING
# ─────────────────────────────────────────────────────

def _parse_sampling_response(text: str) -> dict:
    """
    Parse Claude's sampling response into a dict.
    Handles markdown fences, extra text wrapping JSON.
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

    # Find JSON object if wrapped in extra text
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
                        text = text[start:i + 1]
                        break

    return json.loads(text)


# ─────────────────────────────────────────────────────
# MAIN SAMPLING CALL
# ─────────────────────────────────────────────────────

async def resolve_creative_requests(ctx, llm_requests: list, state,
                                     day_logs: list) -> dict:
    """
    Send creative requests to Claude Desktop via MCP sampling.
    Returns a response dict in the same format as clipboard/API responses:
    {"responses": [{"id": "req_001", "type": "...", "content": "...", ...}]}

    Args:
        ctx: FastMCP Context (provides access to session.create_message)
        llm_requests: list of raw request dicts from engine.py
        state: GameState object
        day_logs: list of day log dicts for context

    Returns:
        dict with "responses" key, or dict with "error" key on failure
    """
    if not llm_requests:
        return {"responses": []}

    prompt = build_sampling_prompt(llm_requests, state, day_logs)

    logger.info(f"Sampling: sending {len(llm_requests)} creative requests to Claude")

    try:
        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(type="text", text=prompt),
                )
            ],
            max_tokens=2048,
            system_prompt=SYSTEM_PROMPT,
            model_preferences=ModelPreferences(
                intelligencePriority=0.8,
                speedPriority=0.5,
            ),
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Sampling call failed: {error_msg}")
        return {"error": f"Sampling failed: {error_msg}",
                "fallback": "requests_queued"}

    # Extract text from response
    if result.content.type != "text":
        return {"error": f"Unexpected response type: {result.content.type}",
                "fallback": "requests_queued"}

    raw_text = result.content.text
    logger.info(f"Sampling: received {len(raw_text)} chars from {result.model}")

    try:
        response = _parse_sampling_response(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse sampling response: {e}")
        return {"error": f"Parse error: {e}",
                "raw_text": raw_text[:500],
                "fallback": "requests_queued"}

    if "responses" not in response:
        return {"error": "Response missing 'responses' key",
                "raw_text": raw_text[:500],
                "fallback": "requests_queued"}

    return response
