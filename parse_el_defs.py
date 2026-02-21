#!/usr/bin/env python3
"""
Parse EL-DEF blocks from NSV-ENGINES.txt and inject them into session JSON
as encounter_lists.
"""

import json
import re
import sys

ENGINES_PATH = r"C:/Users/logar/Documents/Gaming/GAMMARIA NSV/macros-engine/docs/NSV-ENGINES.txt"
SESSION_PATH = r"C:/Users/logar/Documents/Gaming/GAMMARIA NSV/macros-engine/data/Session 11 - 29 Ilrym - Vornost.json"


def extract_el_def_blocks(text_lines):
    """Extract raw line groups between EL-DEF and END EL-DEF."""
    blocks = []
    current = None
    for line in text_lines:
        stripped = line.rstrip("\n").rstrip("\r")
        if stripped.strip() == "EL-DEF":
            current = []
        elif stripped.strip() == "END EL-DEF":
            if current is not None:
                blocks.append(current)
            current = None
        elif current is not None:
            current.append(stripped)
    return blocks


def parse_header(header_line):
    """
    Parse: EL: Zone Name | dice | FP:N | adjacency notes
    Returns (zone_name, randomizer, fallback_priority, adjacency_notes)
    """
    m = re.match(r"EL\s*:\s*(.+)", header_line.strip())
    if not m:
        return None, None, None, None
    rest = m.group(1)
    parts = [p.strip() for p in rest.split("|")]
    zone_name = parts[0] if len(parts) > 0 else ""
    randomizer = parts[1] if len(parts) > 1 else ""
    fp_str = parts[2] if len(parts) > 2 else "FP:1"
    adjacency = parts[3] if len(parts) > 3 else ""

    fp_match = re.search(r"FP\s*:\s*(\d+)", fp_str)
    fallback_priority = int(fp_match.group(1)) if fp_match else 1

    return zone_name, randomizer, fallback_priority, adjacency


def is_bx_stats_line(line):
    """Check if a line is a BX stats line (contains AC= pattern and is not a Run line)."""
    stripped = line.strip()
    if stripped.lower().startswith("run"):
        return False
    if re.search(r"AC\s*=\s*\d+", stripped):
        return True
    if re.match(r".*BX\s*:\s*AC\s*=", stripped):
        return True
    return False


def extract_bx_stats(line):
    """Extract the raw stats string from a BX line."""
    return line.strip()


def classify_run_line(line):
    """
    Classify a Run BX-PLUG line or bare BX-PLUG line.
    Returns a bx_plug dict fragment or None.
    """
    stripped = line.strip()
    # Match "Run BX-PLUG:" or "BX-PLUG:" (without Run)
    if not re.match(r"(Run\s+)?BX-PLUG\s*:", stripped, re.IGNORECASE):
        return None

    lower = stripped.lower()
    if "skill check" in lower:
        m = re.search(r"Skill\s+Check\s*(\([^)]*\))?\s*(.*)", stripped, re.IGNORECASE)
        desc = stripped
        if m:
            skill_type = m.group(1) or ""
            remainder = m.group(2) or ""
            desc = ("Skill Check " + skill_type + " " + remainder).strip()
        return {"type": "skill", "description": desc}
    elif "save" in lower:
        # Extract the Save description
        m = re.search(r"(Save\s*.+)", stripped, re.IGNORECASE)
        desc = m.group(0).strip() if m else stripped
        return {"type": "save", "description": desc}
    elif "combat" in lower:
        return {"type": "combat", "stats": ""}
    elif "reaction" in lower:
        return {"type": "reaction"}
    else:
        return {"type": "reaction"}


def parse_block(lines):
    """Parse a single EL-DEF block into structured dict."""
    if not lines:
        return None

    zone_name, randomizer, fp, adjacency = parse_header(lines[0])
    if zone_name is None:
        return None

    entries = []
    current_entry = None

    # Pattern for numbered entry: "1." or "1-2." or "9-10."
    entry_pat = re.compile(r"^\s*(\d+(?:\s*[-\u2013]\s*\d+)?)\.\s+(.+)")

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue

        # Check if this is a new numbered entry
        em = entry_pat.match(stripped)
        if em:
            if current_entry is not None:
                entries.append(current_entry)

            range_str = em.group(1).replace("\u2013", "-").replace(" ", "")
            prompt_text = em.group(2).strip()
            ua_cue = "[UA]" in prompt_text

            current_entry = {
                "range": range_str,
                "prompt": prompt_text,
                "ua_cue": ua_cue,
                "bx_plug": {}
            }
            continue

        if current_entry is None:
            continue

        # Check if it is a BX stats line
        if is_bx_stats_line(stripped):
            stats_str = extract_bx_stats(stripped)
            if not current_entry["bx_plug"].get("type"):
                current_entry["bx_plug"]["type"] = "combat"
            if current_entry["bx_plug"].get("stats"):
                current_entry["bx_plug"]["stats"] += "\n" + stats_str
            else:
                current_entry["bx_plug"]["stats"] = stats_str
            continue

        # Check if it is a Run BX-PLUG line (or bare BX-PLUG:)
        run_result = classify_run_line(stripped)
        if run_result is not None:
            if not current_entry["bx_plug"]:
                current_entry["bx_plug"] = run_result
            else:
                existing_type = current_entry["bx_plug"].get("type", "")
                new_type = run_result.get("type", "")
                priority = {"combat": 4, "skill": 3, "save": 2, "reaction": 1}
                if priority.get(new_type, 0) >= priority.get(existing_type, 0):
                    old_stats = current_entry["bx_plug"].get("stats")
                    current_entry["bx_plug"].update(run_result)
                    if old_stats and "stats" not in run_result:
                        current_entry["bx_plug"]["stats"] = old_stats
            current_entry["prompt"] += "\n" + stripped
            continue

        # Otherwise it is continuation text for the current entry prompt
        current_entry["prompt"] += "\n" + stripped

    if current_entry is not None:
        entries.append(current_entry)

    return {
        "zone": zone_name,
        "randomizer": randomizer,
        "fallback_priority": fp,
        "adjacency_notes": adjacency,
        "entries": entries
    }


def main():
    # 1. Read engines file
    with open(ENGINES_PATH, "r", encoding="utf-8") as f:
        text_lines = f.readlines()

    # 2. Extract EL-DEF blocks
    raw_blocks = extract_el_def_blocks(text_lines)
    print(f"Found {len(raw_blocks)} raw EL-DEF blocks")

    # 3. Parse each block
    encounter_lists = {}
    total_entries = 0
    for block_lines in raw_blocks:
        parsed = parse_block(block_lines)
        if parsed is None:
            first = block_lines[0] if block_lines else "(empty)"
            print(f"  WARNING: Could not parse block starting with: {first}")
            continue
        zone = parsed["zone"]
        encounter_lists[zone] = parsed
        total_entries += len(parsed["entries"])
        print(f"  Parsed: {zone} ({len(parsed['entries'])} entries, dice={parsed['randomizer']})")

    print(f"\nTotal zones parsed: {len(encounter_lists)}")
    print(f"Total entries across all zones: {total_entries}")

    # 4. Read session JSON
    with open(SESSION_PATH, "r", encoding="utf-8") as f:
        session_data = json.load(f)

    # 5. Inject encounter_lists
    session_data["encounter_lists"] = encounter_lists

    # 6. Write back
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)

    print(f"\nWrote encounter_lists to: {SESSION_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()
