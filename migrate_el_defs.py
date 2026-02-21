"""
One-time migration script: Parse all 38 EL-DEFs from docs/NSV-ENGINES.txt
and inject them into the game save's encounter_lists section.

Usage:
    python migrate_el_defs.py                          # dry-run, prints stats
    python migrate_el_defs.py --save data/save.json    # inject into save file
    python migrate_el_defs.py --dump                   # dump encounter_lists JSON to stdout
"""

import re
import json
import sys
import os
from pathlib import Path


# ─── Dice helpers ────────────────────────────────────────

def dice_max(randomizer: str) -> int:
    """Compute max value for a dice expression like '1d8' or '2d6'."""
    m = re.match(r"(\d+)d(\d+)", randomizer)
    if not m:
        return 6
    return int(m.group(1)) * int(m.group(2))


def dice_min(randomizer: str) -> int:
    """Compute min value for a dice expression."""
    m = re.match(r"(\d+)d(\d+)", randomizer)
    if not m:
        return 1
    return int(m.group(1))


# ─── BX-PLUG parser ─────────────────────────────────────

def parse_bx_plug_text(bx_text: str, bx_stats_lines: list) -> dict:
    """
    Parse BX-PLUG description text and stat lines into structured dict.
    Returns empty dict if no BX-PLUG present.
    """
    if not bx_text and not bx_stats_lines:
        return {}

    result = {}

    # Determine type
    text_lower = bx_text.lower() if bx_text else ""
    if "skill check" in text_lower:
        result["type"] = "skill_check"
        # Extract skill name from parentheses
        skill_match = re.search(r"Skill Check\s*\(([^)]+)\)", bx_text, re.IGNORECASE)
        if skill_match:
            result["skill"] = skill_match.group(1).strip()
        else:
            result["skill"] = None
    elif "save" in text_lower:
        result["type"] = "save"
        result["skill"] = None
        # Extract save damage: "take Xd6 damage" or "lose Xd6 hp" or "Xd6 Dmg"
        dmg_match = re.search(r"(\d+d\d+)\s*(?:damage|dmg|hp|fire damage)", text_lower)
        if dmg_match:
            result["save_damage"] = dmg_match.group(1)
        else:
            result["save_damage"] = None
    elif "reaction" in text_lower:
        result["type"] = "reaction"
        result["skill"] = None
        result["save_damage"] = None
        # Extract hostile action
        hostile_match = re.search(r"if hostile\s*[\u2192→>]\s*(.+?)(?:[;.]|$)", bx_text, re.IGNORECASE)
        if hostile_match:
            result["hostile_action"] = hostile_match.group(1).strip()
        else:
            result["hostile_action"] = None
    elif "combat" in text_lower:
        result["type"] = "combat"
        result["skill"] = None
        result["save_damage"] = None
    else:
        # Fallback: if we have stats but unclear type, assume reaction
        if bx_stats_lines:
            result["type"] = "reaction"
        else:
            return {}

    # Aggregate stats
    if bx_stats_lines:
        result["stats"] = "; ".join(bx_stats_lines)
    else:
        result["stats"] = None

    return result


# ─── Entry parser ────────────────────────────────────────

# Regex: entry starts with number or range like "5-6."
ENTRY_RE = re.compile(r"^(\d+(?:-\d+)?)\.\s+(.+)")

# Regex: BX stat line (starts with optional name, then AC=)
# Use .+? for name prefix to handle unicode apostrophes in names like Ush'n'Taalgith
BX_STAT_RE = re.compile(r"^(?:.+?:\s*)?(?:BX:\s*)?AC=\d+")

# Regex: standalone BX-PLUG line
BX_PLUG_LINE_RE = re.compile(r"^(?:Run\s+)?BX-PLUG:", re.IGNORECASE)

# Regex: Note line
NOTE_RE = re.compile(r"^\*\*Note:\*\*")


def parse_entries(lines: list, randomizer: str) -> list:
    """
    Parse entry lines into list of EncounterEntry dicts.
    Handles multi-line entries, BX-PLUG text, BX stats, [UA] tags.
    """
    max_val = dice_max(randomizer)

    # First pass: collect raw entries
    raw_entries = []  # list of (start_num, end_num_or_none, text_lines)
    current = None

    for line in lines:
        # Skip note lines
        if NOTE_RE.match(line):
            continue

        entry_match = ENTRY_RE.match(line)
        if entry_match:
            # Save previous entry
            if current:
                raw_entries.append(current)

            range_str = entry_match.group(1)
            text = entry_match.group(2)

            if "-" in range_str:
                parts = range_str.split("-")
                start = int(parts[0])
                end = int(parts[1])
            else:
                start = int(range_str)
                end = None  # will compute later

            current = {"start": start, "end": end, "lines": [text]}
        elif current is not None:
            # Continuation line for current entry
            current["lines"].append(line)

    # Don't forget last entry
    if current:
        raw_entries.append(current)

    # Second pass: compute implicit ranges
    for i, entry in enumerate(raw_entries):
        if entry["end"] is not None:
            continue  # explicit range already set

        if i + 1 < len(raw_entries):
            next_start = raw_entries[i + 1]["start"]
            gap = next_start - entry["start"]
            if gap > 1:
                entry["end"] = next_start - 1
            else:
                entry["end"] = entry["start"]
        else:
            # Last entry: extend to max die value
            if entry["start"] < max_val:
                entry["end"] = max_val
            else:
                entry["end"] = entry["start"]

    # Third pass: parse each entry into structured format
    entries = []
    for entry in raw_entries:
        start = entry["start"]
        end = entry["end"]
        if start == end:
            range_str = str(start)
        else:
            range_str = f"{start}-{end}"

        # Separate prompt text from BX-PLUG text and BX stats
        prompt_parts = []
        bx_plug_text_parts = []
        bx_stats = []
        ua_cue = False

        for line in entry["lines"]:
            # Check for [UA] tag
            if "[UA]" in line:
                ua_cue = True
                line = line.replace("[UA]", "").strip()

            # Check if line is a BX stat line
            if BX_STAT_RE.match(line.strip()):
                # Clean up: remove leading "BX: " if present
                stat_text = line.strip()
                # Normalize: if it starts with "BX: ", strip it
                stat_text = re.sub(r"^BX:\s*", "", stat_text)
                bx_stats.append(stat_text)
                continue

            # Check if line is a standalone BX-PLUG line
            if BX_PLUG_LINE_RE.match(line.strip()):
                plug_text = re.sub(r"^(?:Run\s+)?BX-PLUG:\s*", "", line.strip(), flags=re.IGNORECASE)
                bx_plug_text_parts.append(plug_text)
                continue

            # Check if line contains inline BX-PLUG
            bx_inline = re.search(r"(?:Run\s+)?BX-PLUG:\s*(.+?)$", line, re.IGNORECASE)
            if bx_inline:
                # Split: text before is prompt, text after is BX-PLUG
                prompt_part = line[:bx_inline.start()].strip()
                if prompt_part:
                    prompt_parts.append(prompt_part)
                bx_plug_text_parts.append(bx_inline.group(1).strip())
                continue

            # Regular prompt text
            if line.strip():
                prompt_parts.append(line.strip())

        prompt = " ".join(prompt_parts).strip()
        # Clean up trailing/leading punctuation artifacts
        prompt = prompt.rstrip(";").strip()

        bx_plug_text = " ".join(bx_plug_text_parts).strip()
        bx_plug = parse_bx_plug_text(bx_plug_text, bx_stats)

        # If bx_plug is empty but we have stats, create minimal plug
        if not bx_plug and bx_stats:
            bx_plug = {
                "type": "reaction",
                "stats": "; ".join(bx_stats),
            }

        entries.append({
            "range": range_str,
            "prompt": prompt,
            "ua_cue": ua_cue,
            "bx_plug": bx_plug if bx_plug else {},
        })

    return entries


# ─── Block parser ────────────────────────────────────────

def parse_all_el_defs(filepath: str) -> dict:
    """
    Parse all EL-DEF blocks from NSV-ENGINES.txt.
    Returns dict keyed by zone name.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    encounter_lists = {}
    in_block = False
    block_lines = []

    for line in lines:
        stripped = line.strip()

        if stripped == "EL-DEF":
            in_block = True
            block_lines = []
            continue

        if stripped == "END EL-DEF":
            if block_lines:
                el = parse_single_block(block_lines)
                if el:
                    encounter_lists[el["zone"]] = el
            in_block = False
            continue

        if in_block:
            block_lines.append(stripped)

    return encounter_lists


def parse_single_block(lines: list) -> dict:
    """Parse a single EL-DEF block into an EncounterList dict."""
    # Find the header line
    header_line = None
    header_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("EL:"):
            header_line = line
            header_idx = i
            break

    if not header_line:
        return None

    # Parse header: "EL: Zone Name | dice | FP:N | adjacency notes"
    parts = header_line.split("|")
    if len(parts) < 3:
        return None

    zone = parts[0].replace("EL:", "").strip()
    randomizer = parts[1].strip()
    fp_str = parts[2].strip()
    fp_match = re.search(r"FP:(\d+)", fp_str)
    fp = int(fp_match.group(1)) if fp_match else 1
    adjacency = parts[3].strip() if len(parts) > 3 else ""

    # Parse entries from remaining lines
    entry_lines = [l for l in lines[header_idx + 1:] if l]
    entries = parse_entries(entry_lines, randomizer)

    return {
        "zone": zone,
        "randomizer": randomizer,
        "fallback_priority": fp,
        "adjacency_notes": adjacency,
        "entries": entries,
    }


# ─── Main ────────────────────────────────────────────────

def main():
    script_dir = Path(__file__).parent
    engines_path = script_dir / "docs" / "NSV-ENGINES.txt"

    if not engines_path.exists():
        print(f"ERROR: {engines_path} not found")
        sys.exit(1)

    encounter_lists = parse_all_el_defs(str(engines_path))

    # Print stats
    print(f"\nParsed {len(encounter_lists)} EL-DEFs:")
    print("-" * 60)
    total_entries = 0
    for zone, el in sorted(encounter_lists.items()):
        n = len(el["entries"])
        total_entries += n
        print(f"  {zone:40s} {el['randomizer']:5s} FP:{el['fallback_priority']}  {n} entries")
    print("-" * 60)
    print(f"  Total: {len(encounter_lists)} zones, {total_entries} entries")

    # Handle CLI args
    if "--dump" in sys.argv:
        print("\n" + json.dumps(encounter_lists, indent=2, ensure_ascii=False))
        return

    if "--save" in sys.argv:
        save_idx = sys.argv.index("--save")
        if save_idx + 1 >= len(sys.argv):
            print("ERROR: --save requires a file path argument")
            sys.exit(1)
        save_path = sys.argv[save_idx + 1]

        if not os.path.exists(save_path):
            print(f"ERROR: Save file not found: {save_path}")
            sys.exit(1)

        with open(save_path, "r", encoding="utf-8") as f:
            save_data = json.load(f)

        # Inject encounter_lists
        save_data["encounter_lists"] = encounter_lists

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)

        print(f"\nInjected {len(encounter_lists)} EL-DEFs into {save_path}")
        return

    print("\nDry run complete. Use --dump to see JSON, --save <path> to inject into save.")


if __name__ == "__main__":
    main()
