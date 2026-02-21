# MACROS Engine v1.0

A deterministic mechanical engine for the MACROS 3.0 tabletop RPG system.
Handles clocks, procedural engines, T&P day loops, and dice rolls with
full audit logging. Calls Claude only when creative judgment is needed.

## Requirements

- Python 3.10+ (no external packages needed)

## Quick Start

```
# Show current campaign status
python main.py --status

# Run 1 day of Time & Pressure
python main.py

# Run 3 days (e.g., Caras -> Khuzdukan travel)
python main.py 3

# Save state to JSON
python main.py --save
```

## What It Does

The engine executes the T&P day loop **deterministically**:

1. **Advance date** (Nurrian calendar, season tracking)
2. **Run cadence engines** (VP, TSDD, HT-DH, SRP)
3. **Advance cadence clocks** (Binding Degradation "Decay", Lithoe research, etc.)
4. **CLOCK AUDIT** — scans ALL active clocks against established facts
5. **Encounter gate** — rolls 1d6 vs intensity threshold
6. **NPAG gate** — rolls 1d6 vs intensity threshold

### What the engine handles (no LLM needed):
- All dice rolls with full audit trail
- Clock advances, reductions, halts, trigger fires
- Engine hard gate checks
- VP outcome band mapping → clock effects
- Encounter/NPAG gate passes
- Date/season tracking
- Complete adjudication logging

### What gets flagged for Claude:
- NPAG content (what do NPCs actually *do*?)
- Encounter narration
- Ambiguous clock audit bullets (needs judgment)
- CAN-FORGE-AUTO (VP roll=12 creates UA threat)
- Session narration

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point — run from command line |
| `models.py` | Data models: Clock, Engine, Zone, GameState |
| `dice.py` | Dice roller with audit logging |
| `engine.py` | T&P day loop, engine runners, clock audit |
| `campaign_state.py` | **EDIT THIS** — your campaign's current state |
| `data/` | Saved state files (JSON) |

## Editing Campaign State

Open `campaign_state.py` to update between sessions:

- Add/remove clocks
- Update clock progress
- Change PC zone
- Add new engines
- Update zones

The state file is plain Python — readable and editable.

## What's Next (v2.0 roadmap)

- [ ] Claude API integration (send LLM requests automatically)
- [ ] Encounter list loading from NSV-ENGINES
- [ ] GUI dashboard (clock visualizations, timeline)
- [ ] NPAG NPC selection from delta
- [ ] BX-PLUG combat runner
- [ ] Zone travel route calculator
- [ ] Delta file export (generate NSV-DELTA text format)
- [ ] Session management (start/end session procedures)
