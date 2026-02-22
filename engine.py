"""
MACROS Engine v1.0 — Time & Pressure Day Loop
Implements T&P §1.0-7.0 deterministic procedure.

This is the heart of the mechanical engine. It processes each day:
1. Advance date
2. Run cadence engines
3. Advance cadence clocks
4. CLOCK AUDIT — check ALL active clocks against established facts
5. Encounter gate roll
6. NPAG gate roll
7. Full audit log

LLM calls are deferred — the engine marks where creative content is needed
and returns structured requests that can be sent to Claude later.
"""

from models import GameState, Clock, Engine
import re
from dice import (roll_dice, roll_d6, roll_2d6,
                  intensity_gate_check, vp_outcome_band, npag_npc_count)


# ─────────────────────────────────────────────────────
# CALENDAR
# ─────────────────────────────────────────────────────

# Nurrian Calendar: 12 months + 3 intercalary periods = 365 days
# Canonical order from MACROS_ENGINE_SPEC_v1_0
MONTHS = [
    "Day of Awakening",                       # Intercalary (1d)
    "Demes", "Fasting", "Tryphor",            # Winter→Spring
    "Day of the Moot",                        # Intercalary (1d)
    "Ilrym", "Evernew",                       # Spring
    "Jestrim",                                # Summer
    "The Stand",                              # Intercalary (7d)
    "Rannifer", "Reapmere",                   # Summer
    "Grismere", "Aphistri", "Frithium",       # Autumn
    "Revini",                                 # Winter
]

MONTH_DAYS = {
    "Day of Awakening": 1,
    "Demes": 30, "Fasting": 28, "Tryphor": 30,
    "Day of the Moot": 1,
    "Ilrym": 30, "Evernew": 31,
    "Jestrim": 23,
    "The Stand": 7,
    "Rannifer": 31, "Reapmere": 30,
    "Grismere": 30, "Aphistri": 31, "Frithium": 30,
    "Revini": 31,
}

SEASONS = {
    "Day of Awakening": "Winter",
    "Demes": "Winter", "Fasting": "Winter",
    "Tryphor": "Spring",
    "Day of the Moot": "Spring",
    "Ilrym": "Spring", "Evernew": "Spring",
    "Jestrim": "Summer",
    "The Stand": "Summer",
    "Rannifer": "Summer", "Reapmere": "Summer",
    "Grismere": "Autumn", "Aphistri": "Autumn", "Frithium": "Autumn",
    "Revini": "Winter",
}

SEASONAL_PRESSURE = {
    "Spring": "Feed & Seed \u2014 food stores depleted; planting season critical",
    "Summer": "Raw Materials \u2014 construction, repairs, military production peak",
    "Autumn": "Harvest \u2014 success/failure determines winter survival",
    "Winter": "Firewood & Pitch \u2014 survival essentials; cold is lethal",
}


def advance_date(state: GameState) -> dict:
    """Advance in-game date by 1 day. Returns date change info."""
    old_date = f"{state.day_of_month} {state.month}"
    old_season = SEASONS.get(state.month, "Unknown")

    state.day_of_month += 1

    # Month rollover
    max_days = MONTH_DAYS.get(state.month, 31)
    if state.day_of_month > max_days:
        state.day_of_month = 1
        month_idx = MONTHS.index(state.month) if state.month in MONTHS else 0
        month_idx = (month_idx + 1) % len(MONTHS)
        state.month = MONTHS[month_idx]

    new_season = SEASONS.get(state.month, "Unknown")
    state.in_game_date = f"{state.day_of_month} {state.month}"
    state.season = new_season
    state.seasonal_pressure = SEASONAL_PRESSURE.get(new_season, "")

    result = {
        "action": "date_advance",
        "old_date": old_date,
        "new_date": state.in_game_date,
        "season_changed": old_season != new_season,
    }

    if old_season != new_season:
        result["old_season"] = old_season
        result["new_season"] = new_season
        result["seasonal_pressure"] = state.seasonal_pressure
        state.add_fact(f"Season changed: {old_season} -> {new_season}")

    state.add_fact(f"Date advanced to {state.in_game_date}")
    return result


# ─────────────────────────────────────────────────────
# ENGINE RUNNERS
# ─────────────────────────────────────────────────────

def run_vp_engine(state: GameState, engine: Engine) -> dict:
    """
    Run Vanguard Patrol Doctrine (VP v3.0).
    Deterministic: roll 2d6, map to outcome, apply clock effects.
    """
    # Hard gate: Fort Vanguard must exist
    if "Fort Vanguard" not in state.zones:
        return {"engine": engine.name, "skipped": True,
                "reason": "Hard_Gates: Fort Vanguard not in state"}

    roll = roll_2d6(f"VP roll - {state.in_game_date}")
    outcome = vp_outcome_band(roll["total"])

    log_entry = {
        "engine": engine.name,
        "roll": roll,
        "outcome_band": outcome["band"],
        "description": outcome["description"],
        "clock_effects_applied": [],
    }

    # Apply clock effects
    for effect in outcome.get("clock_effects", []):
        clock = state.get_clock(effect["clock"])
        if clock is None:
            log_entry["clock_effects_applied"].append({
                "clock": effect["clock"],
                "error": "Clock not found in state"
            })
            continue

        if clock.status == "retired" or clock.trigger_fired:
            log_entry["clock_effects_applied"].append({
                "clock": effect["clock"],
                "skipped": True,
                "reason": f"Clock status: {clock.status}"
            })
            continue

        if effect["action"] == "advance":
            result = clock.advance(
                reason=f"VP roll {roll['total']} -> {outcome['band']}",
                date=state.in_game_date,
                session=state.session_id,
            )
            log_entry["clock_effects_applied"].append(result)
            if "trigger_fired" in result:
                state.add_fact(f"Clock {clock.name} TRIGGER FIRED: {clock.trigger_on_completion}")

        elif effect["action"] == "reduce":
            result = clock.reduce(
                reason=f"VP roll {roll['total']} -> {outcome['band']}"
            )
            log_entry["clock_effects_applied"].append(result)

    # Special handling for roll=12
    if outcome.get("special"):
        log_entry["special_action"] = outcome["special"]
        log_entry["llm_request"] = {
            "type": "CAN-FORGE-AUTO",
            "context": "VP roll 12 — create UA threat for Fort Vanguard",
        }

    engine.runs_today += 1
    engine.last_run_date = state.in_game_date
    engine.last_run_session = state.session_id
    engine.roll_history.append({
        "date": state.in_game_date,
        "roll": roll["total"],
        "band": outcome["band"],
    })

    state.add_fact(f"VP engine ran: roll={roll['total']}, band={outcome['band']}")
    return log_entry


def run_tsdd_engine(state: GameState, engine: Engine) -> dict:
    """
    Run Temple of the Sun Doctrinal Debate (TSDD v3.0).
    Non-random: advance linked clock by 1 each day.
    """
    # Hard gate: Temple of the Sun must exist
    if "Temple of the Sun" not in state.zones:
        return {"engine": engine.name, "skipped": True,
                "reason": "Hard_Gates: Temple of the Sun not in state"}

    clock = state.get_clock("Temple of the Sun—Doctrinal Fracture")
    if clock is None:
        return {"engine": engine.name, "skipped": True,
                "reason": "Linked clock not found"}

    if clock.status in ("trigger_fired", "retired"):
        return {"engine": engine.name, "status": "inert",
                "reason": f"Linked clock status: {clock.status}"}

    result = clock.advance(
        reason="TSDD daily accumulation",
        date=state.in_game_date,
        session=state.session_id,
    )

    engine.runs_today += 1
    engine.last_run_date = state.in_game_date

    state.add_fact(f"TSDD advanced Doctrinal Fracture: {clock.progress}/{clock.max_progress}")

    log_entry = {"engine": engine.name, "clock_advance": result}
    if result.get("trigger_fired"):
        state.add_fact(f"Temple of the Sun SCHISM: {clock.trigger_on_completion}")
        log_entry["trigger_fired"] = True

    return log_entry


def run_htdh_engine(state: GameState, engine: Engine) -> dict:
    """
    Run Hidden Temple Demon-Hunt Cadence (HT-DH v3.0).
    Hard gate: Demon Ledger must be >= 1.
    Non-random doctrine escalation.
    """
    demon_ledger = state.get_clock("Hidden Temple—Demon Ledger")
    if demon_ledger is None or demon_ledger.progress < 1:
        engine.status = "dormant"
        return {"engine": engine.name, "skipped": True,
                "reason": "Hard_Gates: Demon Ledger = 0 (dormant)"}

    engine.status = "active"
    engine.runs_today += 1
    engine.last_run_date = state.in_game_date

    # HT-DH doesn't auto-advance clocks — it makes the linked clocks
    # eligible for clock audit advancement. The actual advancement
    # happens in the clock audit step when ADV bullets are checked.
    state.add_fact("HT-DH engine active — Hidden Temple clocks eligible for audit advancement")

    return {
        "engine": engine.name,
        "status": "active",
        "note": "Linked clocks eligible for clock audit this day",
        "linked_clocks": engine.linked_clocks,
    }


def run_srp_engine(state: GameState, engine: Engine) -> dict:
    """
    Run Seasonal Resource Pressure (SRP v1.0).
    Only triggers on season change.
    """
    # Check if season changed today (stored in daily_facts)
    season_changed = any("Season changed" in f for f in state.daily_facts)

    if not season_changed:
        return {"engine": engine.name, "skipped": True,
                "reason": "No season change today"}

    engine.runs_today += 1
    engine.last_run_date = state.in_game_date

    state.add_fact(f"SRP triggered: {state.season} — {state.seasonal_pressure}")

    return {
        "engine": engine.name,
        "season": state.season,
        "pressure": state.seasonal_pressure,
    }


# Engine runner dispatch
ENGINE_RUNNERS = {
    "Vanguard Patrol Doctrine": run_vp_engine,
    "Temple of the Sun — Doctrinal Debate": run_tsdd_engine,
    "Hidden Temple — Demon-Hunt Cadence": run_htdh_engine,
    "Seasonal Resource Pressure": run_srp_engine,
}


# ─────────────────────────────────────────────────────
# CADENCE CLOCK ADVANCEMENT
# ─────────────────────────────────────────────────────

def advance_cadence_clocks(state: GameState) -> list:
    """
    Advance cadence clocks. Only auto-advance if cadence_bullet is set
    (e.g. "Decay"). If cadence_bullet is empty, the clock is merely
    eligible for audit review — it does NOT auto-tick.
    """
    results = []
    for clock in state.cadence_clocks():
        if not clock.cadence_bullet:
            # No cadence_bullet → audit-eligible only, not auto-advance
            results.append({
                "clock": clock.name,
                "action": "cadence_eligible_for_audit",
                "reason": "Cadence PE active — clock eligible for audit, "
                          "not auto-advanced (cadence_bullet is empty)",
            })
            continue
        if clock.can_advance():
            result = clock.advance(
                reason=f"Cadence: {clock.cadence_bullet}",
                date=state.in_game_date,
                session=state.session_id,
            )
            results.append(result)
            state.add_fact(f"Cadence clock {clock.name} advanced: "
                          f"{result['new']}/{clock.max_progress}")
            if result.get("trigger_fired"):
                state.add_fact(f"TRIGGER FIRED: {clock.name} — {clock.trigger_on_completion}")
    return results


# ─────────────────────────────────────────────────────
# CLOCK INTERACTION RULES (NSV-CLOCKS v1.0)
# ─────────────────────────────────────────────────────

# Map short names used in rules to full clock names in state
CLOCK_NAME_MAP = {
    "Binding Degradation": "Children of the Dead Gods\u2014Binding Degradation",
    "Enigma Crystal Hunt": "Cult of Orcus\u2014Enigma Crystal Hunt",
    "Dimensional Instability\u2014Western Scarps": "Dimensional Instability\u2014Western Scarps",
    "Demon Ledger": "Hidden Temple\u2014Demon Ledger",
    "Suzanne Loyalty": "Suzanne Loyalty\u2014Helkar vs Orcus",
    "Deep Tremors": "Deep Tremors\u2014Khuzdukan",
    "Frontier (General)": "Helkar Recognition\u2014Frontier (General)",
    "Doctrine Stress Test": "Doctrine Stress Test",
    "East March Unknown Tracks": "East March Unknown Tracks",
}

CLOCK_INTERACTION_RULES = [
    {
        "id": "INTERACT_01",
        "clock_a": "Binding Degradation", "threshold_a": 15,
        "clock_b": "Enigma Crystal Hunt", "threshold_b": 10,
        "effect": "FLAG",
        "flag_text": "Entity senses Orcus network weakening; communion circles flicker; cultists receive visions",
        "one_time": True,
    },
    {
        "id": "INTERACT_02",
        "clock_a": "Binding Degradation", "threshold_a": 12,
        "clock_b": "Dimensional Instability\u2014Western Scarps", "threshold_b": 5,
        "effect": "ADV",
        "adv_clock": "Dimensional Instability\u2014Western Scarps",
        "one_time": True,
    },
    {
        "id": "INTERACT_03",
        "clock_a": "Demon Ledger", "threshold_a": 6,
        "clock_b": "Enigma Crystal Hunt", "threshold_b": 8,
        "effect": "FLAG",
        "flag_text": "Hidden Temple cell and Orcus cult operations intersect; territorial conflict imminent",
        "one_time": True,
    },
    {
        "id": "INTERACT_04",
        "clock_a": "Binding Degradation", "threshold_a": 14,
        "clock_b": "Suzanne Loyalty", "threshold_b": 3,
        "effect": "FLAG",
        "flag_text": "Yor-Kazh resonance intensifies; Suzanne's resistance tested by proximity to weakening binding",
        "one_time": True,
    },
    {
        "id": "INTERACT_05",
        "clock_a": "Dimensional Instability\u2014Western Scarps", "threshold_a": 4,
        "clock_b": "Deep Tremors", "threshold_b": 5,
        "effect": "SPAWN",
        "spawn_clock": {
            "name": "Continental Binding Failure",
            "owner": "Environment",
            "max_progress": 10,
            "advance_bullets": [
                "Any binding node clock reaches max-1",
                "New instability zone discovered",
                "Edhellar incursion",
            ],
            "halt_conditions": [
                "Two or more nodes stabilized simultaneously",
            ],
            "reduce_conditions": [
                "Binding node reinforced",
                "Lithoe/equivalent applies counter-sequence to second node",
            ],
            "trigger_on_completion": "Continental binding cascade \u2014 multiple simultaneous breaches; entity freed or entities freed",
        },
        "one_time": True,
    },
    {
        "id": "INTERACT_06",
        "clock_a": "Enigma Crystal Hunt", "threshold_a": 12,
        "clock_b": "Frontier (General)", "threshold_b": 6,
        "effect": "FLAG",
        "flag_text": "Orcus cult recognizes Thoron's authority as obstacle; assassination or political sabotage considered",
        "one_time": True,
    },
    {
        "id": "INTERACT_07",
        "clock_a": "Doctrine Stress Test", "threshold_a": 4,
        "clock_b": "East March Unknown Tracks", "threshold_b": 3,
        "effect": "FLAG",
        "flag_text": "Patrol doctrine under stress when unknown entity approaches; misidentification risk critical",
        "one_time": True,
    },
]


def evaluate_clock_interactions(state: GameState) -> dict:
    """
    Evaluate cross-clock interaction rules per NSV-CLOCKS v1.0.
    Each rule fires ONCE when both thresholds are met.
    Effects: FLAG (add fact + log), ADV (advance clock), SPAWN (create clock).

    Called from run_day() AFTER cadence clocks advance, BEFORE clock audit.
    """
    results = {"flags": [], "advances": [], "spawns": [], "skipped": []}

    for rule in CLOCK_INTERACTION_RULES:
        rule_id = rule["id"]

        # Skip already-fired one-time rules
        if rule.get("one_time") and rule_id in state.fired_interaction_rules:
            continue

        # Resolve full clock names
        full_a = CLOCK_NAME_MAP.get(rule["clock_a"], rule["clock_a"])
        full_b = CLOCK_NAME_MAP.get(rule["clock_b"], rule["clock_b"])

        clock_a = state.get_clock(full_a)
        clock_b = state.get_clock(full_b)

        # Skip if either clock doesn't exist
        if clock_a is None or clock_b is None:
            continue

        # Check thresholds
        if clock_a.progress < rule["threshold_a"]:
            continue
        if clock_b.progress < rule["threshold_b"]:
            continue

        # ── THRESHOLDS MET — execute effect ──
        effect = rule["effect"]

        if effect == "FLAG":
            flag_text = rule["flag_text"]
            state.add_fact(f"[INTERACTION {rule_id}] {flag_text}")
            results["flags"].append({
                "rule": rule_id, "text": flag_text,
                "clock_a": full_a, "clock_b": full_b,
            })

        elif effect == "ADV":
            adv_name = CLOCK_NAME_MAP.get(rule["adv_clock"], rule["adv_clock"])
            target = state.get_clock(adv_name)
            if target and target.can_advance():
                adv_result = target.advance(
                    reason=f"Clock interaction {rule_id}: "
                           f"{rule['clock_a']} >= {rule['threshold_a']} "
                           f"AND {rule['clock_b']} >= {rule['threshold_b']}",
                    date=state.in_game_date,
                    session=state.session_id,
                )
                results["advances"].append({
                    "rule": rule_id, "clock": adv_name, "result": adv_result,
                })
                state.add_fact(f"[INTERACTION {rule_id}] Advanced {adv_name}: "
                               f"{adv_result['new']}/{target.max_progress}")

        elif effect == "SPAWN":
            spawn_def = rule["spawn_clock"]
            if state.get_clock(spawn_def["name"]) is not None:
                results["skipped"].append({
                    "rule": rule_id,
                    "reason": f"Clock '{spawn_def['name']}' already exists",
                })
                continue
            new_clock = Clock(
                name=spawn_def["name"],
                owner=spawn_def["owner"],
                progress=0,
                max_progress=spawn_def["max_progress"],
                advance_bullets=spawn_def.get("advance_bullets", []),
                halt_conditions=spawn_def.get("halt_conditions", []),
                reduce_conditions=spawn_def.get("reduce_conditions", []),
                trigger_on_completion=spawn_def.get("trigger_on_completion", ""),
                created_session=state.session_id,
            )
            state.add_clock(new_clock)
            results["spawns"].append({
                "rule": rule_id, "clock": spawn_def["name"],
            })
            state.add_fact(f"[INTERACTION {rule_id}] SPAWNED clock: "
                           f"{spawn_def['name']} (0/{spawn_def['max_progress']})")

        # Mark rule as fired
        if rule.get("one_time"):
            state.fired_interaction_rules.append(rule_id)

    return results


# ─────────────────────────────────────────────────────
# HALT CONDITION EVALUATION
# ─────────────────────────────────────────────────────

# Common stop words excluded from keyword matching
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "has", "have",
    "or", "and", "in", "of", "to", "for", "with", "that", "this",
    "day", "passes", "while", "when", "if", "not", "no", "any",
})


def evaluate_halt_conditions(state: GameState) -> list:
    """
    Check each active clock's halt_conditions against today's facts.
    If a halt condition is keyword-matched (>=60%), halt the clock.

    Called from run_day() AFTER clock interactions, BEFORE clock audit.
    """
    results = []
    facts_text = " | ".join(state.daily_facts).lower()
    facts_words = set(facts_text.split())

    for clock in state.clocks.values():
        if clock.status != "active":
            continue
        if not clock.halt_conditions:
            continue

        for condition in clock.halt_conditions:
            cond_lower = condition.lower()
            cond_keywords = set(cond_lower.split()) - _STOP_WORDS

            if not cond_keywords:
                continue

            keyword_hits = sum(1 for kw in cond_keywords if kw in facts_words)
            keyword_ratio = keyword_hits / len(cond_keywords)

            if keyword_ratio >= 0.6:
                clock.halt(reason=f"HALT condition met: '{condition}' "
                                  f"(keyword match {keyword_ratio:.0%})")
                results.append({
                    "clock": clock.name,
                    "condition": condition,
                    "ratio": keyword_ratio,
                })
                state.add_fact(f"Clock HALTED: {clock.name} \u2014 {condition}")
                break  # Only halt once per clock per day

    return results


# ─────────────────────────────────────────────────────
# CLOCK AUDIT (T&P §3.2.1)
# ─────────────────────────────────────────────────────

def _get_local_zones(state: GameState) -> set:
    """
    Return the set of zone names the PC is currently in or adjacent to.
    Adjacent = reachable via 1 crossing point from pc_zone.
    """
    local = {state.pc_zone.lower()}
    zone = state.zones.get(state.pc_zone)
    if zone:
        for cp in zone.crossing_points:
            dest = cp.get("to", "") or cp.get("destination", "")
            if dest:
                local.add(dest.lower())
    return local


def _bullet_references_remote_zone(bullet_lower: str, all_zone_names: list, local_zones: set) -> str:
    """
    Check if an ADV bullet mentions a specific zone name.
    If that zone is NOT in local_zones, return the zone name (remote).
    If the bullet doesn't reference any zone, or references a local zone, return "".

    all_zone_names must be pre-sorted longest-first so "Eastern Scarps"
    matches before "Scarps". Uses word-boundary regex to prevent
    substring false positives (e.g. zone "car" matching "scar").
    """
    for zone_name in all_zone_names:
        if re.search(r'\b' + re.escape(zone_name) + r'\b', bullet_lower, re.IGNORECASE):
            if zone_name not in local_zones:
                return zone_name
            else:
                return ""  # References a local zone — don't skip
    return ""


def clock_audit(state: GameState) -> dict:
    """
    MANDATORY CLOCK AUDIT per T&P §3.2.1-3.2.3.

    Scan ALL active clocks. For each, check ADV bullets against
    facts established this day. If unambiguously satisfied and clock
    has not already advanced today, advance once.

    CRITICAL: This is where the LLM missed ticks before.
    The deterministic engine checks EVERY clock EVERY day.

    For ADV bullets that require judgment (ambiguous), this returns
    a list of "needs_llm_review" items for Claude to adjudicate.

    Zone-aware: ADV bullets that reference a specific zone are skipped
    if the PC is not in or adjacent to that zone.
    """
    results = {
        "auto_advanced": [],       # Unambiguous — advanced automatically
        "needs_llm_review": [],    # Ambiguous — needs Claude's judgment
        "skipped": [],             # Can't advance (halted, fired, already advanced)
        "no_match": [],            # No ADV bullets matched
    }

    facts_text = " | ".join(state.daily_facts).lower()
    facts_words = set(facts_text.split())  # For whole-word matching

    # Build zone locality sets for location-specific bullet filtering
    local_zones = _get_local_zones(state)
    # Sort longest-first so "Eastern Scarps" matches before "Scarps"
    all_zone_names = sorted([z.lower() for z in state.zones.keys()],
                            key=len, reverse=True)

    for clock in state.clocks.values():
        if not clock.can_advance():
            results["skipped"].append({
                "clock": clock.name,
                "reason": f"status={clock.status}, advanced_today={clock.advanced_this_day}, "
                          f"progress={clock.progress}/{clock.max_progress}"
            })
            continue

        # Check each ADV bullet against established facts
        matched_bullets = []
        ambiguous_bullets = []

        for bullet in clock.advance_bullets:
            bullet_lower = bullet.lower()

            # Zone-aware filter: skip bullets that reference a zone
            # the PC is not in or adjacent to
            remote_zone = _bullet_references_remote_zone(bullet_lower, all_zone_names, local_zones)
            if remote_zone:
                continue  # PC is not near this zone — bullet can't fire

            # DETERMINISTIC MATCHES — things the engine can check itself
            # Whole-word keyword matching against today's facts.
            # Hardened thresholds to reduce false positives.

            match_found = False

            bullet_keywords = set(bullet_lower.split()) - _STOP_WORDS

            # Single-keyword bullets are too ambiguous for auto-advance
            if len(bullet_keywords) < 2:
                if bullet_keywords:
                    ambiguous_bullets.append({
                        "bullet": bullet,
                        "confidence": "ambiguous",
                        "keyword_ratio": 0.0,
                        "facts": state.daily_facts.copy(),
                    })
                    match_found = True
            elif bullet_keywords:
                # Whole-word matching (not substring) against facts
                keyword_hits = sum(1 for kw in bullet_keywords
                                   if kw in facts_words)
                keyword_ratio = keyword_hits / len(bullet_keywords)

                if keyword_ratio >= 0.8:  # 80%+ = auto-advance
                    matched_bullets.append({
                        "bullet": bullet,
                        "confidence": "auto",
                        "keyword_ratio": keyword_ratio,
                    })
                    match_found = True
                elif keyword_ratio >= 0.4:  # 40-80% = ambiguous
                    ambiguous_bullets.append({
                        "bullet": bullet,
                        "confidence": "ambiguous",
                        "keyword_ratio": keyword_ratio,
                        "facts": state.daily_facts.copy(),
                    })
                    match_found = True

        if matched_bullets:
            # Auto-advance on first unambiguous match
            best = matched_bullets[0]
            advance_result = clock.advance(
                reason=f"Clock audit: ADV bullet '{best['bullet']}' "
                       f"satisfied (auto, confidence={best['keyword_ratio']:.0%})",
                date=state.in_game_date,
                session=state.session_id,
            )
            results["auto_advanced"].append({
                "clock": clock.name,
                "bullet_matched": best["bullet"],
                "advance_result": advance_result,
            })
            state.add_fact(f"Clock audit advanced {clock.name}: "
                          f"{advance_result['new']}/{clock.max_progress}")

        elif ambiguous_bullets:
            results["needs_llm_review"].append({
                "clock": clock.name,
                "progress": f"{clock.progress}/{clock.max_progress}",
                "ambiguous_bullets": ambiguous_bullets,
                "daily_facts": state.daily_facts.copy(),
            })
        else:
            results["no_match"].append(clock.name)

    return results


# ─────────────────────────────────────────────────────
# ENCOUNTER GATE (T&P §4.0)
# ─────────────────────────────────────────────────────

def _matches_range(roll_total: int, range_str: str) -> bool:
    """Check if a roll total falls within a range string like '1', '1-2', '5-6'."""
    if "-" in range_str:
        parts = range_str.split("-")
        return int(parts[0]) <= roll_total <= int(parts[1])
    return roll_total == int(range_str)


def encounter_gate(state: GameState) -> dict:
    """
    Roll encounter gate per T&P §4.2: 1d6 vs Campaign_Intensity_Level.
    low=1-2 pass, medium=1-3 pass, high=1-4 pass, extreme=auto.
    If passed, roll the zone's encounter list (EL-DEF Migration schema).
    """
    roll = roll_d6("Encounter gate")
    intensity = state.campaign_intensity or "medium"
    passed = intensity_gate_check(intensity, roll["total"])

    result = {
        "gate": "encounter",
        "roll": roll,
        "intensity": intensity,
        "passed": passed,
    }

    if passed:
        # Check for EL-DEF in current zone
        el = state.encounter_lists.get(state.pc_zone)
        if el:
            encounter_roll = roll_dice(el.randomizer, f"Encounter table: {el.zone}")
            roll_total = encounter_roll["total"]

            # Find matching entry by range
            entry = None
            for e in el.entries:
                if _matches_range(roll_total, e.range):
                    entry = e
                    break

            if entry:
                has_bx = bool(entry.bx_plug)
                result["encounter"] = {
                    "roll": encounter_roll,
                    "roll_total": roll_total,
                    "range_matched": entry.range,
                    "prompt": entry.prompt,
                    "ua_cue": entry.ua_cue,
                    "bx_plug": entry.bx_plug if has_bx else None,
                }

                # BX-PLUG §2.1: Reaction roll on first NPC contact
                reaction = None
                if has_bx:
                    reaction_roll = roll_dice("2d6", "Reaction roll (BX-PLUG §2.1)")
                    rt = reaction_roll["total"]
                    if rt <= 2:
                        reaction_band = "hostile"
                    elif rt <= 5:
                        reaction_band = "unfriendly"
                    elif rt <= 8:
                        reaction_band = "neutral"
                    elif rt <= 11:
                        reaction_band = "friendly"
                    else:
                        reaction_band = "enthusiastic"
                    reaction = {
                        "roll": reaction_roll,
                        "total": rt,
                        "band": reaction_band,
                    }
                    result["encounter"]["reaction"] = reaction
                    state.add_fact(f"Reaction roll: 2d6={rt} -> {reaction_band}")

                result["llm_request"] = {
                    "type": "NARR_ENCOUNTER",
                    "context": f"Encounter in {state.pc_zone}: {entry.prompt}",
                    "bx_plug": has_bx,
                    "bx_plug_detail": entry.bx_plug if has_bx else None,
                    "reaction": reaction,
                    "ua_cue": entry.ua_cue,
                }
                state.add_fact(f"Encounter in {state.pc_zone}: {entry.prompt}")
            else:
                result["encounter"] = {"error": f"No entry for roll {roll_total} in {el.zone} table"}
        else:
            result["encounter"] = {"note": f"No EL-DEF for zone {state.pc_zone}"}
    else:
        result["note"] = f"Gate failed (rolled {roll['total']}, intensity={intensity})"

    return result


# ─────────────────────────────────────────────────────
# NPAG GATE (T&P §6.0)
# ─────────────────────────────────────────────────────

def npag_gate(state: GameState) -> dict:
    """
    Roll NPAG gate per T&P §6.1: 1d6 vs Campaign_Intensity_Level.
    low=1-2 pass, medium=1-3 pass, high=1-4 pass, extreme=auto.
    If passed, determine NPC count and flag for LLM resolution.
    """
    roll = roll_d6("NPAG gate")
    intensity = state.campaign_intensity or "medium"
    passed = intensity_gate_check(intensity, roll["total"])

    result = {
        "gate": "npag",
        "roll": roll,
        "intensity": intensity,
        "passed": passed,
    }

    if passed:
        npc_count = npag_npc_count(intensity)
        result["npc_count"] = npc_count
        result["llm_request"] = {
            "type": "NPAG",
            "npc_count": npc_count["count"],
            "context": f"Resolve {npc_count['count']} NPC agency actions",
        }
        state.add_fact(f"NPAG triggered: {npc_count['count']} NPCs act")
    else:
        result["note"] = f"Gate failed (rolled {roll['total']}, intensity={intensity})"

    return result


# ─────────────────────────────────────────────────────
# ZONE GAP CHECK (NPC/EL during T&P)
# ─────────────────────────────────────────────────────

def _zone_gap_check(state: GameState) -> dict:
    """Check for NPC/EL deficits in current zone during T&P."""
    from creative_bridge import build_npc_forge, build_el_forge

    result = {"gaps": [], "llm_requests": []}
    zone_name = state.pc_zone
    if not zone_name:
        return result

    # NPC deficit — same threshold as zone_forge (<=3)
    active_npcs = [
        n for n in state.npcs.values()
        if getattr(n, "zone", "") == zone_name
        and getattr(n, "status", "") == "active"
    ]
    if len(active_npcs) <= 3:
        deficit = max(1, 4 - len(active_npcs))
        zone_obj = state.zones.get(zone_name)
        faction_hint = getattr(zone_obj, "controlling_faction", "") if zone_obj else ""
        for _ in range(deficit):
            result["llm_requests"].append(
                build_npc_forge(state, zone=zone_name, faction_hint=faction_hint)
            )
        result["gaps"].append(
            f"NPC deficit: {len(active_npcs)} active, forging {deficit}"
        )

    # EL deficit — check existing EL-DEFs first
    if not state.encounter_lists.get(zone_name):
        result["llm_requests"].append(build_el_forge(state, zone=zone_name))
        result["gaps"].append(f"No EL-DEF for {zone_name}")

    return result


# ─────────────────────────────────────────────────────
# MAIN T&P DAY LOOP
# ─────────────────────────────────────────────────────

def run_day(state: GameState, skip_zone_gap: bool = False) -> dict:
    """
    Execute one complete T&P day.
    Returns comprehensive audit log of everything that happened.
    skip_zone_gap: True when zone_forge will handle NPC/EL deficits (travel).
    """
    # Reset per-day tracking
    state.reset_day()

    day_log = {
        "day_number": None,
        "date": None,
        "steps": [],
        "llm_requests": [],     # Collected requests for Claude
        "warnings": [],
    }

    # ── §2.3 Advance date ──
    date_result = advance_date(state)
    day_log["date"] = state.in_game_date
    day_log["steps"].append({"step": "date_advance", "result": date_result})

    # ── §3.1 Run cadence engines ──
    for engine in state.cadence_engines():
        runner = ENGINE_RUNNERS.get(engine.name)
        if runner:
            engine_result = runner(state, engine)
            day_log["steps"].append({"step": f"engine:{engine.name}", "result": engine_result})

            # Collect LLM requests
            if "llm_request" in engine_result:
                day_log["llm_requests"].append(engine_result["llm_request"])
        else:
            day_log["warnings"].append(f"No runner for engine: {engine.name}")

    # ── §3.1b Halt condition evaluation (BEFORE cadence tick) ──
    halt_results = evaluate_halt_conditions(state)
    if halt_results:
        day_log["steps"].append({
            "step": "halt_evaluation", "results": halt_results,
        })

    # ── §3.2 Advance cadence clocks ──
    cadence_results = advance_cadence_clocks(state)
    if cadence_results:
        day_log["steps"].append({"step": "cadence_clocks", "results": cadence_results})

    # ── §3.2.1 CLOCK AUDIT ──
    audit_result = clock_audit(state)
    day_log["steps"].append({"step": "clock_audit", "result": audit_result})

    # Collect LLM review requests from audit
    for review in audit_result.get("needs_llm_review", []):
        day_log["llm_requests"].append({
            "type": "CLOCK_AUDIT_REVIEW",
            "clock": review["clock"],
            "progress": review["progress"],
            "ambiguous_bullets": review["ambiguous_bullets"],
            "daily_facts": review["daily_facts"],
        })

    # ── §3.2.4 Clock interactions — AFTER audit (T&P §3.2.4) ──
    interaction_results = evaluate_clock_interactions(state)
    if (interaction_results["flags"] or interaction_results["advances"]
            or interaction_results["spawns"]):
        day_log["steps"].append({
            "step": "clock_interactions", "result": interaction_results,
        })

    # ── §4.0 Encounter gate ──
    encounter_result = encounter_gate(state)
    day_log["steps"].append({"step": "encounter_gate", "result": encounter_result})
    if "llm_request" in encounter_result:
        day_log["llm_requests"].append(encounter_result["llm_request"])

    # ── §5.0 Non-cadence PE (T&P §5.0-5.1) ──
    nc_engines = [
        e for e in state.engines.values()
        if not e.cadence and e.status == "active"
        and (e.zone_scope == state.pc_zone or e.zone_scope == "Global")
    ]
    if nc_engines:
        # Run exactly one (first eligible)
        nc_engine = nc_engines[0]
        nc_runner = ENGINE_RUNNERS.get(nc_engine.name)
        if nc_runner:
            nc_result = nc_runner(state, nc_engine)
            day_log["steps"].append({
                "step": f"non_cadence_pe:{nc_engine.name}", "result": nc_result,
            })
            if "llm_request" in nc_result:
                day_log["llm_requests"].append(nc_result["llm_request"])

    # ── §6.0 NPAG gate ──
    npag_result = npag_gate(state)
    day_log["steps"].append({"step": "npag_gate", "result": npag_result})
    if "llm_request" in npag_result:
        day_log["llm_requests"].append(npag_result["llm_request"])

    # ── §6.5 Zone gap check (NPC/EL deficits) ──
    # Skipped during travel — zone_forge handles these comprehensively
    if not skip_zone_gap:
        gap_result = _zone_gap_check(state)
        if gap_result["gaps"]:
            day_log["steps"].append({"step": "zone_gap_check", "result": gap_result})
            for req in gap_result.get("llm_requests", []):
                day_log["llm_requests"].append(req)

    # ── §6.3 Log to adjudication log ──
    state.log({
        "type": "T&P_DAY",
        "date": state.in_game_date,
        "summary": day_log,
    })

    return day_log


def run_time_and_pressure(state: GameState, days: int = 1) -> list:
    """
    Run T&P for N days. Returns list of day logs.
    Per T&P §2.0-2.2: loop from Day 1 to Day N.
    """
    # §1.3 Validate PC zone
    if not state.pc_zone:
        return [{"error": "PC_Zone is blank/unknown — STOP per T&P §1.3"}]

    all_logs = []
    for i in range(days):
        day_log = run_day(state)
        day_log["day_number"] = i + 1
        all_logs.append(day_log)

    return all_logs
