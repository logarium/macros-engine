"""
MACROS Engine v1.0 — Campaign State Loader
Loads the current Gammaria campaign state (v3.7) into the engine.
Edit this file to update state between sessions.
"""

from models import GameState, Clock, Engine, Zone, EncounterList, EncounterEntry


def load_gammaria_state() -> GameState:
    """Load the current Gammaria campaign state (post-Session 7, v3.7)."""
    state = GameState()

    # ── META ──
    state.session_id = 7
    state.in_game_date = "23 Ilrym"
    state.day_of_month = 23
    state.month = "Ilrym"
    state.pc_zone = "Caras"
    state.campaign_intensity = "medium"
    state.season = "Spring"
    state.seasonal_pressure = "Feed & Seed — food stores depleted; planting season critical"

    # ══════════════════════════════════════════════════
    # CLOCKS
    # ══════════════════════════════════════════════════

    # ── RECOGNITION CLOCKS ──

    state.add_clock(Clock(
        name="Helkar Recognition—Caras",
        owner="Environment/Polity",
        progress=1, max_progress=4,
        advance_bullets=[
            "Thoron takes decisive sovereign action in Caras",
            "Thoron reunites with companion publicly in Caras",
            "Thoron invokes Helkar authority with force/evidence in Caras",
            "Word spreads from another location",
        ],
        halt_conditions=["Thoron leaves Caras for more than 3 days"],
        reduce_conditions=["Thoron acts anonymously or defers to local authority"],
        trigger_on_completion="Caras recognizes Thoron as Helkar; advance Frontier (General) +1",
    ))

    state.add_clock(Clock(
        name="Helkar Recognition—Vornost",
        owner="Environment/Polity",
        progress=2, max_progress=4,
        advance_bullets=[
            "Thoron enters Black Fortress",
            "Thoron reunites with companion in Vornost",
            "Thoron issues orders and they are obeyed",
            "Military intelligence confirms identity",
            "Word spreads",
        ],
        halt_conditions=["Thoron leaves Vornost >3 days"],
        reduce_conditions=["Thoron defers to Joppa", "Garrison questions identity"],
        trigger_on_completion="Vornost recognizes Thoron; Black Fortress opens; advance Frontier (General) +2",
    ))

    state.add_clock(Clock(
        name="Helkar Recognition—Frontier (General)",
        owner="Environment/Polity",
        progress=5, max_progress=6,
        advance_bullets=[
            "Thoron recognized at major location",
            "Companion reunion at frontier post",
            "Stories reach frontier",
            "Thoron demonstrates Helkar knowledge",
        ],
        halt_conditions=["No new recognition events for one full week"],
        reduce_conditions=["Thoron fails publicly", "Companion questions authority"],
        trigger_on_completion="Frontier-wide recognition; authority assumed",
    ))

    state.add_clock(Clock(
        name="Helkar Recognition—Riverwatch/Temple",
        owner="Environment/Polity",
        progress=1, max_progress=4, status="halted",
        advance_bullets=["Reunion in Riverwatch", "Helkar authority invoked", "Lock/customs crisis resolved", "Word spreads"],
        halt_conditions=["Thoron leaves Riverwatch >3 days"],
        trigger_on_completion="Riverwatch institutions recognize Thoron; advance Frontier (General) +1",
        notes="HALTED (>3 days absent, Session 3 Day 4)",
    ))

    state.add_clock(Clock(
        name="Helkar Recognition—Fort Vanguard",
        owner="Environment/Polity",
        progress=4, max_progress=4, status="trigger_fired",
        trigger_fired=True,
        trigger_on_completion="FIRED — Fort Vanguard recognizes Thoron",
        notes="TRG FIRED Session 4; RETIRED Session 4",
    ))

    state.add_clock(Clock(
        name="Helkar Recognition—Seawatch/Riverwatch",
        owner="Environment/Polity",
        progress=1, max_progress=4,
        advance_bullets=["Reunion at Seawatch/Riverwatch", "Port crisis resolved", "Helkar authority invoked", "Word spreads"],
        halt_conditions=["Leaves both regions >7 days"],
        trigger_on_completion="Coastal institutions recognize Thoron; advance Frontier (General) +1",
    ))

    # ── COMPANION REUNION CLOCKS (all fired/retired) ──

    for comp in ["Lalholm", "Suzanne", "Lithoe", "Guldur", "Valania"]:
        state.add_clock(Clock(
            name=f"Companion Reunion—{comp}",
            owner="Thoron (quest)",
            progress=1, max_progress=1, status="trigger_fired",
            trigger_fired=True,
            trigger_on_completion=f"FIRED — {comp} reunited",
        ))

    # ── FACTION CLOCKS ──

    state.add_clock(Clock(
        name="Golden Hind—Assessment of Gammaria",
        owner="Golden Hind Merchants",
        progress=0, max_progress=4,
        advance_bullets=[
            "Lethal enforcement against GH personnel",
            "Seizure/exposure/humiliation of GH assets",
            "Trade restrictions attributable to Helkar policy",
        ],
        halt_conditions=["No direct contact", "External crises divert attention"],
        reduce_conditions=["Successful intimidation without collateral", "Procedural concessions preserving merchant dignity"],
        trigger_on_completion="Coordinated merchant countermove",
    ))

    state.add_clock(Clock(
        name="Doctrine Stress Test",
        owner="Fort Vanguard (Bale)",
        progress=1, max_progress=6,
        advance_bullets=["Patrols deployed", "Ambiguous encounters strain rules"],
        halt_conditions=["Patrols suspended"],
        reduce_conditions=["Correct ID validated publicly"],
        trigger_on_completion="Doctrine brittleness event",
        notes="Vasha dead; Bale now holds this responsibility",
    ))

    state.add_clock(Clock(
        name="Temple of the Sun—Doctrinal Fracture",
        owner="Temple of the Sun",
        progress=20, max_progress=20, status="trigger_fired",
        trigger_fired=True,
        trigger_on_completion="FIRED — Schism irreversible; Ush'n'Elthar and Ush'n'Taalgith split",
        notes="TRG FIRED Session 6 (20th Ilrym)",
    ))

    # ── HIDDEN TEMPLE CLOCKS ──

    state.add_clock(Clock(
        name="Hidden Temple—Demon Ledger",
        owner="Hidden Temple",
        progress=1, max_progress=8,
        advance_bullets=[
            "Knowledgeable NPC confirms demon/fiend-linked presence or activity",
            "Demon-linked artifacts/cults/summons discovered",
        ],
        halt_conditions=["No new evidence for one full week"],
        reduce_conditions=["Demon threat destroyed/banished/sealed with proof"],
        trigger_on_completion="Doctrine priority overrides mercenary work; active hunt posture begins",
        notes="ERROR-CORRECTION-S7-01: retroactive advance from Session 6 (ossuary discovery)",
    ))

    state.add_clock(Clock(
        name="Hidden Temple—Interest in Gammaria",
        owner="Hidden Temple",
        progress=1, max_progress=4,
        advance_bullets=[
            "Credible infernal/demonic signature detected",
            "Contract requests reference demons explicitly",
            "Orcus/Haadis jurisdictional conflict ripples publicly",
        ],
        halt_conditions=["No relevant signals for one full week"],
        reduce_conditions=["Signal disproven or neutralised without Hidden Temple involvement"],
        trigger_on_completion="Sanctioned cell dispatched into Gammaria",
        notes="ERROR-CORRECTION-S7-02: retroactive advance from Session 6",
    ))

    state.add_clock(Clock(
        name="Hidden Temple—Contract Pressure Vector",
        owner="Hidden Temple",
        progress=0, max_progress=6,
        advance_bullets=[
            "Parties seek deniable killers via Caras/Torlec routes",
            "Helkar policy creates enemies seeking removal",
        ],
        halt_conditions=["No contract market activity reaches intermediaries"],
        reduce_conditions=["Procedural off-ramps reduce appetite for murder-for-hire"],
        trigger_on_completion="Contract offer enters play via intermediary (choice-point)",
    ))

    state.add_clock(Clock(
        name="Hidden Temple—Exposure Risk in Caras",
        owner="Hidden Temple",
        progress=0, max_progress=4,
        advance_bullets=[
            "Underlayer contact reused",
            "Evidence/bodies/residue left",
            "Rival counter-surveillance initiates",
        ],
        halt_conditions=["Cell goes dark for one full week"],
        reduce_conditions=["Successful misdirection or clean exfiltration"],
        trigger_on_completion="Exposure event: arrests, blackmail, or forced flight",
    ))

    # ── EXISTENTIAL CLOCKS ──

    state.add_clock(Clock(
        name="Children of the Dead Gods—Binding Degradation",
        owner="Children of Dead Gods",
        progress=11, max_progress=16,
        advance_bullets=[
            "Krovekëan artifact disturbed",
            "Binding site accessed",
            "Corrupted Edhellar increases",
            "Decay",  # <-- cadence bullet
            "Contract signed",
            "Cultist undetected ≥30d",
            "Anyone researches Crystal (psychic alarm)",
            "Orcus advances",
            "Dead Gods' names spoken aloud",
        ],
        halt_conditions=[
            "Names spoken in warding",
            "Ancients Outpost secured",
            "Crystal/Krovekëa truth revealed and proven",
        ],
        reduce_conditions=[
            "Cultist executed", "Artifact sealed", "Alliance forms",
            "Edhellar eliminated", "Contract broken",
            "Counter-sequence applied by Lithoe",
        ],
        trigger_on_completion="Dead God manifests (bound, insane); cult fractures; Orcus +3",
        is_cadence=True,
        cadence_bullet="Decay",
    ))

    state.add_clock(Clock(
        name="Lithoe Counter-Sequence Research",
        owner="Lithoe Wano-Kan",
        progress=7, max_progress=8,
        advance_bullets=[
            "One undisturbed day passes with Lithoe researching at Khuzdukan",
        ],
        halt_conditions=["Lithoe interrupted or forced to relocate"],
        trigger_on_completion="Breakthrough — counter-sequence mapped; can be applied to ward",
        is_cadence=True,
        cadence_bullet="One undisturbed day passes with Lithoe researching at Khuzdukan",
        notes="Lithoe at Khuzdukan; undisturbed; should fire next T&P day",
    ))

    state.add_clock(Clock(
        name="Dimensional Instability—Western Scarps",
        owner="Environment",
        progress=3, max_progress=6,
        advance_bullets=[
            "T&P day passes with Edhellar activity in Scarps",
            "Binding Degradation advances",
        ],
        halt_conditions=["Edhellar eliminated from zone", "Binding stabilised"],
        trigger_on_completion="Dimensional breach event",
    ))

    state.add_clock(Clock(
        name="Deep Tremors—Khuzdukan",
        owner="Environment",
        progress=4, max_progress=6,
        advance_bullets=[
            "Binding Degradation advances",
            "Ward-chamber accessed",
        ],
        halt_conditions=["Counter-sequence applied"],
        trigger_on_completion="Structural collapse risk; Khuzdukan evacuation",
    ))

    state.add_clock(Clock(
        name="Wyvern Territory Dispute",
        owner="Environment",
        progress=4, max_progress=4, status="trigger_fired",
        trigger_fired=True,
        trigger_on_completion="FIRED — Eastern Scarps travel requires escort",
    ))

    # ── ORCUS / SUZANNE CLOCKS ──

    state.add_clock(Clock(
        name="Cult of Orcus—Enigma Crystal Hunt",
        owner="Cult of Orcus",
        progress=3, max_progress=14,
        advance_bullets=[
            "Suzanne investigates Crystal/Enigma Moon lore",
            "Ancient site explored",
            "Orcus cultist interrogates scholar",
            "Dimensional breach studied",
            "Lithoe shares findings with Suzanne",
            "Texts stolen",
            "Tharn-Krovekë consulted",
            "Children advance",
            "Player discovers Crystal location",
        ],
        halt_conditions=["Suzanne chooses Thoron", "All cells destroyed", "Crystal destruction revealed"],
        reduce_conditions=["Cultist killed", "Site sealed", "Suzanne misdirects", "Church purge", "False intel"],
        trigger_on_completion="Cult learns Crystal on Enigma Moon; Orcus demands Suzanne retrieve; spawn loyalty clock",
    ))

    state.add_clock(Clock(
        name="Suzanne Loyalty—Helkar vs Orcus",
        owner="Suzanne",
        progress=0, max_progress=6,
        advance_bullets=[
            "Orcus contact", "Crystal lead",
            "Helkar power witnessed", "Thoron shares trust", "Asked to choose",
        ],
        halt_conditions=["Not in play + no cult contact for one week"],
        reduce_conditions=["Lead disproven", "Thoron demonstrates loyalty", "Intermediary eliminated"],
        trigger_on_completion="Choice-point (gated behind Enigma Crystal Hunt 14/14)",
    ))

    # ── FORT VANGUARD OFFICER CLOCKS ──

    state.add_clock(Clock(
        name="Selde Marr",
        owner="Fort Vanguard",
        progress=0, max_progress=4,
        advance_bullets=["VP outcome 2-4 (clear failure)"],
        halt_conditions=["Patrols suspended"],
        reduce_conditions=["VP outcome 9-11 reduces"],
        trigger_on_completion="Selde Marr's concerns become operational",
    ))

    state.add_clock(Clock(
        name="Arvek Morn",
        owner="Fort Vanguard",
        progress=0, max_progress=4,
        advance_bullets=["VP outcome 2-4 (clear failure)"],
        halt_conditions=["Patrols suspended"],
        reduce_conditions=["VP outcome 9-11 reduces"],
        trigger_on_completion="Arvek Morn's concerns become operational",
    ))

    state.add_clock(Clock(
        name="Henric Bale",
        owner="Fort Vanguard",
        progress=4, max_progress=4, status="retired",
        trigger_on_completion="RETIRED — Bale promoted to Castellan",
        notes="TRG FIRED Session 3; RETIRED Session 4",
    ))

    # ── MISC CLOCKS ──

    state.add_clock(Clock(
        name="Coastal Superstition—Neglected Shrines",
        owner="UA-XX",
        progress=0, max_progress=6,
        advance_bullets=[
            "T&P in coastal zones without observance",
            "Folk warnings dismissed",
        ],
        halt_conditions=["PC leaves zone", "Travel prevented"],
        reduce_conditions=["Shrine acknowledged", "Local guidance followed"],
        trigger_on_completion="Predatory folk manifestation",
    ))

    # ══════════════════════════════════════════════════
    # ENGINES
    # ══════════════════════════════════════════════════

    state.add_engine(Engine(
        name="Vanguard Patrol Doctrine",
        version="VP v3.0",
        status="active",
        zone_scope="Global",
        cadence=True,
        hard_gates=["Fort Vanguard must exist as named Zone"],
        randomizer="2d6",
        linked_clocks=["Doctrine Stress Test", "Selde Marr", "Arvek Morn", "Henric Bale"],
        roll_history=[
            {"date": "5 Ilrym", "roll": 7, "band": "5-7"},
            {"date": "6 Ilrym", "roll": 11, "band": "10-11"},
            {"date": "7 Ilrym", "roll": 3, "band": "2-4"},
            {"date": "8 Ilrym", "roll": 9, "band": "8-9"},
            {"date": "9 Ilrym", "roll": 6, "band": "5-7"},
            {"date": "10 Ilrym", "roll": 8, "band": "8-9"},
            {"date": "11 Ilrym", "roll": 8, "band": "8-9"},
            {"date": "12 Ilrym", "roll": 6, "band": "5-7"},
            {"date": "13 Ilrym", "roll": 7, "band": "5-7"},
            {"date": "14 Ilrym", "roll": 7, "band": "5-7"},
            {"date": "15 Ilrym", "roll": 11, "band": "10-11"},
            {"date": "16 Ilrym", "roll": 3, "band": "2-4"},
            {"date": "17 Ilrym", "roll": 6, "band": "5-7"},
            {"date": "18 Ilrym", "roll": 11, "band": "10-11"},
            {"date": "19 Ilrym", "roll": 6, "band": "5-7"},
            {"date": "20 Ilrym", "roll": 6, "band": "5-7"},
            {"date": "21 Ilrym", "roll": 11, "band": "10-11"},
            {"date": "22 Ilrym", "roll": 5, "band": "5-7"},
            {"date": "23 Ilrym", "roll": 9, "band": "8-9"},
        ],
    ))

    state.add_engine(Engine(
        name="Temple of the Sun — Doctrinal Debate",
        version="TSDD v3.0",
        status="inert",  # Linked clock TRG FIRED
        zone_scope="Temple of the Sun",
        cadence=True,
        hard_gates=["Temple of the Sun must exist as named Zone"],
        linked_clocks=["Temple of the Sun—Doctrinal Fracture"],
    ))

    state.add_engine(Engine(
        name="Hidden Temple — Demon-Hunt Cadence",
        version="HT-DH v3.0",
        status="active",  # Demon Ledger = 1 (activated Session 6 retroactive)
        zone_scope="Any region where demon/fiend evidence exists",
        cadence=True,
        hard_gates=["Demon Ledger >= 1"],
        linked_clocks=[
            "Hidden Temple—Demon Ledger",
            "Hidden Temple—Interest in Gammaria",
            "Hidden Temple—Contract Pressure Vector",
        ],
    ))

    state.add_engine(Engine(
        name="Seasonal Resource Pressure",
        version="SRP v1.0",
        status="active",
        zone_scope="Gammaria (all settlements)",
        cadence=True,
        hard_gates=["Valid in-game date"],
    ))

    # ══════════════════════════════════════════════════
    # ZONES — Full CP network from NSV-ZONES v3.0
    # ══════════════════════════════════════════════════

    state.zones["Barrow Moors"] = Zone(
        name="Barrow Moors", intensity="high",
        crossing_points=[
            {"to": "Forgaard", "name": "Barrows Gate", "tag": "eventful"},
        ],
    )

    state.zones["Blacktooth Forest"] = Zone(
        name="Blacktooth Forest", intensity="moderate",
        controlling_faction="Blacktooth Orcs",
        crossing_points=[
            {"to": "Eastern Scarps", "name": "narrow gulch", "tag": "eventful"},
            {"to": "Eastern Scarps", "name": "Golden Downs", "tag": "slow"},
            {"to": "Grey Plains", "name": "The Claw", "tag": "eventful"},
            {"to": "Khuzduk Hills", "name": "Dwarven Bridge", "tag": None},
        ],
    )

    state.zones["Caras"] = Zone(
        name="Caras", intensity="low",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Grey Plains", "name": "Grey Gate", "tag": None},
            {"to": "Riverwatch", "name": "River Koss Ferry", "tag": None},
        ],
    )

    state.zones["Deep Swamps"] = Zone(
        name="Deep Swamps", intensity="high",
        controlling_faction="Bloodswamp Hobgoblins",
        crossing_points=[
            {"to": "Sea of Birds", "name": "Sunken Shore", "tag": "eventful"},
            {"to": "Sighing Swamps", "name": "broken causeway", "tag": "eventful"},
        ],
    )

    state.zones["East March"] = Zone(
        name="East March", intensity="moderate",
        crossing_points=[
            {"to": "Fort Vanguard", "name": "Old East Road", "tag": None},
            {"to": "Southern Scarps", "name": "game trail", "tag": None},
            {"to": "Floodplain", "name": "eroded slopes", "tag": None},
            {"to": "Khuzduk Peaks", "name": "Dwarven Steps", "tag": None},
        ],
    )

    state.zones["Eastern Scarps"] = Zone(
        name="Eastern Scarps", intensity="moderate",
        controlling_faction="Scarp Watch",
        crossing_points=[
            {"to": "Blacktooth Forest", "name": "narrow gulch", "tag": "eventful"},
            {"to": "Blacktooth Forest", "name": "Golden Downs", "tag": "slow"},
            {"to": "Grey Plains", "name": "poor road", "tag": "eventful"},
            {"to": "Grey Plains", "name": "good road", "tag": "slow"},
            {"to": "Temple of the Sun", "name": "Pilgrim's Walk", "tag": None},
            {"to": "Western Scarps", "name": "Amon's Causeway", "tag": None},
            {"to": "Forgaard", "name": "High Fell", "tag": "eventful"},
        ],
    )

    state.zones["Fisher's Beach"] = Zone(
        name="Fisher's Beach", intensity="low",
        crossing_points=[
            {"to": "Sighing Swamps", "name": "beach trail", "tag": "eventful"},
            {"to": "Sea of Birds", "name": "cold beach", "tag": "eventful"},
            {"to": "Seawatch Ramparts", "name": "Coast Road", "tag": None},
            {"to": "Hinterlands", "name": "windswept trail", "tag": None},
        ],
    )

    state.zones["Floodplain"] = Zone(
        name="Floodplain", intensity="high",
        crossing_points=[
            {"to": "East March", "name": "eroded slopes", "tag": None},
            {"to": "Khuzduk Peaks", "name": "waterfall", "tag": "eventful"},
            {"to": "Outer Wetlands", "name": "River of Stone", "tag": None},
            {"to": "Fort Vanguard", "name": "culvert", "tag": None},
        ],
    )

    state.zones["Forgaard"] = Zone(
        name="Forgaard", intensity="high",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Eastern Scarps", "name": "High Fell", "tag": "eventful"},
            {"to": "Barrow Moors", "name": "Barrows Gate", "tag": None},
        ],
    )

    state.zones["Fort Amon"] = Zone(
        name="Fort Amon", intensity="medium",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Western Scarps", "name": "down Amon's Causeway", "tag": None},
            {"to": "Highfell Forest", "name": "elf path", "tag": None},
        ],
    )

    state.zones["Fort Highguard"] = Zone(
        name="Fort Highguard", intensity="medium",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Hanging Cliffs", "name": "Pinnacle Gate", "tag": None},
            {"to": "Furdach Forest", "name": "high paths", "tag": None},
        ],
    )

    state.zones["Fort Seawatch"] = Zone(
        name="Fort Seawatch", intensity="medium",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "River of Birds", "name": "main canal", "tag": "eventful"},
            {"to": "Riverwatch", "name": "River of Skulls Ferry", "tag": None},
            {"to": "Seawatch Ramparts", "name": "Kraken Gate", "tag": None},
        ],
    )

    state.zones["Fort Vanguard"] = Zone(
        name="Fort Vanguard", intensity="high",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "East March", "name": "Old East Road", "tag": None},
            {"to": "Floodplain", "name": "culvert", "tag": None},
        ],
    )

    state.zones["Furdach"] = Zone(
        name="Furdach", intensity="medium",
        controlling_faction="Gnome Clans of Furdach",
        crossing_points=[
            {"to": "Furdach Forest", "name": "narrow tunnel", "tag": None},
            {"to": "Gloatburrow Hills", "name": "goblin tunnel", "tag": None},
        ],
    )

    state.zones["Furdach Forest"] = Zone(
        name="Furdach Forest", intensity="moderate",
        controlling_faction="Gnome Clans of Furdach",
        crossing_points=[
            {"to": "Furdach", "name": "narrow tunnel", "tag": None},
            {"to": "Gloatburrow Hills", "name": "scree slopes", "tag": None},
            {"to": "Southern Scarps", "name": "easy track", "tag": None},
            {"to": "Fort Highguard", "name": "high paths", "tag": None},
        ],
    )

    state.zones["Gloatburrow Hills"] = Zone(
        name="Gloatburrow Hills", intensity="lethal",
        crossing_points=[
            {"to": "Furdach Forest", "name": "scree slopes", "tag": "eventful"},
            {"to": "Hanging Cliffs", "name": "Conorth's Stair", "tag": "eventful"},
            {"to": "Southern Shore", "name": "broken woodland", "tag": "eventful"},
            {"to": "River of Birds", "name": "River of Skulls", "tag": "eventful"},
            {"to": "Vargol's Reach", "name": "low pass", "tag": "slow"},
            {"to": "Furdach", "name": "goblin tunnel", "tag": None},
        ],
    )

    state.zones["Grey Plains"] = Zone(
        name="Grey Plains", intensity="low",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Vornost", "name": "Dragon-Skull Gate", "tag": None},
            {"to": "Hinterlands", "name": "Merchant's Highway", "tag": None},
            {"to": "Eastern Scarps", "name": "poor road", "tag": "eventful"},
            {"to": "Eastern Scarps", "name": "good road", "tag": "slow"},
            {"to": "Blacktooth Forest", "name": "The Claw", "tag": "eventful"},
            {"to": "Khuzduk Hills", "name": "riverbank", "tag": "slow"},
            {"to": "Khuzduk Hills", "name": "dwarf trail", "tag": "eventful"},
            {"to": "Sighing Swamps", "name": "boggy track", "tag": "eventful"},
        ],
    )

    state.zones["Hanging Cliffs"] = Zone(
        name="Hanging Cliffs", intensity="moderate",
        crossing_points=[
            {"to": "Gloatburrow Hills", "name": "Conorth's Stair", "tag": "eventful"},
            {"to": "Fort Highguard", "name": "Pinnacle Gate", "tag": None},
            {"to": "Furdach Forest", "name": "high paths", "tag": None},
        ],
    )

    state.zones["Highfell Forest"] = Zone(
        name="Highfell Forest", intensity="lethal",
        crossing_points=[
            {"to": "Narrows", "name": "forest tracks", "tag": "eventful"},
            {"to": "Fort Amon", "name": "elf path", "tag": None},
        ],
    )

    state.zones["Hinterlands"] = Zone(
        name="Hinterlands", intensity="low",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Grey Plains", "name": "Merchant's Highway", "tag": "eventful"},
            {"to": "Sighing Swamps", "name": "waterlogged track", "tag": "eventful"},
            {"to": "Fisher's Beach", "name": "windswept trail", "tag": None},
            {"to": "Seawatch Ramparts", "name": "Fishers Causeway", "tag": None},
            {"to": "Vargol's Reach", "name": "Drummer's Bridge", "tag": "eventful"},
        ],
    )

    state.zones["Khuzduk Hills"] = Zone(
        name="Khuzduk Hills", intensity="moderate",
        crossing_points=[
            {"to": "Blacktooth Forest", "name": "Dwarven Bridge", "tag": None},
            {"to": "Sighing Swamps", "name": "crumbling steps", "tag": "eventful"},
            {"to": "Khuzduk Peaks", "name": "cairn path", "tag": None},
            {"to": "Grey Plains", "name": "riverbank", "tag": "slow"},
            {"to": "Grey Plains", "name": "dwarf trail", "tag": "eventful"},
            {"to": "Vornost", "name": "River Koss", "tag": None},
            {"to": "Khuzdukan", "name": "Dwarven Gate", "tag": "eventful"},
        ],
    )

    state.zones["Khuzduk Peaks"] = Zone(
        name="Khuzduk Peaks", intensity="high",
        controlling_faction="Khuzduk Remnant-Wardens",
        crossing_points=[
            {"to": "Khuzduk Hills", "name": "cairn path", "tag": None},
            {"to": "Floodplain", "name": "waterfall", "tag": "eventful"},
            {"to": "East March", "name": "Dwarven Steps", "tag": None},
            {"to": "Khuzdukan", "name": "Dwarven Aqueduct", "tag": None},
        ],
    )

    state.zones["Khuzdukan"] = Zone(
        name="Khuzdukan", intensity="high",
        crossing_points=[
            {"to": "Khuzduk Hills", "name": "Dwarven Gate", "tag": "eventful"},
            {"to": "Khuzduk Peaks", "name": "Dwarven Aqueduct", "tag": None},
        ],
    )

    state.zones["Narrows"] = Zone(
        name="Narrows", intensity="high",
        controlling_faction="Narrows Pathwardens",
        crossing_points=[
            {"to": "Western Scarps", "name": "Amon's Gully", "tag": None},
            {"to": "Highfell Forest", "name": "forest tracks", "tag": "eventful"},
            {"to": "Vargol's Reach", "name": "Havar's Bridge", "tag": "eventful"},
            {"to": "Riverlands", "name": "old Elven road", "tag": None},
        ],
    )

    state.zones["Outer Wetlands"] = Zone(
        name="Outer Wetlands", intensity="medium",
        crossing_points=[
            {"to": "Floodplain", "name": "River of Stone", "tag": None},
        ],
    )

    state.zones["River of Birds"] = Zone(
        name="River of Birds", intensity="low",
        crossing_points=[
            {"to": "Gloatburrow Hills", "name": "River of Skulls", "tag": "eventful"},
            {"to": "Fort Seawatch", "name": "main canal", "tag": "eventful"},
            {"to": "Riverlands", "name": "River of Skulls towpath", "tag": None},
            {"to": "Seawatch Ramparts", "name": "Seawatch Road", "tag": "slow"},
        ],
    )

    state.zones["Riverlands"] = Zone(
        name="Riverlands", intensity="low",
        controlling_faction="Confluence Bargemen",
        crossing_points=[
            {"to": "River of Birds", "name": "River of Skulls towpath", "tag": None},
            {"to": "Vargol's Reach", "name": "tundra trail", "tag": None},
            {"to": "Narrows", "name": "old Elven road", "tag": None},
            {"to": "Riverwatch", "name": "Grand Lock", "tag": None},
        ],
    )

    state.zones["Riverwatch"] = Zone(
        name="Riverwatch", intensity="low",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Riverlands", "name": "Grand Lock", "tag": None},
            {"to": "Caras", "name": "River Koss Ferry", "tag": None},
            {"to": "Fort Seawatch", "name": "River of Skulls Ferry", "tag": None},
        ],
    )

    state.zones["Sea of Birds"] = Zone(
        name="Sea of Birds", intensity="high",
        crossing_points=[
            {"to": "Deep Swamps", "name": "Sunken Shore", "tag": "eventful"},
            {"to": "Southern Shore", "name": "shale beach", "tag": "eventful"},
            {"to": "Fisher's Beach", "name": "cold beach", "tag": "eventful"},
            {"to": "Seawatch Ramparts", "name": "old docks", "tag": "eventful"},
        ],
    )

    state.zones["Seawatch Ramparts"] = Zone(
        name="Seawatch Ramparts", intensity="low",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Fisher's Beach", "name": "Coast Road", "tag": None},
            {"to": "Southern Shore", "name": "South Road", "tag": None},
            {"to": "Sea of Birds", "name": "old docks", "tag": "eventful"},
            {"to": "River of Birds", "name": "Seawatch Road", "tag": "slow"},
            {"to": "Hinterlands", "name": "Fishers Causeway", "tag": None},
            {"to": "Fort Seawatch", "name": "Kraken Gate", "tag": None},
        ],
    )

    state.zones["Sighing Swamps"] = Zone(
        name="Sighing Swamps", intensity="medium",
        crossing_points=[
            {"to": "Deep Swamps", "name": "broken causeway", "tag": "eventful"},
            {"to": "Khuzduk Hills", "name": "crumbling steps", "tag": "eventful"},
            {"to": "Hinterlands", "name": "waterlogged track", "tag": "eventful"},
            {"to": "Grey Plains", "name": "boggy track", "tag": "eventful"},
            {"to": "Fisher's Beach", "name": "beach trail", "tag": "eventful"},
            {"to": "Vornost", "name": "low stairs", "tag": None},
        ],
    )

    state.zones["Southern Scarps"] = Zone(
        name="Southern Scarps", intensity="medium",
        crossing_points=[
            {"to": "East March", "name": "game trail", "tag": None},
            {"to": "Furdach Forest", "name": "easy track", "tag": None},
        ],
    )

    state.zones["Southern Shore"] = Zone(
        name="Southern Shore", intensity="low",
        crossing_points=[
            {"to": "Seawatch Ramparts", "name": "South Road", "tag": None},
            {"to": "Gloatburrow Hills", "name": "broken woodland", "tag": "eventful"},
            {"to": "Sea of Birds", "name": "shale beach", "tag": "eventful"},
        ],
    )

    state.zones["Temple of the Sun"] = Zone(
        name="Temple of the Sun", intensity="low",
        crossing_points=[
            {"to": "Eastern Scarps", "name": "Pilgrim's Walk", "tag": None},
            {"to": "Western Scarps", "name": "Penitent's Way", "tag": None},
        ],
    )

    state.zones["Vallandor Mountains"] = Zone(
        name="Vallandor Mountains", intensity="high",
        crossing_points=[
            {"to": "Whiteagle Keep", "name": "postern gate", "tag": None},
            {"to": "Gloatburrow Hills", "name": "rough trail", "tag": "eventful"},
            {"to": "Vargol's Reach", "name": "steep slope", "tag": "slow"},
        ],
    )

    state.zones["Vargol's Reach"] = Zone(
        name="Vargol's Reach", intensity="medium",
        crossing_points=[
            {"to": "Gloatburrow Hills", "name": "low pass", "tag": "slow"},
            {"to": "Hinterlands", "name": "Drummer's Bridge", "tag": "eventful"},
            {"to": "Narrows", "name": "Havar's Bridge", "tag": "eventful"},
            {"to": "Riverlands", "name": "tundra trail", "tag": None},
            {"to": "Vallandor Mountains", "name": "steep slope", "tag": "slow"},
            {"to": "Whiteagle Keep", "name": "Glaurung's Gate", "tag": None},
        ],
    )

    state.zones["Vornost"] = Zone(
        name="Vornost", intensity="low",
        controlling_faction="Nation of Gammaria",
        crossing_points=[
            {"to": "Sighing Swamps", "name": "low stairs", "tag": None},
            {"to": "Grey Plains", "name": "Dragon-Skull Gate", "tag": None},
            {"to": "Khuzduk Hills", "name": "River Koss", "tag": None},
        ],
    )

    state.zones["Western Scarps"] = Zone(
        name="Western Scarps", intensity="medium",
        controlling_faction="Penitent's Way Wardens",
        crossing_points=[
            {"to": "Eastern Scarps", "name": "Amon's Causeway", "tag": None},
            {"to": "Fort Amon", "name": "down Amon's Causeway", "tag": None},
            {"to": "Narrows", "name": "Amon's Gully", "tag": None},
            {"to": "Temple of the Sun", "name": "Penitent's Way", "tag": None},
        ],
    )

    state.zones["Whiteagle Keep"] = Zone(
        name="Whiteagle Keep", intensity="medium",
        controlling_faction="Ironmask Council",
        crossing_points=[
            {"to": "Vallandor Mountains", "name": "postern gate", "tag": None},
            {"to": "Vargol's Reach", "name": "Glaurung's Gate", "tag": None},
        ],
    )

    return state


if __name__ == "__main__":
    state = load_gammaria_state()
    print(f"Loaded state: Session {state.session_id}, Date: {state.in_game_date}")
    print(f"PC Zone: {state.pc_zone}")
    print(f"Active clocks: {len(state.active_clocks())}")
    print(f"Total clocks: {len(state.clocks)}")
    print(f"Engines: {len(state.engines)}")
    print(f"\nClock summary:")
    for clock in sorted(state.clocks.values(), key=lambda c: c.name):
        status = "🔥" if clock.trigger_fired else ("⏸️" if clock.status == "halted" else "📊")
        print(f"  {status} {clock.name}: {clock.progress}/{clock.max_progress} [{clock.status}]")
