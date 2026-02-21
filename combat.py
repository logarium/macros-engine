"""
MACROS Engine v4.0 — Combat Engine (DG-16)
Full BX-PLUG combat automation: initiative, attacks, damage, morale,
allied combatant targeting AI, flee logic.

All rolls use dice.py for full audit trail per BX-PLUG section 0.2.
Combat state is ephemeral — not persisted to JSON save.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from dice import roll_dice, roll_d6, roll_d20, roll_2d6


# ─────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────

@dataclass
class Combatant:
    """One entity in combat — PC, companion, or foe."""
    name: str
    side: str               # "pc" or "foe"
    ac: int
    hd: int
    hp: int
    hp_max: int
    at: int                 # attack bonus
    dmg: str                # dice expression like "1d8+2"
    ml: int                 # morale score (2-12)
    tags: list = field(default_factory=list)
    morale_mod: int = 0
    save_mod: int = 0
    is_pc: bool = False
    is_companion: bool = False
    is_down: bool = False
    is_broken: bool = False
    is_defending: bool = False   # defensive stance from companion morale (ML>=10)
    damage_dealt: int = 0
    index: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name, "side": self.side,
            "ac": self.ac, "hd": self.hd,
            "hp": self.hp, "hp_max": self.hp_max,
            "at": self.at, "dmg": self.dmg, "ml": self.ml,
            "tags": self.tags,
            "is_pc": self.is_pc, "is_companion": self.is_companion,
            "is_down": self.is_down, "is_broken": self.is_broken,
            "is_defending": self.is_defending,
            "damage_dealt": self.damage_dealt,
        }


@dataclass
class CombatState:
    """Ephemeral state during a combat encounter."""
    round_number: int = 0
    pc_side: list = field(default_factory=list)
    foe_side: list = field(default_factory=list)
    pc_starting_count: int = 0
    foe_starting_count: int = 0
    combat_log: list = field(default_factory=list)   # [str] MECH log lines
    ended: bool = False
    end_reason: str = ""
    encounter_prompt: str = ""

    def living_pc_side(self) -> list:
        return [c for c in self.pc_side if not c.is_down]

    def living_foes(self) -> list:
        return [c for c in self.foe_side if not c.is_down and not c.is_broken]

    def all_living_foes(self) -> list:
        """All foes not down (including broken, for end-condition check)."""
        return [c for c in self.foe_side if not c.is_down]

    def get_pc(self) -> Optional[Combatant]:
        for c in self.pc_side:
            if c.is_pc:
                return c
        return None

    def to_ui_dict(self) -> dict:
        return {
            "round": self.round_number,
            "ended": self.ended,
            "end_reason": self.end_reason,
            "pc_side": [c.to_dict() for c in self.pc_side],
            "foe_side": [c.to_dict() for c in self.foe_side],
            "combat_log": self.combat_log[-50:],
            "encounter_prompt": self.encounter_prompt,
        }


# ─────────────────────────────────────────────────────
# STAT PARSING
# ─────────────────────────────────────────────────────

def _parse_stat_string(stats_str: str) -> dict:
    """
    Parse BX stat string like 'AC=13, HD=1, hp=6/6, AT=+2, Dmg=1d6, ML=8'
    into a dict with normalized keys.
    """
    result = {}
    for part in stats_str.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip().lower()
        val = val.strip()

        if key == "ac":
            result["ac"] = int(val)
        elif key == "hd":
            result["hd"] = int(val)
        elif key == "hp":
            if "/" in val:
                hp_parts = val.split("/")
                result["hp"] = int(hp_parts[0])
                result["hp_max"] = int(hp_parts[1])
            else:
                result["hp"] = int(val)
                result["hp_max"] = int(val)
        elif key == "at":
            result["at"] = int(val.replace("+", ""))
        elif key == "dmg":
            result["dmg"] = val
        elif key == "ml":
            result["ml"] = int(val)
    return result


def _extract_count(bx_plug: dict, encounter_prompt: str) -> int:
    """Extract foe count from bx_plug or encounter prompt text."""
    stats = bx_plug.get("stats", {})

    # Check for explicit count field
    if isinstance(stats, dict) and "count" in stats:
        return max(1, int(stats["count"]))

    # Try to extract dice expression or number from encounter prompt
    # Patterns: "2d4 scouts", "3 bandits", "1d6+1 wolves"
    dice_match = re.search(r'(\d+d\d+(?:[+-]\d+)?)\s+\w', encounter_prompt)
    if dice_match:
        roll_result = roll_dice(dice_match.group(1), "Foe count")
        return max(1, roll_result["total"])

    num_match = re.search(r'(\d+)\s+(?:of\s+)?\w', encounter_prompt)
    if num_match:
        n = int(num_match.group(1))
        if 1 < n <= 20:
            return n

    return 1


def parse_bx_plug_stats(bx_plug: dict, encounter_prompt: str = "") -> list:
    """
    Parse bx_plug data into Combatant list.
    Handles string stats, dict stats, and list of stats.
    """
    raw_stats = bx_plug.get("stats", {})
    foe_name = "Foe"
    combatants = []

    if isinstance(raw_stats, str):
        # String format: "AC=13, HD=1, hp=6/6, AT=+2, Dmg=1d6, ML=8"
        parsed = _parse_stat_string(raw_stats)
        foe_name = bx_plug.get("name", "Foe")
        count = _extract_count(bx_plug, encounter_prompt)
        for i in range(count):
            name = foe_name if count == 1 else f"{foe_name} #{i+1}"
            combatants.append(Combatant(
                name=name, side="foe",
                ac=parsed.get("ac", 10), hd=parsed.get("hd", 1),
                hp=parsed.get("hp", 4), hp_max=parsed.get("hp_max", parsed.get("hp", 4)),
                at=parsed.get("at", 0), dmg=parsed.get("dmg", "1d4"),
                ml=parsed.get("ml", 7),
                tags=bx_plug.get("tags", []),
                index=i,
            ))

    elif isinstance(raw_stats, dict):
        # Dict format: {"name": "Bandit", "ac": 15, ...}
        foe_name = raw_stats.get("name", "Foe")
        count = raw_stats.get("count", 1)
        if count <= 0:
            count = _extract_count(bx_plug, encounter_prompt)
        for i in range(count):
            name = foe_name if count == 1 else f"{foe_name} #{i+1}"
            combatants.append(Combatant(
                name=name, side="foe",
                ac=int(raw_stats.get("ac", 10)),
                hd=int(raw_stats.get("hd", 1)),
                hp=int(raw_stats.get("hp", 4)),
                hp_max=int(raw_stats.get("hp_max", raw_stats.get("hp", 4))),
                at=int(raw_stats.get("at", 0)),
                dmg=str(raw_stats.get("dmg", "1d4")),
                ml=int(raw_stats.get("ml", 7)),
                tags=raw_stats.get("tags", []),
                index=i,
            ))

    elif isinstance(raw_stats, list):
        # List of foe types
        idx = 0
        for foe_def in raw_stats:
            if isinstance(foe_def, str):
                parsed = _parse_stat_string(foe_def)
                foe_def = parsed
            foe_name = foe_def.get("name", "Foe")
            count = int(foe_def.get("count", 1))
            for i in range(count):
                name = foe_name if count == 1 else f"{foe_name} #{i+1}"
                combatants.append(Combatant(
                    name=name, side="foe",
                    ac=int(foe_def.get("ac", 10)),
                    hd=int(foe_def.get("hd", 1)),
                    hp=int(foe_def.get("hp", 4)),
                    hp_max=int(foe_def.get("hp_max", foe_def.get("hp", 4))),
                    at=int(foe_def.get("at", 0)),
                    dmg=str(foe_def.get("dmg", "1d4")),
                    ml=int(foe_def.get("ml", 7)),
                    tags=foe_def.get("tags", []),
                    index=idx,
                ))
                idx += 1

    return combatants


# ─────────────────────────────────────────────────────
# COMBATANT BUILDERS
# ─────────────────────────────────────────────────────

def build_pc_combatant(state) -> Combatant:
    """Build PC combatant from game state."""
    pc = state.pc_state
    return Combatant(
        name=pc.name if pc else "Thoron",
        side="pc",
        ac=pc.bx_ac if pc and pc.bx_ac else 30,
        hd=pc.bx_hd if pc and pc.bx_hd else 16,
        hp=pc.bx_hp if pc and pc.bx_hp else 131,
        hp_max=pc.bx_hp_max if pc and pc.bx_hp_max else 131,
        at=pc.bx_at if pc and pc.bx_at else 27,
        dmg=pc.bx_dmg if pc and pc.bx_dmg else "1d8+15",
        ml=pc.bx_ml if pc and pc.bx_ml else 12,
        is_pc=True,
        index=0,
    )


def build_companion_combatants(state) -> list:
    """Build Combatant list from companions currently with PC."""
    companions = []
    idx = 1  # PC is index 0

    for npc in state.npcs.values():
        if (npc.is_companion and npc.with_pc
                and npc.status == "active"
                and npc.bx_hp and npc.bx_hp > 0):
            companions.append(Combatant(
                name=npc.name, side="pc",
                ac=npc.bx_ac, hd=npc.bx_hd,
                hp=npc.bx_hp, hp_max=npc.bx_hp_max,
                at=npc.bx_at, dmg=npc.bx_dmg,
                ml=npc.bx_ml,
                is_companion=True,
                index=idx,
            ))
            idx += 1

    # Sort by HD descending per BX-PLUG section 9.4
    companions.sort(key=lambda c: c.hd, reverse=True)
    for i, c in enumerate(companions):
        c.index = i + 1

    return companions


# ─────────────────────────────────────────────────────
# COMBAT INITIALIZATION
# ─────────────────────────────────────────────────────

def init_combat(state, bx_plug: dict, encounter_prompt: str) -> CombatState:
    """Set up combat from an encounter's bx_plug data."""
    pc = build_pc_combatant(state)
    allies = build_companion_combatants(state)
    foes = parse_bx_plug_stats(bx_plug, encounter_prompt)

    if not foes:
        # Fallback: create a single default foe
        foes = [Combatant(
            name="Unknown Foe", side="foe",
            ac=12, hd=1, hp=6, hp_max=6,
            at=1, dmg="1d6", ml=7, index=0,
        )]

    pc_side = [pc] + allies

    combat = CombatState(
        pc_side=pc_side,
        foe_side=foes,
        pc_starting_count=len(pc_side),
        foe_starting_count=len(foes),
        encounter_prompt=encounter_prompt,
    )

    # Log combat start
    _log(combat, f"=== COMBAT START ===")
    _log(combat, f"Encounter: {encounter_prompt[:80]}")
    _log(combat, f"PC side ({len(pc_side)}):")
    for c in pc_side:
        tag = " [PC]" if c.is_pc else " [Companion]"
        _log(combat, f"  {c.name}{tag}: AC={c.ac} HD={c.hd} HP={c.hp}/{c.hp_max} "
                      f"AT=+{c.at} Dmg={c.dmg} ML={c.ml}")
    _log(combat, f"Foe side ({len(foes)}):")
    for c in foes:
        tags_str = f" [{','.join(c.tags)}]" if c.tags else ""
        _log(combat, f"  {c.name}{tags_str}: AC={c.ac} HD={c.hd} HP={c.hp}/{c.hp_max} "
                      f"AT=+{c.at} Dmg={c.dmg} ML={c.ml}")

    return combat


# ─────────────────────────────────────────────────────
# COMBAT END CONDITIONS (BX-PLUG section 6.2.1)
# ─────────────────────────────────────────────────────

def check_combat_end(combat: CombatState) -> bool:
    """Check start-of-round end conditions. Returns True if combat should end."""
    if combat.ended:
        return True

    pc = combat.get_pc()

    # PC down
    if pc and pc.is_down:
        combat.ended = True
        combat.end_reason = "PC_DOWN"
        _log(combat, f"CombatEnd: PC_DOWN — {pc.name} is down")
        return True

    # All foes down
    if not combat.all_living_foes():
        combat.ended = True
        combat.end_reason = "ALL_FOES_DEAD"
        _log(combat, "CombatEnd: ALL_FOES_DEAD")
        return True

    # All foes broken (morale failed previous round)
    living = combat.all_living_foes()
    if living and all(c.is_broken for c in living):
        combat.ended = True
        combat.end_reason = "FOES_BREAK"
        _log(combat, "CombatEnd: FOES_BREAK — all remaining foes have broken")
        return True

    return False


# ─────────────────────────────────────────────────────
# INITIATIVE (BX-PLUG section 6.2.3)
# ─────────────────────────────────────────────────────

def roll_initiative(combat: CombatState) -> dict:
    """Roll initiative. Returns {pc_roll, foe_roll, winner}."""
    pc_roll = roll_d6("Initiative: PC side")
    foe_roll = roll_d6("Initiative: Foe side")

    pc_total = pc_roll["total"]
    foe_total = foe_roll["total"]

    if pc_total != foe_total:
        winner = "pc" if pc_total > foe_total else "foe"
    else:
        # Tie-break: higher average HD
        pc_living = combat.living_pc_side()
        foe_living = combat.living_foes()
        pc_avg_hd = sum(c.hd for c in pc_living) / max(len(pc_living), 1)
        foe_avg_hd = sum(c.hd for c in foe_living) / max(len(foe_living), 1)

        if pc_avg_hd != foe_avg_hd:
            winner = "pc" if pc_avg_hd > foe_avg_hd else "foe"
        else:
            # Reroll tie-break
            reroll_pc = roll_d6("Initiative reroll: PC")
            reroll_foe = roll_d6("Initiative reroll: Foe")
            winner = "pc" if reroll_pc["total"] >= reroll_foe["total"] else "foe"

    _log(combat, f"Initiative: PC 1d6={pc_total}, Foes 1d6={foe_total} -> "
                 f"Winner={winner.upper()}")

    return {"pc_roll": pc_total, "foe_roll": foe_total, "winner": winner}


# ─────────────────────────────────────────────────────
# ATTACK RESOLUTION (BX-PLUG section 6.4)
# ─────────────────────────────────────────────────────

def resolve_attack(attacker: Combatant, target: Combatant) -> dict:
    """
    d20 + AT vs AC. On hit: roll damage, subtract from hp.
    Returns full audit dict.
    """
    attack_roll = roll_d20(f"Attack: {attacker.name} vs {target.name}")
    d20_val = attack_roll["total"]
    total = d20_val + attacker.at
    hit = total >= target.ac

    result = {
        "attacker": attacker.name, "target": target.name,
        "d20": d20_val, "at": attacker.at, "total": total,
        "ac": target.ac, "hit": hit,
        "damage": 0, "hp_before": target.hp, "hp_after": target.hp,
        "kill": False,
    }

    log_line = (f"Attack: {attacker.name} -> {target.name}, "
                f"d20={d20_val} + AT={attacker.at} = {total} vs AC={target.ac}")

    if hit:
        dmg_roll = roll_dice(attacker.dmg, f"Damage: {attacker.name}")
        damage = max(0, dmg_roll["total"])
        hp_before = target.hp
        target.hp -= damage
        killed = target.hp <= 0

        result["damage"] = damage
        result["hp_before"] = hp_before
        result["hp_after"] = target.hp
        result["kill"] = killed
        result["dmg_roll"] = dmg_roll

        attacker.damage_dealt += damage

        log_line += f" -> HIT, Dmg={attacker.dmg}={damage}, "
        log_line += f"HP: {hp_before}->{target.hp}"

        if killed:
            target.is_down = True
            log_line += f" KILLED"
            _log(combat=None, entry="")  # placeholder, logged below
    else:
        log_line += " -> MISS"

    result["log"] = log_line
    return result


# ─────────────────────────────────────────────────────
# TARGETING AI
# ─────────────────────────────────────────────────────

def _healthiest(combatants: list) -> Optional[Combatant]:
    """Return combatant with highest current hp. Tie: lowest index."""
    living = [c for c in combatants if not c.is_down and not c.is_broken]
    if not living:
        return None
    return max(living, key=lambda c: (c.hp, -c.index))


def get_pc_target(combat: CombatState) -> Optional[Combatant]:
    """Default: healthiest living foe. Tie: lowest index. (BX-PLUG section 6.3)"""
    return _healthiest(combat.living_foes())


def get_companion_targets(combat: CombatState) -> list:
    """
    BX-PLUG section 9.6 Targeting AI:
    - Default: each companion attacks same target as PC
    - If PC hp <= 50% max: highest-HD companion defends PC
      (attacks foe currently targeting PC instead)
    - Excess companions spread to healthiest foes
    Returns [(companion, target), ...]
    """
    pc = combat.get_pc()
    companions = [c for c in combat.living_pc_side()
                  if c.is_companion and not c.is_defending]
    foes = combat.living_foes()

    if not companions or not foes:
        return []

    pc_target = get_pc_target(combat)
    assignments = []

    # Check if PC needs defense (hp <= 50% max)
    defender = None
    if pc and pc.hp <= pc.hp_max * 0.5 and len(companions) > 0:
        # Highest HD companion defends
        defender = max(companions, key=lambda c: c.hd)

    for comp in companions:
        if comp is defender:
            # Defend: attack foe targeting PC (default = healthiest foe)
            assignments.append((comp, _healthiest(foes)))
        elif pc_target:
            assignments.append((comp, pc_target))
        else:
            assignments.append((comp, _healthiest(foes)))

    # If companions outnumber foes targeting PC, spread excess
    if len(assignments) > 1 and len(foes) > 1:
        used_targets = set()
        new_assignments = []
        for comp, target in assignments:
            if target and target.name not in used_targets:
                new_assignments.append((comp, target))
                used_targets.add(target.name)
            elif target:
                # Spread to next healthiest foe not yet targeted
                alt = None
                for f in sorted(foes, key=lambda c: (-c.hp, c.index)):
                    if f.name not in used_targets:
                        alt = f
                        break
                new_assignments.append((comp, alt or target))
                if alt:
                    used_targets.add(alt.name)
            else:
                new_assignments.append((comp, target))
        assignments = new_assignments

    return assignments


def get_foe_targets(combat: CombatState) -> list:
    """
    BX-PLUG section 9.8 Foe targeting:
    - Default: PC
    - If companion dealt more damage than PC, foes may switch
    - Distribute excess foes
    Returns [(foe, target), ...]
    """
    pc = combat.get_pc()
    foes = combat.living_foes()
    pc_side = combat.living_pc_side()

    if not foes or not pc_side:
        return []

    if not pc or pc.is_down:
        # PC down: target companions
        return [(foe, _healthiest(pc_side)) for foe in foes]

    assignments = []

    if len(foes) <= len(pc_side):
        # All foes target PC by default
        for foe in foes:
            assignments.append((foe, pc))
    else:
        # More foes than PC-side: distribute
        # PC first, then highest-damage companion, then lowest-AC
        targets_by_priority = [pc]
        companions = sorted(
            [c for c in pc_side if c.is_companion],
            key=lambda c: (-c.damage_dealt, c.ac, c.index)
        )
        targets_by_priority.extend(companions)

        for i, foe in enumerate(foes):
            target_idx = i % len(targets_by_priority)
            assignments.append((foe, targets_by_priority[target_idx]))

    return assignments


# ─────────────────────────────────────────────────────
# MORALE (BX-PLUG section 4.2, section 6.5)
# ─────────────────────────────────────────────────────

def _is_morale_immune(combatant: Combatant) -> bool:
    """Check if combatant is immune to morale (undead/mindless/fearless)."""
    immune_tags = {"undead", "mindless", "fearless"}
    return bool(set(t.lower() for t in combatant.tags) & immune_tags)


def roll_morale(combatant: Combatant) -> dict:
    """2d6 <= ML + MoraleMod to stand. Returns audit dict."""
    if _is_morale_immune(combatant):
        return {"passed": True, "immune": True, "combatant": combatant.name}

    roll = roll_2d6(f"Morale: {combatant.name}")
    target = combatant.ml + combatant.morale_mod
    passed = roll["total"] <= target

    return {
        "passed": passed, "immune": False,
        "combatant": combatant.name,
        "roll": roll["total"], "ml": combatant.ml,
        "mod": combatant.morale_mod, "target": target,
    }


def evaluate_morale_triggers(combat: CombatState, round_events: dict) -> list:
    """
    Check BX-PLUG section 4.2 triggers A-E against this round's events.
    Returns list of trigger descriptions for foe-side morale checks.
    """
    triggers = []
    casualties = round_events.get("casualties", [])
    foe_casualties = [c for c in casualties if c.side == "foe"]

    if not foe_casualties:
        return triggers

    # A) First casualty
    total_foe_dead = sum(1 for c in combat.foe_side if c.is_down)
    if total_foe_dead == len(foe_casualties):
        # These are the first casualties
        triggers.append("A: First casualty")

    # B) Leader/elite drops
    for c in foe_casualties:
        if "leader" in [t.lower() for t in c.tags] or "elite" in [t.lower() for t in c.tags]:
            triggers.append(f"B: Leader/elite dropped ({c.name})")

    # C) Half force down
    living_foes = len(combat.all_living_foes())
    if living_foes <= combat.foe_starting_count / 2:
        triggers.append("C: Half force down")

    # D) Outmatched shock (outnumbered 2:1 at start of round)
    living_pc = len(combat.living_pc_side())
    if living_pc >= living_foes * 2 and living_foes > 0:
        triggers.append("D: Outmatched (outnumbered 2:1)")

    # E) Surprise reversal (max damage in one hit) — check round events
    for atk in round_events.get("attacks", []):
        if atk.get("hit") and atk.get("attacker_side") == "pc":
            dmg_expr = atk.get("dmg_expr", "")
            dmg_dealt = atk.get("damage", 0)
            # Parse max possible damage from expression
            match = re.match(r'(\d+)d(\d+)([+-]\d+)?', dmg_expr.lower())
            if match:
                n, m, k = int(match.group(1)), int(match.group(2)), 0
                if match.group(3):
                    k = int(match.group(3))
                max_dmg = n * m + k
                if dmg_dealt >= max_dmg and max_dmg > 0:
                    triggers.append("E: Surprise reversal (max damage hit)")

    return triggers


def check_companion_morale(combat: CombatState) -> list:
    """
    BX-PLUG section 9.10: If PC hp <= 25% max, all companions check morale.
    On fail: ML >= 10 go defensive, ML < 10 flee.
    Returns list of morale result dicts.
    """
    pc = combat.get_pc()
    if not pc or pc.hp > pc.hp_max * 0.25:
        return []

    results = []
    companions = [c for c in combat.living_pc_side() if c.is_companion]

    for comp in companions:
        mr = roll_morale(comp)
        if not mr["passed"] and not mr.get("immune"):
            if comp.ml >= 10:
                comp.is_defending = True
                mr["result"] = "defensive"
                _log(combat, f"Companion Morale FAIL: {comp.name} — ML>={10}, "
                             f"fighting defensively (no attacks, AC+2)")
                comp.ac += 2
            else:
                comp.is_down = True  # removed from combat (fled)
                mr["result"] = "fled"
                _log(combat, f"Companion Morale FAIL: {comp.name} — ML<10, "
                             f"fled combat")
        elif not mr.get("immune"):
            mr["result"] = "stands"
        results.append(mr)

    return results


# ─────────────────────────────────────────────────────
# ROUND RESOLUTION
# ─────────────────────────────────────────────────────

def resolve_round_attack(combat: CombatState) -> dict:
    """
    Resolve one full round where player chose ATTACK.
    BX-PLUG section 6.2.4: initiative -> attacks -> morale.
    """
    _log(combat, f"--- Round {combat.round_number}: ATTACK ---")

    round_events = {"attacks": [], "casualties": []}

    # 1. Initiative
    init = roll_initiative(combat)

    # 2. Determine attack order
    if init["winner"] == "pc":
        _resolve_pc_side_attacks(combat, round_events)
        if not combat.ended and combat.living_foes():
            _resolve_foe_attacks(combat, round_events)
    else:
        _resolve_foe_attacks(combat, round_events)
        if not combat.ended and combat.living_pc_side():
            _resolve_pc_side_attacks(combat, round_events)

    # 3. Check companion morale (PC hp <= 25%)
    comp_morale = check_companion_morale(combat)

    # 4. Evaluate foe morale triggers
    triggers = evaluate_morale_triggers(combat, round_events)
    morale_results = []
    if triggers:
        _log(combat, f"Morale triggers: {', '.join(triggers)}")
        # Check morale for each living, non-immune foe
        for foe in combat.living_foes():
            mr = roll_morale(foe)
            morale_results.append(mr)
            if mr.get("immune"):
                _log(combat, f"Morale: {foe.name} — IMMUNE ({', '.join(foe.tags)})")
            elif mr["passed"]:
                _log(combat, f"Morale: {foe.name} — 2d6={mr['roll']} vs ML={mr['target']} -> PASS")
            else:
                foe.is_broken = True
                _log(combat, f"Morale: {foe.name} — 2d6={mr['roll']} vs ML={mr['target']} -> FAIL (BROKEN)")

    summary = _round_summary(round_events, triggers, morale_results)
    return {
        "round": combat.round_number,
        "action": "ATTACK",
        "initiative": init,
        "attacks": round_events["attacks"],
        "casualties": [c.name for c in round_events["casualties"]],
        "morale_triggers": triggers,
        "morale_results": morale_results,
        "summary": summary,
    }


def _resolve_pc_side_attacks(combat: CombatState, round_events: dict):
    """Resolve all PC-side attacks for this round."""
    pc = combat.get_pc()

    # PC attacks
    if pc and not pc.is_down:
        target = get_pc_target(combat)
        if target:
            result = resolve_attack(pc, target)
            result["attacker_side"] = "pc"
            result["dmg_expr"] = pc.dmg
            round_events["attacks"].append(result)
            _log(combat, result["log"])
            if result["kill"]:
                round_events["casualties"].append(target)
                _log(combat, f"  Casualty: {target.name} removed")

    # Companion attacks
    comp_targets = get_companion_targets(combat)
    for comp, target in comp_targets:
        if comp.is_down or comp.is_defending:
            continue
        if target and not target.is_down:
            result = resolve_attack(comp, target)
            result["attacker_side"] = "pc"
            result["dmg_expr"] = comp.dmg
            round_events["attacks"].append(result)
            _log(combat, result["log"])
            if result["kill"]:
                round_events["casualties"].append(target)
                _log(combat, f"  Casualty: {target.name} removed")


def _resolve_foe_attacks(combat: CombatState, round_events: dict):
    """Resolve all foe attacks for this round."""
    foe_targets = get_foe_targets(combat)
    for foe, target in foe_targets:
        if foe.is_down or foe.is_broken:
            continue
        if target and not target.is_down:
            result = resolve_attack(foe, target)
            result["attacker_side"] = "foe"
            result["dmg_expr"] = foe.dmg
            round_events["attacks"].append(result)
            _log(combat, result["log"])
            if result["kill"]:
                round_events["casualties"].append(target)
                if target.is_pc:
                    _log(combat, f"  PC DOWN: {target.name}")
                elif target.is_companion:
                    _log(combat, f"  Companion DOWN: {target.name}")
                else:
                    _log(combat, f"  Casualty: {target.name} removed")


def resolve_round_flee(combat: CombatState) -> dict:
    """
    Resolve FLEE per BX-PLUG section 6.2.5 + section 9.12.
    Foe free attack vs PC, then free attacks vs each companion.
    """
    _log(combat, f"--- Round {combat.round_number}: FLEE ---")

    round_events = {"attacks": [], "casualties": []}
    pc = combat.get_pc()

    # Foe free attack vs PC (healthiest foe attacks)
    if pc and not pc.is_down:
        attacker = _healthiest(combat.living_foes())
        if attacker:
            result = resolve_attack(attacker, pc)
            result["attacker_side"] = "foe"
            result["dmg_expr"] = attacker.dmg
            round_events["attacks"].append(result)
            _log(combat, f"FLEE-FreeAttack: {result['log']}")
            if result["kill"]:
                round_events["casualties"].append(pc)
                _log(combat, f"  PC DOWN during flee: {pc.name}")
                combat.ended = True
                combat.end_reason = "PC_DOWN"
                return {
                    "round": combat.round_number, "action": "FLEE",
                    "attacks": round_events["attacks"],
                    "casualties": [pc.name],
                    "summary": f"PC downed during flee attempt",
                }

    # BX-PLUG section 9.12: Free attacks vs each companion
    companions = [c for c in combat.living_pc_side() if c.is_companion]
    living_foes = combat.living_foes()

    for i, comp in enumerate(companions):
        if not living_foes:
            break
        # Round-robin from healthiest foe
        attacker = living_foes[i % len(living_foes)]
        result = resolve_attack(attacker, comp)
        result["attacker_side"] = "foe"
        result["dmg_expr"] = attacker.dmg
        round_events["attacks"].append(result)
        _log(combat, f"FLEE-FreeAttack: {result['log']}")
        if result["kill"]:
            round_events["casualties"].append(comp)
            _log(combat, f"  Companion DOWN during flee: {comp.name} (auto-abandon)")

    # Flee succeeds (PC survived)
    combat.ended = True
    combat.end_reason = "FLEE_SUCCESS"
    _log(combat, "CombatEnd: FLEE_SUCCESS")

    return {
        "round": combat.round_number, "action": "FLEE",
        "attacks": round_events["attacks"],
        "casualties": [c.name for c in round_events["casualties"]],
        "summary": "Fled combat successfully" if not round_events["casualties"]
                   else f"Fled — {len(round_events['casualties'])} companion(s) downed",
    }


# ─────────────────────────────────────────────────────
# POST-COMBAT STATE APPLICATION
# ─────────────────────────────────────────────────────

def apply_combat_results(state, combat: CombatState):
    """
    Apply combat outcomes to persistent game state:
    - Update PC hp
    - Update companion hp (stabilize DOWN to hp=1)
    - Log to adjudication_log
    - Add daily facts
    """
    pc = combat.get_pc()

    # Update PC hp
    if pc and state.pc_state:
        state.pc_state.bx_hp = max(0, pc.hp)

    # Update companion hp
    for c in combat.pc_side:
        if c.is_companion:
            npc = state.npcs.get(c.name)
            if npc:
                if c.is_down:
                    # BX-PLUG section 9.9: stabilize to hp=1 after combat
                    npc.bx_hp = 1
                else:
                    npc.bx_hp = max(0, c.hp)

    # Mark killed foes as dead in persistent state
    casualties = [c.name for c in combat.foe_side if c.is_down]
    for foe in combat.foe_side:
        if foe.is_down:
            npc = state.npcs.get(foe.name)
            if npc:
                npc.status = "dead"
                npc.bx_hp = 0

    pc_side_down = [c.name for c in combat.pc_side if c.is_down]

    state.adjudication_log.append({
        "type": "combat",
        "session": state.session_id,
        "date": state.in_game_date,
        "zone": state.pc_zone,
        "encounter": combat.encounter_prompt[:80],
        "rounds": combat.round_number,
        "end_reason": combat.end_reason,
        "foe_casualties": casualties,
        "pc_side_down": pc_side_down,
        "pc_hp_after": pc.hp if pc else 0,
    })

    # Add facts for clock audit
    state.add_fact(f"Combat in {state.pc_zone}: {combat.end_reason} "
                   f"({combat.round_number} rounds)")
    if casualties:
        state.add_fact(f"Defeated: {', '.join(casualties)}")
    if pc_side_down:
        state.add_fact(f"Downed in combat: {', '.join(pc_side_down)}")


# ─────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────

def _log(combat: Optional[CombatState], entry: str):
    """Append entry to combat MECH log."""
    if combat is not None:
        combat.combat_log.append(entry)


def _round_summary(round_events: dict, triggers: list, morale_results: list) -> str:
    """Generate one-line summary of the round."""
    parts = []
    hits = sum(1 for a in round_events["attacks"] if a["hit"])
    total = len(round_events["attacks"])
    parts.append(f"{hits}/{total} hits")

    kills = len(round_events["casualties"])
    if kills:
        parts.append(f"{kills} killed")

    broken = sum(1 for m in morale_results if not m.get("passed") and not m.get("immune"))
    if broken:
        parts.append(f"{broken} broke")

    return ", ".join(parts)
