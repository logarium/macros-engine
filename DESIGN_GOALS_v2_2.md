# GAMMARIA STANDALONE ENGINE — DESIGN GOALS v2.2
# Status: ACTIVE
# Created: Session 10 post-analysis, February 2026
# Updated: February 2026 — statuses synced to actual codebase
# ═══════════════════════════════════════════════════════════════

## COMPLETED (from v1.0)

## DG-01: JSON Save Replaces Delta ✅
Implemented. JSON save is canonical state. Delta format retired.

## DG-02: CNC Handling Review ✅
Resolved. CNCs working as designed — persistent world furniture. No changes needed.

## DG-03: Clock Interaction Effects ✅
Implemented. Seven interaction rules in NSV-CLOCKS. Evaluated during T&P clock audit.

## DG-04: Mode Macro Trim ✅
Done by player.

## DG-05: Companion Combat (Allied Combatant Protocol) ✅
Implemented. BX-PLUG §9 — full allied combatant rules.


# ═══════════════════════════════════════════════════════════════
# NEW GOALS — STANDALONE ENGINE v3.0
# ═══════════════════════════════════════════════════════════════
#
# VISION: A standalone solo procedural RPG that wraps around
# Claude (or any LLM). The engine owns all deterministic
# operations. Claude is called only for creative atoms and
# narration. The player interacts with the engine UI, not
# with Claude directly.
#
# COMMERCIAL VIABILITY: Design for free-tier Claude users.
# Minimise LLM calls. Make the engine do the work.
# ═══════════════════════════════════════════════════════════════


## DG-10: Engine as Outer Loop ✅
STATUS: DONE
PRIORITY: Critical
PHASE: 1
DESCRIPTION: The Python engine owns the game loop. It starts,
  loads state, detects zone, runs all deterministic sequences,
  and only calls Claude via MCP when creative output is needed.
  Claude never decides what runs next. The engine reads the
  procedural rules and executes them. Claude produces content
  when asked.
IMPLEMENTED: GameLoop class in game_loop.py with formal state
  machine (GamePhase enum: IDLE, TRAVEL, TIME_PRESSURE,
  AWAIT_CREATIVE, NARRATE). Engine calls run_day()
  deterministically, collects llm_requests, queues them as
  CreativeRequests via creative_bridge.py. MCP server bridges
  via HTTP to localhost:8000. Entry point: gammaria.py launches
  uvicorn + browser.


## DG-11: Player UI
STATUS: PARTIALLY DONE
PRIORITY: Critical
PHASE: 1
DESCRIPTION: The engine presents all player-facing interface:
  zone info, CP buttons, combat choices (ATTACK/FLEE/companion
  orders), dialogue input box, session header, clock status
  display. No player interaction passes through Claude — it all
  goes through the engine's GUI.

LAYOUT: HEADER + five tabs: PLAY, PARTY, TRACK, FORGE, LOGS

  HEADER (always visible, all tabs):
    Session ID, in-game date, current zone, intensity level.
    Compact danger summary (critical clocks in red, e.g.
    "Binding Degradation 14/16"). Never changes between tabs.

  PLAY (main screen — 80% of player time):
    Chat interface showing Claude narration and player input.
    CP buttons appear contextually after zone arrival.
    Combat UI replaces CP buttons when combat triggers
    (ATTACK/FLEE/companion order buttons).
    Load/save controls.
    Collapsible split pane (right side) showing live log feed
    — toggleable, so player can watch mechanical actions
    alongside narration without switching tabs.
    Space reserved for NPC/companion portraits.

  PARTY:
    PC stats and status.
    Companion cards: location, hp, status, portrait, traits.
    Relationship summary.

  TRACK:
    Clock progress bars (colour-coded by urgency).
    Engine status indicators.
    Zones visited, discoveries, unresolved threads, factions.
    "Export Report" button (HTML report generation).

  FORGE:
    Player-invoked forge macros (NPC-FORGE, EL-FORGE, etc.).
    Stepwise input UI — player fills fields, Claude produces
    atoms, engine validates and commits.
    Separated from PLAY to keep play interface clean.

  LOGS:
    Unified action log — engine mechanical actions AND Claude
    creative responses, timestamped, single stream.
    Auto-scroll with ability to scroll back.
    Full inspection and audit trail.

IMPLEMENTED:
  - Browser-based SPA: web/static/index.html + app.js + style.css.
  - HEADER: session, date, zone, season, intensity, danger-clock
    badges. All working.
  - PLAY: narration area, CP travel buttons, waiting-for-Claude
    overlay. Working.
  - PARTY: PC card + companion cards with BX stats. Working.
  - TRACK: clocks (colour-coded by fill), engines, factions,
    open threads. Working.
  - LOGS: timestamped action log. Working.
  - FORGE: stub only ("will be available in Phase 2").
REMAINING:
  - FORGE tab working via DG-17. Combat UI working via DG-16.
  - Side panel working via DG-27. Export Report button on TRACK tab.
  - Portraits: 6 images (Thoron + 5 companions) served from /images/,
    displayed in PARTY tab cards (64px) and PLAY side panel (36px).
NOTES:
  - Dice roller deferred — engine handles all deterministic
    rolls. Add manual roller later if player need emerges.
  - HTML report auto-generates at session end (ENDS sequence)
    and available on demand via TRACK export button.
  - Portrait space in PLAY and PARTY — implementation later,
    but reserve layout space from the start.
  - Legacy tkinter GUI (gui.py) still exists but is not the
    primary UI.


## DG-12: Claude as Creative API ✅
STATUS: DONE
PRIORITY: Critical
PHASE: 1
DESCRIPTION: Define a clean request/response contract between
  engine and Claude. Engine sends structured requests (NARR,
  NPC-FORGE, EL-FORGE, CLOCK-AUDIT, NPAG, DIALOGUE, etc.)
  with all necessary context. Claude returns structured
  responses. Engine parses and commits to state.
IMPLEMENTED: creative_bridge.py — CreativeRequest and
  CreativeResponse dataclasses. Request builders:
  build_narr_arrival(), build_narr_encounter(),
  build_clock_audit(), build_npag(). CreativeQueue manages
  pending/completed lifecycle. submit_response() parses JSON
  (handles markdown fences, wrapped JSON). apply_responses()
  applies state_changes (clock_advance, clock_reduce, fact,
  npc_update) to game state.
  Request types working: NARR_ARRIVAL, NARR_ENCOUNTER,
  CLOCK_AUDIT, NPAG, CAN_FORGE_AUTO (partial).
REMAINING:
  - FORGE subtypes (NPC/EL/FAC/CAN/CL/PE/UA) not yet built
  - DIALOGUE request type not yet built
  - SESSION_SUMMARY request type not yet built
NOTES:
  - Each request includes: type, context payload, constraints
  - Each response includes: type, structured content, state changes
  - Contract is LLM-agnostic (see DG-26)


## DG-13: Full ZONE-FORGE Automation
STATUS: DONE
PRIORITY: High
PHASE: 2
DESCRIPTION: Engine runs the entire ZONE-FORGE cascade
  deterministically: validate zone name, check controlling
  faction, count NPCs in zone, check EL-DEF exists, check UA
  active. Only calls Claude for creative fill (forge atoms)
  when a gap is detected.
IMPLEMENTED:
  - zone_forge.py: gap detection (NPC threshold by intensity + EL-DEF check)
  - NPC_FORGE emitted per missing NPC, EL_FORGE if no encounter list
  - game_loop.py: start_session() queues forge requests, enters AWAIT_CREATIVE
  - game_loop.py: travel_to() prepends forge requests to creative batch
  - models.py: encounter_lists serialization/deserialization (prerequisite fix)
  - NPC thresholds: low=1, medium/moderate=2, high/lethal=3
DEPENDS: DG-10, DG-12


## DG-14: Full T&P Automation ✅
STATUS: DONE
PRIORITY: High
PHASE: 1
DESCRIPTION: Engine owns the complete T&P cycle: advance date,
  tick cadence clocks, run engine rolls, evaluate encounter and
  NPAG gates, build pending request queue, evaluate clock
  interactions and cascade handling. Expand existing engine.py
  to cover all audit logic.
IMPLEMENTED: engine.py run_day() — full T&P day loop: date
  advance with Nurrian calendar (12 months, season tracking,
  seasonal pressure), VP/TSDD/HT-DH/SRP engine runners with
  hard-gate checks, cadence clock advancement, clock audit with
  auto-advance + LLM-review flagging, encounter gate (d6 vs
  intensity), NPAG gate (d6 vs intensity). dice.py has
  vp_outcome_band() mapping 2d6 to VP v3.0 bands.
  Clock interaction evaluation: evaluate_clock_interactions()
  implements all 7 NSV-CLOCKS interaction rules (FLAG/ADV/SPAWN)
  as data-driven one-time rules with CLOCK_NAME_MAP resolution.
  HALT condition evaluation: evaluate_halt_conditions() checks
  halt_conditions against daily_facts using keyword matching.
  Cadence suppression: already handled — cadence_clocks() filters
  by status=="active" and can_advance() rejects halted clocks.
  fired_interaction_rules persisted in GameState save/load.


## DG-15: Full TRAVEL Automation ✅
STATUS: DONE
PRIORITY: High
PHASE: 1
DESCRIPTION: Engine reads CPs from zone data in JSON save,
  validates destination, calculates time increment from CP
  tags (⊙ slow / ‡ eventful / unmarked standard), triggers
  T&P, sets PC zone, triggers ZONE-FORGE on arrival. Player
  selects destination via UI buttons.
IMPLEMENTED: travel.py — get_crossing_points() reads CPs from
  zone data, returns displayable destinations. validate_travel()
  checks destination reachable. execute_travel() updates PC
  zone, calculates days_traveled from CP tags (unmarked=1d,
  slow=2d, eventful=1d+forced encounter). game_loop.travel_to()
  chains travel → T&P → creative queue → auto-save. Web UI
  renders CP buttons via app.js renderCPs(), POSTs to
  /api/travel. CP network covers 30+ named zones in
  campaign_state.py.
DEPENDS: DG-11, DG-14


## DG-16: Full Combat Automation ✅
STATUS: DONE
PRIORITY: High
PHASE: 2
DESCRIPTION: Engine runs BX-PLUG: initiative rolls, attack
  resolution, damage application, morale triggers, allied
  combatant targeting AI, flee logic. Calls Claude only for
  narration between rounds or at combat end. Player choices
  via UI buttons (ATTACK/FLEE/companion orders).
IMPLEMENTED:
  - combat.py: Full BX-PLUG combat engine (~500 lines). Combatant
    and CombatState dataclasses. Stat parsing (string/dict/list
    formats). init_combat(), check_combat_end(), roll_initiative(),
    resolve_attack(), resolve_round_attack(), resolve_round_flee().
    Targeting AI: get_pc_target() (healthiest foe), get_companion_targets()
    (§9.6 with defender logic at PC hp ≤ 50%), get_foe_targets() (§9.8
    distribution). Morale: evaluate_morale_triggers() (triggers A-E),
    roll_morale(), check_companion_morale() (§9.10). apply_combat_results()
    persists HP to state.
  - game_loop.py: IN_COMBAT phase, _pending_combat_data stash pattern
    (combat starts after Claude narrates encounter setup), combat_action()
    and _end_combat() methods, _backfill_pc_stats() for Thoron.
  - creative_bridge.py: NARR_COMBAT_END request type + build_narr_combat_end()
    builder. Single Claude call per combat (DG-25 token economy).
  - sampling_adapter.py: NARR_COMBAT_END prompt formatting + lore injection.
  - web/routes.py: POST /api/combat/action, GET /api/combat/state.
  - web/static/: Combat dashboard UI — two-column layout (PARTY vs FOES),
    combatant cards with HP bars, scrollable MECH log, ATTACK/FLEE buttons.
  - models.py: bx_* combat stat fields on PCState.
DEPENDS: DG-10, DG-11, DG-12


## DG-17: Forge Request Protocol
STATUS: DONE
PRIORITY: High
PHASE: 2
DESCRIPTION: Standardise the structured input/output format
  for all forges (NPC-FORGE, EL-FORGE, FAC-FORGE, CAN-FORGE,
  CL-FORGE, PE-FORGE, UA-FORGE). Engine assembles inputs from
  game state, sends to Claude as structured request, receives
  structured atoms, validates, commits to JSON save.
IMPLEMENTED:
  - 7 REQUEST_TYPES + 8 STATE_CHANGE_TYPES in creative_bridge.py
  - 7 build_*_forge() builders + 8 _apply_state_change() handlers with validation
  - game_loop.py: converter cases, forge logging, CAN-FORGE-AUTO→UA_FORGE routing
  - sampling_adapter.py: SYSTEM_PROMPT + request formatting for all forge types
  - DG-18 absorbed via clock_create state_change type
NOTES:
  - Each forge has defined required/optional inputs
  - Engine pre-fills all deterministic inputs
  - Claude provides only creative content
  - Engine validates output before committing
DEPENDS: DG-12, DG-13


## DG-18: Clock Creation via Engine
STATUS: DONE (absorbed into DG-17)
PRIORITY: High
PHASE: 2
DESCRIPTION: Engine can create new clocks from forge output
  or clock interaction SPAWN effects. Closes the current gap
  where CL-FORGE produces a definition but the engine cannot
  instantiate it. Engine parses clock atoms from Claude and
  writes them directly into the JSON save.
NOTES:
  - Add create_clock tool to MCP server
  - Accept full clock definition (name, owner, track size,
    ADV/HALT/RED/TRG bullets, starting progress)
  - Validate owner exists in state before creating
DEPENDS: DG-14


## DG-19: Session Lifecycle ✅
STATUS: DONE
PRIORITY: Medium
PHASE: 2
DESCRIPTION: Engine handles SSM (load save, validate zone,
  run ZONE-FORGE cascade, display session header) and ENDS
  (checklist audit, prompt Claude for session summary, update
  all entity states, export save, generate HTML report) as
  automated sequences.
RULES:
  - Session ID increments ONLY at SSM (new session start).
  - ENDS does NOT increment session ID.
  - ENDS writes final save under current session ID.
  - Next SSM reads that save and increments to new session.
IMPLEMENTED: game_loop.py — start_session() (SSM) increments
  session_id, resets session counters, runs ZONE-FORGE stub
  (zone_forge.py), auto-saves. end_session() (ENDS) saves
  state immediately, queues SESSION_SUMMARY creative request
  via build_session_summary() in creative_bridge.py.
  receive_creative_response() handles SESSION_SUMMARY: stores
  summary in session_summaries, generates HTML report via
  report.py, saves final state. report.py generates self-
  contained HTML with inline dark-theme CSS (header, summary,
  session meta, clock status with progress bars, companions,
  key events). Web UI: "New Session" and "End Session" footer
  buttons with confirmation modals. API endpoints:
  POST /api/session/start, POST /api/session/end,
  GET /api/session/report/{session_id}.
  ZONE-FORGE stub (zone_forge.py) validates zone exists,
  checks faction, counts NPCs — creative fill deferred to
  DG-13.
DEPENDS: DG-10, DG-13, DG-12


## DG-20: Context Management
STATUS: DONE
PRIORITY: High
PHASE: 2
DESCRIPTION: Engine controls what Claude sees per request.
  Instead of bulk-loading project files, engine assembles a
  focused context payload: only the lore, NPC data, clock
  states, and zone info relevant to the specific creative
  task. Keeps Claude's context lean and token-efficient.
IMPLEMENTED:
  - lore_index.py: lazy singleton parses docs/ lore files once
    on first access. Indexes places (39), NPCs (7), factions (19),
    world sections (8), party seed (6), forge specs (8), BX-PLUG (9).
    Case-insensitive lookup with partial matching fallback.
  - creative_bridge.py: all builders inject targeted lore into
    context["lore"] dicts:
    - NARR_ARRIVAL: zone atmosphere, faction lore, NPC lore
    - NARR_ENCOUNTER: zone atmosphere, BX-PLUG rules if combat
    - NPAG: NPC lore (10 lines), faction lore for acting NPCs
    - NPC_FORGE: NPC-FORGE spec, zone atmosphere, faction lore
    - EL_FORGE: EL-FORGE spec, zone atmosphere
    - FAC_FORGE: FAC-FORGE spec, existing faction lore if updating
    - CL_FORGE: CL-FORGE spec
    - CAN_FORGE: CAN-FORGE spec, NPC lore, PARTY-SEED entry
    - PE_FORGE: PE-FORGE spec, world lore (divine taxonomy)
    - UA_FORGE: UA-FORGE spec, zone atmosphere
  - sampling_adapter.py: SYSTEM_PROMPT updated with lore instruction,
    _format_lore() renders lore dicts into LORE sections in prompts,
    _inject_lore_for_raw_requests() handles MCP-path raw dicts.
    Both pipeline paths (MCP and game_loop) emit lore in prompts.
DEPENDS: DG-12, DG-25


## DG-21: Standalone Application ✅
STATUS: DONE
PRIORITY: Medium
PHASE: 3
DESCRIPTION: Package as a desktop application that launches,
  starts the MCP server, connects to Claude, and presents
  the full game UI. Player double-clicks an icon and plays.
  No manual setup, no copying files, no pasting state.
IMPLEMENTED: gammaria.py launches FastAPI server + opens
  browser automatically. Single command launch: python
  gammaria.py. install_mcp.bat and setup_helper.py provide
  assisted MCP setup. requirements.txt lists all dependencies
  (fastapi, uvicorn, pydantic, mcp). build.bat runs
  PyInstaller to produce dist/Gammaria.exe with bundled
  web/, docs/, and data/ directories and hidden uvicorn
  imports.
REMAINING:
  - MCP server must be configured separately in Claude Desktop
DEPENDS: DG-10, DG-11, DG-16, DG-19


## DG-22: Mode Macro Integration ✅
STATUS: DONE
PRIORITY: Low
PHASE: 3
DESCRIPTION: Engine detects or accepts mode triggers (INTENS,
  INTIM, INVESTIG, NARR-D, RUMOR) and adjusts request
  parameters to Claude accordingly. Modes modify the creative
  brief sent to Claude, not the mechanical loop.
IMPLEMENTED:
  - game_loop.py: active_mode field, set_mode(), trigger_rumor()
    methods. Modes guard on IDLE phase. Mode passed to
    build_narr_arrival() and build_narr_encounter().
  - creative_bridge.py: MODE_CONSTRAINTS dict with INTENS/INTIM/
    INVESTIG format instructions per MODE MACROS.txt. Mode
    constraints injected into narration request constraints.
    build_rumor() — 1d8 truth roll, zone context, lore injection.
  - sampling_adapter.py: RUMOR formatting case, mode_instruction
    appended to request sections when present.
  - web/routes.py: POST /api/mode, POST /api/rumor endpoints.
  - web/static/: Mode bar with INTENS/INTIM/INVESTIG/RUMOR buttons,
    active highlight, disabled when not idle.
DEPENDS: DG-12


## DG-23: Graceful Degradation ✅
STATUS: DONE
PRIORITY: Medium
PHASE: 3
DESCRIPTION: If MCP connection to Claude drops mid-session,
  engine saves state cleanly and allows resume. If Claude
  returns malformed output, engine logs it, retries once,
  then flags for player ruling. No silent failures. No lost
  state.
IMPLEMENTED: MCP server _get()/_post() catch all exceptions
  and return JSON error strings. creative_bridge.py parser
  handles malformed JSON (strips markdown fences, extracts
  wrapped JSON). game_loop.receive_creative_response() wraps
  in try/except with retry-once logic — on second failure, logs
  ERROR, broadcasts error event to UI, returns with
  retry_attempted flag. Auto-save runs after every travel+T&P
  cycle. WebSocket disconnect triggers auto-save from browser
  and shows toast notification. Reconnect shows success toast.
  All alert() calls replaced with toast notification system
  (DG-23). Error events broadcast via WebSocket for creative
  submit failures.
DEPENDS: DG-10, DG-12


## DG-24: Mobile Play via Web Proxy
STATUS: NOT STARTED
PRIORITY: High
PHASE: 2
DESCRIPTION: Enable mobile play by running a lightweight web
  server (Flask/FastAPI) on the desktop alongside the engine.
  The player chats with Claude via Claude.ai on mobile for
  narration, and hits the web server from a phone browser for
  all mechanical operations. Two windows, one game.
ARCHITECTURE:
  - Desktop engine already runs FastAPI (gammaria.py) — extend
    existing server rather than adding a second one
  - Exposed to local network, or tunnelled via Tailscale/ngrok
    for play outside the home
  - Mobile browser hits endpoints for mechanical ops
  - Claude.ai on mobile handles narration as normal
  - Desktop engine remains the single authoritative state
ENDPOINTS (minimum viable — many already exist as /api/*):
  - GET  /state         — current game state summary (date,
    zone, clocks, companions with PC, intensity)
  - POST /tp            — run T&P for N days, return results
  - POST /roll          — roll dice expression, return result
  - POST /advance_clock — advance named clock with reason
  - GET  /pending       — get pending LLM requests
  - POST /judge         — apply LLM judgments
  - POST /save          — save game
  - GET  /saves         — list available saves
  - POST /load          — load a save file
  - POST /set_zone      — set PC zone
MOBILE UI:
  - Single-page responsive web app, dark theme, touch-friendly
  - Top: compact state header (date, zone, intensity, critical
    clocks)
  - Main: buttons for core operations (Run T&P, Roll Dice,
    Save, Set Zone)
  - Bottom: scrolling log of recent engine actions
  - No narration here — that stays in Claude.ai chat
SECURITY:
  - Local network only by default
  - Optional auth token for tunnelled access
  - Read-only mode available (view state without mutation)
NOTES:
  - Fastest path to mobile play — buildable in a weekend,
    no dependency on Anthropic's MCP mobile roadmap
  - If Anthropic ships MCP on mobile Claude.ai later, this
    becomes a nice-to-have backup rather than the primary path
  - Player workflow on mobile: open Claude.ai, open browser
    tab to engine, play
  - Existing FastAPI server and /api/* routes mean much of the
    backend already exists — primary work is the mobile-
    responsive frontend
DEPENDS: DG-10, DG-14


## DG-29: Mobile Nudge Automation
STATUS: NOT STARTED
PRIORITY: Medium
PHASE: 2
DESCRIPTION: Address the "nudge problem" — Claude in chat does
  not automatically check for pending engine requests without
  player prompting. For mobile play this is especially painful.
  The web proxy (DG-24) can help: after mechanical operations
  complete, the mobile UI displays pending requests and their
  context clearly, so the player can copy/paste or dictate the
  key details into Claude.ai chat for creative resolution.
ALTERNATIVES EXPLORED:
  - Automatic MCP polling by Claude: not possible in chat mode
  - Engine auto-calling Claude API for pending requests: adds
    API cost, breaks the chat-based play model
  - Player-driven: mobile UI shows "2 pending requests —
    CLOCK_AUDIT_REVIEW, NPAG" with summaries. Player tells
    Claude in chat. Least elegant, most reliable.
NOTES:
  - Long-term, if the engine moves to API mode (DG-12), this
    solves itself — engine calls Claude directly for pending
    requests. For chat-based play, the nudge is inherent.
  - A "copy to clipboard" button on pending requests in the
    mobile UI would reduce friction significantly.
DEPENDS: DG-24


## DG-25: Token Economy ✅
STATUS: DONE
PRIORITY: Critical
PHASE: 1
DESCRIPTION: Minimise Claude calls per session. Every request
  must justify its cost. Engine provides focused context
  payloads, not bulk state. Design all request/response
  contracts with token cost in mind.
IMPLEMENTED: CreativeQueue.call_count tracks calls per session,
  displayed in web UI footer ("Claude calls: N/20") and header
  badge. Engine batches all pending creative requests into a
  single call per travel cycle rather than one call per request.
  Context payloads are focused (DG-20). MCP get_creative_requests
  batches all pending into one response, submit_creative_response
  processes all at once. Budget awareness: footer turns yellow at
  15 calls, red at 18 with toast warning. Header badge shows
  Calls: N/20 with safe/caution/danger color coding. Lore
  truncation budget: MAX_LORE_CHARS_PER_KEY=500,
  MAX_TOTAL_LORE_CHARS=2000 — excess lore keys dropped to
  control context size.
TARGETS:
  - Playable session on free tier: under 20 Claude calls
  - Measure and track calls per session as dev metric
  - No Claude call for any deterministic operation
  - Context payload per request: minimal viable context only
DEPENDS: DG-12, DG-20


## DG-26: Model Agnosticism ✅
STATUS: DONE (architecture principle maintained)
PRIORITY: Medium
PHASE: 1 (architecture principle, not a build task)
DESCRIPTION: Design the engine-to-LLM interface so Claude is
  not hardcoded. The request/response contract should work
  with any LLM that accepts structured prompts and returns
  structured output. This enables future local model fallback,
  alternative API providers, or community deployment without
  rewriting the engine.
IMPLEMENTED: CreativeRequest/CreativeResponse in
  creative_bridge.py are plain dataclasses with no
  Claude-specific fields. MCP server is a thin HTTP bridge —
  swapping Claude for another LLM requires only changing the
  MCP adapter, not the engine or contract. Legacy gui.py even
  supports clipboard-paste workflow to any LLM.
NOTES:
  - Not a build priority — an architecture principle
  - Costs nothing to maintain from the start
  - Enables: local models, other APIs, offline play (future)
DEPENDS: DG-12


## DG-27: PLAY Tab Side Panel ✅
STATUS: DONE
PRIORITY: High
PHASE: 1
DESCRIPTION: The main chat/narration column in the PLAY tab is
  too wide for comfortable reading. Add a persistent right-side
  panel that narrows the prose column to a readable width. The
  side panel contains two sections:
  a) PC stat block (compact) plus a short stat block for each
     companion currently with the PC (with_pc = yes). Companion
     cards appear/disappear dynamically as with_pc changes.
  b) Scrolling live log feed — mirrors the LOGS tab content so
     the player can watch mechanical actions alongside narration
     without switching tabs.
NOTES:
  - Panel should be collapsible (toggle button) for players who
    want full-width narration temporarily.
  - Stat blocks: HP, AC, key conditions, location. Not full
    character sheets — those live in PARTY tab.
  - Log section auto-scrolls but allows scroll-back.
  - Replaces the "collapsible split pane" note in DG-11 PLAY
    layout — this IS that pane, now specified.
DEPENDS: DG-11


## DG-28: Expanded Entity Cards in PARTY Tab
STATUS: DONE
PRIORITY: Medium
PHASE: 2
DESCRIPTION: The current PC and NPC/companion cards in the
  PARTY tab are too abbreviated. Expand them to show meaningful
  detail — more than the current compact display, less than the
  full HTML report dump. Target: enough information for the
  player to make informed decisions without leaving the tab.
IMPLEMENTED:
  - game_loop.py get_full_state(): expanded to expose all hidden
    fields from NPC, CompanionDetail, and PCState dataclasses.
  - Companion cards: click-to-expand detail view showing appearance,
    faction, trust/stress badges, motivation_shift, loyalty_change,
    grievances, future_flashpoints, agency_notes, full affection
    levels (all NPCs), knowledge, next_action, recent history.
  - PC card: click-to-expand showing psychological_state, secrets,
    affection_summary, reputation_levels (per-faction breakdown),
    recent history entries.
  - Other NPCs table: click-to-expand inline detail rows showing
    trait, appearance, faction, objective, next_action, BX stat
    line, knowledge.
  - Expand state persists across WebSocket re-renders via _expandedCards Set.
  - CSS: animated expand/collapse with chevron indicator, trust/stress
    status badges (color-coded), detail field layout system.
  - Compact view unchanged from previous implementation.
DEPENDS: DG-11, DG-19


# ═══════════════════════════════════════════════════════════════
# BUILD PHASES
# ═══════════════════════════════════════════════════════════════
#
# PHASE 1 — THE FLIP (Critical) — NEARLY COMPLETE
#   DG-10: Engine as outer loop              ✅ DONE
#   DG-11: Player UI                         ✅ DONE
#   DG-12: Claude as creative API            ✅ DONE
#   DG-14: Full T&P automation               ✅ DONE
#   DG-15: Full TRAVEL automation            ✅ DONE
#   DG-25: Token economy                     ✅ DONE
#   DG-26: Model agnosticism (principle)     ✅ DONE
#   DG-27: PLAY tab side panel               ✅ DONE
#   PROOF: Load save → detect zone → display CPs → player
#   clicks → travel → T&P → narrate. ← THIS WORKS END TO END.
#
# PHASE 2 — FULL AUTOMATION
#   DG-13: Full ZONE-FORGE automation        ✅ DONE
#   DG-16: Full combat automation            ✅ DONE
#   DG-17: Forge request protocol            ✅ DONE
#   DG-18: Clock creation via engine         ✅ DONE (absorbed into DG-17)
#   DG-19: Session lifecycle                 ✅ DONE
#   DG-20: Context management                ✅ DONE (lore_index.py + builder injection + sampling_adapter formatting)
#   DG-28: Expanded entity cards             ✅ DONE (click-to-expand PC/companion/NPC cards)
#   DG-24: Mobile play via web proxy         ○ NOT STARTED
#   DG-29: Mobile nudge automation           ○ NOT STARTED
#
# PHASE 3 — POLISH
#   DG-21: Standalone application            ✅ DONE
#   DG-22: Mode macro integration            ✅ DONE
#   DG-23: Graceful degradation              ✅ DONE
#
# ═══════════════════════════════════════════════════════════════
