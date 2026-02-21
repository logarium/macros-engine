# GAMMARIA STANDALONE ENGINE — DESIGN GOALS v2.1
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
  - FORGE tab: no stepwise input UI yet.
  - Combat UI: no ATTACK/FLEE/companion order buttons in PLAY.
  - No portrait space rendered.
  - No "Export Report" button on TRACK.
  - Side panel (see DG-27) not implemented.
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
STATUS: NOT STARTED
PRIORITY: High
PHASE: 2
DESCRIPTION: Engine runs the entire ZONE-FORGE cascade
  deterministically: validate zone name, check controlling
  faction, count NPCs in zone, check EL-DEF exists, check UA
  active. Only calls Claude for creative fill (forge atoms)
  when a gap is detected.
DEPENDS: DG-10, DG-12


## DG-14: Full T&P Automation
STATUS: PARTIALLY DONE — substantial
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
REMAINING:
  - Clock interaction evaluation per NSV-CLOCKS rules (the
    seven interaction rules)
  - HALT trigger evaluation from interaction effects not wired
  - Automatic cadence suppression for halted clocks


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


## DG-16: Full Combat Automation
STATUS: NOT STARTED
PRIORITY: High
PHASE: 2
DESCRIPTION: Engine runs BX-PLUG: initiative rolls, attack
  resolution, damage application, morale triggers, allied
  combatant targeting AI, flee logic. Calls Claude only for
  narration between rounds or at combat end. Player choices
  via UI buttons (ATTACK/FLEE/companion orders).
DEPENDS: DG-10, DG-11, DG-12


## DG-17: Forge Request Protocol
STATUS: NOT STARTED
PRIORITY: High
PHASE: 2
DESCRIPTION: Standardise the structured input/output format
  for all forges (NPC-FORGE, EL-FORGE, FAC-FORGE, CAN-FORGE,
  CL-FORGE, PE-FORGE, UA-FORGE). Engine assembles inputs from
  game state, sends to Claude as structured request, receives
  structured atoms, validates, commits to JSON save.
NOTES:
  - Each forge has defined required/optional inputs
  - Engine pre-fills all deterministic inputs
  - Claude provides only creative content
  - Engine validates output before committing
DEPENDS: DG-12, DG-13


## DG-18: Clock Creation via Engine
STATUS: NOT STARTED
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


## DG-19: Session Lifecycle
STATUS: NOT STARTED
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
DEPENDS: DG-10, DG-13, DG-12


## DG-20: Context Management
STATUS: PARTIALLY DONE
PRIORITY: High
PHASE: 2
DESCRIPTION: Engine controls what Claude sees per request.
  Instead of bulk-loading project files, engine assembles a
  focused context payload: only the lore, NPC data, clock
  states, and zone info relevant to the specific creative
  task. Keeps Claude's context lean and token-efficient.
IMPLEMENTED: creative_bridge.py builders already assemble
  focused payloads per request type:
  - NARR_ARRIVAL: zone data, present NPCs, companions,
    season, seasonal pressure, date, last 5 daily_facts
  - NARR_ENCOUNTER: zone, encounter desc, bx_plug flag, tags
  - CLOCK_AUDIT: clock name, progress, ambiguous bullets, facts
  - NPAG: npc_count, eligible NPCs (capped at 20), pc_zone, date
REMAINING:
  - No lore-file injection — Claude receives structured state
    fields only, not passages from docs/ lore files
  - FORGE context payloads not yet built
  - DIALOGUE context payloads not yet built
DEPENDS: DG-12, DG-25


## DG-21: Standalone Application
STATUS: PARTIALLY DONE
PRIORITY: Medium
PHASE: 3
DESCRIPTION: Package as a desktop application that launches,
  starts the MCP server, connects to Claude, and presents
  the full game UI. Player double-clicks an icon and plays.
  No manual setup, no copying files, no pasting state.
IMPLEMENTED: gammaria.py launches FastAPI server + opens
  browser automatically. Single command launch: python
  gammaria.py. install_mcp.bat and setup_helper.py provide
  assisted MCP setup.
REMAINING:
  - Not packaged (no PyInstaller, no .exe, no icon)
  - MCP server must be configured separately in Claude Desktop
  - Not a true double-click-and-play experience yet
DEPENDS: DG-10, DG-11, DG-16, DG-19


## DG-22: Mode Macro Integration
STATUS: NOT STARTED
PRIORITY: Low
PHASE: 3
DESCRIPTION: Engine detects or accepts mode triggers (INTENS,
  INTIM, INVESTIG, NARR-D, RUMOR) and adjusts request
  parameters to Claude accordingly. Modes modify the creative
  brief sent to Claude, not the mechanical loop.
DEPENDS: DG-12


## DG-23: Graceful Degradation
STATUS: PARTIALLY DONE
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
  in try/except. Auto-save runs after every travel+T&P cycle.
REMAINING:
  - No "retry once then flag for player ruling" logic
  - Errors logged server-side but not surfaced to browser UI
  - No clean session-save triggered by MCP disconnection
DEPENDS: DG-10, DG-12


## DG-24: Mobile Play via Remote Bridge
STATUS: NOT STARTED — DEFERRED
PRIORITY: Low
PHASE: 4
DESCRIPTION: Enable play from mobile by connecting to the
  running desktop engine remotely. Investigate options: expose
  MCP server over local network, remote desktop relay,
  lightweight web UI served by desktop engine, or mobile app
  as thin client sending player choices to desktop instance.
  Desktop engine remains authoritative.
CONDITION: Deferred until DG-21 is stable.


## DG-25: Token Economy
STATUS: PARTIALLY DONE
PRIORITY: Critical
PHASE: 1
DESCRIPTION: Minimise Claude calls per session. Every request
  must justify its cost. Engine provides focused context
  payloads, not bulk state. Design all request/response
  contracts with token cost in mind.
IMPLEMENTED: CreativeQueue.call_count tracks calls per session,
  displayed in web UI footer ("Claude calls: N"). Engine batches
  all pending creative requests into a single call per travel
  cycle rather than one call per request. Context payloads are
  focused (DG-20). MCP get_creative_requests batches all pending
  into one response, submit_creative_response processes all at
  once.
REMAINING:
  - No formal per-session target enforcement (spec says <20)
  - No token counting per request
  - No context trimming logic
  - No per-request token budget enforcement
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


## DG-27: PLAY Tab Side Panel
STATUS: NOT STARTED
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
STATUS: PARTIALLY DONE
PRIORITY: Medium
PHASE: 2
DESCRIPTION: The current PC and NPC/companion cards in the
  PARTY tab are too abbreviated. Expand them to show meaningful
  detail — more than the current compact display, less than the
  full HTML report dump. Target: enough information for the
  player to make informed decisions without leaving the tab.
INCLUDES:
  - PC card: stats, goals, psychological state, reputation,
    active conditions, key relationships, recent history notes.
  - Companion cards: stats, motivation, loyalty/trust, current
    objective, affection level, grievances, stress/fatigue,
    personality sketch, relationship to PC summary.
  - NPC cards (when inspected): role, faction, disposition to
    PC, objective, knowledge state, last known action.
IMPLEMENTED: app.js renderParty() — companion cards show:
  name, "WITH YOU" badge, class/level, BX stat line
  (AC/HD/HP/AT/Dmg/ML), zone, trait, objective, affection
  level toward Thoron. PC card shows: name, class_level,
  stats, zone, reputation, conditions, equipment notes, goals.
  Other NPCs appear as data table (name/zone/role/status).
REMAINING:
  - No portrait images
  - CompanionDetail fields not fully surfaced (motivation_shift,
    grievances, future_flashpoints, stress_or_fatigue missing)
  - No expandable/collapsible card views
NOTES:
  - Cards should be expandable/collapsible — summary view by
    default, full view on click.
  - Data pulled live from JSON save, not cached.
  - HTML report remains the exhaustive reference; PARTY cards
    are the "working view" for active play.
DEPENDS: DG-11, DG-19


# ═══════════════════════════════════════════════════════════════
# BUILD PHASES
# ═══════════════════════════════════════════════════════════════
#
# PHASE 1 — THE FLIP (Critical) — NEARLY COMPLETE
#   DG-10: Engine as outer loop              ✅ DONE
#   DG-11: Player UI                         ◐ PARTIAL (FORGE stub, no combat UI)
#   DG-12: Claude as creative API            ✅ DONE
#   DG-14: Full T&P automation               ◐ PARTIAL (clock interactions missing)
#   DG-15: Full TRAVEL automation            ✅ DONE
#   DG-25: Token economy                     ◐ PARTIAL (tracking works, no budgets)
#   DG-26: Model agnosticism (principle)     ✅ DONE
#   DG-27: PLAY tab side panel               ○ NOT STARTED
#   PROOF: Load save → detect zone → display CPs → player
#   clicks → travel → T&P → narrate. ← THIS WORKS END TO END.
#
# PHASE 2 — FULL AUTOMATION
#   DG-13: Full ZONE-FORGE automation        ○ NOT STARTED
#   DG-16: Full combat automation            ○ NOT STARTED
#   DG-17: Forge request protocol            ○ NOT STARTED
#   DG-18: Clock creation via engine         ○ NOT STARTED
#   DG-19: Session lifecycle                 ○ NOT STARTED
#   DG-20: Context management                ◐ PARTIAL (builders done, no lore injection)
#   DG-28: Expanded entity cards             ◐ PARTIAL (basic cards, no expand/collapse)
#
# PHASE 3 — POLISH
#   DG-21: Standalone application            ◐ PARTIAL (works, not packaged)
#   DG-22: Mode macro integration            ○ NOT STARTED
#   DG-23: Graceful degradation              ◐ PARTIAL (error handling, no retry/flag)
#
# PHASE 4 — MOBILE
#   DG-24: Mobile play via remote bridge     ○ DEFERRED
#
# ═══════════════════════════════════════════════════════════════
