"""
MACROS Engine v3.0 — Data Models
Core data structures for the complete campaign state.
Full delta parity — every field from NSV-DELTA has a structured equivalent.

v3.0 changes (Delta Parity):
  - Zone: added threat_level, situation_summary
  - NPC: added negative_knowledge
  - PCState: added affection_summary, reputation_levels
  - GameState: added ua_log, seed_overrides, session_meta

v2.0 changes:
  - Added NPC, Faction, Relationship, Discovery, PCState dataclasses
  - Added session_summaries, unresolved_threads, losses_irreversibles
  - Added companion_detail for PARTY-DELTA replacement
  - All state is JSON-serializable for easy save/load/edit
  - Append-only history arrays on all entities for audit trail
"""

import json
import random
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


# ─────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────

class ClockStatus(str, Enum):
    ACTIVE = "active"
    HALTED = "halted"
    RETIRED = "retired"
    TRIGGER_FIRED = "trigger_fired"


class EngineStatus(str, Enum):
    ACTIVE = "active"
    DORMANT = "dormant"
    INERT = "inert"  # linked clock completed; engine runs but outputs nothing


class IntensityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


# ─────────────────────────────────────────────────────
# CLOCK
# ─────────────────────────────────────────────────────

@dataclass
class Clock:
    """A single clock with progress tracking, advance/halt/reduce conditions."""
    name: str
    owner: str                      # faction, NPC, environment, UA-XX
    progress: int = 0
    max_progress: int = 4
    status: str = "active"          # active, halted, retired, trigger_fired

    # Advance bullets — list of condition strings
    advance_bullets: list = field(default_factory=list)
    # Halt conditions
    halt_conditions: list = field(default_factory=list)
    # Reduce conditions
    reduce_conditions: list = field(default_factory=list)
    # What happens on completion
    trigger_on_completion: str = ""

    # Per-session tracking
    advanced_this_session: bool = False
    advanced_this_day: bool = False      # Reset each T&P day
    trigger_fired: bool = False
    trigger_fired_text: str = ""

    # Metadata
    visibility: str = "public"           # public, secret, restricted
    notes: str = ""
    created_session: int = 0
    last_advanced_session: int = 0
    last_advanced_date: str = ""

    # Special flags
    is_cadence: bool = False             # Advances automatically each day
    cadence_bullet: str = ""             # Which ADV bullet is the cadence one


    def can_advance(self) -> bool:
        if self.status in ("retired", "trigger_fired", "halted"):
            return False
        if self.progress >= self.max_progress:
            return False
        if self.advanced_this_day:
            return False
        return True

    def advance(self, reason: str, date: str = "", session: int = 0) -> dict:
        if not self.can_advance():
            return {"error": f"Cannot advance {self.name}: status={self.status}, "
                    f"progress={self.progress}/{self.max_progress}, "
                    f"advanced_today={self.advanced_this_day}"}

        old = self.progress
        self.progress += 1
        self.advanced_this_day = True
        self.advanced_this_session = True
        self.last_advanced_session = session
        self.last_advanced_date = date

        result = {
            "clock": self.name, "action": "advance",
            "old": old, "new": self.progress,
            "max": self.max_progress, "reason": reason, "date": date,
        }

        if self.progress >= self.max_progress:
            self.trigger_fired = True
            self.trigger_fired_text = self.trigger_on_completion
            self.status = "trigger_fired"
            result["trigger_fired"] = True
            result["trigger_text"] = self.trigger_on_completion

        return result

    def reduce(self, reason: str, amount: int = 1) -> dict:
        old = self.progress
        self.progress = max(0, self.progress - amount)
        return {"clock": self.name, "action": "reduce",
                "old": old, "new": self.progress, "reason": reason}

    def halt(self, reason: str) -> dict:
        old_status = self.status
        self.status = "halted"
        return {"clock": self.name, "action": "halt",
                "old_status": old_status, "reason": reason}

    def reset_day(self):
        self.advanced_this_day = False

    def reset_session(self):
        self.advanced_this_session = False


# ─────────────────────────────────────────────────────
# ENGINE (Procedural Engine)
# ─────────────────────────────────────────────────────

@dataclass
class Engine:
    """A procedural engine definition."""
    name: str
    version: str
    status: str = "active"

    authority_tier: str = "GLOBAL"
    registry_target: str = "NSV_DELTA_REGISTRY"  # CSEM|SSM_1A|NSV_DELTA_REGISTRY
    zone_scope: str = "Global"
    state_scope: str = ""

    cadence: bool = True
    trigger_event: str = ""
    hard_gates: list = field(default_factory=list)

    resolution_method: str = ""
    randomizer: str = ""
    outcome_mapping: dict = field(default_factory=dict)

    linked_clocks: list = field(default_factory=list)

    run_cap_per_day: int = 1
    runs_today: int = 0
    last_run_date: str = ""
    last_run_session: int = 0

    roll_history: list = field(default_factory=list)

    def check_hard_gates(self, state: 'GameState') -> tuple:
        if self.runs_today >= self.run_cap_per_day:
            return False, f"Run cap reached ({self.runs_today}/{self.run_cap_per_day})"
        return True, "Gates passed"

    def reset_day(self):
        self.runs_today = 0


# ─────────────────────────────────────────────────────
# ENCOUNTER LIST (EL-DEF)
# ─────────────────────────────────────────────────────

@dataclass
class EncounterEntry:
    """Single encounter in an encounter list (EL-DEF Migration schema)."""
    range: str                          # "1", "1-2", "5-6", "9-10"
    prompt: str                         # Encounter description
    ua_cue: bool = False                # True if tagged [UA]
    bx_plug: dict = field(default_factory=dict)  # Nullable: {type, skill, save_damage, hostile_action, stats}


@dataclass
class EncounterList:
    """Zone encounter list definition (EL-DEF Migration schema)."""
    zone: str
    randomizer: str                     # Dice expression: "1d6", "1d8", "2d6"
    fallback_priority: int = 1          # FP value
    adjacency_notes: str = ""           # Zone flavor/context
    entries: list = field(default_factory=list)  # List of EncounterEntry


# ─────────────────────────────────────────────────────
# ZONE
# ─────────────────────────────────────────────────────

@dataclass
class Zone:
    """A zone in the game world."""
    name: str
    intensity: str = "medium"
    controlling_faction: str = ""
    description: str = ""
    crossing_points: list = field(default_factory=list)
    notes: str = ""
    threat_level: str = ""              # low, moderate, high, stabilized, etc.
    situation_summary: str = ""         # Rich narrative situation description
    no_faction: bool = False            # True for wilderness zones (no faction possible)
    encounter_threshold: int = 6        # d6 roll needed to trigger encounter (default 6)


# ─────────────────────────────────────────────────────
# NPC (v2.0 — replaces delta NPC_STATE_CHANGES)
# ─────────────────────────────────────────────────────

@dataclass
class NPC:
    """A named NPC with full state tracking."""
    name: str
    zone: str = ""                      # Current zone
    status: str = "active"              # active, inactive, dead, missing
    role: str = ""                      # CNC role (e.g., "Castellan", "patrol commander")
    trait: str = ""                     # 1-2 word personality sketch
    appearance: str = ""                # Short identifying phrase
    faction: str = ""                   # Faction affiliation if any

    # Agency fields (NPAG)
    objective: str = ""
    knowledge: str = ""
    negative_knowledge: str = ""        # What this NPC does NOT know
    next_action: str = ""

    # Party tracking
    with_pc: bool = False               # Currently traveling with PC?
    is_companion: bool = False          # One of the five companions?

    # Class/level (companions)
    class_level: str = ""               # e.g. "Fighter 16", "Assassin 10"

    # BX stats (optional — populated by NPC-FORGE)
    bx_ac: int = 0
    bx_hd: int = 0
    bx_hp: int = 0
    bx_hp_max: int = 0
    bx_at: int = 0
    bx_dmg: str = ""
    bx_ml: int = 0

    # Metadata
    visibility: str = "public"
    created_session: int = 0
    last_updated_session: int = 0

    # Append-only history
    history: list = field(default_factory=list)
    # Each entry: {"session": N, "date": "...", "event": "description"}


# ─────────────────────────────────────────────────────
# COMPANION DETAIL (v2.0 — replaces PARTY-DELTA)
# ─────────────────────────────────────────────────────

@dataclass
class CompanionDetail:
    """Extended tracking for the five companions. Replaces PARTY-DELTA."""
    npc_name: str                       # Must match an NPC entry
    motivation_shift: str = ""
    loyalty_change: str = ""
    trust_in_pc: str = "unknown"        # high, moderate, low, unknown
    affection_levels: dict = field(default_factory=dict)
    # e.g. {"Thoron": "love", "Suzanne": "aversion"}
    stress_or_fatigue: str = "unknown"
    grievances: str = ""
    agency_notes: str = ""
    future_flashpoints: str = ""

    # Append-only history
    history: list = field(default_factory=list)


# ─────────────────────────────────────────────────────
# FACTION (v2.0 — replaces delta FACTION_STATE_CHANGES)
# ─────────────────────────────────────────────────────

@dataclass
class Faction:
    """A faction with state tracking."""
    name: str
    status: str = "active"              # active, inactive, destroyed, unknown
    trend: str = ""                     # arrow direction (stable, rising, declining)
    disposition: str = "unknown"        # toward PC: friendly, neutral, hostile, unknown
    last_action: str = ""               # Most recent offscreen action
    notes: str = ""

    # Metadata
    created_session: int = 0
    last_updated_session: int = 0

    # Append-only history
    history: list = field(default_factory=list)


# ─────────────────────────────────────────────────────
# RELATIONSHIP (v2.0 — replaces delta RELATIONSHIP_STATE_CHANGES)
# ─────────────────────────────────────────────────────

@dataclass
class Relationship:
    """A tracked relationship between two NPCs (or NPC and PC)."""
    id: str                             # e.g., "REL-Thoron-Valania-love-01"
    npc_a: str                          # First party name
    npc_b: str                          # Second party name
    rel_type: str = ""                  # love, friends, attraction, dislike, etc.
    visibility: str = "public"          # public, restricted, secret
    trust: str = ""                     # Current trust level
    loyalty: str = ""                   # Current loyalty level
    current_state: str = ""             # Current emotional state

    # Metadata
    created_session: int = 0
    last_updated_session: int = 0

    # Append-only history
    history: list = field(default_factory=list)


# ─────────────────────────────────────────────────────
# NPC RISK FLAG (v2.0)
# ─────────────────────────────────────────────────────

@dataclass
class NPCRiskFlag:
    """Risk flag on an NPC — potential future threat or complication."""
    npc_name: str
    risk_type: str = ""                 # betrayal, death, departure, etc.
    level: str = ""                     # low, moderate, high, critical
    triggers: str = ""                  # What would escalate this
    consequences: str = ""              # What happens if triggered
    visibility: str = "secret"
    basis: str = ""                     # Why this flag exists


# ─────────────────────────────────────────────────────
# DISCOVERY (v2.0 — replaces delta DISCOVERIES)
# ─────────────────────────────────────────────────────

@dataclass
class Discovery:
    """A discovered fact, location, or piece of intelligence."""
    id: str                             # e.g., "DISC-cairn-desecration-01"
    zone: str = ""                      # Zone where discovered (or "—")
    ua_code: str = ""                   # Linked UA code if any
    reliability: str = "uncertain"      # confirmed, uncertain, inferred, rumor
    visibility: str = "public"          # public, restricted, secret
    source: str = ""                    # How it was discovered
    info: str = ""                      # The actual discovery content
    session_discovered: int = 0


# ─────────────────────────────────────────────────────
# PC STATE (v2.0 — replaces delta PC_STATE_CHANGES)
# ─────────────────────────────────────────────────────

@dataclass
class PCState:
    """Player character state tracking."""
    name: str = "Thoron"
    goals: list = field(default_factory=list)
    psychological_state: list = field(default_factory=list)
    secrets: list = field(default_factory=list)
    reputation: str = ""
    conditions: list = field(default_factory=list)  # Venom, injuries, etc.
    equipment_notes: str = ""           # Notable gear changes
    affection_summary: str = ""         # PC-centric view of companion affections
    reputation_levels: dict = field(default_factory=dict)  # e.g. {"Caras": "1/4", "Frontier": "5/6"}

    # BX combat stats (DG-16)
    bx_ac: int = 0
    bx_hd: int = 0
    bx_hp: int = 0
    bx_hp_max: int = 0
    bx_at: int = 0
    bx_dmg: str = ""
    bx_ml: int = 0

    # Append-only history
    history: list = field(default_factory=list)


# ─────────────────────────────────────────────────────
# UNRESOLVED THREAD (v2.0)
# ─────────────────────────────────────────────────────

@dataclass
class UnresolvedThread:
    """An open narrative thread or question."""
    id: str
    zone: str = ""
    description: str = ""
    session_created: int = 0
    resolved: bool = False
    resolution: str = ""
    session_resolved: int = 0


# ─────────────────────────────────────────────────────
# GAME STATE (v2.0 — complete delta replacement)
# ─────────────────────────────────────────────────────

@dataclass
class GameState:
    """Complete game state — the structured equivalent of NSV-DELTA + PARTY-DELTA."""

    # META
    session_id: int = 0
    in_game_date: str = ""
    day_of_month: int = 23
    month: str = "Ilrym"
    pc_zone: str = ""
    campaign_intensity: str = "medium"
    season: str = "Spring"
    seasonal_pressure: str = "Feed & Seed"

    # EXISTING STATE COLLECTIONS (v1.0)
    clocks: dict = field(default_factory=dict)      # name -> Clock
    engines: dict = field(default_factory=dict)      # name -> Engine
    zones: dict = field(default_factory=dict)        # name -> Zone
    encounter_lists: dict = field(default_factory=dict)  # zone -> EncounterList

    # v2.0 STATE COLLECTIONS
    npcs: dict = field(default_factory=dict)         # name -> NPC
    companions: dict = field(default_factory=dict)   # name -> CompanionDetail
    factions: dict = field(default_factory=dict)      # name -> Faction
    relationships: dict = field(default_factory=dict) # id -> Relationship
    npc_risk_flags: list = field(default_factory=list) # list of NPCRiskFlag
    discoveries: list = field(default_factory=list)   # list of Discovery
    pc_state: Optional[PCState] = None
    unresolved_threads: list = field(default_factory=list)  # list of UnresolvedThread
    losses_irreversibles: list = field(default_factory=list)  # list of dicts
    session_summaries: dict = field(default_factory=dict)  # session_id (str) -> summary text
    divine_metaphysical: list = field(default_factory=list)  # list of dicts

    # v3.0 STATE COLLECTIONS (delta parity)
    ua_log: list = field(default_factory=list)        # list of dicts {id, status, zone, description, touched, promotion}
    seed_overrides: list = field(default_factory=list) # list of dicts {section, nature, reason, details}
    session_meta: dict = field(default_factory=dict)  # session_id (str) -> {tone_shift, pacing, next_session_pressure}

    # FACTS ESTABLISHED TODAY — used for clock audit
    daily_facts: list = field(default_factory=list)

    # Clock interaction rules that have already fired (one-time effects)
    fired_interaction_rules: list = field(default_factory=list)

    # AUDIT LOG
    adjudication_log: list = field(default_factory=list)

    # SESSION LOG
    session_log: list = field(default_factory=list)

    # ── Helpers ──

    def get_clock(self, name: str) -> Optional[Clock]:
        return self.clocks.get(name)

    def get_engine(self, name: str) -> Optional[Engine]:
        return self.engines.get(name)

    def get_npc(self, name: str) -> Optional[NPC]:
        return self.npcs.get(name)

    def get_faction(self, name: str) -> Optional[Faction]:
        return self.factions.get(name)

    def get_relationship(self, rel_id: str) -> Optional[Relationship]:
        return self.relationships.get(rel_id)

    def add_clock(self, clock: Clock):
        self.clocks[clock.name] = clock

    def add_engine(self, engine: Engine):
        self.engines[engine.name] = engine

    def add_npc(self, npc: NPC):
        self.npcs[npc.name] = npc

    def add_faction(self, faction: Faction):
        self.factions[faction.name] = faction

    def add_relationship(self, rel: Relationship):
        self.relationships[rel.id] = rel

    def add_discovery(self, disc: Discovery):
        self.discoveries.append(disc)

    def add_fact(self, fact: str):
        self.daily_facts.append(fact)

    def reset_day(self):
        self.daily_facts = []
        for clock in self.clocks.values():
            clock.reset_day()
        for engine in self.engines.values():
            engine.reset_day()

    def reset_session(self):
        for clock in self.clocks.values():
            clock.reset_session()

    def log(self, entry: dict):
        entry["date"] = self.in_game_date
        entry["session"] = self.session_id
        self.adjudication_log.append(entry)

    def active_clocks(self) -> list:
        return [c for c in self.clocks.values() if c.status == "active"]

    def cadence_clocks(self) -> list:
        return [c for c in self.active_clocks() if c.is_cadence]

    def cadence_engines(self) -> list:
        return [e for e in self.engines.values()
                if e.cadence and e.status == "active"]

    def npcs_in_zone(self, zone: str) -> list:
        return [n for n in self.npcs.values()
                if n.zone == zone and n.status == "active"]

    def companions_with_pc(self) -> list:
        return [n for n in self.npcs.values()
                if n.is_companion and n.with_pc]


# ─────────────────────────────────────────────────────
# SERIALIZATION (v2.0)
# ─────────────────────────────────────────────────────

def state_to_json(state: GameState) -> str:
    """Serialize complete game state to JSON."""
    data = {
        "meta": {
            "session_id": state.session_id,
            "in_game_date": state.in_game_date,
            "day_of_month": state.day_of_month,
            "month": state.month,
            "pc_zone": state.pc_zone,
            "campaign_intensity": state.campaign_intensity,
            "season": state.season,
            "seasonal_pressure": state.seasonal_pressure,
        },
        "clocks": {name: asdict(clock) for name, clock in state.clocks.items()},
        "engines": {name: asdict(engine) for name, engine in state.engines.items()},
        "zones": {name: asdict(zone) for name, zone in state.zones.items()},
        "encounter_lists": {
            zone: asdict(el) for zone, el in state.encounter_lists.items()
        },

        # v2.0 collections
        "npcs": {name: asdict(npc) for name, npc in state.npcs.items()},
        "companions": {name: asdict(comp) for name, comp in state.companions.items()},
        "factions": {name: asdict(fac) for name, fac in state.factions.items()},
        "relationships": {rid: asdict(rel) for rid, rel in state.relationships.items()},
        "npc_risk_flags": [asdict(rf) for rf in state.npc_risk_flags],
        "discoveries": [asdict(d) for d in state.discoveries],
        "pc_state": asdict(state.pc_state) if state.pc_state else None,
        "unresolved_threads": [asdict(t) for t in state.unresolved_threads],
        "losses_irreversibles": state.losses_irreversibles,
        "session_summaries": state.session_summaries,
        "divine_metaphysical": state.divine_metaphysical,

        # v3.0 collections (delta parity)
        "ua_log": state.ua_log,
        "seed_overrides": state.seed_overrides,
        "session_meta": state.session_meta,

        # Clock interaction tracking
        "fired_interaction_rules": state.fired_interaction_rules,

        # Logs
        "adjudication_log": state.adjudication_log,
        "session_log": state.session_log,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def state_from_json(json_str: str) -> GameState:
    """Deserialize game state from JSON. Backward-compatible with v1.0 saves."""
    data = json.loads(json_str)
    state = GameState()

    # META
    meta = data.get("meta", {})
    state.session_id = meta.get("session_id", 0)
    state.in_game_date = meta.get("in_game_date", "")
    state.day_of_month = meta.get("day_of_month", 0)
    state.month = meta.get("month", "")
    state.pc_zone = meta.get("pc_zone", "")
    state.campaign_intensity = meta.get("campaign_intensity", "medium")
    state.season = meta.get("season", "Spring")
    state.seasonal_pressure = meta.get("seasonal_pressure", "")

    # CLOCKS
    for name, cdata in data.get("clocks", {}).items():
        clock = Clock(
            name=cdata["name"], owner=cdata["owner"],
            progress=cdata["progress"], max_progress=cdata["max_progress"],
            status=cdata.get("status", "active"),
            advance_bullets=cdata.get("advance_bullets", []),
            halt_conditions=cdata.get("halt_conditions", []),
            reduce_conditions=cdata.get("reduce_conditions", []),
            trigger_on_completion=cdata.get("trigger_on_completion", ""),
            advanced_this_session=cdata.get("advanced_this_session", False),
            advanced_this_day=cdata.get("advanced_this_day", False),
            trigger_fired=cdata.get("trigger_fired", False),
            trigger_fired_text=cdata.get("trigger_fired_text", ""),
            visibility=cdata.get("visibility", "public"),
            notes=cdata.get("notes", ""),
            created_session=cdata.get("created_session", 0),
            last_advanced_session=cdata.get("last_advanced_session", 0),
            last_advanced_date=cdata.get("last_advanced_date", ""),
            is_cadence=cdata.get("is_cadence", False),
            cadence_bullet=cdata.get("cadence_bullet", ""),
        )
        state.clocks[name] = clock

    # ENGINES
    for name, edata in data.get("engines", {}).items():
        engine = Engine(
            name=edata["name"], version=edata["version"],
            status=edata.get("status", "active"),
            authority_tier=edata.get("authority_tier", "GLOBAL"),
            zone_scope=edata.get("zone_scope", "Global"),
            state_scope=edata.get("state_scope", ""),
            cadence=edata.get("cadence", True),
            trigger_event=edata.get("trigger_event", ""),
            hard_gates=edata.get("hard_gates", []),
            resolution_method=edata.get("resolution_method", ""),
            randomizer=edata.get("randomizer", ""),
            outcome_mapping=edata.get("outcome_mapping", {}),
            linked_clocks=edata.get("linked_clocks", []),
            run_cap_per_day=edata.get("run_cap_per_day", 1),
            runs_today=edata.get("runs_today", 0),
            last_run_date=edata.get("last_run_date", ""),
            last_run_session=edata.get("last_run_session", 0),
            roll_history=edata.get("roll_history", []),
        )
        state.engines[name] = engine

    # ZONES
    for name, zdata in data.get("zones", {}).items():
        zone = Zone(
            name=zdata["name"],
            intensity=zdata.get("intensity", "medium"),
            controlling_faction=zdata.get("controlling_faction", ""),
            description=zdata.get("description", ""),
            crossing_points=zdata.get("crossing_points", []),
            notes=zdata.get("notes", ""),
            threat_level=zdata.get("threat_level", ""),
            situation_summary=zdata.get("situation_summary", ""),
            no_faction=zdata.get("no_faction", False),
            encounter_threshold=zdata.get("encounter_threshold", 6),
        )
        state.zones[name] = zone

    # ENCOUNTER LISTS (EL-DEF Migration schema)
    for zone_name, eldata in data.get("encounter_lists", {}).items():
        entries = []
        for edata in eldata.get("entries", []):
            entries.append(EncounterEntry(
                range=edata.get("range", "1"),
                prompt=edata.get("prompt", ""),
                ua_cue=edata.get("ua_cue", False),
                bx_plug=edata.get("bx_plug", {}),
            ))
        state.encounter_lists[zone_name] = EncounterList(
            zone=eldata.get("zone", zone_name),
            randomizer=eldata.get("randomizer", "1d6"),
            fallback_priority=eldata.get("fallback_priority", 1),
            adjacency_notes=eldata.get("adjacency_notes", ""),
            entries=entries,
        )

    # NPCs (v2.0)
    for name, ndata in data.get("npcs", {}).items():
        npc = NPC(
            name=ndata["name"],
            zone=ndata.get("zone", ""),
            status=ndata.get("status", "active"),
            role=ndata.get("role", ""),
            trait=ndata.get("trait", ""),
            appearance=ndata.get("appearance", ""),
            faction=ndata.get("faction", ""),
            objective=ndata.get("objective", ""),
            knowledge=ndata.get("knowledge", ""),
            negative_knowledge=ndata.get("negative_knowledge", ""),
            next_action=ndata.get("next_action", ""),
            with_pc=ndata.get("with_pc", False),
            is_companion=ndata.get("is_companion", False),
            class_level=ndata.get("class_level", ""),
            bx_ac=ndata.get("bx_ac", 0),
            bx_hd=ndata.get("bx_hd", 0),
            bx_hp=ndata.get("bx_hp", 0),
            bx_hp_max=ndata.get("bx_hp_max", 0),
            bx_at=ndata.get("bx_at", 0),
            bx_dmg=ndata.get("bx_dmg", ""),
            bx_ml=ndata.get("bx_ml", 0),
            visibility=ndata.get("visibility", "public"),
            created_session=ndata.get("created_session", 0),
            last_updated_session=ndata.get("last_updated_session", 0),
            history=ndata.get("history", []),
        )
        state.npcs[name] = npc

    # COMPANIONS (v2.0)
    for name, cdata in data.get("companions", {}).items():
        comp = CompanionDetail(
            npc_name=cdata["npc_name"],
            motivation_shift=cdata.get("motivation_shift", ""),
            loyalty_change=cdata.get("loyalty_change", ""),
            trust_in_pc=cdata.get("trust_in_pc", "unknown"),
            affection_levels=cdata.get("affection_levels", {}),
            stress_or_fatigue=cdata.get("stress_or_fatigue", "unknown"),
            grievances=cdata.get("grievances", ""),
            agency_notes=cdata.get("agency_notes", ""),
            future_flashpoints=cdata.get("future_flashpoints", ""),
            history=cdata.get("history", []),
        )
        state.companions[name] = comp

    # FACTIONS (v2.0)
    for name, fdata in data.get("factions", {}).items():
        fac = Faction(
            name=fdata["name"],
            status=fdata.get("status", "active"),
            trend=fdata.get("trend", ""),
            disposition=fdata.get("disposition", "unknown"),
            last_action=fdata.get("last_action", ""),
            notes=fdata.get("notes", ""),
            created_session=fdata.get("created_session", 0),
            last_updated_session=fdata.get("last_updated_session", 0),
            history=fdata.get("history", []),
        )
        state.factions[name] = fac

    # RELATIONSHIPS (v2.0)
    for rid, rdata in data.get("relationships", {}).items():
        rel = Relationship(
            id=rdata["id"],
            npc_a=rdata.get("npc_a", ""),
            npc_b=rdata.get("npc_b", ""),
            rel_type=rdata.get("rel_type", ""),
            visibility=rdata.get("visibility", "public"),
            trust=rdata.get("trust", ""),
            loyalty=rdata.get("loyalty", ""),
            current_state=rdata.get("current_state", ""),
            created_session=rdata.get("created_session", 0),
            last_updated_session=rdata.get("last_updated_session", 0),
            history=rdata.get("history", []),
        )
        state.relationships[rid] = rel

    # NPC RISK FLAGS (v2.0)
    for rfdata in data.get("npc_risk_flags", []):
        rf = NPCRiskFlag(
            npc_name=rfdata["npc_name"],
            risk_type=rfdata.get("risk_type", ""),
            level=rfdata.get("level", ""),
            triggers=rfdata.get("triggers", ""),
            consequences=rfdata.get("consequences", ""),
            visibility=rfdata.get("visibility", "secret"),
            basis=rfdata.get("basis", ""),
        )
        state.npc_risk_flags.append(rf)

    # DISCOVERIES (v2.0)
    for ddata in data.get("discoveries", []):
        disc = Discovery(
            id=ddata["id"],
            zone=ddata.get("zone", ""),
            ua_code=ddata.get("ua_code", ""),
            reliability=ddata.get("reliability", ddata.get("certainty", "uncertain")),
            visibility=ddata.get("visibility", "public"),
            source=ddata.get("source", ""),
            info=ddata.get("info", ""),
            session_discovered=ddata.get("session_discovered", 0),
        )
        state.discoveries.append(disc)

    # PC STATE (v2.0)
    pcdata = data.get("pc_state")
    if pcdata:
        state.pc_state = PCState(
            name=pcdata.get("name", "Thoron"),
            goals=pcdata.get("goals", []),
            psychological_state=pcdata.get("psychological_state", []),
            secrets=pcdata.get("secrets", []),
            reputation=pcdata.get("reputation", ""),
            conditions=pcdata.get("conditions", []),
            equipment_notes=pcdata.get("equipment_notes", ""),
            affection_summary=pcdata.get("affection_summary", ""),
            reputation_levels=pcdata.get("reputation_levels", {}),
            bx_ac=pcdata.get("bx_ac", 0),
            bx_hd=pcdata.get("bx_hd", 0),
            bx_hp=pcdata.get("bx_hp", 0),
            bx_hp_max=pcdata.get("bx_hp_max", 0),
            bx_at=pcdata.get("bx_at", 0),
            bx_dmg=pcdata.get("bx_dmg", ""),
            bx_ml=pcdata.get("bx_ml", 0),
            history=pcdata.get("history", []),
        )

    # UNRESOLVED THREADS (v2.0)
    for tdata in data.get("unresolved_threads", []):
        thread = UnresolvedThread(
            id=tdata["id"],
            zone=tdata.get("zone", ""),
            description=tdata.get("description", ""),
            session_created=tdata.get("session_created", 0),
            resolved=tdata.get("resolved", False),
            resolution=tdata.get("resolution", ""),
            session_resolved=tdata.get("session_resolved", 0),
        )
        state.unresolved_threads.append(thread)

    # SIMPLE COLLECTIONS (v2.0)
    state.losses_irreversibles = data.get("losses_irreversibles", [])
    state.session_summaries = data.get("session_summaries", {})
    state.divine_metaphysical = data.get("divine_metaphysical", [])

    # v3.0 COLLECTIONS (delta parity)
    state.ua_log = data.get("ua_log", [])
    state.seed_overrides = data.get("seed_overrides", [])
    state.session_meta = data.get("session_meta", {})

    # Clock interaction tracking
    state.fired_interaction_rules = data.get("fired_interaction_rules", [])

    # LOGS
    state.adjudication_log = data.get("adjudication_log", [])
    state.session_log = data.get("session_log", [])

    return state
