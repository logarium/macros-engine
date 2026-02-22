"""
MACROS Engine v4.0 — Game Loop (DG-10)
The outer loop. The engine owns the game. Claude provides creative atoms.

State machine:
  IDLE            -> Player is in a zone. UI shows CPs. Waiting for input.
  TRAVEL          -> Player picked a CP. Engine validates, calcs time, sets zone.
  TIME_PRESSURE   -> Engine runs T&P for N days. Deterministic.
  AWAIT_CREATIVE  -> Creative requests pending. Waiting for Claude via MCP.
  NARRATE         -> Display narration and updated state. Transition to IDLE.
"""

import json
import os
import glob
from enum import Enum
from datetime import datetime
from dataclasses import dataclass, field

from models import GameState, state_to_json, state_from_json
from engine import run_day
from travel import get_crossing_points, execute_travel, validate_travel
from creative_bridge import (
    CreativeQueue, CreativeRequest, CreativeResponse,
    build_narr_arrival, build_narr_encounter, build_clock_audit,
    build_npag, build_session_summary, build_narr_combat_end,
    build_rumor, build_player_input, reset_request_counter,
    build_narr_time_passage,
    # DG-17 forge builders
    build_npc_forge, build_el_forge, build_fac_forge,
    build_can_forge, build_cl_forge, build_pe_forge, build_ua_forge,
    build_zone_expansion,
)
from combat import (
    CombatState, init_combat, check_combat_end,
    resolve_round_attack, resolve_round_flee,
    apply_combat_results,
)
from zone_forge import run_zone_forge
from report import generate_session_report


class GamePhase(str, Enum):
    IDLE = "idle"
    TRAVEL = "travel"
    TIME_PRESSURE = "time_pressure"
    AWAIT_CREATIVE = "await_creative"
    NARRATE = "narrate"
    IN_COMBAT = "in_combat"          # DG-16: BX-PLUG combat active


class GameLoop:
    """
    Central game state machine. The engine that drives everything.
    The web server and MCP server both interact with this object.
    """

    def __init__(self):
        self.state: GameState = None
        self.phase: GamePhase = GamePhase.IDLE
        self.creative_queue: CreativeQueue = CreativeQueue()
        self.narration_buffer: list[dict] = []  # [{type, text, timestamp}]
        self.action_log: list[dict] = []        # Mechanical log entries
        self.last_travel: dict = None            # Result of most recent travel
        self.last_tp_logs: list[dict] = []       # T&P day logs from last run
        self.combat_state: CombatState = None    # DG-16: ephemeral combat state
        self._pending_combat_data: dict = None   # DG-16: bx_plug data awaiting combat
        self.active_mode: str = None              # DG-22: INTENS, INTIM, INVESTIG, or None

        # Callbacks — the web layer registers these to push updates
        self._on_phase_change = None
        self._on_state_update = None
        self._on_narration = None
        self._on_log_entry = None

    # ─────────────────────────────────────────────────
    # SHARED PENDING FILE (GameLoop → MCP server v3)
    # ─────────────────────────────────────────────────

    def _pending_file_path(self) -> str:
        data_dir = getattr(self, "_data_dir",
                           os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
        return os.path.join(data_dir, "pending_creative.json")

    def _write_pending_file(self):
        """Write current creative_queue to shared file so MCP server v3 can read it."""
        if self.creative_queue.is_empty():
            return
        try:
            batch = self.creative_queue.get_pending_batch()
            payload = {
                "requests": batch.get("requests", []),
                "state_summary": {
                    "session_id": self.state.session_id if self.state else "",
                    "date": self.state.in_game_date if self.state else "",
                    "zone": self.state.pc_zone if self.state else "",
                    "season": self.state.season if self.state else "",
                },
                "day_logs": [{k: v for k, v in dl.items() if k != "llm_requests"}
                             for dl in (self.last_tp_logs or [])],
                "timestamp": datetime.now().isoformat(),
            }
            path = self._pending_file_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self._log_action("ERROR", f"Failed to write pending file: {e}")

    def _clear_pending_file(self):
        """Remove the shared pending file after responses are consumed."""
        path = self._pending_file_path()
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    # ─────────────────────────────────────────────────
    # PLAYER INPUT (Engine Chat — creative queue)
    # ─────────────────────────────────────────────────

    def receive_player_input(self, intent: str) -> dict:
        """Player types in-character intent via chat panel.
        Routes through creative queue like RUMOR — same pipe, same workflow."""
        if not intent or not intent.strip():
            return {"success": False, "error": "Empty input"}
        if not self.state:
            return {"success": False, "error": "No state loaded"}
        if self.phase != GamePhase.IDLE:
            return {"success": False,
                    "error": f"Cannot submit input during {self.phase.value} phase"}

        # Show player's message in narration immediately
        self.narration_buffer.append({
            "type": "PLAYER_INPUT",
            "text": intent,
            "timestamp": datetime.now().isoformat(),
        })

        # Queue as creative request
        req = build_player_input(self.state, intent, active_mode=self.active_mode)
        self.creative_queue.enqueue(req)
        self._write_pending_file()
        self._set_phase(GamePhase.AWAIT_CREATIVE)
        self._log_action("CHAT", f"Player: {intent[:80]}")

        return {
            "success": True,
            "request_id": req.id,
            "pending": self.creative_queue.pending_count(),
        }

    # ─────────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────────

    def init(self, data_dir: str = None):
        """Load state and prepare for play."""
        if data_dir is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "data"
            )
        self._data_dir = data_dir
        self.state = self._auto_load(data_dir)
        self._set_phase(GamePhase.IDLE)
        self._log_action("SESSION", f"Engine started. Session {self.state.session_id}. "
                         f"Zone: {self.state.pc_zone}, Date: {self.state.in_game_date}")

    def _auto_load(self, data_dir: str) -> GameState:
        """Load the most recent save, or fall back to default state."""
        if os.path.isdir(data_dir):
            saves = sorted(
                glob.glob(os.path.join(data_dir, "save_*.json")) +
                glob.glob(os.path.join(data_dir, "Session *.json")),
                key=os.path.getmtime, reverse=True,
            )
            for save_path in saves:
                try:
                    with open(save_path, "r", encoding="utf-8") as f:
                        state = state_from_json(f.read())
                    self._backfill_crossing_points(state)
                    self._backfill_companion_stats(state)
                    self._backfill_pc_stats(state)
                    self._backfill_encounter_lists(state)
                    self._log_action("SESSION", f"Loaded: {os.path.basename(save_path)}")
                    return state
                except Exception as e:
                    self._log_action("SESSION",
                                     f"Failed to load {os.path.basename(save_path)}: {e}")
                    continue

        from campaign_state import load_gammaria_state
        self._log_action("SESSION", "Loaded default state (Session 7)")
        return load_gammaria_state()

    def _backfill_crossing_points(self, state: GameState):
        """
        Always apply canonical CPs from campaign_state.
        CPs are structural map data, not runtime state — the reference
        file is always authoritative.
        """
        from campaign_state import load_gammaria_state
        reference = load_gammaria_state()
        for zone_name, ref_zone in reference.zones.items():
            if ref_zone.crossing_points:
                if zone_name in state.zones:
                    state.zones[zone_name].crossing_points = ref_zone.crossing_points
                else:
                    state.zones[zone_name] = ref_zone

    def _backfill_companion_stats(self, state: GameState):
        """
        Backfill companion class/level and BX stats from PARTY-SEED data.
        Saves created before these fields existed will have zeros.
        """
        COMPANION_STATS = {
            "Valania Lorethor": {
                "class_level": "Assassin 10",
                "bx_ac": 21, "bx_hd": 10, "bx_hp": 60, "bx_hp_max": 60,
                "bx_at": 10, "bx_dmg": "1d8+8", "bx_ml": 10,
            },
            "Suzanne of Corlaine": {
                "class_level": "Anti-Paladin 7",
                "bx_ac": 19, "bx_hd": 7, "bx_hp": 70, "bx_hp_max": 70,
                "bx_at": 16, "bx_dmg": "1d8+10", "bx_ml": 12,
            },
            "Lithoe Wano-Kan": {
                "class_level": "Wizard 10",
                "bx_ac": 25, "bx_hd": 10, "bx_hp": 40, "bx_hp_max": 40,
                "bx_at": 5, "bx_dmg": "1d6+2", "bx_ml": 8,
            },
            "Father Lalholm": {
                "class_level": "Reaver 11",
                "bx_ac": 26, "bx_hd": 11, "bx_hp": 75, "bx_hp_max": 75,
                "bx_at": 8, "bx_dmg": "1d6+2", "bx_ml": 10,
            },
            "Guldur Emeldyr": {
                "class_level": "Fighter 8",
                "bx_ac": 23, "bx_hd": 8, "bx_hp": 80, "bx_hp_max": 80,
                "bx_at": 11, "bx_dmg": "1d8+10", "bx_ml": 9,
            },
        }
        for name, stats in COMPANION_STATS.items():
            npc = state.npcs.get(name)
            if npc:
                if not npc.class_level:
                    npc.class_level = stats["class_level"]
                for field in ("bx_ac", "bx_hd", "bx_hp", "bx_hp_max", "bx_at", "bx_dmg", "bx_ml"):
                    if not getattr(npc, field):
                        setattr(npc, field, stats[field])

    def _backfill_pc_stats(self, state: GameState):
        """Backfill Thoron's BX combat stats onto PCState (DG-16)."""
        if state.pc_state and not state.pc_state.bx_ac:
            state.pc_state.bx_ac = 30
            state.pc_state.bx_hd = 16
            state.pc_state.bx_hp = 131
            state.pc_state.bx_hp_max = 131
            state.pc_state.bx_at = 27
            state.pc_state.bx_dmg = "1d8+15"
            state.pc_state.bx_ml = 12

    def _backfill_encounter_lists(self, state: GameState):
        """Seed encounter_lists from NSV-ENGINES.txt for zones that lack them."""
        engines_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "docs", "NSV-ENGINES.txt"
        )
        if not os.path.exists(engines_path):
            return
        try:
            from parse_el_defs import extract_el_def_blocks, parse_block
            from models import EncounterList, EncounterEntry
            with open(engines_path, "r", encoding="utf-8") as f:
                raw_blocks = extract_el_def_blocks(f.readlines())
            seeded = 0
            for block_lines in raw_blocks:
                parsed = parse_block(block_lines)
                if not parsed:
                    continue
                zone = parsed["zone"]
                if zone in state.encounter_lists:
                    continue  # Don't overwrite save data
                entries = []
                for e in parsed["entries"]:
                    entries.append(EncounterEntry(
                        range=e["range"],
                        prompt=e["prompt"],
                        ua_cue=e.get("ua_cue", False),
                        bx_plug=e.get("bx_plug", {}),
                    ))
                state.encounter_lists[zone] = EncounterList(
                    zone=zone,
                    randomizer=parsed["randomizer"],
                    fallback_priority=parsed.get("fallback_priority", 1),
                    adjacency_notes=parsed.get("adjacency_notes", ""),
                    entries=entries,
                )
                seeded += 1
            if seeded:
                self._log_action("SESSION",
                                 f"EL-DEF backfill: seeded {seeded} encounter list(s)")
        except Exception as e:
            self._log_action("SESSION", f"EL-DEF backfill failed: {e}")

    # ─────────────────────────────────────────────────
    # PHASE TRANSITIONS
    # ─────────────────────────────────────────────────

    def _set_phase(self, phase: GamePhase):
        old = self.phase
        self.phase = phase
        if self._on_phase_change and old != phase:
            self._on_phase_change(phase, self._build_phase_data())

    def _build_phase_data(self) -> dict:
        """Data payload for the current phase."""
        data = {
            "phase": self.phase.value,
            "zone": self.state.pc_zone if self.state else "",
            "date": self.state.in_game_date if self.state else "",
            "session_id": self.state.session_id if self.state else 0,
        }
        if self.phase == GamePhase.IDLE:
            data["crossing_points"] = get_crossing_points(self.state)
        elif self.phase == GamePhase.AWAIT_CREATIVE:
            data["pending_count"] = self.creative_queue.pending_count()
            data["pending_types"] = self.creative_queue.pending_types()
        elif self.phase == GamePhase.IN_COMBAT:
            data["combat"] = (self.combat_state.to_ui_dict()
                              if self.combat_state else {})
        return data

    # ─────────────────────────────────────────────────
    # PLAYER ACTIONS
    # ─────────────────────────────────────────────────

    def travel_to(self, destination: str) -> dict:
        """
        Player clicked a CP. Execute the full travel -> T&P -> creative cycle.
        Returns a result dict with success/error info.
        """
        if self.phase != GamePhase.IDLE:
            return {"success": False, "error": f"Cannot travel during {self.phase.value} phase"}

        if not self.state.pc_zone:
            return {"success": False, "error": "PC zone is not set"}

        # ── TRAVEL ──
        self._set_phase(GamePhase.TRAVEL)
        travel_result = execute_travel(self.state, destination)

        if not travel_result["success"]:
            self._set_phase(GamePhase.IDLE)
            return travel_result

        self.last_travel = travel_result
        self._log_action("TRAVEL",
                         f"{travel_result['old_zone']} -> {travel_result['new_zone']} "
                         f"via {travel_result['cp_name']} ({travel_result['days_traveled']}d)")

        # ── TIME & PRESSURE ──
        self._set_phase(GamePhase.TIME_PRESSURE)
        days = travel_result["days_traveled"]
        reset_request_counter()

        all_day_logs = []
        all_llm_requests = []

        for i in range(days):
            day_log = run_day(self.state)
            day_log["day_number"] = i + 1
            all_day_logs.append(day_log)

            # Collect raw LLM requests from engine and convert to CreativeRequests
            for req in day_log.get("llm_requests", []):
                creative_req = self._convert_engine_request(req)
                if creative_req:
                    all_llm_requests.append(creative_req)

            # Log T&P actions
            self._log_tp_day(day_log)

        self.last_tp_logs = all_day_logs

        # ── ZONE-FORGE on arrival (DG-13) ──
        forge_result = run_zone_forge(self.state)
        zone_forge_requests = forge_result.get("forge_requests", [])

        # Log With_PC cohesion moves
        for move in forge_result.get("with_pc_moved", []):
            self._log_action("WITH_PC", f"Cohesion: {move}")

        for gap in forge_result.get("gaps", []):
            self._log_action("ZONE_FORGE",
                             f"Gap in {self.state.pc_zone}: {gap}")

        if zone_forge_requests:
            self._log_action("ZONE_FORGE",
                             f"{len(zone_forge_requests)} forge requests "
                             f"for {self.state.pc_zone}")

        # Always request arrival narration — include travel context
        travel_info = {
            "old_zone": travel_result.get("old_zone", ""),
            "cp_name": travel_result.get("cp_name", ""),
            "cp_tag": travel_result.get("cp_tag", ""),
            "days_traveled": travel_result.get("days_traveled", 1),
            "is_eventful": travel_result.get("is_eventful", False),
        }
        arrival_req = build_narr_arrival(self.state, active_mode=self.active_mode, travel_info=travel_info)
        all_llm_requests.append(arrival_req)

        # ── QUEUE CREATIVE REQUESTS ──
        # Forge requests go FIRST so state_changes apply before narration
        combined = zone_forge_requests + all_llm_requests

        if combined:
            self.creative_queue.clear()
            self.creative_queue.enqueue_many(combined)
            self._write_pending_file()
            self._set_phase(GamePhase.AWAIT_CREATIVE)
            self._log_action("CREATIVE",
                             f"{len(combined)} requests queued for Claude"
                             + (f" ({len(zone_forge_requests)} forge"
                                f" + {len(all_llm_requests)} T&P/narr)"
                                if zone_forge_requests else ""))
        else:
            self._set_phase(GamePhase.IDLE)

        # Auto-save after travel + T&P
        self._auto_save()

        return {
            "success": True,
            "travel": travel_result,
            "days_run": days,
            "creative_pending": self.creative_queue.pending_count(),
        }

    def rest_days(self, days: int) -> dict:
        """Player voluntarily rests — runs T&P for N days without travel."""
        if self.phase != GamePhase.IDLE:
            return {"success": False,
                    "error": f"Cannot rest during {self.phase.value} phase"}
        if not self.state:
            return {"success": False, "error": "No state loaded"}
        if days < 1 or days > 30:
            return {"success": False, "error": "Days must be 1-30"}

        self._set_phase(GamePhase.TIME_PRESSURE)
        reset_request_counter()

        all_day_logs = []
        all_llm_requests = []

        for i in range(days):
            day_log = run_day(self.state)
            day_log["day_number"] = i + 1
            all_day_logs.append(day_log)

            for req in day_log.get("llm_requests", []):
                creative_req = self._convert_engine_request(req)
                if creative_req:
                    all_llm_requests.append(creative_req)

            self._log_tp_day(day_log)

        self.last_tp_logs = all_day_logs
        self._log_action("REST", f"Rested {days} day(s) in {self.state.pc_zone}")

        # Always request time passage narration for rest days
        time_passage_req = build_narr_time_passage(
            self.state,
            days_passed=days,
            day_logs=all_day_logs,
            active_mode=self.active_mode,
        )
        all_llm_requests.append(time_passage_req)

        if all_llm_requests:
            self.creative_queue.clear()
            self.creative_queue.enqueue_many(all_llm_requests)
            self._write_pending_file()
            self._set_phase(GamePhase.AWAIT_CREATIVE)
            self._log_action("CREATIVE",
                             f"{len(all_llm_requests)} requests queued for Claude")
        else:
            self._set_phase(GamePhase.IDLE)

        self._auto_save()

        return {
            "success": True,
            "days_run": days,
            "creative_pending": self.creative_queue.pending_count(),
        }

    def receive_creative_response(self, response_json: str) -> dict:
        """
        Claude submitted creative content via MCP.
        Parse, validate, apply to state, advance to NARRATE.
        """
        if self.phase != GamePhase.AWAIT_CREATIVE:
            return {"success": False,
                    "error": f"Not awaiting creative content (phase: {self.phase.value})"}

        try:
            responses = self.creative_queue.submit_response(response_json)
        except Exception as first_error:
            # DG-23: Retry once, then flag for player ruling
            self._log_action("ERROR", f"Parse failure (retrying): {first_error}")
            try:
                responses = self.creative_queue.submit_response(response_json)
            except Exception as second_error:
                self._log_action("ERROR", f"Parse failure (giving up): {second_error}")
                return {"success": False,
                        "error": f"Failed to parse response after retry: {second_error}",
                        "retry_attempted": True}

        # Apply state changes
        log_entries = self.creative_queue.apply_responses(self.state)

        # Extract narration and handle special response types
        for resp in responses:
            # All responses with content display in the chat window
            if resp.content and resp.type != "SESSION_SUMMARY":
                display_type = resp.type
                if resp.type == "PLAYER_INPUT":
                    display_type = "NARR_PLAYER_RESPONSE"
                self.narration_buffer.append({
                    "type": display_type,
                    "text": resp.content,
                    "timestamp": datetime.now().isoformat(),
                })
                if self._on_narration:
                    self._on_narration(display_type, resp.content)

            if resp.type == "SESSION_SUMMARY" and resp.content:
                # Store session summary (DG-19 ENDS)
                sid_str = str(self.state.session_id)
                self.state.session_summaries[sid_str] = resp.content
                self._log_action("SESSION",
                                 f"Session {sid_str} summary stored "
                                 f"({len(resp.content)} chars)")
                # Generate HTML report
                report_html = generate_session_report(
                    self.state, self.state.session_id)
                report_filename = f"Session_{self.state.session_id}_Report.html"
                report_path = os.path.join(self._data_dir, report_filename)
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report_html)
                self._log_action("REPORT",
                                 f"HTML report saved: {report_filename}")
                # Final save with summary included
                self._auto_save()

            elif resp.type.endswith("_FORGE") or resp.type == "ZONE_EXPANSION":
                # DG-17: Forge responses — state_changes applied above
                summary = resp.content[:80] if resp.content else "no content"
                self._log_action("FORGE",
                                 f"[{resp.type}] applied — {summary}")

        # Log applied changes
        for entry in log_entries:
            if "content_preview" in entry:
                self._log_action("CREATIVE", f"[{entry['type']}] {entry['content_preview']}")
            elif entry.get("applied") == "clock_advance":
                r = entry["result"]
                self._log_action("CLOCK_ADVANCE",
                                 f"{r['clock']}: {r['old']}->{r['new']}")
            elif entry.get("applied") == "fact":
                self._log_action("FACT", entry.get("text", ""))
            # DG-17 forge state change logging
            elif entry.get("applied") == "npc_create":
                self._log_action("NPC_CREATE",
                                 f"{entry.get('npc', '?')} in {entry.get('zone', '?')}")
            elif entry.get("applied") == "el_create":
                self._log_action("EL_CREATE",
                                 f"{entry.get('zone', '?')} ({entry.get('entry_count', 0)} entries)")
            elif entry.get("applied") in ("faction_create", "faction_update"):
                self._log_action("FACTION",
                                 f"[{entry['applied']}] {entry.get('faction', '?')}")
            elif entry.get("applied") == "clock_create":
                self._log_action("CLOCK_CREATE",
                                 f"{entry.get('clock', '?')} (max {entry.get('max', '?')})")
            elif entry.get("applied") == "companion_create":
                self._log_action("COMPANION",
                                 f"Created companion detail: {entry.get('npc', '?')}")
            elif entry.get("applied") == "pe_create":
                self._log_action("PE_CREATE",
                                 f"Engine: {entry.get('engine', '?')} ({entry.get('zone_scope', '?')})")
            elif entry.get("applied") == "discovery_create":
                self._log_action("DISCOVERY",
                                 f"{entry.get('id', '?')} in {entry.get('zone', '?')}")
            elif entry.get("applied") == "thread_create":
                self._log_action("THREAD",
                                 f"{entry.get('id', '?')} in {entry.get('zone', '?')}")
            elif entry.get("applied") == "ua_create":
                self._log_action("UA",
                                 f"{entry.get('ua_id', '?')} in {entry.get('zone', '?')}")
            elif entry.get("applied") == "zone_create":
                self._log_action("ZONE_CREATE",
                                 f"New zone: {entry.get('zone', '?')}")
            elif entry.get("applied") == "zone_update":
                self._log_action("ZONE_UPDATE",
                                 f"Updated: {entry.get('zone', '?')}")
            elif entry.get("error"):
                self._log_action("ERROR",
                                 f"[{entry.get('applied', '?')}] {entry['error']}")

        self.creative_queue.clear_pending()
        self._clear_pending_file()
        self._auto_save()

        # DG-16: If pending combat, transition to IN_COMBAT instead of IDLE
        if self._pending_combat_data:
            try:
                self.combat_state = init_combat(
                    self.state,
                    self._pending_combat_data["bx_plug"],
                    self._pending_combat_data["encounter_prompt"],
                )
                self._pending_combat_data = None
                self._set_phase(GamePhase.IN_COMBAT)
                self._log_action("COMBAT",
                                 f"Combat started: "
                                 f"{self.combat_state.encounter_prompt[:60]}")
                return {
                    "success": True,
                    "responses_applied": len(responses),
                    "log_entries": len(log_entries),
                    "call_count": self.creative_queue.call_count,
                    "combat_started": True,
                }
            except Exception as e:
                self._log_action("ERROR", f"Failed to start combat: {e}")
                self._pending_combat_data = None

        # Transition
        self._set_phase(GamePhase.IDLE)

        return {
            "success": True,
            "responses_applied": len(responses),
            "log_entries": len(log_entries),
            "call_count": self.creative_queue.call_count,
        }

    # ─────────────────────────────────────────────────
    # MANUAL FORGE TRIGGER (FORGE TAB)
    # ─────────────────────────────────────────────────

    _FORGE_DISPATCH = {
        "NPC_FORGE":  lambda self, p: build_npc_forge(
            self.state, p.get("zone", self.state.pc_zone),
            role_hint=p.get("role_hint", ""),
            faction_hint=p.get("faction_hint", "")),
        "EL_FORGE":   lambda self, p: build_el_forge(
            self.state, p.get("zone", self.state.pc_zone)),
        "FAC_FORGE":  lambda self, p: build_fac_forge(
            self.state, faction_name=p.get("faction_name", ""),
            zone_hint=p.get("zone_hint", "")),
        "CL_FORGE":   lambda self, p: build_cl_forge(
            self.state, owner=p.get("owner", ""),
            trigger_context=p.get("trigger_context", "")),
        "CAN_FORGE":  lambda self, p: build_can_forge(
            self.state, zone=p.get("zone", self.state.pc_zone),
            trigger=p.get("trigger", "manual")),
        "PE_FORGE":   lambda self, p: build_pe_forge(
            self.state, engine_name=p.get("engine_name", ""),
            zone_scope=p.get("zone_scope", ""),
            trigger_event=p.get("trigger_event", "")),
        "UA_FORGE":   lambda self, p: build_ua_forge(
            self.state, zone=p.get("zone", self.state.pc_zone),
            trigger_context=p.get("trigger_context", "")),
    }

    def trigger_forge(self, forge_type: str, params: dict) -> dict:
        """Manually trigger a forge from the FORGE tab UI."""
        if self.phase != GamePhase.IDLE:
            return {"success": False,
                    "error": f"Cannot forge in phase: {self.phase.value}"}
        if not self.state:
            return {"success": False, "error": "No state loaded"}

        builder = self._FORGE_DISPATCH.get(forge_type)
        if not builder:
            return {"success": False,
                    "error": f"Unknown forge type: {forge_type}"}

        try:
            req = builder(self, params)
        except Exception as e:
            return {"success": False, "error": f"Forge build failed: {e}"}

        self.creative_queue.clear()
        self.creative_queue.enqueue(req)
        self._write_pending_file()
        self._set_phase(GamePhase.AWAIT_CREATIVE)
        self._log_action("FORGE", f"[{forge_type}] queued — awaiting Claude")

        return {
            "success": True,
            "forge_type": forge_type,
            "request_id": req.id,
            "pending": self.creative_queue.pending_count(),
        }

    # ─────────────────────────────────────────────────
    # SESSION LIFECYCLE (DG-19)
    # ─────────────────────────────────────────────────

    def start_session(self) -> dict:
        """
        SSM — Session Start Macro.
        Increments session_id, resets session counters, runs ZONE-FORGE.
        Player-initiated only (button press).
        """
        if self.phase != GamePhase.IDLE:
            return {"success": False,
                    "error": f"Cannot start session in phase: {self.phase.value}"}

        self.state.session_id += 1
        sid = self.state.session_id
        self.state.reset_session()
        self.creative_queue.call_count = 0

        # Run ZONE-FORGE cascade (DG-13)
        forge_result = run_zone_forge(self.state)

        self._log_action("SESSION",
                         f"=== SESSION {sid} STARTED ===")
        self._log_action("ZONE_FORGE",
                         f"Zone: {self.state.pc_zone} \u2014 {forge_result.get('status', 'unknown')}")

        # Log With_PC cohesion moves
        for move in forge_result.get("with_pc_moved", []):
            self._log_action("WITH_PC", f"Cohesion: {move}")

        # Log detected gaps
        for gap in forge_result.get("gaps", []):
            self._log_action("ZONE_FORGE", f"  Gap: {gap}")

        # Queue forge requests if gaps detected
        forge_requests = forge_result.get("forge_requests", [])
        if forge_requests:
            self.creative_queue.clear()
            self.creative_queue.enqueue_many(forge_requests)
            self._write_pending_file()
            self._set_phase(GamePhase.AWAIT_CREATIVE)
            self._log_action("ZONE_FORGE",
                             f"{len(forge_requests)} forge requests queued")

        self._auto_save()

        # Strip non-serializable forge_requests from result
        forge_summary = {k: v for k, v in forge_result.items()
                         if k != "forge_requests"}
        forge_summary["forge_request_count"] = len(forge_requests)

        return {
            "success": True,
            "session_id": sid,
            "zone": self.state.pc_zone,
            "zone_forge": forge_summary,
            "creative_pending": self.creative_queue.pending_count(),
        }

    def end_session(self) -> dict:
        """
        ENDS — Session End Macro.
        Saves state, queues SESSION_SUMMARY creative request.
        Player-initiated only (button press).
        """
        if self.phase != GamePhase.IDLE:
            return {"success": False,
                    "error": f"Cannot end session in phase: {self.phase.value}"}

        sid = self.state.session_id

        # Save immediately (state loss prevention)
        self._auto_save()
        self._log_action("SESSION", f"=== SESSION {sid} ENDING ===")

        # Generate HTML report immediately (will be regenerated with
        # summary once Claude responds)
        report_html = generate_session_report(self.state, sid)
        report_filename = f"Session_{sid}_Report.html"
        report_path = os.path.join(self._data_dir, report_filename)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_html)
        self._log_action("REPORT", f"HTML report saved: {report_filename}")

        # Queue SESSION_SUMMARY creative request
        summary_req = build_session_summary(self.state)
        self.creative_queue.clear()
        self.creative_queue.enqueue(summary_req)
        self._write_pending_file()
        self._set_phase(GamePhase.AWAIT_CREATIVE)

        return {
            "success": True,
            "session_id": sid,
            "awaiting_summary": True,
            "report_url": f"/api/session/report/{sid}",
            "pending_types": self.creative_queue.pending_types(),
        }

    def get_session_report(self, session_id: int) -> str:
        """Return HTML report for a session, generating if needed."""
        report_filename = f"Session_{session_id}_Report.html"
        report_path = os.path.join(self._data_dir, report_filename)
        if os.path.exists(report_path):
            with open(report_path, "r", encoding="utf-8") as f:
                return f.read()
        # Generate on demand
        report_html = generate_session_report(self.state, session_id)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_html)
        return report_html

    # ─────────────────────────────────────────────────
    # COMBAT (DG-16)
    # ─────────────────────────────────────────────────

    def start_combat_with_npc(self, npc_name: str) -> dict:
        """Manually start combat with an NPC in the current zone."""
        if self.phase != GamePhase.IDLE:
            return {"success": False,
                    "error": f"Cannot start combat during {self.phase.value} phase"}
        if not self.state:
            return {"success": False, "error": "No state loaded"}

        # Find the NPC
        npc = self.state.npcs.get(npc_name)
        if not npc:
            # Try case-insensitive match
            for name, n in self.state.npcs.items():
                if name.lower() == npc_name.lower():
                    npc = n
                    break
        if not npc:
            return {"success": False, "error": f"NPC not found: {npc_name}"}
        if npc.zone != self.state.pc_zone:
            return {"success": False,
                    "error": f"{npc.name} is in {npc.zone}, not {self.state.pc_zone}"}

        # Dead NPC guard (spec bug #4)
        if getattr(npc, "status", "") in ("dead", "destroyed"):
            return {"success": False,
                    "error": f"{npc.name} is {npc.status} — cannot fight"}

        # Build bx_plug from NPC stats
        if not npc.bx_ac and not npc.bx_hd:
            return {"success": False,
                    "error": f"{npc.name} has no BX combat stats"}

        bx_plug = {
            "name": npc.name,
            "stats": {
                "name": npc.name,
                "ac": npc.bx_ac,
                "hd": npc.bx_hd,
                "hp": npc.bx_hp if npc.bx_hp else npc.bx_hp_max,
                "hp_max": npc.bx_hp_max,
                "at": npc.bx_at,
                "dmg": npc.bx_dmg or "1d6",
                "ml": npc.bx_ml or 7,
                "count": 1,
            },
            "type": "combat",
        }

        try:
            self.combat_state = init_combat(
                self.state, bx_plug, f"Combat with {npc.name}")
            self._set_phase(GamePhase.IN_COMBAT)
            self._log_action("COMBAT", f"Manual combat started with {npc.name}")
            return {
                "success": True,
                "combat": self.combat_state.to_ui_dict(),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to init combat: {e}"}

    def combat_action(self, action: str) -> dict:
        """
        Player chose ATTACK or FLEE for this combat round.
        Resolves the round mechanically, returns result.
        """
        if self.phase != GamePhase.IN_COMBAT or not self.combat_state:
            return {"success": False,
                    "error": f"Not in combat (phase: {self.phase.value})"}

        combat = self.combat_state

        # Check start-of-round end conditions
        if check_combat_end(combat):
            return self._end_combat()

        combat.round_number += 1
        action_upper = action.upper()

        if action_upper == "ATTACK":
            round_result = resolve_round_attack(combat)
        elif action_upper == "FLEE":
            round_result = resolve_round_flee(combat)
        else:
            return {"success": False,
                    "error": f"Invalid action: {action}. Use ATTACK or FLEE."}

        # Log round to action log
        summary = round_result.get("summary", "")
        self._log_action("COMBAT",
                         f"Round {combat.round_number}: {action_upper} — {summary}")

        # Log each MECH entry from this round
        for entry in combat.combat_log:
            if entry.startswith("---") or entry.startswith("==="):
                continue  # skip headers in action log

        # Check if combat ended this round
        if combat.ended:
            return self._end_combat()

        # Check start-of-next-round conditions
        if check_combat_end(combat):
            return self._end_combat()

        return {
            "success": True,
            "round": combat.round_number,
            "action": action_upper,
            "round_result": round_result,
            "combat": combat.to_ui_dict(),
            "ended": False,
        }

    def _end_combat(self) -> dict:
        """Combat has ended. Apply results, queue narration, transition."""
        combat = self.combat_state

        # Apply HP changes to persistent state
        apply_combat_results(self.state, combat)

        self._log_action("COMBAT",
                         f"Combat ended: {combat.end_reason} "
                         f"(Round {combat.round_number})")

        # Queue post-combat narration
        narr_req = build_narr_combat_end(self.state, combat)
        self.creative_queue.clear()
        self.creative_queue.enqueue(narr_req)
        self._write_pending_file()

        combat_summary = combat.to_ui_dict()
        self.combat_state = None

        self._set_phase(GamePhase.AWAIT_CREATIVE)
        self._auto_save()

        return {
            "success": True,
            "ended": True,
            "end_reason": combat_summary["end_reason"],
            "combat": combat_summary,
        }

    # ─────────────────────────────────────────────────
    # MODE MACROS (DG-22)
    # ─────────────────────────────────────────────────

    VALID_MODES = {"INTENS", "INTIM", "INVESTIG"}

    def set_mode(self, mode: str) -> dict:
        """Activate or deactivate a narrative mode."""
        if mode is None or mode == "" or mode.upper().startswith("EX"):
            old = self.active_mode
            self.active_mode = None
            self._log_action("MODE", f"Mode deactivated (was: {old or 'none'})")
            return {"success": True, "mode": None, "previous": old}

        mode_upper = mode.upper()
        if mode_upper not in self.VALID_MODES:
            return {"success": False,
                    "error": f"Unknown mode: {mode}. Valid: {', '.join(sorted(self.VALID_MODES))}"}

        if self.phase != GamePhase.IDLE:
            return {"success": False,
                    "error": f"Cannot change mode during {self.phase.value} phase"}

        old = self.active_mode
        self.active_mode = mode_upper
        self._log_action("MODE", f"Mode set: {mode_upper} (was: {old or 'none'})")
        return {"success": True, "mode": mode_upper, "previous": old}

    def trigger_rumor(self) -> dict:
        """Trigger a one-shot RUMOR request."""
        if self.phase != GamePhase.IDLE:
            return {"success": False,
                    "error": f"Cannot trigger rumor during {self.phase.value} phase"}
        if not self.state:
            return {"success": False, "error": "No state loaded"}

        req = build_rumor(self.state)
        self.creative_queue.clear()
        self.creative_queue.enqueue(req)
        self._write_pending_file()
        self._set_phase(GamePhase.AWAIT_CREATIVE)
        self._log_action("RUMOR", f"Rumor requested for {self.state.pc_zone}")
        return {
            "success": True,
            "request_id": req.id,
            "pending": self.creative_queue.pending_count(),
        }

    # ─────────────────────────────────────────────────
    # STATE QUERIES (for web UI)
    # ─────────────────────────────────────────────────

    def get_full_state(self) -> dict:
        """Return everything the web UI needs to render."""
        s = self.state
        if not s:
            return {"error": "No state loaded"}

        # Active clocks
        active_clocks = []
        fired_clocks = []
        halted_clocks = []
        for c in s.clocks.values():
            cd = {
                "name": c.name, "owner": c.owner,
                "progress": c.progress, "max_progress": c.max_progress,
                "status": c.status, "is_cadence": c.is_cadence,
                "trigger_fired": c.trigger_fired,
                "trigger_text": c.trigger_on_completion,
            }
            if c.trigger_fired:
                fired_clocks.append(cd)
            elif c.status == "halted":
                halted_clocks.append(cd)
            elif c.status != "retired":
                active_clocks.append(cd)

        # Sort active by urgency (highest fill first)
        active_clocks.sort(
            key=lambda c: c["progress"] / max(c["max_progress"], 1),
            reverse=True,
        )

        # Danger clocks for header (>= 75% full)
        danger_clocks = [
            c for c in active_clocks
            if c["progress"] / max(c["max_progress"], 1) >= 0.75
        ]

        # NPCs
        companions = []
        other_npcs = []
        for npc in s.npcs.values():
            nd = {
                "name": npc.name, "zone": npc.zone, "status": npc.status,
                "role": npc.role, "trait": npc.trait, "faction": npc.faction,
                "with_pc": npc.with_pc, "is_companion": npc.is_companion,
                "bx_hp": npc.bx_hp, "bx_hp_max": npc.bx_hp_max,
            }
            if npc.is_companion:
                # Full companion data for PARTY tab
                nd.update({
                    "class_level": npc.class_level,
                    "bx_ac": npc.bx_ac,
                    "bx_hd": npc.bx_hd,
                    "bx_at": npc.bx_at,
                    "bx_dmg": npc.bx_dmg,
                    "bx_ml": npc.bx_ml,
                    "appearance": npc.appearance,
                    "objective": npc.objective,
                    "knowledge": npc.knowledge,
                    "next_action": npc.next_action,
                    "history": npc.history[-5:] if npc.history else [],
                })
                # Companion detail (relationship, trust, etc.)
                comp_detail = s.companions.get(npc.name)
                if comp_detail:
                    nd["trust_in_pc"] = comp_detail.trust_in_pc
                    nd["affection_levels"] = comp_detail.affection_levels
                    nd["motivation_shift"] = comp_detail.motivation_shift
                    nd["loyalty_change"] = comp_detail.loyalty_change
                    nd["stress_or_fatigue"] = comp_detail.stress_or_fatigue
                    nd["grievances"] = comp_detail.grievances
                    nd["agency_notes"] = comp_detail.agency_notes
                    nd["future_flashpoints"] = comp_detail.future_flashpoints
                companions.append(nd)
            else:
                # DG-28: Include detail fields for expandable NPC rows
                nd.update({
                    "appearance": npc.appearance,
                    "objective": npc.objective,
                    "class_level": npc.class_level,
                    "bx_ac": npc.bx_ac,
                    "bx_hd": npc.bx_hd,
                    "bx_at": npc.bx_at,
                    "bx_dmg": npc.bx_dmg,
                    "bx_ml": npc.bx_ml,
                    "knowledge": npc.knowledge,
                    "next_action": npc.next_action,
                })
                other_npcs.append(nd)

        # Factions
        factions = []
        for fac in s.factions.values():
            factions.append({
                "name": fac.name, "status": fac.status,
                "disposition": fac.disposition, "trend": fac.trend,
            })

        # Engines
        engines = []
        for eng in s.engines.values():
            engines.append({
                "name": eng.name, "version": eng.version,
                "status": eng.status, "cadence": eng.cadence,
            })

        # PC state
        pc = None
        if s.pc_state:
            p = s.pc_state
            pc = {
                "name": p.name,
                "class_level": "Fighter 16",
                "stats": (f"AC {p.bx_ac or 30} | HD {p.bx_hd or 16} | "
                          f"HP {p.bx_hp or 131}/{p.bx_hp_max or 131} | "
                          f"AT +{p.bx_at or 27} | Dmg {p.bx_dmg or '1d8+15'} | "
                          f"ML {p.bx_ml or 12}"),
                "reputation": p.reputation,
                "conditions": p.conditions,
                "goals": p.goals,
                "equipment_notes": p.equipment_notes,
                "zone": s.pc_zone,
                "psychological_state": p.psychological_state,
                "secrets": p.secrets,
                "affection_summary": p.affection_summary,
                "reputation_levels": p.reputation_levels,
                "history": p.history[-5:] if p.history else [],
                "bx_hp": p.bx_hp or 131,
                "bx_hp_max": p.bx_hp_max or 131,
            }

        # Open threads
        open_threads = []
        for t in s.unresolved_threads:
            if not t.resolved:
                open_threads.append({
                    "id": t.id, "zone": t.zone,
                    "description": t.description,
                })

        return {
            "phase": self.phase.value,
            "meta": {
                "session_id": s.session_id,
                "in_game_date": s.in_game_date,
                "pc_zone": s.pc_zone,
                "season": s.season,
                "campaign_intensity": s.campaign_intensity,
                "seasonal_pressure": s.seasonal_pressure,
            },
            "crossing_points": get_crossing_points(s) if self.phase == GamePhase.IDLE else [],
            "danger_clocks": danger_clocks,
            "active_clocks": active_clocks,
            "fired_clocks": fired_clocks,
            "halted_clocks": halted_clocks,
            "companions": companions,
            "other_npcs": other_npcs,
            "factions": factions,
            "engines": engines,
            "pc": pc,
            "open_threads": open_threads,
            "narration": self.narration_buffer[-20:],
            "action_log": self.action_log[-100:],
            "zones": sorted(list(s.zones.keys())) if s.zones else [],
            "creative_pending": self.creative_queue.pending_count(),
            "creative_call_count": self.creative_queue.call_count,
            "combat": (self.combat_state.to_ui_dict()
                       if self.combat_state and self.phase == GamePhase.IN_COMBAT
                       else None),
            "active_mode": self.active_mode,  # DG-22
        }

    def get_creative_pending(self) -> dict:
        """Return pending creative requests for Claude (MCP pulls this)."""
        if self.creative_queue.is_empty():
            return {"pending": False, "request_count": 0, "requests": []}
        batch = self.creative_queue.get_pending_batch()
        batch["pending"] = True
        return batch

    # ─────────────────────────────────────────────────
    # SAVE / LOAD
    # ─────────────────────────────────────────────────

    def save_game(self, filename: str = "") -> str:
        """Save current state. Returns the filename used."""
        os.makedirs(self._data_dir, exist_ok=True)
        if not filename:
            filename = self._canonical_save_name()
        if not filename.endswith(".json"):
            filename += ".json"
        filepath = os.path.join(self._data_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(state_to_json(self.state))
        self._log_action("SAVE", f"Saved: {filename}")
        return filename

    def load_game(self, filename: str) -> dict:
        """Load state from a save file."""
        filepath = os.path.join(self._data_dir, filename)
        if not os.path.exists(filepath):
            if not filepath.endswith(".json"):
                filepath += ".json"
            if not os.path.exists(filepath):
                return {"success": False, "error": f"File not found: {filename}"}

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                self.state = state_from_json(f.read())
            self._backfill_crossing_points(self.state)
            self._backfill_companion_stats(self.state)
            self._backfill_pc_stats(self.state)
            self._backfill_encounter_lists(self.state)
            self.creative_queue.clear()
            self.narration_buffer = []
            self._set_phase(GamePhase.IDLE)
            self._log_action("SESSION", f"Loaded: {filename}")
            return {
                "success": True,
                "filename": filename,
                "date": self.state.in_game_date,
                "zone": self.state.pc_zone,
                "session_id": self.state.session_id,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_saves(self) -> list[dict]:
        """List available save files."""
        if not os.path.isdir(self._data_dir):
            return []
        saves = sorted(
            glob.glob(os.path.join(self._data_dir, "save_*.json")) +
            glob.glob(os.path.join(self._data_dir, "Session *.json")),
            key=os.path.getmtime, reverse=True,
        )
        result = []
        for s in saves:
            result.append({
                "filename": os.path.basename(s),
                "size": os.path.getsize(s),
                "modified": datetime.fromtimestamp(
                    os.path.getmtime(s)
                ).strftime("%Y-%m-%d %H:%M"),
            })
        return result

    def _auto_save(self):
        """Auto-save after state-changing operations."""
        try:
            os.makedirs(self._data_dir, exist_ok=True)
            filename = self._canonical_save_name()
            filepath = os.path.join(self._data_dir, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(state_to_json(self.state))
        except Exception:
            pass

    def _canonical_save_name(self) -> str:
        s = self.state
        sid = str(s.session_id).zfill(2)
        date_str = s.in_game_date or "unknown"
        zone_str = s.pc_zone or "unknown"
        safe_date = date_str.replace("/", "-").replace("\\", "-").replace(":", "-")
        safe_zone = zone_str.replace("/", "-").replace("\\", "-").replace(":", "-")
        return f"Session {sid} - {safe_date} - {safe_zone}.json"

    # ─────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────

    def _convert_engine_request(self, raw_req: dict) -> CreativeRequest:
        """Convert a raw engine llm_request dict into a typed CreativeRequest."""
        req_type = raw_req.get("type", "")

        if req_type == "CLOCK_AUDIT_REVIEW":
            return build_clock_audit(
                clock_name=raw_req.get("clock", ""),
                progress=raw_req.get("progress", ""),
                ambiguous_bullets=raw_req.get("ambiguous_bullets", []),
                daily_facts=raw_req.get("daily_facts", []),
            )

        elif req_type == "NPAG":
            return build_npag(self.state, raw_req.get("npc_count", 0))

        elif req_type == "NARR_ENCOUNTER":
            bx_detail = raw_req.get("bx_plug_detail")
            encounter_data = {
                "description": raw_req.get("context", ""),
                "has_bx_plug": raw_req.get("bx_plug", False),
                "bx_stat_block": bx_detail if bx_detail else "",
                "ua_cue": raw_req.get("ua_cue", False),
            }
            # DG-16: Stash bx_plug detail for combat after narration
            if bx_detail and (bx_detail.get("type") == "combat"
                              or bx_detail.get("hostile_action")):
                self._pending_combat_data = {
                    "bx_plug": bx_detail,
                    "encounter_prompt": raw_req.get("context", ""),
                }
            return build_narr_encounter(self.state, encounter_data, active_mode=self.active_mode)

        elif req_type == "CAN-FORGE-AUTO":
            # VP roll=12 — route through UA_FORGE (DG-17)
            return build_ua_forge(
                self.state,
                zone=raw_req.get("zone", self.state.pc_zone),
                trigger_context="VP roll 12 — automatic UA threat",
            )

        # DG-17 Forge request types
        elif req_type == "NPC_FORGE":
            return build_npc_forge(
                self.state,
                zone=raw_req.get("zone", self.state.pc_zone),
                role_hint=raw_req.get("role_hint", ""),
                faction_hint=raw_req.get("faction_hint", ""),
            )

        elif req_type == "EL_FORGE":
            return build_el_forge(
                self.state,
                zone=raw_req.get("zone", self.state.pc_zone),
            )

        elif req_type == "FAC_FORGE":
            return build_fac_forge(
                self.state,
                faction_name=raw_req.get("faction_name", ""),
                zone_hint=raw_req.get("zone_hint", ""),
            )

        elif req_type == "CAN_FORGE":
            return build_can_forge(
                self.state,
                zone=raw_req.get("zone", self.state.pc_zone),
                trigger=raw_req.get("trigger", "manual"),
            )

        elif req_type == "CL_FORGE":
            return build_cl_forge(
                self.state,
                owner=raw_req.get("owner", ""),
                trigger_context=raw_req.get("trigger_context", ""),
            )

        elif req_type == "PE_FORGE":
            return build_pe_forge(
                self.state,
                engine_name=raw_req.get("engine_name", ""),
                zone_scope=raw_req.get("zone_scope", ""),
                trigger_event=raw_req.get("trigger_event", ""),
            )

        elif req_type == "UA_FORGE":
            return build_ua_forge(
                self.state,
                zone=raw_req.get("zone", self.state.pc_zone),
                trigger_context=raw_req.get("trigger_context", ""),
            )

        return None

    def _log_tp_day(self, day_log: dict):
        """Log T&P day results to the action log."""
        date = day_log.get("date", "?")

        for step in day_log.get("steps", []):
            sn = step["step"]
            r = step.get("result", step.get("results", {}))

            if sn == "date_advance":
                if r.get("season_changed"):
                    self._log_action("DATE", f"{r['new_date']} — SEASON: {r['new_season']}")
                else:
                    self._log_action("DATE", r.get("new_date", "?"))

            elif sn.startswith("engine:"):
                en = sn.split(":", 1)[1]
                if r.get("skipped") or r.get("status") == "inert":
                    continue
                if "roll" in r:
                    self._log_action("ENGINE",
                                     f"{en}: 2d6={r['roll']['total']} -> {r.get('outcome_band', '')}")
                    for ce in r.get("clock_effects_applied", []):
                        if not ce.get("skipped") and "error" not in ce:
                            self._log_action("CLOCK_ADVANCE",
                                             f"{ce['clock']}: {ce.get('old', '?')}->{ce.get('new', '?')}")

            elif sn == "cadence_clocks":
                for cr in step.get("results", []):
                    if "error" not in cr:
                        self._log_action("CADENCE",
                                         f"{cr['clock']}: {cr['old']}->{cr['new']}/{cr['max']}")
                        if cr.get("trigger_fired"):
                            self._log_action("TRIGGER", f"FIRED: {cr.get('trigger_text', '')}")

            elif sn == "clock_audit":
                for a in r.get("auto_advanced", []):
                    ar = a["advance_result"]
                    self._log_action("CLOCK_AUDIT",
                                     f"{a['clock']}: {ar['old']}->{ar['new']}/{ar.get('max', '?')}")
                for rv in r.get("needs_llm_review", []):
                    self._log_action("CLOCK_AUDIT",
                                     f"{rv['clock']}: needs Claude review "
                                     f"({len(rv['ambiguous_bullets'])} bullets)")

            elif sn == "clock_interactions":
                for flag in r.get("flags", []):
                    self._log_action("TRIGGER",
                                     f"INTERACTION {flag['rule']}: {flag['text'][:80]}")
                for adv in r.get("advances", []):
                    ar = adv["result"]
                    self._log_action("CLOCK_ADVANCE",
                                     f"INTERACTION {adv['rule']}: "
                                     f"{ar['clock']}: {ar['old']}->{ar['new']}")
                for spawn in r.get("spawns", []):
                    self._log_action("TRIGGER",
                                     f"INTERACTION {spawn['rule']}: SPAWNED {spawn['clock']}")

            elif sn == "halt_evaluation":
                for h in (r if isinstance(r, list) else []):
                    self._log_action("CLOCK_AUDIT",
                                     f"HALTED: {h['clock']} \u2014 {h['condition'][:60]}")

            elif sn == "encounter_gate":
                rv = r["roll"]["total"]
                if r["passed"]:
                    enc = r.get("encounter", {})
                    self._log_action("ENCOUNTER",
                                     f"PASS (d6={rv}) -> {enc.get('description', 'no table')[:60]}")
                else:
                    self._log_action("ENCOUNTER", f"fail (d6={rv})")

            elif sn == "npag_gate":
                rv = r["roll"]["total"]
                if r["passed"]:
                    self._log_action("NPAG",
                                     f"PASS (d6={rv}) -> {r['npc_count']['count']} NPCs")
                else:
                    self._log_action("NPAG", f"fail (d6={rv})")

    def _log_action(self, action_type: str, detail: str):
        """Add an entry to the action log."""
        entry = {
            "type": action_type,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
            "date": self.state.in_game_date if self.state else "",
        }
        self.action_log.append(entry)
        if self._on_log_entry:
            self._on_log_entry(entry)
