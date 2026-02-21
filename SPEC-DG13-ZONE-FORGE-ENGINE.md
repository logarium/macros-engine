# DG-13: ZONE-FORGE Engine Automation

## Problem
ZONE-FORGE conditional logic is currently executed by the LLM, not the engine. The LLM repeatedly fails to check existing state before queuing creative requests — creating duplicate EL-DEFs, ignoring NPC counts, applying wrong CAN-FORGE mode caps. This produces invalid pending requests that corrupt game state.

## Solution
Move ALL ZONE-FORGE conditional checks into the Python engine. The engine determines WHAT needs creating. Claude only provides creative CONTENT for confirmed gaps.

## Implementation

### New function: `run_zone_forge(state, zone_name) -> list[dict]`

Called by `run_tp_days` on zone entry, or manually via a new MCP tool `zone_forge`.

#### Step 1: Validate Zone
```
if zone_name not in state.zones:
    return [{"error": f"Zone '{zone_name}' not found in zone registry"}]
zone = state.zones[zone_name]
```

#### Step 2: PC Zone Binding
```
state.pc_zone = zone_name
# Update all with_pc NPCs to this zone
for npc in state.npcs.values():
    if npc.with_pc:
        npc.zone = zone_name
```

#### Step 3: Controlling Faction Check
```
needs_faction = False
if not zone.controlling_faction:
    # Check NSV-ZONES data (loaded at startup from save)
    if not zone.get("no_faction", False):
        needs_faction = True
```

#### Step 4: NPC Count Check
```
npc_count = sum(1 for npc in state.npcs.values() if npc.zone == zone_name)
needs_npcs = npc_count < 3
```

#### Step 5: EL-DEF Existence Check (THIS IS THE CRITICAL FIX)
```
needs_el = zone_name not in state.encounter_lists
# That's it. If the zone has an encounter_lists entry, skip EL-FORGE.
# The encounter_lists dict is populated from both NSV-ENGINES (at load)
# and any runtime-created ELs.
```

#### Step 6: Clock/PE Check
```
# Check if any active clock has this zone in its owner or zone field
zone_clocks = [c for c in state.clocks.values() 
               if c.status == "active" and zone_name.lower() in (c.owner or "").lower()]
# Agent chooses CL-FORGE or PE-FORGE — always queue one
needs_clock_or_pe = True
```

#### Step 7: UA Check (determines CAN-FORGE mode)
```
zone_uas = [ua for ua in state.ua_log if ua.zone == zone_name and ua.status == "ACTIVE"]
needs_can_forge = len(zone_uas) == 0
```

#### Step 8: CP Expansion Check
```
cp_count = len(zone.get("crossing_points", []))
needs_cp_expansion = cp_count <= 1
```

### Build Creative Request Queue

Based on the checks above, the engine builds ONLY the requests that are actually needed:

```python
requests = []

if needs_faction:
    requests.append({
        "type": "FAC_FORGE",
        "zone": zone_name,
        "caller": "ZONE-FORGE",
        "constraints": {
            "mode": "ZONE-FORGE",  # NOT full mode
            "visibility": "secret",
            "pc_targeting": "forbidden"
        }
    })

if needs_npcs:
    requests.append({
        "type": "NPC_FORGE",
        "zone": zone_name,
        "caller": "ZONE-FORGE",
        "existing_npc_count": npc_count,
        "max_to_create": 3 - npc_count
    })

# ALWAYS queue CL-FORGE (§2.5 — agent chooses clock or PE)
requests.append({
    "type": "CL_FORGE",
    "zone": zone_name,
    "caller": "ZONE-FORGE",
    "owner": "TBD",  # LLM decides owner from existing entities
    "constraints": {
        "owner_must_exist": True,
        "zone_entity_clocks": [c.name for c in zone_clocks]
    }
})

if needs_el:
    requests.append({
        "type": "EL_FORGE",
        "zone": zone_name,
        "caller": "ZONE-FORGE"
    })

if needs_can_forge:
    requests.append({
        "type": "CAN_FORGE",
        "zone": zone_name,
        "caller": "ZONE-FORGE",
        "constraints": {
            "mode": "ZONE-FORGE",       # HARD: NOT full mode
            "caps": {
                "new_ua_codes": 1,
                "new_clocks": 1,         # owner = new UA or environment
                "new_discoveries": 1,
                "new_factions": 0,       # ZERO — ZONE-FORGE mode
                "new_npcs": 0,           # ZERO
                "new_el_def": 0,         # ZERO
                "new_pe_def": 0          # ZERO
            },
            "visibility": "secret",
            "pc_targeting": "forbidden"
        }
    })

if needs_cp_expansion:
    # Engine rolls 1d3 for new CP count
    # Each new CP triggers a mini zone-create request
    requests.append({
        "type": "CP_EXPANSION",
        "zone": zone_name,
        "new_cp_count": roll("1d3")
    })
```

### Key Invariants (HARD)

1. **EL-DEF check is a dict lookup, not an LLM judgment.** If `zone_name in state.encounter_lists` → no EL-FORGE. Period.

2. **CAN-FORGE mode is set by the engine, not the LLM.** When caller is ZONE-FORGE, mode is ALWAYS "ZONE-FORGE" with §9 caps. The LLM cannot override this to full mode.

3. **NPC count is arithmetic, not estimation.** `sum(1 for npc in state.npcs.values() if npc.zone == zone_name)` — if ≥3, no NPC-FORGE.

4. **The engine passes caps as structured data in the request.** The LLM receives `"new_factions": 0` and cannot decide to create a faction anyway.

### New MCP Tool

```python
@server.tool()
def zone_forge(zone_name: str = "") -> str:
    """
    Run ZONE-FORGE checks for a zone. Determines what content
    gaps exist and queues only necessary creative requests.
    If zone_name is empty, uses current PC zone.
    Returns a summary of what was found and what was queued.
    """
    state = _get_state()
    if not zone_name:
        zone_name = state.pc_zone
    
    results = run_zone_forge(state, zone_name)
    
    # Queue any creative requests
    for req in results:
        if req.get("type") in CREATIVE_TYPES:
            _pending_llm_requests.append(req)
    
    _auto_save(state)
    return format_zone_forge_summary(results)
```

### Integration with run_tp_days

Currently `run_tp_days` does NOT call zone_forge (it only runs T&P mechanics). Zone forge should be triggered:
- On TRAVEL arrival (after T&P completes and zone changes)
- On SSM if zone has never been forged
- On explicit `zone_forge` tool call

Do NOT auto-trigger zone_forge inside run_tp_days. Travel and SSM are the correct triggers.

## Testing Checklist

- [ ] Load save with Vornost as PC zone
- [ ] Run `zone_forge("Vornost")`
- [ ] Verify: NO EL-FORGE request (Vornost EL exists)
- [ ] Verify: NO NPC-FORGE request (8 NPCs in Vornost)
- [ ] Verify: CAN-FORGE request has mode="ZONE-FORGE" and caps.new_el_def=0
- [ ] Verify: CL-FORGE request includes existing zone clocks for dedup
- [ ] Load save with a brand-new zone (no EL, no NPCs, no UA)
- [ ] Run `zone_forge("NewZone")`
- [ ] Verify: EL-FORGE IS queued
- [ ] Verify: NPC-FORGE IS queued
- [ ] Verify: CAN-FORGE has ZONE-FORGE caps, not full mode caps
