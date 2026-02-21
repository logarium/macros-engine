"""
MACROS Engine v4.0 — ZONE-FORGE (DG-13)
Full 7-step cascade per authoritative spec (docs/ZONE-FORGE.txt).
Triggered on zone arrival (spawn/travel/session start).

Cascade:
  1.0  Validate zone (roll starting zone if blank)
  1.3  With_PC cohesion
  2.0  Controlling faction (FAC-FORGE if missing)
  2.4  NPC presence (NPC-FORGE if <= 3)
  2.5  Clocks/PEs (CL-FORGE — always queued)
  2.6  EL-DEF (EL-FORGE if missing)
  2.7  UA check (CAN-FORGE if no active UA)
  3.0  CP expansion (ZONE_EXPANSION if <= 1 CP)
"""

import random
from creative_bridge import (
    build_npc_forge, build_el_forge, build_fac_forge,
    build_cl_forge, build_pe_forge, build_can_forge, build_zone_expansion,
)

# NPC-FORGE fires when active NPC count in zone is 3 or less
NPC_FORGE_THRESHOLD = 3


# Starting zones (d6 table)
STARTING_ZONES = [
    "Eastern Scarps",
    "Western Scarps",
    "Riverlands",
    "Seawatch Ramparts",
    "Grey Plains",
    "Southern Scarps",
]


def _roll_starting_zone(state) -> str:
    """Roll d6 for starting zone from the fixed starting zone table."""
    idx = random.randint(0, 5)
    return STARTING_ZONES[idx]


def _with_pc_cohesion(state, zone_name: str) -> list:
    """1.3 — Move all with_pc NPCs to the PC's zone. Returns list of move descriptions."""
    moved = []
    for npc in state.npcs.values():
        if npc.with_pc and npc.zone != zone_name:
            old_zone = npc.zone or "(none)"
            npc.zone = zone_name
            moved.append(f"{npc.name}: {old_zone} -> {zone_name}")
    return moved


def run_zone_forge(state) -> dict:
    """
    ZONE-FORGE cascade (DG-13) — full 7-step implementation.

    Returns dict with:
      status, zone, controlling_faction, npc_count,
      with_pc_moved, gaps, forge_requests
    """
    zone_name = state.pc_zone
    zone = state.zones.get(zone_name) if zone_name else None

    # ── 1.0 Validate zone (roll starting zone if blank) ──
    if not zone and not zone_name:
        zone_name = _roll_starting_zone(state)
        if zone_name:
            state.pc_zone = zone_name
            zone = state.zones.get(zone_name)

    if not zone:
        return {
            "status": "skip",
            "reason": f"Zone '{zone_name}' not in zone data",
            "forge_requests": [],
        }

    # ── 1.3 With_PC cohesion ──
    with_pc_moved = _with_pc_cohesion(state, zone_name)

    # Count active NPCs in this zone
    npcs_in_zone = [
        n for n in state.npcs.values()
        if getattr(n, "zone", "") == zone_name
        and getattr(n, "status", "") == "active"
    ]
    npc_count = len(npcs_in_zone)

    gaps = []
    forge_requests = []

    # ── 2.0 Controlling faction resolution ──
    controlling_fac = getattr(zone, "controlling_faction", "")
    no_faction = getattr(zone, "no_faction", False)
    if not controlling_fac and not no_faction:
        gaps.append("No controlling faction — FAC-FORGE")
        req = build_fac_forge(state, zone_hint=zone_name)
        forge_requests.append(req)

    # ── 2.4 NPC presence ──
    if npc_count <= NPC_FORGE_THRESHOLD:
        npc_deficit = max(1, NPC_FORGE_THRESHOLD + 1 - npc_count)
        gaps.append(
            f"NPC deficit: {npc_count} active "
            f"(threshold {NPC_FORGE_THRESHOLD}, forging {npc_deficit})"
        )
        faction_hint = controlling_fac or ""
        for _ in range(npc_deficit):
            req = build_npc_forge(
                state,
                zone=zone_name,
                faction_hint=faction_hint,
            )
            forge_requests.append(req)

    # ── 2.5 Clocks/PEs — agent chooses CL-FORGE or PE-FORGE (spec §2.5) ──
    zone_npc_names = {n.name for n in npcs_in_zone}
    zone_relevant_owners = zone_npc_names | ({controlling_fac} if controlling_fac else set())
    zone_entity_clocks = [
        c.name for c in state.clocks.values()
        if c.status == "active" and c.owner in zone_relevant_owners
    ]
    # Always queue CL-FORGE
    gaps.append("CL-FORGE (§2.5 — always queued)")
    req = build_cl_forge(
        state,
        owner=controlling_fac or zone_name,
        trigger_context=f"zone-forge: existing zone clocks={zone_entity_clocks}",
    )
    forge_requests.append(req)
    # Queue PE-FORGE if no active zone-local engine for this zone
    zone_engines = [
        e for e in state.engines.values()
        if e.status == "active" and e.zone_scope == zone_name
    ]
    if not zone_engines:
        gaps.append("No zone-local PE — PE-FORGE (§2.5)")
        req = build_pe_forge(
            state,
            engine_name=f"{zone_name} Zone Engine",
            zone_scope=zone_name,
            trigger_event="zone-forge",
        )
        forge_requests.append(req)

    # ── 2.6 EL-DEF ──
    el = state.encounter_lists.get(zone_name)
    if not el:
        gaps.append("No EL-DEF for zone — EL-FORGE")
        req = build_el_forge(state, zone=zone_name)
        forge_requests.append(req)

    # ── 2.7 UA / CAN-FORGE ──
    active_uas = [
        u for u in state.ua_log
        if u.get("zone") == zone_name and u.get("status") == "ACTIVE"
    ]
    if not active_uas:
        gaps.append("No active UA in zone — CAN-FORGE")
        req = build_can_forge(state, zone=zone_name, trigger="zone-forge",
                              mode="ZONE-FORGE")
        forge_requests.append(req)

    # ── 3.0 CP expansion ──
    crossing_points = getattr(zone, "crossing_points", []) or []
    if len(crossing_points) <= 1:
        cp_count = random.randint(1, 3)
        gaps.append(
            f"CP count {len(crossing_points)} <= 1 — "
            f"expanding with {cp_count} new zone(s)"
        )
        req = build_zone_expansion(
            state,
            parent_zone=zone_name,
            cp_count=cp_count,
        )
        forge_requests.append(req)

    return {
        "status": "ok",
        "zone": zone_name,
        "controlling_faction": getattr(zone, "controlling_faction", ""),
        "npc_count": npc_count,
        "with_pc_moved": with_pc_moved,
        "gaps": gaps,
        "forge_requests": forge_requests,
    }
