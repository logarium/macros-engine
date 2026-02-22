"""
MACROS Engine v4.0 — Creative Bridge
Request/Response contract between engine and Claude (DG-12).
LLM-agnostic: defines what the engine needs, not how Claude provides it.

The engine queues CreativeRequests when it needs creative content.
An adapter (MCP, API, clipboard) delivers them to an LLM and returns
CreativeResponses. The engine applies the responses to game state.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime
from lore_index import get_lore_index


# ─────────────────────────────────────────────────────
# REQUEST / RESPONSE TYPES
# ─────────────────────────────────────────────────────

# Request types
REQUEST_TYPES = {
    "NARR_ARRIVAL",       # Zone arrival narration after travel
    "NARR_ENCOUNTER",     # Encounter narration after gate pass
    "CLOCK_AUDIT",        # Ambiguous ADV bullet adjudication
    "NPAG",               # NPC agency resolution
    "SESSION_SUMMARY",    # End-of-session narrative summary (DG-19)
    "NARR_COMBAT_END",    # Post-combat aftermath narration (DG-16)
    "RUMOR",               # One-shot rumor generation (DG-22)
    "PLAYER_INPUT",        # Player in-character intent from chat panel
    # DG-17 Forge Request Protocol
    "NPC_FORGE",          # Create NPC with BX stats
    "EL_FORGE",           # Create encounter list for zone
    "FAC_FORGE",          # Create or update faction
    "CAN_FORGE",          # Zone canonicalization (FAC+NPC+CL+EL+PE+UA)
    "CL_FORGE",           # Create clock (also DG-18)
    "PE_FORGE",           # Create persistent procedural engine
    "UA_FORGE",           # Create Unknown Actor entry
    "ZONE_EXPANSION",     # Create new zones via CP expansion (ZONE-FORGE 3.0)
    "NARR_TIME_PASSAGE",  # Time passage narration after rest/T&P
    "NARR_SESSION_START", # Session opening scene after ZONE-FORGE cascade
}

# State change types that can appear in responses
STATE_CHANGE_TYPES = {
    "clock_advance",      # Advance named clock by 1
    "clock_reduce",       # Reduce named clock by 1
    "fact",               # Establish a new narrative fact
    "npc_update",         # Update an NPC field
    "session_meta",       # Update session meta (tone, pacing, pressure)
    # DG-17 Forge state changes
    "npc_create",         # Create new NPC (NPC-FORGE)
    "el_create",          # Create encounter list (EL-FORGE)
    "faction_create",     # Create new faction (FAC-FORGE)
    "faction_update",     # Update existing faction (FAC-FORGE)
    "clock_create",       # Create new clock (CL-FORGE / DG-18)
    "companion_create",   # Create companion detail (NPAG / companionization)
    "pe_create",          # Create persistent procedural engine (PE-FORGE)
    "ua_create",          # Create Unknown Actor entry (UA-FORGE)
    "discovery_create",   # Create a discovery (CAN-FORGE / UA anchor)
    "thread_create",      # Create an unresolved thread (CAN-FORGE)
    "zone_create",        # Create new zone (ZONE-FORGE CP expansion)
    "zone_update",        # Update existing zone (add CPs, etc.)
}

# Default constraints
DEFAULT_CONSTRAINTS = {
    "max_words": 300,
    "tone": "sword_and_sorcery",
    "style": "Compressed prose. Inspirations: Elric, Conan, Dark Crystal, Krull, Willow, LotR.",
    "voice": "Second person present tense. The player IS the character. 'You stand at the gate' not 'Thoron stood at the gate'. Never use the PC name as subject.",
}

# DG-22: Mode-specific constraint overlays
MODE_CONSTRAINTS = {
    "INTENS": {
        "mode": "INTENS",
        "mode_instruction": (
            "MODE: INTENS v3.0. Focus on dialogue and relationship pressure. "
            "Surface emotional themes, NPC goals/emotion. "
            "Format: 1) Context  2) Dialogue (NPC only)  3) Rising intensity  "
            "4) Decision or Silence. "
            "End with suggested options + travel options. "
            "Prose-only. No PC dialogue authored. No mechanical annotations."
        ),
    },
    "INTIM": {
        "mode": "INTIM",
        "mode_instruction": (
            "MODE: INTIM v3.0. Focus on intimacy, sensuality, NPC desire/emotion. "
            "Format: 1) Proximity  2) NPC Action  3) Player Reaction Prompt  "
            "4) Choice. "
            "End with suggested options + travel options. "
            "Prose-only. No PC dialogue authored. No mechanical annotations."
        ),
    },
    "INVESTIG": {
        "mode": "INVESTIG",
        "mode_instruction": (
            "MODE: INVESTIG v3.0. Focus on observation, inference, clue discovery. "
            "Surface what can be observed vs inferred. "
            "Format: 1) Observations  2) NPC Reactions (on-screen)  "
            "3) Uncertainties  4) Decision Point. "
            "End with suggested options + travel options. "
            "Prose-only. No PC dialogue authored. No mechanical annotations."
        ),
    },
    "RUMOR": {
        "mode": "RUMOR",
        "mode_instruction": (
            "MODE: RUMOR v3.0. Invent one plausible rumor circulating in current zone. "
            "1d8 roll determines truth: on 1, rumor is ACTUALLY TRUE; "
            "otherwise FALSE/distorted/exaggerated. "
            "Reflect tensions, recent events, faction agendas. "
            "May hint at clocks, offscreen moves, threats. "
            "Format: 1-2 sentences, optional source attribution. "
            "No quotes or mechanical annotations."
        ),
    },
}


@dataclass
class CreativeRequest:
    """A structured request for creative content from an LLM."""
    id: str                         # "cr_001"
    type: str                       # One of REQUEST_TYPES
    context: dict = field(default_factory=dict)       # Focused payload
    constraints: dict = field(default_factory=dict)   # Word limits, tone, format

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'CreativeRequest':
        return cls(
            id=data["id"],
            type=data["type"],
            context=data.get("context", {}),
            constraints=data.get("constraints", {}),
        )


@dataclass
class CreativeResponse:
    """A structured response containing creative content from an LLM."""
    id: str                         # Must match a request id
    type: str                       # Must match request type
    content: str = ""               # The creative text output
    state_changes: list = field(default_factory=list)  # State mutations to apply

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'CreativeResponse':
        return cls(
            id=data["id"],
            type=data["type"],
            content=data.get("content", ""),
            state_changes=data.get("state_changes", []),
        )


# ─────────────────────────────────────────────────────
# REQUEST BUILDERS
# ─────────────────────────────────────────────────────

_request_counter = 0


def _next_id() -> str:
    global _request_counter
    _request_counter += 1
    return f"cr_{_request_counter:03d}"


def reset_request_counter():
    global _request_counter
    _request_counter = 0


def build_narr_arrival(state, active_mode: str = None, travel_info: dict = None) -> CreativeRequest:
    """Build a NARR_ARRIVAL request for the current zone."""
    zone = state.zones.get(state.pc_zone)
    zone_context = {}
    if zone:
        zone_context = {
            "zone_name": zone.name,
            "description": zone.description,
            "threat_level": zone.threat_level,
            "situation_summary": zone.situation_summary,
            "controlling_faction": zone.controlling_faction,
        }

    present_npcs = []
    for npc in state.npcs_in_zone(state.pc_zone):
        present_npcs.append({
            "name": npc.name,
            "role": npc.role,
            "trait": npc.trait,
            "is_companion": npc.is_companion,
        })

    companions = []
    for npc in state.companions_with_pc():
        companions.append({
            "name": npc.name,
            "trait": npc.trait,
            "status": npc.status,
        })

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    zone_lore = lore.get_zone_lore(state.pc_zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore
    if zone and zone.controlling_faction:
        fac_lore = lore.get_faction_lore(zone.controlling_faction)
        if fac_lore:
            lore_dict[f"faction:{zone.controlling_faction}"] = fac_lore
    for npc_info in present_npcs:
        npc_lore = lore.get_npc_lore(npc_info["name"], max_lines=15)
        if npc_lore:
            lore_dict[f"npc:{npc_info['name']}"] = npc_lore

    # Travel journey context (where from, how long, which CP)
    journey = {}
    if travel_info:
        journey = {
            "from_zone": travel_info.get("old_zone", ""),
            "crossing_point": travel_info.get("cp_name", ""),
            "cp_tag": travel_info.get("cp_tag", ""),
            "days_traveled": travel_info.get("days_traveled", 1),
            "is_eventful": travel_info.get("is_eventful", False),
        }

    return CreativeRequest(
        id=_next_id(),
        type="NARR_ARRIVAL",
        context={
            "zone": zone_context,
            "travel": journey,
            "present_npcs": present_npcs,
            "companions_with_pc": companions,
            "season": state.season,
            "seasonal_pressure": state.seasonal_pressure,
            "in_game_date": state.in_game_date,
            "recent_facts": state.daily_facts[-5:] if state.daily_facts else [],
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS, "max_words": 300,
            "instruction": (
                "Narrate arrival at this zone. Cover: journey, "
                "first impressions, sensory detail, companion reactions, "
                "immediate situation. Do NOT advance time or resolve encounters."
            ),
            # DG-22: Inject mode constraints
            **(MODE_CONSTRAINTS.get(active_mode, {}) if active_mode else {}),
        },
    )


def build_narr_encounter(state, encounter_data: dict, active_mode: str = None) -> CreativeRequest:
    """Build a NARR_ENCOUNTER request for a triggered encounter."""
    # Zone context for encounter framing
    zone = state.zones.get(state.pc_zone)
    zone_context = {}
    if zone:
        zone_context = {
            "zone_name": zone.name,
            "description": zone.description,
            "threat_level": zone.threat_level,
            "controlling_faction": zone.controlling_faction,
        }

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    zone_lore = lore.get_zone_lore(state.pc_zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore
    if encounter_data.get("has_bx_plug"):
        bx_rules = lore.get_bx_plug(["0", "1", "6", "9"])
        if bx_rules:
            lore_dict["bx_plug_rules"] = bx_rules

    return CreativeRequest(
        id=_next_id(),
        type="NARR_ENCOUNTER",
        context={
            "zone": zone_context if zone_context else state.pc_zone,
            "encounter_description": encounter_data.get("description", ""),
            "has_bx_plug": encounter_data.get("has_bx_plug", False),
            "bx_stat_block": encounter_data.get("bx_stat_block", ""),
            "ua_cue": encounter_data.get("ua_cue", False),
            "tags": encounter_data.get("tags", []),
            "season": state.season,
            "in_game_date": state.in_game_date,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 250,
            "instruction": (
                "Narrate the encounter. If BX-PLUG combat is flagged, "
                "describe initial contact and set up ATTACK/FLEE choice."
            ),
            # DG-22: Inject mode constraints
            **(MODE_CONSTRAINTS.get(active_mode, {}) if active_mode else {}),
        },
    )


def build_narr_time_passage(state, days_passed: int, day_logs: list,
                            active_mode: str = None) -> CreativeRequest:
    """Build a NARR_TIME_PASSAGE request to narrate the passage of time after T&P."""
    zone = state.zones.get(state.pc_zone)
    zone_context = {}
    if zone:
        zone_context = {
            "zone_name": zone.name,
            "description": zone.description,
            "threat_level": zone.threat_level,
            "situation_summary": zone.situation_summary,
            "controlling_faction": zone.controlling_faction,
        }

    companions = []
    for npc in state.companions_with_pc():
        companions.append({
            "name": npc.name, "trait": npc.trait, "status": npc.status,
        })

    present_npcs = []
    for npc in state.npcs_in_zone(state.pc_zone):
        if not npc.is_companion:
            present_npcs.append({
                "name": npc.name, "role": npc.role, "trait": npc.trait,
            })

    # Extract mechanical events from day logs for narration context
    encounters = []
    npag_results = []
    clock_changes = []
    start_date = ""
    end_date = ""

    for dl in day_logs:
        if not start_date:
            start_date = dl.get("date", "")
        end_date = dl.get("date", "")

        for step in dl.get("steps", []):
            sn = step["step"]
            r = step.get("result", step.get("results", {}))

            if sn == "encounter_gate" and r.get("passed"):
                enc = r.get("encounter", {})
                encounters.append(enc.get("description", "encounter"))

            if sn == "npag_gate" and r.get("passed"):
                npag_results.append({
                    "npc_count": r.get("npc_count", {}).get("count", 0),
                })

            if sn == "cadence_clocks":
                for cr in (step.get("results", []) if isinstance(step.get("results"), list) else []):
                    if cr.get("action") != "cadence_eligible_for_audit" and "error" not in cr:
                        clock_changes.append(
                            f"{cr.get('clock', '?')}: {cr.get('old', '?')}->{cr.get('new', '?')}")

            if sn == "clock_audit":
                for a in r.get("auto_advanced", []):
                    ar = a.get("advance_result", {})
                    clock_changes.append(
                        f"{a.get('clock', '?')}: {ar.get('old', '?')}->{ar.get('new', '?')}")

    # Lore context
    lore = get_lore_index()
    lore_dict = {}
    zone_lore = lore.get_zone_lore(state.pc_zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore

    return CreativeRequest(
        id=_next_id(),
        type="NARR_TIME_PASSAGE",
        context={
            "days_passed": days_passed,
            "start_date": start_date,
            "end_date": end_date,
            "zone": zone_context,
            "companions_with_pc": companions,
            "npcs_present": present_npcs,
            "encounters_this_period": encounters,
            "npag_results_this_period": npag_results,
            "clock_changes_this_period": clock_changes,
            "season": state.season,
            "in_game_date": state.in_game_date,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 300,
            "instruction": (
                f"Narrate the passage of {days_passed} day(s). "
                "Weave in any encounters and NPAG results that the PC would "
                "learn about. Not all NPAG actions are visible to the PC — "
                "only include what they would realistically see, hear, or be told. "
                "Even uneventful days deserve a sense of time passing."
            ),
            **(MODE_CONSTRAINTS.get(active_mode, {}) if active_mode else {}),
        },
    )


def build_clock_audit(clock_name: str, progress: str,
                      ambiguous_bullets: list, daily_facts: list) -> CreativeRequest:
    """Build a CLOCK_AUDIT request for ambiguous ADV bullet review."""
    return CreativeRequest(
        id=_next_id(),
        type="CLOCK_AUDIT",
        context={
            "clock": clock_name,
            "progress": progress,
            "ambiguous_bullets": ambiguous_bullets,
            "daily_facts": daily_facts,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 100,
            "instruction": (
                "Review whether these ADV bullets are UNAMBIGUOUSLY satisfied "
                "by today's established facts. Respond 'advance' or 'no_advance' "
                "with reasoning. Do NOT invent events to justify advancement."
            ),
        },
    )


def build_npag(state, npc_count: int) -> CreativeRequest:
    """Build an NPAG request for NPC agency resolution."""
    eligible_npcs = []
    for npc in state.npcs.values():
        if npc.status == "active" and (npc.objective or npc.next_action):
            eligible_npcs.append({
                "name": npc.name,
                "zone": npc.zone,
                "role": npc.role,
                "trait": npc.trait,
                "objective": npc.objective,
                "knowledge": npc.knowledge,
                "next_action": npc.next_action,
                "faction": npc.faction,
                "with_pc": npc.with_pc,
            })

    # DG-20: Inject NPC and faction lore for acting NPCs
    lore = get_lore_index()
    lore_dict = {}
    seen_factions = set()
    for npc_info in eligible_npcs[:npc_count]:
        npc_lore = lore.get_npc_lore(npc_info["name"], max_lines=10)
        if npc_lore:
            lore_dict[f"npc:{npc_info['name']}"] = npc_lore
        fac = npc_info.get("faction", "")
        if fac and fac not in seen_factions:
            fac_lore = lore.get_faction_lore(fac)
            if fac_lore:
                lore_dict[f"faction:{fac}"] = fac_lore
            seen_factions.add(fac)

    # Inject companion profiles (spec: "companion profiles and faction data")
    for npc in state.npcs.values():
        if npc.is_companion and npc.name in state.companions:
            comp = state.companions[npc.name]
            lore_dict[f"companion:{npc.name}"] = {
                "trust_in_pc": getattr(comp, "trust_in_pc", ""),
                "motivation_shift": getattr(comp, "motivation_shift", ""),
                "grievances": getattr(comp, "grievances", ""),
                "agency_notes": getattr(comp, "agency_notes", ""),
            }

    return CreativeRequest(
        id=_next_id(),
        type="NPAG",
        context={
            "npc_count": npc_count,
            "eligible_npcs": eligible_npcs[:20],  # Cap for token economy
            "pc_zone": state.pc_zone,
            "in_game_date": state.in_game_date,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 50 * npc_count,  # ~50 words per NPC action
            "instruction": (
                f"Resolve agency actions for {npc_count} NPCs. "
                "Choose NPCs with active objectives. Describe off-screen actions. "
                "Note any clock ADV bullets their actions satisfy."
            ),
        },
    )


def build_session_summary(state) -> CreativeRequest:
    """Build a SESSION_SUMMARY request for end-of-session wrap-up (DG-19)."""
    # Gather session events from adjudication_log
    session_events = [
        e for e in state.adjudication_log
        if e.get("session") == state.session_id
    ]

    # Active clocks summary
    clock_summary = [
        {"name": c.name, "progress": f"{c.progress}/{c.max_progress}", "status": c.status}
        for c in state.clocks.values() if c.status != "retired"
    ]

    # Companions with PC (from NPC list, not CompanionDetail)
    companions = [
        {"name": n.name, "status": n.status, "zone": getattr(n, "zone", "")}
        for n in state.npcs.values() if n.is_companion and n.with_pc
    ]

    return CreativeRequest(
        id=_next_id(),
        type="SESSION_SUMMARY",
        context={
            "session_id": state.session_id,
            "in_game_date": state.in_game_date,
            "pc_zone": state.pc_zone,
            "season": state.season,
            "event_count": len(session_events),
            "recent_events": session_events[-20:],
            "clock_summary": clock_summary,
            "companions_with_pc": companions,
            "previous_summary": state.session_summaries.get(
                str(state.session_id - 1), ""),
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 600,
            "instruction": (
                "Write a 400-600 word narrative summary of this session. "
                "Cover: key events, clock movements, NPC developments, "
                "player decisions and their consequences. "
                "End with a 1-sentence hook for next session. "
                "Write in past tense, third person."
            ),
        },
    )


# ─────────────────────────────────────────────────────
# COMBAT NARRATION (DG-16)
# ─────────────────────────────────────────────────────

def build_narr_combat_end(state, combat_state) -> CreativeRequest:
    """Build a NARR_COMBAT_END request for post-combat aftermath narration."""
    zone_obj = state.zones.get(state.pc_zone)
    zone_context = {}
    if zone_obj:
        zone_context = {
            "zone_name": zone_obj.name,
            "description": zone_obj.description,
            "controlling_faction": zone_obj.controlling_faction,
            "threat_level": zone_obj.threat_level,
        }

    combat_summary = {
        "rounds": combat_state.round_number,
        "end_reason": combat_state.end_reason,
        "encounter_prompt": combat_state.encounter_prompt[:120],
        "pc_hp_final": None,
        "companions_status": [],
        "foes_status": [],
        "key_events": [],
    }

    for c in combat_state.pc_side:
        if c.is_pc:
            combat_summary["pc_hp_final"] = f"{max(0, c.hp)}/{c.hp_max}"
        elif c.is_companion:
            combat_summary["companions_status"].append({
                "name": c.name,
                "hp": f"{max(0, c.hp)}/{c.hp_max}",
                "down": c.is_down,
            })

    for c in combat_state.foe_side:
        combat_summary["foes_status"].append({
            "name": c.name,
            "down": c.is_down,
        })

    # Extract key events from combat log
    for entry in combat_state.combat_log:
        if "KILLED" in entry or "DOWN" in entry:
            combat_summary["key_events"].append(entry)
        elif "BROKEN" in entry:
            combat_summary["key_events"].append(entry)
        elif "FLEE_SUCCESS" in entry:
            combat_summary["key_events"].append(entry)

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    zone_lore = lore.get_zone_lore(state.pc_zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore

    return CreativeRequest(
        id=_next_id(),
        type="NARR_COMBAT_END",
        context={
            "zone": zone_context,
            "combat_summary": combat_summary,
            "season": state.season,
            "in_game_date": state.in_game_date,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 300,
            "instruction": (
                "Narrate the aftermath of this combat encounter. "
                "Cover: how the fight resolved, injuries sustained, "
                "companion reactions, any loot or consequences. "
                "Do NOT re-narrate the mechanical combat round by round — "
                "the engine already resolved that. Focus on the aftermath, "
                "mood, and what happens next."
            ),
        },
    )


# ─────────────────────────────────────────────────────
# SESSION START NARRATION
# ─────────────────────────────────────────────────────

def build_narr_session_start(state) -> CreativeRequest:
    """Build NARR_SESSION_START — opening scene after ZONE-FORGE cascade."""
    zone = state.zones.get(state.pc_zone)
    zone_context = {}
    if zone:
        zone_context = {
            "zone_name": zone.name,
            "description": zone.description,
            "threat_level": zone.threat_level,
            "controlling_faction": zone.controlling_faction,
        }

    companions = []
    for npc in state.companions_with_pc():
        companions.append({
            "name": npc.name,
            "trait": npc.trait,
            "status": npc.status,
        })

    npcs_in_zone = []
    for npc in state.npcs_in_zone(state.pc_zone):
        if not npc.is_companion:
            npcs_in_zone.append({
                "name": npc.name,
                "role": npc.role,
                "trait": npc.trait,
            })

    # 3 most recent open threads
    open_threads = [t for t in state.unresolved_threads if not t.resolved]
    recent_threads = [
        {"id": t.id, "description": t.description}
        for t in open_threads[-3:]
    ]

    # Previous session summary
    prev_summary = state.session_summaries.get(
        str(state.session_id - 1), ""
    )

    # DG-20: Lore injection
    lore = get_lore_index()
    lore_dict = {}
    zone_lore = lore.get_zone_lore(state.pc_zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore
    for comp in companions:
        npc_lore = lore.get_npc_lore(comp["name"], max_lines=15)
        if npc_lore:
            lore_dict[f"npc:{comp['name']}"] = npc_lore

    return CreativeRequest(
        id=_next_id(),
        type="NARR_SESSION_START",
        context={
            "zone": zone_context,
            "session_id": state.session_id,
            "in_game_date": state.in_game_date,
            "season": state.season,
            "seasonal_pressure": state.seasonal_pressure,
            "companions_with_pc": companions,
            "npcs_in_zone": npcs_in_zone,
            "active_threads": recent_threads,
            "previous_session_summary": prev_summary,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS, "max_words": 400,
            "instruction": (
                "Set the opening scene for this session. "
                "Establish where the PC is, the zone atmosphere, "
                "who is present (companions and notable NPCs), "
                "and weave in the active threads as stakes the player can feel. "
                "This is the first thing the player reads — set tone, ground them "
                "in the world, and give them something to react to. "
                "Do NOT advance time, resolve encounters, or trigger mechanical gates."
            ),
        },
    )


# ─────────────────────────────────────────────────────
# RUMOR (DG-22)
# ─────────────────────────────────────────────────────

def build_player_input(state, intent: str, active_mode: str = None) -> CreativeRequest:
    """Build a PLAYER_INPUT request — player typed in-character intent."""
    zone_obj = state.zones.get(state.pc_zone)
    zone_ctx = {}
    if zone_obj:
        zone_ctx = {
            "zone_name": zone_obj.name,
            "description": zone_obj.description,
            "controlling_faction": zone_obj.controlling_faction,
            "threat_level": zone_obj.threat_level,
        }

    companions = []
    for npc in state.companions_with_pc():
        companions.append({
            "name": npc.name,
            "trait": npc.trait,
        })

    present_npcs = []
    for npc in state.npcs_in_zone(state.pc_zone):
        if not npc.is_companion:
            present_npcs.append({
                "name": npc.name,
                "role": npc.role,
                "trait": npc.trait,
            })

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    zone_lore = lore.get_zone_lore(state.pc_zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore

    return CreativeRequest(
        id=_next_id(),
        type="PLAYER_INPUT",
        context={
            "intent": intent,
            "mode": active_mode or "",
            "mode_instruction": (
                MODE_CONSTRAINTS.get(active_mode, {}).get("mode_instruction", "")
                if active_mode else ""
            ),
            "zone": zone_ctx,
            "pc_zone": state.pc_zone,
            "companions_with_pc": companions,
            "npcs_present": present_npcs,
            "in_game_date": state.in_game_date,
            "season": state.season,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "instruction": (
                f"The player says: \"{intent}\"\n"
                "Narrate what happens in response to the player's action or dialogue. "
                "Stay in-world. React to the intent naturally within the current scene. "
                "If the player speaks, NPCs present may respond. "
                "If the player acts, describe the outcome."
            ),
            # DG-22: Inject mode constraints
            **(MODE_CONSTRAINTS.get(active_mode, {}) if active_mode else {}),
        },
    )


def build_rumor(state) -> CreativeRequest:
    """Build a RUMOR request — one-shot rumor generation for the current zone."""
    from dice import roll_dice as _roll
    truth_roll = _roll("1d8", "RUMOR truth check")
    is_true = truth_roll["total"] == 1

    zone_obj = state.zones.get(state.pc_zone)
    zone_ctx = {}
    if zone_obj:
        zone_ctx = {
            "zone_name": zone_obj.name,
            "description": zone_obj.description,
            "controlling_faction": zone_obj.controlling_faction,
            "threat_level": zone_obj.threat_level,
        }

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    zone_lore = lore.get_zone_lore(state.pc_zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore
    for fname in state.factions:
        fac = state.factions[fname]
        if fac.status == "active":
            fac_lore = lore.get_faction_lore(fname)
            if fac_lore:
                lore_dict[f"faction:{fname}"] = fac_lore

    return CreativeRequest(
        id=_next_id(),
        type="RUMOR",
        context={
            "zone": zone_ctx,
            "pc_zone": state.pc_zone,
            "truth_roll": truth_roll["total"],
            "is_true": is_true,
            "season": state.season,
            "in_game_date": state.in_game_date,
            "active_clocks": [
                {"name": c.name, "progress": f"{c.progress}/{c.max_progress}"}
                for c in state.clocks.values()
                if c.status == "active"
            ][:5],
            "active_factions": [
                f.name for f in state.factions.values()
                if f.status == "active"
            ][:5],
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 60,
            "instruction": (
                f"Generate ONE plausible rumor circulating in {state.pc_zone}. "
                f"Truth roll: 1d8={truth_roll['total']}. "
                f"{'This rumor is ACTUALLY TRUE.' if is_true else 'This rumor is FALSE, distorted, or exaggerated.'} "
                "Reflect current tensions, recent events, or faction agendas. "
                "May hint at hidden clocks, faction moves, or future threats. "
                "Format: 1-2 sentences, source optional. "
                "Return content as the rumor text. No state_changes needed."
            ),
        },
    )


# ─────────────────────────────────────────────────────
# FORGE REQUEST BUILDERS (DG-17)
# ─────────────────────────────────────────────────────

def build_npc_forge(state, zone: str,
                    role_hint: str = "", faction_hint: str = "",
                    max_clocks: int = 2) -> CreativeRequest:
    """Build an NPC_FORGE request to create an NPC with BX stats."""
    zone_obj = state.zones.get(zone)
    zone_ctx = {}
    if zone_obj:
        zone_ctx = {
            "description": zone_obj.description,
            "threat_level": zone_obj.threat_level,
            "controlling_faction": zone_obj.controlling_faction,
            "intensity": zone_obj.intensity,
        }

    existing_npcs = [
        {"name": n.name, "role": n.role, "faction": n.faction}
        for n in state.npcs.values() if n.zone == zone
    ]

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    forge_spec = lore.get_forge_spec("NPC-FORGE")
    if forge_spec:
        lore_dict["forge_spec"] = forge_spec
    zone_lore = lore.get_zone_lore(zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore
    if faction_hint:
        fac_lore = lore.get_faction_lore(faction_hint)
        if fac_lore:
            lore_dict[f"faction:{faction_hint}"] = fac_lore

    # Clamp max_clocks to valid range (NPC-FORGE §2.3)
    max_clocks = max(0, min(5, max_clocks))

    return CreativeRequest(
        id=_next_id(),
        type="NPC_FORGE",
        context={
            "zone": zone,
            "zone_data": zone_ctx,
            "existing_npcs_in_zone": existing_npcs,
            "existing_factions": list(state.factions.keys()),
            "role_hint": role_hint,
            "faction_hint": faction_hint,
            "max_clocks": max_clocks,
            "session_id": state.session_id,
            "season": state.season,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 100,
            "max_clocks": max_clocks,
            "instruction": (
                "Create one NPC for this zone. Return a state_change with type 'npc_create'. "
                "Required fields: name, zone, role, trait (1-2 words), "
                "appearance (short identifying phrase), faction (from existing factions or 'none'). "
                "Optional: objective, knowledge, next_action. "
                "BX stats: bx_ac (9-20), bx_hd (1-8), bx_hp (rolled from HD), "
                "bx_hp_max (same as hp), bx_at (HD-based), bx_dmg (weapon die string), bx_ml (5-12). "
                f"Optional new clocks: up to {max_clocks} (use clock_create state_changes). "
                "Do NOT duplicate existing NPC names in this zone."
            ),
        },
    )


def build_el_forge(state, zone: str) -> CreativeRequest:
    """Build an EL_FORGE request to create an encounter list for a zone."""
    zone_obj = state.zones.get(zone)
    zone_ctx = {}
    if zone_obj:
        zone_ctx = {
            "description": zone_obj.description,
            "threat_level": zone_obj.threat_level,
            "controlling_faction": zone_obj.controlling_faction,
            "intensity": zone_obj.intensity,
        }

    existing_npcs = [
        {"name": n.name, "role": n.role}
        for n in state.npcs.values() if n.zone == zone
    ]

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    forge_spec = lore.get_forge_spec("EL-FORGE")
    if forge_spec:
        lore_dict["forge_spec"] = forge_spec
    zone_lore = lore.get_zone_lore(zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore

    # Tone constraints from lore (EL-FORGE §2.1.8)
    tone_constraints = ""
    place_lore = lore.get_zone_lore(zone) if lore else ""
    if place_lore:
        tone_constraints = place_lore
    # Heat level default (EL-FORGE §2.1.9)
    heat_level = "routine_only"

    return CreativeRequest(
        id=_next_id(),
        type="EL_FORGE",
        context={
            "zone": zone,
            "zone_data": zone_ctx,
            "existing_npcs_in_zone": existing_npcs,
            "season": state.season,
            "seasonal_pressure": state.seasonal_pressure,
            "session_id": state.session_id,
            "tone_constraints": tone_constraints,
            "heat_level": heat_level,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 400,
            "heat_level": heat_level,
            "instruction": (
                "Create an encounter list for this zone. Return a state_change with type 'el_create'. "
                "Fields: zone, randomizer (e.g. '1d6', '1d8', '1d10', '2d6'), "
                "fallback_priority (1-4, higher = more remote), adjacency_notes (comma-separated zone flavor). "
                "entries: list of objects with range (e.g. '1', '1-2', '5-6'), "
                "prompt (1-2 sentence encounter description), ua_cue (bool, true if tagged [UA]), "
                "bx_plug (dict with type/skill/save_damage/hostile_action/stats, or empty {}). "
                "bx_plug.type: 'reaction', 'save', 'skill_check', or 'combat'. "
                "Heat level: routine_only (default — routine encounters, no world-shaking events). "
                "Mix combat and non-combat. Fit zone theme and threat level."
            ),
        },
    )


def build_fac_forge(state, faction_name: str = "",
                    zone_hint: str = "") -> CreativeRequest:
    """Build a FAC_FORGE request to create or update a faction."""
    is_update = bool(faction_name and faction_name in state.factions)
    existing_data = None
    if is_update:
        fac = state.factions[faction_name]
        existing_data = {
            "name": fac.name, "status": fac.status, "trend": fac.trend,
            "disposition": fac.disposition, "last_action": fac.last_action,
            "notes": fac.notes,
        }

    zone_ctx = {}
    if zone_hint:
        zone_obj = state.zones.get(zone_hint)
        if zone_obj:
            zone_ctx = {
                "description": zone_obj.description,
                "controlling_faction": zone_obj.controlling_faction,
            }

    controlling = {z.name: z.controlling_faction
                   for z in state.zones.values() if z.controlling_faction}

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    forge_spec = lore.get_forge_spec("FAC-FORGE")
    if forge_spec:
        lore_dict["forge_spec"] = forge_spec
    if is_update and faction_name:
        fac_lore = lore.get_faction_lore(faction_name)
        if fac_lore:
            lore_dict[f"faction:{faction_name}"] = fac_lore

    return CreativeRequest(
        id=_next_id(),
        type="FAC_FORGE",
        context={
            "faction_name": faction_name,
            "is_update": is_update,
            "existing_faction_data": existing_data,
            "existing_factions": list(state.factions.keys()),
            "zone_hint": zone_hint,
            "zone_data": zone_ctx,
            "controlling_factions": controlling,
            "session_id": state.session_id,
            "season": state.season,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 150,
            "instruction": (
                f"{'Update' if is_update else 'Create'} a faction. "
                f"Return a state_change with type '{'faction_update' if is_update else 'faction_create'}'. "
                "Fields: name, status (active/inactive/destroyed/unknown), "
                "trend (stable/rising/declining), disposition toward PC "
                "(friendly/neutral/hostile/unknown), notes (2-3 sentences). "
                "For updates: include only changed fields plus name. "
                "Add history_entry (1 sentence) describing the change."
            ),
        },
    )


def build_cl_forge(state, owner: str,
                   trigger_context: str = "") -> CreativeRequest:
    """Build a CL_FORGE request to create a clock (DG-17 + DG-18)."""
    existing_clocks = [
        {"name": c.name, "owner": c.owner,
         "progress": f"{c.progress}/{c.max_progress}", "status": c.status}
        for c in state.clocks.values() if c.status != "retired"
    ]

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    forge_spec = lore.get_forge_spec("CL-FORGE")
    if forge_spec:
        lore_dict["forge_spec"] = forge_spec

    return CreativeRequest(
        id=_next_id(),
        type="CL_FORGE",
        context={
            "owner": owner,
            "trigger_context": trigger_context,
            "existing_clocks": existing_clocks,
            "existing_factions": list(state.factions.keys()),
            "pc_zone": state.pc_zone,
            "session_id": state.session_id,
            "season": state.season,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 200,
            "instruction": (
                "Create a clock. Return a state_change with type 'clock_create'. "
                "Fields: name (format 'Owner\u2014Concept'), owner, "
                "max_progress (4-16), advance_bullets (3-5 observable condition strings), "
                "halt_conditions (1-2), reduce_conditions (1-2), "
                "trigger_on_completion (what happens when filled). "
                "Optional: is_cadence (true if auto-advance daily), cadence_bullet. "
                "ADV bullets must be observable facts, not vague conditions."
            ),
        },
    )


def build_can_forge(state, zone: str,
                    trigger: str = "manual",
                    mode: str = "full") -> CreativeRequest:
    """Build a CAN_FORGE request — zone canonicalization macro.

    mode="full": Player-invoked — creates FAC + NPC + CL + EL + PE + UA
    plus mandatory discovery and optional unresolved thread.
    mode="ZONE-FORGE": Engine-invoked — UA + clock + discovery ONLY.
    Hard caps enforced: no faction, no NPC, no EL, no PE.
    """
    zone_obj = state.zones.get(zone)
    zone_ctx = {}
    if zone_obj:
        zone_ctx = {
            "description": zone_obj.description,
            "threat_level": zone_obj.threat_level,
        }

    # Existing entities in zone for Claude's context
    zone_npcs = [
        {"name": n.name, "role": n.role, "faction": n.faction, "status": n.status}
        for n in state.npcs.values() if n.zone == zone
    ]
    zone_factions = [
        {"name": f.name, "status": f.status, "disposition": f.disposition}
        for f in state.factions.values()
    ]
    zone_clocks = [
        {"name": c.name, "owner": c.owner, "progress": f"{c.progress}/{c.max_progress}"}
        for c in state.clocks.values()
    ]
    zone_engines = [
        {"name": e.name, "zone_scope": e.zone_scope, "status": e.status}
        for e in state.engines.values()
        if e.zone_scope == zone or e.zone_scope == "Global"
    ]
    zone_uas = [
        {"id": u.get("id", ""), "zone": u.get("zone", ""), "status": u.get("status", "")}
        for u in state.ua_log if u.get("zone") == zone
    ]
    existing_els = list(state.encounter_lists.keys())

    next_ua_code = f"UA-{len(state.ua_log) + 1:02d}"

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    forge_spec = lore.get_forge_spec("CAN-FORGE")
    if forge_spec:
        lore_dict["forge_spec"] = forge_spec
    zone_lore = lore.get_zone_lore(zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore

    ctx = {
        "zone": zone,
        "zone_data": zone_ctx,
        "trigger": trigger,
        "mode": mode,
        "existing_npcs_in_zone": zone_npcs,
        "existing_factions": zone_factions,
        "existing_clocks": zone_clocks,
        "existing_engines": zone_engines,
        "existing_uas_in_zone": zone_uas,
        "existing_encounter_lists": existing_els,
        "next_ua_code": next_ua_code,
        "pc_zone": state.pc_zone,
        "session_id": state.session_id,
        "season": state.season,
        "lore": lore_dict,
    }

    if mode == "ZONE-FORGE":
        constraints = {
            **DEFAULT_CONSTRAINTS,
            "max_words": 300,
            "mode": "ZONE-FORGE",
            "visibility": "secret",
            "pc_targeting": "forbidden",
            "caps": {
                "new_ua_codes": 1,
                "new_clocks": 1,
                "new_discoveries": 1,
                "new_factions": 0,
                "new_npcs": 0,
                "new_el_def": 0,
                "new_pe_def": 0,
            },
            "instruction": (
                "ZONE-FORGE mode. Create ONLY the following state_changes: "
                "1) ua_create — 1 Unknown Actor "
                f"(use ua_id '{next_ua_code}'). "
                "2) clock_create — 1 clock (owner = new UA or environment). "
                "3) discovery_create — 1 discovery (MANDATORY). "
                "Do NOT create: faction, NPC, encounter list, or procedural engine. "
                "CAN-FORGE outputs ONLY save-ready inserts. "
                "No narration, no prose, no scenes, no AGENCY ACTIONS. "
                "New clocks start at 0. No canon invention."
            ),
        }
    else:
        constraints = {
            **DEFAULT_CONSTRAINTS,
            "max_words": 500,
            "instruction": (
                "Canonicalize this zone. Player-invoked full mode. "
                "Return MULTIPLE state_changes (all required unless noted): "
                "1) faction_create \u2014 1 new faction for this zone. "
                "2) npc_create \u2014 1 new named NPC for this zone (with BX stats). "
                "3) clock_create \u2014 1-2 new clocks (owners must be existing entities). "
                "4) el_create \u2014 1 encounter list for this zone (6 entries with range/prompt). "
                "5) pe_create \u2014 1 persistent procedural engine for this zone. "
                "6) ua_create \u2014 1 Unknown Actor "
                f"(use ua_id '{next_ua_code}'). "
                "7) discovery_create \u2014 1 discovery (MANDATORY, can serve as UA anchor). "
                "8) thread_create \u2014 1 unresolved thread (if durable stakes introduced). "
                "CAN-FORGE outputs ONLY save-ready inserts. "
                "No narration, no prose, no scenes, no AGENCY ACTIONS. "
                "New clocks start at 0. No canon invention."
            ),
        }

    return CreativeRequest(
        id=_next_id(),
        type="CAN_FORGE",
        context=ctx,
        constraints=constraints,
    )


def build_pe_forge(state, engine_name: str,
                   zone_scope: str = "",
                   trigger_event: str = "") -> CreativeRequest:
    """Build a PE_FORGE request to design one persistent procedural engine."""
    existing_engines = [
        {"name": e.name, "version": e.version, "status": e.status,
         "zone_scope": e.zone_scope, "trigger_event": e.trigger_event}
        for e in state.engines.values()
    ]

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    forge_spec = lore.get_forge_spec("PE-FORGE")
    if forge_spec:
        lore_dict["forge_spec"] = forge_spec
    if zone_scope:
        zone_lore = lore.get_zone_lore(zone_scope)
        if zone_lore:
            lore_dict["zone_atmosphere"] = zone_lore

    return CreativeRequest(
        id=_next_id(),
        type="PE_FORGE",
        context={
            "engine_name": engine_name,
            "zone_scope": zone_scope or state.pc_zone,
            "trigger_event": trigger_event,
            "existing_engines": existing_engines,
            "pc_zone": state.pc_zone,
            "session_id": state.session_id,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 200,
            "instruction": (
                "Design one persistent procedural engine (PE-DEF). "
                "Return a state_change with type 'pe_create'. "
                "Required fields: engine_name, version (e.g. '1.0'), "
                "authority_tier (ZONE-LOCAL|GLOBAL), "
                "registry_target (CSEM|SSM_1A|NSV_DELTA_REGISTRY), "
                "zone_scope, state_scope, "
                "cadence (true/false), trigger_event (1-3 phrases), "
                "hard_gates (list of strings), resolution_method, "
                "run_cap_per_day (int, default 1). "
                "Optional: randomizer, linked_clocks (list of existing clock names). "
                "No canon invention. No clocks created inside PE-DEF. "
                "Respect registry immutability."
            ),
        },
    )


def build_ua_forge(state, zone: str,
                   trigger_context: str = "") -> CreativeRequest:
    """Build a UA_FORGE request to create an Unknown Actor entry."""
    zone_obj = state.zones.get(zone)
    zone_ctx = {}
    if zone_obj:
        zone_ctx = {
            "description": zone_obj.description,
            "threat_level": zone_obj.threat_level,
        }

    next_code = f"UA-{len(state.ua_log) + 1:02d}"

    # DG-20: Inject lore context
    lore = get_lore_index()
    lore_dict = {}
    forge_spec = lore.get_forge_spec("UA-FORGE")
    if forge_spec:
        lore_dict["forge_spec"] = forge_spec
    zone_lore = lore.get_zone_lore(zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore

    return CreativeRequest(
        id=_next_id(),
        type="UA_FORGE",
        context={
            "zone": zone,
            "zone_data": zone_ctx,
            "trigger_context": trigger_context,
            "existing_uas": [{"id": u.get("id", ""), "zone": u.get("zone", ""),
                              "status": u.get("status", "")}
                             for u in state.ua_log],
            "next_ua_code": next_code,
            "session_id": state.session_id,
            "season": state.season,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 100,
            "instruction": (
                "Create an Unknown Actor entry (persistent threat). "
                "Return TWO state_changes: "
                "1) ua_create \u2014 "
                f"ua_id (use '{next_code}'), zone, "
                "description (1-2 sentences of observable agency), "
                "status ('ACTIVE'). "
                "2) discovery_create OR thread_create \u2014 "
                "the UA MUST be anchored in a discovery, unresolved thread, "
                "or clock (per UA.CREATE ANCHOR rule). "
                "UA should imply agency (surveillance, pursuit, sabotage, enforcement) "
                "without revealing stable identity."
            ),
        },
    )

def build_zone_expansion(state, parent_zone: str, cp_count: int) -> CreativeRequest:
    """
    ZONE_EXPANSION — Create new destination zones via CP expansion.
    Triggered by ZONE-FORGE step 3.0 when crossing_points count <= 1.
    """
    zone_obj = state.zones.get(parent_zone)
    zone_ctx = {}
    existing_cps = []
    if zone_obj:
        zone_ctx = {
            "description": zone_obj.description,
            "threat_level": zone_obj.threat_level,
            "intensity": zone_obj.intensity,
            "controlling_faction": zone_obj.controlling_faction,
        }
        existing_cps = zone_obj.crossing_points or []

    lore = get_lore_index()
    lore_dict = {}
    zone_lore = lore.get_zone_lore(parent_zone)
    if zone_lore:
        lore_dict["zone_atmosphere"] = zone_lore

    return CreativeRequest(
        id=_next_id(),
        type="ZONE_EXPANSION",
        context={
            "parent_zone": parent_zone,
            "parent_zone_data": zone_ctx,
            "existing_crossing_points": existing_cps,
            "cp_count": cp_count,
            "existing_zones": list(state.zones.keys()),
            "session_id": state.session_id,
            "season": state.season,
            "lore": lore_dict,
        },
        constraints={
            **DEFAULT_CONSTRAINTS,
            "max_words": 300,
            "instruction": (
                f"Create {cp_count} new destination zone(s) reachable from {parent_zone}. "
                "For EACH new zone, return TWO state_changes: "
                "1) zone_create \u2014 name, intensity, description, threat_level, "
                "crossing_points (list with at least a CP back to parent). "
                f"2) zone_update \u2014 name='{parent_zone}', add_crossing_points "
                "(list of new CPs pointing to the new zone). "
                "CP format: {{\"name\": \"<landmark>\", \"destination\": \"<zone>\"}}. "
                "No narration \u2014 save-ready inserts only."
            ),
        },
    )


# ─────────────────────────────────────────────────────
# CREATIVE QUEUE
# ─────────────────────────────────────────────────────

class CreativeQueue:
    """Manages pending creative requests and received responses."""

    def __init__(self):
        self.pending: list[CreativeRequest] = []
        self.completed: list[CreativeResponse] = []
        self.call_count: int = 0  # Claude calls this session (DG-25)

    def enqueue(self, req: CreativeRequest):
        """Add a creative request to the pending queue."""
        self.pending.append(req)

    def enqueue_many(self, requests: list[CreativeRequest]):
        """Add multiple requests to the pending queue."""
        self.pending.extend(requests)

    def is_empty(self) -> bool:
        """True if no pending requests."""
        return len(self.pending) == 0

    def pending_count(self) -> int:
        return len(self.pending)

    def pending_types(self) -> list[str]:
        """Return list of pending request types."""
        return [r.type for r in self.pending]

    def get_pending_batch(self) -> dict:
        """
        Serialize all pending requests into a batch dict for the LLM.
        This is the payload that goes to Claude (via MCP, API, or clipboard).
        """
        return {
            "batch_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "request_count": len(self.pending),
            "requests": [r.to_dict() for r in self.pending],
        }

    def get_pending_batch_json(self) -> str:
        """JSON string of the pending batch."""
        return json.dumps(self.get_pending_batch(), indent=2, ensure_ascii=False)

    def submit_response(self, response_json: str) -> list[CreativeResponse]:
        """
        Parse and validate a batch response from the LLM.
        Returns list of validated CreativeResponse objects.
        Raises ValueError on invalid input.
        """
        data = _parse_response_json(response_json)
        responses = []

        for resp_data in data.get("responses", []):
            resp = CreativeResponse.from_dict(resp_data)

            # Validate: response id must match a pending request
            matching = [r for r in self.pending if r.id == resp.id]
            if not matching:
                # Try to match by index if ids don't align
                pass  # Permissive — accept anyway

            # Validate state changes have valid types
            for sc in resp.state_changes:
                sc_type = sc.get("type", "")
                if sc_type and sc_type not in STATE_CHANGE_TYPES:
                    sc["_warning"] = f"Unknown state_change type: {sc_type}"

            responses.append(resp)

        self.completed = responses
        self.call_count += 1
        return responses

    def apply_responses(self, state) -> list[dict]:
        """
        Apply all completed responses to game state.
        Returns list of log entries describing what was applied.
        Ported from claude_integration.apply_response.
        """
        log_entries = []

        for resp in self.completed:
            # Log the creative content
            log_entries.append({
                "id": resp.id,
                "type": resp.type,
                "content_preview": (resp.content[:100] + "...")
                                   if len(resp.content) > 100 else resp.content,
            })

            # UA anchor validation (UA-FORGE §2.1 HARD):
            # ua_create must be paired with discovery_create, thread_create,
            # or clock_create in the same response
            sc_types = {sc.get("type", "") for sc in resp.state_changes}
            if "ua_create" in sc_types:
                anchor_types = {"discovery_create", "thread_create", "clock_create"}
                if not sc_types & anchor_types:
                    log_entries.append({
                        "id": resp.id,
                        "type": resp.type,
                        "warning": "UA anchor violation: ua_create without "
                                   "discovery_create/thread_create/clock_create. "
                                   "Skipping ua_create per UA-FORGE §2.1 HARD.",
                    })
                    resp.state_changes = [
                        sc for sc in resp.state_changes
                        if sc.get("type") != "ua_create"
                    ]

            # Apply state changes
            had_clock_advance = False
            for change in resp.state_changes:
                entry = _apply_state_change(state, resp.id, change)
                if entry:
                    log_entries.append(entry)
                    if entry.get("applied") == "clock_advance":
                        had_clock_advance = True


        return log_entries

    def clear(self):
        """Clear both pending and completed queues."""
        self.pending = []
        self.completed = []

    def clear_pending(self):
        """Clear pending queue after responses received."""
        self.pending = []


# ─────────────────────────────────────────────────────
# RESPONSE PARSING
# ─────────────────────────────────────────────────────

def _parse_response_json(text: str) -> dict:
    """
    Parse LLM response text into dict.
    Handles markdown code fences, extra whitespace, wrapped JSON.
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


def _apply_state_change(state, req_id: str, change: dict) -> Optional[dict]:
    """Apply a single state change to game state. Returns log entry."""
    change_type = change.get("type", "")

    if change_type == "clock_advance":
        clock = state.get_clock(change.get("clock", ""))
        if clock and clock.can_advance():
            result = clock.advance(
                reason=f"Creative ({req_id}): {change.get('reason', '')}",
                date=state.in_game_date,
                session=state.session_id,
            )
            return {"applied": "clock_advance", "result": result}
        elif not clock:
            return {"applied": "clock_advance",
                    "error": f"Clock not found: {change.get('clock', '')}"}

    elif change_type == "clock_reduce":
        clock = state.get_clock(change.get("clock", ""))
        if clock:
            result = clock.reduce(
                reason=f"Creative ({req_id}): {change.get('reason', '')}",
            )
            return {"applied": "clock_reduce", "result": result}

    elif change_type == "fact":
        fact_text = change.get("text", "")
        if fact_text:
            state.add_fact(fact_text)
            return {"applied": "fact", "text": fact_text}

    elif change_type == "npc_update":
        npc_name = change.get("name", "") or change.get("npc", "")
        npc = state.get_npc(npc_name)
        if npc:
            for field_name in ("zone", "status", "next_action", "objective"):
                if field_name in change:
                    setattr(npc, field_name, change[field_name])
            return {"applied": "npc_update", "npc": npc_name}

    elif change_type == "session_meta":
        sid = str(state.session_id)
        meta = state.session_meta.get(sid, {})
        for key in ("tone_shift", "pacing", "next_session_pressure"):
            if key in change:
                meta[key] = change[key]
        state.session_meta[sid] = meta
        return {"applied": "session_meta", "session": sid}

    # ── DG-17 Forge state changes ──

    elif change_type == "npc_create":
        from models import NPC
        name = change.get("name", "")
        if not name:
            return {"applied": "npc_create", "error": "Missing name"}
        if name in state.npcs:
            return {"applied": "npc_create", "error": f"NPC '{name}' already exists"}
        zone_name = change.get("zone", "")
        if zone_name and zone_name not in state.zones:
            return {"applied": "npc_create",
                    "error": f"Zone '{zone_name}' not found"}
        npc = NPC(
            name=name,
            zone=zone_name,
            role=change.get("role", ""),
            trait=change.get("trait", ""),
            appearance=change.get("appearance", ""),
            faction=change.get("faction", ""),
            objective=change.get("objective", ""),
            knowledge=change.get("knowledge", ""),
            negative_knowledge=change.get("negative_knowledge", ""),
            next_action=change.get("next_action", ""),
            class_level=change.get("class_level", ""),
            bx_ac=change.get("bx_ac", 0),
            bx_hd=change.get("bx_hd", 0),
            bx_hp=change.get("bx_hp", 0),
            bx_hp_max=change.get("bx_hp_max", 0),
            bx_at=change.get("bx_at", 0),
            bx_dmg=change.get("bx_dmg", ""),
            bx_ml=change.get("bx_ml", 0),
            visibility=change.get("visibility", "public"),
            created_session=state.session_id,
            last_updated_session=state.session_id,
        )
        state.add_npc(npc)
        return {"applied": "npc_create", "npc": name, "zone": zone_name}

    elif change_type == "el_create":
        from models import EncounterList, EncounterEntry
        zone_name = change.get("zone", "")
        if not zone_name or zone_name not in state.zones:
            return {"applied": "el_create",
                    "error": f"Zone '{zone_name}' not found"}
        raw_entries = change.get("entries", [])
        if not raw_entries:
            return {"applied": "el_create", "error": "No entries provided"}
        entries = []
        for e in raw_entries:
            entries.append(EncounterEntry(
                range=e.get("range", "1"),
                prompt=e.get("prompt", ""),
                ua_cue=e.get("ua_cue", False),
                bx_plug=e.get("bx_plug", {}),
            ))
        el = EncounterList(
            zone=zone_name,
            randomizer=change.get("randomizer", "1d6"),
            fallback_priority=change.get("fallback_priority", 1),
            adjacency_notes=change.get("adjacency_notes", ""),
            entries=entries,
        )
        state.encounter_lists[zone_name] = el
        return {"applied": "el_create", "zone": zone_name,
                "entry_count": len(entries)}

    elif change_type == "faction_create":
        from models import Faction
        name = change.get("name", "")
        if not name:
            return {"applied": "faction_create", "error": "Missing name"}
        if name in state.factions:
            return {"applied": "faction_create",
                    "error": f"Faction '{name}' already exists"}
        fac = Faction(
            name=name,
            status=change.get("status", "active"),
            trend=change.get("trend", ""),
            disposition=change.get("disposition", "unknown"),
            last_action=change.get("last_action", ""),
            notes=change.get("notes", ""),
            created_session=state.session_id,
            last_updated_session=state.session_id,
        )
        state.add_faction(fac)
        return {"applied": "faction_create", "faction": name}

    elif change_type == "faction_update":
        name = change.get("name", "")
        fac = state.get_faction(name)
        if not fac:
            return {"applied": "faction_update",
                    "error": f"Faction '{name}' not found"}
        for field_name in ("status", "trend", "disposition", "last_action", "notes"):
            if field_name in change:
                setattr(fac, field_name, change[field_name])
        fac.last_updated_session = state.session_id
        if change.get("history_entry"):
            fac.history.append({
                "session": state.session_id,
                "date": state.in_game_date,
                "event": change["history_entry"],
            })
        return {"applied": "faction_update", "faction": name}

    elif change_type == "clock_create":
        from models import Clock
        name = change.get("name", "")
        if not name:
            return {"applied": "clock_create", "error": "Missing name"}
        if name in state.clocks:
            return {"applied": "clock_create",
                    "error": f"Clock '{name}' already exists"}
        max_prog = change.get("max_progress", 4)
        if not isinstance(max_prog, int) or max_prog < 1 or max_prog > 20:
            return {"applied": "clock_create",
                    "error": f"Invalid max_progress: {max_prog}"}
        # CL-FORGE §3 HARD: Clock owner must exist in authoritative state
        clock_owner = change.get("owner", "")
        if clock_owner and clock_owner.lower() != "environment":
            owner_exists = (
                clock_owner in state.npcs
                or clock_owner in state.factions
                or any(u.get("id") == clock_owner or u.get("ua_id") == clock_owner
                       for u in state.ua_log)
            )
            if not owner_exists:
                return {"applied": "clock_create",
                        "error": f"HARD STOP: Clock owner '{clock_owner}' "
                                 f"not found in NPCs, factions, or UA_LOG"}
        clock = Clock(
            name=name,
            owner=change.get("owner", ""),
            progress=change.get("progress", 0),
            max_progress=max_prog,
            advance_bullets=change.get("advance_bullets", []),
            halt_conditions=change.get("halt_conditions", []),
            reduce_conditions=change.get("reduce_conditions", []),
            trigger_on_completion=change.get("trigger_on_completion", ""),
            is_cadence=change.get("is_cadence", False),
            cadence_bullet=change.get("cadence_bullet", ""),
            created_session=state.session_id,
        )
        state.add_clock(clock)
        return {"applied": "clock_create", "clock": name, "max": max_prog}

    elif change_type == "companion_create":
        from models import CompanionDetail
        npc_name = change.get("npc_name", "")
        if not npc_name:
            return {"applied": "companion_create", "error": "Missing npc_name"}
        npc = state.get_npc(npc_name)
        if npc:
            npc.is_companion = True
            npc.with_pc = True
        comp = CompanionDetail(
            npc_name=npc_name,
            motivation_shift=change.get("motivation_shift", ""),
            loyalty_change=change.get("loyalty_change", ""),
            trust_in_pc=change.get("trust_in_pc", "unknown"),
            affection_levels=change.get("affection_levels", {}),
            stress_or_fatigue=change.get("stress_or_fatigue", "unknown"),
            grievances=change.get("grievances", ""),
            agency_notes=change.get("agency_notes", ""),
            future_flashpoints=change.get("future_flashpoints", ""),
        )
        state.companions[npc_name] = comp
        return {"applied": "companion_create", "npc": npc_name}

    elif change_type == "pe_create":
        from models import Engine
        eng_name = change.get("engine_name", "")
        if not eng_name:
            return {"applied": "pe_create", "error": "Missing engine_name"}
        if eng_name in state.engines:
            return {"applied": "pe_create",
                    "error": f"Engine '{eng_name}' already exists (registry immutability)"}
        # Validate registry_target (PE-FORGE spec)
        registry_target = change.get("registry_target", "NSV_DELTA_REGISTRY")
        valid_registries = {"CSEM", "SSM_1A", "NSV_DELTA_REGISTRY"}
        if registry_target not in valid_registries:
            registry_target = "NSV_DELTA_REGISTRY"
        engine = Engine(
            name=eng_name,
            version=change.get("version", "1.0"),
            status=change.get("status", "active"),
            authority_tier=change.get("authority_tier", "ZONE-LOCAL"),
            registry_target=registry_target,
            zone_scope=change.get("zone_scope", ""),
            state_scope=change.get("state_scope", ""),
            cadence=bool(change.get("cadence", False)),
            trigger_event=change.get("trigger_event", ""),
            hard_gates=change.get("hard_gates", []),
            resolution_method=change.get("resolution_method", ""),
            randomizer=change.get("randomizer", ""),
            linked_clocks=change.get("linked_clocks", []),
            run_cap_per_day=int(change.get("run_cap_per_day", 1)),
        )
        state.engines[eng_name] = engine
        return {"applied": "pe_create", "engine": eng_name,
                "zone_scope": engine.zone_scope}

    elif change_type == "discovery_create":
        from models import Discovery
        disc_id = change.get("id", "")
        if not disc_id:
            disc_id = f"DISC-{state.session_id}-{len(state.discoveries) + 1:02d}"
        disc = Discovery(
            id=disc_id,
            zone=change.get("zone", ""),
            ua_code=change.get("ua_code", ""),
            reliability=change.get("reliability", change.get("certainty", "uncertain")),
            visibility=change.get("visibility", "public"),
            source=change.get("source", ""),
            info=change.get("info", change.get("description", "")),
            session_discovered=state.session_id,
        )
        state.discoveries.append(disc)
        return {"applied": "discovery_create", "id": disc_id,
                "zone": disc.zone}

    elif change_type == "thread_create":
        from models import UnresolvedThread
        thread_id = change.get("id", "")
        if not thread_id:
            thread_id = f"THR-{state.session_id}-{len(state.unresolved_threads) + 1:02d}"
        thread = UnresolvedThread(
            id=thread_id,
            zone=change.get("zone", ""),
            description=change.get("description", ""),
            session_created=state.session_id,
        )
        state.unresolved_threads.append(thread)
        return {"applied": "thread_create", "id": thread_id,
                "zone": thread.zone}

    elif change_type == "ua_create":
        ua_id = change.get("ua_id", "")
        if not ua_id:
            return {"applied": "ua_create", "error": "Missing ua_id"}
        for existing_ua in state.ua_log:
            if existing_ua.get("id") == ua_id:
                return {"applied": "ua_create",
                        "error": f"UA '{ua_id}' already exists"}
        ua_entry = {
            "id": ua_id,
            "zone": change.get("zone", ""),
            "description": change.get("description", ""),
            "status": change.get("status", "ACTIVE"),
            "touched": "no",
            "promotion": "no",
        }
        state.ua_log.append(ua_entry)
        return {"applied": "ua_create", "ua_id": ua_id,
                "zone": change.get("zone", "")}

    elif change_type == "zone_create":
        from models import Zone
        name = change.get("name", "")
        if not name:
            return {"applied": "zone_create", "error": "Missing name"}
        if name in state.zones:
            return {"applied": "zone_create",
                    "error": f"Zone '{name}' already exists"}
        zone = Zone(
            name=name,
            intensity=change.get("intensity", "medium"),
            controlling_faction=change.get("controlling_faction", ""),
            description=change.get("description", ""),
            crossing_points=change.get("crossing_points", []),
            threat_level=change.get("threat_level", ""),
            situation_summary=change.get("situation_summary", ""),
            no_faction=change.get("no_faction", False),
            encounter_threshold=change.get("encounter_threshold", 6),
        )
        state.zones[name] = zone
        return {"applied": "zone_create", "zone": name}

    elif change_type == "zone_update":
        name = change.get("name", "")
        zone = state.zones.get(name)
        if not zone:
            return {"applied": "zone_update",
                    "error": f"Zone '{name}' not found"}
        for field_name in ("controlling_faction", "description",
                           "threat_level", "situation_summary",
                           "intensity", "no_faction"):
            if field_name in change:
                setattr(zone, field_name, change[field_name])
        # Merge crossing points (append new ones, don't overwrite)
        new_cps = change.get("add_crossing_points", [])
        for cp in new_cps:
            if cp not in zone.crossing_points:
                zone.crossing_points.append(cp)
        return {"applied": "zone_update", "zone": name}

    return None
