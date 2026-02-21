# TASK: Migrate EL-DEFs from NSV-ENGINES into JSON Save

## Problem
The MACROS engine's ZONE-FORGE detects missing EL-DEFs because it only reads the JSON save file. EL-DEFs currently live in `NSV-ENGINES.txt` (a project knowledge file). The engine cannot access project knowledge — only Claude can. All deterministic elements must be engine-owned.

## Goal
1. Add an `encounter_lists` section to the JSON save schema
2. Populate it with all EL-DEFs extracted from `NSV-ENGINES.txt`
3. Engine reads EL-DEFs from save, rolls encounters mechanically
4. EL-FORGE (when run by Claude) writes new EL-DEFs to the save via MCP
5. ZONE-FORGE gap detection resolves when EL-DEF is present in save

## Schema Design

Add top-level key `"encounter_lists"` to JSON save. Structure:

```json
{
  "encounter_lists": {
    "Vornost": {
      "el_name": "Vornost",
      "zone": "Vornost",
      "randomizer": "1d10",
      "fallback_priority": 1,
      "adjacency_notes": "fortress-capital, Black Fortress, military heart, court intrigue",
      "entries": {
        "1": {
          "range": "1-2",
          "prompt": "Guard inspection hardens - papers demanded, questioning aggressive; someone's orders, but whose",
          "ua_cue": true,
          "bx_plug": null
        },
        "2": {
          "range": "3",
          "prompt": "Court summons - messenger seeks you, or Castellan Joppa requests audience; ignore at your peril",
          "ua_cue": false,
          "bx_plug": null
        },
        "3": {
          "range": "9",
          "prompt": "Dragon! Young white dragon departs, returns, roosts (Soreth)",
          "ua_cue": false,
          "bx_plug": {
            "type": "reaction",
            "hostile_action": "roars in defiance, then flies quickly away",
            "stats": "AC=17, HD=7, hp=35/35, AT=+7, Dmg=3d8, ML=5"
          }
        }
      }
    }
  }
}
```

### Key design decisions:
- **Key by zone name** — matches engine's zone lookup
- **`range` field** — handles entries like "1-2" or "5-6" or "9-10" that map multiple roll results to one entry
- **`ua_cue`** — boolean flag for entries marked [UA] in source
- **`bx_plug`** — nullable; contains BX stats and plug type when combat/save/skill check is specified
- **`randomizer`** — dice expression string (1d6, 1d8, 1d10, 2d6)
- **`fallback_priority`** — integer, used when multiple EL-DEFs could apply

## Source Data

All EL-DEFs are in `/mnt/project/NSV-ENGINES.txt`, lines 159-738. The complete list of zones with EL-DEFs:

| Zone | Randomizer | FP | Entries |
|------|-----------|-----|---------|
| Blacktooth Forest | 1d8 | 1 | 8 |
| Caras | 2d6 | 1 | 11 |
| Deep Swamps | 2d6 | 1 | 11 |
| East March | 1d8 | 1 | 8 |
| Eastern Scarps | 1d8 | 2 | 8 |
| Fisher's Beach | 1d6 | 1 | 6 |
| Floodplain | 1d8 | 3 | 8 |
| Forgaard | 1d6 | 2 | 6 |
| Fort Amon | 1d6 | 2 | 6 |
| Fort Highguard | 1d6 | 2 | 6 |
| Fort Seawatch - Docks and Alleys | 2d6 | 1 | 11 |
| Fort Seawatch | 1d10 | 1 | 10 |
| Fort Vanguard | 1d8 | 1 | 8 |
| Fort Vanguard - Yards & Approaches | 1d6 | 2 | 6 |
| Furdach | 1d6 | 2 | 6 |
| Furdach Forest | 1d6 | 2 | 6 |
| Gloatburrow Hills | 2d6 | 4 | 11 |
| Grey Plains | 1d8 | 1 | 8 |
| Hanging Cliffs | 1d6 | 2 | 6 |
| Hinterlands | 1d6 | 1 | 6 |
| Khuzduk Hills | 1d8 | 2 | 8 |
| Khuzduk Peaks | 1d6 | 3 | 6 |
| Khuzdukan | 1d8 | 3 | 8 |
| Narrows | 1d6 | 3 | 6 |
| River of Birds | 1d6 | 1 | 6 |
| Riverlands | 1d6 | 1 | 6 |
| Riverwatch | 1d8 | 1 | 8 |
| Sea of Birds | 2d6 | 3 | 11 |
| Seawatch Ramparts | 1d8 | 1 | 8 |
| Sighing Swamps | 1d8 | 1 | 8 |
| Southern Scarps | 1d6 | 2 | 6 |
| Southern Shore | 1d6 | 1 | 6 |
| Temple of the Sun | 1d8 | 2 | 8 |
| Vallandor Mountains | 1d8 | 4 | 8 |
| Vargol's Reach | 1d8 | 2 | 8 |
| Vornost | 1d10 | 1 | 10 |
| Western Scarps | 1d6 | 3 | 6 |
| Whiteagle Keep | 1d8 | 2 | 8 |

**Total: 38 EL-DEFs**

## Engine Changes Required

### 1. Save schema (dataclass)
Add `encounter_lists: dict` to the save model. Each value is an `EncounterList` dataclass.

### 2. ZONE-FORGE gap detection
Change from "No EL-DEF for zone" gap to checking `save.encounter_lists.get(zone_name)`. If present, no gap. If absent, queue EL-FORGE request.

### 3. Encounter rolling
When T&P or TRAVEL triggers an encounter roll:
1. Look up `encounter_lists[zone_name]`
2. Roll the `randomizer` dice expression
3. Match result to entry `range`
4. Return the entry (prompt, ua_cue, bx_plug) for Claude to narrate
5. If `bx_plug` is present, run BX-PLUG mechanically

### 4. EL-FORGE integration
When Claude runs EL-FORGE and produces a new EL-DEF, write it to `save.encounter_lists[zone_name]` via a new MCP tool (e.g., `update_encounter_list`) or by including it in `apply_llm_judgments`.

### 5. Migration script
One-time script to parse `NSV-ENGINES.txt` and populate the `encounter_lists` section of the current save. Run once, then saves carry EL-DEFs forward.

## BX-PLUG Parsing Notes

Entries have varying BX-PLUG formats:
- `"Run BX-PLUG: reaction roll; if hostile → combat"` + BX stat line
- `"Run BX-PLUG: Save or take 3d6 damage"`
- `"Run BX-PLUG: Skill Check (Athletics) grants +2"`
- Some entries have no BX-PLUG at all
- Some entries have BX stats on the next line: `BX: AC=17, HD=7, hp=35/35, AT=+7, Dmg=3d8, ML=5`

Parse these into structured `bx_plug` objects:
```json
{
  "type": "reaction|save|skill_check|combat",
  "skill": "Athletics|Observation|Healing|null",
  "save_damage": "3d6|5d6|null",
  "hostile_action": "text description|null",
  "stats": "AC=17, HD=7, hp=35/35, AT=+7, Dmg=3d8, ML=5|null"
}
```

## Acceptance Criteria
- [ ] `encounter_lists` section exists in JSON save
- [ ] All 38 EL-DEFs from NSV-ENGINES are present
- [ ] Engine ZONE-FORGE no longer flags "No EL-DEF" for zones with EL-DEFs
- [ ] Engine can roll encounters mechanically from save data
- [ ] New EL-DEFs created by EL-FORGE can be written to save
- [ ] Existing save migration works without data loss (100% fidelity on all other sections)

## Priority
Medium — not blocking gameplay (Claude can still find EL-DEFs via project knowledge) but required for engine self-sufficiency and the long-term architecture goal of LLMs handling creativity, engine handling determinism.
