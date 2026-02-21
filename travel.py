"""
MACROS Engine v4.0 — Travel Automation (DG-15)
Reads CPs from zone data, validates destinations, calculates time increments.
Player selects destination via UI buttons. Engine handles everything else.

CP tag mapping:
  None / unmarked  -> 1 day standard travel
  "slow"           -> 2 days (rough terrain, longer route)
  "eventful"       -> 1 day + forced encounter check
"""

from models import GameState


# ─────────────────────────────────────────────────────
# CP ROUTING
# ─────────────────────────────────────────────────────

def get_crossing_points(state: GameState) -> list[dict]:
    """
    Return available CPs from the PC's current zone.
    Each CP becomes a clickable button in the UI.
    """
    zone = state.zones.get(state.pc_zone)
    if not zone:
        return []

    cps = []
    for cp in zone.crossing_points:
        destination = cp.get("to", "")
        if not destination:
            continue

        tag = cp.get("tag")
        time_days = calculate_travel_time(tag)

        # Build display label
        name = cp.get("name", destination)
        label = format_cp_label(name, destination, tag, time_days)

        cps.append({
            "destination": destination,
            "name": name,
            "tag": tag,
            "time_days": time_days,
            "label": label,
        })

    return cps


def format_cp_label(name: str, destination: str, tag, time_days: int) -> str:
    """Format a CP for display as a button label."""
    parts = [f"{name} -> {destination}"]
    if tag == "slow":
        parts.append(f"({time_days}d, slow)")
    elif tag == "eventful":
        parts.append(f"({time_days}d, eventful)")
    else:
        parts.append(f"({time_days}d)")
    return " ".join(parts)


def calculate_travel_time(tag) -> int:
    """
    CP tag -> travel days.
    None/unmarked = 1 day, slow = 2 days, eventful = 1 day.
    """
    if tag == "slow":
        return 2
    return 1


# ─────────────────────────────────────────────────────
# TRAVEL EXECUTION
# ─────────────────────────────────────────────────────

def validate_travel(state: GameState, destination: str) -> dict:
    """
    Check if travel to destination is valid from the current zone.
    Returns {valid: bool, cp: dict or None, error: str or None}.
    """
    zone = state.zones.get(state.pc_zone)
    if not zone:
        return {
            "valid": False,
            "cp": None,
            "error": f"Current zone '{state.pc_zone}' not found in state",
        }

    for cp in zone.crossing_points:
        if cp.get("to", "").lower() == destination.lower():
            return {"valid": True, "cp": cp, "error": None}

    available = [cp.get("to", "?") for cp in zone.crossing_points]
    return {
        "valid": False,
        "cp": None,
        "error": (f"'{destination}' is not reachable from {state.pc_zone}. "
                  f"Available: {', '.join(available)}"),
    }


def execute_travel(state: GameState, destination: str) -> dict:
    """
    Execute travel from current zone to destination.
    Updates PC zone, logs the transition.
    Returns travel result with days_traveled, trigger info, etc.

    Does NOT run T&P — the game loop handles that after this returns.
    """
    validation = validate_travel(state, destination)
    if not validation["valid"]:
        return {"success": False, "error": validation["error"]}

    cp = validation["cp"]
    old_zone = state.pc_zone
    tag = cp.get("tag")
    time_days = calculate_travel_time(tag)

    # Update state
    state.pc_zone = destination
    state.add_fact(f"Traveled from {old_zone} to {destination} via {cp.get('name', '?')}")

    # Log the zone change
    state.log({
        "type": "TRAVEL",
        "detail": f"{old_zone} -> {destination} via {cp.get('name', '?')} ({time_days}d)",
        "old_zone": old_zone,
        "new_zone": destination,
        "cp_name": cp.get("name", ""),
        "cp_tag": tag,
        "days": time_days,
    })

    result = {
        "success": True,
        "old_zone": old_zone,
        "new_zone": destination,
        "cp_name": cp.get("name", ""),
        "cp_tag": tag,
        "days_traveled": time_days,
        "is_eventful": tag == "eventful",
    }

    return result
