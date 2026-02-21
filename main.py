"""
MACROS Engine v1.0 — Main Entry Point
Run this to execute T&P day loops for the Gammaria campaign.

Usage:
    python main.py              # Run 1 day
    python main.py 3            # Run 3 days (Caras -> Khuzdukan travel)
    python main.py --status     # Show current state
    python main.py --save       # Save state to JSON
"""

import sys
import json
from campaign_state import load_gammaria_state
from engine import run_time_and_pressure
from models import state_to_json


def show_status(state):
    """Print current campaign status."""
    print(f"\n{'═'*60}")
    print(f"  MACROS ENGINE v1.0 — GAMMARIA CAMPAIGN STATUS")
    print(f"{'═'*60}")
    print(f"  Session: {state.session_id}")
    print(f"  Date: {state.in_game_date}")
    print(f"  PC Zone: {state.pc_zone}")
    print(f"  Intensity: {state.campaign_intensity}")
    print(f"  Season: {state.season}")
    print(f"{'─'*60}")

    # Active clocks sorted by urgency (progress/max ratio)
    active = [c for c in state.clocks.values() if c.status == "active"]
    active.sort(key=lambda c: c.progress / max(c.max_progress, 1), reverse=True)

    print(f"\n  ACTIVE CLOCKS ({len(active)}):")
    for clock in active:
        bar_len = 20
        filled = int((clock.progress / clock.max_progress) * bar_len) if clock.max_progress > 0 else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        pct = (clock.progress / clock.max_progress * 100) if clock.max_progress > 0 else 0

        # Color code by urgency
        if pct >= 75:
            urgency = "🔴"
        elif pct >= 50:
            urgency = "🟡"
        else:
            urgency = "🟢"

        cadence_tag = " ⏰" if clock.is_cadence else ""
        print(f"  {urgency} {clock.name}: [{bar}] {clock.progress}/{clock.max_progress} ({pct:.0f}%){cadence_tag}")

    # Fired triggers
    fired = [c for c in state.clocks.values() if c.trigger_fired]
    if fired:
        print(f"\n  TRIGGERS FIRED ({len(fired)}):")
        for clock in fired:
            print(f"  🔥 {clock.name}")

    # Halted clocks
    halted = [c for c in state.clocks.values() if c.status == "halted"]
    if halted:
        print(f"\n  HALTED ({len(halted)}):")
        for clock in halted:
            print(f"  ⏸️  {clock.name}: {clock.progress}/{clock.max_progress}")

    # Engines
    print(f"\n  ENGINES:")
    for engine in state.engines.values():
        if engine.status == "active":
            print(f"  ⚙️  {engine.name} [{engine.version}] — ACTIVE")
        elif engine.status == "dormant":
            print(f"  💤 {engine.name} [{engine.version}] — DORMANT")
        else:
            print(f"  ⬛ {engine.name} [{engine.version}] — {engine.status.upper()}")

    print(f"\n{'═'*60}")


def main():
    args = sys.argv[1:]

    # Load state
    state = load_gammaria_state()

    if "--status" in args:
        show_status(state)
        return

    if "--save" in args:
        json_str = state_to_json(state)
        with open("data/campaign_state.json", "w") as f:
            f.write(json_str)
        print(f"State saved to data/campaign_state.json")
        return

    # Determine number of days
    days = 1
    for arg in args:
        try:
            days = int(arg)
            break
        except ValueError:
            pass

    print(f"\n{'═'*60}")
    print(f"  MACROS ENGINE v1.0 — TIME & PRESSURE")
    print(f"  Running {days} day(s) from {state.in_game_date}")
    print(f"  PC Zone: {state.pc_zone}")
    print(f"  Intensity: {state.campaign_intensity}")
    print(f"{'═'*60}")

    # Run T&P
    results = run_time_and_pressure(state, days)

    # Summary
    print(f"\n{'═'*60}")
    print(f"  T&P COMPLETE — {days} day(s) processed")
    print(f"  Final date: {state.in_game_date}")
    print(f"{'═'*60}")

    # Collect all LLM requests
    all_llm = []
    for day in results:
        all_llm.extend(day.get("llm_requests", []))

    if all_llm:
        print(f"\n  📋 PENDING LLM REQUESTS ({len(all_llm)}):")
        print(f"  These need Claude's creative judgment:")
        for i, req in enumerate(all_llm, 1):
            print(f"  {i}. [{req['type']}] {req.get('context', '')}")

    # Show final clock states
    print(f"\n  CLOCK STATES AFTER T&P:")
    for clock in sorted(state.active_clocks(), key=lambda c: c.name):
        changed = " ← CHANGED" if clock.advanced_this_session else ""
        print(f"  📊 {clock.name}: {clock.progress}/{clock.max_progress}{changed}")

    # Save results
    with open("data/tp_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to data/tp_results.json")

    # Save final state
    json_str = state_to_json(state)
    with open("data/campaign_state_post_tp.json", "w") as f:
        f.write(json_str)
    print(f"  Final state saved to data/campaign_state_post_tp.json")


if __name__ == "__main__":
    main()
