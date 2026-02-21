"""
MACROS Engine v1.0 — Dice Roller
Full audit trail on every roll. No hidden rolls per BX-PLUG §0.2.
"""

import random
import re


def roll_dice(expression: str, label: str = "") -> dict:
    """
    Roll a dice expression like '2d6', '1d8+2', '2d6+3'.
    Returns dict with full audit trail.
    """
    expr = expression.strip().lower()

    # Parse NdM+K
    match = re.match(r'(\d+)d(\d+)([+-]\d+)?', expr)
    if not match:
        return {"error": f"Invalid dice expression: {expression}"}

    n = int(match.group(1))
    m = int(match.group(2))
    k = int(match.group(3)) if match.group(3) else 0

    individual = [random.randint(1, m) for _ in range(n)]
    total = sum(individual) + k

    result = {
        "expression": expression,
        "dice": individual,
        "modifier": k,
        "total": total,
        "label": label,
    }

    return result


def roll_d6(label: str = "") -> dict:
    """Roll 1d6 with audit."""
    return roll_dice("1d6", label)


def roll_2d6(label: str = "") -> dict:
    """Roll 2d6 with audit."""
    return roll_dice("2d6", label)


def roll_d20(label: str = "") -> dict:
    """Roll 1d20 with audit."""
    return roll_dice("1d20", label)


def intensity_gate_check(intensity: str, roll_result: int) -> bool:
    """
    Check if a 1d6 roll passes the intensity gate.
    Per T&P §4.2 / §6.1:
      low: 1-2 pass
      medium: 1-3 pass
      high: 1-4 pass
      extreme: auto-pass
    """
    thresholds = {
        "low": 2,
        "medium": 3,
        "high": 4,
        "extreme": 6,
    }
    threshold = thresholds.get(intensity.lower(), 3)
    return roll_result <= threshold


def vp_outcome_band(roll: int) -> dict:
    """
    Map 2d6 VP roll to outcome band per VP v3.0 Resolution_Method.
    Returns band name and clock effects.
    """
    if roll <= 4:
        return {
            "band": "2-4: Clear failure",
            "description": "Threat missed or misidentified",
            "clock_effects": [
                {"clock": "Selde Marr", "action": "advance"},
                {"clock": "Arvek Morn", "action": "advance"},
            ]
        }
    elif roll <= 7:
        return {
            "band": "5-7: Ambiguous contact",
            "description": "Doctrine stress",
            "clock_effects": [
                {"clock": "Henric Bale", "action": "advance"},
            ]
        }
    elif roll <= 9:
        return {
            "band": "8-9: Correct restraint",
            "description": "Good logs, no escalation",
            "clock_effects": []
        }
    elif roll <= 11:
        return {
            "band": "10-11: Correct identification",
            "description": "No engagement needed",
            "clock_effects": [
                {"clock": "Selde Marr", "action": "reduce"},
                {"clock": "Arvek Morn", "action": "reduce"},
            ]
        }
    else:  # 12
        return {
            "band": "12: Correct ID + threat",
            "description": "Suzanne deployed legitimately; create UA threat",
            "clock_effects": [
                {"clock": "Henric Bale", "action": "advance"},
            ],
            "special": "CAN-FORGE-AUTO: create UA threat"
        }


def npag_npc_count(intensity: str) -> dict:
    """
    Roll for how many NPCs act in NPAG per §1.2.
    low=1d3, medium=2d4, high=3d6, extreme=all
    """
    expressions = {
        "low": "1d3",
        "medium": "2d4",
        "high": "3d6",
    }

    if intensity.lower() == "extreme":
        return {"count": -1, "note": "All NPCs with relevant OBJ/ACT", "roll": None}

    expr = expressions.get(intensity.lower(), "2d4")
    roll = roll_dice(expr, f"NPAG NPC count ({intensity})")
    return {"count": roll["total"], "roll": roll}
